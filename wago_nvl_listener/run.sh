#!/bin/sh
set -e
echo "Starting WAGO NVL Listener..."
exec python /app/listener.py
