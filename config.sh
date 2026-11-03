#!/usr/bin/env bash
# CPA Linux package config
# Run ./restart.sh after editing

# Service port
BACKEND_PORT="8000"

# Bind address
BACKEND_HOST="0.0.0.0"

# Linux uses system Python by default. Do not point this to the bundled Windows python directory.
PYTHON_BIN="python3"

# Browser auto-open: 1=yes, 0=no
AUTO_OPEN_BROWSER="0"

# Linux runtime files
PID_FILE="${PACKAGE_DIR}/runtime/linux-cpa.pid"
LOG_FILE="${PACKAGE_DIR}/runtime/logs/linux-backend.log"
