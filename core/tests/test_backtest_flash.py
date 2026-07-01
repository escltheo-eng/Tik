"""Tests de la logique pure du backtest flash (backtest_flash.py).

Aucune dépendance DB/réseau : on teste `evaluate_flash_signal` avec un historique
1m synthétique et des signaux factices (duck-typed).
"""

from datetime import UTC, datetime
from types import SimpleNamespace

from tik_core.scripts.backtest_flash import PriceIndex, evaluate_flash_signal


def _history_from(t0: datetime, prices_by_minute: list[float]) -> list[tuple[int, float]]:
    """Construit [(ts_ms, close), ...] à 1 point par minute à partir de t0."""
    base_ms = int(t0.replace(tzinfo=UTC).timestamp() * 1000)
    return [(base_ms + i * 60_000, p) for i, p in enumerate(prices_by_minute)]


T0 = datetime(2026, 6, 30, 12, 0, 0)


def _sig(direction: str, ts: datetime = T0):
    return SimpleNamespace(
        id="TIK-FLASH-BTC-x", timestamp=ts, direction=direction, confidence=0.4, veracity=0.85
    )


class TestEvaluateFlashSignal:
    def test_long_success_when_price_rises(self):
        # +1% sur 60 min → un long (seuil 0.1%) réussit.
        hist = _history_from(T0, [100.0] + [100.0] * 59 + [101.0])
        item = evaluate_flash_signal(_sig("long"), horizon_minutes=60, threshold_pct=0.1, prices=PriceIndex(hist))
        assert item is not None
        assert round(item["delta_pct"], 3) == 1.0
        assert item["success"] is True

    def test_short_fails_when_price_rises(self):
        hist = _history_from(T0, [100.0] + [100.0] * 59 + [101.0])
        item = evaluate_flash_signal(_sig("short"), horizon_minutes=60, threshold_pct=0.1, prices=PriceIndex(hist))
        assert item is not None
        assert item["success"] is False

    def test_short_success_when_price_drops(self):
        hist = _history_from(T0, [100.0] + [100.0] * 59 + [99.0])
        item = evaluate_flash_signal(_sig("short"), horizon_minutes=60, threshold_pct=0.1, prices=PriceIndex(hist))
        assert item is not None
        assert item["success"] is True

    def test_neutral_success_when_flat(self):
        # Mouvement < seuil → un neutral réussit.
        hist = _history_from(T0, [100.0] * 61)
        item = evaluate_flash_signal(_sig("neutral"), horizon_minutes=60, threshold_pct=0.1, prices=PriceIndex(hist))
        assert item is not None
        assert item["success"] is True

    def test_none_when_price_out_of_range(self):
        # Historique trop court (pas de prix à t0+60) → None (au-delà de la tolérance 2 min).
        hist = _history_from(T0, [100.0] * 5)
        item = evaluate_flash_signal(_sig("long"), horizon_minutes=60, threshold_pct=0.1, prices=PriceIndex(hist))
        assert item is None

    def test_entity_always_btc(self):
        hist = _history_from(T0, [100.0] * 61)
        item = evaluate_flash_signal(_sig("neutral"), horizon_minutes=60, threshold_pct=0.1, prices=PriceIndex(hist))
        assert item["entity"] == "BTC"
