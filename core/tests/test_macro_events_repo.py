"""Tests unitaires du repo macro_events (Lacune B Phase B1 J+10, ADR-017).

Couvre les helpers purs (`to_naive_utc`, `cutoff_horizon_naive`,
`cutoff_history_naive`) et le comportement de `upsert_many` avec un
mock session_maker (pas de DB réelle nécessaire).

Les fonctions `fetch_upcoming` / `fetch_history` (qui dépendent du SQL)
sont testées en intégration runtime au déploiement.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from tik_core.storage.macro_events_repo import (
    cutoff_history_naive,
    cutoff_horizon_naive,
    to_naive_utc,
    upsert_many,
)


# =============================================================================
# to_naive_utc — strip tzinfo cohérent ADR-013 / Bug 9
# =============================================================================


def test_to_naive_utc_strips_aware_utc():
    aware = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    naive = to_naive_utc(aware)
    assert naive.tzinfo is None
    assert naive.hour == 12


def test_to_naive_utc_converts_other_offset_to_utc_then_strips():
    """+02:00 → -02:00 en UTC, puis tzinfo=None."""
    et = timezone(timedelta(hours=-4))
    aware = datetime(2026, 6, 5, 8, 30, tzinfo=et)  # 8h30 EDT
    naive = to_naive_utc(aware)
    assert naive.tzinfo is None
    assert naive.hour == 12
    assert naive.minute == 30


def test_to_naive_utc_passes_through_naive():
    naive = datetime(2026, 5, 6, 12, 0)
    out = to_naive_utc(naive)
    assert out == naive
    assert out.tzinfo is None


# =============================================================================
# cutoff_horizon_naive / cutoff_history_naive
# =============================================================================


def test_cutoff_horizon_naive_returns_naive_pair():
    now, until = cutoff_horizon_naive(168)
    assert now.tzinfo is None
    assert until.tzinfo is None
    delta = until - now
    assert delta == timedelta(hours=168)


def test_cutoff_horizon_naive_24h():
    now, until = cutoff_horizon_naive(24)
    delta = until - now
    assert abs(delta.total_seconds() - 86400) < 1


def test_cutoff_history_naive_subtracts_days():
    cutoff = cutoff_history_naive(30)
    assert cutoff.tzinfo is None
    now_naive = datetime.utcnow()  # noqa: DTZ003
    delta = now_naive - cutoff
    # Tolère 5 secondes d'écart pour temps d'exécution
    assert abs(delta.total_seconds() - 30 * 86400) < 5


# =============================================================================
# upsert_many — None / empty / mock
# =============================================================================


class _MockSession:
    def __init__(self, parent):
        self.parent = parent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def execute(self, stmt):
        self.parent.execute_count += 1
        return None

    async def commit(self):
        self.parent.commit_count += 1


class _MockSessionMaker:
    def __init__(self, raise_on_execute: Exception | None = None):
        self.execute_count = 0
        self.commit_count = 0
        self._raise = raise_on_execute

    def __call__(self):
        if self._raise is not None:
            class _BrokenSession:
                def __init__(self_inner, parent):
                    self_inner.parent = parent

                async def __aenter__(self_inner):
                    return self_inner

                async def __aexit__(self_inner, *args):
                    return None

                async def execute(self_inner, stmt):
                    raise self._raise

                async def commit(self_inner):
                    pass

            return _BrokenSession(self)
        return _MockSession(self)


async def test_upsert_many_none_session_maker():
    """session_maker=None → 0 (rétrocompat)."""
    out = await upsert_many(None, [{"event_code": "X"}])
    assert out == 0


async def test_upsert_many_empty_list():
    """Liste vide → 0, pas de session ouverte."""
    sm = _MockSessionMaker()
    out = await upsert_many(sm, [])
    assert out == 0
    assert sm.execute_count == 0
    assert sm.commit_count == 0


async def test_upsert_many_executes_per_event():
    """N events → N executes + 1 commit."""
    sm = _MockSessionMaker()
    events = [
        {
            "event_code": "NFP",
            "event_name": "Employment",
            "scheduled_for": datetime(2026, 6, 5, 12, 30, tzinfo=timezone.utc),
            "importance": "HIGH",
            "assets_impacted": ["BTC", "GOLD"],
            "source": "fred",
            "release_id": 50,
        },
        {
            "event_code": "CPI",
            "event_name": "Consumer Price Index",
            "scheduled_for": datetime(2026, 6, 12, 12, 30, tzinfo=timezone.utc),
            "importance": "HIGH",
            "assets_impacted": ["BTC", "GOLD"],
            "source": "fred",
            "release_id": 10,
        },
    ]
    n = await upsert_many(sm, events)
    assert n == 2
    assert sm.execute_count == 2
    assert sm.commit_count == 1


async def test_upsert_many_swallows_db_error():
    """Erreur DB → 0, pas de raise."""
    sm = _MockSessionMaker(raise_on_execute=RuntimeError("postgres down"))
    events = [
        {
            "event_code": "NFP",
            "event_name": "Employment",
            "scheduled_for": datetime(2026, 6, 5, 12, 30, tzinfo=timezone.utc),
            "importance": "HIGH",
            "assets_impacted": ["BTC", "GOLD"],
            "source": "fred",
            "release_id": 50,
        },
    ]
    n = await upsert_many(sm, events)
    assert n == 0
