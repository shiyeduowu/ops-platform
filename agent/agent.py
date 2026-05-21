from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path

import psutil
import requests
import yaml

_AGENT_DIR = str(Path(__file__).resolve().parent)
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
from state_store import DedupCache, OffsetStore, fingerprint_for_exception


def _app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _default_config_path() -> Path:
    return _app_base_dir() / "config.yaml"


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw


def _deep_merge_nested(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = _deep_merge_nested(merged[k], v)
        else:
            merged[k] = v
    return merged


def _deep_merge_defaults(cfg: dict, defaults: dict) -> dict:
    return _deep_merge_nested(deepcopy(defaults), cfg or {})


DEFAULTS = {
    "server_url": "http://127.0.0.1:5000",
    "hostname": None,
    "service_catalog": [],
    "services": [],
    "log_sources": [],
    "log_paths": [],
    "log_discovery": [],
    "local_check_interval_seconds": 60,
    "heartbeat_interval_seconds": 7200,
    "report_interval_seconds": 7200,
    "scan_interval_seconds": 45,
    "tail_idle_sleep_seconds": 0.5,
    "stack_date_line_regex": r"^\d{4}-\d{2}-\d{2}",
    "error_keywords": [
        "ERROR",
        "Exception",
        "SEVERE",
        "ORA-",
        "SQLException",
        "OutOfMemoryError",
        "Caused by:",
    ],
    "system": {"disk_path": "C:\\"},
    "tail_resume": {
        "enabled": True,
        "offset_file": "tail_offsets.json",
        "new_file_without_state": "beginning",
    },
    "dedup": {"enabled": True, "window_seconds": 120, "max_entries": 3000},
    "tail_limits": {"max_concurrent_tails": 48},
    "port_checks": [],
    "port_check_timeout_seconds": 0.6,
    "windows_services": [],
    "customer": {"id": "", "name": ""},
    "alerts": {
        "enabled": True,
        "endpoint": "",
        "heartbeat_endpoint": "",
        "token": "",
        "server_ip": "",
        "disk_free_threshold_percent": 10,
        "port_down_alert": True,
        "disk_low_alert": True,
        "queue_file": "alert_queue.jsonl",
        "max_queue_entries": 1000,
        "retry_interval_seconds": 30,
        "state_file": "alert_state.json",
    },
    "log_cleanup": {
        "enabled": False,
        "retention_days": 30,
        "dry_run": True,
        "interval_seconds": 3600,
    },
}

config: dict = {}
CONFIG_PATH: Path = _default_config_path()

SERVER_URL = ""
CHECK_INTERVAL = 5
SCAN_INTERVAL = 45
TAIL_SLEEP = 0.5
STACK_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
ERROR_KEYWORDS: list[str] = []

_state_lock = threading.Lock()
_meta_by_id: dict[str, dict] = {}
_tail_thread_count = 0

offset_store: OffsetStore | None = None
dedup_cache: DedupCache | None = None
tail_semaphore: threading.Semaphore | None = None
_alert_state: dict[str, bool] = {}
_alert_retry_last = 0.0
_latest_status: dict = {}


def update_source_meta(entry: dict) -> None:
    with _state_lock:
        _meta_by_id[entry["id"]] = entry


def list_sources_meta() -> list[dict]:
    with _state_lock:
        return sorted(_meta_by_id.values(), key=lambda x: x["id"])


def normalized_service_catalog() -> dict[str, dict]:
    """Return service metadata keyed by service_key, keeping old services config valid."""
    catalog: dict[str, dict] = {}
    raw = config.get("service_catalog") or []
    if isinstance(raw, dict):
        raw = [{"service_key": k, **(v if isinstance(v, dict) else {"name": str(v)})} for k, v in raw.items()]

    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("service_key") or item.get("key") or item.get("id") or "").strip()
        if not key:
            continue
        catalog[key] = {
            "service_key": key,
            "name": item.get("name") or key,
            "product_line": item.get("product_line") or item.get("product") or "",
            "owner": item.get("owner") or "",
            "description": item.get("description") or "",
        }

    for service_name in config.get("services") or []:
        key = str(service_name)
        catalog.setdefault(
            key,
            {
                "service_key": key,
                "name": key,
                "product_line": "",
                "owner": "",
                "description": "",
            },
        )
    return catalog


