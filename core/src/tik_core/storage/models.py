"""Modèles SQLAlchemy pour Tik Core.

Note : les tables time-series (signal_history, price_ticks) sont des
hypertables TimescaleDB, configurées dans les migrations Alembic.
"""

from datetime import datetime
from enum import Enum as PyEnum
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base déclarative SQLAlchemy."""


# ----- Enums -----

class DomainType(str, PyEnum):
    TRADING = "trading"
    BETTING = "betting"
    POLITICS = "politics"
    WEATHER = "weather"
    GENERIC = "generic"


class HorizonType(str, PyEnum):
    FLASH = "flash"
    SWING = "swing"
    MACRO = "macro"


class DirectionType(str, PyEnum):
    LONG = "long"
    SHORT = "short"
    NEUTRAL = "neutral"


# ----- Tables -----

class Entity(Base):
    """Entité observable (BTC, GOLD, event_X)."""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    namespace: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    signals: Mapped[list["Signal"]] = relationship(back_populates="entity")


class Source(Base):
    """Source de données (Binance, Reuters, Polymarket…).

    Le score de crédibilité évolue dans le temps (via feedback et audit).
    """

    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    base_veracity: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    current_veracity: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    tier: Mapped[int] = mapped_column(Integer, default=3)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Signal(Base):
    """Signal émis par Tik Core (un par entity, par horizon, par instant)."""

    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )
    entity_id: Mapped[str] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    horizon: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    veracity: Mapped[float] = mapped_column(Float, nullable=False)

    hypothesis: Mapped[str | None] = mapped_column(Text)
    counter_scenarios: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    triggers: Mapped[list] = mapped_column(JSON, default=list)

    sources_count: Mapped[int] = mapped_column(Integer, default=0)
    expiry: Mapped[datetime | None] = mapped_column(DateTime)

    advisory: Mapped[dict] = mapped_column(JSON, default=dict)
    circuit_breaker_status: Mapped[str] = mapped_column(String(32), default="ok")

    entity: Mapped[Entity] = relationship(back_populates="signals")


class Feedback(Base):
    """Retour d'un client (bot) sur le PnL d'un signal appliqué."""

    __tablename__ = "feedbacks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    signal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    signal_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    trade_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    pnl_points: Mapped[float | None] = mapped_column(Float)
    pnl_pct: Mapped[float | None] = mapped_column(Float)
    duration_held_s: Mapped[int | None] = mapped_column(Integer)
    exit_reason: Mapped[str | None] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ApiKey(Base):
    """Clé API pour authentification des SDK clients.

    Hash stocké, jamais la clé en clair. Le suffixe est conservé pour affichage.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    key_suffix: Mapped[str] = mapped_column(String(8), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)
