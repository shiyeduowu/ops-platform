from __future__ import annotations

import math
import multiprocessing
import os
import platform
import socket
import subprocess
import tempfile
import time
from typing import Any

import psutil

from stress.base import BaseStressRunner


class InfraStressRunner(BaseStressRunner):
    """基础设施压测执行器（网络/磁盘/CPU/内存）"""

    def __init__(self, test_id: int, test_type: str, config: dict[str, Any], report_callback):
        super().__init__(test_id, config, report_callback)
        self.test_type = test_type

    def run(self) -> dict[str, Any]:
        self._start_time = time.monotonic()
        dispatch = {
            "network_bandwidth": self._test_network_bandwidth,
            "network_latency": self._test_network_latency,
            "network_packet_loss": self._test_network_packet_loss,
            "disk_io": self._test_disk_io,
            "cpu_stress": self._test_cpu_stress,
            "memory_stress": self._test_memory_stress,
        }
        fn = dispatch.get(self.test_type)
        if fn is None:
            raise ValueError(f"未知的测试类型: {self.test_type}")
        return fn()

    # ──────────────── 网络压测 ────────────────

    def _test_network_bandwidth(self) -> dict[str, Any]:
        target = self.config["target_host"]
        duration = min(self.config.get("duration_seconds", 10), 60)
        streams = min(self.config.get("parallel_streams", 1), 8)

        # 优先 iperf3
        if self._has_command("iperf3"):
            return self._iperf3_bandwidth(target, duration, streams)

        # 降级：纯 Python socket 测量
        return self._socket_bandwidth(target, duration)

    def _iperf3_bandwidth(self, target: str, duration: int, streams: int) -> dict[str, Any]:
        cmd = ["iperf3", "-c", target, "-t", str(duration), "-P", str(streams), "-J"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
        if proc.returncode != 0:
            raise RuntimeError(f"iperf3 失败: {proc.stderr[:500]}")
        import json
        data = json.loads(proc.stdout)
        bps = data["end"]["sum_sent"]["bits_per_second"]
        return {
            "bandwidth_mbps": round(bps / 1_000_000, 2),
            "duration_seconds": duration,
            "bytes_transferred": data["end"]["sum_sent"]["bytes"],
            "tool": "iperf3",
        }

    def _socket_bandwidth(self, target: str, duration: int) -> dict[str, Any]:
        """纯 Python 带宽测试（需目标有 iperf3 服务端或开放端口）"""
        port = int(self.config.get("target_port", 5201))
        chunk_size = 65536
        total_bytes = 0
        end_time = time.monotonic() + duration

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((target, port))
            data = b"\x00" * chunk_size
            while time.monotonic() < end_time and not self._cancelled:
                sent = sock.send(data)
                total_bytes += sent
            sock.close()
        except Exception as e:
            raise RuntimeError(f"Socket 连接失败: {e}")

        elapsed = max(duration, 1)
        return {
            "bandwidth_mbps": round((total_bytes * 8) / (elapsed * 1_000_000), 2),
            "duration_seconds": elapsed,
            "bytes_transferred": total_bytes,
            "tool": "socket",
        }

    def _test_network_latency(self) -> dict[str, Any]:
        target = self.config["target_host"]
        count = min(self.config.get("count", 50), 500)

        # 优先系统 ping
        if self._has_command("ping"):
            return self._ping_latency(target, count)

        # 降级：TCP 连接延迟
        return self._tcp_latency(target, count)

    def _ping_latency(self, target: str, count: int) -> dict[str, Any]:
        is_windows = platform.system() == "Windows"
        if is_windows:
            cmd = ["ping", "-n", str(count), "-w", "3000", target]
        else:
            cmd = ["ping", "-c", str(count), "-i", "0.2", "-W", "3", target]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=count * 5 + 10)
        output = proc.stdout + proc.stderr

        samples = self._parse_ping_samples(output, is_windows)
        if not samples:
            raise RuntimeError("无法解析 ping 结果")

        avg = sum(samples) / len(samples)
        loss = count - len(samples)
        return {
            "min_ms": round(min(samples), 2),
            "max_ms": round(max(samples), 2),
            "avg_ms": round(avg, 2),
            "stddev_ms": round(math.sqrt(sum((x - avg) ** 2 for x in samples) / len(samples)), 2),
            "packet_loss_percent": round((loss / count) * 100, 1),
            "samples_count": len(samples),
            "tool": "ping",
        }

    def _parse_ping_samples(self, output: str, is_windows: bool) -> list[float]:
        import re
        samples = []
        if is_windows:
            # Windows ping: "时间=1ms" 或 "time=1ms" 或 "time<1ms"，支持小数
            for m in re.finditer(r"[=<](\d+\.?\d*)\s*ms", output, re.IGNORECASE):
                samples.append(float(m.group(1)))
        else:
            for m in re.finditer(r"time[=](\d+\.?\d*)", output):
                samples.append(float(m.group(1)))
        return samples

    def _tcp_latency(self, target: str, count: int) -> dict[str, Any]:
        port = int(self.config.get("target_port", 80))
        samples = []
        for _ in range(count):
            if self._cancelled:
                break
            try:
                start = time.monotonic()
                sock = socket.create_connection((target, port), timeout=3)
                sock.close()
                elapsed_ms = (time.monotonic() - start) * 1000
                samples.append(elapsed_ms)
            except Exception:
                pass

        if not samples:
            raise RuntimeError("所有 TCP 连接均失败")

        avg = sum(samples) / len(samples)
        return {
            "min_ms": round(min(samples), 2),
            "max_ms": round(max(samples), 2),
            "avg_ms": round(avg, 2),
            "stddev_ms": round(math.sqrt(sum((x - avg) ** 2 for x in samples) / len(samples)), 2),
            "packet_loss_percent": round(((count - len(samples)) / count) * 100, 1),
            "samples_count": len(samples),
            "tool": "tcp",
        }

    def _test_network_packet_loss(self) -> dict[str, Any]:
        target = self.config["target_host"]
        count = min(self.config.get("count", 100), 1000)
        is_windows = platform.system() == "Windows"

        if is_windows:
            cmd = ["ping", "-n", str(count), "-w", "3000", "-l", str(self.config.get("packet_size_bytes", 32)), target]
        else:
            cmd = ["ping", "-c", str(count), "-i", "0.1", "-W", "3", "-s", str(self.config.get("packet_size_bytes", 56)), target]

        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=count * 2 + 10)
        output = proc.stdout + proc.stderr
        samples = self._parse_ping_samples(output, is_windows)

        return {
            "sent": count,
            "received": len(samples),
            "loss_percent": round(((count - len(samples)) / count) * 100, 1),
            "duration_seconds": int(self.elapsed_seconds()),
        }

    # ──────────────── 磁盘压测 ────────────────

    def _test_disk_io(self) -> dict[str, Any]:
        block_size = self.config.get("block_size_kb", 1024) * 1024
        count = min(self.config.get("count", 100), 500)
        test_dir = self.config.get("path", tempfile.gettempdir())
        test_file = os.path.join(test_dir, f".stress_test_{int(time.time())}.tmp")

        data = os.urandom(block_size)

        # 写入测试
        write_start = time.monotonic()
        with open(test_file, "wb") as f:
            for i in range(count):
                if self._cancelled:
                    break
                f.write(data)
            f.flush()
            os.fsync(f.fileno())
        write_elapsed = time.monotonic() - write_start

        # 读取测试
        read_start = time.monotonic()
        with open(test_file, "rb") as f:
            while f.read(block_size):
                if self._cancelled:
                    break
        read_elapsed = time.monotonic() - read_start

        total_bytes = block_size * count
        self._cleanup_file(test_file)

        return {
            "write_mbps": round((total_bytes / 1_000_000) / max(write_elapsed, 0.001), 2),
            "read_mbps": round((total_bytes / 1_000_000) / max(read_elapsed, 0.001), 2),
            "write_iops": int(count / max(write_elapsed, 0.001)),
            "read_iops": int(count / max(read_elapsed, 0.001)),
            "total_bytes": total_bytes,
            "block_size_kb": block_size // 1024,
            "count": count,
        }

    # ──────────────── CPU 压测 ────────────────

    def _test_cpu_stress(self) -> dict[str, Any]:
        duration = min(self.config.get("duration_seconds", 10), 300)
        threads = self.config.get("threads", 0) or multiprocessing.cpu_count()
        threads = min(threads, multiprocessing.cpu_count())

        self.report_progress({"status": "starting", "threads": threads, "duration_seconds": duration})

        # 多进程 CPU 密集计算
        with multiprocessing.Pool(threads) as pool:
            start = time.monotonic()
            results = pool.map(self._cpu_worker, [duration] * threads)
            elapsed = time.monotonic() - start

        peak_cpu = max(r["peak_cpu"] for r in results) if results else 0
        return {
            "peak_cpu_percent": round(peak_cpu, 1),
            "duration_seconds": round(elapsed, 1),
            "cores_used": threads,
            "iterations_per_core": results[0]["iterations"] if results else 0,
        }

    @staticmethod
    def _cpu_worker(duration: int) -> dict[str, Any]:
        end = time.monotonic() + duration
        iterations = 0
        proc = psutil.Process()
        peak_cpu = proc.cpu_percent(interval=0.1)
        while time.monotonic() < end:
            _sum = sum(math.sin(i) * math.cos(i) for i in range(10000))
            iterations += 1
            if iterations % 100 == 0:
                cpu = proc.cpu_percent(interval=0)
                peak_cpu = max(peak_cpu, cpu)
        return {"peak_cpu": peak_cpu, "iterations": iterations}

    # ──────────────── 内存压测 ────────────────

    def _test_memory_stress(self) -> dict[str, Any]:
        target_mb = min(self.config.get("target_mb", 512), int(psutil.virtual_memory().total * 0.8 / 1_024 / 1_024))
        duration = min(self.config.get("duration_seconds", 10), 120)
        chunk_mb = 64
        chunks_count = target_mb // chunk_mb

        mem = psutil.virtual_memory()
        if target_mb * 1024 * 1024 > mem.available:
            raise RuntimeError(f"可用内存不足: 需要 {target_mb}MB, 可用 {mem.available // 1024 // 1024}MB")

        self.report_progress({"status": "allocating", "target_mb": target_mb})

        alloc_start = time.monotonic()
        buffers: list[bytearray] = []
        for i in range(chunks_count):
            if self._cancelled:
                break
            buffers.append(bytearray(chunk_mb * 1024 * 1024))
            # 写入确保物理内存分配
            for j in range(0, len(buffers[-1]), 4096):
                buffers[-1][j] = 0xFF
        alloc_elapsed = (time.monotonic() - alloc_start) * 1000

        peak_mem = psutil.virtual_memory().percent
        self.report_progress({"status": "holding", "allocated_mb": len(buffers) * chunk_mb})

        time.sleep(min(duration, 10))

        release_start = time.monotonic()
        buffers.clear()
        release_elapsed = (time.monotonic() - release_start) * 1000

        return {
            "allocated_mb": len(buffers) * chunk_mb if buffers else chunks_count * chunk_mb,
            "target_mb": target_mb,
            "peak_memory_percent": round(peak_mem, 1),
            "duration_seconds": duration,
            "allocation_time_ms": round(alloc_elapsed, 1),
            "release_time_ms": round(release_elapsed, 1),
        }

    # ──────────────── 工具方法 ────────────────

    @staticmethod
    def _has_command(name: str) -> bool:
        import shutil
        return shutil.which(name) is not None

    @staticmethod
    def _cleanup_file(path: str) -> None:
        try:
            os.unlink(path)
        except OSError:
            pass
