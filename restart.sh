#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${PACKAGE_DIR}/stop.sh"
sleep 2
"${PACKAGE_DIR}/start.sh"
