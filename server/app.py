import os
import json
import queue
import re
import sqlite3
import sys
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml
from flask import Flask, jsonify, render_template, request


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _exe_or_project_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _template_folder() -> str:
    br = _bundle_root()
    t = br / "templates"
    if t.is_dir():
        return str(t)
    return str(_exe_or_project_dir() / "templates")


def _load_server_config() -> dict:
    defaults = {
        "host": "0.0.0.0",
        "port": 5000,
        "auth_token": "",
        "database": {"enabled": True, "path": "ops_monitor.db"},
        "monitored_agents": [],
        "default_stale_seconds": 120,
        "deadman": {"enabled": True, "check_interval_seconds": 60, "default_timeout_seconds": 750},
        "webhooks": {
            "enabled": False,
            "timeout_seconds": 8,
            "workers": 2,
            "routes": [],
        },
    }
    env = os.environ.get("OPS_SERVER_CONFIG", "").strip()
    candidates = [
        Path(env) if env else None,
        _exe_or_project_dir() / "server_config.yaml",
    ]
    path = next((p for p in candidates if p and p.is_file()), None)
    if not path:
        return defaults
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    merged = {**defaults, **cfg}
    if isinstance(cfg.get("database"), dict):
        merged["database"] = {**defaults["database"], **cfg["database"]}
    if isinstance(cfg.get("webhooks"), dict):
        merged["webhooks"] = {**defaults["webhooks"], **cfg["webhooks"]}
    if isinstance(cfg.get("deadman"), dict):
        merged["deadman"] = {**defaults["deadman"], **cfg["deadman"]}
    return merged


def _load_server_listen():
    cfg = _load_server_config()
    host = str(cfg.get("host", "0.0.0.0"))
    port = int(cfg.get("port", 5000))
    return host, port


app = Flask(__name__, template_folder=_template_folder())


@app.after_request
def cors_api(response):
    if request.path.startswith("/api/"):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


server_data = {}
error_logs = deque(maxlen=2000)
alert_logs = deque(maxlen=2000)
webhook_delivery_logs = deque(maxlen=2000)
debug_webhook_logs = deque(maxlen=200)
agent_last_seen = {}
webhook_queue: queue.Queue = queue.Queue()
_webhook_workers_started = False
_webhook_workers_lock = threading.Lock()
_deadman_started = False
_deadman_lock = threading.Lock()
_agent_online_state: dict[str, bool] = {}

METRIC_HISTORY_LEN = 36
metrics_history = defaultdict(
    lambda: {"cpu": deque(maxlen=METRIC_HISTORY_LEN), "mem": deque(maxlen=METRIC_HISTORY_LEN)}
)

log_stats = {
    "by_service": defaultdict(int),
    "by_source": defaultdict(int),
    "by_host": defaultdict(int),
    "total": 0,
}
# 按分钟聚合错误条数，供趋势图
trend_by_minute: deque = deque(maxlen=90)
_current_trend_minute: int | None = None
_current_trend_count: int = 0


def _db_path() -> Path | None:
    cfg = _load_server_config()
    db_cfg = cfg.get("database") or {}
    if not db_cfg.get("enabled", True):
        return None
    path = Path(str(db_cfg.get("path") or "ops_monitor.db"))
    if not path.is_absolute():
        path = _exe_or_project_dir() / path
    return path


