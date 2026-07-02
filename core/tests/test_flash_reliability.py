"""Tests des fixes fiabilité du flash engine (audit 2026-07-02).

Couvre les chemins qui n'avaient AUCUN test alors qu'ils portent les pires
modes d'échec pour un outil de trading (signal directionnel plausible mais
faux, produit par une donnée partielle) :

- finding #1 : carnet « une seule face » / tronqué → OBI saturé ±1.0
- finding #2 : signal mono-source (N=1) présenté à veracity 0.95
- finding #3 : fraîcheur des klines REST (chemin distinct du WS)
- finding #4 : fetch klines non protégé, réponse vide, < 60 bougies contournée
- finding #6 : contrat de skip par chaîne magique "stale"
- finding #11 : échantillon aggTrades minuscule
- fraîcheur du feed WS (`is_realtime_data_fresh`) : zéro test avant l'audit
"""

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from tik_core.scoring import flash_engine as fe
from tik_core.scoring.cross_validator import cross_validate
from tik_core.scoring.flash_engine import (
    MIN_AGG_TRADES,
    MIN_ORDERBOOK_LEVELS_PER_SIDE,
    _compute_aggression_bias,
    _compute_obi_bias,
    _klines_are_fresh,
    analyze_flash_btc,
    is_realtime_data_fresh,
)
from tik_core.scoring.indicators import rsi


# ----- Helpers -----


class _FakeRedis:
    """Stub Redis minimal : get() renvoie une valeur pré-programmée."""

    def __init__(self, value: str | None):
        self._value = value

    async def get(self, key):  # noqa: ARG002
        return self._value


def _book(n_bids: int, n_asks: int, bid_qty: float = 1.0, ask_qty: float = 1.0) -> dict:
    return {
        "bids": [["50000", str(bid_qty)] for _ in range(n_bids)],
        "asks": [["50001", str(ask_qty)] for _ in range(n_asks)],
    }


def _trades(n: int, buyer_maker: bool = False) -> list[dict]:
    return [{"q": "0.5", "m": buyer_maker} for _ in range(n)]


def _klines_df(n: int, last_open: datetime, price: float = 50000.0) -> pd.DataFrame:
    ts = [last_open - timedelta(minutes=n - 1 - i) for i in range(n)]
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ts, utc=True),
            "open": [price] * n,
            "high": [price * 1.001] * n,
            "low": [price * 0.999] * n,
            "close": [price] * n,
            "volume": [10.0] * n,
        }
    )


# ----- Finding #1 : carnet une face / tronqué -----


def test_obi_one_sided_book_returns_none():
    """Le pire cas : asks vide → OBI vaudrait +1.0 (biais bull maximal fabriqué)."""
    assert _compute_obi_bias({"bids": [["50000", "10"]], "asks": []}) is None


def test_obi_thin_book_returns_none():
    thin = _book(MIN_ORDERBOOK_LEVELS_PER_SIDE - 1, MIN_ORDERBOOK_LEVELS_PER_SIDE - 1)
    assert _compute_obi_bias(thin) is None


def test_obi_normal_book_still_works():
    result = _compute_obi_bias(_book(20, 20, bid_qty=10.0, ask_qty=1.0))
    assert result is not None
    bias, zone, obi = result
    assert bias == 1.0
    assert zone == "obi_strong_bid"
    assert obi > 0.4


def test_obi_balanced_book_unchanged():
    result = _compute_obi_bias(_book(20, 20))
    assert result is not None
    assert result[0] == 0.0


# ----- Finding #11 : échantillon aggTrades minuscule -----


def test_aggression_tiny_sample_returns_none():
    assert _compute_aggression_bias(_trades(MIN_AGG_TRADES - 1)) is None


def test_aggression_sufficient_sample_still_works():
    result = _compute_aggression_bias(_trades(MIN_AGG_TRADES, buyer_maker=False))
    assert result is not None
    assert result[0] == 1.0  # 100 % takers acheteurs


# ----- Finding #2 : N=1 → plus jamais "cross-validé ok" -----


def test_cross_validate_single_source_is_degraded():
    cv = cross_validate({"binance_orderbook": 1.0})
    assert cv.circuit_breaker_status == "degraded"
    assert cv.method == "single_source"
    assert cv.n_sources == 1


# ----- is_realtime_data_fresh (zéro test avant l'audit) -----


@pytest.mark.asyncio
async def test_fresh_feed_returns_true():
    ts = datetime.now(UTC).isoformat()
    redis = _FakeRedis(json.dumps({"price": 50000, "timestamp": ts}))
    assert await is_realtime_data_fresh(redis) is True


