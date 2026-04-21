"""Publisher : persiste les signaux en DB et les publie sur Redis.

Utilisé par les engines (swing, flash, macro) pour émettre un signal.
"""

import json
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

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


async def publish_swing_signal(
    session: AsyncSession,
    redis: Redis,
    decision: SwingDecision,
    veracity: float = 0.85,
) -> Signal:
    """Persiste et publie un signal swing."""
    signal_id = _make_signal_id("swing", decision.entity_id)
    expiry = datetime.utcnow() + EXPIRY_BY_HORIZON["swing"]

    signal = Signal(
        id=signal_id,
        timestamp=decision.timestamp,
        entity_id=decision.entity_id,
        horizon="swing",
        direction=decision.direction,
        confidence=decision.confidence,
        veracity=veracity,
        hypothesis=decision.hypothesis,
        counter_scenarios=decision.counter_scenarios,
        evidence=decision.evidence,
        triggers=decision.triggers,
        sources_count=len({e["source"] for e in decision.evidence}),
        expiry=expiry,
        advisory={},
        circuit_breaker_status="ok",
    )
    session.add(signal)
    await session.flush()

    # Publie sur Redis
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
