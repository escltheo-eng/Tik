"""Fixtures pytest partagées.

Utilise une DB Postgres éphémère (via fixture) ou SQLite en mémoire
si Postgres n'est pas disponible. Les tests d'intégration nécessitent
un Postgres réel (docker-compose up postgres).
"""

import asyncio
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


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    """Engine DB — réutilise la config de test.

    Pour les tests unitaires du health endpoint et logique pure, on peut
    juste ne pas appeler ce fixture.
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
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
