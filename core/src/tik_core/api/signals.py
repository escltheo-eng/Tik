"""Endpoints signals : récupération des signaux émis par Tik + ingestion micro."""

from dataclasses import dataclass
from datetime import datetime, timedelta

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.scoring.publisher import _publish_signal
from tik_core.storage.database import get_session
from tik_core.storage.models import Signal
from tik_core.storage.schemas import MicroSignalIn, SignalOut
from tik_core.utils.time import now_utc, now_utc_naive

router = APIRouter(prefix="/signals")


@dataclass
class _IngestedMicroDecision:
    """Objet décision minimal pour réutiliser `publisher._publish_signal`.

    Expose exactement les attributs que le publisher lit (entity_id, timestamp,
    direction, confidence, veracity, hypothesis, counter_scenarios, evidence,
    triggers, advisory, circuit_breaker_status). Pas un SwingDecision/FlashDecision
    mais duck-typé — le publisher ne dépend que de ces champs.
    """

    entity_id: str
    timestamp: datetime
    direction: str
    confidence: float
    veracity: float
    hypothesis: str | None
    counter_scenarios: list[dict]
    evidence: list[dict]
    triggers: list[dict]
    advisory: dict
    circuit_breaker_status: str = "degraded"


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
    since = now_utc_naive() - timedelta(hours=since_hours)
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


@router.post("/ingest", response_model=SignalOut, status_code=201)
async def ingest_micro_signal(
    payload: MicroSignalIn,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("write:signals")),
) -> Signal:
    """Ingère un signal externe 'micro' (couche ML btc-research-lab) — SHADOW.

    Fusion macro+micro (ADR-030), Étape 2. Le signal est TOUJOURS persisté en
    `horizon='micro'` et marqué `circuit_breaker_status='degraded'` (shadow strict) :
    l'appelant ne peut PAS injecter un faux signal swing/flash. Il est stocké et
    publié sur Redis (`tik.signal.{entity}.micro`) comme tout signal, donc visible
    via l'API et le WebSocket — mais n'alimente AUCUN moteur OSINT (NO-GO inchangé).

    Réutilise `publisher._publish_signal` (mêmes garanties timezone/DB/Redis que
    les signaux internes). La veracity n'est PAS gonflée : défaut conservateur
    0.70 si l'appelant n'en fournit pas (Axe #1 — pas de vernis de certitude).
    """
    decision = _IngestedMicroDecision(
        entity_id=payload.entity_id.upper(),
        timestamp=now_utc(),
        direction=payload.direction,
        confidence=payload.confidence,
        veracity=payload.veracity if payload.veracity is not None else 0.70,
        hypothesis=payload.hypothesis,
        counter_scenarios=[cs.model_dump() for cs in payload.counter_scenarios],
        evidence=[e.model_dump() for e in payload.evidence],
        triggers=[t.model_dump() for t in payload.triggers],
        advisory=dict(payload.advisory),
        circuit_breaker_status="degraded",  # shadow strict — non négociable
    )
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        signal = await _publish_signal(session, redis, decision, "micro")
    finally:
        await redis.aclose()
    return signal
