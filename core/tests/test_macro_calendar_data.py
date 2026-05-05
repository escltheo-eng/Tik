"""Tests des données statiques du calendrier macro (Lacune B Phase B1 J+10).

Couvre :
- Validité structurelle des `FRED_RELEASES` (release_id unique, importance ∈
  {HIGH/MEDIUM/LOW}, heures release ET cohérentes).
- Validité structurelle des `FOMC_STATIC_DATES` (dates ISO valides, importance
  HIGH, futur ou passé proche).
- Helper `find_fred_release` (lookup par release_id).

Tests purs, aucune dépendance externe.
"""

from __future__ import annotations

from datetime import date

from tik_core.aggregator.macro_calendar_data import (
    FOMC_STATIC_DATES,
    FRED_RELEASES,
    find_fred_release,
)


# =============================================================================
# FRED_RELEASES — invariants structurels
# =============================================================================


def test_fred_releases_release_ids_unique():
    """Pas de doublon de release_id dans la whitelist."""
    ids = [s.release_id for s in FRED_RELEASES]
    assert len(ids) == len(set(ids))


def test_fred_releases_event_codes_unique():
    """Pas de doublon d'event_code dans la whitelist."""
    codes = [s.event_code for s in FRED_RELEASES]
    assert len(codes) == len(set(codes))


def test_fred_releases_importance_levels_valid():
    """Toutes les importances ∈ {HIGH, MEDIUM, LOW}."""
    for spec in FRED_RELEASES:
        assert spec.importance in {"HIGH", "MEDIUM", "LOW"}


def test_fred_releases_release_hours_in_business_range():
    """Les heures de release ET sont dans 7h-17h (business hours US).

    BLS publie à 8:30 ET, FRB à 9:15 ET, FOMC à 14:00 ET. Anomalie si une
    valeur est hors de cette plage — à signaler dans une review.
    """
    for spec in FRED_RELEASES:
        assert 7 <= spec.release_hour_et <= 17
        assert 0 <= spec.release_minute_et < 60


def test_fred_releases_assets_impacted_non_empty():
    """Tous les events doivent impacter au moins un asset."""
    for spec in FRED_RELEASES:
        assert len(spec.assets_impacted) >= 1


def test_fred_releases_includes_high_importance_critical_releases():
    """NFP et CPI sont marqués HIGH (releases qui font bouger BTC + GOLD le plus)."""
    high_codes = {s.event_code for s in FRED_RELEASES if s.importance == "HIGH"}
    assert "NFP" in high_codes
    assert "CPI" in high_codes


# =============================================================================
# FOMC_STATIC_DATES — invariants structurels
# =============================================================================


def test_fomc_static_dates_iso_valid():
    """Toutes les iso_date sont parsables en date ISO."""
    for spec in FOMC_STATIC_DATES:
        date.fromisoformat(spec.iso_date)


def test_fomc_static_dates_all_high_importance():
    """FOMC = toujours HIGH (mouvement BTC/GOLD le plus brutal)."""
    for spec in FOMC_STATIC_DATES:
        assert spec.importance == "HIGH"


def test_fomc_static_dates_release_hour_14_00_et():
    """Le statement FOMC est publié à 14:00 ET."""
    for spec in FOMC_STATIC_DATES:
        assert spec.release_hour_et == 14
        assert spec.release_minute_et == 0


def test_fomc_static_dates_event_code_consistent():
    """Tous portent le code FOMC_MEETING."""
    for spec in FOMC_STATIC_DATES:
        assert spec.event_code == "FOMC_MEETING"


def test_fomc_static_dates_btc_and_gold_impacted():
    """FOMC impacte BTC ET GOLD (rates → DXY → both)."""
    for spec in FOMC_STATIC_DATES:
        assert "BTC" in spec.assets_impacted
        assert "GOLD" in spec.assets_impacted


def test_fomc_static_dates_chronological_order():
    """Liste triée chronologiquement par iso_date."""
    iso_dates = [s.iso_date for s in FOMC_STATIC_DATES]
    assert iso_dates == sorted(iso_dates)


# =============================================================================
# find_fred_release
# =============================================================================


def test_find_fred_release_matches_existing():
    """Lookup par release_id → spec correspondant."""
    spec = find_fred_release(50)  # NFP
    assert spec is not None
    assert spec.event_code == "NFP"


def test_find_fred_release_returns_none_for_unknown():
    """ID inexistant → None (pas de raise)."""
    assert find_fred_release(99999) is None
