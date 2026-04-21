"""Gestion du moteur SQLAlchemy async."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


async def init_engine(database_url: str) -> None:
    """Initialise le moteur et le session maker."""
    global _engine, _session_maker
    _engine = create_async_engine(
        database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )
    _session_maker = async_sessionmaker(_engine, expire_on_commit=False)


async def close_engine() -> None:
    """Ferme proprement les connexions."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dépendance FastAPI pour récupérer une session."""
    if _session_maker is None:
        raise RuntimeError("DB engine not initialized")
    async with _session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
