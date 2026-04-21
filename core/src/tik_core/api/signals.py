"""Endpoints signals : récupération des signaux émis par Tik."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.storage.database import get_session
from tik_core.storage.models import Signal
from tik_core.storage.schemas import SignalOut

router = APIRouter(prefix="/signals")


@router.get("/latest", response_model=list[SignalOut])
async def get_latest_signals(
    entity: str | None = Query(None, description="Filter by entity id (ex: BTC)"),
    horizon: str | None = Query(None, pattern="^(flash|swing|macro)$"),
    limit: int = Query(20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> list[Signal]:
    """Derniers signaux émis (ordre antéchronologique).

    Les signaux expirés sont inclus : c'est au client de vérifier `expiry`
    et le flag `circuit_breaker_status`.
    """
    stmt = select(Signal).order_by(Signal.timestamp.desc()).limit(limit)
    if entity:
        stmt = stmt.where(Signal.entity_id == entity)
    if horizon:
        stmt = stmt.where(Signal.horizon == horizon)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/{signal_id}", response_model=SignalOut)
async def get_signal(
    signal_id: str,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> Signal:
    signal = await session.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return signal


@router.get("", response_model=list[SignalOut])
async def search_signals(
    entity: str | None = None,
    horizon: str | None = Query(None, pattern="^(flash|swing|macro)$"),
    direction: str | None = Query(None, pattern="^(long|short|neutral)$"),
    min_confidence: float = Query(0.0, ge=0, le=1),
    min_veracity: float = Query(0.0, ge=0, le=1),
    since_hours: int = Query(24, ge=1, le=720),
    limit: int = Query(100, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> list[Signal]:
    """Recherche signaux avec filtres."""
    since = datetime.utcnow() - timedelta(hours=since_hours)
    stmt = (
        select(Signal)
        .where(Signal.timestamp >= since)
        .where(Signal.confidence >= min_confidence)
        .where(Signal.veracity >= min_veracity)
        .order_by(Signal.timestamp.desc())
        .limit(limit)
    )
    if entity:
        stmt = stmt.where(Signal.entity_id == entity)
    if horizon:
        stmt = stmt.where(Signal.horizon == horizon)
    if direction:
        stmt = stmt.where(Signal.direction == direction)
    result = await session.execute(stmt)
    return list(result.scalars().all())