def _init_db() -> None:
    path = _db_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL,
                customer TEXT,
                product TEXT,
                hostname TEXT,
                server_ip TEXT,
                service_key TEXT,
                service_name TEXT,
                port INTEGER,
                disk_mount TEXT,
                message TEXT,
                observed_at INTEGER,
                received_at INTEGER NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_received_at ON alerts(received_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_hostname ON alerts(hostname)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_event_id ON alerts(event_id)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webhook_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_id INTEGER,
                event_id TEXT,
                route_name TEXT NOT NULL,
                target_url TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                request_json TEXT,
                response_status INTEGER,
                response_text TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_event_id ON webhook_deliveries(event_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON webhook_deliveries(status)")


def _save_alert(payload: dict) -> int | None:
    path = _db_path()
    if path is None:
        return None
    _init_db()
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO alerts (
                event_id, type, severity, status, customer, product, hostname, server_ip,
                service_key, service_name, port, disk_mount, message, observed_at,
                received_at, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload.get("event_id"),
                payload.get("type") or "unknown",
                payload.get("severity") or "warning",
                payload.get("status") or "open",
                payload.get("customer"),
                payload.get("product"),
                payload.get("hostname"),
                payload.get("server_ip"),
                payload.get("service_key"),
                payload.get("service_name"),
                payload.get("port"),
                payload.get("disk_mount"),
                payload.get("message"),
                payload.get("observed_at"),
                payload.get("received_at"),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return int(cur.lastrowid)


def _save_webhook_delivery(delivery: dict) -> int | None:
    path = _db_path()
    if path is None:
        return None
    _init_db()
    now = int(time.time())
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO webhook_deliveries (
                alert_id, event_id, route_name, target_url, status, attempts,
                last_error, request_json, response_status, response_text,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery.get("alert_id"),
                delivery.get("event_id"),
                delivery.get("route_name"),
                delivery.get("target_url"),
                delivery.get("status"),
                int(delivery.get("attempts") or 0),
                delivery.get("last_error"),
                json.dumps(delivery.get("request") or {}, ensure_ascii=False),
                delivery.get("response_status"),
                delivery.get("response_text"),
                delivery.get("created_at") or now,
                delivery.get("updated_at") or now,
            ),
        )
        return int(cur.lastrowid)


def _token_allowed() -> bool:
    token = str((_load_server_config().get("auth_token") or "")).strip()
    if not token:
        return True
    return request.headers.get("Auth-Token") == token or request.headers.get("X-Ops-Token") == token


def _mark_seen(hostname: str, payload: dict | None = None) -> None:
    if not hostname:
        return
    agent_last_seen[hostname] = {
        "last_seen": int(time.time()),
        "server_ip": (payload or {}).get("server_ip") or "",
        "customer": (payload or {}).get("customer") or "",
        "product": (payload or {}).get("product") or "",
    }


def _monitored_status() -> list[dict]:
    cfg = _load_server_config()
    deadman = cfg.get("deadman") or {}
    default_stale = int(deadman.get("default_timeout_seconds") or cfg.get("default_stale_seconds") or 750)
    monitored = cfg.get("monitored_agents") or cfg.get("agents") or []
    rows = []
    for item in monitored:
        if not isinstance(item, dict):
            continue
        hostname = str(item.get("hostname") or "").strip()
        if not hostname:
            continue
        stale_seconds = int(item.get("stale_seconds") or default_stale)
        seen = agent_last_seen.get(hostname)
        if not seen:
            status = "missing"
            last_seen = None
            age = None
        else:
            last_seen = seen["last_seen"]
            age = int(time.time()) - int(last_seen)
            status = "stale" if age > stale_seconds else "ok"
        rows.append(
            {
                "hostname": hostname,
                "customer": item.get("customer") or (seen or {}).get("customer") or "",
                "product": item.get("product") or (seen or {}).get("product") or "",
                "server_ip": item.get("server_ip") or (seen or {}).get("server_ip") or "",
                "stale_seconds": stale_seconds,
                "last_seen": last_seen,
                "age_seconds": age,
                "status": status,
            }
        )
    return rows


def _value_for_path(payload: dict, path: str):
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return ""
    return "" if cur is None else cur


def _render_template(text: str, payload: dict) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1).strip()
        return str(_value_for_path(payload, key))

    return re.sub(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}", repl, str(text))


def _match_value(expected, actual) -> bool:
    if expected in (None, "", "*"):
        return True
    if isinstance(expected, list):
        return any(_match_value(item, actual) for item in expected)
    return str(expected) == str(actual or "")


def _route_matches(route: dict, payload: dict) -> bool:
    match = route.get("match") or {}
    if not isinstance(match, dict):
        return True
    for key, expected in match.items():
        if not _match_value(expected, _value_for_path(payload, key)):
            return False
    return True


def _build_webhook_request(route: dict, payload: dict) -> dict:
    req_cfg = route.get("request") or {}
    method = str(req_cfg.get("method") or "POST").upper()
    url = _render_template(str(req_cfg.get("url") or ""), payload)
    headers = {
        str(k): _render_template(str(v), payload)
        for k, v in (req_cfg.get("headers") or {}).items()
    }
    body_template = req_cfg.get("body_template")
    if body_template is None:
        body = json.dumps(
            {
                "title": f"{payload.get('severity', 'warning')} {payload.get('type', 'alert')}",
                "content": payload.get("message") or "",
                "payload": payload,
            },
            ensure_ascii=False,
        )
    else:
        body = _render_template(str(body_template), payload)
    return {"method": method, "url": url, "headers": headers, "body": body}


def _enqueue_webhooks(payload: dict, alert_id: int | None) -> None:
    cfg = _load_server_config().get("webhooks") or {}
    if not cfg.get("enabled", False):
        return
    _ensure_webhook_workers()
    for route in cfg.get("routes") or []:
        if not isinstance(route, dict) or not route.get("enabled", True):
            continue
        if not _route_matches(route, payload):
            continue
        req = _build_webhook_request(route, payload)
        if not req.get("url"):
            continue
        webhook_queue.put(
            {
                "alert_id": alert_id,
                "payload": payload,
                "route_name": route.get("name") or "unnamed",
                "request": req,
            }
        )


def _record_delivery(delivery: dict) -> None:
    delivery["updated_at"] = int(time.time())
    webhook_delivery_logs.appendleft(delivery)
    _save_webhook_delivery(delivery)


def _handle_alert(payload: dict) -> tuple[int | None, int]:
    payload["received_at"] = int(time.time())
    payload.setdefault("event_id", f"{payload.get('hostname')}-{payload.get('type')}-{payload.get('status')}-{payload['received_at']}")
    alert_logs.appendleft(payload)
    _mark_seen(payload.get("hostname") or "", payload)
    alert_id = _save_alert(payload)
    _enqueue_webhooks(payload, alert_id)
    return alert_id, webhook_queue.qsize()


def _send_webhook(item: dict) -> dict:
    cfg = _load_server_config().get("webhooks") or {}
    timeout = float(cfg.get("timeout_seconds") or 8)
    req = item["request"]
    body_bytes = str(req.get("body") or "").encode("utf-8")
    headers = dict(req.get("headers") or {})
    headers.setdefault("Content-Type", "application/json")
    started = int(time.time())
    delivery = {
        "alert_id": item.get("alert_id"),
        "event_id": item.get("payload", {}).get("event_id"),
        "route_name": item.get("route_name"),
        "target_url": req.get("url"),
        "status": "pending",
        "attempts": 1,
        "request": req,
        "created_at": started,
        "updated_at": started,
    }
    try:
        http_req = Request(req.get("url"), data=body_bytes, headers=headers, method=req.get("method") or "POST")
        with urlopen(http_req, timeout=timeout) as resp:
            text = resp.read(4000).decode("utf-8", errors="replace")
            delivery.update(
                {
                    "status": "success" if 200 <= resp.status < 300 else "failed",
                    "response_status": resp.status,
                    "response_text": text,
                }
            )
    except HTTPError as exc:
        text = exc.read(4000).decode("utf-8", errors="replace")
        delivery.update(
            {
                "status": "failed",
                "response_status": exc.code,
                "response_text": text,
                "last_error": str(exc),
            }
        )
    except (OSError, URLError, TimeoutError) as exc:
        delivery.update({"status": "failed", "last_error": str(exc)})
    return delivery


def _webhook_worker_loop() -> None:
    while True:
        item = webhook_queue.get()
        try:
            try:
                delivery = _send_webhook(item)
            except Exception as exc:
                now = int(time.time())
                req = item.get("request") or {}
                delivery = {
                    "alert_id": item.get("alert_id"),
                    "event_id": (item.get("payload") or {}).get("event_id"),
                    "route_name": item.get("route_name") or "unknown",
                    "target_url": req.get("url") or "",
                    "status": "failed",
                    "attempts": 1,
                    "last_error": f"worker error: {exc}",
                    "request": req,
                    "created_at": now,
                    "updated_at": now,
                }
            _record_delivery(delivery)
        finally:
            webhook_queue.task_done()


def _ensure_webhook_workers() -> None:
    global _webhook_workers_started
    with _webhook_workers_lock:
        if _webhook_workers_started:
            return
        cfg = _load_server_config().get("webhooks") or {}
        workers = max(1, int(cfg.get("workers") or 2))
        for i in range(workers):
            threading.Thread(target=_webhook_worker_loop, name=f"webhook-worker-{i+1}", daemon=True).start()
        _webhook_workers_started = True


def _deadman_loop() -> None:
    while True:
        cfg = _load_server_config()
        deadman = cfg.get("deadman") or {}
        interval = max(10, int(deadman.get("check_interval_seconds") or 60))
        now = int(time.time())
        for row in _monitored_status():
            hostname = row["hostname"]
            is_offline = row["status"] in ("missing", "stale")
            old = _agent_online_state.get(hostname)
            if old is None:
                _agent_online_state[hostname] = not is_offline
                continue
            if is_offline and old is not False:
                _agent_online_state[hostname] = False
                timeout = row.get("stale_seconds") or (deadman.get("default_timeout_seconds") or 750)
                payload = {
                    "hostname": hostname,
                    "server_ip": row.get("server_ip") or "",
                    "customer": row.get("customer") or "",
                    "product": row.get("product") or "",
                    "type": "offline",
                    "status": "error",
                    "severity": "critical",
                    "message": f"服务器失联: {hostname} 超过 {timeout} 秒未上报心跳",
                    "observed_at": now,
                    "details": row,
                }
                _handle_alert(payload)
            elif not is_offline and old is False:
                _agent_online_state[hostname] = True
        time.sleep(interval)


def _ensure_deadman() -> None:
    global _deadman_started
    with _deadman_lock:
        if _deadman_started:
            return
        cfg = _load_server_config()
        if not (cfg.get("deadman") or {}).get("enabled", True):
            return
        threading.Thread(target=_deadman_loop, name="deadman-monitor", daemon=True).start()
        _deadman_started = True


def _bump_trend():
    global _current_trend_minute, _current_trend_count
    m = int(time.time() // 60)
    if _current_trend_minute is None:
        _current_trend_minute = m
        _current_trend_count = 1
        return
    if m != _current_trend_minute:
        trend_by_minute.append(
            {"minute": _current_trend_minute, "count": _current_trend_count}
        )
        _current_trend_minute = m
        _current_trend_count = 1
    else:
        _current_trend_count += 1


def _stats_snapshot():
    return {
        "total": log_stats["total"],
        "by_service": dict(log_stats["by_service"]),
        "by_source": dict(log_stats["by_source"]),
        "by_host": dict(log_stats["by_host"]),
        "trend": list(trend_by_minute)
        + (
            [{"minute": _current_trend_minute, "count": _current_trend_count}]
            if _current_trend_minute is not None
            else []
        ),
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/report", methods=["POST"])
def receive_report():
    if not _token_allowed():
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    data = request.get_json(force=True, silent=True) or {}
    metrics = data.get("metrics") or {}
    hostname = metrics.get("hostname")
    if not hostname:
        return jsonify({"status": "error", "message": "missing hostname"}), 400

    m = metrics_history[hostname]
    if "cpu" in metrics:
        m["cpu"].append(metrics["cpu"])
    if "memory" in metrics:
        m["mem"].append(metrics["memory"])

    server_data[hostname] = data
    _mark_seen(hostname, data)
    return {"status": "ok"}


@app.route("/heartbeat", methods=["POST"])
def receive_heartbeat():
    if not _token_allowed():
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    payload = request.get_json(force=True, silent=True) or {}
    hostname = payload.get("hostname")
    if not hostname:
        return jsonify({"status": "error", "message": "missing hostname"}), 400

    status_payload = payload.get("status") or {}
    if status_payload:
        server_data[hostname] = status_payload
        metrics = status_payload.get("metrics") or {}
        m = metrics_history[hostname]
        if "cpu" in metrics:
            m["cpu"].append(metrics["cpu"])
        if "memory" in metrics:
            m["mem"].append(metrics["memory"])

    _mark_seen(hostname, payload)
    old = _agent_online_state.get(hostname)
    _agent_online_state[hostname] = True
    if old is False:
        recovered = {
            "hostname": hostname,
            "server_ip": payload.get("server_ip") or "",
            "customer": payload.get("customer") or "",
            "product": payload.get("product") or "",
            "type": "offline",
            "status": "resolved",
            "severity": "info",
            "message": f"服务器已恢复心跳: {hostname}",
            "observed_at": int(time.time()),
        }
        _handle_alert(recovered)
    return {"status": "ok", "server_time": int(time.time())}


@app.route("/log", methods=["POST"])
def receive_log():
    if not _token_allowed():
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    payload = request.get_json(force=True, silent=True) or {}
    error_logs.appendleft(payload)
    _mark_seen(payload.get("hostname") or "", payload)

    log_stats["total"] += 1
    h = payload.get("hostname") or "?"
    sk = payload.get("service_key") or payload.get("source_id") or "?"
    sid = payload.get("source_id") or "?"
    log_stats["by_host"][h] += 1
    log_stats["by_service"][sk] += 1
    log_stats["by_source"][sid] += 1
    _bump_trend()

    return {"status": "ok"}


@app.route("/alert", methods=["POST"])
def receive_alert():
    if not _token_allowed():
        return jsonify({"status": "error", "message": "unauthorized"}), 401
    payload = request.get_json(force=True, silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "invalid json"}), 400
    if not payload.get("type") or not payload.get("hostname"):
        return jsonify({"status": "error", "message": "missing type or hostname"}), 400

    _handle_alert(payload)
    return {"status": "ok", "event_id": payload.get("event_id"), "queued_webhooks": webhook_queue.qsize()}


@app.route("/debug/webhook", methods=["POST"])
def debug_webhook():
    payload = request.get_json(force=True, silent=True)
    if payload is None:
        payload = {"raw": request.get_data(as_text=True)}
    row = {
        "received_at": int(time.time()),
        "headers": {k: v for k, v in request.headers.items()},
        "payload": payload,
    }
    debug_webhook_logs.appendleft(row)
    return {"status": "ok", "received": row}


@app.route("/api/status")
def get_status():
    history = {
        h: {"cpu": list(v["cpu"]), "mem": list(v["mem"])}
        for h, v in metrics_history.items()
    }
    return jsonify(
        {
            "servers": server_data,
            "logs": list(error_logs),
            "alerts": list(alert_logs),
            "monitored": _monitored_status(),
            "webhook_deliveries": list(webhook_delivery_logs),
            "debug_webhooks": list(debug_webhook_logs),
            "webhook_queue_size": webhook_queue.qsize(),
            "history": history,
            "stats": _stats_snapshot(),
        }
    )


def main():
    _init_db()
    if (_load_server_config().get("webhooks") or {}).get("enabled", False):
        _ensure_webhook_workers()
    _ensure_deadman()
    host, port = _load_server_listen()
    try:
        from waitress import serve
    except ImportError:
        print(
            "waitress is not installed; falling back to Flask development server. "
            "Install waitress to remove the production warning."
        )
        app.run(host=host, port=port)
        return

    print(f"ops-server listening on http://{host}:{port}")
    serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()
