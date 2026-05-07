@echo off
chcp 65001 >nul
title CPA - Start Services
setlocal EnableDelayedExpansion

echo ========================================
echo    CPA - Start Services
echo ========================================
echo.

cd /d "%~dp0"

if exist "%~dp0config.bat" (
    call "%~dp0config.bat"
) else (
    set "BACKEND_PORT=8000"
    set "FRONTEND_PORT=3000"
    set "AUTO_OPEN_BROWSER=1"
    set "BACKEND_HOST=0.0.0.0"
    set "PIP_DEFAULT_TIMEOUT=120"
)

if not defined PIP_DEFAULT_TIMEOUT set "PIP_DEFAULT_TIMEOUT=120"

set "PORTABLE_READY_PY=%~dp0portable-ready\python\python.exe"
set "PORTABLE_GREEN_PY=%~dp0portable-green\python\python.exe"

echo [Config] Backend port: %BACKEND_PORT%
echo [Config] Frontend port: %FRONTEND_PORT%
echo.

set "PYTHON_CMD="
set "PYTHON_LABEL="

call :try_python "py -3.14" "Python 3.14"
if not defined PYTHON_CMD call :try_python "py -3.13" "Python 3.13"
if not defined PYTHON_CMD call :try_python "py -3.12" "Python 3.12"
if not defined PYTHON_CMD call :try_python "py -3.11" "Python 3.11"
if not defined PYTHON_CMD call :try_python "py -3.10" "Python 3.10"
if not defined PYTHON_CMD call :try_python "python" "python"

rem Fallback to bundled portable python with complete backend dependencies
if not defined PYTHON_CMD if exist "%PORTABLE_READY_PY%" (
    call :try_python "%PORTABLE_READY_PY%" "Portable Ready"
)
if not defined PYTHON_CMD if exist "%PORTABLE_GREEN_PY%" (
    call :try_python "%PORTABLE_GREEN_PY%" "Portable Green"
)

if not defined PYTHON_CMD (
    echo [Error] No supported Python found.
    echo [Error] Install Python 3.10, 3.11, 3.12, 3.13, or 3.14 and retry.
    call :hold_on_error "No supported Python found"
)

echo [Info] Using %PYTHON_LABEL%

node --version >nul 2>&1
if errorlevel 1 (
    echo [Warn] Node.js was not found. Frontend startup will be skipped.
    set "NO_FRONTEND=1"
)

if not defined NO_FRONTEND (
    if not exist "frontend\node_modules" (
        echo [Info] Installing frontend dependencies...
        cd frontend
        set "NPM_INSTALL_ARGS=install"
        if defined NPM_REGISTRY set "NPM_INSTALL_ARGS=!NPM_INSTALL_ARGS! --registry %NPM_REGISTRY%"
        if defined NPM_REGISTRY echo [Info] Frontend npm registry: %NPM_REGISTRY%
        call npm !NPM_INSTALL_ARGS!
        if errorlevel 1 call :hold_on_error "Frontend dependency installation failed"
        cd ..
    )
)

call :check_backend_dependencies
if errorlevel 1 (
    if defined PYTHON_LABEL if /i not "%PYTHON_LABEL:~0,8%"=="Portable" (
        echo [Info] Installing backend dependencies...
        cd backend
        set "PIP_INSTALL_ARGS=-r requirements.txt --default-timeout %PIP_DEFAULT_TIMEOUT%"
        if defined PIP_INDEX_URL set "PIP_INSTALL_ARGS=!PIP_INSTALL_ARGS! -i %PIP_INDEX_URL%"
        if defined PIP_EXTRA_INDEX_URL set "PIP_INSTALL_ARGS=!PIP_INSTALL_ARGS! --extra-index-url %PIP_EXTRA_INDEX_URL%"
        if defined PIP_INDEX_URL echo [Info] Backend pip index: %PIP_INDEX_URL%
        %PYTHON_CMD% -m pip install !PIP_INSTALL_ARGS!
        if errorlevel 1 call :hold_on_error "Backend dependency installation failed"
        cd ..
    ) else (
        call :hold_on_error "No Python with complete backend dependencies was found"
    )
)

