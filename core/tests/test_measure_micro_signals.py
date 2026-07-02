"""Tests unitaires du script measure_micro_signals (ADR-030 Étape 4).

Pure logique — pas de DB, HTTP ni Redis. Les Signal sont mockés (MagicMock),
les histoires de prix sont des listes [(ts_ms, price)].

Couvre les 3 briques que le rapport agrège :
- select_non_overlapping : anti pseudo-réplication (rendements chevauchants)
- evaluate_micro_signal : delta prix à t0+2h, succès, prix indisponible
- correlate_micro_vs_swing : appariement temporel + Spearman des directions
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from tik_core.scripts.measure_micro_signals import (
    correlate_micro_vs_swing,
    evaluate_micro_signal,
    select_non_overlapping,
)

T0 = datetime(2026, 7, 1, 12, 0, 0)


def _sig(ts: datetime, direction: str = "long", horizon: str = "micro"):
    s = MagicMock()
    s.id = f"TIK-MICRO-BTC-{ts:%Y%m%d%H%M%S}"
    s.entity_id = "BTC"
    s.horizon = horizon
    s.direction = direction
    s.timestamp = ts
    s.confidence = 0.6
    s.veracity = 0.70
    s.circuit_breaker_status = "degraded"
    return s


def _history(start: datetime, n: int, base: float, step_pct: float):
    out, price = [], base
    ts_ms = int(start.timestamp() * 1000)
    for _ in range(n):
        out.append((ts_ms, price))
        price *= 1 + step_pct / 100
        ts_ms += 15 * 60 * 1000  # klines 15m
    return out


# ----- select_non_overlapping -----


def test_non_overlapping_keeps_first_of_each_window():
    signals = [
        _sig(T0),
        _sig(T0 + timedelta(minutes=30)),  # chevauche la fenêtre 2h → drop
        _sig(T0 + timedelta(hours=1)),  # idem
        _sig(T0 + timedelta(hours=2)),  # nouvelle fenêtre → gardé
        _sig(T0 + timedelta(hours=5)),  # gardé
    ]
    kept = select_non_overlapping(signals, timedelta(hours=2))
    assert [s.timestamp for s in kept] == [
        T0,
        T0 + timedelta(hours=2),
        T0 + timedelta(hours=5),
    ]


def test_non_overlapping_sorts_before_selecting():
    signals = [_sig(T0 + timedelta(hours=2)), _sig(T0)]
    kept = select_non_overlapping(signals, timedelta(hours=2))
    assert len(kept) == 2
    assert kept[0].timestamp == T0


def test_non_overlapping_empty():
    assert select_non_overlapping([], timedelta(hours=2)) == []


# ----- evaluate_micro_signal -----


def test_evaluate_long_success_on_uptrend():
    # +0.3 %/15 min → +2.4 % à 2h : long réussit au seuil 0.3 %.
    history = _history(T0 - timedelta(hours=1), 40, 50000.0, 0.3)
    r = evaluate_micro_signal(_sig(T0, "long"), timedelta(hours=2), 0.3, history)
    assert r is not None
    assert r["success"] is True
    assert r["delta_pct"] > 0.3


def test_evaluate_short_fails_on_uptrend():
    history = _history(T0 - timedelta(hours=1), 40, 50000.0, 0.3)
    r = evaluate_micro_signal(_sig(T0, "short"), timedelta(hours=2), 0.3, history)
    assert r is not None
    assert r["success"] is False


def test_evaluate_returns_none_when_price_missing():
    # Historique terminé bien avant t0+2h (> tolérance 30 min) → None.
    history = _history(T0 - timedelta(days=2), 10, 50000.0, 0.1)
    r = evaluate_micro_signal(_sig(T0, "long"), timedelta(hours=2), 0.3, history)
    assert r is None


# ----- correlate_micro_vs_swing -----


def test_correlation_perfectly_aligned_directions():
    micro, swing = [], []
    directions = ["long", "short", "long", "neutral", "short", "long"]
    for i, d in enumerate(directions):
        ts = T0 + timedelta(hours=3 * i)
        micro.append(_sig(ts, d))
        swing.append(_sig(ts - timedelta(minutes=10), d, horizon="swing"))
    rho, n = correlate_micro_vs_swing(micro, swing, timedelta(hours=1))
    assert n == len(directions)
    assert rho is not None and rho > 0.9  # redondance quasi parfaite


def test_correlation_skips_micro_without_recent_swing():
    micro = [_sig(T0, "long"), _sig(T0 + timedelta(hours=3), "short")]
    # Un seul swing, trop vieux pour le 2e micro.
    swing = [_sig(T0 - timedelta(minutes=5), "long", horizon="swing")]
    rho, n = correlate_micro_vs_swing(micro, swing, timedelta(hours=1))
    assert n == 1  # la 2e paire est ignorée
    assert rho is None  # < 3 paires → pas de corrélation calculable


def test_correlation_ignores_future_swing():
    # Un swing émis APRÈS le micro ne doit jamais être apparié (anti-lookahead).
    micro = [_sig(T0, "long")]
    swing = [_sig(T0 + timedelta(minutes=5), "long", horizon="swing")]
    rho, n = correlate_micro_vs_swing(micro, swing, timedelta(hours=1))
    assert n == 0
    assert rho is None
