#!/bin/sh
set -e
echo "Starting WAGO NVL Listener..."
exec python3 /app/listener.py
