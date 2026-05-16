"""Tests des données statiques du calendrier macro.

Phase B1 (ADR-017) — FRED releases + FOMC statiques (US).
Phase B2 (ADR-020) — ECB / BoJ / BoE statiques (international).

Couvre :
- Validité structurelle des `FRED_RELEASES` (release_id unique, importance ∈
  {HIGH/MEDIUM/LOW}, heures release ET cohérentes).
- Validité structurelle des `FOMC_STATIC_DATES` (dates ISO valides, importance
  HIGH, futur ou passé proche).
- Validité structurelle des `ECB_STATIC_DATES`, `BOJ_STATIC_DATES`,
  `BOE_STATIC_DATES` (Phase B2 — tz_name, source, importance, chronologie).
- Helper `find_fred_release` (lookup par release_id).
- Helpers `date_to_utc_release` (B2 : multi-tz), `build_event_from_fred`,
  `build_event_from_static`, `all_static_events`.

Tests purs, aucune dépendance externe.
"""

from __future__ import annotations

from datetime import date, timezone

from tik_core.aggregator.macro_calendar_data import (
    BOE_STATIC_DATES,
    BOJ_STATIC_DATES,
    ECB_STATIC_DATES,
    FOMC_STATIC_DATES,
    FRED_RELEASES,
    FredReleaseSpec,
    StaticEventSpec,
    all_static_events,
    build_event_from_fred,
    build_event_from_static,
    date_to_utc_release,
    find_fred_release,
)


# =============================================================================
# FRED_RELEASES — invariants structurels (Phase B1)
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
    """Les heures de release ET sont dans 7h-17h (business hours US)."""
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


def test_fred_releases_all_use_us_eastern_tz():
    """Phase B2 : toutes les releases FRED ont tz_name='America/New_York'."""
    for spec in FRED_RELEASES:
        assert spec.tz_name == "America/New_York"


# =============================================================================
# FOMC_STATIC_DATES — invariants structurels (Phase B1)
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


def test_fomc_static_dates_use_us_eastern_tz():
    """Phase B2 : toutes les dates FOMC ont tz_name='America/New_York'."""
    for spec in FOMC_STATIC_DATES:
        assert spec.tz_name == "America/New_York"


def test_fomc_static_dates_source_fed_static():
    """Phase B2 : source='fed_static' pour les FOMC."""
    for spec in FOMC_STATIC_DATES:
        assert spec.source == "fed_static"


# =============================================================================
# ECB_STATIC_DATES — invariants structurels (Phase B2)
# =============================================================================


def test_ecb_static_dates_non_empty():
    """La liste ECB n'est pas vide."""
    assert len(ECB_STATIC_DATES) > 0


def test_ecb_static_dates_iso_valid():
    """Toutes les iso_date ECB sont parsables."""
    for spec in ECB_STATIC_DATES:
        date.fromisoformat(spec.iso_date)


def test_ecb_static_dates_all_high_importance():
    """ECB Governing Council = toujours HIGH (Lagarde bouge EUR/USD violemment)."""
    for spec in ECB_STATIC_DATES:
        assert spec.importance == "HIGH"


def test_ecb_static_dates_event_code_consistent():
    """Tous portent le code ECB_GOVERNING_COUNCIL."""
    for spec in ECB_STATIC_DATES:
        assert spec.event_code == "ECB_GOVERNING_COUNCIL"


def test_ecb_static_dates_release_hour_14_15_local():
    """Statement ECB publié à 14:15 Europe/Paris."""
    for spec in ECB_STATIC_DATES:
        assert spec.release_hour_et == 14
        assert spec.release_minute_et == 15


def test_ecb_static_dates_tz_europe_paris():
    """tz_name = 'Europe/Paris' (Frankfurt = même fuseau)."""
    for spec in ECB_STATIC_DATES:
        assert spec.tz_name == "Europe/Paris"


def test_ecb_static_dates_source_ecb_static():
    for spec in ECB_STATIC_DATES:
        assert spec.source == "ecb_static"


def test_ecb_static_dates_btc_and_gold_impacted():
    for spec in ECB_STATIC_DATES:
        assert "BTC" in spec.assets_impacted
        assert "GOLD" in spec.assets_impacted


def test_ecb_static_dates_chronological_order():
    iso_dates = [s.iso_date for s in ECB_STATIC_DATES]
    assert iso_dates == sorted(iso_dates)


# =============================================================================
# BOJ_STATIC_DATES — invariants structurels (Phase B2)
# =============================================================================


def test_boj_static_dates_non_empty():
    assert len(BOJ_STATIC_DATES) > 0


def test_boj_static_dates_iso_valid():
    for spec in BOJ_STATIC_DATES:
        date.fromisoformat(spec.iso_date)


