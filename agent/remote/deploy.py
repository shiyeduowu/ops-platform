from __future__ import annotations

import hashlib
import logging
import platform
import re
import shlex
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("remote.deploy")

# 允许的安装命令前缀
ALLOWED_INSTALLERS = {
    "msiexec", "msiexec.exe",
    "setup", "setup.exe", "install", "install.exe",
    "dpkg", "apt", "apt-get", "yum", "rpm",
    "pip", "pip3", "python", "python3",
}

# 危险的 shell 元字符
_SHELL_META = re.compile(r"[;|&$`\n\r]")


def _validate_install_command(command: str) -> str | None:
    """校验安装命令，返回错误消息或 None"""
    if not command.strip():
        return "安装命令不能为空"
    if _SHELL_META.search(command):
        return "安装命令包含不允许的特殊字符"
    first = command.strip().split()[0].lower()
    if "/" in first:
        first = first.rsplit("/", 1)[-1]
    if "\\" in first:
        first = first.rsplit("\\", 1)[-1]
    if first not in ALLOWED_INSTALLERS:
        return f"不允许的安装程序: {first}"
    return None


class DeployExecutor:
    """软件部署执行器：下载安装包 → 执行安装命令"""

    def __init__(self, server_url: str, sign_callback: Any, report_callback: Any):
        self._server_url = server_url.rstrip("/")
        self._sign = sign_callback
        self._report = report_callback

    def deploy(self, deployment_id: int, installer_filename: str,
               install_command: str, install_args: str | None,
               timeout: int, download_token: str) -> None:
        t = threading.Thread(
            target=self._run,
            args=(deployment_id, installer_filename, install_command, install_args, timeout, download_token),
            daemon=True,
            name=f"deploy-{deployment_id}",
        )
        t.start()

    def _run(self, deployment_id: int, installer_filename: str,
             install_command: str, install_args: str | None,
             timeout: int, download_token: str) -> None:
        installer_path = None
        tmp_dir = None
        try:
            # 校验安装命令
            err = _validate_install_command(install_command)
            if err:
                self._report(deployment_id, "install", "failed", None, None, -1, err)
                return
            # 校验安装参数
            if install_args and _SHELL_META.search(install_args):
                self._report(deployment_id, "install", "failed", None, None, -1, "安装参数包含不允许的特殊字符")
                return

            # 1. 下载安装包
            installer_path, tmp_dir = self._download_installer(deployment_id, installer_filename, download_token)
            self._report(deployment_id, "file", "completed", None, None, None, None)

            # 2. 执行安装命令
            self._execute_install(
                deployment_id, installer_path, install_command, install_args, timeout,
            )

        except Exception as e:
            error_msg = f"{type(e).__name__}"[:2000]
            logger.error(f"部署失败: {type(e).__name__}: {e}")
            self._report(deployment_id, "install", "failed", None, None, -1, error_msg)
        finally:
            # 清理临时目录
            if tmp_dir and tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    logger.info(f"已清理临时目录: {tmp_dir}")
                except Exception as e:
                    logger.warning(f"清理临时目录失败: {e}")

    def _download_installer(self, deployment_id: int, filename: str, token: str) -> tuple[Path, Path]:
        """下载安装包到临时目录，返回 (安装包路径, 临时目录)"""
        import tempfile

        tmp_dir = Path(tempfile.mkdtemp(prefix="deploy_"))
        # 清理文件名中的特殊字符
        safe_name = Path(filename).name.replace("..", "_")
        target = tmp_dir / safe_name
        download_url = f"{self._server_url}/api/v1/deployments/{deployment_id}/download?token={token}"

        logger.info(f"下载安装包: {filename}")
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            with client.stream("GET", download_url) as resp:
                resp.raise_for_status()
                with open(target, "wb") as f:
                    for chunk in resp.iter_bytes(chunk_size=8192):
                        f.write(chunk)

        logger.info(f"安装包下载完成: {target} ({target.stat().st_size} bytes)")
        return target, tmp_dir

    def _execute_install(self, deployment_id: int, installer_path: Path,
                         install_command: str, install_args: str | None,
                         timeout: int) -> None:
        """执行安装命令"""
        # 使用 shlex.quote 保护路径中的特殊字符
        quoted_path = shlex.quote(str(installer_path))

        # 替换模板变量 — 使用 shlex.quote 保护路径中的特殊字符
        safe_path = shlex.quote(str(installer_path))
        if "{installer}" in install_command:
            cmd = install_command.replace("{installer}", safe_path)
        else:
            cmd = f"{install_command} {quoted_path}"

        if install_args:
            args = install_args.replace("{installer}", safe_path)
            cmd = f"{cmd} {args}"

        is_windows = platform.system() == "Windows"
        if is_windows:
            exec_args = ["cmd", "/c", cmd]
        else:
            exec_args = ["sh", "-c", cmd]

        logger.info(f"执行安装命令: {cmd[:200]}")

        try:
            result = subprocess.run(
                exec_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            stdout = (result.stdout or "")[:100000]
            stderr = (result.stderr or "")[:100000]
            exit_code = result.returncode

            status = "completed" if exit_code == 0 else "failed"
            self._report(deployment_id, "install", status, stdout, stderr, exit_code, None)

        except subprocess.TimeoutExpired:
            self._report(deployment_id, "install", "failed", None, None, -2, f"安装超时（{timeout}秒）")
        except Exception as e:
            self._report(deployment_id, "install", "failed", None, None, -1, f"执行异常")

    @staticmethod
    def _compute_md5(file_path: Path) -> str:
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                h.update(chunk)
        return h.hexdigest()
