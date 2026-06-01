"""Tests d'intégration DB : `macro_events_repo` contre un vrai Postgres.

CONTEXTE — Paquet 49 (durcissement des chemins best-effort silencieux) :

`storage/macro_events_repo.upsert_macro_event` écrit le calendrier macro via un
`pg_insert(...).on_conflict_do_update(index_elements=["event_code",
"scheduled_for"])` **spécifique Postgres**. C'est le seul chemin d'écriture du
calendrier (ingester FRED + ingester static). Or `test_macro_events_repo.py`
ne testait QUE les helpers purs (`to_naive_utc`, `cutoff_*`) et les gardes
triviales de `upsert_many` (None / liste vide) — **le SQL upsert lui-même
n'était couvert ni par un mock ni par la DB**.

Risque non couvert : si la contrainte UNIQUE `(event_code, scheduled_for)`
(migration 0005) était droppée/renommée, l'`ON CONFLICT` n'aurait plus de cible
→ soit erreur SQL avalée par le best-effort (calendrier muet), soit accumulation
de doublons. Côté near_macro (Paquet 47) + carte calendrier dashboard, tout
dépend de ce chemin. Ces tests sont le garde-fou.

NOTE robustesse tracée (NON corrigée ici — chemin prod qui marche, non
déclenchable avec les specs statiques actuelles) : dans `upsert_many`, si un
event lève `SQLAlchemyError`, l'`except` interne de `upsert_macro_event`
retourne False SANS rollback → la transaction Postgres passe « aborted » → les
events suivants et le `commit()` final échouent → batch entier perdu (best-effort
retourne 0, log warning). À reconsidérer (savepoint par event) si un jour une
spec malformée le déclenche.

Pré-requis : Postgres réel via `db_session` (skip propre hors base de test).
Isolation : `upsert_macro_event` ne commit pas → le `rollback()` de teardown du
fixture `db_session` discard les rows insérées. Aucune pollution de `tik_test`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.storage.macro_events_repo import (
    fetch_history,
    fetch_upcoming,
    upsert_macro_event,
)
from tik_core.storage.models import MacroEvent
from tik_core.utils.time import now_utc_naive

# Anchor 2030 pour les tests d'upsert (indépendants de la fenêtre temps réel).
FIXED = datetime(2030, 6, 5, 12, 30, 0)  # naïf


async def _count(session: AsyncSession, code: str, sched: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(MacroEvent)
        .where(MacroEvent.event_code == code)
        .where(MacroEvent.scheduled_for == sched)
    )
    return int((await session.execute(stmt)).scalar_one())


@pytest.mark.asyncio
async def test_upsert_inserts_row(db_session: AsyncSession) -> None:
    """Un upsert simple crée la row (retourne True, 1 row en DB)."""
    ok = await upsert_macro_event(
        db_session,
        event_code="ITEST_NFP",
        event_name="Test NFP",
        scheduled_for=FIXED,
        importance="HIGH",
        assets_impacted=["BTC", "GOLD"],
        source="itest",
        release_id=50,
    )
    assert ok is True
    assert await _count(db_session, "ITEST_NFP", FIXED) == 1


@pytest.mark.asyncio
async def test_upsert_idempotent_on_conflict(db_session: AsyncSession) -> None:
    """GUARD contrainte UNIQUE — deux upserts du même (event_code, scheduled_for)
    ne créent qu'UNE row (ON CONFLICT DO UPDATE).

    Si la contrainte UNIQUE (event_code, scheduled_for) de la migration 0005
    disparaissait, le 2e upsert insérerait un doublon → count == 2 → ce test
    échoue. C'est le garde-fou contre une accumulation silencieuse de doublons
    dans le calendrier.
    """
    for importance in ("HIGH", "MEDIUM"):
        await upsert_macro_event(
            db_session,
            event_code="ITEST_CPI",
            event_name="Test CPI",
            scheduled_for=FIXED,
            importance=importance,
            assets_impacted=["BTC"],
            source="itest",
            release_id=10,
        )
    assert await _count(db_session, "ITEST_CPI", FIXED) == 1, (
        "ON CONFLICT a échoué : 2 rows au lieu d'1. Contrainte UNIQUE "
        "(event_code, scheduled_for) probablement absente (migration 0005)."
    )


@pytest.mark.asyncio
async def test_upsert_updates_fields_on_conflict(db_session: AsyncSession) -> None:
    """ON CONFLICT met à jour les métadonnées (importance, event_name) — utile
    quand on corrige une spec dans `macro_calendar_data.py`."""
    await upsert_macro_event(
        db_session,
        event_code="ITEST_PPI",
        event_name="Ancien nom",
        scheduled_for=FIXED,
        importance="LOW",
        assets_impacted=["GOLD"],
        source="itest",
        release_id=None,
    )
    await upsert_macro_event(
        db_session,
        event_code="ITEST_PPI",
        event_name="Nouveau nom",
        scheduled_for=FIXED,
        importance="HIGH",
        assets_impacted=["BTC", "GOLD"],
        source="itest",
        release_id=46,
    )
    row = (
        await db_session.execute(
            select(MacroEvent)
            .where(MacroEvent.event_code == "ITEST_PPI")
            .where(MacroEvent.scheduled_for == FIXED)
        )
    ).scalar_one()
    assert row.event_name == "Nouveau nom"
    assert row.importance == "HIGH"
    assert row.assets_impacted == ["BTC", "GOLD"]
    assert row.release_id == 46


@pytest.mark.asyncio
async def test_upsert_strips_aware_datetime(db_session: AsyncSession) -> None:
    """GUARD Bug 9 — un `scheduled_for` aware doit être strippé en naïf avant
    l'INSERT (colonne TIMESTAMP WITHOUT TIME ZONE), sinon asyncpg lève DataError."""
    aware = datetime(2030, 7, 1, 14, 0, 0, tzinfo=UTC)
    ok = await upsert_macro_event(
        db_session,
        event_code="ITEST_AWARE",
        event_name="Aware test",
        scheduled_for=aware,  # aware → doit être strippé par to_naive_utc
        importance="HIGH",
        assets_impacted=["BTC"],
        source="itest",
        release_id=None,
    )
    assert ok is True
    row = (
        await db_session.execute(select(MacroEvent).where(MacroEvent.event_code == "ITEST_AWARE"))
    ).scalar_one()
    assert row.scheduled_for.tzinfo is None
    # Le moment UTC est préservé (14:00 reste 14:00).
    assert row.scheduled_for.hour == 14


