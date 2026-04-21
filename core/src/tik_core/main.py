"""Tik Core — FastAPI app factory.

Point d'entrée principal. Compose les routers, middlewares, et services.
"""

import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tik_core import __version__
from tik_core.api import entities, feedback, health, signals, veracity, ws
from tik_core.config import get_settings
from tik_core.storage.database import close_engine, init_engine


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
async def lifespan(app: FastAPI):
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
    app.include_router(ws.router, prefix=prefix, tags=["websocket"])

    return app


app = create_app()
