"""Tail 偏移持久化与异常去重（Agent 重启断点续传、短时间相同异常合并）。"""

from __future__ import annotations

import atexit
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any


class OffsetStore:
    """按文件路径记录读取字节偏移，JSON 持久化。"""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._last_flush = 0.0
        self.flush_interval = 2.0
        self._load()
        atexit.register(self.flush)

    def _load(self) -> None:
        if self.path.is_file():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def get_offset(self, file_key: str) -> int:
        with self._lock:
            ent = self._data.get(file_key) or {}
            return int(ent.get("offset", 0))

    def set_offset(self, file_key: str, offset: int) -> None:
        with self._lock:
            self._data[file_key] = {"offset": offset, "ts": time.time()}
            self._dirty = True
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        now = time.time()
        if not self._dirty or (now - self._last_flush) < self.flush_interval:
            return
        self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            payload = json.dumps(self._data, ensure_ascii=False, indent=0)
            self._dirty = False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.path)
        self._last_flush = time.time()


class DedupCache:
    """近期相同异常指纹只保留一次上报。"""

    def __init__(self, window_seconds: float = 120.0, max_entries: int = 2000):
        self.window = float(window_seconds)
        self.max_entries = max_entries
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_send(self, fingerprint: str) -> bool:
        now = time.time()
        with self._lock:
            self._prune_locked(now)
            if fingerprint in self._seen:
                return False
            self._seen[fingerprint] = now
            return True

    def _prune_locked(self, now: float) -> None:
        cutoff = now - self.window
        dead = [k for k, t in self._seen.items() if t < cutoff]
        for k in dead:
            del self._seen[k]
        while len(self._seen) > self.max_entries:
            oldest = min(self._seen.items(), key=lambda x: x[1])[0]
            del self._seen[oldest]


def fingerprint_for_exception(text: str, max_len: int = 400) -> str:
    """首行 + 归一化前缀做哈希，忽略堆栈行号波动时可缩短 max_len。"""
    raw = text.strip()[:max_len]
    n = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
    return n
