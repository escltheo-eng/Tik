"""Tests du chemin de significativité de `measure_post_fix_hit_rates.py`.

Constat C-1 CRITIQUE (audit 2026-07-02) : le test apparié « Tik vs Always X »
était calculé sur des signaux émis toutes les 15-30 min avec un horizon 5 j →
fenêtres forward chevauchantes à ~99 %, p-value invalide. Ces tests vérifient
que les verdicts « sig. » viennent désormais UNIQUEMENT du sous-échantillon
non chevauchant, avec affichage de N_total ET N_indépendant.

Sans le fix, le cas « dense » ci-dessous imprimait « Tik GAGNE (sig.) » sur
une pseudo-significativité fabriquée par la densité d'émission.
"""

import math
from datetime import UTC, datetime, timedelta

from tik_core.scripts.measure_post_fix_hit_rates import _print_trend_baseline_comparison

_BASE = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def _row(direction: str, delta_pct: float, ts: datetime) -> dict:
    """Résultat minimal au format produit par `_evaluate_signal_td`."""
    return {
        "direction": direction,
        "delta_pct": delta_pct,
        "ts": ts.isoformat(),
        "veracity": 0.9,
        "entity": "BTC",
        "success": True,
    }


def _dense_results() -> list[dict]:
    """300 signaux long espacés de 1 min (5 h) : une seule fenêtre 24h
    indépendante, mais des deltas à moyenne positive qui donneraient une
    pseudo-significativité éclatante en plein échantillon."""
    return [_row("long", 0.2 + math.sin(i), _BASE + timedelta(minutes=i)) for i in range(300)]


class TestTrendBaselineComparisonNonOverlapping:
    def test_dense_sample_cannot_claim_significance(self, capsys):
        _print_trend_baseline_comparison(
            _dense_results(), horizon_td=timedelta(hours=24), min_samples=20
        )
        out = capsys.readouterr().out
        # N_total ET N_indépendant affichés (exigence audit)
        assert "N_total = 300" in out
        assert "N_indépendant = 1" in out
        # Aucun verdict significatif fabriqué par le chevauchement
        assert "GAGNE (sig.)" not in out
        assert "PERD (sig.)" not in out
        assert "n/a (N_indép < 2)" in out

    def test_dense_sample_warns_too_few_independent_windows(self, capsys):
        _print_trend_baseline_comparison(
            _dense_results(), horizon_td=timedelta(hours=24), min_samples=20
        )
        out = capsys.readouterr().out
        assert "trop peu de fenêtres" in out

    def test_spaced_sample_keeps_significance(self, capsys):
        # 30 signaux long espacés de 25 h ≥ horizon 24h → réellement
        # indépendants : la significativité vs Always NEUTRAL reste
        # établissable (deltas positifs variés).
        results = [
            _row("long", 1.0 + 0.1 * (i % 2), _BASE + timedelta(hours=25 * i)) for i in range(30)
        ]
        _print_trend_baseline_comparison(results, horizon_td=timedelta(hours=24), min_samples=20)
        out = capsys.readouterr().out
        assert "N_indépendant = 30" in out
        assert "Tik GAGNE (sig.)" in out

    def test_empty_results_prints_placeholder(self, capsys):
        _print_trend_baseline_comparison([], horizon_td=timedelta(hours=24), min_samples=20)
        out = capsys.readouterr().out
        assert "(aucun signal)" in out
