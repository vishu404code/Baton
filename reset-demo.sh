#!/usr/bin/env bash
# Wipe ALL Baton data (database volume + demo tokens) and start fresh with demo data.
set -euo pipefail
cd "$(dirname "$0")"

if [ "${1:-}" != "-y" ]; then
  read -r -p "This deletes every room, record and agent token in Baton. Continue? [y/N] " ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "Cancelled."; exit 0 ;; esac
fi

docker compose down -v
rm -f .baton/demo.json
exec ./start.sh
