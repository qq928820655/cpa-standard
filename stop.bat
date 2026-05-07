@echo off
chcp 65001 >nul
title CPA - 停止服务
setlocal EnableDelayedExpansion

echo ========================================
echo    CPA - 停止所有服务
echo ========================================
echo.

cd /d "%~dp0"

if exist "%~dp0config.bat" (
    call "%~dp0config.bat"
) else (
    set "BACKEND_PORT=8000"
    set "FRONTEND_PORT=3000"
)

set "STOPPED_ANY=0"

call :stop_service %BACKEND_PORT% 后端 "CPA-Backend*"
if errorlevel 1 exit /b 1
call :stop_service %FRONTEND_PORT% 前端 "CPA-Frontend*"
if errorlevel 1 exit /b 1

echo.
if "%STOPPED_ANY%"=="1" (
    echo ========================================
    echo    服务已停止
    echo ========================================
) else (
    echo ========================================
    echo    未发现运行中的服务
    echo ========================================
)
echo.
exit /b 0

:stop_service
set "PORT=%~1"
set "LABEL=%~2"
set "WINDOW_FILTER=%~3"
set "FOUND_PID="
echo [停止] %LABEL%服务 (端口 %PORT%)...
for /f %%a in ('powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"') do (
    set "FOUND_PID=%%a"
    set "STOPPED_ANY=1"
    echo   - 结束进程树 PID %%a
    taskkill /F /T /PID %%a >nul 2>&1
)
if not defined FOUND_PID (
    echo   - 端口 %PORT% 未监听
) else (
    timeout /t 1 /nobreak >nul
)

taskkill /F /T /FI "WINDOWTITLE eq %WINDOW_FILTER%" >nul 2>&1

timeout /t 1 /nobreak >nul
for /f %%a in ('powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"') do (
    echo [错误] %LABEL%端口 %PORT% 仍在监听，PID=%%a
    exit /b 1
)
exit /b 0
