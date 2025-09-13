#!/usr/bin/env bash
set -euo pipefail

echo "[NVL-ADDON] Starting..."
exec python3 /app/listener.py
