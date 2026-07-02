"""Rétention DB (décision utilisatrice 2026-07-02, audit S-1).

Contrats verrouillés :
- les lignes plus vieilles que la profondeur choisie sont purgées
  (signaux 12 mois, headlines 3 mois, macro_events 12 mois, crédibilité 12 mois) ;
- les lignes récentes sont conservées ;
- les feedbacks des signaux purgés partent avec eux (pas d'orphelins) ;
- `manual_trades` n'est JAMAIS touché, quel que soit son âge (journal trader).

Tests d'intégration contre `tik_test` (skip propre sans Postgres — garde
anti-prod du conftest).
"""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tik_core.storage.models import (
    Entity,
    Feedback,
    HeadlineRecord,
    MacroEvent,
    ManualTrade,
    Signal,
    SourceCredibilityHistory,
)
from tik_core.storage.retention import (
    RETENTION_HEADLINES_DAYS,
    RETENTION_SIGNALS_DAYS,
    purge_expired_rows,
)
from tik_core.utils.time import now_utc_naive

pytestmark = pytest.mark.asyncio

TAG = uuid.uuid4().hex[:8]  # isole les lignes de CE run de tests


def _signal(signal_id: str, age_days: int) -> Signal:
    return Signal(
        id=signal_id,
        timestamp=now_utc_naive() - timedelta(days=age_days),
        entity_id="BTC",
        horizon="swing",
        direction="neutral",
        confidence=0.1,
        veracity=0.7,
        hypothesis="test rétention",
        counter_scenarios=[],
        evidence=[],
        triggers=[],
        sources_count=0,
    )


async def _seed(session) -> dict:
    if await session.get(Entity, "BTC") is None:
        session.add(
            Entity(
                id="BTC",
                domain="trading",
                namespace="test",
                metadata_json={},
                active=True,
                created_at=now_utc_naive(),
                updated_at=now_utc_naive(),
            )
        )
    old_signal = _signal(f"TIK-RET-OLD-{TAG}", RETENTION_SIGNALS_DAYS + 30)
    fresh_signal = _signal(f"TIK-RET-FRESH-{TAG}", 5)
    session.add_all([old_signal, fresh_signal])
    session.add(
        Feedback(
            signal_id=old_signal.id,
            signal_timestamp=old_signal.timestamp,
            client_id=f"ret-test-{TAG}",
            outcome="win",
        )
    )
    session.add_all(
        [
            HeadlineRecord(
                entity_id="BTC",
                source=f"ret_test_{TAG}",
                title_hash="deadbeef",
                title="vieux titre",
                sentiment="neutral",
                credibility=0.5,
                fetched_at=now_utc_naive() - timedelta(days=RETENTION_HEADLINES_DAYS + 10),
            ),
            HeadlineRecord(
                entity_id="BTC",
                source=f"ret_test_{TAG}",
                title_hash="cafebabe",
                title="titre frais",
                sentiment="neutral",
                credibility=0.5,
                fetched_at=now_utc_naive() - timedelta(days=2),
            ),
        ]
    )
    session.add(
        MacroEvent(
            event_code=f"RET_TEST_{TAG}",
            event_name="event passé très vieux",
            scheduled_for=now_utc_naive() - timedelta(days=400),
            importance="LOW",
            assets_impacted=[],
            source=f"ret_test_{TAG}",
        )
    )
    session.add(
        SourceCredibilityHistory(
            source=f"ret_test_{TAG}",
            computed_at=now_utc_naive() - timedelta(days=400),
            score=0.5,
            samples=1,
        )
    )
    # Le journal de la trader : PLUS VIEUX que toute rétention → doit survivre.
    trade = ManualTrade(
        entity_id="BTC",
        direction="long",
        entry_time=now_utc_naive() - timedelta(days=500),
        entry_price=50000.0,
        size_lots=0.01,
        status="closed",
    )
    session.add(trade)
    await session.commit()
    return {
        "old_signal_id": old_signal.id,
        "fresh_signal_id": fresh_signal.id,
        "trade_id": trade.id,
    }


async def test_purge_removes_old_keeps_fresh_and_never_touches_trades(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    async with maker() as session:
        ids = await _seed(session)

    counts = await purge_expired_rows(maker)
    assert counts["signals"] >= 1
    assert counts["headlines"] >= 1
    assert counts["macro_events"] >= 1
    assert counts["source_credibility_history"] >= 1
    assert counts["feedbacks"] >= 1
    assert "manual_trades" not in counts  # jamais purgés, même pas listés

    async with maker() as session:
        assert await session.get(Signal, ids["old_signal_id"]) is None
        assert await session.get(Signal, ids["fresh_signal_id"]) is not None
        # Pas de feedback orphelin sur le signal purgé
        n_orphans = (
            await session.execute(
                select(func.count())
                .select_from(Feedback)
                .where(Feedback.signal_id == ids["old_signal_id"])
            )
        ).scalar_one()
        assert n_orphans == 0
        # Le titre frais survit, le vieux est parti
        titles = (
            (
                await session.execute(
                    select(HeadlineRecord.title).where(HeadlineRecord.source == f"ret_test_{TAG}")
                )
            )
            .scalars()
            .all()
        )
        assert titles == ["titre frais"]
        # Le journal de la trader est intact malgré ses 500 jours
        assert await session.get(ManualTrade, ids["trade_id"]) is not None

        # Nettoyage des lignes restantes de ce run (le vieux est déjà purgé)
        fresh = await session.get(Signal, ids["fresh_signal_id"])
        await session.delete(fresh)
        trade = await session.get(ManualTrade, ids["trade_id"])
        await session.delete(trade)
        for h in (
            await session.execute(
                select(HeadlineRecord).where(HeadlineRecord.source == f"ret_test_{TAG}")
            )
        ).scalars():
            await session.delete(h)
        await session.commit()


async def test_purge_is_idempotent(db_engine):
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    first = await purge_expired_rows(maker)
    second = await purge_expired_rows(maker)
    # Un second passage immédiat ne trouve plus rien à purger de ce run.
    assert second["signals"] <= first["signals"]
