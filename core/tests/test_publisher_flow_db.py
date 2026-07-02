"""Tests du flux métier de `publisher` (comble un gap — 2026-06-01).

`test_publisher_timezone_db.py` couvre la régression Bug 9 (tzinfo asyncpg)
mais pas le **métier** : dédup de `sources_count`, nom du canal Redis publié,
et forme du payload JSON (suffixe `Z` sur les datetimes pour les clients).
Ces assertions verrouillent le contrat que consomment le dashboard et le SDK.

S'y ajoute le garde-fou **fail-fast** (audit 2026-07-02, constat E2E-1) :
`_publish_signal` valide evidence/triggers/counter_scenarios contre les
schémas de sortie (`storage/schemas.py`) AVANT insertion. Sans cette
validation, un seul signal mal formé persisté en DB faisait tomber en 500
`GET /signals/{id}` ET tout le listing `GET /signals`
(ResponseValidationError à la sérialisation).

Pré-requis : Postgres `tik_test` (fixture `db_session`).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
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


def _decision(
    *,
    evidence: list[dict] | None = None,
    triggers: list[dict] | None = None,
    counter_scenarios: list[dict] | None = None,
) -> SwingDecision:
    return SwingDecision(
        entity_id="BTC",
        timestamp=datetime(2026, 5, 19, 14, 30, tzinfo=UTC),
        direction="short",
        confidence=0.42,
        hypothesis="flux-test",
        veracity=0.88,
        counter_scenarios=counter_scenarios if counter_scenarios is not None else [],
        # Défaut : 3 lignes mais seulement 2 sources distinctes → sources_count == 2.
        evidence=evidence
        if evidence is not None
        else [
            {"source": "fear_greed", "score": 0.65, "fact": "a"},
            {"source": "fear_greed", "score": 0.65, "fact": "b"},
            {"source": "google_news_rss", "score": 0.70, "fact": "c"},
        ],
        triggers=triggers if triggers is not None else [],
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


# =============================================================================
# Fail-fast au publish (audit 2026-07-02, constat E2E-1)
# =============================================================================
# Sans la validation dans `_publish_signal`, ces payloads mal formés seraient
# persistés tels quels (colonnes JSON permissives) puis feraient tomber en 500
# `GET /signals/{id}` ET tout le listing `GET /signals` au moment de la
# sérialisation `SignalOut` (Evidence.fact, Trigger.type/value,
# CounterScenario.name obligatoires). Le fix refuse le signal AU PUBLISH avec
# une ValueError explicite — chaque test négatif échouerait sans le fix (le
# publish passerait sans lever).


@pytest.mark.asyncio
async def test_valid_payload_passes_and_is_persisted_unchanged(
    db_session: AsyncSession, ensure_btc: list[str]
) -> None:
    """Un payload conforme aux schémas traverse la validation SANS altération.

    Garantit que le fail-fast est un simple garde-fou (validation) et non une
    transformation : les dicts persistés sont ceux fournis par l'engine.
    """
    evidence = [{"source": "fear_greed", "score": 0.65, "fact": "FG=12 (extreme fear)"}]
    triggers = [{"type": "rsi", "value": "RSI oversold 24.1", "weight": 0.0}]
    counter_scenarios = [
        {"name": "macro_shock", "probability": 0.15, "mitigation": "Monitor DXY spike"},
        {"name": "whipsaw", "probability": 0.20, "mitigation": "Confirm on 1D trend"},
    ]
    redis = _FakeRedis()
    signal = await publish_swing_signal(
        db_session,
        redis,
        _decision(evidence=evidence, triggers=triggers, counter_scenarios=counter_scenarios),
    )
    await db_session.commit()
    ensure_btc.append(signal.id)

    row = (await db_session.execute(select(Signal).where(Signal.id == signal.id))).scalar_one()
    assert row.evidence == evidence
    assert row.triggers == triggers
    assert row.counter_scenarios == counter_scenarios
    assert len(redis.published) == 1


@pytest.mark.asyncio
async def test_publish_rejects_evidence_without_fact(db_session: AsyncSession) -> None:
    """Evidence sans `fact` → ValueError explicite, rien persisté ni publié.

    Pas besoin du fixture `ensure_btc` : le fail-fast lève AVANT toute
    écriture DB (aucun signal à nettoyer, la FK entité n'est jamais touchée).
    """
    redis = _FakeRedis()
    bad = _decision(evidence=[{"source": "fear_greed", "score": 0.65}])  # pas de "fact"

    with pytest.raises(ValueError, match=r"evidence\[0\]") as exc_info:
        await publish_swing_signal(db_session, redis, bad)

    assert "fact" in str(exc_info.value)
    assert redis.published == []  # fail-fast : rien ne part sur Redis


@pytest.mark.asyncio
async def test_publish_rejects_trigger_without_type_and_value(db_session: AsyncSession) -> None:
    """Trigger sans `type`/`value` → ValueError listant les champs manquants."""
    redis = _FakeRedis()
    bad = _decision(triggers=[{"weight": 0.1}])  # ni "type" ni "value"

    with pytest.raises(ValueError, match=r"triggers\[0\]") as exc_info:
        await publish_swing_signal(db_session, redis, bad)

    message = str(exc_info.value)
    assert "type" in message
    assert "value" in message
    assert redis.published == []


@pytest.mark.asyncio
async def test_publish_rejects_counter_scenario_without_name(db_session: AsyncSession) -> None:
    """Counter-scenario sans `name` → ValueError explicite (index + champ)."""
    redis = _FakeRedis()
    bad = _decision(
        counter_scenarios=[
            {"name": "ok", "probability": 0.2, "mitigation": "watch"},  # valide
            {"probability": 0.3, "mitigation": "watch too"},  # pas de "name"
        ]
    )

    with pytest.raises(ValueError, match=r"counter_scenarios\[1\]") as exc_info:
        await publish_swing_signal(db_session, redis, bad)

    assert "name" in str(exc_info.value)
    assert redis.published == []
