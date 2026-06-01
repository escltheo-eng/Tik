"""Tests d'intégration DB : `annotate_near_macro_event` contre un vrai Postgres.

CONTEXTE — Paquet 47 (couplage signal ↔ calendrier macro, Phase B1.5) :

`scoring/macro_proximity.annotate_near_macro_event` requête la table
`macro_events` (modèle ORM `MacroEvent`), filtre par importance et par entité
(`assets_impacted` JSON), puis pose `decision.advisory["near_macro_event"]`.
TOUT est enveloppé dans un `except Exception` best-effort (l'émission du signal
ne doit jamais être bloquée). **Conséquence pernicieuse** : si un nom de colonne
du modèle changeait (`event_name`, `assets_impacted`, `scheduled_for`,
`importance`), l'`AttributeError`/erreur SQL serait silencieusement avalée → le
flag ne serait JAMAIS posé, sans aucune alerte.

Les tests existants de `test_macro_proximity.py` utilisent des objets MOCKÉS
(`FakeEvent` + `_mock_session`) — ils ne touchent ni le vrai modèle `MacroEvent`
ni le vrai Postgres, donc un drift modèle/schéma leur échapperait. Ce fichier
comble ce trou : il insère de VRAIES rows `MacroEvent` dans `tik_test` et vérifie
le comportement de bout en bout.

Enjeu concret : la feature se déclenche pour la PREMIÈRE fois en réel sur le NFP
du 2026-06-05 (premier event HIGH). Si elle était silencieusement cassée, la
discipline macro de la trader serait muette au pire moment. Ces tests sont le
garde-fou contre cette classe de régression.

Pré-requis : Postgres réel via fixture `db_session` (conftest) — `skip` propre si
`TIK_DB_NAME` n'est pas une base de test (garde anti-prod, cf. Paquet 31).
Isolation : on insère via `session.flush()` SANS commit → le `rollback()` de
teardown du fixture `db_session` discard les rows. Aucune pollution de `tik_test`.
Anchor temporel en 2030 → aucune collision avec une vraie row du calendrier.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.scoring.macro_proximity import annotate_near_macro_event
from tik_core.storage.models import MacroEvent

# Anchor en 2030 : aucune row réelle du calendrier macro ne tombe ici, donc les
# rows insérées par chaque test sont les seules dans la fenêtre ±4h interrogée.
BASE = datetime(2030, 1, 15, 12, 30, 0)  # naïf (colonne DateTime WITHOUT TZ)
# Signal émis 2h AVANT l'event → hours_until attendu = +2.0 (event à venir).
SIGNAL_TS = BASE - timedelta(hours=2)


def _decision(entity_id: str = "BTC"):
    """Objet decision minimal : `annotate_near_macro_event` ne lit que
    `.timestamp`, `.entity_id` et `.advisory`."""
    return SimpleNamespace(timestamp=SIGNAL_TS, entity_id=entity_id, advisory={})


def _macro_event(
    *,
    code: str,
    scheduled_for: datetime,
    importance: str,
    assets: list[str],
) -> MacroEvent:
    """Construit une row MacroEvent réelle (colonnes non-nullables fournies)."""
    return MacroEvent(
        event_code=code,
        event_name=f"Test {code}",
        scheduled_for=scheduled_for,  # naïf — colonne TIMESTAMP WITHOUT TIME ZONE
        importance=importance,
        assets_impacted=assets,
        source="test_db_guard",
    )


@pytest.mark.asyncio
async def test_real_high_event_in_window_sets_flag(db_session: AsyncSession) -> None:
    """GUARD modèle/schéma — une vraie row HIGH dans la fenêtre pose le flag.

    C'est LE test qui attrape un drift de nom de colonne (`event_name`,
    `assets_impacted`, `scheduled_for`, `importance`) que les mocks ne voient pas.
    """
    db_session.add(
        _macro_event(code="TEST_NFP", scheduled_for=BASE, importance="HIGH", assets=["BTC", "GOLD"])
    )
    await db_session.flush()  # visible dans la transaction, discard au rollback

    decision = _decision("BTC")
    await annotate_near_macro_event(db_session, decision)

    near = decision.advisory.get("near_macro_event")
    assert near is not None, (
        "Le flag near_macro_event n'a pas été posé alors qu'un event HIGH BTC "
        "est dans la fenêtre ±4h. Drift modèle/schéma probable (cf. except "
        "best-effort qui avale l'erreur silencieusement)."
    )
    assert near["event_code"] == "TEST_NFP"
    assert near["title"] == "Test TEST_NFP"
    assert near["importance"] == "HIGH"
    # Signal émis 2h avant l'event → hours_until signé positif.
    assert near["hours_until"] == pytest.approx(2.0)
    # scheduled_for sérialisé en ISO-8601 UTC explicite (suffixe Z) pour REST/WS.
    assert near["scheduled_for"].endswith("Z")


@pytest.mark.asyncio
async def test_real_medium_event_not_flagged(db_session: AsyncSession) -> None:
    """Filtre importance (SQL `IN (HIGH,)`) — un event MEDIUM dans la fenêtre
    ne déclenche pas la discipline (réservée aux HIGH)."""
    db_session.add(
        _macro_event(code="TEST_PPI", scheduled_for=BASE, importance="MEDIUM", assets=["BTC"])
    )
    await db_session.flush()

    decision = _decision("BTC")
    await annotate_near_macro_event(db_session, decision)

    assert decision.advisory.get("near_macro_event") is None


@pytest.mark.asyncio
async def test_real_event_impacting_other_entity_not_flagged(db_session: AsyncSession) -> None:
    """Filtre entité via `assets_impacted` JSON (Postgres) — un event HIGH qui
    n'impacte que GOLD ne flagge pas un signal BTC."""
    db_session.add(
        _macro_event(code="TEST_GOLD_ONLY", scheduled_for=BASE, importance="HIGH", assets=["GOLD"])
    )
    await db_session.flush()

    decision = _decision("BTC")
    await annotate_near_macro_event(db_session, decision)

    assert decision.advisory.get("near_macro_event") is None


