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

NOTE robustesse (corrigée 2026-07-02, audit constat S-2) : historiquement,
si un event levait `SQLAlchemyError`, l'`except` interne de
`upsert_macro_event` retournait False SANS rollback → la transaction Postgres
passait « aborted » → les events suivants et le `commit()` final échouaient →
batch entier perdu (dont les FOMC HIGH ±4h). Fix : SAVEPOINT
(`session.begin_nested()`) par event dans `upsert_macro_event`. Les tests
`test_upsert_failure_does_not_poison_the_session` et
`test_upsert_many_batch_survives_one_invalid_event` sont les garde-fous —
ils échoueraient sans le savepoint.

Pré-requis : Postgres réel via `db_session` (skip propre hors base de test).
Isolation : `upsert_macro_event` ne commit pas → le `rollback()` de teardown du
fixture `db_session` discard les rows insérées. Aucune pollution de `tik_test`.
(Exception : le test `upsert_many`, qui commit par design — il nettoie ses
rows lui-même en `finally`.)
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.storage.macro_events_repo import (
    fetch_history,
    fetch_upcoming,
    upsert_macro_event,
    upsert_many,
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


# =============================================================================
# SAVEPOINT par event (fix S-2, audit 2026-07-02)
# =============================================================================
# Sans le `begin_nested()` dans `upsert_macro_event`, une erreur SQL avortait
# la transaction Postgres du batch entier : les upserts suivants échouaient en
# cascade (« current transaction is aborted ») puis le commit → UN event
# invalide faisait perdre TOUT le calendrier macro du cycle. Les deux tests
# ci-dessous échoueraient sans le savepoint.

# event_name > 128 chars → dépasse String(128) de `MacroEvent.event_name` →
# asyncpg lève StringDataRightTruncationError (SQLAlchemyError) à l'execute.
_TOO_LONG_NAME = "X" * 200


def _spec(code: str, name: str, offset_h: int = 0) -> dict:
    """Spec d'event macro minimale pour `upsert_many` (anchor 2030)."""
    return {
        "event_code": code,
        "event_name": name,
        "scheduled_for": FIXED + timedelta(hours=offset_h),
        "importance": "HIGH",
        "assets_impacted": ["BTC"],
        "source": "itest",
        "release_id": None,
    }


@pytest.mark.asyncio
async def test_upsert_failure_does_not_poison_the_session(db_session: AsyncSession) -> None:
    """Un upsert en échec (rollback du SAVEPOINT) laisse la session utilisable.

    Sans le savepoint, le 2e upsert (valide) échouerait sur la transaction
    avortée par le 1er → False au lieu de True, et 0 row visible.
    """
    ok_bad = await upsert_macro_event(
        db_session,
        event_code="ITEST_SP_POISON",
        event_name=_TOO_LONG_NAME,  # > String(128) → DataError Postgres
        scheduled_for=FIXED,
        importance="HIGH",
        assets_impacted=["BTC"],
        source="itest",
        release_id=None,
    )
    assert ok_bad is False

    ok_good = await upsert_macro_event(
        db_session,
        event_code="ITEST_SP_AFTER",
        event_name="Event valide après échec",
        scheduled_for=FIXED,
        importance="HIGH",
        assets_impacted=["BTC"],
        source="itest",
        release_id=None,
    )
    assert ok_good is True, (
        "La transaction est restée « aborted » après l'échec du 1er upsert : "
        "le SAVEPOINT de upsert_macro_event a disparu (fix S-2, audit 2026-07-02)."
    )
    assert await _count(db_session, "ITEST_SP_AFTER", FIXED) == 1


@pytest.mark.asyncio
async def test_upsert_many_batch_survives_one_invalid_event(db_engine) -> None:
    """Batch de 3 events dont celui du MILIEU invalide → les 2 autres persistés.

    Reproduit le scénario du constat S-2 : sans savepoint, l'event invalide
    avortait la transaction → l'event 3 puis le commit échouaient → batch
    entier perdu (`upsert_many` retournait 0, calendrier macro muet pour le
    cycle). Avec le fix : retourne 2 et les 2 events valides sont commités.

    `upsert_many` commit par design (chemin ingester réel) → cleanup manuel
    en `finally` (le rollback du teardown ne peut pas annuler un commit).
    """
    maker = async_sessionmaker(db_engine, expire_on_commit=False)
    events = [
        _spec("ITEST_SP_OK1", "Premier event valide", offset_h=0),
        _spec("ITEST_SP_BAD", _TOO_LONG_NAME, offset_h=1),  # celui du milieu, invalide
        _spec("ITEST_SP_OK2", "Troisième event valide", offset_h=2),
    ]
    try:
        n = await upsert_many(maker, events)
        assert n == 2, (
            f"upsert_many a retourné {n} au lieu de 2 : l'event invalide du milieu "
            "a empoisonné le batch (SAVEPOINT absent — fix S-2, audit 2026-07-02)."
        )
        async with maker() as session:
            assert await _count(session, "ITEST_SP_OK1", FIXED) == 1
            assert await _count(session, "ITEST_SP_BAD", FIXED + timedelta(hours=1)) == 0
            assert await _count(session, "ITEST_SP_OK2", FIXED + timedelta(hours=2)) == 1
    finally:
        async with maker() as session:
            await session.execute(
                delete(MacroEvent).where(MacroEvent.event_code.like("ITEST_SP_%"))
            )
            await session.commit()
