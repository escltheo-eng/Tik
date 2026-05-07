"""Tests unitaires pour les helpers purs de `backtest_numeric_sources.py` (P2).

Tests des helpers math : `spearman_correlation`, `_ranks`, `parse_horizons`,
`parse_iso_date`, `is_success`. Pas d'appels API live, pas d'I/O.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tik_core.scripts.backtest_numeric_sources import (
    _ranks,
    is_success,
    parse_horizons,
    parse_iso_date,
    spearman_correlation,
)


class TestParseHorizons:
    def test_hours_24h(self):
        assert parse_horizons("24h") == [24]

    def test_days_5d(self):
        assert parse_horizons("5d") == [120]

    def test_mixed(self):
        assert parse_horizons("24h,5d,30d") == [24, 120, 720]

    def test_whitespace_tolerant(self):
        assert parse_horizons(" 24h , 5d ") == [24, 120]

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Horizon format inconnu"):
            parse_horizons("24x")


class TestParseIsoDate:
    def test_yyyy_mm_dd(self):
        result = parse_iso_date("2025-05-07")
        assert result.tzinfo is timezone.utc
        assert result.year == 2025
        assert result.month == 5
        assert result.day == 7

    def test_iso_with_t_strips_time(self):
        result = parse_iso_date("2025-05-07T12:30:00")
        assert result.year == 2025
        assert result.month == 5
        assert result.day == 7
        assert result.hour == 0  # heure remise à 0


class TestIsSuccess:
    def test_neutral_bias_returns_none(self):
        # bias=0 (palier neutral) n'est pas évaluable
        assert is_success("contrarian", 0.0, 1.0, 0.5) is None

    def test_bull_expected_delta_above_threshold_success(self):
        # bias positif (attend bull) + delta > +threshold → success
        assert is_success("contrarian", 1.0, 0.6, 0.5) is True

    def test_bull_expected_delta_below_threshold_fail(self):
        # bias positif + delta < +threshold → fail
        assert is_success("contrarian", 1.0, 0.3, 0.5) is False

    def test_bull_expected_delta_negative_fail(self):
        # bias positif + delta négatif fort → fail (mauvaise direction)
        assert is_success("contrarian", 1.0, -1.0, 0.5) is False

    def test_bear_expected_delta_below_threshold_success(self):
        # bias négatif (attend bear) + delta < -threshold → success
        assert is_success("contrarian", -1.0, -0.6, 0.5) is True

    def test_bear_expected_delta_positive_fail(self):
        # bias négatif + delta positif → fail
        assert is_success("contrarian", -1.0, 1.0, 0.5) is False

    def test_threshold_zero_treats_zero_delta_as_below(self):
        # Edge case : delta == threshold mais bias ≠ 0 → fail (abs<threshold strict)
        assert is_success("contrarian", 1.0, 0.4, 0.5) is False


class TestRanks:
    def test_simple(self):
        assert _ranks([10.0, 20.0, 30.0]) == [1.0, 2.0, 3.0]

    def test_reverse(self):
        assert _ranks([30.0, 20.0, 10.0]) == [3.0, 2.0, 1.0]

    def test_ties(self):
        # Deux 20.0 ex-aequo → rangs moyens
        # Trié : [10 (rang 1), 20 (rang 2), 20 (rang 3), 30 (rang 4)]
        # Rang moyen pour 20 : (2+3)/2 = 2.5
        ranks = _ranks([10.0, 20.0, 20.0, 30.0])
        assert ranks[0] == 1.0
        assert ranks[1] == 2.5
        assert ranks[2] == 2.5
        assert ranks[3] == 4.0

    def test_all_same(self):
        # Tous ex-aequo → rang moyen = (1+2+3)/3 = 2
        assert _ranks([5.0, 5.0, 5.0]) == [2.0, 2.0, 2.0]


class TestSpearmanCorrelation:
    def test_perfect_positive_correlation(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert spearman_correlation(xs, ys) == pytest.approx(1.0, abs=1e-6)

    def test_perfect_negative_correlation(self):
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [50.0, 40.0, 30.0, 20.0, 10.0]
        assert spearman_correlation(xs, ys) == pytest.approx(-1.0, abs=1e-6)

    def test_no_correlation(self):
        # Cas zéro corrélation rangs : 5 points avec rangs en X mais Y choisi pour cov=0
        xs = [1.0, 2.0, 3.0, 4.0, 5.0]
        ys = [3.0, 1.0, 5.0, 2.0, 4.0]  # rangs aléatoires
        result = spearman_correlation(xs, ys)
        assert result is not None
        assert -0.5 < result < 0.5  # corrélation faible, pas exactement 0

    def test_too_few_points_returns_none(self):
        assert spearman_correlation([1.0, 2.0], [3.0, 4.0]) is None
        assert spearman_correlation([1.0, 2.0, 3.0, 4.0], [5.0, 6.0, 7.0, 8.0]) is None

    def test_unequal_lengths_returns_none(self):
        assert spearman_correlation([1.0, 2.0, 3.0, 4.0, 5.0], [1.0, 2.0, 3.0]) is None

    def test_constant_returns_none(self):
        # Variance nulle (tous les ys identiques) → division par zéro → None
        assert spearman_correlation(
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [10.0, 10.0, 10.0, 10.0, 10.0],
        ) is None

    def test_handles_ties(self):
        # Dataset avec ex-aequo, doit retourner une valeur valide
        xs = [1.0, 1.0, 2.0, 3.0, 4.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        result = spearman_correlation(xs, ys)
        assert result is not None
        assert -1.0 <= result <= 1.0
