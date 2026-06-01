"""Tests du couplage signal ↔ event macro (Phase B1.5, scoring/macro_proximity).

Couvre :
- `find_nearest_macro_event` (fonction pure : fenêtre ±4h, plus proche, signe
  de hours_until, datetimes aware/naïf, bornes, liste vide).
- `annotate_near_macro_event` (best-effort : pose le flag, filtre par entité,
  avale les erreurs DB sans bloquer l'émission, crée advisory si absent).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from tik_core.scoring.macro_proximity import (
    NEAR_MACRO_WINDOW_HOURS,
    annotate_near_macro_event,
    find_nearest_macro_event,
)

# Référence : signal émis le 2026-06-05 à 10:30 UTC (naïf, comme en DB).
SIG_TS = datetime(2026, 6, 5, 10, 30, 0)


@dataclass
class FakeEvent:
    event_code: str
    event_name: str
    scheduled_for: datetime
    importance: str = "HIGH"
    assets_impacted: list[str] = field(default_factory=lambda: ["BTC", "GOLD"])


def _evt(code: str, when: datetime, **kw) -> FakeEvent:
    return FakeEvent(event_code=code, event_name=f"{code} event", scheduled_for=when, **kw)


# ---------- find_nearest_macro_event (pur) ----------


class TestFindNearest:
    def test_event_2h_in_future_returned_positive_hours(self):
        ev = _evt("NFP", SIG_TS + timedelta(hours=2))
        out = find_nearest_macro_event(SIG_TS, [ev])
        assert out is not None
        assert out["event_code"] == "NFP"
        assert out["title"] == "NFP event"
        assert out["importance"] == "HIGH"
        assert out["hours_until"] == 2.0
        assert out["scheduled_for"].endswith("Z")

    def test_event_2h_in_past_returned_negative_hours(self):
        ev = _evt("CPI", SIG_TS - timedelta(hours=2))
        out = find_nearest_macro_event(SIG_TS, [ev])
        assert out is not None
        assert out["event_code"] == "CPI"
        assert out["hours_until"] == -2.0

    def test_event_exactly_at_window_boundary_included(self):
        ev = _evt("FOMC", SIG_TS + timedelta(hours=NEAR_MACRO_WINDOW_HOURS))
        out = find_nearest_macro_event(SIG_TS, [ev])
        assert out is not None
        assert out["hours_until"] == 4.0

    def test_event_just_outside_window_excluded(self):
        ev = _evt("FOMC", SIG_TS + timedelta(hours=NEAR_MACRO_WINDOW_HOURS, minutes=1))
        assert find_nearest_macro_event(SIG_TS, [ev]) is None

    def test_picks_nearest_among_several(self):
        events = [
            _evt("FOMC", SIG_TS + timedelta(hours=3, minutes=30)),
            _evt("NFP", SIG_TS + timedelta(minutes=40)),  # le plus proche
            _evt("CPI", SIG_TS - timedelta(hours=2)),
        ]
        out = find_nearest_macro_event(SIG_TS, events)
        assert out is not None
        assert out["event_code"] == "NFP"

    def test_empty_list_returns_none(self):
        assert find_nearest_macro_event(SIG_TS, []) is None

    def test_aware_signal_ts_handled(self):
        ts_aware = SIG_TS.replace(tzinfo=UTC)
        ev = _evt("NFP", SIG_TS + timedelta(hours=1))
        out = find_nearest_macro_event(ts_aware, [ev])
        assert out is not None
        assert out["hours_until"] == 1.0

    def test_aware_event_scheduled_for_handled(self):
        ev = _evt("NFP", (SIG_TS + timedelta(hours=1)).replace(tzinfo=UTC))
        out = find_nearest_macro_event(SIG_TS, [ev])
        assert out is not None
        assert out["hours_until"] == 1.0

    def test_custom_window_hours(self):
        ev = _evt("NFP", SIG_TS + timedelta(hours=5))
        assert find_nearest_macro_event(SIG_TS, [ev]) is None  # hors ±4h
        out = find_nearest_macro_event(SIG_TS, [ev], window_hours=6.0)
        assert out is not None and out["hours_until"] == 5.0


# ---------- annotate_near_macro_event (async, best-effort) ----------


def _mock_session(rows: list[FakeEvent]) -> MagicMock:
    """Session dont `await session.execute(...)` renvoie `rows` via scalars().all()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _decision(entity_id: str = "BTC", advisory=None) -> SimpleNamespace:
    return SimpleNamespace(
        entity_id=entity_id,
        timestamp=SIG_TS,
        advisory={} if advisory is None else advisory,
    )


@pytest.mark.asyncio
class TestAnnotate:
    async def test_sets_flag_when_event_in_window(self):
        session = _mock_session([_evt("NFP", SIG_TS + timedelta(hours=2))])
        decision = _decision("BTC")
        await annotate_near_macro_event(session, decision)
        flag = decision.advisory["near_macro_event"]
        assert flag["event_code"] == "NFP"
        assert flag["hours_until"] == 2.0

    async def test_filters_out_event_not_impacting_entity(self):
        # Event impacte GOLD seulement ; signal BTC → pas de flag.
        session = _mock_session(
            [_evt("XAU", SIG_TS + timedelta(hours=1), assets_impacted=["GOLD"])]
        )
        decision = _decision("BTC")
        await annotate_near_macro_event(session, decision)
        assert "near_macro_event" not in decision.advisory

    async def test_empty_assets_impacted_treated_as_all(self):
        session = _mock_session([_evt("WORLD", SIG_TS + timedelta(hours=1), assets_impacted=[])])
        decision = _decision("BTC")
        await annotate_near_macro_event(session, decision)
        assert decision.advisory["near_macro_event"]["event_code"] == "WORLD"

    async def test_no_event_no_flag(self):
        session = _mock_session([])
        decision = _decision("BTC")
        await annotate_near_macro_event(session, decision)
        assert "near_macro_event" not in decision.advisory

    async def test_db_error_is_swallowed_and_advisory_untouched(self):
        session = MagicMock()
        session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
        decision = _decision("BTC")
        # Ne lève PAS (best-effort) — l'émission ne doit jamais être bloquée.
        await annotate_near_macro_event(session, decision)
        assert decision.advisory == {}

    async def test_creates_advisory_dict_when_absent(self):
        session = _mock_session([_evt("CPI", SIG_TS + timedelta(hours=1))])
        decision = _decision("GOLD", advisory=None)
        decision.advisory = None  # simule advisory non-dict
        await annotate_near_macro_event(session, decision)
        assert isinstance(decision.advisory, dict)
        assert decision.advisory["near_macro_event"]["event_code"] == "CPI"


# ---------- schéma : near_macro_event doit survivre à la sérialisation REST ----------


class TestSchemaPassthrough:
    def test_signalout_keeps_near_macro_event(self):
        from tik_core.storage.schemas import SignalOut

        signal = SignalOut(
            id="TIK-SWING-BTC-x",
            timestamp=SIG_TS,
            entity_id="BTC",
            horizon="swing",
            direction="short",
            confidence=0.5,
            veracity=0.85,
            advisory={
                "near_macro_event": {
                    "event_code": "NFP",
                    "title": "NFP event",
                    "scheduled_for": "2026-06-05T12:30:00Z",
                    "importance": "HIGH",
                    "hours_until": 2.0,
                }
            },
        )
        dumped = signal.model_dump(mode="json")
        assert dumped["advisory"]["near_macro_event"]["event_code"] == "NFP"
        assert dumped["advisory"]["near_macro_event"]["hours_until"] == 2.0
