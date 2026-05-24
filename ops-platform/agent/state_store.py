"""Local alert state persistence and exception deduplication."""

from __future__ import annotations

import atexit
import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any


class LocalStateStore:
    """Persists alert state to JSON so Agent restarts don't cause false alerts."""

    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._last_flush = 0.0
        self._flush_interval = 2.0
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

    def get_state(self, key: str) -> bool:
        with self._lock:
            return bool(self._data.get(key, {}).get("is_bad", False))

    def set_state(self, key: str, is_bad: bool) -> None:
        with self._lock:
            self._data[key] = {
                "is_bad": is_bad,
                "updated_at": int(time.time()),
            }
            self._dirty = True
        self._maybe_flush()

    def _maybe_flush(self) -> None:
        now = time.time()
        if not self._dirty or (now - self._last_flush) < self._flush_interval:
            return
        self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._dirty:
                return
            payload = json.dumps(self._data, ensure_ascii=False, indent=2)
            self._dirty = False
            self._write_payload(payload)
        self._last_flush = time.time()

    def _write_payload(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(self.path)
                break
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.2 * (attempt + 1))
                else:
                    raise

    def get_all(self) -> dict:
        with self._lock:
            return dict(self._data)


class DedupCache:
    """Suppress duplicate exceptions within a time window."""

    def __init__(self, window_seconds: float = 120.0, max_entries: int = 3000):
        self.window = window_seconds
        self.max_entries = max_entries
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def should_send(self, fingerprint: str) -> bool:
        now = time.time()
        with self._lock:
            self._prune(now)
            if fingerprint in self._seen:
                return False
            self._seen[fingerprint] = now
            return True

    def _prune(self, now: float) -> None:
        cutoff = now - self.window
        dead = [k for k, t in self._seen.items() if t < cutoff]
        for k in dead:
            del self._seen[k]
        while len(self._seen) > self.max_entries:
            oldest = min(self._seen, key=lambda k: self._seen[k])
            del self._seen[oldest]


class OffsetStore:
    """Persist per-file byte offsets for log tail resume across agent restarts."""

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
            self._write_payload(payload)
        self._last_flush = time.time()

    def _write_payload(self, payload: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(self.path)
                break
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.2 * (attempt + 1))
                else:
                    raise


def fingerprint_for_exception(text: str, max_len: int = 400) -> str:
    raw = text.strip()[:max_len]
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()