def service_display_name(service_key: str) -> str:
    svc = normalized_service_catalog().get(service_key)
    return str((svc or {}).get("name") or service_key)


def _customer_info() -> dict:
    raw = config.get("customer") or {}
    if isinstance(raw, str):
        return {"id": raw, "name": raw}
    return {
        "id": str(raw.get("id") or ""),
        "name": str(raw.get("name") or raw.get("customer_name") or ""),
    }


def _local_server_ip() -> str:
    alert_cfg = config.get("alerts") or {}
    configured = str(alert_cfg.get("server_ip") or "").strip()
    if configured:
        return configured
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


def get_disk_usages() -> list[dict]:
    disks: list[dict] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        mount = part.mountpoint
        if not mount or mount in seen:
            continue
        seen.add(mount)
        try:
            usage = psutil.disk_usage(mount)
        except OSError:
            continue
        disks.append(
            {
                "device": part.device,
                "mountpoint": mount,
                "fstype": part.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "used_percent": usage.percent,
                "free_percent": round(100 - usage.percent, 2),
            }
        )
    return disks


def load_config(explicit_path: Path | None):
    env_path = os.environ.get("OPS_AGENT_CONFIG", "").strip()
    candidates = [
        explicit_path,
        Path(env_path) if env_path else None,
        _default_config_path(),
    ]
    cfg_file = next((p for p in candidates if p and p.is_file()), None)
    if cfg_file is None:
        raise FileNotFoundError(
            "未找到 config.yaml。请将配置文件放在 exe 同目录，或使用 "
            "--config 路径 / 环境变量 OPS_AGENT_CONFIG"
        )
    merged = _deep_merge_defaults(_load_yaml(cfg_file), DEFAULTS)
    if not merged.get("hostname"):
        merged["hostname"] = os.environ.get("COMPUTERNAME", "unknown-host")
    return merged, cfg_file.resolve()


def discover_log_sources() -> list[dict]:
    """在 runner / 多实例目录下自动发现 */logs。"""
    out: list[dict] = []
    for block in config.get("log_discovery") or []:
        root = Path(os.path.expandvars(str(block.get("root", ""))))
        if not root.is_dir():
            continue
        mode = block.get("mode", "direct_child_logs")
        prefix = str(block.get("id_prefix", ""))
        scan_iv = block.get("scan_interval_seconds")
        if mode != "direct_child_logs":
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            logs = child / "logs"
            if not logs.is_dir():
                continue
            svc = child.name
            sid = f"{prefix}{svc}-auto" if prefix else f"{svc}-auto"
            sk_tpl = block.get("service_key")
            if isinstance(sk_tpl, str) and "{folder}" in sk_tpl:
                svc_key = sk_tpl.replace("{folder}", svc)
            elif sk_tpl:
                svc_key = str(sk_tpl)
            else:
                svc_key = svc
            entry = {
                "id": sid,
                "name": block.get("name_template", "{svc} (发现)").replace("{svc}", svc),
                "path": str(logs),
                "glob": block.get("glob", "*.log"),
                "globs": block.get("globs"),
                "scan_interval_seconds": scan_iv,
                "service_key": svc_key,
            }
            out.append(entry)
    return out


