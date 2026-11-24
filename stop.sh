#!/usr/bin/env bash
# Stop Baton. Data is kept in the baton_pgdata volume.
set -euo pipefail
cd "$(dirname "$0")"
docker compose down
echo "Baton stopped. Data is kept; ./start.sh brings it back."
