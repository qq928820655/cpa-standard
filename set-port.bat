@echo off
chcp 65001 >nul
title CPA - 端口配置

cd /d "%~dp0"

:: 加载当前配置
if exist "%~dp0config.bat" (
    call "%~dp0config.bat"
) else (
    set BACKEND_PORT=8000
    set FRONTEND_PORT=3000
    set AUTO_OPEN_BROWSER=1
    set BACKEND_HOST=0.0.0.0
)

:menu
cls
echo ========================================
echo    CPA - 端口配置工具
echo ========================================
echo.
echo    当前配置:
echo    [1] 后端端口: %BACKEND_PORT%
echo    [2] 前端端口: %FRONTEND_PORT%
echo    [3] 后端绑定: %BACKEND_HOST%
echo    [4] 自动打开浏览器: %AUTO_OPEN_BROWSER%
echo.
echo    [5] 保存并退出
echo    [6] 保存并重启服务
echo    [0] 取消退出
echo.
echo ========================================
echo.

set /p choice=请选择操作 [0-6]:

if "%choice%"=="1" goto set_backend_port
if "%choice%"=="2" goto set_frontend_port
if "%choice%"=="3" goto set_backend_host
if "%choice%"=="4" goto set_auto_browser
if "%choice%"=="5" goto save_and_exit
if "%choice%"=="6" goto save_and_restart
if "%choice%"=="0" goto cancel
goto menu

:set_backend_port
echo.
set "INPUT_VALUE="
set /p INPUT_VALUE=请输入后端端口 [当前: %BACKEND_PORT%]:
call :validate_port "%INPUT_VALUE%"
if errorlevel 1 goto menu
set "BACKEND_PORT=%VALIDATED_VALUE%"
goto menu

:set_frontend_port
echo.
set "INPUT_VALUE="
set /p INPUT_VALUE=请输入前端端口 [当前: %FRONTEND_PORT%]:
call :validate_port "%INPUT_VALUE%"
if errorlevel 1 goto menu
set "FRONTEND_PORT=%VALIDATED_VALUE%"
goto menu

:set_backend_host
echo.
echo 可选值: 0.0.0.0 (允许外部访问) 或 127.0.0.1 (仅本机)
set "INPUT_VALUE="
set /p INPUT_VALUE=请输入后端绑定地址 [当前: %BACKEND_HOST%]:
call :validate_host "%INPUT_VALUE%"
if errorlevel 1 goto menu
set "BACKEND_HOST=%VALIDATED_VALUE%"
goto menu

:set_auto_browser
echo.
set "INPUT_VALUE="
set /p INPUT_VALUE=是否自动打开浏览器 (1=是, 0=否) [当前: %AUTO_OPEN_BROWSER%]:
call :validate_auto_browser "%INPUT_VALUE%"
if errorlevel 1 goto menu
set "AUTO_OPEN_BROWSER=%VALIDATED_VALUE%"
goto menu

:save_config
:: 写入配置文件
(
echo :: CPA 配置文件
echo :: 修改后运行 restart.bat 生效
echo.
echo :: 后端端口
echo set BACKEND_PORT=%BACKEND_PORT%
echo.
echo :: 前端端口
echo set FRONTEND_PORT=%FRONTEND_PORT%
echo.
echo :: 是否自动打开浏览器 ^(1=是, 0=否^)
echo set AUTO_OPEN_BROWSER=%AUTO_OPEN_BROWSER%
echo.
echo :: 后端绑定地址 ^(0.0.0.0 允许外部访问, 127.0.0.1 仅本机^)
echo set BACKEND_HOST=%BACKEND_HOST%
) > "%~dp0config.bat"
echo.
echo [成功] 配置已保存到 %~dp0config.bat
goto :eof

:validate_port
set "VALIDATED_VALUE=%~1"
if not defined VALIDATED_VALUE (
    echo [错误] 端口不能为空
    goto :validation_failed
)
for /f "delims=0123456789" %%i in ("%VALIDATED_VALUE%") do (
    echo [错误] 端口只能输入数字
    goto :validation_failed
)
if %VALIDATED_VALUE% LSS 1 (
    echo [错误] 端口范围必须在 1-65535
    goto :validation_failed
)
if %VALIDATED_VALUE% GTR 65535 (
    echo [错误] 端口范围必须在 1-65535
    goto :validation_failed
)
goto :validation_ok

:validate_host
set "VALIDATED_VALUE=%~1"
if /i "%VALIDATED_VALUE%"=="0.0.0.0" goto :validation_ok
if /i "%VALIDATED_VALUE%"=="127.0.0.1" goto :validation_ok
echo [错误] 后端绑定地址只能是 0.0.0.0 或 127.0.0.1
goto :validation_failed

:validate_auto_browser
set "VALIDATED_VALUE=%~1"
if "%VALIDATED_VALUE%"=="0" goto :validation_ok
if "%VALIDATED_VALUE%"=="1" goto :validation_ok
echo [错误] 自动打开浏览器只能输入 0 或 1
goto :validation_failed

:validation_ok
exit /b 0

:validation_failed
ping 127.0.0.1 -n 3 >nul
exit /b 1

:save_and_exit
call :save_config
echo.
ping 127.0.0.1 -n 3 >nul
exit /b 0

:save_and_restart
call :save_config
echo.
echo [信息] 正在重启服务...
ping 127.0.0.1 -n 3 >nul
call "%~dp0restart.bat"
exit /b 0

:cancel
echo.
echo [取消] 未保存任何更改
ping 127.0.0.1 -n 3 >nul
exit /b 0
