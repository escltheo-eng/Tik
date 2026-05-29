"""Tik Core — FastAPI app factory.

Point d'entrée principal. Compose les routers, middlewares, et services.
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from tik_core import __version__
from tik_core.api import (
    entities,
    feedback,
    headlines,
    health,
    macro_events,
    macro_reading,
    metrics,
    polymarket,
    signals,
    veracity,
    ws,
)
from tik_core.config import get_settings
from tik_core.storage.database import close_engine, init_engine

# Endpoints qui n'exigent pas de clé API (cadenas masqué dans Swagger).
PUBLIC_PATHS: set[str] = {"/api/v1/health"}


def _configure_logging(log_level: str) -> None:
    """Configure structlog + stdlib logging."""
    logging.basicConfig(level=log_level, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001 — signature imposée par FastAPI lifespan
    """Gère le cycle de vie : init DB, Redis, cleanup."""
    settings = get_settings()
    log = structlog.get_logger()
    log.info("tik.startup", version=__version__, env=settings.env)

    # Init engine DB
    await init_engine(settings.database_url)
    log.info("tik.db.initialized", host=settings.db_host)

    yield

    # Cleanup
    await close_engine()
    log.info("tik.shutdown")


def create_app() -> FastAPI:
    """Factory FastAPI."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title="Tik Core",
        description="Moteur OSINT modulaire — agrégation, scoring, signaux.",
        version=__version__,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routers
    prefix = "/api/v1"
    app.include_router(health.router, prefix=prefix, tags=["health"])
    app.include_router(entities.router, prefix=prefix, tags=["entities"])
    app.include_router(signals.router, prefix=prefix, tags=["signals"])
    app.include_router(veracity.router, prefix=prefix, tags=["veracity"])
    app.include_router(feedback.router, prefix=prefix, tags=["feedback"])
    app.include_router(headlines.router, prefix=prefix, tags=["headlines"])
    app.include_router(macro_events.router, prefix=prefix, tags=["macro_events"])
    app.include_router(macro_reading.router, prefix=prefix, tags=["macro_reading"])
    app.include_router(metrics.router, prefix=prefix, tags=["metrics"])
    app.include_router(polymarket.router, prefix=prefix, tags=["polymarket"])
    app.include_router(ws.router, prefix=prefix, tags=["websocket"])

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        schema.setdefault("components", {})["securitySchemes"] = {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "API Key",
                "description": (
                    "Clé API au format `tik_xxxxx`. "
                    "Coller juste la clé brute, sans le préfixe `Bearer `."
                ),
            }
        }
        for path, path_item in schema.get("paths", {}).items():
            if path in PUBLIC_PATHS:
                continue
            for method, operation in path_item.items():
                if method.lower() not in {"get", "post", "put", "delete", "patch"}:
                    continue
                operation.setdefault("security", [{"bearerAuth": []}])

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
    return app


app = create_app()
