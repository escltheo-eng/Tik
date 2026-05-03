"""Publisher : persiste les signaux en DB et les publie sur Redis.

Utilisé par les engines (swing, flash, macro) pour émettre un signal.
"""

import json
import uuid
from datetime import datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.scoring.flash_engine import FlashDecision
from tik_core.scoring.swing_engine import SwingDecision
from tik_core.storage.models import Signal

log = structlog.get_logger()

# Durées d'expiry par horizon (valeurs par défaut, override en config)
EXPIRY_BY_HORIZON = {
    "flash": timedelta(hours=1),
    "swing": timedelta(days=7),
    "macro": timedelta(days=30),
}


def _make_signal_id(horizon: str, entity_id: str) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"TIK-{horizon.upper()}-{entity_id}-{ts}-{short}"


async def _publish_signal(
    session: AsyncSession,
    redis: Redis,
    decision: SwingDecision | FlashDecision,
    horizon: str,
    veracity: float | None = None,
) -> Signal:
    """Logique commune de persistance + publication, partagée swing/flash/macro.

    La veracity provient de `decision.veracity` (calculée par l'engine via
    cross-validation). Le paramètre `veracity` reste accepté pour override.
    """
    signal_id = _make_signal_id(horizon, decision.entity_id)
    expiry = datetime.utcnow() + EXPIRY_BY_HORIZON[horizon]
    final_veracity = veracity if veracity is not None else decision.veracity

    decision_advisory = getattr(decision, "advisory", None)
    if not isinstance(decision_advisory, dict):
        decision_advisory = {}

    signal = Signal(
        id=signal_id,
        timestamp=decision.timestamp,
        entity_id=decision.entity_id,
        horizon=horizon,
        direction=decision.direction,
        confidence=decision.confidence,
        veracity=final_veracity,
        hypothesis=decision.hypothesis,
        counter_scenarios=decision.counter_scenarios,
        evidence=decision.evidence,
        triggers=decision.triggers,
        sources_count=len({e["source"] for e in decision.evidence}),
        expiry=expiry,
        advisory=decision_advisory,
        circuit_breaker_status=getattr(decision, "circuit_breaker_status", "ok"),
    )
    session.add(signal)
    await session.flush()

    payload = {
        "id": signal.id,
        "timestamp": signal.timestamp.isoformat(),
        "entity_id": signal.entity_id,
        "horizon": signal.horizon,
        "direction": signal.direction,
        "confidence": signal.confidence,
        "veracity": signal.veracity,
        "hypothesis": signal.hypothesis,
        "counter_scenarios": signal.counter_scenarios,
        "evidence": signal.evidence,
        "triggers": signal.triggers,
        "sources_count": signal.sources_count,
        "expiry": signal.expiry.isoformat() if signal.expiry else None,
        "advisory": signal.advisory,
        "circuit_breaker_status": signal.circuit_breaker_status,
    }
    channel = f"tik.signal.{signal.entity_id}.{signal.horizon}"
    await redis.publish(channel, json.dumps(payload))

    log.info(
        "signal.published",
        id=signal.id,
        entity=signal.entity_id,
        horizon=signal.horizon,
        direction=signal.direction,
        confidence=signal.confidence,
    )
    return signal


async def publish_swing_signal(
    session: AsyncSession,
    redis: Redis,
    decision: SwingDecision,
    veracity: float | None = None,
) -> Signal:
    """Persiste et publie un signal swing."""
    return await _publish_signal(session, redis, decision, "swing", veracity)


async def publish_flash_signal(
    session: AsyncSession,
    redis: Redis,
    decision: FlashDecision,
    veracity: float | None = None,
) -> Signal:
    """Persiste et publie un signal flash."""
    return await _publish_signal(session, redis, decision, "flash", veracity)
