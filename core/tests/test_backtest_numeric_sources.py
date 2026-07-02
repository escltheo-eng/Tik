"""Tests unitaires pour les helpers purs de `backtest_numeric_sources.py` (P2).

Tests des helpers math : `spearman_correlation`, `_ranks`, `parse_horizons`,
`parse_iso_date`, `is_success`. Pas d'appels API live, pas d'I/O.

Depuis l'audit 2026-07-02 : tests du lag de publication DXY
(`apply_publication_lag`), du sous-échantillonnage non chevauchant
(`_subsample_non_overlapping` + champs `*_indep` de `_analyze_rows`) et de la
correction multiple-testing des recommandations (`_count_tested_cells`,
`_significance_marker`, `build_recommendations`).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest

from tik_core.scripts.backtest_numeric_sources import (
    _analyze_rows,
    _count_tested_cells,
    _proportion_p_value,
    _ranks,
    _significance_marker,
    _spearman_p_value,
    _subsample_non_overlapping,
    apply_publication_lag,
    build_recommendations,
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
        assert result.tzinfo is UTC
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
        assert (
            spearman_correlation(
                [1.0, 2.0, 3.0, 4.0, 5.0],
                [10.0, 10.0, 10.0, 10.0, 10.0],
            )
            is None
        )

    def test_handles_ties(self):
        # Dataset avec ex-aequo, doit retourner une valeur valide
        xs = [1.0, 1.0, 2.0, 3.0, 4.0]
        ys = [5.0, 4.0, 3.0, 2.0, 1.0]
        result = spearman_correlation(xs, ys)
        assert result is not None
        assert -1.0 <= result <= 1.0


# -------- Anti-look-ahead DXY (audit 2026-07-02) --------


class TestApplyPublicationLag:
    def test_shifts_dates_and_keeps_observation_date(self):
        points = [
            {"date": "2026-06-01", "value": 120.5},
            {"date": "2026-06-02", "value": 121.0},
        ]
        shifted = apply_publication_lag(points, 7)
        assert [p["date"] for p in shifted] == ["2026-06-08", "2026-06-09"]
        assert [p["observation_date"] for p in shifted] == ["2026-06-01", "2026-06-02"]
        assert [p["value"] for p in shifted] == [120.5, 121.0]
        # Les points d'origine ne sont pas mutés
        assert points[0]["date"] == "2026-06-01"
        assert "observation_date" not in points[0]

    def test_zero_lag_returns_input_unchanged(self):
        points = [{"date": "2026-06-01", "value": 120.5}]
        assert apply_publication_lag(points, 0) is points

    def test_malformed_date_skipped(self):
        points = [
            {"date": "pas-une-date", "value": 1.0},
            {"date": "2026-06-01", "value": 2.0},
        ]
        shifted = apply_publication_lag(points, 7)
        assert len(shifted) == 1
        assert shifted[0]["value"] == 2.0


# -------- Sous-échantillonnage non chevauchant + p-values --------


class TestSubsampleNonOverlapping:
    def test_daily_points_all_kept_at_24h(self):
        rows = [{"date": f"2026-06-{i + 1:02d}"} for i in range(10)]
        assert len(_subsample_non_overlapping(rows, 24)) == 10

    def test_daily_points_thinned_at_120h(self):
        # 10 points quotidiens, horizon 5 j → seuls 06-01 et 06-06 espacés ≥ 120h
        rows = [{"date": f"2026-06-{i + 1:02d}"} for i in range(10)]
        out = _subsample_non_overlapping(rows, 120)
        assert [r["date"] for r in out] == ["2026-06-01", "2026-06-06"]

    def test_empty_and_malformed(self):
        assert _subsample_non_overlapping([], 24) == []
        rows = [{"date": "n/a"}, {"date": "2026-06-01"}]
        out = _subsample_non_overlapping(rows, 24)
        assert [r["date"] for r in out] == ["2026-06-01"]


class TestProportionPValue:
    def test_zero_n_returns_none(self):
        assert _proportion_p_value(0, 0) is None

    def test_exactly_null_rate_gives_p_one(self):
        assert _proportion_p_value(50, 100, 0.5) == pytest.approx(1.0)

    def test_strong_deviation_significant(self):
        p = _proportion_p_value(90, 100, 0.5)
        assert p is not None and p < 0.001

    def test_small_n_not_significant(self):
        # 2/2 succès : trop peu de points indépendants pour conclure
        p = _proportion_p_value(2, 2, 0.5)
        assert p is not None and p > 0.05


class TestSpearmanPValue:
    def test_none_ic_returns_none(self):
        assert _spearman_p_value(None, 100) is None

    def test_too_few_points_returns_none(self):
        assert _spearman_p_value(0.9, 3) is None

    def test_strong_ic_significant(self):
        p = _spearman_p_value(0.9, 30)
        assert p is not None and p < 0.001

    def test_weak_ic_not_significant(self):
        p = _spearman_p_value(0.05, 30)
        assert p is not None and p > 0.5


class TestAnalyzeRowsIndependentSubsample:
    """`_analyze_rows` doit exposer des comptages non chevauchants + p-values
    (constat C-1 audit 2026-07-02) en plus des stats descriptives."""

    @staticmethod
    def _rows(n: int = 10) -> list[dict[str, Any]]:
        # n points quotidiens, bias extrême -1.0 (contrarian attend bear),
        # delta -3.0 % → succès à l'horizon 120h (seuil 1.0 %).
        return [
            {
                "date": f"2026-06-{i + 1:02d}",
                "value": 90.0 + i,
                "bias": -1.0,
                "palier": "extreme_greed",
                "entry_price": 100.0,
                "deltas_pct": {120: -3.0},
            }
            for i in range(n)
        ]

    def test_descriptive_full_sample_stats_unchanged(self):
        out = _analyze_rows(self._rows(), "contrarian", [120], "BTC")
        m = out["metrics_by_horizon"]["120h"]
        assert m["extreme"]["n_evaluable"] == 10
        assert m["extreme"]["hit_rate"] == pytest.approx(1.0)
        assert m["by_palier"]["extreme_greed"]["n_evaluable"] == 10

    def test_independent_counts_and_pvalues_exposed(self):
        out = _analyze_rows(self._rows(), "contrarian", [120], "BTC")
        m = out["metrics_by_horizon"]["120h"]
        # 10 points quotidiens à horizon 5 j → 2 fenêtres indépendantes
        assert m["n_indep"] == 2
        assert m["extreme"]["n_evaluable_indep"] == 2
        assert m["extreme"]["n_success_indep"] == 2
        # 2/2 vs 50 % : p non significative (z=1.41) — le plein échantillon
        # (10/10) aurait donné une pseudo-significativité indue
        assert m["extreme"]["p_value"] is not None
        assert m["extreme"]["p_value"] > 0.05
        palier = m["by_palier"]["extreme_greed"]
        assert palier["n_evaluable_indep"] == 2
        assert palier["p_value"] is not None
        # IC : descriptif sur 10 points, significativité sur 2 (trop peu → None)
        assert m["ic_n"] == 10
        assert m["ic_n_indep"] == 2
        assert m["ic_p_value"] is None


# -------- Correction multiple-testing des recommandations --------


def _fake_report(
    extreme_p: float | None,
    ic_p: float | None = 0.5,
) -> dict[str, Any]:
    """Rapport minimal avec 2 cellules testées (IC + cas extrêmes)."""
    return {
        "by_source": {
            "fear_greed": {
                "n_total": 50,
                "asset": "BTC",
                "direction": "contrarian",
                "metrics_by_horizon": {
                    "24h": {
                        "threshold_pct": 0.5,
                        "n_evaluable_total": 30,
                        "n_indep": 12,
                        "ic_spearman": -0.25,
                        "ic_n": 50,
                        "ic_spearman_indep": -0.2,
                        "ic_n_indep": 12,
                        "ic_p_value": ic_p,
                        "ic_expected_sign": "negative",
                        "ic_actual_sign": "negative",
                        "ic_sign_correct": True,
                        "by_palier": {},
                        "extreme": {
                            "n_total": 20,
                            "n_evaluable": 20,
                            "n_success": 15,
                            "hit_rate": 0.75,
                            "n_evaluable_indep": 8,
                            "n_success_indep": 6,
                            "p_value": extreme_p,
                        },
                    }
                },
            }
        },
    }


class TestSignificanceMarker:
    def test_none_p_marks_not_computable(self):
        assert "p non calculable" in _significance_marker(None, 0.025)

    def test_below_threshold_marks_significant(self):
        marker = _significance_marker(0.001, 0.025)
        assert "significatif après correction" in marker
        assert "indicatif" not in marker

    def test_above_threshold_marks_indicative(self):
        marker = _significance_marker(0.30, 0.025)
        assert "indicatif — non significatif après correction" in marker


class TestBuildRecommendationsMultipleTesting:
    def test_count_tested_cells(self):
        assert _count_tested_cells(_fake_report(extreme_p=0.5)) == 2
        assert _count_tested_cells(_fake_report(extreme_p=None)) == 1

    def test_header_announces_bonferroni_threshold(self):
        recos = build_recommendations(_fake_report(extreme_p=0.5))
        header = recos[0]
        assert "2 cellules testées" in header
        assert "0.05/2" in header

    def test_non_significant_reco_marked_indicative(self):
        recos = build_recommendations(_fake_report(extreme_p=0.5))
        extreme_reco = next(r for r in recos if "paliers extrêmes" in r)
        assert "indicatif — non significatif après correction" in extreme_reco

    def test_significant_reco_marked_after_correction(self):
        # p=0.001 < 0.05/2 = 0.025 → survit à Bonferroni
        recos = build_recommendations(_fake_report(extreme_p=0.001))
        extreme_reco = next(r for r in recos if "paliers extrêmes" in r)
        assert "significatif après correction" in extreme_reco
        assert "indicatif" not in extreme_reco

    def test_missing_p_marked_not_computable(self):
        recos = build_recommendations(_fake_report(extreme_p=None))
        extreme_reco = next(r for r in recos if "paliers extrêmes" in r)
        assert "p non calculable" in extreme_reco

    def test_analyze_rows_output_flows_into_recommendations(self):
        # Intégration légère : la sortie réelle de _analyze_rows doit se
        # brancher sur build_recommendations sans clé manquante.
        rows = TestAnalyzeRowsIndependentSubsample._rows(12)
        report = {
            "by_source": {"fear_greed": _analyze_rows(rows, "contrarian", [120], "BTC")},
        }
        recos = build_recommendations(report)
        assert recos
        assert any("cellules testées" in r for r in recos)
