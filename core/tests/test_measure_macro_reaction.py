"""Tests des helpers purs de measure_macro_reaction (shadow, lecture seule).

Pas de HTTP/FRED : on teste l'agrégation et le matching de clôtures journalières.
"""

from datetime import UTC, date, datetime

from tik_core.scripts.measure_macro_reaction import (
    _close_on_or_after,
    _close_on_or_before,
    aggregate,
    date_close_map,
    reaction,
)


def _ts(y: int, m: int, d: int) -> int:
    return int(datetime(y, m, d, tzinfo=UTC).timestamp() * 1000)


def _dt(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)


class TestDateCloseMap:
    def test_builds_map_by_date(self):
        m = date_close_map([(_ts(2026, 1, 1), 100.0), (_ts(2026, 1, 2), 110.0)])
        assert m[date(2026, 1, 1)] == 100.0
        assert m[date(2026, 1, 2)] == 110.0

    def test_empty(self):
        assert date_close_map([]) == {}


class TestCloseLookup:
    def _m(self):
        # Trous = week-end : pas de bougie les 3 et 4 (sam/dim).
        return {date(2026, 1, 2): 100.0, date(2026, 1, 5): 105.0}

    def test_on_or_before_exact(self):
        assert _close_on_or_before(self._m(), _dt(2026, 1, 2)) == 100.0

    def test_on_or_before_walks_back_over_gap(self):
        # 4 jan (dim) → remonte au 2 jan (ven).
        assert _close_on_or_before(self._m(), _dt(2026, 1, 4)) == 100.0

    def test_on_or_before_none_beyond_window(self):
        assert _close_on_or_before(self._m(), _dt(2026, 1, 20)) is None

    def test_on_or_after_exact(self):
        assert _close_on_or_after(self._m(), _dt(2026, 1, 5)) == 105.0

    def test_on_or_after_walks_forward_over_gap(self):
        # 3 jan (sam) → avance au 5 jan (lun).
        assert _close_on_or_after(self._m(), _dt(2026, 1, 3)) == 105.0

    def test_on_or_after_none_beyond_window(self):
        assert _close_on_or_after(self._m(), _dt(2025, 12, 1)) is None


class TestReaction:
    def test_signed_moves_vs_prev_close(self):
        # veille=100, jour=102 (+2%), J+1=99 (-1%), J+3=110 (+10%)
        m = {
            date(2026, 1, 1): 100.0,
            date(2026, 1, 2): 102.0,
            date(2026, 1, 3): 99.0,
            date(2026, 1, 5): 110.0,
        }
        r = reaction(m, _dt(2026, 1, 2))
        assert r is not None
        assert abs(r["same_day"] - 2.0) < 1e-9
        assert abs(r["+1d"] - (-1.0)) < 1e-9
        assert abs(r["+3d"] - 10.0) < 1e-9

    def test_none_when_no_baseline(self):
        m = {date(2026, 1, 2): 102.0}  # pas de clôture la veille
        assert reaction(m, _dt(2026, 1, 2)) is None

    def test_horizon_none_when_future_missing(self):
        m = {date(2026, 1, 1): 100.0, date(2026, 1, 2): 102.0}
        r = reaction(m, _dt(2026, 1, 2))
        assert r is not None
        assert r["same_day"] is not None
        assert r["+3d"] is None  # pas de donnée à J+3


class TestAggregate:
    def test_basic(self):
        agg = aggregate([1.0, -2.0, 3.0, None])
        assert agg["n"] == 3
        assert agg["median"] == 1.0
        assert abs(agg["pct_up"] - (2 / 3 * 100)) < 1e-9
        assert abs(agg["mean_abs"] - (6 / 3)) < 1e-9

    def test_empty_returns_none(self):
        assert aggregate([]) is None
        assert aggregate([None, None]) is None
