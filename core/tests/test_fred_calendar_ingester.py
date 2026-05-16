"""Tests unitaires du FredCalendarIngester (Lacune B Phase B1 J+10, ADR-017).

Couvre :
- `date_to_utc_release` : conversion date ET → datetime UTC aware avec DST.
- `filter_future_dates` : garde les dates ≥ now-30j (passé proche + futur).
- `build_event_from_fred` / `build_event_from_static` : sérialisation dict.
- Cycle ingester via mock httpx + mock session_maker (pas de DB ni réseau).

Pas de tests d'intégration FRED API (clé requise, validation runtime au déploiement).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import pytest

from tik_core.aggregator.fred_calendar_ingester import (
    FredCalendarIngester,
    build_event_from_fred,
    build_event_from_static,
    date_to_utc_release,
    filter_future_dates,
)
from tik_core.aggregator.macro_calendar_data import (
    FOMC_STATIC_DATES,
    FRED_RELEASES,
    FredReleaseSpec,
    StaticEventSpec,
)


# =============================================================================
# date_to_utc_release — DST, conversion ET → UTC
# =============================================================================


def test_date_to_utc_release_summer_dst():
    """En juin (EDT = UTC-4), 8h30 ET = 12h30 UTC."""
    dt = date_to_utc_release("2026-06-15", 8, 30)
    assert dt.tzinfo is timezone.utc
    assert dt.hour == 12
    assert dt.minute == 30
    assert dt.day == 15


def test_date_to_utc_release_winter_no_dst():
    """En janvier (EST = UTC-5), 8h30 ET = 13h30 UTC."""
    dt = date_to_utc_release("2026-01-15", 8, 30)
    assert dt.hour == 13
    assert dt.minute == 30


def test_date_to_utc_release_fomc_summer():
    """En juin (EDT), 14h00 ET (FOMC) = 18h00 UTC."""
    dt = date_to_utc_release("2026-06-18", 14, 0)
    assert dt.hour == 18
    assert dt.minute == 0


def test_date_to_utc_release_fomc_winter():
    """En décembre (EST), 14h00 ET (FOMC) = 19h00 UTC."""
    dt = date_to_utc_release("2026-12-17", 14, 0)
    assert dt.hour == 19
    assert dt.minute == 0


def test_date_to_utc_release_industrial_production():
    """9h15 ET en juillet (EDT) = 13h15 UTC."""
    dt = date_to_utc_release("2026-07-15", 9, 15)
    assert dt.hour == 13
    assert dt.minute == 15


# =============================================================================
# filter_future_dates
# =============================================================================


def test_filter_future_dates_keeps_today_and_future():
    """Aujourd'hui et futur sont gardés."""
    today = datetime.now(timezone.utc).date()
    future = (datetime.now(timezone.utc) + timedelta(days=10)).date()
    dates = [today.isoformat(), future.isoformat()]
    out = filter_future_dates(dates)
    assert today.isoformat() in out
    assert future.isoformat() in out


def test_filter_future_dates_keeps_recent_past_for_audit():
    """30 jours dans le passé : gardés (audit historique)."""
    recent = (datetime.now(timezone.utc) - timedelta(days=15)).date()
    dates = [recent.isoformat()]
    out = filter_future_dates(dates)
    assert recent.isoformat() in out


def test_filter_future_dates_drops_very_old():
    """Trop vieux (> 30 jours) : drop."""
    old = (datetime.now(timezone.utc) - timedelta(days=60)).date()
    dates = [old.isoformat()]
    out = filter_future_dates(dates)
    assert old.isoformat() not in out


def test_filter_future_dates_with_explicit_min_date():
    """Si min_date est fourni explicitement, c'est lui qui s'applique."""
    cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dates = ["2025-12-31", "2026-01-01", "2026-06-15"]
    out = filter_future_dates(dates, min_date=cutoff)
    assert "2025-12-31" not in out
    assert "2026-01-01" in out
    assert "2026-06-15" in out


def test_filter_future_dates_empty_input():
    assert filter_future_dates([]) == []


# =============================================================================
# build_event_from_fred / build_event_from_static
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


def test_build_event_from_static_structure():
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
# FredCalendarIngester — lifecycle + mock cycle
# =============================================================================


class _MockSession:
    def __init__(self, parent):
        self.parent = parent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, stmt):
        self.parent.executed_count += 1
        return None

    async def commit(self):
        self.parent.commit_count += 1


class _MockSessionMaker:
    def __init__(self):
        self.executed_count = 0
        self.commit_count = 0

    def __call__(self):
        return _MockSession(self)


