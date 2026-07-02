"""Tests du chemin de significativité de `backtest_dual_lens.py`.

Constat C-1 CRITIQUE (audit 2026-07-02) : la p-value « vs random » de chaque
groupe était calculée sur le plein échantillon alors que les fenêtres forward
de signaux émis toutes les 15-30 min se chevauchent massivement. Ces tests
vérifient que la p-value (donc sig0.05 / Bonferroni) vient UNIQUEMENT du
sous-échantillon non chevauchant (`n_indep`).

Sans le fix, le cas « dense » ci-dessous affichait p ≈ 0 (sig0.05 ✓Bonf) sur
une seule fenêtre de marché réellement indépendante.
"""

from datetime import UTC, datetime, timedelta

from tik_core.scripts.backtest_dual_lens import _build_groups, _group_stats, _verdicts

_BASE = datetime(2026, 6, 1, 0, 0, 0, tzinfo=UTC)


def _row(
    direction: str,
    delta_pct: float,
    ts: datetime,
    *,
    success: bool = True,
    veracity: float = 0.9,
    cb_status: str = "ok",
) -> dict:
    """Résultat minimal au format produit par le main() de dual-lens."""
    return {
        "direction": direction,
        "delta_pct": delta_pct,
        "ts": ts.isoformat(),
        "success": success,
        "veracity": veracity,
        "cb_status": cb_status,
        "entity": "BTC",
    }


class TestGroupStatsNonOverlapping:
    def test_dense_group_pvalue_not_inflated(self):
        # 100 signaux long gagnants espacés de 1 min : une seule fenêtre 24h
        # indépendante. Le plein échantillon donnerait p ≈ 0 (hit 100 % vs
        # random ~33 % sur n=100) — pseudo-significativité pure densité.
        rows = [_row("long", 1.0, _BASE + timedelta(minutes=i)) for i in range(100)]
        s = _group_stats(rows, 0.30, timedelta(hours=24))
        assert s is not None
        # Stats descriptives plein échantillon inchangées
        assert s["n"] == 100
        assert s["hit"] == 1.0
        assert s["gain"] == 1.0
        # Significativité honnête : 1 seule fenêtre indépendante → pas de
        # p < 0.05 revendicable
        assert s["n_indep"] == 1
        assert s["p"] is None or s["p"] > 0.05

    def test_independent_group_keeps_significance(self):
        # 60 signaux gagnants espacés de 25 h ≥ horizon 24h : la
        # significativité vs random reste établissable.
        rows = [_row("long", 1.0, _BASE + timedelta(hours=25 * i)) for i in range(60)]
        s = _group_stats(rows, 0.30, timedelta(hours=24))
        assert s is not None
        assert s["n_indep"] == 60
        assert s["p"] is not None and s["p"] < 0.05

    def test_empty_group_returns_none(self):
        assert _group_stats([], 0.30, timedelta(hours=24)) is None


class TestVerdictsFlags:
    def test_small_independent_sample_flagged(self):
        s = {
            "n": 100,
            "hits": 100,
            "hit": 1.0,
            "gain": 1.0,
            "rnd": 0.33,
            "n_indep": 1,
            "p": None,
        }
        _opt, par = _verdicts(s, bonferroni_threshold=0.005, min_samples=20)
        assert "nInd<20" in par
        assert "non-sig" in par

    def test_large_independent_sample_not_flagged(self):
        s = {
            "n": 100,
            "hits": 90,
            "hit": 0.9,
            "gain": 1.0,
            "rnd": 0.33,
            "n_indep": 60,
            "p": 0.001,
        }
        _opt, par = _verdicts(s, bonferroni_threshold=0.005, min_samples=20)
        assert "nInd<20" not in par
        assert "sig0.05" in par
        assert "✓Bonf" in par


class TestBuildGroups:
    def test_groups_include_overall_and_dimensions(self):
        rows = [
            _row("long", 1.0, _BASE, veracity=0.9, cb_status="ok"),
            _row("short", -1.0, _BASE + timedelta(hours=1), veracity=0.7, cb_status="degraded"),
        ]
        labels = [label for label, _ in _build_groups(rows)]
        assert "overall" in labels
        assert "direction=long" in labels
        assert "veracity>=0.85" in labels
        assert "cb_status=degraded" in labels
