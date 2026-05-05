"""Tests unitaires des endpoints macro_events (Lacune B Phase B1 J+10, ADR-017).

Couvre la logique pure des helpers de l'endpoint :
- `_parse_importance` (csv → liste validée)
- `_make_cache_key` (déterministe + lisible)
- `_serialize_event` (dict avec iso_utc)

Les tests d'intégration HTTP avec session DB + Redis sont laissés à la
validation runtime (suite intégration nécessite Postgres + Redis up).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from tik_core.api.macro_events import (
    _make_cache_key,
    _parse_importance,
    _serialize_event,
)


# =============================================================================
# _parse_importance
# =============================================================================


def test_parse_importance_none_returns_none():
    assert _parse_importance(None) is None


def test_parse_importance_empty_returns_none():
    assert _parse_importance("") is None


def test_parse_importance_single_value():
    assert _parse_importance("HIGH") == ["HIGH"]


def test_parse_importance_multiple_values():
    out = _parse_importance("HIGH,MEDIUM")
    assert set(out) == {"HIGH", "MEDIUM"}


def test_parse_importance_case_insensitive():
    out = _parse_importance("high,medium")
    assert set(out) == {"HIGH", "MEDIUM"}


def test_parse_importance_filters_unknown_values():
    """Niveau inconnu (ex: "CRITICAL") → ignoré."""
    out = _parse_importance("HIGH,CRITICAL,MEDIUM")
    assert set(out) == {"HIGH", "MEDIUM"}


def test_parse_importance_returns_none_when_all_invalid():
    """Si tous les niveaux sont invalides → None (pas de filtre)."""
    assert _parse_importance("FOO,BAR") is None


def test_parse_importance_strips_whitespace():
    out = _parse_importance(" HIGH , MEDIUM ")
    assert set(out) == {"HIGH", "MEDIUM"}


# =============================================================================
# _make_cache_key
# =============================================================================


def test_make_cache_key_deterministic():
    """Mêmes inputs → même clé."""
    k1 = _make_cache_key("upcoming", 168, ["HIGH", "MEDIUM"], "BTC", 50)
    k2 = _make_cache_key("upcoming", 168, ["MEDIUM", "HIGH"], "BTC", 50)
    # importance triée → clé identique malgré l'ordre d'entrée différent
    assert k1 == k2


def test_make_cache_key_different_for_different_kind():
    k1 = _make_cache_key("upcoming", 168, None, None, 50)
    k2 = _make_cache_key("history", 168, None, None, 50)
    assert k1 != k2


def test_make_cache_key_different_for_different_horizon():
    k1 = _make_cache_key("upcoming", 168, None, None, 50)
    k2 = _make_cache_key("upcoming", 24, None, None, 50)
    assert k1 != k2


def test_make_cache_key_different_for_different_asset():
    k1 = _make_cache_key("upcoming", 168, None, "BTC", 50)
    k2 = _make_cache_key("upcoming", 168, None, "GOLD", 50)
    assert k1 != k2


def test_make_cache_key_uppercases_asset():
    k1 = _make_cache_key("upcoming", 168, None, "btc", 50)
    k2 = _make_cache_key("upcoming", 168, None, "BTC", 50)
    assert k1 == k2


def test_make_cache_key_format():
    """La clé est lisible et préfixée correctement."""
    k = _make_cache_key("upcoming", 168, ["HIGH"], "BTC", 50)
    assert k.startswith("tik.cache.macro_events.upcoming.")
    assert "h168" in k
    assert "imp_HIGH" in k
    assert "asset_BTC" in k
    assert "lim50" in k


def test_make_cache_key_no_filter():
    k = _make_cache_key("upcoming", 168, None, None, 50)
    assert "imp_all" in k
    assert "asset_ALL" in k


# =============================================================================
# _serialize_event
# =============================================================================


def test_serialize_event_basic():
    """Sérialisation d'une row MacroEvent (mock SimpleNamespace)."""
    row = SimpleNamespace(
        id="abc-123",
        event_code="NFP",
        event_name="Employment Situation",
        scheduled_for=datetime(2026, 6, 5, 12, 30, tzinfo=timezone.utc),
        importance="HIGH",
        assets_impacted=["BTC", "GOLD"],
        source="fred",
        release_id=50,
    )
    out = _serialize_event(row)
    assert out["id"] == "abc-123"
    assert out["event_code"] == "NFP"
    assert out["event_name"] == "Employment Situation"
    assert out["importance"] == "HIGH"
    assert out["assets_impacted"] == ["BTC", "GOLD"]
    assert out["source"] == "fred"
    assert out["release_id"] == 50


def test_serialize_event_iso_utc_z_suffix():
    """scheduled_for sérialisé avec suffix Z (ADR-013)."""
    row = SimpleNamespace(
        id="abc-123",
        event_code="NFP",
        event_name="x",
        scheduled_for=datetime(2026, 6, 5, 12, 30),  # naïf → marqué Z
        importance="HIGH",
        assets_impacted=["BTC"],
        source="fred",
        release_id=50,
    )
    out = _serialize_event(row)
    assert out["scheduled_for"].endswith("Z")


def test_serialize_event_handles_none_assets_impacted():
    """assets_impacted None → liste vide (rétrocompat)."""
    row = SimpleNamespace(
        id="abc-123",
        event_code="X",
        event_name="x",
        scheduled_for=datetime(2026, 6, 5, 12, 30, tzinfo=timezone.utc),
        importance="LOW",
        assets_impacted=None,
        source="fred",
        release_id=None,
    )
    out = _serialize_event(row)
    assert out["assets_impacted"] == []
    assert out["release_id"] is None
