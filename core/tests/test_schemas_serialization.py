"""Tests de sérialisation Pydantic timezone-aware (cf. ADR-013, bug 8).

Le piège bug 8 : SQLAlchemy retourne des datetimes naïfs (colonnes
`DateTime` sans `timezone=True`). Sans field_serializer, Pydantic
sérialiserait sans suffixe `Z` et JavaScript interpréterait comme
heure locale → décalage de l'offset utilisateur sur tous les âges
affichés au dashboard.

Ces tests verrouillent que tous les schémas Out exposent leurs
datetimes en JSON avec `Z` final, que la source soit aware ou naïve.
"""

import json
from datetime import datetime, timezone

import pytest

from tik_core.storage.schemas import (
    Advisory,
    EntityOut,
    FeedbackOut,
    SignalOut,
    VeracityStatus,
)


# =====================================================================
# SignalOut.timestamp + expiry
# =====================================================================

def test_signal_out_timestamp_aware_serialized_with_z():
    aware = datetime(2026, 5, 4, 11, 32, 14, tzinfo=timezone.utc)
    sig = SignalOut(
        id="TIK-SWING-BTC-X",
        timestamp=aware,
        entity_id="BTC",
        horizon="swing",
        direction="long",
        confidence=0.5,
        veracity=0.85,
    )
    payload = json.loads(sig.model_dump_json())
    assert payload["timestamp"].endswith("Z")
    assert "+00:00" not in payload["timestamp"]


def test_signal_out_timestamp_naive_serialized_with_z():
    """Le piège bug 8 : un datetime naïf (cas SQLAlchemy DB) doit sortir avec Z."""
    naive = datetime(2026, 5, 4, 11, 32, 14)
    sig = SignalOut(
        id="TIK-SWING-BTC-X",
        timestamp=naive,
        entity_id="BTC",
        horizon="swing",
        direction="long",
        confidence=0.5,
        veracity=0.85,
    )
    payload = json.loads(sig.model_dump_json())
    assert payload["timestamp"] == "2026-05-04T11:32:14Z"


def test_signal_out_expiry_none_stays_none():
    sig = SignalOut(
        id="X",
        timestamp=datetime(2026, 5, 4, tzinfo=timezone.utc),
        entity_id="BTC",
        horizon="swing",
        direction="long",
        confidence=0.5,
        veracity=0.85,
        expiry=None,
    )
    payload = json.loads(sig.model_dump_json())
    assert payload["expiry"] is None


def test_signal_out_expiry_naive_serialized_with_z():
    sig = SignalOut(
        id="X",
        timestamp=datetime(2026, 5, 4, tzinfo=timezone.utc),
        entity_id="BTC",
        horizon="swing",
        direction="long",
        confidence=0.5,
        veracity=0.85,
        expiry=datetime(2026, 5, 11, 11, 32, 14),  # naïf
    )
    payload = json.loads(sig.model_dump_json())
    assert payload["expiry"].endswith("Z")


# =====================================================================
# EntityOut.created_at + updated_at
# =====================================================================

def test_entity_out_created_updated_naive_serialized_with_z():
    """Cas typique lecture DB : naïf des deux côtés, Pydantic doit forcer Z."""
    ent = EntityOut(
        id="BTC",
        domain="trading",
        namespace="crypto",
        metadata_json={},
        active=True,
        created_at=datetime(2026, 4, 20, 10, 0, 0),
        updated_at=datetime(2026, 5, 4, 11, 32, 14),
    )
    payload = json.loads(ent.model_dump_json())
    assert payload["created_at"].endswith("Z")
    assert payload["updated_at"].endswith("Z")


# =====================================================================
# VeracityStatus.last_computed
# =====================================================================

def test_veracity_status_last_computed_aware_serialized_with_z():
    aware = datetime(2026, 5, 4, 11, 32, 14, tzinfo=timezone.utc)
    vs = VeracityStatus(
        global_veracity=0.85,
        sources_count_active=5,
        last_computed=aware,
        status="healthy",
    )
    payload = json.loads(vs.model_dump_json())
    assert payload["last_computed"] == "2026-05-04T11:32:14Z"


def test_veracity_status_last_computed_naive_serialized_with_z():
    naive = datetime(2026, 5, 4, 11, 32, 14)
    vs = VeracityStatus(
        global_veracity=0.85,
        sources_count_active=5,
        last_computed=naive,
        status="healthy",
    )
    payload = json.loads(vs.model_dump_json())
    assert payload["last_computed"] == "2026-05-04T11:32:14Z"


# =====================================================================
# FeedbackOut.received_at
# =====================================================================

def test_feedback_out_received_at_naive_serialized_with_z():
    fb = FeedbackOut(
        id="abc",
        signal_id="TIK-SWING-BTC-X",
        client_id="zeta",
        outcome="win",
        received_at=datetime(2026, 5, 4, 11, 32, 14),
    )
    payload = json.loads(fb.model_dump_json())
    assert payload["received_at"].endswith("Z")


# =====================================================================
# Régression bug 8 — JS-compatibility check
# =====================================================================

def test_signal_out_json_parseable_as_utc_in_js():
    """Vérifie que le format JSON sortant est parseable par JS comme UTC.

    JavaScript interprète "2026-05-04T11:32:14Z" comme UTC explicite,
    "2026-05-04T11:32:14" sans tz comme heure locale. Ce test verrouille
    que Tik ne renvoie JAMAIS un timestamp ambigü (sans Z ni offset).
    """
    sig = SignalOut(
        id="X",
        timestamp=datetime(2026, 5, 4, 11, 32, 14),  # naïf comme depuis DB
        entity_id="BTC",
        horizon="swing",
        direction="long",
        confidence=0.5,
        veracity=0.85,
    )
    payload = json.loads(sig.model_dump_json())
    ts = payload["timestamp"]
    # Le timestamp doit avoir un suffixe explicite (Z ou ±HH:MM)
    assert ts.endswith("Z") or ts.endswith("+00:00") or "+0" in ts[-6:] or "-0" in ts[-6:]
    # On vérifie aussi que c'est bien Z (pas +00:00) — convention Tik
    assert ts.endswith("Z")
