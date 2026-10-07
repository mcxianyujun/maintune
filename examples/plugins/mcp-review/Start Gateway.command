#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
cd "$(dirname "$0")"
command -v python3 >/dev/null 2>&1 || { echo 'Python 3.12 or newer is required.'; exit 1; }
if [ ! -f .private/gateway.json ]; then
  python3 setup_gateway.py
fi
exec python3 gateway.py
