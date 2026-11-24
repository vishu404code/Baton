"""Baton FastAPI app. Mounts the REST API, the room WebSocket and the MCP server (/mcp)."""

import asyncio
import logging
from contextlib import asynccontextmanager

import anyio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.routing import Route

from app import __version__
from app import logging_filters, ws
from app.api import agents, approvals, context, evidence, providers, records, rooms, runs, session
from app.config import get_settings
from app.db import SessionLocal, db_ok, init_db
from app.errors import install_error_handlers
from app.mcp_server import mcp_endpoint
from app.services import claims as claim_svc
from app.services import presence
from app.services.events import bus

settings = get_settings()
log = logging.getLogger("baton")
logging_filters.install()


def _sweep_once() -> int:
    with SessionLocal() as db:
        n = claim_svc.expire_due(db)
        db.commit()
        return n


async def _lease_sweeper() -> None:
    while True:
        await asyncio.sleep(settings.baton_lease_sweep_seconds)
        try:
            await anyio.to_thread.run_sync(_sweep_once)
        except Exception:  # keep sweeping even if one pass fails (e.g. DB restarting)
            log.exception("lease sweep failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    bus.loop = asyncio.get_running_loop()
    session_manager = mcp_endpoint.new_app()
    background = [asyncio.create_task(_lease_sweeper()), asyncio.create_task(presence.watcher())]
    try:
        async with session_manager.run():
            yield
    finally:
        for task in background:
            task.cancel()


app = FastAPI(
    title="Baton",
    version=__version__,
    description="Shared memory and handoff layer for AI coding agents. See docs/API_CONTRACT.md.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Dev: also allow any localhost / 127.0.0.1 / LAN origin on any port (Vite may pick another port).
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|\[::1\]|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
install_error_handlers(app)

for module in (session, rooms, agents, records, approvals, evidence, providers, runs, context, ws):
    app.include_router(module.router)

# MCP over Streamable HTTP, for agents. Both /mcp and /mcp/ work (no redirect for POST).
app.router.routes.append(Route("/mcp", endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"], include_in_schema=False))
app.router.routes.append(Route("/mcp/", endpoint=mcp_endpoint, methods=["GET", "POST", "DELETE"], include_in_schema=False))


@app.get("/health", tags=["meta"])
def health() -> JSONResponse:
    ok = db_ok()
    body = {"status": "ok" if ok else "degraded", "db": "ok" if ok else "unreachable", "version": __version__}
    return JSONResponse(body, status_code=200 if ok else 503)


# Desktop app: serve the built UI from the same origin as the API (added last so it never shadows a route).
if settings.baton_static_dir:
    from pathlib import Path

    from fastapi.staticfiles import StaticFiles

    _static = Path(settings.baton_static_dir)
    if _static.is_dir():
        app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
