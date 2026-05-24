@echo off
chcp 65001 >nul
echo ========================================
echo  Ops Agent Windows 服务安装工具
echo ========================================
echo.

:: 检查管理员权限
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 需要管理员权限运行此脚本
    echo 请右键点击此文件，选择"以管理员身份运行"
    pause
    exit /b 1
)

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.12+
    pause
    exit /b 1
)

:: 安装依赖
echo [1/3] 安装依赖...
pip install pywin32 -q
if %errorlevel% neq 0 (
    echo [错误] 安装 pywin32 失败
    pause
    exit /b 1
)

:: 注册服务
echo [2/3] 注册 Windows 服务...
python "%~dp0win_service.py" install
if %errorlevel% neq 0 (
    echo [错误] 注册服务失败
    pause
    exit /b 1
)

:: 设置崩溃自动重启（失败后 30 秒重启，无限次）
echo [3/3] 配置崩溃自动恢复...
sc failure OpsAgent reset= 86400 actions= restart/30000/restart/30000/restart/30000 >nul 2>&1
sc failureflag OpsAgent 1 >nul 2>&1

echo.
echo ========================================
echo  安装完成！
echo ========================================
echo.
echo  启动服务:  net start OpsAgent
echo  停止服务:  net stop OpsAgent
echo  查看状态:  python win_service.py status
echo  卸载服务:  python win_service.py remove
echo.
echo  服务已配置崩溃自动恢复（30秒后重启）
echo  开机将自动启动
echo.
pause
