"""Tests unitaires des helpers de scoring du script de backtest.

Vérifie la logique de classification "succès / échec", le calcul du gain réel,
la recherche de prix par timestamp (avec garde-fou anti-prix-périmé), l'évaluation
bout-en-bout d'un signal, et les baselines (Tik / Random / Always X).

Ces primitives sous-tendent TOUS les chiffres de hit-rate exposés à
l'utilisatrice (cartes dashboard, track record, mesure officielle J+10) — un bug
ici corromprait silencieusement la décision go/no-go. D'où la couverture.
"""

import math
from datetime import UTC, datetime, timedelta
from statistics import mean
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
    format_coverage_warning,
    klines_coverage_start,
    non_overlapping_subsample,
    normal_cdf,
    paired_gain_significance,
    split_out_of_coverage,
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
        # NEUTRAL : pas de position → gain 0 quel que soit le mouvement.
        # Convention unifiée 2026-07-02 (audit) : l'ancienne convention
        # -|delta| pénalisait Tik dans les tests appariés alors
        # qu'analyze_colinearity modélisait déjà neutral = 0.
        ("neutral", 2.0, 0.0),
        ("neutral", -1.5, 0.0),
        ("neutral", 0.0, 0.0),
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

    def test_neutral_convention_is_zero_in_paired_gains(self):
        # Convention 2026-07-02 : neutral = pas de position → gain Tik = 0,
        # alignée sur analyze_colinearity (avant : -|delta|, biais vers le bas).
        results = [_result("neutral", d) for d in (-2.0, 3.0, -1.0)]
        out = paired_gain_significance(results, "short")
        assert out["tik_gain"] == pytest.approx(0.0)
        # baseline short : mean(-(-2), -(3), -(-1)) = mean(2, -3, 1) = 0
        assert out["baseline_gain"] == pytest.approx(0.0)


# ----- non_overlapping_subsample -----


def _ts_row(direction: str, delta_pct: float, ts) -> dict:
    """Résultat minimal avec timestamp (clé 'ts', datetime ou ISO str)."""
    return {"direction": direction, "delta_pct": delta_pct, "ts": ts}


class TestNonOverlappingSubsample:
    """Constat C-1 audit 2026-07-02 : le sous-échantillonnage non chevauchant
    est le prérequis de toute p-value honnête sur des signaux denses."""

    def test_dense_rows_collapse_to_one_window(self):
        # 300 signaux espacés de 1 min sur un horizon 24h → 1 seule fenêtre
        rows = [_ts_row("long", 1.0, _BASE + timedelta(minutes=i)) for i in range(300)]
        out = non_overlapping_subsample(rows, timedelta(hours=24))
        assert len(out) == 1
        assert out[0]["ts"] == _BASE  # le premier chronologiquement

    def test_exact_spacing_keeps_all_rows(self):
        rows = [_ts_row("long", 1.0, _BASE + timedelta(hours=24 * i)) for i in range(10)]
        out = non_overlapping_subsample(rows, timedelta(hours=24))
        assert len(out) == 10

    def test_accepts_iso_strings_with_and_without_z(self):
        rows = [
            _ts_row("long", 1.0, _BASE.isoformat()),
            _ts_row("long", 1.0, (_BASE + timedelta(hours=25)).replace(tzinfo=None).isoformat()),
            _ts_row("long", 1.0, (_BASE + timedelta(hours=50)).isoformat() + "Z"),
        ]
        # Hétérogène aware/naïf/Z-suffixé : tous normalisés en naïf UTC
        rows[0]["ts"] = _BASE.replace(tzinfo=None).isoformat()
        out = non_overlapping_subsample(rows, timedelta(hours=24))
        assert len(out) == 3

    def test_unsorted_input_is_sorted_first(self):
        rows = [
            _ts_row("long", 1.0, _BASE + timedelta(hours=48)),
            _ts_row("long", 1.0, _BASE),
            _ts_row("long", 1.0, _BASE + timedelta(minutes=30)),  # chevauche le 1er
        ]
        out = non_overlapping_subsample(rows, timedelta(hours=24))
        assert [r["ts"] for r in out] == [_BASE, _BASE + timedelta(hours=48)]

    def test_empty_returns_empty(self):
        assert non_overlapping_subsample([], timedelta(hours=24)) == []


