"""Fixtures pytest partagées.

Utilise une DB Postgres éphémère (via fixture) ou SQLite en mémoire
si Postgres n'est pas disponible. Les tests d'intégration nécessitent
un Postgres réel (docker-compose up postgres).
"""

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("TIK_ENV", "development")
os.environ.setdefault("TIK_SECRET_KEY", "test-secret-key-32-chars-long!!")
os.environ.setdefault("TIK_DB_HOST", "localhost")
os.environ.setdefault("TIK_DB_NAME", "tik_test")
os.environ.setdefault("TIK_DB_USER", "tik")
os.environ.setdefault("TIK_DB_PASSWORD", "tik_dev")
os.environ.setdefault("TIK_REDIS_HOST", "localhost")

from tik_core.config import get_settings  # noqa: E402
from tik_core.main import app  # noqa: E402
from tik_core.storage.database import init_engine, close_engine  # noqa: E402
from tik_core.storage.models import Base  # noqa: E402


def _is_test_database(db_name: str) -> bool:
    """Garde anti-production pour les fixtures qui gèrent le schéma DB.

    Les fixtures `db_engine`/`db_session` font des `create_all` (et
    historiquement un `drop_all`) sur la base de `settings.database_url`.
    Lancées par erreur dans le conteneur de production (`TIK_DB_NAME=tik`),
    elles pourraient détruire les signaux réels — near-miss constaté le
    2026-05-20 (le `drop_all` de teardown ciblait la base de prod, sauvé
    seulement par un bug de boucle d'événements concomitant).

    On n'autorise donc ces fixtures QUE sur une base dont le nom contient
    "test". La CI utilise `TIK_DB_NAME=tik_test` (cf.
    `.github/workflows/ci.yml`), et le sandbox local se lance avec
    `TIK_DB_NAME=tik_test` explicite.
    """
    return "test" in db_name.lower()


@pytest_asyncio.fixture
async def db_engine():
    """Engine DB pour les tests d'intégration nécessitant un vrai Postgres.

    Scope FONCTION (et non session) : avec pytest-asyncio >= 1.0, une
    fixture async session-scoped tourne sur une boucle d'événements
    différente de celle des tests function-scoped → asyncpg lève
    « another operation is in progress » au moment de l'INSERT. Le scope
    fonction garantit que l'engine partage la boucle du test. Coût
    négligeable : seul `test_publisher_timezone_db.py` consomme ce fixture.

    Garde anti-prod : `skip` propre si la base n'est pas une base de test,
    pour ne jamais créer/modifier le schéma de la production.

    Pas de `drop_all` en teardown : les tests nettoient leurs propres lignes
    (cf. fixture `clean_signal_row`), et `create_all` est idempotent. On
    évite ainsi l'opération destructrice qui était le foot-gun d'origine.
    """
    settings = get_settings()
    if not _is_test_database(settings.db_name):
        pytest.skip(
            f"Tests d'intégration DB désactivés sur la base '{settings.db_name}' "
            "(non-test). Relance avec TIK_DB_NAME=tik_test pour protéger la "
            "production. Cf. conftest._is_test_database + CLAUDE.md section 9."
        )
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def api_client() -> AsyncGenerator[AsyncClient, None]:
    """Client HTTP pour tests API (pas besoin de serveur)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
