@echo off
chcp 65001 >nul
title CPA - 重启服务

echo ========================================
echo    CPA - 重启服务
echo ========================================
echo.

cd /d "%~dp0"

call "%~dp0stop.bat"
if errorlevel 1 (
    echo [错误] 停止服务失败
    exit /b 1
)

powershell -NoProfile -Command "Start-Sleep -Seconds 2" >nul

call "%~dp0start.bat"
if errorlevel 1 (
    echo [错误] 启动服务失败
    exit /b 1
)

echo.
echo [完成] 重启流程执行完成
exit /b 0
