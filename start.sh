#!/usr/bin/env bash
# Start Baton (Postgres + backend) in Docker, seed demo data if empty, print connection info.
set -euo pipefail
cd "$(dirname "$0")"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
fail() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || fail "Docker is not installed. Install Docker Desktop (or OrbStack) and run ./start.sh again."
docker info >/dev/null 2>&1 || fail "Docker is installed but not running. Start Docker Desktop and try again."

if [ ! -f .env ]; then
  cp .env.example .env
  info "Created .env from .env.example"
fi
mkdir -p .baton

set -a; . ./.env; set +a
PORT="${BATON_PORT:-8000}"
API_URL="http://localhost:${PORT}"
PUBLIC_URL="${BATON_PUBLIC_URL:-$API_URL}"

bold "▶ Building and starting containers"
docker compose up --build -d

bold "▶ Waiting for ${API_URL}/health"
for i in $(seq 1 90); do
  if curl -fsS "${API_URL}/health" >/dev/null 2>&1; then
    info "Backend is healthy"
    break
  fi
  if [ "$i" -eq 90 ]; then
    docker compose logs --tail 50 backend
    fail "Backend did not become healthy in 90s (logs above)."
  fi
  sleep 1
done

if [ -f scripts/seed_demo.py ]; then
  bold "▶ Seeding demo data (only if the database is empty)"
  docker compose exec -T backend python scripts/seed_demo.py --if-empty
else
  info "(seed script not written yet; skipping demo data)"
fi

echo
bold "✔ Baton is running"
info "API:          ${API_URL}"
info "API docs:     ${API_URL}/docs"
info "WebSocket:    ${API_URL/http/ws}/ws/rooms/{room_id}"
info "MCP (agents): ${PUBLIC_URL%/}/mcp"
info "Frontend dev: http://localhost:5173 (run it from frontend/)"

if [ -f .baton/demo.json ]; then
  echo
  docker compose exec -T backend python scripts/seed_demo.py --print
fi
echo
info "Stop with ./stop.sh · wipe and re-seed with ./reset-demo.sh"
