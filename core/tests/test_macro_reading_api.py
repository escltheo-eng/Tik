"""Tests des helpers purs de l'endpoint /macro_reading (mapping agg → schéma)."""

from tik_core.api.macro_reading import _asset, _stat


class TestStat:
    def test_none_on_empty(self):
        assert _stat(None) is None
        assert _stat({}) is None

    def test_maps_and_rounds(self):
        s = _stat({"n": 33, "median": 1.814, "pct_up": 72.7, "mean_abs": 3.681})
        assert s is not None
        assert s.n == 33
        assert s.median == 1.81
        assert s.pct_up == 73.0
        assert s.mean_abs == 3.68


class TestAsset:
    def test_none_when_no_aggs(self):
        assert _asset(None) is None
        assert _asset({}) is None

    def test_maps_labels_plus1d_plus3d(self):
        a = _asset(
            {
                "same_day": {"n": 1, "median": 0.5, "pct_up": 100, "mean_abs": 0.5},
                "+1d": None,
                "+3d": {"n": 2, "median": 1.0, "pct_up": 50, "mean_abs": 1.0},
            }
        )
        assert a is not None
        assert a.same_day is not None and a.same_day.n == 1
        assert a.d1 is None
        assert a.d3 is not None and a.d3.median == 1.0

    def test_none_when_all_horizons_none(self):
        assert _asset({"same_day": None, "+1d": None, "+3d": None}) is None