def test_boj_static_dates_all_high_importance():
    """BoJ MPM = HIGH (carry trade JPY bouge tous les actifs risk-on)."""
    for spec in BOJ_STATIC_DATES:
        assert spec.importance == "HIGH"


def test_boj_static_dates_event_code_consistent():
    for spec in BOJ_STATIC_DATES:
        assert spec.event_code == "BOJ_MPM"


def test_boj_static_dates_tz_asia_tokyo():
    """tz_name = 'Asia/Tokyo' (JST = UTC+9 sans DST)."""
    for spec in BOJ_STATIC_DATES:
        assert spec.tz_name == "Asia/Tokyo"


def test_boj_static_dates_source_boj_static():
    for spec in BOJ_STATIC_DATES:
        assert spec.source == "boj_static"


def test_boj_static_dates_chronological_order():
    iso_dates = [s.iso_date for s in BOJ_STATIC_DATES]
    assert iso_dates == sorted(iso_dates)


# =============================================================================
# BOE_STATIC_DATES — invariants structurels (Phase B2)
# =============================================================================


def test_boe_static_dates_non_empty():
    assert len(BOE_STATIC_DATES) > 0


def test_boe_static_dates_iso_valid():
    for spec in BOE_STATIC_DATES:
        date.fromisoformat(spec.iso_date)


def test_boe_static_dates_all_medium_importance():
    """BoE MPC = MEDIUM (impact réel mais GBP moins influente sur DXY)."""
    for spec in BOE_STATIC_DATES:
        assert spec.importance == "MEDIUM"


def test_boe_static_dates_event_code_consistent():
    for spec in BOE_STATIC_DATES:
        assert spec.event_code == "BOE_MPC"


def test_boe_static_dates_tz_europe_london():
    """tz_name = 'Europe/London' (GMT/BST avec DST)."""
    for spec in BOE_STATIC_DATES:
        assert spec.tz_name == "Europe/London"


def test_boe_static_dates_source_boe_static():
    for spec in BOE_STATIC_DATES:
        assert spec.source == "boe_static"


def test_boe_static_dates_chronological_order():
    iso_dates = [s.iso_date for s in BOE_STATIC_DATES]
    assert iso_dates == sorted(iso_dates)


# =============================================================================
# all_static_events — agrégation FOMC + ECB + BoJ + BoE (Phase B2)
# =============================================================================


def test_all_static_events_length_equals_sum():
    """all_static_events() retourne la concat des 4 listes."""
    expected = (
        len(FOMC_STATIC_DATES)
        + len(ECB_STATIC_DATES)
        + len(BOJ_STATIC_DATES)
        + len(BOE_STATIC_DATES)
    )
    assert len(all_static_events()) == expected


def test_all_static_events_returns_tuple():
    """Retourne un tuple immutable (frozen-friendly)."""
    assert isinstance(all_static_events(), tuple)


def test_all_static_events_includes_all_central_banks():
    """La concat contient au moins 1 spec de chaque BC."""
    events = all_static_events()
    sources = {e.source for e in events}
    assert "fed_static" in sources
    assert "ecb_static" in sources
    assert "boj_static" in sources
    assert "boe_static" in sources


def test_all_static_events_unique_event_codes_per_source():
    """Pour chaque source, le event_code est constant (cohérence)."""
    events = all_static_events()
    by_source: dict[str, set[str]] = {}
    for e in events:
        by_source.setdefault(e.source, set()).add(e.event_code)
    for source, codes in by_source.items():
        assert len(codes) == 1, f"{source} a plusieurs event_codes: {codes}"


# =============================================================================
# date_to_utc_release — multi-timezone (Phase B2)
# =============================================================================


def test_date_to_utc_release_us_eastern_summer_dst():
    """En juin (EDT = UTC-4), 8h30 ET = 12h30 UTC."""
    dt = date_to_utc_release("2026-06-15", 8, 30)
    assert dt.tzinfo is timezone.utc
    assert dt.hour == 12
    assert dt.minute == 30


def test_date_to_utc_release_us_eastern_winter_no_dst():
    """En janvier (EST = UTC-5), 8h30 ET = 13h30 UTC."""
    dt = date_to_utc_release("2026-01-15", 8, 30)
    assert dt.hour == 13
    assert dt.minute == 30


def test_date_to_utc_release_europe_paris_summer_cest():
    """En juin (CEST = UTC+2), 14h15 ECB Frankfurt = 12h15 UTC."""
    dt = date_to_utc_release(
        "2026-06-11", 14, 15, tz_name="Europe/Paris"
    )
    assert dt.hour == 12
    assert dt.minute == 15


def test_date_to_utc_release_europe_paris_winter_cet():
    """En janvier (CET = UTC+1), 14h15 ECB Frankfurt = 13h15 UTC."""
    dt = date_to_utc_release(
        "2026-01-22", 14, 15, tz_name="Europe/Paris"
    )
    assert dt.hour == 13
    assert dt.minute == 15


