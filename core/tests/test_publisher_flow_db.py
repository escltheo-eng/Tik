"""Tests du flux métier de `publisher` (comble un gap — 2026-06-01).

`test_publisher_timezone_db.py` couvre la régression Bug 9 (tzinfo asyncpg)
mais pas le **métier** : dédup de `sources_count`, nom du canal Redis publié,
et forme du payload JSON (suffixe `Z` sur les datetimes pour les clients).
Ces assertions verrouillent le contrat que consomment le dashboard et le SDK.

Pré-requis : Postgres `tik_test` (fixture `db_session`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.scoring.publisher import publish_swing_signal
from tik_core.scoring.swing_engine import SwingDecision
from tik_core.storage.models import Entity, Signal


class _FakeRedis:
    """Capture les publications pour inspection (pas de Redis réel)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, data: str) -> int:
        self.published.append((channel, data))
        return 0


@pytest_asyncio.fixture
async def ensure_btc(db_session: AsyncSession):
    if await db_session.get(Entity, "BTC") is None:
        db_session.add(Entity(id="BTC", domain="crypto", namespace="binance"))
        await db_session.commit()
    inserted: list[str] = []
    yield inserted
    for sid in inserted:
        await db_session.execute(Signal.__table__.delete().where(Signal.id == sid))
    await db_session.commit()


def _decision() -> SwingDecision:
    return SwingDecision(
        entity_id="BTC",
        timestamp=datetime(2026, 5, 19, 14, 30, tzinfo=UTC),
        direction="short",
        confidence=0.42,
        hypothesis="flux-test",
        veracity=0.88,
        counter_scenarios=[],
        # 3 lignes mais seulement 2 sources distinctes → sources_count == 2.
        evidence=[
            {"source": "fear_greed", "score": 0.65, "fact": "a"},
            {"source": "fear_greed", "score": 0.65, "fact": "b"},
            {"source": "google_news_rss", "score": 0.70, "fact": "c"},
        ],
        triggers=[],
        circuit_breaker_status="ok",
        advisory={},
    )


@pytest.mark.asyncio
async def test_sources_count_deduplicates_evidence_sources(
    db_session: AsyncSession, ensure_btc: list[str]
) -> None:
    redis = _FakeRedis()
    signal = await publish_swing_signal(db_session, redis, _decision())
    await db_session.commit()
    ensure_btc.append(signal.id)

    assert signal.sources_count == 2  # 3 evidences, 2 sources distinctes


@pytest.mark.asyncio
async def test_publishes_on_canonical_channel_with_z_suffixed_payload(
    db_session: AsyncSession, ensure_btc: list[str]
) -> None:
    redis = _FakeRedis()
    signal = await publish_swing_signal(db_session, redis, _decision())
    await db_session.commit()
    ensure_btc.append(signal.id)

    assert len(redis.published) == 1
    channel, raw = redis.published[0]
    assert channel == "tik.signal.BTC.swing"

    payload = json.loads(raw)
    assert payload["id"] == signal.id
    assert payload["direction"] == "short"
    assert payload["entity_id"] == "BTC"
    # Contrat ADR-013 : les datetimes du payload portent le suffixe Z (UTC).
    assert payload["timestamp"].endswith("Z")
    assert payload["expiry"].endswith("Z")
    # Le moment UTC est préservé (14:30 passé en aware UTC).
    assert payload["timestamp"].startswith("2026-05-19T14:30:00")
