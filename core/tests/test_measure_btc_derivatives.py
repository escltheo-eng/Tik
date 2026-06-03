"""Tests des fonctions pures de measure_btc_derivatives (SHADOW, ADR-023).

Lecture seule, aucune dépendance Redis/réseau : on teste le tri chronologique,
le calcul des rendements forward et l'IC prédictif (N chevauchant vs non
chevauchant) sur des données construites.
"""

import json

from tik_core.scripts.measure_btc_derivatives import (
    _stats,
    forward_returns,
    predictive_ic,
    to_chronological,
)


class TestToChronological:
    def test_sorts_and_filters(self):
        raw = [
            json.dumps({"fetched_at": "2026-06-03T03:00:00+00:00", "mark_price": 3}),
            json.dumps({"fetched_at": "2026-06-03T01:00:00+00:00", "mark_price": 1}),
            "not-json",  # ignoré
            json.dumps({"mark_price": 5}),  # pas de fetched_at → ignoré
        ]
        snaps = to_chronological(raw)
        assert len(snaps) == 2
        assert [s["mark_price"] for s in snaps] == [1, 3]  # trié ascendant

    def test_empty(self):
        assert to_chronological([]) == []


class TestForwardReturns:
    def test_horizon_1(self):
        prices = [100.0, 110.0, 121.0, None]
        out = forward_returns(prices, 1)
        assert out[0] == 0.1  # (110-100)/100
        assert abs(out[1] - 0.1) < 1e-9  # (121-110)/110
        assert out[2] is None  # P[3] manquant
        assert out[3] is None  # hors série

    def test_zero_price_guard(self):
        assert forward_returns([0.0, 100.0], 1)[0] is None


class TestPredictiveIc:
    def test_perfect_monotonic(self):
        # spearman_correlation exige ≥ 5 points → 5 paires alignées minimum.
        metric = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        fwd = [0.1, 0.2, 0.3, 0.4, 0.5, None]
        res = predictive_ic(metric, fwd, horizon=1)
        assert res["n_overlap"] == 5
        assert res["ic"] == 1.0  # croissance monotone parfaite

    def test_non_overlapping_subsample_spacing(self):
        metric = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        fwd = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        res = predictive_ic(metric, fwd, horizon=2)
        # Sous-échantillon non chevauchant : i = 0, 2, 4 → 3 points.
        assert res["n_indep"] == 3

    def test_too_few_points(self):
        # 4 paires alignées < 5 → IC non calculable (contrat spearman_correlation).
        res = predictive_ic([1.0, 2.0, 3.0, 4.0], [0.1, 0.2, 0.3, 0.4], horizon=1)
        assert res["n_overlap"] == 4
        assert res["ic"] is None


class TestStats:
    def test_basic(self):
        st = _stats([1.0, 2.0, 3.0, 4.0])
        assert st["n"] == 4
        assert st["min"] == 1.0
        assert st["max"] == 4.0
        assert st["median"] == 2.5
        assert st["mean"] == 2.5
        assert st["pct_pos"] == 100.0

    def test_with_none_and_negative(self):
        st = _stats([None, -1.0, 1.0, 3.0])
        assert st["n"] == 3
        assert st["median"] == 1.0
        assert abs(st["pct_pos"] - 66.666) < 0.01

    def test_empty(self):
        st = _stats([None, None])
        assert st["n"] == 0
        assert st["median"] is None