def test_date_to_utc_release_asia_tokyo_no_dst():
    """Japon = UTC+9 constant. 12h00 JST = 03h00 UTC quel que soit le mois."""
    dt_jan = date_to_utc_release(
        "2026-01-23", 12, 0, tz_name="Asia/Tokyo"
    )
    dt_jul = date_to_utc_release(
        "2026-07-31", 12, 0, tz_name="Asia/Tokyo"
    )
    assert dt_jan.hour == 3
    assert dt_jul.hour == 3


def test_date_to_utc_release_europe_london_winter_gmt():
    """En janvier (GMT = UTC), 12h00 London = 12h00 UTC."""
    dt = date_to_utc_release(
        "2026-02-05", 12, 0, tz_name="Europe/London"
    )
    assert dt.hour == 12


def test_date_to_utc_release_europe_london_summer_bst():
    """En juin (BST = UTC+1), 12h00 London = 11h00 UTC."""
    dt = date_to_utc_release(
        "2026-06-19", 12, 0, tz_name="Europe/London"
    )
    assert dt.hour == 11


def test_date_to_utc_release_default_tz_is_us_eastern():
    """Sans tz_name explicite, fallback America/New_York (rétrocompat B1)."""
    dt = date_to_utc_release("2026-06-15", 8, 30)
    # 8h30 ET en juin (EDT) = 12h30 UTC
    assert dt.hour == 12


# =============================================================================
# build_event_from_fred / build_event_from_static (Phase B1 + B2)
# =============================================================================


def test_build_event_from_fred_structure():
    spec = FredReleaseSpec(
        release_id=50,
        event_code="NFP",
        event_name="Employment Situation (NFP)",
        importance="HIGH",
        release_hour_et=8,
        release_minute_et=30,
        assets_impacted=("BTC", "GOLD"),
    )
    ev = build_event_from_fred(spec, "2026-06-05")
    assert ev["event_code"] == "NFP"
    assert ev["event_name"] == "Employment Situation (NFP)"
    assert ev["importance"] == "HIGH"
    assert ev["assets_impacted"] == ["BTC", "GOLD"]
    assert ev["source"] == "fred"
    assert ev["release_id"] == 50
    # 8h30 ET en juin (EDT) = 12h30 UTC
    assert ev["scheduled_for"].hour == 12


def test_build_event_from_static_fomc_us():
    """Phase B1 — FOMC default → tz=US/Eastern, source=fed_static."""
    spec = StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-12-17",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    )
    ev = build_event_from_static(spec)
    assert ev["event_code"] == "FOMC_MEETING"
    assert ev["importance"] == "HIGH"
    assert ev["assets_impacted"] == ["BTC", "GOLD"]
    assert ev["source"] == "fed_static"
    assert ev["release_id"] is None
    # 14h00 ET en décembre (EST) = 19h00 UTC
    assert ev["scheduled_for"].hour == 19


def test_build_event_from_static_ecb_europe_paris():
    """Phase B2 — ECB → tz=Europe/Paris, source=ecb_static."""
    spec = StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-06-11",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    )
    ev = build_event_from_static(spec)
    assert ev["source"] == "ecb_static"
    # 14h15 CEST = 12h15 UTC
    assert ev["scheduled_for"].hour == 12
    assert ev["scheduled_for"].minute == 15


def test_build_event_from_static_boj_asia_tokyo():
    """Phase B2 — BoJ → tz=Asia/Tokyo (UTC+9), source=boj_static."""
    spec = StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-07-31",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    )
    ev = build_event_from_static(spec)
    assert ev["source"] == "boj_static"
    # 12h00 JST = 03h00 UTC
    assert ev["scheduled_for"].hour == 3


def test_build_event_from_static_boe_europe_london_summer():
    """Phase B2 — BoE en été → tz=Europe/London (BST = UTC+1), source=boe_static."""
    spec = StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-08-07",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    )
    ev = build_event_from_static(spec)
    assert ev["source"] == "boe_static"
    # 12h00 BST = 11h00 UTC
    assert ev["scheduled_for"].hour == 11


def test_build_event_from_fred_uses_real_whitelist_spec():
    """Test contre une spec réelle de la whitelist."""
    nfp_spec = next(s for s in FRED_RELEASES if s.event_code == "NFP")
    ev = build_event_from_fred(nfp_spec, "2026-07-03")
    assert ev["event_code"] == "NFP"
    assert ev["release_id"] == nfp_spec.release_id


def test_build_event_from_static_uses_real_whitelist_spec():
    """Test contre la première spec FOMC réelle."""
    fomc_spec = FOMC_STATIC_DATES[0]
    ev = build_event_from_static(fomc_spec)
    assert ev["event_code"] == "FOMC_MEETING"
    assert ev["source"] == "fed_static"


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
