"""Tik Core — FastAPI app factory.

Point d'entrée principal. Compose les routers, middlewares, et services.
"""

import logging
import re
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from tik_core import __version__
from tik_core.api import (
    derivatives,
    entities,
    feedback,
    headlines,
    health,
    macro,
    macro_events,
    manual_trades,
    metrics,
    polymarket,
    signals,
    tradingview,
    veracity,
    ws,
)
from tik_core.config import get_settings
from tik_core.storage.database import close_engine, init_engine

# Endpoints qui n'exigent pas de clé API (cadenas masqué dans Swagger).
PUBLIC_PATHS: set[str] = {"/api/v1/health"}

# Motif d'une clé API passée en query string (ex. `?api_key=tik_xxx`).
# La valeur s'arrête au prochain séparateur d'URL, guillemet ou espace.
_API_KEY_QUERY_RE = re.compile(r"(api_key=)[^&\s\"']+")


def _redact_api_key(text: str) -> str:
    """Masque la valeur d'une clé API dans une chaîne (URL, ligne de log).

    Fonction pure : `api_key=tik_secret` → `api_key=***REDACTED***`, le reste
    de la chaîne (autres paramètres, méthode, status) est préservé.
    """
    return _API_KEY_QUERY_RE.sub(r"\1***REDACTED***", text)


class ApiKeyRedactionFilter(logging.Filter):
    """Redacte la clé API des logs uvicorn (audit 2026-07-02, constat A-1/E2E-2).

    L'auth WebSocket passe la clé en query string (`?api_key=...`, compromis
    navigateur assumé — cf. api/ws.py) et uvicorn logue l'URL complète : sans
    ce filtre, quiconque lit `docker compose logs core` récupère une clé
    valide en clair. On nettoie `record.msg` ET `record.args` (uvicorn passe
    le path en argument de format `%s`, dans un tuple).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str) and "api_key=" in record.msg:
            record.msg = _redact_api_key(record.msg)
        args = record.args
        if isinstance(args, tuple) and any(isinstance(a, str) and "api_key=" in a for a in args):
            record.args = tuple(_redact_api_key(a) if isinstance(a, str) else a for a in args)
        return True


def _configure_logging(log_level: str) -> None:
    """Configure structlog + stdlib logging + redaction des clés API."""
    logging.basicConfig(level=log_level, format="%(message)s")
    # Les loggers uvicorn (accès HTTP + connexions WebSocket) loguent l'URL
    # complète, y compris `?api_key=...` : on installe le filtre de redaction.
    # Idempotent : pas de doublon si `create_app()` est rappelé (tests).
    for uvicorn_logger_name in ("uvicorn.access", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(uvicorn_logger_name)
        if not any(isinstance(f, ApiKeyRedactionFilter) for f in uvicorn_logger.filters):
            uvicorn_logger.addFilter(ApiKeyRedactionFilter())
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
        # En production, le schéma OpenAPI est masqué comme docs/redoc (audit
        # 2026-07-02) : le VPS expose IP:8200, inutile d'offrir la carte des
        # 37 routes à un scanner. En dev, l'override `custom_openapi` ci-dessous
        # (Bug 5, bouton Authorize Swagger) continue de fonctionner.
        openapi_url="/openapi.json" if not settings.is_production else None,
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
    app.include_router(macro.router, prefix=prefix, tags=["macro"])
    app.include_router(metrics.router, prefix=prefix, tags=["metrics"])
    app.include_router(polymarket.router, prefix=prefix, tags=["polymarket"])
    app.include_router(derivatives.router, prefix=prefix, tags=["derivatives"])
    app.include_router(tradingview.router, prefix=prefix, tags=["tradingview"])
    app.include_router(manual_trades.router, prefix=prefix, tags=["manual_trades"])
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
