#!/usr/bin/env bash
set -euo pipefail

echo "Jarvis AI Assistant setup"
command -v python3 >/dev/null 2>&1 || {
  echo "Python 3.10 or newer is required."
  exit 1
}

if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi

".venv/bin/python" -m pip install -r requirements.txt
echo "Starting Jarvis at http://127.0.0.1:8765 (press Ctrl+C to stop)"
exec ".venv/bin/python" jarvis_server.py
