from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

from stress.base import BaseStressRunner

logger = logging.getLogger("stress.runner")


class StressTestRunner:
    """压测命令分发器 + 生命周期管理"""

    def __init__(self, report_callback: Callable):
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._active: dict[int, BaseStressRunner] = {}
        self._report = report_callback
        self._lock = threading.Lock()

    def enqueue_command(self, cmd: dict[str, Any]) -> None:
        self._queue.put(cmd)

    def start_loop(self) -> None:
        t = threading.Thread(target=self._dispatch_loop, daemon=True, name="stress-dispatch")
        t.start()
        logger.info("压测命令分发循环已启动")

    def _dispatch_loop(self) -> None:
        while True:
            try:
                cmd = self._queue.get(timeout=1)
            except queue.Empty:
                continue

            action = cmd.get("action", "start")
            test_id = cmd.get("test_id")

            if action == "stop":
                with self._lock:
                    runner = self._active.get(test_id)
                if runner:
                    runner.cancel()
                    logger.info(f"已取消压测任务 #{test_id}")
                continue

            # action == "start"
            with self._lock:
                if test_id in self._active:
                    logger.warning(f"压测任务 #{test_id} 已在运行，跳过")
                    continue

            try:
                runner = self._create_runner(cmd)
            except Exception as e:
                logger.error(f"创建压测执行器失败: {e}")
                self._report(test_id, "failed", None, str(e)[:500])
                continue

            with self._lock:
                self._active[test_id] = runner

            t = threading.Thread(
                target=self._run_test, args=(test_id, runner), daemon=True,
                name=f"stress-{test_id}",
            )
            t.start()

    def _create_runner(self, cmd: dict[str, Any]) -> BaseStressRunner:
        test_type = cmd.get("test_type", "")
        config = cmd.get("config", {})
        test_id = cmd["test_id"]

        if test_type == "browser_automation":
            from stress.browser import BrowserStressRunner
            return BrowserStressRunner(test_id, config, self._report)
        elif test_type == "http_api":
            from stress.http_api import HttpApiStressRunner
            return HttpApiStressRunner(test_id, config, self._report)
        else:
            from stress.infra import InfraStressRunner
            return InfraStressRunner(test_id, test_type, config, self._report)

    def _run_test(self, test_id: int, runner: BaseStressRunner) -> None:
        try:
            logger.info(f"开始执行压测任务 #{test_id}")
            self._report(test_id, "running", {"status": "started"}, None)
            runner._start_monitor()
            result = runner.run()
            runner.report_done(result)
            logger.info(f"压测任务 #{test_id} 完成")
        except Exception as e:
            error_msg = str(e)[:2000]
            logger.error(f"压测任务 #{test_id} 失败: {error_msg}")
            runner.report_error(error_msg)
        finally:
            with self._lock:
                self._active.pop(test_id, None)

    def cancel_all(self) -> None:
        with self._lock:
            for runner in self._active.values():
                runner.cancel()
        logger.info("已取消所有压测任务")

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)