def normalized_log_sources():
    raw = config.get("log_sources")
    explicit: list[dict] = []
    if raw:
        for item in raw:
            sid = item.get("id") or item.get("name") or "unknown"
            explicit.append(
                {
                    "id": sid,
                    "name": item.get("name") or sid,
                    "path": item["path"],
                    "glob": item.get("glob"),
                    "globs": item.get("globs"),
                    "scan_interval_seconds": item.get("scan_interval_seconds"),
                    "service_key": item.get("service_key") or item.get("service") or sid,
                    "product_line": item.get("product_line") or item.get("product") or "",
                }
            )
    else:
        for i, p in enumerate(config.get("log_paths") or []):
            explicit.append(
                {
                    "id": f"path-{i}",
                    "name": Path(p).name or p,
                    "path": p,
                    "glob": "*.log",
                    "globs": None,
                    "scan_interval_seconds": None,
                    "service_key": f"path-{i}",
                    "product_line": "",
                }
            )

    seen = {s["id"] for s in explicit}
    for d in discover_log_sources():
        if d["id"] not in seen:
            explicit.append(d)
            seen.add(d["id"])
    return explicit


def patterns_for_source(src: dict) -> list[str]:
    globs = src.get("globs")
    if globs:
        if isinstance(globs, str):
            return [globs]
        return list(globs)
    g = src.get("glob")
    if g:
        return [g]
    return ["*.log"]


def resolve_watch_files(source: dict) -> list[Path]:
    p = Path(os.path.expandvars(str(source["path"])))
    if p.is_file():
        return [p] if p.exists() else []
    if not p.is_dir():
        return []
    found: set = set()
    for pattern in patterns_for_source(source):
        if not pattern:
            continue
        for f in p.glob(pattern):
            if f.is_file():
                found.add(f.resolve())
    return sorted(found)


def _disk_usage_path() -> str:
    sys_cfg = config.get("system")
    if isinstance(sys_cfg, dict):
        return str(sys_cfg.get("disk_path") or "C:\\")
    if isinstance(sys_cfg, str) and sys_cfg.strip():
        return sys_cfg.strip()
    return "C:\\"


def get_system_metrics():
    disk_path = _disk_usage_path()
    try:
        disk_pct = psutil.disk_usage(disk_path).percent
    except OSError:
        disk_pct = 0.0
    disks = get_disk_usages()
    return {
        "cpu": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory().percent,
        "disk": disk_pct,
        "disks": disks,
        "hostname": config["hostname"],
    }


def check_java_processes():
    active_java = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["name"] == "java.exe":
                cmdline = " ".join(proc.info["cmdline"] or [])
                active_java.append(cmdline)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    status = {}
    for service_name in config.get("services") or []:
        status[service_name] = any(service_name in cmd for cmd in active_java)
    return status


def normalized_port_checks() -> list[dict]:
    checks: list[dict] = []
    seen: set[str] = set()
    for idx, item in enumerate(config.get("port_checks") or []):
        if isinstance(item, dict):
            port_raw = item.get("port")
            if port_raw is None:
                continue
            host = str(item.get("host") or "127.0.0.1")
            port = int(port_raw)
            service_key = str(item.get("service_key") or item.get("service") or "").strip()
            name = str(item.get("name") or item.get("label") or f"{host}:{port}")
            key = str(item.get("id") or f"{host}:{port}:{service_key or idx}")
            checks.append(
                {
                    "id": key,
                    "host": host,
                    "port": port,
                    "name": name,
                    "service_key": service_key,
                    "service_name": service_display_name(service_key) if service_key else "",
                    "product_line": item.get("product_line") or item.get("product") or "",
                    "description": item.get("description") or "",
                }
            )
        else:
            port = int(item)
            key = f"127.0.0.1:{port}"
            if key in seen:
                continue
            checks.append(
                {
                    "id": key,
                    "host": "127.0.0.1",
                    "port": port,
                    "name": str(port),
                    "service_key": "",
                    "service_name": "",
                    "product_line": "",
                    "description": "",
                }
            )
            seen.add(key)
    return checks


