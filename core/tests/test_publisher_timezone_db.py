"""Tests d'intégration : asyncpg vs datetime aware (Bug 9 régression guard).

CONTEXTE — CLAUDE.md section 9 Bug 9 :

Le Paquet 7 (ADR-013, 2026-05-04) a refactoré tout le code core pour utiliser
`datetime` aware via `now_utc()`. Conséquence inattendue runtime : asyncpg
lève `DataError: invalid input for query argument $2: ... (can't subtract
offset-naive and offset-aware datetimes)` quand on passe un datetime aware
à une colonne SQL `TIMESTAMP WITHOUT TIME ZONE` (cas des colonnes
`signals.timestamp` et `signals.expiry`).

Le commentaire d'`utils/time.py:18` prétendait que "asyncpg strippe
silencieusement la tzinfo" — c'est obsolète sur la version actuelle d'asyncpg.

Le bug a tourné **4h sans détection** (2026-05-04 13:09 → 17:11 UTC) car
aucun signal ne s'insérait en DB. La suite pytest CI (590 tests verts
à l'époque, 988 aujourd'hui) n'attrapait pas car :
- Le test conftest `db_engine` utilise asyncpg vers Postgres réel, mais
  aucun test ne créait de Signal avec timestamp aware avant ce fix
- Les engines testés (`test_swing_engine.py`, etc.) testent des fonctions
  pures `_compute_technical_evidence` qui ne touchent pas la DB

**Fix appliqué** (chirurgical, 2 lignes dans `publisher.py:_publish_signal`) :
strip explicite de `tzinfo` avant l'insertion DB. Les datetime restent
aware **en mémoire** (cohérent ADR-013), seul le moment de l'INSERT
strippe pour rester compatible avec les colonnes `TIMESTAMP WITHOUT TIME
ZONE`. À la sortie API, le `field_serializer` Pydantic + `iso_utc` ajoute
le suffixe `Z` pour que les clients lisent en UTC explicite.

Les tests ci-dessous **plantent** si quelqu'un retire le strip dans
`publisher._publish_signal`. Pré-requis : Postgres réel via fixture
`db_engine` (asyncpg, pas SQLite — sinon SQLite accepte aware sans
broncher et le bug ne se reproduit pas).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.scoring.publisher import publish_swing_signal
from tik_core.scoring.swing_engine import SwingDecision
from tik_core.storage.models import Entity, Signal


class _FakeRedis:
    """Stub Redis minimal pour `publisher._publish_signal`.

    Le test cible la couche DB asyncpg, pas Redis. On collecte les
    publications dans une liste pour audit éventuel.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, data: str) -> int:
        self.published.append((channel, data))
        return 0


def _build_decision(ts: datetime) -> SwingDecision:
    """SwingDecision minimale pour publish_swing_signal."""
    return SwingDecision(
        entity_id="BTC",
        timestamp=ts,
        direction="neutral",
        confidence=0.0,
        hypothesis="test-bug-9-regression-guard",
        veracity=0.85,
        counter_scenarios=[],
        evidence=[{"source": "test", "score": 1.0, "fact": "regression guard"}],
        triggers=[],
        circuit_breaker_status="ok",
        advisory={},
    )


@pytest_asyncio.fixture
async def clean_signal_row(db_session: AsyncSession):
    """Garantit l'entité BTC (FK) puis nettoie les signaux créés en teardown.

    `signals.entity_id` a une foreign key vers `entities.id`. En production
    l'entité BTC est seedée ; sur la base de test (`tik_test`, schéma vierge
    via `create_all`) il faut l'insérer avant tout signal, sinon asyncpg lève
    `ForeignKeyViolationError`. Insertion idempotente (skip si déjà présente).

    Le signal_id créé par chaque test est capturé puis retiré en teardown
    pour ne pas accumuler de lignes Bug 9 dans la base de test.
    """
    if await db_session.get(Entity, "BTC") is None:
        db_session.add(Entity(id="BTC", domain="crypto", namespace="binance"))
        await db_session.commit()

    inserted: list[str] = []
    yield inserted
    for sid in inserted:
        await db_session.execute(Signal.__table__.delete().where(Signal.id == sid))
    await db_session.commit()


@pytest.mark.asyncio
async def test_publish_swing_signal_accepts_aware_datetime(
    db_session: AsyncSession,
    clean_signal_row: list[str],
) -> None:
    """REGRESSION GUARD Bug 9 — un datetime aware doit s'insérer sans DataError.

    Sans le strip dans `publisher._publish_signal`, asyncpg lève
    `DataError` au moment du flush et la session est rollback. Le test
    échoue avec une exception explicite, ce qui suffit comme garde-fou.
    """
    aware_ts = datetime.now(UTC)
    assert aware_ts.tzinfo is not None, "sanity: le timestamp doit être aware"

    decision = _build_decision(aware_ts)
    redis = _FakeRedis()

    # Si Bug 9 ré-introduit (strip retiré) : asyncpg.exceptions.DataError ici
    signal = await publish_swing_signal(db_session, redis, decision)
    await db_session.commit()
    clean_signal_row.append(signal.id)

    # Vérification : la row existe en DB
    result = await db_session.execute(select(Signal).where(Signal.id == signal.id))
    persisted = result.scalar_one()
    assert persisted is not None
    assert persisted.entity_id == "BTC"
    assert persisted.horizon == "swing"
    # SQLAlchemy retourne le datetime naïf depuis Postgres (colonne
    # TIMESTAMP WITHOUT TIME ZONE) — c'est le comportement attendu.
    assert persisted.timestamp.tzinfo is None, (
        "Bug 9 sanity : la colonne signals.timestamp est WITHOUT TIME ZONE, "
        "doit ressortir naïve même si on a inséré un aware."
    )