@pytest.mark.asyncio
async def test_stale_feed_returns_false():
    ts = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    redis = _FakeRedis(json.dumps({"price": 50000, "timestamp": ts}))
    assert await is_realtime_data_fresh(redis) is False


@pytest.mark.asyncio
async def test_missing_key_returns_false():
    assert await is_realtime_data_fresh(_FakeRedis(None)) is False


@pytest.mark.asyncio
async def test_corrupted_payload_returns_false():
    assert await is_realtime_data_fresh(_FakeRedis("not-json{")) is False
    assert await is_realtime_data_fresh(_FakeRedis(json.dumps({"price": 1}))) is False


# ----- Finding #3 : fraîcheur klines REST -----


def test_klines_fresh_when_last_candle_recent():
    df = _klines_df(240, datetime.now(UTC))
    assert _klines_are_fresh(df) is True


def test_klines_stale_when_last_candle_old():
    df = _klines_df(240, datetime.now(UTC) - timedelta(minutes=10))
    assert _klines_are_fresh(df) is False


def test_klines_empty_is_stale():
    assert _klines_are_fresh(pd.DataFrame({"timestamp": []})) is False


# ----- Findings #4/#6 : analyze_flash_btc skip proprement, contrat advisory -----


@pytest.mark.asyncio
async def test_analyze_skips_when_klines_fetch_fails(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("HTTP 429")

    monkeypatch.setattr(fe, "_fetch_klines_1m", boom)
    decision = await analyze_flash_btc(redis=None)
    assert decision.direction == "neutral"
    assert decision.confidence == 0.0
    assert decision.advisory["skip_reason"] == "klines_unavailable"


@pytest.mark.asyncio
async def test_analyze_skips_on_stale_klines(monkeypatch):
    async def stale_klines(*args, **kwargs):
        return _klines_df(240, datetime.now(UTC) - timedelta(minutes=30))

    monkeypatch.setattr(fe, "_fetch_klines_1m", stale_klines)
    decision = await analyze_flash_btc(redis=None)
    assert decision.advisory["skip_reason"] == "klines_stale"


@pytest.mark.asyncio
async def test_analyze_skips_on_insufficient_klines_no_overlay_override(monkeypatch):
    """Avant le fix, 30 bougies produisaient quand même un signal directionnel
    (la décision "insufficient data" était écrasée par les overlays)."""

    async def short_klines(*args, **kwargs):
        return _klines_df(30, datetime.now(UTC))

    called = {"orderbook": False}

    async def orderbook_should_not_run(*args, **kwargs):
        called["orderbook"] = True
        return _book(20, 20, bid_qty=10.0)

    monkeypatch.setattr(fe, "_fetch_klines_1m", short_klines)
    monkeypatch.setattr(fe, "_fetch_orderbook", orderbook_should_not_run)
    decision = await analyze_flash_btc(redis=None)
    assert decision.advisory["skip_reason"] == "insufficient_klines"
    assert decision.direction == "neutral"
    assert called["orderbook"] is False


@pytest.mark.asyncio
async def test_analyze_single_overlay_caps_veracity(monkeypatch):
    """N=1 (aggTrades down, orderbook seul) : veracity 0.70 + statut degraded,
    plus jamais 0.95 sur une photo unique du carnet (finding #2)."""

    async def fresh_klines(*args, **kwargs):
        return _klines_df(240, datetime.now(UTC))

    async def strong_bid_book(*args, **kwargs):
        return _book(20, 20, bid_qty=10.0, ask_qty=1.0)

    async def trades_down(*args, **kwargs):
        raise RuntimeError("HTTP 500")

    async def no_dynamic_scores(*args, **kwargs):
        return {}

    monkeypatch.setattr(fe, "_fetch_klines_1m", fresh_klines)
    monkeypatch.setattr(fe, "_fetch_orderbook", strong_bid_book)
    monkeypatch.setattr(fe, "_fetch_agg_trades", trades_down)
    monkeypatch.setattr(fe, "preload_source_scores", no_dynamic_scores)

    decision = await analyze_flash_btc(redis=None)
    assert decision.direction == "long"  # le biais mono-source reste appliqué
    assert decision.veracity == 0.70  # ... mais sans vernis de certitude
    assert decision.circuit_breaker_status == "degraded"


# ----- RSI : plus de NaN sur montée pure (cosmétique, finding #9 audit) -----


def test_rsi_pure_uptrend_is_100_not_nan():
    prices = pd.Series([100.0 + i for i in range(30)])
    value = rsi(prices, 14).iloc[-1]
    assert value == 100.0


def test_rsi_flat_series_is_50():
    prices = pd.Series([100.0] * 30)
    value = rsi(prices, 14).iloc[-1]
    assert value == 50.0