def check_tcp_ports() -> list[dict]:
    ports = normalized_port_checks()
    timeout = float(config.get("port_check_timeout_seconds") or 0.6)
    result = []
    for item in ports:
        try:
            with socket.create_connection((item["host"], item["port"]), timeout=timeout):
                ok = True
        except OSError:
            ok = False
        result.append({**item, "ok": ok})
    return result


def check_windows_services() -> dict[str, bool]:
    names = config.get("windows_services") or []
    result = {}
    if sys.platform != "win32" or not names:
        return result
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for name in names:
        try:
            cp = subprocess.run(
                ["sc", "query", name],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=creationflags,
            )
            out = (cp.stdout or "") + (cp.stderr or "")
            result[name] = "RUNNING" in out.upper()
        except (OSError, subprocess.TimeoutExpired):
            result[name] = False
    return result


def _alert_endpoint() -> str:
    alert_cfg = config.get("alerts") or {}
    endpoint = str(alert_cfg.get("endpoint") or "").strip()
    if endpoint:
        return endpoint.rstrip("/")
    return f"{SERVER_URL}/alert"


def _heartbeat_endpoint() -> str:
    alert_cfg = config.get("alerts") or {}
    endpoint = str(alert_cfg.get("heartbeat_endpoint") or "").strip()
    if endpoint:
        return endpoint.rstrip("/")
    return f"{SERVER_URL}/heartbeat"


def _alert_queue_path() -> Path:
    alert_cfg = config.get("alerts") or {}
    return _app_base_dir() / str(alert_cfg.get("queue_file") or "alert_queue.jsonl")


def _alert_state_path() -> Path:
    alert_cfg = config.get("alerts") or {}
    return _app_base_dir() / str(alert_cfg.get("state_file") or "alert_state.json")


def load_alert_state() -> None:
    global _alert_state
    path = _alert_state_path()
    if not path.is_file():
        _alert_state = {}
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _alert_state = {}
        return
    if isinstance(raw, dict):
        _alert_state = {str(k): bool(v) for k, v in raw.items()}


