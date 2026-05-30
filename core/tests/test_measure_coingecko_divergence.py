"""Tests purs de l'instrument de divergence CoinGecko vs Fear & Greed (ADR-021 D4).

Zéro réseau/Redis : agrégation quotidienne, parsing FG, appariement, accord
directionnel, divergence, étiquette de verdict.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from tik_core.scripts.measure_coingecko_divergence import (
    COMPLEMENTARY_THRESHOLD,
    REDUNDANT_THRESHOLD,
    _median,
    centered_directional_agreement,
    daily_coingecko,
    directional_agreement,
    divergence_stats,
    fg_by_day,
    movement_agreement,
    movement_deltas,
    movement_stats,
    pair_by_day,
    primary_spearman,
    verdict_label,
)


def _snap(up, when: str) -> dict:
    return {"source": "coingecko_sentiment", "up_pct": up, "fetched_at": when}


class TestDailyCoingecko:
    def test_mean_per_day(self):
        snaps = [
            _snap(60.0, "2026-05-27T05:00:00+00:00"),
            _snap(40.0, "2026-05-27T06:00:00+00:00"),
            _snap(50.0, "2026-05-28T05:00:00+00:00"),
        ]
        out = daily_coingecko(snaps)
        assert out[date(2026, 5, 27)] == pytest.approx(50.0)
        assert out[date(2026, 5, 28)] == pytest.approx(50.0)

    @pytest.mark.parametrize("bad", [None, "x", 150.0, -1.0])
    def test_skips_invalid_up(self, bad):
        out = daily_coingecko([_snap(bad, "2026-05-27T05:00:00+00:00")])
        assert out == {}

    def test_skips_bad_fetched_at(self):
        out = daily_coingecko([_snap(60.0, "pas une date")])
        assert out == {}

    def test_empty(self):
        assert daily_coingecko([]) == {}


class TestFgByDay:
    def test_parses_unix_and_value(self):
        ts = int(datetime(2026, 5, 27, tzinfo=UTC).timestamp())
        out = fg_by_day([{"timestamp": str(ts), "value": "25"}])
        assert out == {date(2026, 5, 27): 25.0}

    @pytest.mark.parametrize(
        "entry",
        [
            {"timestamp": "abc", "value": "25"},
            {"timestamp": "123", "value": "x"},
            {"value": "25"},
            {"timestamp": "123"},
        ],
    )
    def test_skips_bad(self, entry):
        assert fg_by_day([entry]) == {}

    def test_out_of_range_value_skipped(self):
        ts = int(datetime(2026, 5, 27, tzinfo=UTC).timestamp())
        assert fg_by_day([{"timestamp": str(ts), "value": "200"}]) == {}


class TestPairByDay:
    def test_intersection_only(self):
        cg = {date(2026, 5, 26): 60.0, date(2026, 5, 27): 55.0, date(2026, 5, 28): 50.0}
        fg = {date(2026, 5, 27): 30.0, date(2026, 5, 28): 25.0, date(2026, 5, 30): 40.0}
        assert pair_by_day(cg, fg) == [(55.0, 30.0), (50.0, 25.0)]

    def test_no_overlap(self):
        assert pair_by_day({date(2026, 5, 1): 50.0}, {date(2026, 6, 1): 50.0}) == []


class TestDirectionalAgreement:
    def test_both_above_or_below_agree(self):
        pairs = [(60.0, 70.0), (40.0, 30.0)]  # haut/haut + bas/bas
        assert directional_agreement(pairs) == pytest.approx(100.0)

    def test_opposite_disagree(self):
        pairs = [(60.0, 40.0), (45.0, 70.0)]
        assert directional_agreement(pairs) == pytest.approx(0.0)

    def test_midpoint_excluded(self):
        # (50,x) et (x,50) exclus → reste 1 paire d'accord
        pairs = [(50.0, 70.0), (60.0, 80.0), (45.0, 50.0)]
        assert directional_agreement(pairs) == pytest.approx(100.0)

    def test_none_when_all_midpoint(self):
        assert directional_agreement([(50.0, 50.0)]) is None


class TestDivergenceStats:
    def test_perfect_rank_correlation(self):
        # spearman_correlation exige ≥ 5 points (sinon None)
        pairs = [(10.0, 20.0), (20.0, 30.0), (30.0, 40.0), (40.0, 50.0), (50.0, 60.0)]
        s = divergence_stats(pairs)
        assert s["spearman"] == pytest.approx(1.0)
        assert s["mean_abs_norm_diff"] == pytest.approx(0.10)  # |diff|=10 → /100

    def test_anti_correlation(self):
        pairs = [(10.0, 50.0), (20.0, 40.0), (30.0, 30.0), (40.0, 20.0), (50.0, 10.0)]
        assert divergence_stats(pairs)["spearman"] == pytest.approx(-1.0)

    def test_below_five_points_spearman_none(self):
        # < 5 points → spearman None (mais mad/agreement restent calculés)
        s = divergence_stats([(10.0, 20.0), (20.0, 30.0)])
        assert s["spearman"] is None
        assert s["mean_abs_norm_diff"] == pytest.approx(0.10)

    def test_empty_all_none(self):
        s = divergence_stats([])
        assert s["spearman"] is None and s["mean_abs_norm_diff"] is None


class TestVerdictLabel:
    def test_redundant(self):
        assert "REDONDANT" in verdict_label(REDUNDANT_THRESHOLD)
        assert "REDONDANT" in verdict_label(-0.85)  # |valeur| compte

    def test_partial(self):
        assert "PARTIEL" in verdict_label((REDUNDANT_THRESHOLD + COMPLEMENTARY_THRESHOLD) / 2)

    def test_complementary(self):
        assert "COMPLÉMENTAIRE" in verdict_label(0.10)

    def test_none(self):
        assert "indéterminé" in verdict_label(None)


class TestMedian:
    def test_odd(self):
        assert _median([3.0, 1.0, 2.0]) == pytest.approx(2.0)

    def test_even(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)


class TestMovementDeltas:
    def test_consecutive_deltas(self):
        # paires triées par jour → deltas jour-à-jour
        pairs = [(60.0, 25.0), (63.0, 22.0), (65.0, 23.0)]
        assert movement_deltas(pairs) == [(3.0, -3.0), (2.0, 1.0)]

    def test_too_few_pairs(self):
        assert movement_deltas([(60.0, 25.0)]) == []

    def test_empty(self):
        assert movement_deltas([]) == []


class TestMovementAgreement:
    def test_same_direction_agree(self):
        assert movement_agreement([(3.0, 2.0), (-1.0, -4.0)]) == pytest.approx(100.0)

    def test_opposite_disagree(self):
        assert movement_agreement([(3.0, -2.0), (-1.0, 4.0)]) == pytest.approx(0.0)

    def test_mixed_50(self):
        assert movement_agreement([(3.0, 2.0), (3.0, -2.0)]) == pytest.approx(50.0)

    def test_zero_delta_excluded(self):
        # (0, 3) exclu → reste (2, 5) qui s'accorde
        assert movement_agreement([(0.0, 3.0), (2.0, 5.0)]) == pytest.approx(100.0)

    def test_none_when_all_zero(self):
        assert movement_agreement([(0.0, 1.0), (2.0, 0.0)]) is None

    def test_empty_none(self):
        assert movement_agreement([]) is None


class TestCenteredDirectionalAgreement:
    def test_all_agree(self):
        # cg médiane 65, fg médiane 25 ; chaque paire du même côté des deux médianes
        pairs = [(60.0, 20.0), (70.0, 30.0), (50.0, 15.0), (80.0, 40.0)]
        assert centered_directional_agreement(pairs) == pytest.approx(100.0)

    def test_all_disagree(self):
        # mêmes niveaux, FG inversé → opposés vs leurs médianes respectives
        pairs = [(60.0, 40.0), (70.0, 15.0), (50.0, 30.0), (80.0, 20.0)]
        assert centered_directional_agreement(pairs) == pytest.approx(0.0)

    def test_too_few_pairs(self):
        assert centered_directional_agreement([(60.0, 20.0)]) is None

    def test_all_at_median_none(self):
        assert centered_directional_agreement([(50.0, 50.0), (50.0, 50.0)]) is None


class TestMovementStats:
    def test_perfect_movement_correlation(self):
        # deltas cg [1,2,3,4,5] vs fg [2,4,6,8,10] → Spearman des variations = 1.0
        cg = [60.0, 61.0, 63.0, 66.0, 70.0, 75.0]
        fg = [20.0, 22.0, 26.0, 32.0, 40.0, 50.0]
        pairs = list(zip(cg, fg, strict=True))
        s = movement_stats(pairs)
        assert s["movement_spearman"] == pytest.approx(1.0)
        assert s["movement_agreement_pct"] == pytest.approx(100.0)
        assert s["centered_directional_agreement_pct"] == pytest.approx(100.0)

    def test_too_few_for_movement_spearman(self):
        # < 6 paires → < 5 deltas → Spearman mouvement None, mais accord calculé
        pairs = [(60.0, 20.0), (63.0, 22.0), (65.0, 25.0)]
        s = movement_stats(pairs)
        assert s["movement_spearman"] is None
        assert s["movement_agreement_pct"] is not None


class TestPrimarySpearman:
    def test_prefers_movement(self):
        value, basis = primary_spearman(0.2, 0.9)
        assert value == pytest.approx(0.9)
        assert "mouvement" in basis

    def test_falls_back_to_level(self):
        value, basis = primary_spearman(0.5, None)
        assert value == pytest.approx(0.5)
        assert "niveau" in basis

    def test_none_when_both_none(self):
        value, basis = primary_spearman(None, None)
        assert value is None
        assert basis == "aucune"
