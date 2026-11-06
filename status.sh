#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="8000"
BACKEND_HOST="0.0.0.0"
PYTHON_BIN="python3"
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
echo "   CPA - Linux Status"
echo "========================================"
echo

echo "[Config] Service port: ${BACKEND_PORT}"
echo "[Config] Bind host   : ${BACKEND_HOST}"
echo "[Info] Runtime       : ${PYTHON_BIN}"
echo "[Info] PID file      : ${PID_FILE}"
echo "[Info] Log file      : ${LOG_FILE}"
echo

if [ -f "${PID_FILE}" ]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [ -n "${PID}" ] && kill -0 "${PID}" >/dev/null 2>&1; then
    echo "[OK] Process is running (PID=${PID})."
  else
    echo "[Warn] PID file exists but process is not running."
  fi
else
  echo "[Info] PID file not found. Service may not be running."
fi

if command -v curl >/dev/null 2>&1; then
  echo
  if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    echo "[OK] Health check passed: http://127.0.0.1:${BACKEND_PORT}/health"
  else
    echo "[Warn] Health check failed: http://127.0.0.1:${BACKEND_PORT}/health"
  fi
fi