@pytest.mark.asyncio
async def test_fetch_upcoming_importance_and_asset_filters(db_session: AsyncSession) -> None:
    """`fetch_upcoming` : filtre importance (SQL) + filtre asset (`assets_impacted`
    JSON Postgres) sur des rows réelles dans la fenêtre temps réel."""
    base = now_utc_naive() + timedelta(days=1)
    # 3 events dans la fenêtre +72h : HIGH/BTC, MEDIUM/GOLD, HIGH/GOLD.
    specs = [
        ("ITEST_UP_HBTC", "HIGH", ["BTC", "GOLD"]),
        ("ITEST_UP_MGOLD", "MEDIUM", ["GOLD"]),
        ("ITEST_UP_HGOLD", "HIGH", ["GOLD"]),
    ]
    for i, (code, imp, assets) in enumerate(specs):
        await upsert_macro_event(
            db_session,
            event_code=code,
            event_name=code,
            scheduled_for=base + timedelta(hours=i),
            importance=imp,
            assets_impacted=assets,
            source="itest",
            release_id=None,
        )

    rows = await fetch_upcoming(
        db_session, hours=72, importance_filter=["HIGH"], asset_filter="BTC"
    )
    codes = {r.event_code for r in rows}
    assert "ITEST_UP_HBTC" in codes  # HIGH + impacte BTC → gardé
    assert "ITEST_UP_MGOLD" not in codes  # MEDIUM → exclu par filtre importance
    assert "ITEST_UP_HGOLD" not in codes  # HIGH mais GOLD-only → exclu par asset


@pytest.mark.asyncio
async def test_fetch_history_window(db_session: AsyncSession) -> None:
    """`fetch_history` : un event passé est dans la fenêtre `since_days` large,
    hors d'une fenêtre étroite."""
    past = now_utc_naive() - timedelta(days=2)
    await upsert_macro_event(
        db_session,
        event_code="ITEST_HIST",
        event_name="Hist test",
        scheduled_for=past,
        importance="HIGH",
        assets_impacted=["BTC"],
        source="itest",
        release_id=None,
    )

    wide = await fetch_history(db_session, since_days=7)
    assert any(r.event_code == "ITEST_HIST" for r in wide)

    narrow = await fetch_history(db_session, since_days=1)
    assert all(r.event_code != "ITEST_HIST" for r in narrow)