async def test_ingester_no_api_key_does_not_start():
    """Sans clé FRED, le ingester log warning et ne démarre pas."""
    ing = FredCalendarIngester(api_key="", session_maker=_MockSessionMaker())
    await ing.start()
    assert ing._task is None
    assert ing._running is False


async def test_ingester_no_session_maker_does_not_start():
    """Sans session_maker, le ingester log warning et ne démarre pas."""
    ing = FredCalendarIngester(api_key="abc", session_maker=None)
    await ing.start()
    assert ing._task is None


async def test_ingester_fetch_release_dates_handles_http_error():
    """Erreur HTTP → log warning, retourne []."""
    ing = FredCalendarIngester(
        api_key="abc", session_maker=_MockSessionMaker()
    )

    def _broken_handler(request):
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(_broken_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        nfp_spec = next(s for s in FRED_RELEASES if s.event_code == "NFP")
        out = await ing._fetch_release_dates(client, nfp_spec)
    assert out == []


async def test_ingester_fetch_release_dates_parses_response():
    """Réponse FRED valide → liste de dates ISO."""
    ing = FredCalendarIngester(
        api_key="abc", session_maker=_MockSessionMaker()
    )

    def _ok_handler(request):
        return httpx.Response(
            200,
            json={
                "release_dates": [
                    {"release_id": 50, "date": "2026-06-05"},
                    {"release_id": 50, "date": "2026-07-03"},
                ]
            },
        )

    transport = httpx.MockTransport(_ok_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        nfp_spec = next(s for s in FRED_RELEASES if s.event_code == "NFP")
        out = await ing._fetch_release_dates(client, nfp_spec)
    assert out == ["2026-06-05", "2026-07-03"]


async def test_ingester_fetch_release_dates_skips_empty_dates():
    """Entries sans date sont skippées (rare mais possible avec include_with_no_data)."""
    ing = FredCalendarIngester(
        api_key="abc", session_maker=_MockSessionMaker()
    )

    def _ok_handler(request):
        return httpx.Response(
            200,
            json={
                "release_dates": [
                    {"release_id": 50, "date": ""},
                    {"release_id": 50, "date": None},
                    {"release_id": 50, "date": "2026-06-05"},
                ]
            },
        )

    transport = httpx.MockTransport(_ok_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        nfp_spec = next(s for s in FRED_RELEASES if s.event_code == "NFP")
        out = await ing._fetch_release_dates(client, nfp_spec)
    assert out == ["2026-06-05"]


async def test_ingester_cycle_does_not_include_static_fomc(monkeypatch):
    """Phase B2 (ADR-020) : le cycle FRED ne gère plus les FOMC statiques.

    Les FOMC dates sont désormais upsertées par `MacroStaticIngester`
    séparément. Ici on stub `_fetch_release_dates` pour retourner une
    liste vide → si la séparation est respectée, `upsert_many` reçoit
    0 events (aucun FRED, aucun FOMC).
    """
    sm = _MockSessionMaker()
    ing = FredCalendarIngester(api_key="abc", session_maker=sm)

    async def _stub_fetch(self_ing, client, spec):
        return []

    monkeypatch.setattr(
        FredCalendarIngester, "_fetch_release_dates", _stub_fetch
    )

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.fred_calendar_ingester.upsert_many",
        _stub_upsert,
    )

    n = await ing._cycle()

    # Phase B2 : aucun FOMC dans le cycle FRED (déplacé vers MacroStaticIngester)
    assert n == 0
    fomc_events = [e for e in captured_events if e["event_code"] == "FOMC_MEETING"]
    assert fomc_events == []


async def test_ingester_cycle_includes_fred_dates_only(monkeypatch):
    """Le cycle FRED retourne uniquement des events `source="fred"` (Phase B2).

    Stub `_fetch_release_dates` pour retourner 1 date → 1 event FRED
    attendu (pour chaque release de la whitelist).
    """
    sm = _MockSessionMaker()
    ing = FredCalendarIngester(api_key="abc", session_maker=sm)

    async def _stub_fetch(self_ing, client, spec):
        # 1 date par release pour vérifier le branchement
        return ["2026-06-05"]

    monkeypatch.setattr(
        FredCalendarIngester, "_fetch_release_dates", _stub_fetch
    )

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.fred_calendar_ingester.upsert_many",
        _stub_upsert,
    )

    n = await ing._cycle()

    # 1 event par release de la whitelist
    assert n == len(FRED_RELEASES)
    # Tous les events ont source="fred", pas de fed_static
    assert all(e["source"] == "fred" for e in captured_events)
    assert all(e["release_id"] is not None for e in captured_events)
