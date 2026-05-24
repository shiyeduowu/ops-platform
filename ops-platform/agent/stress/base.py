from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Callable

import psutil


class BaseStressRunner(ABC):
    """压测执行器基类"""

    def __init__(self, test_id: int, config: dict[str, Any], report_callback: Callable):
        self.test_id = test_id
        self.config = config
        self._report = report_callback
        self._cancelled = False
        self._running = False
        self._start_time: float | None = None
        self._monitor_thread: threading.Thread | None = None

    def cancel(self) -> None:
        self._cancelled = True

    @abstractmethod
    def run(self) -> dict[str, Any]:
        """执行测试，返回 result_data"""
        ...

    def _start_monitor(self) -> None:
        """启动系统指标监控线程（每秒采集）"""
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name=f"monitor-{self.test_id}",
        )
        self._monitor_thread.start()

    def _stop_monitor(self) -> None:
        self._running = False

    def _monitor_loop(self) -> None:
        """每秒采集 CPU/内存/磁盘/网络指标并上报"""
        net_prev = psutil.net_io_counters()
        time_prev = time.monotonic()

        while self._running and not self._cancelled:
            time.sleep(1)
            try:
                net_cur = psutil.net_io_counters()
                time_cur = time.monotonic()
                dt = max(time_cur - time_prev, 0.001)

                cpu = psutil.cpu_percent(interval=0)
                mem = psutil.virtual_memory()
                net_sent_speed = (net_cur.bytes_sent - net_prev.bytes_sent) / dt
                net_recv_speed = (net_cur.bytes_recv - net_prev.bytes_recv) / dt

                self.report_progress({
                    "monitor": {
                        "cpu_percent": cpu,
                        "memory_percent": mem.percent,
                        "memory_used_mb": round(mem.used / 1024 / 1024),
                        "memory_total_mb": round(mem.total / 1024 / 1024),
                        "net_sent_kbps": round(net_sent_speed / 1024, 1),
                        "net_recv_kbps": round(net_recv_speed / 1024, 1),
                        "timestamp": time.time(),
                    }
                })

                net_prev = net_cur
                time_prev = time_cur
            except Exception:
                pass

    def report_progress(self, result_data: dict[str, Any]) -> None:
        self._report(self.test_id, "running", result_data, None)

    def report_done(self, result_data: dict[str, Any]) -> None:
        self._stop_monitor()
        self._report(self.test_id, "completed", result_data, None)

    def report_error(self, error: str) -> None:
        self._stop_monitor()
        self._report(self.test_id, "failed", None, error)

    def elapsed_seconds(self) -> float:
        if self._start_time is None:
            return 0
        return time.monotonic() - self._start_time
