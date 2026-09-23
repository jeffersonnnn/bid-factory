#!/bin/sh
set -eu
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.lock
fi
if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi
exec .venv/bin/python scripts/serve.py
