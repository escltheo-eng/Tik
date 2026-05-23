"""Tests unitaires des helpers de scoring du script de backtest.

Vérifie la logique de classification "succès / échec", le calcul du gain réel,
la recherche de prix par timestamp (avec garde-fou anti-prix-périmé), l'évaluation
bout-en-bout d'un signal, et les baselines (Tik / Random / Always X).

Ces primitives sous-tendent TOUS les chiffres de hit-rate exposés à
l'utilisatrice (cartes dashboard, track record, mesure officielle J+10) — un bug
ici corromprait silencieusement la décision go/no-go. D'où la couverture.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from tik_core.scripts.backtest import (
    _gain_for,
    _success_for,
    evaluate_constant_baseline,
    evaluate_random_baseline,
    evaluate_signal,
    evaluate_tik_baseline,
    find_closest_price,
    normal_cdf,
    paired_gain_significance,
)

# Base temporelle commune (aware UTC) pour construire les historiques de prix.
_BASE = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)


def _ms(dt: datetime) -> int:
    """Timestamp POSIX en millisecondes (format des klines)."""
    return int(dt.timestamp() * 1000)


def _signal(entity_id: str, direction: str, ts: datetime, sig_id: str = "sig-1"):
    """Stub Signal minimal pour evaluate_signal (accès attributs uniquement)."""
    return SimpleNamespace(
        id=sig_id,
        entity_id=entity_id,
        direction=direction,
        timestamp=ts,
        confidence=0.5,
        veracity=0.9,
    )


def _result(direction: str, delta_pct: float, success: bool | None = None) -> dict:
    """Dict 'résultat' minimal consommé par les baselines."""
    d = {"direction": direction, "delta_pct": delta_pct}
    if success is not None:
        d["success"] = success
    return d


# ----- _gain_for -----


@pytest.mark.parametrize(
    "direction, delta_pct, expected_gain",
    [
        # LONG : on profite directement du delta
        ("long", 2.0, 2.0),  # marché monte → gain = delta
        ("long", -1.5, -1.5),  # marché baisse → perte
        ("long", 0.0, 0.0),  # stable → 0
        # SHORT : on profite de l'inverse du delta
        ("short", 2.0, -2.0),  # marché monte → on perd notre short
        ("short", -1.5, 1.5),  # marché baisse → on gagne sur le short
        ("short", 0.0, 0.0),
        # NEUTRAL : "réussi" si stable, donc gain = -|delta|
        ("neutral", 2.0, -2.0),  # gros mouvement → loupé
        ("neutral", -1.5, -1.5),  # ditto en baisse
        ("neutral", 0.0, 0.0),  # marché stable → "réussi"
    ],
)
def test_gain_for(direction, delta_pct, expected_gain):
    assert _gain_for(direction, delta_pct) == expected_gain


# ----- _success_for -----


@pytest.mark.parametrize(
    "direction, delta_pct, threshold, expected_success",
    [
        # LONG : succès si delta > threshold
        ("long", 2.0, 0.5, True),
        ("long", 0.6, 0.5, True),
        ("long", 0.5, 0.5, False),  # strictement supérieur
        ("long", 0.3, 0.5, False),
        ("long", -1.0, 0.5, False),
        # SHORT : succès si delta < -threshold
        ("short", -2.0, 0.5, True),
        ("short", -0.6, 0.5, True),
        ("short", -0.5, 0.5, False),
        ("short", -0.3, 0.5, False),
        ("short", 1.0, 0.5, False),
        # NEUTRAL : succès si |delta| < threshold
        ("neutral", 0.3, 0.5, True),
        ("neutral", -0.3, 0.5, True),
        ("neutral", 0.0, 0.5, True),
        ("neutral", 0.5, 0.5, False),  # |0.5| < 0.5 = False
        ("neutral", 1.0, 0.5, False),
        ("neutral", -1.0, 0.5, False),
        # Threshold custom
        ("long", 0.2, 0.1, True),
        ("long", 0.05, 0.1, False),
    ],
)
def test_success_for(direction, delta_pct, threshold, expected_success):
    assert _success_for(direction, delta_pct, threshold) is expected_success


# ----- find_closest_price -----


class TestFindClosestPrice:
    """Recherche du prix au plus proche d'un timestamp + garde-fou tolérance.

    CRITIQUE : si cette fonction renvoie un prix trop éloigné dans le temps
    (au lieu de None), le delta calculé est faux et le hit rate corrompu.
    """

    def test_empty_history_returns_none(self):
        assert find_closest_price([], _BASE) is None

    def test_exact_match(self):
        assert find_closest_price([(_ms(_BASE), 100.0)], _BASE) == 100.0

    def test_picks_closest_among_candidates(self):
        history = [
            (_ms(_BASE - timedelta(hours=2)), 90.0),
            (_ms(_BASE + timedelta(minutes=10)), 110.0),  # le plus proche
            (_ms(_BASE + timedelta(hours=3)), 130.0),
        ]
        assert find_closest_price(history, _BASE) == 110.0

    def test_beyond_default_tolerance_returns_none(self):
        # kline à 7h, tolérance défaut 6h → None (pas de prix périmé)
        history = [(_ms(_BASE + timedelta(hours=7)), 100.0)]
        assert find_closest_price(history, _BASE) is None

    def test_tolerance_boundary_exactly_at_max_is_accepted(self):
        # le rejet est strict (best_diff > max_diff_ms), donc == est accepté
        history = [(_ms(_BASE) + 6 * 3600 * 1000, 100.0)]
        assert find_closest_price(history, _BASE, max_diff_ms=6 * 3600 * 1000) == 100.0

    def test_tolerance_just_over_max_is_rejected(self):
        history = [(_ms(_BASE) + 6 * 3600 * 1000 + 1, 100.0)]
        assert find_closest_price(history, _BASE, max_diff_ms=6 * 3600 * 1000) is None

    def test_narrow_tolerance_for_fine_klines(self):
        # klines 15m → tolérance 30min ; un kline à 1h est rejeté (cohérent flash)
        history = [(_ms(_BASE + timedelta(hours=1)), 100.0)]
        assert find_closest_price(history, _BASE, max_diff_ms=30 * 60 * 1000) is None

    def test_naive_target_treated_as_utc(self):
        # cohérent Bug 9 : les timestamps DB sont naïfs (UTC sémantique)
        history = [(_ms(_BASE), 100.0)]
        assert find_closest_price(history, _BASE.replace(tzinfo=None)) == 100.0


# ----- evaluate_signal (évaluation bout-en-bout) -----


class TestEvaluateSignal:
    def test_long_success_when_price_rises(self):
        ts0 = _BASE
        history = [(_ms(ts0), 100.0), (_ms(ts0 + timedelta(days=1)), 102.0)]  # +2 %
        res = evaluate_signal(_signal("BTC", "long", ts0), 1, 0.5, history, [])
        assert res is not None
        assert res["success"] is True
        assert res["delta_pct"] == pytest.approx(2.0)

    def test_short_success_when_price_drops(self):
        ts0 = _BASE
        history = [(_ms(ts0), 100.0), (_ms(ts0 + timedelta(days=1)), 98.0)]  # -2 %
        res = evaluate_signal(_signal("BTC", "short", ts0), 1, 0.5, history, [])
        assert res["success"] is True

    def test_neutral_success_when_flat(self):
        ts0 = _BASE
        history = [(_ms(ts0), 100.0), (_ms(ts0 + timedelta(days=1)), 100.2)]  # +0.2 %
        res = evaluate_signal(_signal("BTC", "neutral", ts0), 1, 0.5, history, [])
        assert res["success"] is True

    def test_gold_uses_gold_history(self):
        ts0 = _BASE
        gold = [(_ms(ts0), 2000.0), (_ms(ts0 + timedelta(days=1)), 2040.0)]
        res = evaluate_signal(_signal("GOLD", "long", ts0), 1, 0.5, [], gold)
        assert res is not None
        assert res["entity"] == "GOLD"

    def test_unknown_entity_returns_none(self):
        assert evaluate_signal(_signal("ETH", "long", _BASE), 1, 0.5, [], []) is None

    def test_missing_p1_returns_none(self):
        # seul p0 présent ; p1 (J+1) est à 24h > tolérance 6h → None
        history = [(_ms(_BASE), 100.0)]
        assert evaluate_signal(_signal("BTC", "long", _BASE), 1, 0.5, history, []) is None

    def test_zero_p0_returns_none(self):
        ts0 = _BASE
        history = [(_ms(ts0), 0.0), (_ms(ts0 + timedelta(days=1)), 100.0)]
        assert evaluate_signal(_signal("BTC", "long", ts0), 1, 0.5, history, []) is None


# ----- baselines -----


class TestConstantBaseline:
    def test_empty_returns_zero(self):
        out = evaluate_constant_baseline([], "long", 0.5)
        assert out["n"] == 0
        assert out["hit_rate"] == 0.0

    def test_always_long_counts_only_rises(self):
        results = [_result("x", 2.0), _result("x", -1.0), _result("x", 0.3)]
        out = evaluate_constant_baseline(results, "long", 0.5)
        assert out["n"] == 3
        assert out["n_success"] == 1  # seul +2.0 > 0.5
        assert out["hit_rate"] == pytest.approx(1 / 3)

    def test_always_neutral_counts_only_flat(self):
        results = [_result("x", 0.3), _result("x", -0.2), _result("x", 2.0)]
        out = evaluate_constant_baseline(results, "neutral", 0.5)
        assert out["n_success"] == 2  # |0.3| et |0.2| < 0.5


class TestRandomBaseline:
    def test_empty_returns_zero(self):
        assert evaluate_random_baseline([], 0.5)["n"] == 0

    def test_deterministic_with_seed(self):
        results = [_result("x", 1.0), _result("x", -1.0), _result("x", 0.1), _result("x", 3.0)]
        a = evaluate_random_baseline(results, 0.5, seed=42)
        b = evaluate_random_baseline(results, 0.5, seed=42)
        assert a["hit_rate"] == b["hit_rate"]
        assert 0.0 <= a["hit_rate"] <= 1.0


class TestTikBaseline:
    def test_empty_returns_zero(self):
        assert evaluate_tik_baseline([], 0.5)["n"] == 0

    def test_counts_success_field_and_avg_gain(self):
        results = [
            _result("long", 2.0, success=True),
            _result("short", 1.0, success=False),
        ]
        out = evaluate_tik_baseline(results, 0.5)
        assert out["n"] == 2
        assert out["n_success"] == 1
        # avg_gain = (gain_long(+2.0) + gain_short(1.0)=-1.0) / 2 = 0.5
        assert out["avg_gain"] == pytest.approx(0.5)


# ----- normal_cdf -----


class TestNormalCdf:
    def test_zero_is_half(self):
        assert normal_cdf(0.0) == pytest.approx(0.5)

    def test_large_positive_approaches_one(self):
        assert normal_cdf(8.0) == pytest.approx(1.0, abs=1e-6)

    def test_large_negative_approaches_zero(self):
        assert normal_cdf(-8.0) == pytest.approx(0.0, abs=1e-6)

    @pytest.mark.parametrize("x", [0.3, 1.0, 1.96, 3.5])
    def test_symmetry(self, x):
        # Phi(x) + Phi(-x) == 1
        assert normal_cdf(x) + normal_cdf(-x) == pytest.approx(1.0)


# ----- paired_gain_significance -----


class TestPairedGainSignificance:
    def test_empty_returns_none(self):
        assert paired_gain_significance([], "short") is None

    def test_gains_computed_correctly(self):
        # Tik = long sur ces signaux ; deltas +2 et -1
        results = [_result("long", 2.0), _result("long", -1.0)]
        out = paired_gain_significance(results, "short")
        # tik_gain = mean(long: +2, -1) = +0.5
        assert out["tik_gain"] == pytest.approx(0.5)
        # baseline short gain = mean(-(+2), -(-1)) = mean(-2, +1) = -0.5
        assert out["baseline_gain"] == pytest.approx(-0.5)
        # mean_diff = tik - base = +1.0
        assert out["mean_diff"] == pytest.approx(1.0)
        assert out["n"] == 2

    def test_identical_direction_has_no_variance(self):
        # Tik == baseline (tous short) → diffs tous nuls → z/p indéfinis
        results = [_result("short", 2.0), _result("short", -1.0), _result("short", 0.5)]
        out = paired_gain_significance(results, "short")
        assert out["mean_diff"] == pytest.approx(0.0)
        assert out["z"] is None
        assert out["p"] is None

    def test_single_signal_no_pvalue(self):
        out = paired_gain_significance([_result("long", 1.0)], "short")
        assert out["n"] == 1
        assert out["z"] is None
        assert out["p"] is None

    def test_tik_loses_to_short_in_downtrend(self):
        # Marché baisse, Tik reste neutral → perd vs Always SHORT
        results = [_result("neutral", d) for d in (-2.0, -3.0, -1.0, -2.5, -1.8, -2.2)]
        out = paired_gain_significance(results, "short")
        assert out["mean_diff"] < 0  # Tik fait moins bien que short
        assert out["z"] is not None and out["z"] < 0
        assert out["p"] is not None and 0.0 <= out["p"] <= 1.0

    def test_tik_beats_neutral_baseline_directionally(self):
        # Marché baisse, Tik est short (correct) → bat Always NEUTRAL
        results = [_result("short", d) for d in (-2.0, -3.0, -1.0, -2.5, -1.8, -2.2)]
        out = paired_gain_significance(results, "neutral")
        assert out["mean_diff"] > 0
        assert out["z"] is not None and out["z"] > 0
        assert out["p"] is not None and out["p"] < 0.05
