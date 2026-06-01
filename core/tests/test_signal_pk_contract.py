"""Garde-fou : le PK ORM de `Signal` reste mono-colonne `id` (divergence Timescale).

CONTEXTE — Paquet 49, analyse approfondie du « drift PK Signal » :

En prod, la table `signals` est une **hypertable Timescale** avec un PK
**composite `(id, timestamp)`** (la clé de partitionnement DOIT figurer dans le
PK — contrainte Timescale, posée par la migration 0001, cf. Bug 1/2). Le modèle
SQLAlchemy `Signal`, lui, déclare volontairement un PK **mono-colonne `id`**.

Cette divergence est **intentionnelle et correcte** (pattern standard
ORM + Timescale) : le modèle expose un PK logique simple pour l'ergonomie ORM,
la table physique garde le PK composite pour le partitionnement. **3 endpoints
prod en dépendent directement** via `session.get(Signal, id)` avec un id SIMPLE :
  - `api/signals.py`        → GET /signals/{id}
  - `api/feedback.py`       → POST /feedback (lookup du signal)
  - `api/metrics.py`        → GET /metrics/signal_track_record/{id}

⚠ **NE PAS « corriger » ce drift en déclarant le PK composite dans le modèle.**
`session.get(Signal, id)` exige le PK COMPLET → avec un PK composite il faudrait
passer `(id, timestamp)` partout → les 3 endpoints casseraient
(`sqlalchemy InvalidRequestError: Incorrect number of values in identifier`).
L'`id` est un UUID globalement unique, donc le PK mono-colonne est sûr et
suffisant pour l'identité ORM. Le diff `alembic --autogenerate` sur ce PK est un
faux positif connu (à ignorer ; les migrations du projet sont écrites à la main).

Ces tests **plantent** si une future session ajoute `timestamp` au PK du modèle —
c'est le garde-fou qui protège les 3 endpoints contre une « correction » naïve.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.storage.models import Entity, Signal


def test_signal_model_pk_is_single_id_column() -> None:
    """Le PK ORM de Signal DOIT rester `[id]` (divergence Timescale intentionnelle).

    Si ce test échoue : quelqu'un a ajouté `timestamp` (ou autre) au PK du modèle
    → `session.get(Signal, id)` des 3 endpoints va casser. Relire le docstring de
    ce fichier + l'analyse Paquet 49 AVANT de « corriger » le drift.
    """
    pk_cols = [c.name for c in Signal.__table__.primary_key.columns]
    assert pk_cols == ["id"], (
        f"PK modèle Signal attendu ['id'], obtenu {pk_cols}. "
        "Cette divergence avec le PK composite (id, timestamp) de l'hypertable "
        "Timescale prod est INTENTIONNELLE — ne pas la 'corriger', sinon "
        "session.get(Signal, id) casse dans 3 endpoints (cf. docstring)."
    )


@pytest.mark.asyncio
async def test_session_get_signal_by_single_id_works(db_session: AsyncSession) -> None:
    """Contrat runtime des 3 endpoints : `session.get(Signal, id)` avec un id
    SIMPLE doit fonctionner (présent → la row, absent → None)."""
    if await db_session.get(Entity, "BTC") is None:
        db_session.add(Entity(id="BTC", domain="crypto", namespace="binance"))
        await db_session.flush()

    sig = Signal(
        id="ITEST-PK-CONTRACT-1",
        entity_id="BTC",
        timestamp=datetime(2030, 1, 1, 12, 0, 0),
        horizon="swing",
        direction="neutral",
        confidence=0.0,
        veracity=0.85,
    )
    db_session.add(sig)
    await db_session.flush()  # rollback de teardown discard (pas de commit)

    # Présent : session.get avec un id simple renvoie la row.
    got = await db_session.get(Signal, "ITEST-PK-CONTRACT-1")
    assert got is not None
    assert got.id == "ITEST-PK-CONTRACT-1"
    assert got.entity_id == "BTC"

    # Absent : renvoie None (comportement attendu par les endpoints → 404).
    missing = await db_session.get(Signal, "does-not-exist")
    assert missing is None
