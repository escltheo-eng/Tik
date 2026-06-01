"""Tests des helpers purs de `measure_polymarket` (mesure SHADOW lecture seule).

Durcissement de l'outillage avant le run de mesure ~2026-06-10 (cf. memory
polymarket-shadow-live). Couvre la logique de dérivation du signal (médiane
implicite), le matching de prix, le filtrage des seuils buggés (pré-fix Paquet
39), les métriques directionnelles, et surtout la **réduction au N indépendant**
(1 paire par event résolu) qui rend la mesure honnête (cf. memory
measurement-overlapping-returns).

100 % pur : aucune DB / Redis / HTTP.
"""

from __future__ import annotations

import math
from datetime import datetime

from tik_core.scripts.measure_polymarket import (
    count_buggy_thresholds,
    dedupe_one_pair_per_event,
    direction_metrics,
    implied_median,
    is_above_on_date,
    parse_iso,
    price_at,
)


class TestIsAboveOnDate:
    def test_true_for_above_on_date(self):
        assert is_above_on_date("Bitcoin above $80,000 on June 5?") is True
        assert is_above_on_date("BTC above 80k on 2026-06-05") is True

    def test_false_for_reach_family(self):
        assert is_above_on_date("What price will Bitcoin reach in June?") is False

    def test_false_for_non_bitcoin(self):
        assert is_above_on_date("Gold above 2000 on June 5") is False

    def test_false_for_none_or_empty(self):
        assert is_above_on_date(None) is False
        assert is_above_on_date("") is False


class TestParseIso:
    def test_z_suffix(self):
        d = parse_iso("2026-06-01T12:00:00Z")
        assert d is not None and d.year == 2026 and d.hour == 12

    def test_offset(self):
        assert parse_iso("2026-06-01T12:00:00+00:00") is not None

    def test_none_and_invalid(self):
        assert parse_iso(None) is None
        assert parse_iso("") is None
        assert parse_iso("pas une date") is None


class TestImpliedMedian:
    def test_crossing_interpolation(self):
        # P(>70k)=0.8, P(>80k)=0.3 → croise 0.5 à 70k + 0.6*(10k) = 76000.
        markets = [
            {"threshold_usd": 70000, "yes_prob": 0.8},
            {"threshold_usd": 80000, "yes_prob": 0.3},
        ]
        med = implied_median(markets)
        assert med is not None
        assert abs(med - 76000.0) < 1.0

    def test_no_crossing_returns_none(self):
        # Tout > 0.5 → pas de croisement.
        markets = [
            {"threshold_usd": 70000, "yes_prob": 0.8},
            {"threshold_usd": 75000, "yes_prob": 0.7},
        ]
        assert implied_median(markets) is None

    def test_single_point_returns_none(self):
        assert implied_median([{"threshold_usd": 70000, "yes_prob": 0.6}]) is None

    def test_filters_out_of_range_threshold_and_prob(self):
        # Seuil buggé 84e9 + proba hors [0,1] ignorés → < 2 points → None.
        markets = [
            {"threshold_usd": 84_000_000_000, "yes_prob": 0.8},
            {"threshold_usd": 80000, "yes_prob": 1.5},
        ]
        assert implied_median(markets) is None


class TestPriceAt:
    KLINES = [(1000, 100.0), (2000, 110.0), (3000, 120.0)]
    TIMES = [1000, 2000, 3000]

    def test_nearest_within_tolerance(self):
        # ts=2100 → plus proche de 2000 (diff 100) → 110.0
        assert price_at(self.KLINES, self.TIMES, 2100) == 110.0

    def test_outside_tolerance_returns_none(self):
        # ts très loin (> PRICE_TOL_MS 90 min) → None
        assert price_at(self.KLINES, self.TIMES, 10_000_000_000) is None

    def test_empty_klines_returns_none(self):
        assert price_at([], [], 2000) is None


class TestCountBuggyThresholds:
    def test_counts_above_max(self):
        snaps = [
            {
                "events": [
                    {"markets": [{"threshold_usd": 84_000_000_000}, {"threshold_usd": 80000}]},
                ]
            }
        ]
        assert count_buggy_thresholds(snaps) == 1

    def test_zero_when_all_sane(self):
        snaps = [{"events": [{"markets": [{"threshold_usd": 80000}]}]}]
        assert count_buggy_thresholds(snaps) == 0


class TestDirectionMetrics:
    def test_empty(self):
        m = direction_metrics([])
        assert m["n"] == 0
        assert m["ic"] is None

    def test_all_directions_correct(self):
        pairs = [(0.01, 0.02), (-0.01, -0.03), (0.02, 0.01)]
        m = direction_metrics(pairs)
        assert m["n"] == 3
        assert m["n_directional"] == 3
        assert m["hit_rate"] == 1.0
        assert m["gain"] > 0

    def test_all_neutral_signals_give_nan(self):
        # |signal| <= eps (1e-4) → aucun directionnel → NaN.
        pairs = [(0.0, 0.01), (0.00005, -0.01)]
        m = direction_metrics(pairs)
        assert m["n_directional"] == 0
        assert math.isnan(m["hit_rate"])
        assert math.isnan(m["gain"])


class TestDedupeOnePairPerEvent:
    def test_keeps_earliest_per_event(self):
        t1 = datetime(2030, 1, 1, 10, 0, 0)
        t2 = datetime(2030, 1, 1, 11, 0, 0)
        t3 = datetime(2030, 1, 1, 12, 0, 0)
        pairs_full = [
            ("e1", t2, 0.3, 0.4),  # plus tard pour e1
            ("e1", t1, 0.1, 0.2),  # plus tôt pour e1 → gardé
            ("e2", t3, 0.5, 0.6),
        ]
        result = dedupe_one_pair_per_event(pairs_full)
        assert len(result) == 2
        assert (0.1, 0.2) in result  # earliest e1
        assert (0.3, 0.4) not in result  # later e1 écarté
        assert (0.5, 0.6) in result

    def test_empty(self):
        assert dedupe_one_pair_per_event([]) == []
