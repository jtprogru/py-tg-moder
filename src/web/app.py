# -*- coding: utf-8 -*-
"""FastAPI application for the admin dashboard.

The app runs in the same process (and event loop) as the bot and reads the
same ``Storage`` singleton. The PTB ``Application`` is stored in ``app.state``
so routes can reach the Bot API (chat titles now; moderation actions in a
later stage).
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from core import config
from web.routes.auth_routes import router as auth_router
from web.routes.dashboard import router as dashboard_router
from web.templating import STATIC_DIR


def create_app(application=None) -> FastAPI:
    """Build the dashboard app; ``application`` is the running PTB Application."""
    if not config.WEB_SESSION_SECRET:
        raise RuntimeError("WEB_SESSION_SECRET must be set when the web dashboard is enabled")

    app = FastAPI(title="py-tg-moder", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.application = application
    app.state.chat_titles = {}  # chat_id -> title, best-effort cache

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    async def healthz() -> dict:
        """Unauthenticated liveness/readiness probe."""
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    return app
