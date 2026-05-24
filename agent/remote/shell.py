from __future__ import annotations

import logging
import platform
import re
import shlex
import subprocess
import threading
from typing import Any

logger = logging.getLogger("remote.shell")

# 平台感知的白名单
WINDOWS_COMMANDS = {
    "ipconfig", "hostname", "whoami", "systeminfo", "tasklist",
    "netstat", "ping", "dir", "type", "echo", "date", "time",
    "ver", "tree", "findstr",
}

POSIX_COMMANDS = {
    "hostname", "whoami", "ping", "echo", "date",
    "df", "free", "uptime", "ps", "cat", "ls", "uname",
    "ifconfig", "dig", "nslookup", "traceroute", "tail", "head",
    "wc", "grep", "sort", "uniq", "du", "nslookup",
}

# 危险的 shell 元字符 — 任何包含这些字符的命令都会被拒绝
_SHELL_META = re.compile(r"[;|&$`\\(){}!\n\r]")

# 输出大小限制
MAX_OUTPUT_BYTES = 100_000


def _validate_command_text(command_text: str) -> str | None:
    """校验命令文本，返回错误消息或 None"""
    if not command_text.strip():
        return "命令为空"
    if _SHELL_META.search(command_text):
        return "命令包含不允许的特殊字符"
    return None


class ShellExecutor:
    """白名单命令执行器"""

    def __init__(self, report_callback: Any):
        self._report = report_callback

    def execute(self, command_id: int, command_type: str, command_text: str, timeout: int = 60) -> None:
        """在新线程中执行命令并回报结果"""
        t = threading.Thread(
            target=self._run,
            args=(command_id, command_type, command_text, timeout),
            daemon=True,
            name=f"shell-{command_id}",
        )
        t.start()

    def _run(self, command_id: int, command_type: str, command_text: str, timeout: int) -> None:
        stdout = ""
        stderr = ""
        exit_code = -1

        try:
            # 校验命令文本（元字符检测）
            err = _validate_command_text(command_text)
            if err:
                stderr = err
                exit_code = 1
                return

            # 解析命令名
            parts = command_text.strip().split()
            cmd_name = parts[0].lower()
            # 去除路径前缀
            if "/" in cmd_name:
                cmd_name = cmd_name.rsplit("/", 1)[-1]
            if "\\" in cmd_name:
                cmd_name = cmd_name.rsplit("\\", 1)[-1]

            # 平台感知的白名单校验
            is_windows = platform.system() == "Windows"
            allowed = WINDOWS_COMMANDS if is_windows else POSIX_COMMANDS
            if cmd_name not in allowed:
                stderr = f"不允许的命令: {cmd_name}（当前平台: {'Windows' if is_windows else 'POSIX'}）"
                exit_code = 126
                return

            # 构建执行参数 — 使用列表避免 shell 注入
            if command_type == "powershell":
                # PowerShell 命令已通过白名单 + 元字符校验，使用列表形式传递
                exec_args = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command_text]
            elif is_windows:
                # cmd /c + 列表形式，command_text 已通过元字符检测
                exec_args = ["cmd", "/c", command_text]
            else:
                exec_args = ["sh", "-c", command_text]

            logger.info(f"执行远程命令 #{command_id}: {command_text[:100]}")

            result = subprocess.run(
                exec_args,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=None,
            )

            stdout = (result.stdout or "")[:MAX_OUTPUT_BYTES]
            stderr = (result.stderr or "")[:MAX_OUTPUT_BYTES]
            exit_code = result.returncode

        except subprocess.TimeoutExpired:
            stderr = f"命令执行超时（{timeout}秒）"
            exit_code = -2
        except FileNotFoundError:
            stderr = f"命令未找到: {parts[0] if parts else '?'}"
            exit_code = 127
        except Exception as e:
            stderr = f"执行异常: {type(e).__name__}"
            exit_code = -1
        finally:
            try:
                self._report(command_id, stdout, stderr, exit_code)
            except Exception as e:
                logger.error(f"回报命令结果失败: {e}")
