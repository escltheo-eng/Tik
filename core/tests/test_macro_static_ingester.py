"""Tests unitaires du MacroStaticIngester (Phase B2 — ADR-020).

Couvre :
- Lifecycle : pas de session_maker → skip propre, ne crash pas.
- `_cycle()` : upsert toutes les dates statiques (FOMC + ECB + BoJ + BoE)
  via un stub `upsert_many` qui capture les events.
- Best-effort : erreur DB → retourne 0, pas de crash.

Pas de tests d'intégration DB réelle (validation runtime au déploiement).
"""

from __future__ import annotations

from tik_core.aggregator.macro_calendar_data import (
    BOE_STATIC_DATES,
    BOJ_STATIC_DATES,
    ECB_STATIC_DATES,
    FOMC_STATIC_DATES,
    all_static_events,
)
from tik_core.aggregator.macro_static_ingester import MacroStaticIngester


# =============================================================================
# Mocks DB session
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


# =============================================================================
# Lifecycle
# =============================================================================


async def test_ingester_no_session_maker_does_not_start():
    """Sans session_maker, le ingester log warning et ne démarre pas."""
    ing = MacroStaticIngester(session_maker=None)
    await ing.start()
    assert ing._task is None
    assert ing._running is False


async def test_ingester_with_session_maker_starts_then_stops(monkeypatch):
    """Avec session_maker, le ingester démarre. stop() arrête proprement."""
    sm = _MockSessionMaker()

    # Stub upsert_many pour éviter d'attendre un cycle complet
    async def _stub_upsert(session_maker, events):
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    # interval_s très grand pour qu'un seul cycle se lance puis sleep
    ing = MacroStaticIngester(session_maker=sm, interval_s=3600)
    await ing.start()
    assert ing._task is not None
    assert ing._running is True

    await ing.stop()
    assert ing._running is False


# =============================================================================
# _cycle()
# =============================================================================


async def test_cycle_upserts_all_static_events(monkeypatch):
    """Le cycle upsert tous les events statiques (FOMC + ECB + BoJ + BoE)."""
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    n = await ing._cycle()

    expected_total = len(all_static_events())
    assert n == expected_total
    assert len(captured_events) == expected_total


async def test_cycle_includes_all_central_bank_sources(monkeypatch):
    """Vérifie que les 4 sources sont représentées dans le cycle."""
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    await ing._cycle()

    sources = {e["source"] for e in captured_events}
    assert "fed_static" in sources
    assert "ecb_static" in sources
    assert "boj_static" in sources
    assert "boe_static" in sources


async def test_cycle_fomc_count_matches_static_list(monkeypatch):
    """Le nombre d'events FOMC dans le cycle = len(FOMC_STATIC_DATES)."""
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    await ing._cycle()

    fomc_events = [e for e in captured_events if e["source"] == "fed_static"]
    assert len(fomc_events) == len(FOMC_STATIC_DATES)
    assert all(e["event_code"] == "FOMC_MEETING" for e in fomc_events)


async def test_cycle_ecb_count_matches_static_list(monkeypatch):
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    await ing._cycle()

    ecb_events = [e for e in captured_events if e["source"] == "ecb_static"]
    assert len(ecb_events) == len(ECB_STATIC_DATES)
    assert all(e["event_code"] == "ECB_GOVERNING_COUNCIL" for e in ecb_events)


async def test_cycle_boj_count_matches_static_list(monkeypatch):
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    await ing._cycle()

    boj_events = [e for e in captured_events if e["source"] == "boj_static"]
    assert len(boj_events) == len(BOJ_STATIC_DATES)
    assert all(e["event_code"] == "BOJ_MPM" for e in boj_events)


async def test_cycle_boe_count_matches_static_list(monkeypatch):
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    await ing._cycle()

    boe_events = [e for e in captured_events if e["source"] == "boe_static"]
    assert len(boe_events) == len(BOE_STATIC_DATES)
    assert all(e["event_code"] == "BOE_MPC" for e in boe_events)


async def test_cycle_returns_zero_on_db_error(monkeypatch):
    """Best-effort : upsert_many échec → retourne 0, pas de crash."""
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    async def _broken_upsert(session_maker, events):
        return 0  # upsert_many est best-effort et retourne 0 sur erreur

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _broken_upsert,
    )

    n = await ing._cycle()
    assert n == 0


# =============================================================================
# Cohérence sortie ingester (timezones et structure)
# =============================================================================


async def test_cycle_events_have_required_fields(monkeypatch):
    """Tous les events upsertés ont les champs attendus par macro_events_repo."""
    sm = _MockSessionMaker()
    ing = MacroStaticIngester(session_maker=sm)

    captured_events: list = []

    async def _stub_upsert(session_maker, events):
        captured_events.extend(events)
        return len(events)

    monkeypatch.setattr(
        "tik_core.aggregator.macro_static_ingester.upsert_many",
        _stub_upsert,
    )

    await ing._cycle()

    required_keys = {
        "event_code",
        "event_name",
        "scheduled_for",
        "importance",
        "assets_impacted",
        "source",
        "release_id",
    }
    for ev in captured_events:
        assert required_keys.issubset(ev.keys())
        # release_id toujours None pour les events statiques
        assert ev["release_id"] is None
        # scheduled_for est timezone-aware UTC
        assert ev["scheduled_for"].tzinfo is not None