@pytest.mark.asyncio
async def test_real_empty_assets_treated_as_all_entities(db_session: AsyncSession) -> None:
    """`assets_impacted` vide = impacte toutes les entités → flagge BTC."""
    db_session.add(
        _macro_event(code="TEST_WORLD", scheduled_for=BASE, importance="HIGH", assets=[])
    )
    await db_session.flush()

    decision = _decision("BTC")
    await annotate_near_macro_event(db_session, decision)

    near = decision.advisory.get("near_macro_event")
    assert near is not None
    assert near["event_code"] == "TEST_WORLD"


@pytest.mark.asyncio
async def test_real_event_outside_window_not_flagged(db_session: AsyncSession) -> None:
    """Fenêtre SQL (`scheduled_for BETWEEN ts-4h AND ts+4h`) — un event HIGH à
    +6h du signal (donc hors ±4h) ne flagge pas."""
    db_session.add(
        _macro_event(
            code="TEST_FAR",
            scheduled_for=SIGNAL_TS + timedelta(hours=6),
            importance="HIGH",
            assets=["BTC"],
        )
    )
    await db_session.flush()

    decision = _decision("BTC")
    await annotate_near_macro_event(db_session, decision)

    assert decision.advisory.get("near_macro_event") is None


@pytest.mark.asyncio
async def test_real_picks_nearest_high_event(db_session: AsyncSession) -> None:
    """Deux events HIGH dans la fenêtre → le plus proche du signal est choisi."""
    # Signal à SIGNAL_TS (= BASE-2h). Event A à BASE (+2h), Event B à BASE-3.5h (-1.5h).
    db_session.add(
        _macro_event(code="TEST_FAR2H", scheduled_for=BASE, importance="HIGH", assets=["BTC"])
    )
    db_session.add(
        _macro_event(
            code="TEST_NEAR",
            scheduled_for=SIGNAL_TS - timedelta(minutes=30),  # 0.5h du signal
            importance="HIGH",
            assets=["BTC"],
        )
    )
    await db_session.flush()

    decision = _decision("BTC")
    await annotate_near_macro_event(db_session, decision)

    near = decision.advisory.get("near_macro_event")
    assert near is not None
    assert near["event_code"] == "TEST_NEAR", (
        "doit choisir l'event le plus proche en valeur absolue"
    )
    assert near["hours_until"] == pytest.approx(-0.5)  # event 0.5h AVANT le signal → signé négatif