class TestPairedGainSignificanceNonOverlapping:
    """La significativité doit venir du sous-échantillon non chevauchant
    (constat C-1 CRITIQUE audit 2026-07-02) : un z-test plein échantillon sur
    des fenêtres partagées à ~99 % affiche des p minuscules sans fondement."""

    @staticmethod
    def _dense_results() -> list[dict]:
        # 300 signaux long espacés de 1 min (5 h au total) : avec un horizon
        # 24h ils partagent quasiment toute leur fenêtre forward. Deltas
        # variés (sin) à moyenne positive ~0.2 pour créer une pseudo-signif.
        return [
            _ts_row("long", 0.2 + math.sin(i), _BASE + timedelta(minutes=i)) for i in range(300)
        ]

    def test_full_sample_p_is_inflated_without_horizon(self):
        # Rétrocompat sans horizon_td : z/p plein échantillon → illusion de
        # significativité (c'est exactement le piège que corrige horizon_td).
        out = paired_gain_significance(self._dense_results(), "neutral")
        assert out["p"] is not None and out["p"] < 0.05
        assert out["n_indep"] is None

    def test_dense_sample_yields_no_claimable_significance(self):
        out = paired_gain_significance(
            self._dense_results(), "neutral", horizon_td=timedelta(hours=24)
        )
        # 300 signaux en 5 h = UNE seule fenêtre 24h indépendante → pas de p
        assert out["n"] == 300
        assert out["n_indep"] == 1
        assert out["z"] is None
        assert out["p"] is None
        # Les stats descriptives restent plein échantillon
        assert out["tik_gain"] == pytest.approx(mean(0.2 + math.sin(i) for i in range(300)))

    def test_spaced_results_keep_significance(self):
        # Signaux espacés de 25h ≥ horizon 24h → réellement indépendants,
        # la significativité reste établissable.
        results = [
            _ts_row("long", 1.0 + 0.1 * (i % 2), _BASE + timedelta(hours=25 * i)) for i in range(30)
        ]
        out = paired_gain_significance(results, "neutral", horizon_td=timedelta(hours=24))
        assert out["n_indep"] == 30
        assert out["p"] is not None and out["p"] < 0.05
        assert out["mean_diff_indep"] == pytest.approx(out["mean_diff"])


# ----- Couverture klines (anti-troncature silencieuse) -----


class TestKlinesCoverage:
    """Binance plafonne à 1000 bougies (~41,6 j en 1h) : la troncature de la
    fenêtre demandée doit être explicite (WARNING + compteur dédié)."""

    def test_coverage_start_empty_history(self):
        assert klines_coverage_start([]) is None

    def test_coverage_start_is_first_candle_naive_utc(self):
        history = [(_ms(_BASE), 100.0), (_ms(_BASE + timedelta(hours=1)), 101.0)]
        start = klines_coverage_start(history)
        assert start == _BASE.replace(tzinfo=None)
        assert start.tzinfo is None  # cohérent timestamps DB naïfs (Bug 9)

    def test_split_out_of_coverage_dedicated_counter(self):
        cov = {"BTC": _BASE.replace(tzinfo=None), "GOLD": None}
        signals = [
            SimpleNamespace(
                entity_id="BTC", timestamp=_BASE.replace(tzinfo=None) - timedelta(days=2)
            ),
            SimpleNamespace(
                entity_id="BTC", timestamp=_BASE.replace(tzinfo=None) + timedelta(days=1)
            ),
            # GOLD sans couverture connue → conservé
            SimpleNamespace(
                entity_id="GOLD", timestamp=_BASE.replace(tzinfo=None) - timedelta(days=9)
            ),
        ]
        kept, excluded_by_entity = split_out_of_coverage(signals, cov)
        assert len(kept) == 2
        assert excluded_by_entity == {"BTC": 1}

    def test_format_coverage_warning_none_when_covered(self):
        cov = _BASE.replace(tzinfo=None)
        assert format_coverage_warning("BTC", cov, cov + timedelta(days=1), 0) is None
        assert format_coverage_warning("BTC", None, cov, 0) is None

    def test_format_coverage_warning_explicit_when_truncated(self):
        cov = _BASE.replace(tzinfo=None)
        requested = cov - timedelta(days=10)
        msg = format_coverage_warning("BTC", cov, requested, 42)
        assert msg is not None
        assert "WARNING" in msg
        assert "TRONQUÉE" in msg
        assert "42 signaux exclus" in msg
        assert cov.isoformat() in msg
        assert requested.isoformat() in msg
