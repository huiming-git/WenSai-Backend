#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENTSDK_DIR="$ROOT/WenSai-AgentSDK"
if [ ! -d "$AGENTSDK_DIR" ]; then
  AGENTSDK_DIR="$ROOT/WenSai-AgentSdk"
fi

cd "$ROOT/WenSai-Backend"
uv venv --python 3.12 --seed .venv
uv pip install --python .venv/bin/python -r requirements.txt

cd "$AGENTSDK_DIR"
uv venv --python 3.12 --seed .venv
uv pip install --python .venv/bin/python -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
fi

cd "$ROOT/WenSai-App"
npm install

echo "Local dependencies are ready."
