from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("remote.file_download")


class FileDownloader:
    """文件下载器 — 从 Server 拉取文件并校验 MD5"""

    def __init__(self, server_url: str, sign_callback: Any, report_callback: Any):
        self._server_url = server_url.rstrip("/")
        self._sign = sign_callback
        self._report = report_callback

    def download(self, distribution_id: int, filename: str, target_path: str,
                 file_size: int, checksum_md5: str, download_token: str) -> None:
        """在新线程中下载文件"""
        t = threading.Thread(
            target=self._run,
            args=(distribution_id, filename, target_path, file_size, checksum_md5, download_token),
            daemon=True,
            name=f"file-dl-{distribution_id}",
        )
        t.start()

    def _run(self, distribution_id: int, filename: str, target_path: str,
             file_size: int, checksum_md5: str, download_token: str) -> None:
        try:
            target = Path(target_path)
            # 如果目标路径是目录，追加文件名
            if target.is_dir() or target_path.endswith(("/", "\\")):
                target = target / filename

            # 路径穿越检测
            if ".." in str(target):
                raise ValueError("目标路径不能包含 .. 组件")

            # 确保父目录存在
            target.parent.mkdir(parents=True, exist_ok=True)

            # 下载到临时文件
            tmp_path = target.with_suffix(target.suffix + ".tmp")
            download_url = f"{self._server_url}/api/v1/file-distributions/{distribution_id}/download?token={download_token}"

            logger.info(f"开始下载文件: {filename} -> {target}")

            with httpx.Client(timeout=120, follow_redirects=True) as client:
                with client.stream("GET", download_url) as resp:
                    resp.raise_for_status()
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=8192):
                            f.write(chunk)

            # 校验 MD5
            actual_md5 = self._compute_md5(tmp_path)
            if actual_md5 != checksum_md5:
                tmp_path.unlink(missing_ok=True)
                raise ValueError(f"MD5 校验失败: 期望 {checksum_md5}, 实际 {actual_md5}")

            # 校验文件大小
            actual_size = tmp_path.stat().st_size
            if actual_size != file_size:
                tmp_path.unlink(missing_ok=True)
                raise ValueError(f"文件大小不匹配: 期望 {file_size}, 实际 {actual_size}")

            # 移动到目标路径
            if target.exists():
                target.unlink()
            tmp_path.rename(target)

            logger.info(f"文件下载完成: {target} ({actual_size} bytes)")
            self._report(distribution_id, "completed", None)

        except Exception as e:
            logger.error(f"文件下载失败: {type(e).__name__}: {e}")
            self._report(distribution_id, "failed", f"下载失败: {type(e).__name__}")

    @staticmethod
    def _compute_md5(file_path: Path) -> str:
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
