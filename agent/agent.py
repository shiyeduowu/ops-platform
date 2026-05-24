from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import platform
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import psutil

_AGENT_DIR = str(Path(__file__).resolve().parent)
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)
from state_store import DedupCache, LocalStateStore, OffsetStore, fingerprint_for_exception
from stress.runner import StressTestRunner
from remote.shell import ShellExecutor
from remote.file_download import FileDownloader
from remote.deploy import DeployExecutor


AGENT_VERSION = "1.0.0"
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
DEFAULT_ACTIVATION_CODE = "OPS-DEMO"
DEFAULT_CHECK_INTERVAL = 30        # Agent 本地高频检测间隔（30秒）
DEFAULT_HEARTBEAT_INTERVAL = 7200  # 心跳间隔（2小时，仅做存活证明）
DEFAULT_DISK_THRESHOLD = 10


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ops-agent")


def _hardware_fingerprint() -> str:
    parts: list[str] = []
    try:
        parts.append(str(uuid.getnode()))
    except Exception:
        pass
    parts.append(platform.node())
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:64]


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _line_fingerprint(agent_id: str, service_key: str, content: str) -> str:
    raw = f"{agent_id}:{service_key}:{content[:500]}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


class OpsAgent:
    def __init__(self, server_url: str, activation_code: str, data_dir: Path):
        self.bootstrap_url = server_url.rstrip("/")
        self.server_url = self.bootstrap_url
        self.activation_code = activation_code
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.agent_id = ""
        self.secret = ""
        self.hostname = platform.node() or "unknown"
        self.ip = _local_ip()
        self.fingerprint = _hardware_fingerprint()
        self.config_version = "v0"
        self.config: dict[str, Any] = self._default_config()

        self.state_store = LocalStateStore(data_dir / "alert_state.json")
        self.dedup = DedupCache(window_seconds=120, max_entries=3000)
        self.offset_store = OffsetStore(data_dir / "tail_offsets.json")
        self._tail_semaphore: threading.Semaphore | None = None

        self._latest_status: dict[str, Any] = {}
        self._status_lock = threading.Lock()
        self._stack_date_re = re.compile(r"^\d{4}-\d{2}-\d{2}")

        self._credentials_path = data_dir / "agent_credentials.json"
        self._config_cache_path = data_dir / "agent_config_cache.json"
        self._load_credentials()
        self._load_config_cache()

        self.stress_runner = StressTestRunner(self._submit_stress_result)
        self.shell_executor = ShellExecutor(self._submit_remote_command_result)
        self.file_downloader = FileDownloader(self.server_url, self._sign_request, self._submit_file_dist_result)
        self.deploy_executor = DeployExecutor(self.server_url, self._sign_request, self._submit_deploy_result)

    def _default_config(self) -> dict[str, Any]:
        return {
            "port_checks": [],
            "log_keywords": ["ERROR"],
            "disk_threshold": DEFAULT_DISK_THRESHOLD,
            "check_interval_seconds": DEFAULT_CHECK_INTERVAL,
            "heartbeat_interval_seconds": DEFAULT_HEARTBEAT_INTERVAL,
            "log_sources": [],
            "service_catalog": [],
            "windows_services": [],
            "log_discovery": [],
            "stack_date_line_regex": r"^\d{4}-\d{2}-\d{2}",
            "max_concurrent_tails": 48,
            "log_cleanup_enabled": False,
            "log_cleanup_retention_days": 30,
            "log_cleanup_dry_run": True,
            "log_cleanup_interval_seconds": 3600,
        }

    def _load_json(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        # Windows 上文件可能被杀毒软件/索引服务锁定，重试几次
        for attempt in range(5):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt < 4:
                    time.sleep(0.2 * (attempt + 1))
                else:
                    raise

    def _load_credentials(self) -> None:
        data = self._load_json(self._credentials_path)
        self.agent_id = data.get("agent_id", "")
        self.secret = data.get("secret") or data.get("aes_key", "")
        self.server_url = data.get("server_url") or self.server_url
        if self.agent_id and self.secret:
            logger.info("Loaded credentials for agent %s", self.agent_id)

    def _save_credentials(self) -> None:
        self._write_json(
            self._credentials_path,
            {
                "agent_id": self.agent_id,
                "secret": self.secret,
                "server_url": self.server_url,
            },
        )

    def _load_config_cache(self) -> None:
        data = self._load_json(self._config_cache_path)
        cached = data.get("config")
        if isinstance(cached, dict):
            self.config.update(cached)
        if data.get("config_version"):
            self.config_version = str(data["config_version"])

    def _save_config_cache(self) -> None:
        self._write_json(
            self._config_cache_path,
            {
                "config_version": self.config_version,
                "config": self.config,
            },
        )

    def _sign_request(self) -> dict[str, str]:
        timestamp = int(time.time())
        message = f"{self.agent_id}.{timestamp}".encode("utf-8")
        signature = hmac.new(self.secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return {
            "X-Agent-ID": self.agent_id,
            "X-Agent-Signature": signature,
            "X-Agent-Timestamp": str(timestamp),
        }

    def _apply_config(self, config: dict[str, Any], version: str) -> None:
        if config:
            self.config.update(config)
        self.config_version = version or self.config_version
        self._stack_date_re = re.compile(self.config.get("stack_date_line_regex") or r"^\d{4}-\d{2}-\d{2}")
        self._save_config_cache()
        logger.info("Applied config version %s", self.config_version)

    def _port_checks(self) -> list[int]:
        raw = self.config.get("port_checks") or self.config.get("ports_to_monitor") or []
        ports: list[int] = []
        for item in raw:
            try:
                ports.append(int(item))
            except (TypeError, ValueError):
                continue
        return ports

    def _disk_threshold(self) -> float:
        value = self.config.get("disk_threshold", self.config.get("disk_threshold_percent", DEFAULT_DISK_THRESHOLD))
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(DEFAULT_DISK_THRESHOLD)

    def _log_keywords(self) -> list[str]:
        raw = self.config.get("log_keywords") or self.config.get("error_keywords") or []
        return [str(item) for item in raw if str(item)]

    def _interval(self, key: str, fallback: int) -> int:
        try:
            return max(10, int(self.config.get(key, fallback)))
        except (TypeError, ValueError):
            return fallback

    def _service_catalog(self) -> dict[str, dict[str, str]]:
        """Normalize service_catalog into {service_key: {...}} dict."""
        catalog: dict[str, dict[str, str]] = {}
        raw = self.config.get("service_catalog") or []
        if isinstance(raw, dict):
            raw = [{"service_key": k, **(v if isinstance(v, dict) else {"name": str(v)})} for k, v in raw.items()]
        for item in raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("service_key") or item.get("key") or "").strip()
            if not key:
                continue
            catalog[key] = {
                "service_key": key,
                "name": item.get("name") or key,
                "product_line": item.get("product_line") or item.get("product") or "",
                "owner": item.get("owner") or "",
                "description": item.get("description") or "",
            }
        return catalog

    def _port_checks_structured(self) -> list[dict[str, Any]]:
        """Normalize port_checks to support both dict and int formats."""
        checks: list[dict[str, Any]] = []
        seen: set[str] = set()
        for idx, item in enumerate(self.config.get("port_checks") or []):
            if isinstance(item, dict):
                port_raw = item.get("port")
                if port_raw is None:
                    continue
                host = str(item.get("host") or "127.0.0.1")
                port = int(port_raw)
                service_key = str(item.get("service_key") or item.get("service") or "").strip()
                name = str(item.get("name") or item.get("label") or f"{host}:{port}")
                key = f"{host}:{port}:{service_key or idx}"
                if key in seen:
                    continue
                seen.add(key)
                checks.append({
                    "host": host, "port": port, "name": name,
                    "service_key": service_key,
                })
            else:
                port = int(item)
                key = f"127.0.0.1:{port}"
                if key in seen:
                    continue
                seen.add(key)
                checks.append({"host": "127.0.0.1", "port": port, "name": str(port), "service_key": ""})
        return checks

    def _discover_log_sources(self) -> list[dict[str, Any]]:
        """Scan log_discovery config roots for */logs/ subdirectories."""
        out: list[dict[str, Any]] = []
        for block in self.config.get("log_discovery") or []:
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
                out.append({
                    "id": sid,
                    "name": block.get("name_template", "{svc} (auto)").replace("{svc}", svc),
                    "path": str(logs),
                    "glob": block.get("glob", "*.log"),
                    "globs": block.get("globs"),
                    "scan_interval_seconds": scan_iv,
                    "service_key": svc_key,
                })
        return out

    def register(self) -> bool:
        payload = {
            "activation_code": self.activation_code,
            "hostname": self.hostname,
            "ip": self.ip,
            "fingerprint": self.fingerprint,
            "version": AGENT_VERSION,
        }
        try:
            with httpx.Client(timeout=15) as client:
                response = client.post(f"{self.bootstrap_url}/api/v1/agent/register", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.error("Registration failed: %s", exc)
            return False

        self.agent_id = data["agent_id"]
        self.secret = data["secret"]
        self.server_url = data.get("server_url") or self.bootstrap_url
        self.server_url = self.server_url.rstrip("/")
        self._save_credentials()
        logger.info("Registered agent_id=%s server=%s", self.agent_id, self.server_url)
        return True

    def send_heartbeat(self) -> bool:
        with self._status_lock:
            status = dict(self._latest_status)
        if not status:
            status = self.collect_status()

        system = status.get("system", {})
        # 构建 port_check_results 供服务端处理
        port_check_results = []
        for port_str, is_alive in status.get("ports", {}).items():
            port_check_results.append({
                "port": int(port_str),
                "status": "open" if is_alive else "closed",
            })
        metrics = {
            "cpu_percent": system.get("cpu_percent"),
            "memory_percent": system.get("memory_percent"),
            "disk": status.get("disks", []),
            "ports": status.get("ports", {}),
            "port_check_results": port_check_results,
            "hostname": self.hostname,
            "ip": self.ip,
            "java_processes": status.get("java_processes", {}),
            "windows_services": status.get("windows_services", {}),
            "service_catalog": status.get("service_catalog", {}),
        }
        payload = {
            "agent_id": self.agent_id,
            "hostname": self.hostname,
            "ip": self.ip,
            "version": AGENT_VERSION,
            "metrics": metrics,
            "config_version": self.config_version,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self.server_url}/api/v1/agent/heartbeat",
                    json=payload,
                    headers=self._sign_request(),
                )
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning("Heartbeat failed: %s", exc)
            return False

        if data.get("config_changed"):
            self._apply_config(data.get("config") or {}, str(data.get("config_version") or self.config_version))

        upgrade = data.get("upgrade") or {}
        if upgrade.get("need_upgrade"):
            logger.info("Upgrade available: version=%s url=%s", upgrade.get("version"), upgrade.get("upgrade_url"))

        # 处理压测命令
        commands = data.get("commands") or []
        for cmd in commands:
            try:
                logger.info("收到压测命令: test_id=%s type=%s action=%s", cmd.get("test_id"), cmd.get("test_type"), cmd.get("action"))
                self.stress_runner.enqueue_command(cmd)
            except Exception as e:
                logger.error("处理压测命令失败: %s", e)

        # 处理远程命令
        remote_commands = data.get("remote_commands") or []
        for rc in remote_commands:
            try:
                cmd_id = rc.get("command_id")
                cmd_type = rc.get("command_type", "shell")
                cmd_text = rc.get("command_text", "")
                timeout = rc.get("timeout_seconds", 60)
                logger.info("收到远程命令: id=%s type=%s cmd=%s", cmd_id, cmd_type, cmd_text[:80])
                self.shell_executor.execute(cmd_id, cmd_type, cmd_text, timeout)
            except Exception as e:
                logger.error("处理远程命令失败: %s", e)

        # 处理文件分发
        file_distributions = data.get("file_distributions") or []
        for fd in file_distributions:
            try:
                dist_id = fd.get("distribution_id")
                logger.info("收到文件分发: id=%s file=%s", dist_id, fd.get("filename"))
                self.file_downloader.download(
                    distribution_id=dist_id,
                    filename=fd.get("filename", ""),
                    target_path=fd.get("target_path", ""),
                    file_size=fd.get("file_size", 0),
                    checksum_md5=fd.get("checksum_md5", ""),
                    download_token=fd.get("download_token", ""),
                )
            except Exception as e:
                logger.error("处理文件分发失败: %s", e)

        # 处理软件部署
        software_deployments = data.get("software_deployments") or []
        for sd in software_deployments:
            try:
                dep_id = sd.get("deployment_id")
                logger.info("收到软件部署: id=%s software=%s", dep_id, sd.get("installer_filename"))
                self.deploy_executor.deploy(
                    deployment_id=dep_id,
                    installer_filename=sd.get("installer_filename", ""),
                    install_command=sd.get("install_command", ""),
                    install_args=sd.get("install_args"),
                    timeout=sd.get("timeout_seconds", 300),
                    download_token=sd.get("download_token", ""),
                )
            except Exception as e:
                logger.error("处理软件部署失败: %s", e)

        return True

    def _submit_stress_result(
        self, test_id: int, result_status: str, result_data: dict[str, Any] | None, error: str | None = None,
    ) -> bool:
        payload = {
            "test_id": test_id,
            "status": result_status,
            "result_data": result_data,
            "error_message": error,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self.server_url}/api/v1/stress-tests/agent/result",
                    json=payload,
                    headers=self._sign_request(),
                )
                return 200 <= response.status_code < 300
        except Exception as exc:
            logger.warning("Stress test result submit failed: %s", exc)
            return False

    def _submit_deploy_result(
        self, deployment_id: int, phase: str, result_status: str,
        stdout: str | None, stderr: str | None, exit_code: int | None,
        error_message: str | None = None,
    ) -> bool:
        payload = {
            "deployment_id": deployment_id,
            "phase": phase,
            "status": result_status,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "error_message": error_message,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self.server_url}/api/v1/deployments/agent/result",
                    json=payload,
                    headers=self._sign_request(),
                )
                return 200 <= response.status_code < 300
        except Exception as exc:
            logger.warning("Deploy result submit failed: %s", exc)
            return False

    def _submit_file_dist_result(
        self, distribution_id: int, result_status: str, error_message: str | None = None,
    ) -> bool:
        payload = {
            "distribution_id": distribution_id,
            "status": result_status,
            "error_message": error_message,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self.server_url}/api/v1/file-distributions/agent/result",
                    json=payload,
                    headers=self._sign_request(),
                )
                return 200 <= response.status_code < 300
        except Exception as exc:
            logger.warning("File distribution result submit failed: %s", exc)
            return False

    def _submit_remote_command_result(
        self, command_id: int, stdout: str, stderr: str, exit_code: int,
    ) -> bool:
        payload = {
            "command_id": command_id,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self.server_url}/api/v1/remote-commands/agent/result",
                    json=payload,
                    headers=self._sign_request(),
                )
                return 200 <= response.status_code < 300
        except Exception as exc:
            logger.warning("Remote command result submit failed: %s", exc)
            return False

    def send_alert(
        self,
        alert_type: str,
        alert_status: str,
        message: str,
        severity: str = "warning",
        details: dict[str, Any] | None = None,
    ) -> bool:
        status_value = "open" if alert_status == "error" else alert_status
        payload = {
            "agent_id": self.agent_id,
            "type": alert_type,
            "status": status_value,
            "severity": severity,
            "message": message,
            "details": details,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self.server_url}/api/v1/alerts",
                    json=payload,
                    headers=self._sign_request(),
                )
                return 200 <= response.status_code < 300
        except Exception as exc:
            logger.warning("Alert send failed: %s", exc)
            return False

    def send_log(self, service_key: str, content: str) -> bool:
        fingerprint = _line_fingerprint(self.agent_id, service_key, content)
        payload = {
            "agent_id": self.agent_id,
            "service_key": service_key,
            "content": content,
            "fingerprint": fingerprint,
        }
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(
                    f"{self.server_url}/api/v1/logs",
                    json=payload,
                    headers=self._sign_request(),
                )
                return 200 <= response.status_code < 300
        except Exception as exc:
            logger.warning("Log send failed: %s", exc)
            return False

    def check_port(self, port: int, host: str = "127.0.0.1") -> bool:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return True
        except OSError:
            return False

    def check_disk(self) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            if not mount or mount in seen:
                continue
            seen.add(mount)
            try:
                usage = psutil.disk_usage(mount)
                results.append(
                    {
                        "mountpoint": mount,
                        "total_gb": round(usage.total / (1024**3), 2),
                        "free_gb": round(usage.free / (1024**3), 2),
                        "free_percent": round(100 - usage.percent, 2),
                    }
                )
            except OSError:
                continue
        return results

    def get_system_metrics(self) -> dict[str, Any]:
        return {
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "memory_percent": psutil.virtual_memory().percent,
            "hostname": self.hostname,
            "server_ip": self.ip,
        }

    def _check_java_processes(self) -> dict[str, bool]:
        """Check if java.exe processes match service_catalog service_keys."""
        catalog = self._service_catalog()
        if not catalog:
            return {}
        active_java: list[str] = []
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                if proc.info["name"] and "java" in proc.info["name"].lower():
                    cmdline = " ".join(proc.info["cmdline"] or [])
                    active_java.append(cmdline)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return {sk: any(sk in cmd for cmd in active_java) for sk in catalog}

    def _check_windows_services(self) -> dict[str, bool]:
        """Check Windows service status via sc query."""
        names = self.config.get("windows_services") or []
        if sys.platform != "win32" or not names:
            return {}
        result: dict[str, bool] = {}
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        for name in names:
            try:
                cp = subprocess.run(
                    ["sc", "query", str(name)],
                    capture_output=True, text=True, timeout=8,
                    creationflags=creationflags,
                )
                out = (cp.stdout or "") + (cp.stderr or "")
                result[str(name)] = "RUNNING" in out.upper()
            except (OSError, subprocess.TimeoutExpired):
                result[str(name)] = False
        return result

    def collect_status(self) -> dict[str, Any]:
        # Structured port checks (supports dict with host/port/service_key)
        structured_ports = self._port_checks_structured()
        port_results = []
        for p in structured_ports:
            ok = self.check_port(p["port"], p.get("host", "127.0.0.1"))
            port_results.append({**p, "ok": ok})
        ports = {str(p["port"]): p["ok"] for p in port_results if p.get("host", "127.0.0.1") == "127.0.0.1"}

        disks = self.check_disk()
        status = {
            "ports": ports,
            "port_checks": port_results,
            "disks": disks,
            "system": self.get_system_metrics(),
            "java_processes": self._check_java_processes(),
            "windows_services": self._check_windows_services(),
            "service_catalog": self._service_catalog(),
        }
        with self._status_lock:
            self._latest_status = status
        return status

    def evaluate_and_alert(self, status: dict[str, Any]) -> None:
        # Structured port alerts with service_key in state_key
        for p in status.get("port_checks", []):
            host = p.get("host", "127.0.0.1")
            port = p.get("port")
            service_key = p.get("service_key", "")
            target = f"{host}:{port}"
            state_key = f"port:{target}:{service_key}" if service_key else f"port:{target}"
            is_bad = not p.get("ok")
            was_bad = self.state_store.get_state(state_key)
            if is_bad and not was_bad:
                self.state_store.set_state(state_key, True)
                self.send_alert(
                    "port_down", "error",
                    f"Port unavailable: {p.get('name') or target} ({target})",
                    severity="critical",
                    details={"port": port, "host": host, "service_key": service_key},
                )
            elif not is_bad and was_bad:
                self.state_store.set_state(state_key, False)
                self.send_alert(
                    "port_down", "resolved",
                    f"Port recovered: {p.get('name') or target} ({target})",
                    severity="info",
                    details={"port": port, "host": host, "service_key": service_key},
                )

        # Disk alerts
        threshold = self._disk_threshold()
        for disk in status.get("disks", []):
            mount = disk.get("mountpoint", "unknown")
            free_pct = float(disk.get("free_percent", 100))
            state_key = f"disk:{mount}"
            is_low = free_pct < threshold
            was_low = self.state_store.get_state(state_key)
            if is_low and not was_low:
                self.state_store.set_state(state_key, True)
                self.send_alert(
                    "disk_low", "error",
                    f"Disk {mount} free space is {free_pct}%, below threshold {threshold}%",
                    severity="warning",
                    details=disk,
                )
            elif not is_low and was_low:
                self.state_store.set_state(state_key, False)
                self.send_alert(
                    "disk_low", "resolved",
                    f"Disk {mount} free space recovered to {free_pct}%",
                    severity="info",
                    details=disk,
                )

        # Windows service alerts
        for svc_name, is_running in status.get("windows_services", {}).items():
            state_key = f"win_svc:{svc_name}"
            is_bad = not is_running
            was_bad = self.state_store.get_state(state_key)
            if is_bad and not was_bad:
                self.state_store.set_state(state_key, True)
                self.send_alert(
                    "service_down", "error",
                    f"Windows service not running: {svc_name}",
                    severity="critical",
                    details={"service_name": svc_name},
                )
            elif not is_bad and was_bad:
                self.state_store.set_state(state_key, False)
                self.send_alert(
                    "service_down", "resolved",
                    f"Windows service recovered: {svc_name}",
                    severity="info",
                    details={"service_name": svc_name},
                )

        # Java process alerts
        for sk, is_running in status.get("java_processes", {}).items():
            state_key = f"java_proc:{sk}"
            is_bad = not is_running
            was_bad = self.state_store.get_state(state_key)
            if is_bad and not was_bad:
                self.state_store.set_state(state_key, True)
                self.send_alert(
                    "java_process_down", "error",
                    f"Java process not found: {sk}",
                    severity="critical",
                    details={"service_key": sk},
                )
            elif not is_bad and was_bad:
                self.state_store.set_state(state_key, False)
                self.send_alert(
                    "java_process_down", "resolved",
                    f"Java process recovered: {sk}",
                    severity="info",
                    details={"service_key": sk},
                )

    def _tail_file_loop(self, file_path: Path, source: dict[str, Any], keywords: list[str]) -> None:
        """Enhanced tail with stack buffer aggregation and OffsetStore resume."""
        file_key = str(file_path.resolve())
        service_key = str(source.get("service_key") or file_path.stem or "default")
        max_buf = 400
        stack_date_re = self._stack_date_re

        if not file_path.is_file():
            return
        file_size = file_path.stat().st_size
        offset = self.offset_store.get_offset(file_key)
        if offset > file_size:
            offset = 0

        stack_buffer: list[str] = []

        def flush_buffer() -> None:
            if not stack_buffer:
                return
            text = "".join(stack_buffer)
            if any(k in text for k in keywords):
                fp = fingerprint_for_exception(f"{service_key}\n{text}")
                if self.dedup.should_send(fp):
                    self.send_alert(
                        "log_keyword", "error",
                        f"Keyword matched in {service_key}: {text[:300]}",
                        severity="warning",
                        details={"service_key": service_key, "path": file_key},
                    )
            self.send_log(service_key, text)
            stack_buffer.clear()

        try:
            with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                if offset > 0:
                    f.seek(offset)
                while True:
                    line = f.readline()
                    if line:
                        pos = f.tell()
                        self.offset_store.set_offset(file_key, pos)
                        probe = line.lstrip()
                        is_new_record = bool(stack_date_re.match(probe))
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
                        time.sleep(0.5)
        except OSError as exc:
            logger.warning("Failed to tail %s: %s", file_path, exc)

    def _run_tail_job(self, file_path: Path, source: dict[str, Any]) -> None:
        """Semaphore-limited tail thread entry."""
        if not file_path.exists():
            return
        if self._tail_semaphore and not self._tail_semaphore.acquire(blocking=False):
            return
        keywords = self._log_keywords()
        try:
            self._tail_file_loop(file_path, source, keywords)
        finally:
            if self._tail_semaphore:
                self._tail_semaphore.release()

    def _watch_directory_source(self, source: dict[str, Any]) -> None:
        """Periodically glob a directory for new log files and start tails."""
        scan_iv = float(source.get("scan_interval_seconds") or 45)
        root = Path(os.path.expandvars(str(source.get("path", ""))))
        patterns = source.get("globs") or [source.get("glob", "*.log")]
        if isinstance(patterns, str):
            patterns = [patterns]
        tracked: dict[str, Path] = {}
        while True:
            if root.is_dir():
                for pattern in patterns:
                    for fp in root.glob(pattern):
                        if not fp.is_file():
                            continue
                        key = str(fp.resolve())
                        if key not in tracked:
                            tracked[key] = fp
                            threading.Thread(target=self._run_tail_job, args=(fp, source), daemon=True).start()
            time.sleep(max(5, scan_iv))

    def _cleanup_old_logs(self) -> dict[str, int]:
        """Delete log files older than retention_days from all log sources."""
        if not self.config.get("log_cleanup_enabled"):
            return {"deleted": 0, "candidates": 0}
        retention_days = float(self.config.get("log_cleanup_retention_days") or 30)
        dry_run = bool(self.config.get("log_cleanup_dry_run", True))
        cutoff = time.time() - retention_days * 86400
        deleted = 0
        candidates = 0

        all_sources = list(self.config.get("log_sources") or []) + self._discover_log_sources()
        for source in all_sources:
            if not isinstance(source, dict):
                continue
            path_val = source.get("path")
            if not path_val:
                continue
            root = Path(os.path.expandvars(str(path_val)))
            if not root.is_dir():
                continue
            patterns = source.get("globs") or [source.get("glob", "*.log")]
            if isinstance(patterns, str):
                patterns = [patterns]
            for pattern in patterns:
                for fp in root.glob(pattern):
                    if not fp.is_file():
                        continue
                    try:
                        if fp.stat().st_mtime >= cutoff:
                            continue
                        candidates += 1
                        if dry_run:
                            logger.info("[log-cleanup] dry-run would delete %s", fp)
                        else:
                            fp.unlink()
                            deleted += 1
                            logger.info("[log-cleanup] deleted %s", fp)
                    except OSError as exc:
                        logger.warning("[log-cleanup] failed %s: %s", fp, exc)
        return {"deleted": deleted, "candidates": candidates}

    def _log_cleanup_loop(self) -> None:
        interval = max(60, int(self.config.get("log_cleanup_interval_seconds") or 3600))
        while True:
            try:
                result = self._cleanup_old_logs()
                if result["candidates"]:
                    logger.info("Log cleanup: %d candidates, %d deleted", result["candidates"], result["deleted"])
            except Exception:
                logger.exception("Log cleanup error")
            time.sleep(interval)

    def _check_loop(self) -> None:
        logger.info("Check loop started")
        while True:
            try:
                status = self.collect_status()
                self.evaluate_and_alert(status)
            except Exception:
                logger.exception("Check loop error")
            time.sleep(self._interval("check_interval_seconds", DEFAULT_CHECK_INTERVAL))

    def _heartbeat_loop(self) -> None:
        logger.info("Heartbeat loop started")
        while True:
            try:
                self.send_heartbeat()
            except Exception:
                logger.exception("Heartbeat loop error")
            time.sleep(self._interval("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_INTERVAL))

    def _log_tail_loop(self) -> None:
        """Start tail threads for configured log sources and discovered directories."""
        logger.info("Log tail loop started")
        # Initialize semaphore for concurrent tail limit
        max_tails = int(self.config.get("max_concurrent_tails") or 48)
        self._tail_semaphore = threading.Semaphore(max_tails)

        started: set[str] = set()

        while True:
            try:
                # Static log_sources (single files)
                sources = self.config.get("log_sources") or []
                for source in sources:
                    if not isinstance(source, dict):
                        continue
                    path_val = source.get("path")
                    if not path_val:
                        continue
                    fp = Path(str(path_val))
                    key = str(fp.resolve())
                    if key in started:
                        continue
                    if fp.is_dir():
                        # Directory source: start watcher thread
                        started.add(key)
                        threading.Thread(target=self._watch_directory_source, args=(source,), daemon=True).start()
                    elif fp.is_file():
                        started.add(key)
                        threading.Thread(target=self._run_tail_job, args=(fp, source), daemon=True).start()

                # Auto-discovered log directories
                for source in self._discover_log_sources():
                    path_val = source.get("path")
                    if not path_val:
                        continue
                    key = str(Path(path_val).resolve())
                    if key in started:
                        continue
                    started.add(key)
                    threading.Thread(target=self._watch_directory_source, args=(source,), daemon=True).start()

            except Exception:
                logger.exception("Log tail loop error")
            time.sleep(30)

    def run(self) -> None:
        if not self.agent_id or not self.secret:
            logger.info("No credentials found, registering...")
            while not self.register():
                logger.info("Retrying registration in 10s...")
                time.sleep(10)

        self.send_heartbeat()
        threading.Thread(target=self._check_loop, daemon=True).start()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._log_tail_loop, daemon=True).start()
        if self.config.get("log_cleanup_enabled"):
            threading.Thread(target=self._log_cleanup_loop, daemon=True).start()
            logger.info("Log cleanup thread started")
        self.stress_runner.start_loop()
        self._start_local_dashboard()

        while True:
            time.sleep(3600)

    def _start_local_dashboard(self) -> None:
        try:
            from starlette.applications import Starlette
            from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
            from starlette.routing import Route
            from starlette.requests import Request
            import uvicorn

            agent_ref = self

            CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;padding:20px}
