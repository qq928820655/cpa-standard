#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="8000"
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
echo "   CPA - Linux Stop"
echo "========================================"
echo

if [ ! -f "${PID_FILE}" ]; then
  echo "[Info] PID file not found. Service may not be running."
  exit 0
fi

PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
if [ -z "${PID}" ]; then
  echo "[Info] PID file is empty. Cleaning it."
  rm -f "${PID_FILE}"
  exit 0
fi

if ! kill -0 "${PID}" >/dev/null 2>&1; then
  echo "[Info] Process ${PID} is not running. Cleaning PID file."
  rm -f "${PID_FILE}"
  exit 0
fi

echo "[Stop] Service PID ${PID}..."
kill -TERM "${PID}"

for _ in $(seq 1 15); do
  if ! kill -0 "${PID}" >/dev/null 2>&1; then
    rm -f "${PID_FILE}"
    echo "[Done] Service stopped."
    exit 0
  fi
  sleep 1
done

echo "[Warn] Graceful stop timed out, sending SIGTERM again."
kill -TERM "${PID}" >/dev/null 2>&1 || true
for _ in 1 2 3 4 5; do
  if ! kill -0 "${PID}" >/dev/null 2>&1; then
    rm -f "${PID_FILE}"
    echo "[Done] Service stopped."
    exit 0
  fi
  sleep 1
done

echo "[Warn] Process ${PID} is still running, sending SIGKILL."
kill -KILL "${PID}" >/dev/null 2>&1 || true
for _ in 1 2 3 4 5; do
  if ! kill -0 "${PID}" >/dev/null 2>&1; then
    rm -f "${PID_FILE}"
    echo "[Done] Service stopped."
    exit 0
  fi
  sleep 1
done

echo "[Warn] Unable to stop process ${PID}."
echo "[Hint] Check log: ${LOG_FILE}"
exit 1
