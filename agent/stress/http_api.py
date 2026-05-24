from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx

from stress.base import BaseStressRunner


class HttpApiStressRunner(BaseStressRunner):
    """HTTP API 压测执行器"""

    def run(self) -> dict[str, Any]:
        self._start_time = time.monotonic()

        targets = self.config.get("targets", [])
        concurrency = min(self.config.get("concurrency", 10), 100)
        total_requests = min(self.config.get("total_requests", 1000), 10000)
        duration_seconds = self.config.get("duration_seconds")
        timeout_seconds = self.config.get("timeout_seconds", 10)

        if not targets:
            raise ValueError("至少需要一个目标 API")

        results: list[dict[str, Any]] = []
        for i, target in enumerate(targets):
            if self._cancelled:
                break
            self.report_progress({
                "status": "running",
                "current_target": target.get("name", f"Target {i+1}"),
                "target_index": i,
                "total_targets": len(targets),
            })
            result = self._run_single_target(target, concurrency, total_requests, duration_seconds, timeout_seconds)
            results.append(result)

        return {
            "targets": results,
            "summary": self._compute_summary(results),
        }

    def _run_single_target(
        self,
        target: dict[str, Any],
        concurrency: int,
        total_requests: int,
        duration_seconds: int | None,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        method = target.get("method", "GET").upper()
        url = target["url"]
        headers = target.get("headers") or {}
        body = target.get("body")
        name = target.get("name", url)

        latencies: list[float] = []
        errors: dict[str, int] = {}
        success_count = 0
        error_count = 0

        start_time = time.monotonic()

        # 使用共享客户端实现连接池
        client = httpx.Client(timeout=timeout_seconds, verify=True, limits=httpx.Limits(
            max_connections=concurrency, max_keepalive_connections=concurrency,
        ))

        def make_request() -> tuple[bool, float, str | None]:
            req_start = time.monotonic()
            try:
                if method == "GET":
                    resp = client.get(url, headers=headers)
                elif method == "POST":
                    resp = client.post(url, headers=headers, json=body)
                elif method == "PUT":
                    resp = client.put(url, headers=headers, json=body)
                elif method == "DELETE":
                    resp = client.delete(url, headers=headers)
                elif method == "PATCH":
                    resp = client.patch(url, headers=headers, json=body)
                else:
                    return False, 0, f"unsupported_method:{method}"

                elapsed = (time.monotonic() - req_start) * 1000
                if resp.status_code >= 400:
                    return False, elapsed, f"http_{resp.status_code}"
                return True, elapsed, None
            except httpx.TimeoutException:
                return False, (time.monotonic() - req_start) * 1000, "timeout"
            except Exception as e:
                return False, (time.monotonic() - req_start) * 1000, type(e).__name__

        # 按时间或请求数控制
        try:
            if duration_seconds:
                end_time = start_time + duration_seconds
                request_count = 0
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = []
                    while time.monotonic() < end_time and not self._cancelled:
                        futures.append(pool.submit(make_request))
                        request_count += 1
                        # 控制提交速率，避免队列爆炸
                        if len(futures) >= concurrency * 2:
                            for f in as_completed(futures[:concurrency]):
                                ok, lat, err = f.result()
                                latencies.append(lat)
                                if ok:
                                    success_count += 1
                                else:
                                    error_count += 1
                                    errors[err or "unknown"] = errors.get(err or "unknown", 0) + 1
                            futures = futures[concurrency:]

                    for f in futures:
                        if self._cancelled:
                            break
                        ok, lat, err = f.result()
                        latencies.append(lat)
                        if ok:
                            success_count += 1
                        else:
                            error_count += 1
                            errors[err or "unknown"] = errors.get(err or "unknown", 0) + 1
            else:
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    futures = [pool.submit(make_request) for _ in range(total_requests)]
                    for i, f in enumerate(as_completed(futures)):
                        if self._cancelled:
                            break
                        ok, lat, err = f.result()
                        latencies.append(lat)
                        if ok:
                            success_count += 1
                        else:
                            error_count += 1
                            errors[err or "unknown"] = errors.get(err or "unknown", 0) + 1
                        if (i + 1) % 100 == 0:
                            self.report_progress({
                                "status": "running",
                                "current_target": name,
                                "completed": i + 1,
                                "total": total_requests,
                            })
        finally:
            client.close()

        elapsed_total = time.monotonic() - start_time
        total = success_count + error_count

        # 计算延迟分布
        latency_stats = {}
        if latencies:
            sorted_lat = sorted(latencies)
            latency_stats = {
                "min_ms": round(sorted_lat[0], 2),
                "max_ms": round(sorted_lat[-1], 2),
                "avg_ms": round(statistics.mean(sorted_lat), 2),
                "p50_ms": round(sorted_lat[len(sorted_lat) // 2], 2),
                "p90_ms": round(sorted_lat[int(len(sorted_lat) * 0.9)], 2),
                "p99_ms": round(sorted_lat[int(len(sorted_lat) * 0.99)], 2),
            }

        return {
            "name": name,
            "method": method,
            "url": url,
            "total_requests": total,
            "success_count": success_count,
            "error_count": error_count,
            "success_rate": round(success_count / max(total, 1) * 100, 1),
            "qps": round(total / max(elapsed_total, 0.001), 1),
            "duration_seconds": round(elapsed_total, 2),
            "latency": latency_stats,
            "errors": errors,
        }

    def _compute_summary(self, targets: list[dict]) -> dict[str, Any]:
        total_requests = sum(t["total_requests"] for t in targets)
        total_success = sum(t["success_count"] for t in targets)
        total_errors = sum(t["error_count"] for t in targets)
        total_duration = max((t["duration_seconds"] for t in targets), default=0)

        return {
            "total_targets": len(targets),
            "total_requests": total_requests,
            "total_success": total_success,
            "total_errors": total_errors,
            "overall_success_rate": round(total_success / max(total_requests, 1) * 100, 1),
            "overall_qps": round(total_requests / max(total_duration, 0.001), 1),
            "duration_seconds": round(total_duration, 2),
        }