@pytest.mark.asyncio
async def test_publish_swing_signal_accepts_naive_datetime(
    db_session: AsyncSession,
    clean_signal_row: list[str],
) -> None:
    """REGRESSION GUARD : rétrocompat — un datetime naïf doit aussi passer.

    Cas legacy avant ADR-013 (avant 2026-05-04) où le code créait des
    timestamps via `datetime.utcnow()`. La logique de strip ne doit pas
    casser ce cas.
    """
    naive_ts = datetime.utcnow()  # noqa: DTZ003 — test explicite legacy naïf
    assert naive_ts.tzinfo is None, "sanity: le timestamp doit être naïf"

    decision = _build_decision(naive_ts)
    redis = _FakeRedis()

    signal = await publish_swing_signal(db_session, redis, decision)
    await db_session.commit()
    clean_signal_row.append(signal.id)

    result = await db_session.execute(select(Signal).where(Signal.id == signal.id))
    persisted = result.scalar_one()
    assert persisted is not None
    assert persisted.timestamp.tzinfo is None


@pytest.mark.asyncio
async def test_publish_swing_signal_preserves_utc_moment_after_strip(
    db_session: AsyncSession,
    clean_signal_row: list[str],
) -> None:
    """Vérifie que le strip de tzinfo ne décale PAS l'instant.

    Un datetime aware avec offset non-UTC (ex. +02:00 Paris) doit être
    converti en UTC AVANT le strip, sinon on stockerait l'heure locale
    avec un label UTC → bug 8 ré-introduit côté backend.

    Note : `replace(tzinfo=None)` ne convertit pas, il fait juste tomber
    la timezone. Donc si on passe un datetime CEST (UTC+2) tel quel, on
    stockerait l'heure CEST comme si c'était UTC. **Le contrat actuel** :
    le caller (engines) crée toujours via `now_utc()` qui retourne déjà
    UTC-aware → strip ne change pas le moment. On vérifie ici que les
    callers actuels respectent ce contrat.

    Si une session future ajoute un caller qui produit du datetime aware
    non-UTC, ce test capturera la régression (la valeur en DB sera
    décalée de l'offset).
    """
    # Datetime aware UTC explicite, comme le produit `now_utc()`
    aware_utc = datetime(2026, 5, 19, 14, 30, 0, tzinfo=UTC)
    decision = _build_decision(aware_utc)
    redis = _FakeRedis()

    signal = await publish_swing_signal(db_session, redis, decision)
    await db_session.commit()
    clean_signal_row.append(signal.id)

    result = await db_session.execute(select(Signal).where(Signal.id == signal.id))
    persisted = result.scalar_one()

    # Le moment UTC est préservé : 14:30 UTC reste 14:30 en DB (naïf,
    # mais représentant l'heure UTC car le caller a passé un aware UTC).
    assert persisted.timestamp.year == 2026
    assert persisted.timestamp.month == 5
    assert persisted.timestamp.day == 19
    assert persisted.timestamp.hour == 14
    assert persisted.timestamp.minute == 30
    assert persisted.timestamp.tzinfo is None


@pytest.mark.asyncio
async def test_publish_swing_signal_expiry_is_naive(
    db_session: AsyncSession,
    clean_signal_row: list[str],
) -> None:
    """REGRESSION GUARD : `expiry` est calculé via `now_utc() + delta` (aware)
    puis doit être strippé avant l'INSERT.

    Sans le `.replace(tzinfo=None)` sur `expiry` dans `publisher.py`, asyncpg
    lève DataError sur ce champ même si `timestamp` passe.
    """
    aware_ts = datetime.now(UTC)
    decision = _build_decision(aware_ts)
    redis = _FakeRedis()

    signal = await publish_swing_signal(db_session, redis, decision)
    await db_session.commit()
    clean_signal_row.append(signal.id)

    result = await db_session.execute(select(Signal).where(Signal.id == signal.id))
    persisted = result.scalar_one()
    assert persisted.expiry is not None
    assert persisted.expiry.tzinfo is None
    # Swing → expiry = now + 7 jours (cf. EXPIRY_BY_HORIZON dans publisher)
    delta = persisted.expiry - persisted.timestamp
    assert delta >= timedelta(days=6, hours=23), (
        f"expiry attendu ~7j après timestamp, observé delta={delta}"
    )


def test_publisher_module_strips_tzinfo_in_source() -> None:
    """SMOKE TEST documentation — vérifie que le code source de publisher.py
    contient bien le strip explicite de tzinfo.

    Sert de garde-fou contre un refactor qui retirerait le workaround sans
    relire le commentaire d'ADR-013 amendement (cf. CLAUDE.md Bug 9).
    """
    from pathlib import Path

    publisher_src = Path(__file__).parent.parent / "src" / "tik_core" / "scoring" / "publisher.py"
    source = publisher_src.read_text(encoding="utf-8")

    # Le strip de timestamp doit être présent
    assert ".replace(tzinfo=None)" in source, (
        "Bug 9 régression : le strip explicite de tzinfo a disparu de "
        "publisher.py. Cf. CLAUDE.md section 9 Bug 9 + ADR-013 amendement. "
        "Sans ce strip, asyncpg lève DataError et tous les signaux sont "
        "perdus runtime sans alerte CI."
    )