call :get_listening_pid %BACKEND_PORT%
if defined FOUND_PID (
    echo [Info] Backend port %BACKEND_PORT% is already in use ^(PID=!FOUND_PID!^). Skipping backend startup.
) else (
    echo [Start] Backend service on port %BACKEND_PORT%...
    set "BACKEND_CMD=%PYTHON_CMD% -m uvicorn main:app --host %BACKEND_HOST% --port %BACKEND_PORT%"
    start "CPA-Backend" /D "%~dp0backend" "%ComSpec%" /k !BACKEND_CMD!
    call :wait_port %BACKEND_PORT% Backend
    if errorlevel 1 call :hold_on_error "Backend did not start correctly"
)

if defined NO_FRONTEND goto summary

call :get_listening_pid %FRONTEND_PORT%
if defined FOUND_PID (
    echo [Info] Frontend port %FRONTEND_PORT% is already in use ^(PID=!FOUND_PID!^). Skipping frontend startup.
) else (
    echo [Start] Frontend service on port %FRONTEND_PORT%...
    start "CPA-Frontend" /D "%~dp0frontend" "%ComSpec%" /k "call npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%"
    call :wait_port %FRONTEND_PORT% Frontend
    if errorlevel 1 call :hold_on_error "Frontend did not start correctly"
)

:summary
echo.
echo ========================================
echo    Services Ready
echo ========================================
echo.
echo    Backend : http://127.0.0.1:%BACKEND_PORT%
echo    Frontend: http://127.0.0.1:%FRONTEND_PORT%
echo    API docs: http://127.0.0.1:%BACKEND_PORT%/docs
echo.
echo    Edit ports: config.bat
echo    Stop all  : stop.bat
echo ========================================
echo.

if "%AUTO_OPEN_BROWSER%"=="1" if not defined NO_FRONTEND (
    start http://127.0.0.1:%FRONTEND_PORT%
)

exit /b 0

:get_listening_pid
set "FOUND_PID="
set "PORT=%~1"
for /f %%a in ('powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique"') do (
    set "FOUND_PID=%%a"
    goto :eof
)
exit /b 0

:try_python
if defined PYTHON_CMD exit /b 0
set "CANDIDATE=%~1"
set "LABEL=%~2"
%~1 -c "import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)" >nul 2>&1
if errorlevel 1 exit /b 0
pushd "%~dp0backend" >nul
%~1 -c "import fastapi, uvicorn, sqlalchemy, httpx, pydantic" >nul 2>&1
set "CANDIDATE_DEP_EXIT=%errorlevel%"
popd >nul
if not "%CANDIDATE_DEP_EXIT%"=="0" exit /b 0
set "PYTHON_CMD=%~1"
for /f "delims=" %%v in ('%~1 --version 2^>^&1') do set "PYTHON_LABEL=%LABEL% (%%v)"
exit /b 0

:check_backend_dependencies
pushd "%~dp0backend" >nul
%PYTHON_CMD% -c "import fastapi, uvicorn, sqlalchemy, httpx, pydantic" >nul 2>&1
set "DEPENDENCY_CHECK_EXIT=%errorlevel%"
popd >nul
exit /b %DEPENDENCY_CHECK_EXIT%

:wait_port
set "PORT=%~1"
set "LABEL=%~2"
for /l %%i in (1,1,20) do (
    call :get_listening_pid %PORT%
    if defined FOUND_PID (
        echo [OK] %LABEL% is listening on port %PORT% ^(PID=!FOUND_PID!^)
        exit /b 0
    )
    powershell -NoProfile -Command "Start-Sleep -Seconds 1" >nul
)
echo [Error] %LABEL% did not start listening on port %PORT%.
exit /b 1

:hold_on_error
echo.
echo [Error] %~1
echo [Error] Press any key to close this window.
pause >nul
exit /b 1
