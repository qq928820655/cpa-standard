#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${PACKAGE_DIR}/backend"
FRONTEND_DIST_DIR="${PACKAGE_DIR}/frontend/dist"

BACKEND_PORT="8000"
BACKEND_HOST="0.0.0.0"
PYTHON_BIN="python3"
AUTO_OPEN_BROWSER="0"
PID_FILE="${PACKAGE_DIR}/runtime/linux-cpa.pid"
LOG_FILE="${PACKAGE_DIR}/runtime/logs/linux-backend.log"

if [ -f "${PACKAGE_DIR}/config.sh" ]; then
  # shellcheck source=/dev/null
  source "${PACKAGE_DIR}/config.sh"
fi

# 本机部署覆盖（不入库）：venv 路径、出口代理等按机器而异的设置放这里
if [ -f "${PACKAGE_DIR}/config.local.sh" ]; then
  # shellcheck source=/dev/null
  source "${PACKAGE_DIR}/config.local.sh"
fi

echo "========================================"
echo "   CPA - Linux Start"
echo "========================================"
echo

if [ ! -d "${BACKEND_DIR}" ]; then
  echo "[Error] Backend folder not found: ${BACKEND_DIR}"
  exit 1
fi

if [ ! -d "${FRONTEND_DIST_DIR}" ]; then
  echo "[Error] Frontend build not found: ${FRONTEND_DIST_DIR}"
  exit 1
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "[Error] Python not found: ${PYTHON_BIN}"
  echo "[Hint] Install Python 3 or edit config.sh PYTHON_BIN."
  exit 1
fi

if [ -f "${PID_FILE}" ]; then
  EXISTING_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [ -n "${EXISTING_PID}" ] && kill -0 "${EXISTING_PID}" >/dev/null 2>&1; then
    echo "[Info] Service is already running (PID=${EXISTING_PID})."
    echo "[Info] App URL: http://127.0.0.1:${BACKEND_PORT}"
    exit 0
  fi
  rm -f "${PID_FILE}"
fi

mkdir -p "$(dirname "${LOG_FILE}")"

echo "[Config] Service port: ${BACKEND_PORT}"
echo "[Config] Bind host   : ${BACKEND_HOST}"
echo "[Info] Runtime       : $(${PYTHON_BIN} -c 'import sys; print(sys.executable)' 2>/dev/null || echo "${PYTHON_BIN}")"
echo "[Info] Log file      : ${LOG_FILE}"
echo

echo "[Start] CPA service on port ${BACKEND_PORT}..."
(
  cd "${BACKEND_DIR}"
  export PYTHONUTF8=1
  export PYTHONDONTWRITEBYTECODE=1
  nohup "${PYTHON_BIN}" -m uvicorn main:app --host "${BACKEND_HOST}" --port "${BACKEND_PORT}" >> "${LOG_FILE}" 2>&1 &
  echo $! > "${PID_FILE}"
)

STARTED_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
if [ -z "${STARTED_PID}" ]; then
  echo "[Error] Failed to record service PID."
  exit 1
fi

for _ in 1 2 3 4 5; do
  if ! kill -0 "${STARTED_PID}" >/dev/null 2>&1; then
    echo "[Error] Service exited during startup."
    echo "[Hint] Check log: ${LOG_FILE}"
    rm -f "${PID_FILE}"
    exit 1
  fi

  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
      echo "[OK] Service is healthy (PID=${STARTED_PID})."
      echo
      echo "========================================"
      echo "   Service Ready"
      echo "========================================"
      echo "   App URL : http://127.0.0.1:${BACKEND_PORT}"
      echo "   API docs: http://127.0.0.1:${BACKEND_PORT}/docs"
      echo "   Health  : http://127.0.0.1:${BACKEND_PORT}/health"
      echo "========================================"
      echo
      if [ "${AUTO_OPEN_BROWSER}" = "1" ] && command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:${BACKEND_PORT}" >/dev/null 2>&1 || true
      fi
      exit 0
    fi
  fi

  sleep 1
done

echo "[Info] Service started (PID=${STARTED_PID})."
echo "[Info] If the page cannot open yet, check log: ${LOG_FILE}"
echo "[Info] App URL: http://127.0.0.1:${BACKEND_PORT}"
