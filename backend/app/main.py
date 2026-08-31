"""FastAPI entrypoint. `uvicorn app.main:app` (run from backend/)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from . import reuse  # noqa: F401 — sys.path shim for the reused repo modules
from .admin_schema import ensure_admin_schema
from .config import get_settings
from .db import close_pool, init_pool
from .routers import (
    analytics,
    connections,
    explore,
    filters,
    matching,
    oauth,
    overview,
    po_admin,
    po_docs,
    po_edit,
    pricing,
    quality,
    review,
    settings as settings_router,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    import doc_storage  # repo root, via app.reuse

    init_pool()
    ensure_admin_schema()
    _s = get_settings()
    doc_storage.configure(_s.supabase_url, _s.supabase_service_key)
    yield
    close_pool()


settings = get_settings()

app = FastAPI(
    title="PO Dashboard API",
    version="0.1.0",
    summary="Backend for the rebuilt purchase-order dashboard (replaces Streamlit).",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(overview.router)
app.include_router(analytics.router)
app.include_router(explore.router)
app.include_router(filters.router)
app.include_router(quality.router)
app.include_router(matching.router)
app.include_router(review.router)
app.include_router(po_edit.router)
app.include_router(po_admin.router)
app.include_router(po_docs.router)
app.include_router(pricing.router)
app.include_router(settings_router.router)
app.include_router(connections.router)
app.include_router(oauth.router)

_log = logging.getLogger("po-api")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Turn an unhandled error into a logged 500 that still carries the CORS
    header. Starlette's default 500 path sits *outside* CORSMiddleware, so without
    this the browser only ever sees an opaque "Failed to fetch"."""
    _log.exception("unhandled error: %s %s", request.method, request.url.path)
    headers = {}
    origin = request.headers.get("origin")
    if origin and origin in settings.origins:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        headers["Vary"] = "Origin"
    return JSONResponse(
        {"detail": f"internal server error: {type(exc).__name__}"},
        status_code=500,
        headers=headers,
    )


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "env": settings.env, "version": app.version}