def save_alert_state() -> None:
    path = _alert_state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(_alert_state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _alert_headers() -> dict:
    alert_cfg = config.get("alerts") or {}
    token = str(alert_cfg.get("token") or "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Auth-Token"] = token
        headers["X-Ops-Token"] = token
    return headers


def _alert_base_payload(alert_type: str, severity: str, status: str, message: str) -> dict:
    customer = _customer_info()
    now = int(time.time())
    return {
        "event_id": f"{config['hostname']}-{alert_type}-{now}",
        "type": alert_type,
        "severity": severity,
        "status": status,
        "customer_id": customer["id"],
        "customer": customer["name"],
        "hostname": config["hostname"],
        "server_ip": _local_server_ip(),
        "message": message,
        "observed_at": now,
        "config_path": str(CONFIG_PATH),
    }


def _queue_alert(payload: dict) -> None:
    alert_cfg = config.get("alerts") or {}
    max_entries = int(alert_cfg.get("max_queue_entries") or 1000)
    path = _alert_queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            existing = []
    existing.append(json.dumps(payload, ensure_ascii=False))
    existing = existing[-max_entries:]
    path.write_text("\n".join(existing) + "\n", encoding="utf-8")


def _post_alert(payload: dict) -> bool:
    try:
        resp = requests.post(
            _alert_endpoint(),
            json=payload,
            headers=_alert_headers(),
            timeout=8,
        )
        return 200 <= resp.status_code < 300
    except requests.RequestException:
        return False


def send_alert(payload: dict, *, queue_on_fail: bool = True) -> bool:
    alert_cfg = config.get("alerts") or {}
    if not alert_cfg.get("enabled", True):
        return True
    ok = _post_alert(payload)
    if not ok and queue_on_fail:
        _queue_alert(payload)
    return ok


def flush_alert_queue(force: bool = False) -> None:
    global _alert_retry_last
    alert_cfg = config.get("alerts") or {}
    interval = float(alert_cfg.get("retry_interval_seconds") or 30)
    now = time.time()
    if not force and now - _alert_retry_last < interval:
        return
    _alert_retry_last = now

    path = _alert_queue_path()
    if not path.is_file():
        return
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return
    remaining: list[str] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not send_alert(payload, queue_on_fail=False):
            remaining.append(line)
    if remaining:
        path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    else:
        try:
            path.unlink()
        except OSError:
            pass


def _send_state_alert(state_key: str, is_bad: bool, bad_payload: dict, recover_payload: dict) -> None:
    old = _alert_state.get(state_key)
    if old is is_bad:
        return
    _alert_state[state_key] = is_bad
    save_alert_state()
    send_alert(bad_payload if is_bad else recover_payload)


def evaluate_port_alerts(port_results: list[dict]) -> None:
    alert_cfg = config.get("alerts") or {}
    if not alert_cfg.get("port_down_alert", True):
        return
    for p in port_results:
        service_key = p.get("service_key") or ""
        product = p.get("product_line") or ""
        target = f"{p.get('host') or '127.0.0.1'}:{p.get('port')}"
        state_key = f"port:{target}:{service_key}"
        base_bad = _alert_base_payload(
            "port",
            "critical",
            "error",
            f"端口不可用: {p.get('name') or target} {target}",
        )
        base_bad.update(
            {
                "product": product,
                "service_key": service_key,
                "service_name": p.get("service_name") or service_display_name(service_key),
                "port": p.get("port"),
                "details": p,
            }
        )
        base_ok = _alert_base_payload(
            "port",
            "info",
            "resolved",
            f"端口已恢复: {p.get('name') or target} {target}",
        )
        base_ok.update(base_bad | {"type": "port", "severity": "info", "status": "resolved", "message": base_ok["message"], "observed_at": base_ok["observed_at"], "event_id": base_ok["event_id"]})
        _send_state_alert(state_key, not bool(p.get("ok")), base_bad, base_ok)


def evaluate_disk_alerts(disks: list[dict]) -> None:
    alert_cfg = config.get("alerts") or {}
    if not alert_cfg.get("disk_low_alert", True):
        return
    threshold = float(alert_cfg.get("disk_free_threshold_percent") or 10)
    for d in disks:
        mount = d.get("mountpoint") or d.get("device") or "unknown"
        free_pct = float(d.get("free_percent") or 0)
        state_key = f"disk:{mount}"
        base_bad = _alert_base_payload(
            "disk",
            "warning",
            "error",
            f"磁盘空闲容量低于阈值: {mount} 空闲 {free_pct}%",
        )
        base_bad.update(
            {
                "product": "",
                "disk_mount": mount,
                "details": {**d, "threshold_free_percent": threshold},
            }
        )
        base_ok = _alert_base_payload(
            "disk",
            "info",
            "resolved",
            f"磁盘空闲容量已恢复: {mount} 空闲 {free_pct}%",
        )
        base_ok.update(base_bad | {"type": "disk", "severity": "info", "status": "resolved", "message": base_ok["message"], "observed_at": base_ok["observed_at"], "event_id": base_ok["event_id"]})
        _send_state_alert(state_key, free_pct < threshold, base_bad, base_ok)


def content_matches_error(content: str) -> bool:
    return any(k in content for k in ERROR_KEYWORDS)


def send_log(
    content: str,
    source_id: str,
    source_name: str,
    log_file: str,
    service_key: str,
):
    if not content_matches_error(content):
        return
    fp_txt = fingerprint_for_exception(f"{service_key}\n{content}")
    if dedup_cache and not dedup_cache.should_send(fp_txt):
        return
    try:
        requests.post(
            f"{SERVER_URL}/log",
            json={
                "hostname": config["hostname"],
                "source_id": source_id,
                "source_name": source_name,
                "service_key": service_key,
                "log_file": log_file,
                "content": content,
                "time": time.strftime("%H:%M:%S"),
                "fingerprint": hashlib.sha256(content[:800].encode("utf-8", errors="ignore")).hexdigest()[:16],
            },
            timeout=8,
        )
    except requests.RequestException:
        pass


def _initial_seek(f, file_key: str, file_size: int) -> None:
    """优先读持久化 offset；无记录或校验失败则按 new_file_without_state 策略。"""
    tr = config.get("tail_resume") or {}
    mode_default = str(tr.get("new_file_without_state", "beginning"))

    if not tr.get("enabled", True) or offset_store is None:
        f.seek(0, 2) if mode_default == "end" else f.seek(0)
        return

    off = offset_store.get_offset(file_key)
    if off > 0 and off <= file_size:
        f.seek(off)
        return
    if off > file_size:
        f.seek(0)
        return

    f.seek(0, 2) if mode_default == "end" else f.seek(0)


def _tail_file_loop(
    file_path: Path,
    source_id: str,
    source_name: str,
    service_key: str,
):
    file_key = str(file_path.resolve())
    max_buf = int((config.get("tail_limits") or {}).get("max_exception_lines") or 400)

    path_str = str(file_path)
    file_size = file_path.stat().st_size

    tr_enabled = bool((config.get("tail_resume") or {}).get("enabled", True))

    with open(path_str, "r", encoding="utf-8", errors="ignore") as f:
        if tr_enabled and offset_store:
            _initial_seek(f, file_key, file_size)
        else:
            tr = config.get("tail_resume") or {}
            mode = str(tr.get("new_file_without_state", "beginning"))
            f.seek(0, 2) if mode == "end" else f.seek(0)

        stack_buffer: list[str] = []

        def flush_buffer():
            if not stack_buffer:
                return
            text = "".join(stack_buffer)
            if content_matches_error(text):
                send_log(text, source_id, source_name, file_path.name, service_key)
            stack_buffer.clear()

        while True:
            line = f.readline()
            if line:
                pos = f.tell()
                if offset_store and tr_enabled:
                    offset_store.set_offset(file_key, pos)

                probe = line.lstrip()
                is_new_record = bool(STACK_DATE_RE.match(probe))
                if is_new_record:
                    flush_buffer()
                    stack_buffer = [line]
                else:
                    if stack_buffer:
                        stack_buffer.append(line)
                    else:
                        stack_buffer = [line]
                    if len(stack_buffer) > max_buf:
                        flush_buffer()
            else:
                time.sleep(TAIL_SLEEP)


def _run_tail_job(fp: Path, src: dict):
    """Semaphore 限制并发 tail，避免日志文件过多时线程失控。"""
    global _tail_thread_count
    if not fp.exists():
        return
    if tail_semaphore and not tail_semaphore.acquire(blocking=False):
        return
    with _state_lock:
        _tail_thread_count += 1
    sk = src.get("service_key") or src["id"]
    try:
        _tail_file_loop(fp, src["id"], src["name"], sk)
    finally:
        with _state_lock:
            _tail_thread_count -= 1
        if tail_semaphore:
            tail_semaphore.release()


def submit_tail(fp: Path, src: dict):
    threading.Thread(target=_run_tail_job, args=(fp, src), daemon=True).start()


def watch_directory_source(src: dict):
    scan_iv = src.get("scan_interval_seconds")
    if scan_iv is None:
        scan_iv = SCAN_INTERVAL
    tracked: dict[str, Path] = {}

    while True:
        files = resolve_watch_files(src)
        root = Path(os.path.expandvars(str(src["path"])))
        sk = src.get("service_key") or src["id"]
        meta_entry = {
            "id": src["id"],
            "name": src["name"],
            "path": str(root),
            "globs": patterns_for_source(src),
            "watch_files": [str(f) for f in files],
            "service_key": sk,
            "service_name": service_display_name(sk),
            "product_line": src.get("product_line") or "",
        }
        update_source_meta(meta_entry)

        for fp in files:
            key = str(fp.resolve())
            if key not in tracked:
                tracked[key] = fp
                submit_tail(fp, src)

        time.sleep(max(5, float(scan_iv)))


def start_single_file_tail(src: dict, fp: Path) -> None:
    sk = src.get("service_key") or src["id"]
    meta_entry = {
        "id": src["id"],
        "name": src["name"],
        "path": str(fp.resolve()),
        "globs": [fp.name],
        "watch_files": [str(fp.resolve())],
        "service_key": sk,
        "service_name": service_display_name(sk),
        "product_line": src.get("product_line") or "",
    }
    update_source_meta(meta_entry)
    submit_tail(fp, src)


def cleanup_old_logs_once() -> dict:
    cfg = config.get("log_cleanup") or {}
    if not cfg.get("enabled", False):
        return {"deleted": 0, "candidates": 0}
    retention_days = float(cfg.get("retention_days") or 30)
    dry_run = bool(cfg.get("dry_run", True))
    cutoff = time.time() - retention_days * 86400
    deleted = 0
    candidates = 0
    for src in normalized_log_sources():
        root = Path(os.path.expandvars(str(src["path"])))
        if not root.is_dir():
            continue
        for pattern in patterns_for_source(src):
            for fp in root.glob(pattern):
                if not fp.is_file():
                    continue
                try:
                    if fp.stat().st_mtime >= cutoff:
                        continue
                    candidates += 1
                    if dry_run:
                        print(f"[log-cleanup] dry-run would delete {fp}")
                    else:
                        fp.unlink()
                        deleted += 1
                        print(f"[log-cleanup] deleted {fp}")
                except OSError as exc:
                    print(f"[log-cleanup] failed {fp}: {exc}")
    return {"deleted": deleted, "candidates": candidates}


def log_cleanup_loop() -> None:
    cfg = config.get("log_cleanup") or {}
    interval = max(60, float(cfg.get("interval_seconds") or 3600))
    while True:
        cleanup_old_logs_once()
        time.sleep(interval)


def collect_status() -> dict:
    meta = list_sources_meta()
    with _state_lock:
        wcount = _tail_thread_count
    metrics = get_system_metrics()
    ports = check_tcp_ports()
    win_svc = check_windows_services()
    return {
        "metrics": metrics,
        "service_catalog": normalized_service_catalog(),
        "processes": check_java_processes(),
        "log_sources": meta,
        "watcher_count": wcount,
        "config_path": str(CONFIG_PATH),
        "ports": {str(p["port"]): p["ok"] for p in ports if p.get("host") == "127.0.0.1"},
        "port_checks": ports,
        "windows_services": win_svc,
    }


def local_check_loop():
    global _latest_status
    while True:
        status = collect_status()
        metrics = status["metrics"]
        ports = status["port_checks"]
        evaluate_port_alerts(ports)
        evaluate_disk_alerts(metrics.get("disks") or [])
        flush_alert_queue()
        _latest_status = status
        time.sleep(CHECK_INTERVAL)


def send_heartbeat() -> bool:
    global _latest_status
    if not _latest_status:
        _latest_status = collect_status()
    customer = _customer_info()
    payload = {
        "hostname": config["hostname"],
        "server_ip": _local_server_ip(),
        "customer_id": customer["id"],
        "customer": customer["name"],
        "observed_at": int(time.time()),
        "status": _latest_status,
        "summary": {
            "port_total": len(_latest_status.get("port_checks") or []),
            "port_bad": len([p for p in (_latest_status.get("port_checks") or []) if not p.get("ok")]),
            "disk_total": len((_latest_status.get("metrics") or {}).get("disks") or []),
            "disk_bad": len([d for d in ((_latest_status.get("metrics") or {}).get("disks") or []) if float(d.get("free_percent") or 0) < float((config.get("alerts") or {}).get("disk_free_threshold_percent") or 10)]),
        },
    }
    try:
        resp = requests.post(_heartbeat_endpoint(), json=payload, headers=_alert_headers(), timeout=8)
        return 200 <= resp.status_code < 300
    except requests.RequestException:
        return False


def heartbeat_loop():
    interval = int(config.get("heartbeat_interval_seconds") or config.get("report_interval_seconds") or 7200)
    while True:
        ok = send_heartbeat()
        if not ok:
            print("Heartbeat unavailable...")
        time.sleep(max(60, interval))


def report_status():
    while True:
        data = collect_status()
        try:
            requests.post(f"{SERVER_URL}/report", json=data, timeout=8)
        except requests.RequestException:
            print("Server unavailable...")
        time.sleep(max(60, int(config.get("report_interval_seconds") or 7200)))


def start_watchers():
    global offset_store, dedup_cache, tail_semaphore

    tr = config.get("tail_resume") or {}
    if tr.get("enabled", True):
        off_path = _app_base_dir() / str(tr.get("offset_file") or "tail_offsets.json")
        offset_store = OffsetStore(off_path)

    dc = config.get("dedup") or {}
    if dc.get("enabled", True):
        dedup_cache = DedupCache(
            window_seconds=float(dc.get("window_seconds") or 120),
            max_entries=int(dc.get("max_entries") or 3000),
        )

    tl = config.get("tail_limits") or {}
    max_tails = int(tl.get("max_concurrent_tails") or 48)
    tail_semaphore = threading.Semaphore(max_tails)
    load_alert_state()

    sources = normalized_log_sources()
    threads_started = 0

    for src in sources:
        p = Path(os.path.expandvars(str(src["path"])))
        if p.is_file():
            threads_started += 1
            start_single_file_tail(src, p)
        else:
            threads_started += 1
            threading.Thread(
                target=watch_directory_source,
                args=(src,),
                daemon=True,
            ).start()

    if (config.get("log_cleanup") or {}).get("enabled", False):
        threading.Thread(target=log_cleanup_loop, daemon=True).start()

    threading.Thread(target=local_check_loop, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    return threads_started, sources


def apply_runtime_settings(cfg: dict):
    global config, SERVER_URL, CHECK_INTERVAL, SCAN_INTERVAL, TAIL_SLEEP, STACK_DATE_RE, ERROR_KEYWORDS
    config = cfg
    SERVER_URL = str(config["server_url"]).rstrip("/")
    CHECK_INTERVAL = int(config.get("local_check_interval_seconds") or 60)
    SCAN_INTERVAL = int(config.get("scan_interval_seconds") or 45)
    TAIL_SLEEP = float(config.get("tail_idle_sleep_seconds") or 0.5)
    pattern = config.get("stack_date_line_regex") or DEFAULTS["stack_date_line_regex"]
    STACK_DATE_RE = re.compile(pattern)
    ERROR_KEYWORDS = list(config.get("error_keywords") or DEFAULTS["error_keywords"])


def parse_args():
    ap = argparse.ArgumentParser(description="运维 Agent：日志采集与上报")
    ap.add_argument(
        "--config",
        type=Path,
        default=None,
        help="配置文件路径；默认同级 config.yaml，也可用环境变量 OPS_AGENT_CONFIG",
    )
    return ap.parse_args()


def main():
    global CONFIG_PATH
    args = parse_args()
    cfg, CONFIG_PATH = load_config(args.config)
    apply_runtime_settings(cfg)
    n, srcs = start_watchers()
    print(
        f"Agent started: hostname={config['hostname']}, "
        f"config={CONFIG_PATH}, sources={len(srcs)}, offsets={offset_store.path if offset_store else 'off'}"
    )
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
