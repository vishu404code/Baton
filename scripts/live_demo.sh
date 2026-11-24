#!/usr/bin/env bash
# Trigger one live demo moment while the UI is open: handoff | decision | redo | crash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T backend python scripts/live_demo.py "${1:-}"