.header{display:flex;align-items:center;gap:12px;margin-bottom:24px;flex-wrap:wrap}
.header h1{font-size:20px;font-weight:600}
.header .tag{font-size:11px;padding:3px 8px;border-radius:4px;background:#1e293b;color:#94a3b8}
.nav-link{display:inline-block;padding:6px 16px;background:#1e293b;color:#94a3b8;border-radius:6px;text-decoration:none;font-size:13px;border:1px solid #334155;margin-left:auto}
.nav-link:hover{background:#334155;color:#e2e8f0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}
.card{background:#1e293b;border-radius:12px;padding:16px;border:1px solid #334155}
.card h2{font-size:14px;font-weight:600;margin-bottom:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em}
.item{display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #334155}
.item:last-child{border-bottom:none}
.label{font-size:13px;color:#cbd5e1}
.value{font-size:13px;color:#94a3b8;margin-right:8px}
.badge{font-size:11px;padding:2px 8px;border-radius:4px;color:#fff;font-weight:600}
.empty{font-size:13px;color:#64748b;padding:12px 0;text-align:center}
.metric-bar{height:6px;background:#334155;border-radius:3px;margin-top:4px;overflow:hidden}
.metric-fill{height:100%;border-radius:3px;transition:width 0.3s}
.alert-item{background:#7f1d1d22;border-radius:6px;padding:8px;margin:4px 0}
.footer{margin-top:24px;text-align:center;font-size:12px;color:#475569}
.section{background:#1e293b;border-radius:12px;padding:16px;border:1px solid #334155;margin-bottom:16px}
.section h2{font-size:14px;font-weight:600;margin-bottom:12px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.05em}
.section h3{font-size:13px;font-weight:600;margin:12px 0 6px;color:#cbd5e1}
.form-row{display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap;align-items:center}
.form-row input,.form-row select{background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:6px 10px;border-radius:6px;font-size:13px}
.form-row input:focus{outline:none;border-color:#3b82f6}
.form-row input[type=text]{min-width:120px}
.form-row input.wide{flex:1;min-width:200px}
.btn{padding:6px 14px;border-radius:6px;border:1px solid #334155;background:#1e293b;color:#e2e8f0;font-size:13px;cursor:pointer}
.btn:hover{background:#334155}
.btn.primary{background:#3b82f6;border-color:#3b82f6;color:#fff}
.btn.primary:hover{background:#2563eb}
.btn.danger{color:#ef4444;border-color:#ef444444}
.btn.danger:hover{background:#ef444422}
.btn.sm{padding:3px 8px;font-size:12px}
.tag-box{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:8px}
.tag{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;background:#3b82f6;color:#fff;border-radius:6px;font-size:12px;font-weight:500}
.tag .x{cursor:pointer;opacity:.7;font-size:14px;line-height:1}
.tag .x:hover{opacity:1}
.hint{font-size:11px;color:#64748b;margin-top:2px}
.toggle{display:flex;align-items:center;gap:8px;margin-bottom:8px;font-size:13px;color:#cbd5e1}
.toggle input[type=checkbox]{width:16px;height:16px;accent-color:#3b82f6}
.msg{padding:8px 12px;border-radius:6px;font-size:13px;margin-bottom:12px}
.msg.ok{background:#065f4622;border:1px solid #22c55e44;color:#22c55e}
.msg.err{background:#7f1d1d22;border:1px solid #ef444444;color:#ef4444}
table{width:100%;border-collapse:collapse}
table th{text-align:left;font-size:12px;color:#94a3b8;padding:6px 8px;border-bottom:1px solid #334155;font-weight:600}
table td{padding:6px 8px;border-bottom:1px solid #1e293b}
"""

            def _get_status_dict() -> dict:
                with agent_ref._status_lock:
                    status_data = dict(agent_ref._latest_status)
                return {
                    "agent_id": agent_ref.agent_id,
                    "hostname": agent_ref.hostname,
                    "local_time": int(time.time()),
                    "server_url": agent_ref.server_url,
                    "config_version": agent_ref.config_version,
                    "config": agent_ref.config,
                    "ports": status_data.get("ports", {}),
                    "disks": status_data.get("disks", []),
                    "system": status_data.get("system", {}),
                    "java_processes": status_data.get("java_processes", {}),
                    "windows_services": status_data.get("windows_services", {}),
                    "alert_state": agent_ref.state_store.get_all(),
                }

            def _page(title: str, body: str) -> str:
                return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - {agent_ref.hostname}</title>
<style>{CSS}</style></head><body>
<div class="header">
<h1>{agent_ref.hostname}</h1>
<span class="tag">Agent {agent_ref.agent_id[:12]}...</span>
<span class="tag">v{AGENT_VERSION}</span>
<span class="tag">配置 {agent_ref.config_version}</span>
<a class="nav-link" href="/">仪表盘</a>
<a class="nav-link" href="/config">配置</a>
</div>
{body}
<div class="footer">Agent 本地仪表盘 &middot; {agent_ref.server_url}</div>
</body></html>"""

            async def local_status(request):
                return JSONResponse(_get_status_dict())

            async def local_dashboard(request):
                esc = _esc
                data = _get_status_dict()
                ports_html = ""
                for port, alive in data.get("ports", {}).items():
                    color = "#22c55e" if alive else "#ef4444"
                    label = "开启" if alive else "关闭"
                    ports_html += f'<div class="item"><span class="label">端口 {esc(str(port))}</span><span class="badge" style="background:{color}">{label}</span></div>'
                if not data.get("ports"):
                    ports_html = '<div class="empty">未配置端口</div>'

                disks_html = ""
                for d in data.get("disks", []):
                    free = d.get("free_percent", 0)
                    color = "#22c55e" if free > 20 else ("#f59e0b" if free > 10 else "#ef4444")
                    disks_html += f'<div class="item"><span class="label">{esc(str(d.get("mountpoint","?")))}</span><span class="value">{d.get("free_gb",0)} GB 可用</span><span class="badge" style="background:{color}">{free}%</span></div>'
                if not data.get("disks"):
                    disks_html = '<div class="empty">无磁盘信息</div>'

                sys = data.get("system", {})
                cpu = sys.get("cpu_percent", 0)
                mem = sys.get("memory_percent", 0)
                cpu_color = "#22c55e" if cpu < 70 else ("#f59e0b" if cpu < 90 else "#ef4444")
                mem_color = "#22c55e" if mem < 70 else ("#f59e0b" if mem < 90 else "#ef4444")

                alerts_html = ""
                for k, v in data.get("alert_state", {}).items():
                    if v:
                        alerts_html += f'<div class="item alert-item"><span class="label">{esc(str(k))}</span><span class="badge" style="background:#ef4444">活跃</span></div>'
                if not alerts_html:
                    alerts_html = '<div class="empty">无活跃告警</div>'

                java_html = ""
                for sk, running in data.get("java_processes", {}).items():
                    color = "#22c55e" if running else "#ef4444"
                    label = "运行中" if running else "已停止"
                    java_html += f'<div class="item"><span class="label">{esc(str(sk))}</span><span class="badge" style="background:{color}">{label}</span></div>'
                if not java_html:
                    java_html = '<div class="empty">无 Java 进程</div>'

                winsvc_html = ""
                for name, running in data.get("windows_services", {}).items():
                    color = "#22c55e" if running else "#ef4444"
                    label = "运行中" if running else "已停止"
                    winsvc_html += f'<div class="item"><span class="label">{esc(str(name))}</span><span class="badge" style="background:{color}">{label}</span></div>'
                if not winsvc_html:
                    winsvc_html = '<div class="empty">无 Windows 服务</div>'

                body = f"""
<div class="grid">
<div class="card"><h2>系统</h2>
<div class="item"><span class="label">CPU</span><span class="badge" style="background:{cpu_color}">{cpu}%</span></div>
<div class="metric-bar"><div class="metric-fill" style="width:{cpu}%;background:{cpu_color}"></div></div>
<div class="item"><span class="label">内存</span><span class="badge" style="background:{mem_color}">{mem}%</span></div>
<div class="metric-bar"><div class="metric-fill" style="width:{mem}%;background:{mem_color}"></div></div>
<div class="item"><span class="label">服务器</span><span class="value">{esc(str(data['server_url']))}</span></div>
</div>
<div class="card"><h2>端口</h2>{ports_html}</div>
<div class="card"><h2>磁盘</h2>{disks_html}</div>
<div class="card"><h2>Java 进程</h2>{java_html}</div>
<div class="card"><h2>Windows 服务</h2>{winsvc_html}</div>
<div class="card"><h2>活跃告警</h2>{alerts_html}</div>
</div>
<script>setTimeout(()=>location.reload(),10000)</script>"""
                return HTMLResponse(_page("仪表盘", body))

            # ── Config page ──
            def _esc(s: str) -> str:
                return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

            async def local_config(request: Request):
                cfg = dict(agent_ref.config)
                msg = request.query_params.get("msg", "")
                msg_html = ""
                if msg == "ok":
                    msg_html = '<div class="msg ok">配置保存成功</div>'
                elif msg == "err":
                    msg_html = '<div class="msg err">配置保存失败</div>'

                # Port checks
                ports = cfg.get("port_checks") or []
                port_rows = ""
                for i, p in enumerate(ports):
                    if isinstance(p, dict):
                        port_rows += f'<div class="form-row"><input name="port_host_{i}" value="{_esc(str(p.get("host","127.0.0.1")))}" placeholder="主机" style="width:120px"><input name="port_port_{i}" value="{_esc(str(p.get("port","")))}" placeholder="端口" style="width:80px"><input name="port_sk_{i}" value="{_esc(str(p.get("service_key","")))}" placeholder="服务标识"><button class="btn danger sm" type="button" onclick="this.parentElement.remove()">X</button></div>'
                    else:
                        port_rows += f'<div class="form-row"><input name="port_host_{i}" value="127.0.0.1" placeholder="主机" style="width:120px"><input name="port_port_{i}" value="{_esc(str(p))}" placeholder="端口" style="width:80px"><input name="port_sk_{i}" value="" placeholder="服务标识"><button class="btn danger sm" type="button" onclick="this.parentElement.remove()">X</button></div>'

                # Log sources
                log_srcs = cfg.get("log_sources") or []
                log_rows = ""
                for i, s in enumerate(log_srcs):
                    log_rows += f'<div class="form-row"><input name="log_path_{i}" value="{_esc(str(s.get("path","")))}" placeholder="日志路径" class="wide"><input name="log_sk_{i}" value="{_esc(str(s.get("service_key","")))}" placeholder="服务标识" style="width:120px"><button class="btn danger sm" type="button" onclick="this.parentElement.remove()">X</button></div>'

                # Log keywords
                keywords = cfg.get("log_keywords") or ["ERROR"]
                kw_tags = "".join(f'<span class="tag">{_esc(k)}<span class="x" onclick="this.parentElement.remove()">&times;</span><input type="hidden" name="keywords" value="{_esc(k)}"></span>' for k in keywords)

                # Service catalog
                catalog = cfg.get("service_catalog") or []
                cat_rows = ""
                for i, s in enumerate(catalog):
                    cat_rows += f'''<tr>
<td><input name="cat_sk_{i}" value="{_esc(str(s.get("service_key","")))}" style="width:100%"></td>
<td><input name="cat_name_{i}" value="{_esc(str(s.get("name","")))}" style="width:100%"></td>
<td><input name="cat_pl_{i}" value="{_esc(str(s.get("product_line","")))}" style="width:100%"></td>
<td><input name="cat_owner_{i}" value="{_esc(str(s.get("owner","")))}" style="width:100%"></td>
<td><input name="cat_desc_{i}" value="{_esc(str(s.get("description","")))}" style="width:100%"></td>
<td><button class="btn danger sm" type="button" onclick="this.closest('tr').remove()">X</button></td>
</tr>'''

                # Windows services
                win_svcs = cfg.get("windows_services") or []
                win_tags = "".join(f'<span class="tag">{_esc(s)}<span class="x" onclick="this.parentElement.remove()">&times;</span><input type="hidden" name="winsvc" value="{_esc(s)}"></span>' for s in win_svcs)

                # Log discovery
                discoveries = cfg.get("log_discovery") or []
                disc_rows = ""
                for i, d in enumerate(discoveries):
                    disc_rows += f'''<tr>
<td><input name="disc_root_{i}" value="{_esc(str(d.get("root","")))}" style="width:100%"></td>
<td><input name="disc_glob_{i}" value="{_esc(str(d.get("glob","*.log")))}" style="width:100%"></td>
<td><input name="disc_sk_{i}" value="{_esc(str(d.get("service_key","{folder}")))}" style="width:100%"></td>
<td><input name="disc_prefix_{i}" value="{_esc(str(d.get("id_prefix","")))}" style="width:100%"></td>
<td><input name="disc_iv_{i}" value="{_esc(str(d.get("scan_interval_seconds",45)))}" style="width:80px"></td>
<td><button class="btn danger sm" type="button" onclick="this.closest('tr').remove()">X</button></td>
</tr>'''

                stack_regex_val = _esc(str(cfg.get("stack_date_line_regex", r"^\d{4}-\d{2}-\d{2}")))
                body = f"""
{msg_html}
<form method="POST" action="/config">
<div class="section">
<h2>端口检测</h2>
<div id="port-list">{port_rows}</div>
<button class="btn sm" type="button" onclick="addPort()">+ 添加端口</button>
<h3>日志采集</h3>
<div id="log-list">{log_rows}</div>
<button class="btn sm" type="button" onclick="addLogSrc()">+ 添加日志源</button>
<h3>日志关键词</h3>
<div class="tag-box" id="kw-box">{kw_tags}</div>
<input id="kw-input" placeholder="输入关键词，回车添加" onkeydown="if(event.key==='Enter'){{addKw(event)}}" style="background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:6px 10px;border-radius:6px;font-size:13px;width:200px">
</div>

<div class="section">
<h2>服务目录</h2>
<table>
<tr><th>服务标识</th><th>名称</th><th>产品线</th><th>负责人</th><th>描述</th><th></th></tr>
<tbody id="cat-body">{cat_rows}</tbody>
</table>
<button class="btn sm" type="button" onclick="addCat()">+ 添加服务</button>
<h3>Windows 服务监控</h3>
<div class="tag-box" id="win-box">{win_tags}</div>
<input id="win-input" placeholder="输入服务名，回车添加" onkeydown="if(event.key==='Enter'){{addWin(event)}}" style="background:#0f172a;border:1px solid #334155;color:#e2e8f0;padding:6px 10px;border-radius:6px;font-size:13px;width:200px">
<h3>日志自动发现</h3>
<table>
<tr><th>扫描目录</th><th>文件匹配</th><th>服务标识</th><th>ID 前缀</th><th>扫描间隔(秒)</th><th></th></tr>
<tbody id="disc-body">{disc_rows}</tbody>
</table>
<button class="btn sm" type="button" onclick="addDisc()">+ 添加规则</button>
</div>

<div class="section">
<h2>高级设置</h2>
<div class="form-row">
<span class="label">堆栈日期行正则：</span>
<input name="stack_regex" value="{stack_regex_val}" style="flex:1">
</div>
<div class="form-row">
<span class="label">最大并发 tail 数：</span>
<input name="max_tails" type="number" value="{cfg.get('max_concurrent_tails',48)}" min="1" max="200" style="width:80px">
</div>
<h3>日志清理</h3>
<label class="toggle"><input name="cleanup_enabled" type="checkbox" {"checked" if cfg.get("log_cleanup_enabled") else ""}> 启用日志清理</label>
<div class="form-row">
<span class="label">保留天数：</span>
<input name="cleanup_days" type="number" value="{cfg.get('log_cleanup_retention_days',30)}" min="1" max="365" style="width:80px"> 天
<span class="label" style="margin-left:12px">清理间隔：</span>
<input name="cleanup_interval" type="number" value="{cfg.get('log_cleanup_interval_seconds',3600)}" min="60" max="86400" style="width:80px"> 秒
<label class="toggle" style="margin-left:12px"><input name="cleanup_dry" type="checkbox" {"checked" if cfg.get("log_cleanup_dry_run",True) else ""}> 试运行</label>
</div>
</div>

<div class="section">
<h2>阈值与间隔</h2>
<div class="form-row">
<span class="label">磁盘阈值：</span>
<input name="disk_threshold" type="number" value="{cfg.get('disk_threshold',10)}" min="1" max="99" style="width:80px"> %
<span class="label" style="margin-left:12px">检测间隔：</span>
<input name="check_interval" type="number" value="{cfg.get('check_interval_seconds',30)}" min="10" max="3600" style="width:80px"> 秒
<span class="label" style="margin-left:12px">心跳间隔：</span>
<input name="heartbeat_interval" type="number" value="{cfg.get('heartbeat_interval_seconds',7200)}" min="60" max="86400" style="width:80px"> 秒
</div>
</div>

<div style="text-align:right;margin-top:16px">
<button class="btn primary" type="submit">保存配置</button>
</div>
</form>

<script>
function addPort(){{
  const i=document.querySelectorAll('#port-list .form-row').length;
  const d=document.createElement('div');d.className='form-row';
  d.innerHTML='<input name="port_host_'+i+'" value="127.0.0.1" placeholder="主机" style="width:120px"><input name="port_port_'+i+'" value="" placeholder="端口" style="width:80px"><input name="port_sk_'+i+'" value="" placeholder="服务标识"><button class="btn danger sm" type="button" onclick="this.parentElement.remove()">X</button>';
  document.getElementById('port-list').appendChild(d);
}}
function addLogSrc(){{
  const i=document.querySelectorAll('#log-list .form-row').length;
  const d=document.createElement('div');d.className='form-row';
  d.innerHTML='<input name="log_path_'+i+'" value="" placeholder="日志路径" class="wide"><input name="log_sk_'+i+'" value="" placeholder="服务标识" style="width:120px"><button class="btn danger sm" type="button" onclick="this.parentElement.remove()">X</button>';
  document.getElementById('log-list').appendChild(d);
}}
function addKw(e){{
  e.preventDefault();
  const v=document.getElementById('kw-input').value.trim();
  if(!v)return;
  const s=document.createElement('span');s.className='tag';
  s.innerHTML=v+'<span class="x" onclick="this.parentElement.remove()">&times;</span><input type="hidden" name="keywords" value="'+v.replace(/"/g,'&quot;')+'">';
  document.getElementById('kw-box').appendChild(s);
  document.getElementById('kw-input').value='';
}}
function addWin(e){{
  e.preventDefault();
  const v=document.getElementById('win-input').value.trim();
  if(!v)return;
  const s=document.createElement('span');s.className='tag';
  s.innerHTML=v+'<span class="x" onclick="this.parentElement.remove()">&times;</span><input type="hidden" name="winsvc" value="'+v.replace(/"/g,'&quot;')+'">';
  document.getElementById('win-box').appendChild(s);
  document.getElementById('win-input').value='';
}}
function addCat(){{
  const i=document.querySelectorAll('#cat-body tr').length;
  const tr=document.createElement('tr');
  tr.innerHTML='<td><input name="cat_sk_'+i+'" style="width:100%"></td><td><input name="cat_name_'+i+'" style="width:100%"></td><td><input name="cat_pl_'+i+'" style="width:100%"></td><td><input name="cat_owner_'+i+'" style="width:100%"></td><td><input name="cat_desc_'+i+'" style="width:100%"></td><td><button class="btn danger sm" type="button" onclick="this.closest(&quot;tr&quot;).remove()">X</button></td>';
  document.getElementById('cat-body').appendChild(tr);
}}
function addDisc(){{
  const i=document.querySelectorAll('#disc-body tr').length;
  const tr=document.createElement('tr');
  tr.innerHTML='<td><input name="disc_root_'+i+'" style="width:100%"></td><td><input name="disc_glob_'+i+'" value="*.log" style="width:100%"></td><td><input name="disc_sk_'+i+'" value="{{folder}}" style="width:100%"></td><td><input name="disc_prefix_'+i+'" style="width:100%"></td><td><input name="disc_iv_'+i+'" value="45" style="width:80px"></td><td><button class="btn danger sm" type="button" onclick="this.closest(&quot;tr&quot;).remove()">X</button></td>';
  document.getElementById('disc-body').appendChild(tr);
}}
</script>"""
                return HTMLResponse(_page("配置", body))

            async def save_config(request: Request):
                try:
                    form = await request.form()
                    new_cfg: dict[str, Any] = {}

                    # Port checks
                    ports: list[dict[str, Any]] = []
                    i = 0
                    while f"port_port_{i}" in form:
                        port_val = str(form.get(f"port_port_{i}", "")).strip()
                        if port_val:
                            host = str(form.get(f"port_host_{i}", "127.0.0.1")).strip() or "127.0.0.1"
                            sk = str(form.get(f"port_sk_{i}", "")).strip()
                            ports.append({"host": host, "port": int(port_val), "service_key": sk})
                        i += 1
                    new_cfg["port_checks"] = ports

                    # Log sources
                    logs: list[dict[str, Any]] = []
                    i = 0
                    while f"log_path_{i}" in form:
                        path = str(form.get(f"log_path_{i}", "")).strip()
                        if path:
                            sk = str(form.get(f"log_sk_{i}", "")).strip()
                            logs.append({"path": path, "service_key": sk or Path(path).stem})
                        i += 1
                    new_cfg["log_sources"] = logs

                    # Keywords
                    kws = form.getlist("keywords")
                    new_cfg["log_keywords"] = [str(k).strip() for k in kws if str(k).strip()] or ["ERROR"]

                    # Service catalog
                    catalog: list[dict[str, str]] = []
                    i = 0
                    while f"cat_sk_{i}" in form:
                        sk = str(form.get(f"cat_sk_{i}", "")).strip()
                        if sk:
                            catalog.append({
                                "service_key": sk,
                                "name": str(form.get(f"cat_name_{i}", "")).strip() or sk,
                                "product_line": str(form.get(f"cat_pl_{i}", "")).strip(),
                                "owner": str(form.get(f"cat_owner_{i}", "")).strip(),
                                "description": str(form.get(f"cat_desc_{i}", "")).strip(),
                            })
                        i += 1
                    new_cfg["service_catalog"] = catalog

                    # Windows services
                    winsvcs = form.getlist("winsvc")
                    new_cfg["windows_services"] = [str(s).strip() for s in winsvcs if str(s).strip()]

                    # Log discovery
                    discs: list[dict[str, Any]] = []
                    i = 0
                    while f"disc_root_{i}" in form:
                        root = str(form.get(f"disc_root_{i}", "")).strip()
                        if root:
                            discs.append({
                                "root": root,
                                "glob": str(form.get(f"disc_glob_{i}", "*.log")).strip() or "*.log",
                                "service_key": str(form.get(f"disc_sk_{i}", "{folder}")).strip() or "{folder}",
                                "id_prefix": str(form.get(f"disc_prefix_{i}", "")).strip(),
                                "scan_interval_seconds": int(str(form.get(f"disc_iv_{i}", "45")).strip() or 45),
                            })
                        i += 1
                    new_cfg["log_discovery"] = discs

                    # Advanced
                    new_cfg["stack_date_line_regex"] = str(form.get("stack_regex", r"^\d{4}-\d{2}-\d{2}")).strip()
                    new_cfg["max_concurrent_tails"] = int(str(form.get("max_tails", "48")).strip() or 48)
                    new_cfg["log_cleanup_enabled"] = "cleanup_enabled" in form
                    new_cfg["log_cleanup_retention_days"] = int(str(form.get("cleanup_days", "30")).strip() or 30)
                    new_cfg["log_cleanup_interval_seconds"] = int(str(form.get("cleanup_interval", "3600")).strip() or 3600)
                    new_cfg["log_cleanup_dry_run"] = "cleanup_dry" in form

                    # Thresholds
                    new_cfg["disk_threshold"] = int(str(form.get("disk_threshold", "10")).strip() or 10)
                    new_cfg["check_interval_seconds"] = int(str(form.get("check_interval", "30")).strip() or 30)
                    new_cfg["heartbeat_interval_seconds"] = int(str(form.get("heartbeat_interval", "7200")).strip() or 7200)

                    agent_ref.config.update(new_cfg)
                    agent_ref._save_config_cache()
                    logger.info("通过本地仪表盘更新了配置")
                    return RedirectResponse("/config?msg=ok", status_code=303)
                except Exception as exc:
                    logger.exception("通过本地仪表盘保存配置失败")
                    return RedirectResponse("/config?msg=err", status_code=303)

            local_app = Starlette(routes=[
                Route("/local/status", local_status),
                Route("/", local_dashboard),
                Route("/local", local_dashboard),
                Route("/config", local_config, methods=["GET"]),
                Route("/config", save_config, methods=["POST"]),
            ])

            def _run() -> None:
                uvicorn.run(local_app, host="127.0.0.1", port=17680, log_level="warning")

            threading.Thread(target=_run, daemon=True).start()
            logger.info("Local dashboard at http://127.0.0.1:17680/")
        except ImportError:
            logger.warning("starlette/uvicorn not installed, local dashboard disabled")
        except Exception:
            logger.exception("Failed to start local dashboard")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ops Platform Agent")
    parser.add_argument("--server", default=os.getenv("OPS_SERVER_URL", DEFAULT_SERVER_URL))
    parser.add_argument("--activation-code", default=os.getenv("OPS_ACTIVATION_CODE", DEFAULT_ACTIVATION_CODE))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("OPS_DATA_DIR", ".")))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    activation_code = args.activation_code or DEFAULT_ACTIVATION_CODE
    activation_code = str(activation_code)
    agent = OpsAgent(server_url=args.server, activation_code=activation_code, data_dir=args.data_dir)
    logger.info("Starting agent bootstrap=%s data=%s", args.server, args.data_dir)
    agent.run()


if __name__ == "__main__":
    main()
