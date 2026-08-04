from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.settings import get_settings
from app.scrapers.registry import get_all_source_names


def create_app(*, validate_config: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if validate_config:
            settings = get_settings()
            settings.require_dynamodb()
            # Load the catalog during startup so a bad target never waits until
            # the first ingestion request to produce an actionable error.
            get_all_source_names(settings)
        yield

    app = FastAPI(
        title="JobData API",
        version="0.1.0",
        lifespan=lifespan,
    )
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
