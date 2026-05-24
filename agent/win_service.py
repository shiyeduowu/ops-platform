# -*- coding: utf-8 -*-
"""
Ops Agent Windows 服务

将 Agent 注册为 Windows 服务，实现开机自启和崩溃自动恢复。

安装服务:
    python win_service.py install

启动服务:
    python win_service.py start

停止服务:
    python win_service.py stop

卸载服务:
    python win_service.py remove

查看状态:
    python win_service.py status
"""

import os
import sys
import subprocess
import logging

# pywin32 导入
import win32serviceutil
import win32service
import win32event
import servicemanager

logger = logging.getLogger("ops-agent-service")

AGENT_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.py")
PYTHON_EXE = sys.executable


class OpsAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = "OpsAgent"
    _svc_display_name_ = "Ops Platform Monitoring Agent"
    _svc_description_ = (
        "分布式运维监控 Agent — 本地高频检测（端口/磁盘/CPU/内存/Windows服务/Java进程/日志），"
        "状态翻转告警，远程命令执行，心跳上报。"
    )

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.process = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self.stop_event)
        if self.process:
            self.process.terminate()

    def SvcDoRun(self):
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        self._run_agent()

    def _run_agent(self):
        while True:
            try:
                self.process = subprocess.Popen(
                    [PYTHON_EXE, AGENT_SCRIPT],
                    cwd=os.path.dirname(AGENT_SCRIPT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                # 等待进程结束或服务停止
                wait_result = win32event.WaitForMultipleObjects(
                    [self.stop_event, int(self.process._handle)],
                    False,
                    win32event.INFINITE,
                )
                if wait_result == win32event.WAIT_OBJECT_0:
                    # 服务停止信号
                    self.process.terminate()
                    break
                else:
                    # 进程意外退出，等待 10 秒后重启
                    exit_code = self.process.returncode
                    logger.warning(f"Agent 进程退出 (code={exit_code})，10 秒后重启")
                    win32event.WaitForSingleObject(self.stop_event, 10000)
                    # 检查是否在等待期间收到了停止信号
                    if win32event.WaitForSingleObject(self.stop_event, 0) == win32event.WAIT_OBJECT_0:
                        break
            except Exception as e:
                logger.error(f"启动 Agent 失败: {e}")
                win32event.WaitForSingleObject(self.stop_event, 30000)
                if win32event.WaitForSingleObject(self.stop_event, 0) == win32event.WAIT_OBJECT_0:
                    break


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # 以服务方式启动
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(OpsAgentService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # 命令行方式：install / start / stop / remove / status
        win32serviceutil.HandleCommandLine(OpsAgentService)
