"""FastAPI application factory for the Job Tracker web interface."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.web.routers import offers as offers_router

_BASE_DIR = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="Job Tracker", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")
    app.include_router(offers_router.router)

    return app


app = create_app()
