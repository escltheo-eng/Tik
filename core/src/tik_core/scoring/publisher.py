"""Publisher : persiste les signaux en DB et les publie sur Redis.

Utilisé par les engines (swing, flash, macro) pour émettre un signal.
"""

import json
import uuid
from datetime import UTC, timedelta

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.scoring.flash_engine import FlashDecision
from tik_core.scoring.swing_engine import SwingDecision
from tik_core.storage.models import Signal
from tik_core.utils.time import iso_utc, now_utc

log = structlog.get_logger()

# Durées d'expiry par horizon (valeurs par défaut, override en config)
EXPIRY_BY_HORIZON = {
    "flash": timedelta(hours=1),
    "swing": timedelta(days=7),
    "macro": timedelta(days=30),
    # "micro" : couche ML btc-research-lab (fusion macro+micro, ADR-033, SHADOW).
    # Horizon court (le moteur micro raisonne en minutes→heures) → fraîcheur 2h.
    "micro": timedelta(hours=2),
}


def _make_signal_id(horizon: str, entity_id: str) -> str:
    ts = now_utc().strftime("%Y%m%d%H%M%S")
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
    # Strip tzinfo avant insertion DB : Signal.timestamp et Signal.expiry sont
    # DateTime sans timezone=True (TIMESTAMP WITHOUT TIME ZONE). asyncpg lève
    # DataError sur un datetime aware au lieu de stripper silencieusement (le
    # commentaire d'utils/time.py qui prétend le contraire est obsolète). Le
    # serializer Pydantic iso_utc continue de produire `Z` à la sortie API.
    # Convertit en UTC AVANT de stripper la tzinfo : .replace(tzinfo=None) ne
    # convertit pas, il fait tomber la tz. Un futur caller passant un aware
    # non-UTC stockerait l'heure locale étiquetée UTC (régression bug 8). Tous
    # les callers actuels passent now_utc() (déjà UTC) ; on rend le strip robuste
    # pour tout futur caller (audit 2026-05-24 B4).
    timestamp_naive = (
        decision.timestamp.astimezone(UTC).replace(tzinfo=None)
        if decision.timestamp.tzinfo is not None
        else decision.timestamp
    )
    expiry = (now_utc() + EXPIRY_BY_HORIZON[horizon]).astimezone(UTC).replace(tzinfo=None)
    final_veracity = veracity if veracity is not None else decision.veracity

    decision_advisory = getattr(decision, "advisory", None)
    if not isinstance(decision_advisory, dict):
        decision_advisory = {}

    signal = Signal(
        id=signal_id,
        timestamp=timestamp_naive,
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

    # iso_utc force le suffixe `Z` même si SQLAlchemy a strippé la tzinfo
    # à l'insertion DB — garantit que les clients (dashboard, SDK) parsent
    # correctement comme UTC sans risque d'interprétation locale (cf. ADR-013).
    payload = {
        "id": signal.id,
        "timestamp": iso_utc(signal.timestamp),
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
        "expiry": iso_utc(signal.expiry),
        "advisory": signal.advisory,
        "circuit_breaker_status": signal.circuit_breaker_status,
    }
    channel = f"tik.signal.{signal.entity_id}.{signal.horizon}"
    # Publish best-effort : à ce stade le signal est `flush` mais PAS commité (le
    # commit est fait par le scheduler après retour). Sans ce try/except, une
    # panne Redis ferait remonter l'exception → rollback DB → signal entièrement
    # perdu (pas seulement raté côté WS). On préserve la ligne DB : les clients la
    # récupèrent au resync REST. Le flux temps réel reprendra au signal suivant.
    try:
        await redis.publish(channel, json.dumps(payload))
    except RedisError as exc:  # noqa: BLE001
        log.warning("signal.publish_redis_failed", id=signal.id, error=str(exc))

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
