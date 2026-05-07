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

:: Optional: pip timeout for first-time installs on a new machine
set PIP_DEFAULT_TIMEOUT=120

:: Optional: pip mirror, uncomment if direct PyPI access is slow
set PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

:: Optional: npm registry mirror, uncomment if npm install is slow
set NPM_REGISTRY=https://registry.npmmirror.com
