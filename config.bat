:: CPA config
:: Run restart.bat after editing

:: Backend port
set BACKEND_PORT=8000

:: Frontend port
set FRONTEND_PORT=3000

:: Auto open browser (1=yes, 0=no)
set AUTO_OPEN_BROWSER=1

:: Backend bind address
set BACKEND_HOST=0.0.0.0

:: Session sticky TTL: keep same API key within a session to maximize prompt cache hit rate (seconds)
set PROXY_SESSION_STICKY_TTL_SECONDS=86400

:: Fallback session sticky: when clients do not send session headers, bind by auth/user-agent/model
set PROXY_SESSION_STICKY_FALLBACK_ENABLED=1

:: Proxy read timeout: wait up to 3 minutes for upstream responses
set PROXY_REQUEST_TIMEOUT_SECONDS=180
set PROXY_STREAM_READ_TIMEOUT_SECONDS=180

:: Optional: pip timeout for first-time installs on a new machine
set PIP_DEFAULT_TIMEOUT=120

:: Optional: pip mirror, uncomment if direct PyPI access is slow
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

:: Optional: npm registry mirror, uncomment if npm install is slow
set NPM_REGISTRY=https://registry.npmmirror.com
