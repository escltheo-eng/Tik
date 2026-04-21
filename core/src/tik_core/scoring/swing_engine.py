"""Swing engine — horizon jours-semaines.

Logique actuelle volontairement simple et lisible (MVP) :
- Récupère les N derniers klines Binance (BTC) ou Yahoo (Gold)
- Calcule RSI 14, MACD, EMA 20/50
- Score par règles pondérées → direction + confidence
- Contre-scénarios ajoutés automatiquement

Cette implémentation est un POINT DE DÉPART. Elle sera enrichie par :
- Sentiment news (couche 6)
- Calendrier macro (FRED)
- Fear & Greed (couche 7)
- ML après collecte de données suffisantes
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import httpx
import pandas as pd
import structlog

from tik_core.scoring.indicators import ema, macd, rsi

log = structlog.get_logger()

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
UA = "Mozilla/5.0 (compatible; TikBot/0.1)"


@dataclass
class SwingDecision:
    """Résultat de l'analyse swing pour une entity."""

    entity_id: str
    timestamp: datetime
    direction: Literal["long", "short", "neutral"]
    confidence: float                      # 0..1
    hypothesis: str
    counter_scenarios: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)


async def _fetch_binance_klines(symbol: str = "BTCUSDT", interval: str = "4h", limit: int = 200) -> pd.DataFrame:
    """Récupère les klines Binance en DataFrame (open, high, low, close, volume)."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            BINANCE_KLINES,
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        r.raise_for_status()
        raw = r.json()

    df = pd.DataFrame(
        raw,
        columns=[
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "_q", "_n", "_tb_base", "_tb_quote", "_ignore",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


async def _fetch_yahoo_klines(symbol: str = "GC=F", interval: str = "1h", range_: str = "60d") -> pd.DataFrame:
    """Récupère les klines Yahoo en DataFrame."""
    url = YAHOO_CHART.format(symbol=symbol)
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            url,
            params={"interval": interval, "range": range_},
            headers={"User-Agent": UA},
        )
        r.raise_for_status()
        data = r.json()

    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(ts, unit="s", utc=True),
            "open": q["open"],
            "high": q["high"],
            "low": q["low"],
            "close": q["close"],
            "volume": q.get("volume") or [0] * len(ts),
        }
    ).dropna()
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df


def _score_indicators(df: pd.DataFrame) -> SwingDecision:
    """Score les indicateurs et produit une décision swing."""
    if len(df) < 60:
        return SwingDecision(
            entity_id="unknown",
            timestamp=datetime.utcnow(),
            direction="neutral",
            confidence=0.0,
            hypothesis="Insufficient historical data for swing analysis",
        )

    close = df["close"]
    rsi_14 = rsi(close, 14)
    ema_20 = ema(close, 20)
    ema_50 = ema(close, 50)
    macd_line, signal_line, hist = macd(close)

    last = df.iloc[-1]
    current_price = last["close"]
    current_rsi = rsi_14.iloc[-1]
    current_ema20 = ema_20.iloc[-1]
    current_ema50 = ema_50.iloc[-1]
    current_macd = macd_line.iloc[-1]
    current_signal = signal_line.iloc[-1]
    current_hist = hist.iloc[-1]
    prev_hist = hist.iloc[-2]

    triggers: list[dict] = []
    evidence: list[dict] = []

    # Règle 1 — EMA cross (trend direction)
    trend_long = current_ema20 > current_ema50
    trend_short = current_ema20 < current_ema50
    if trend_long:
        triggers.append({"type": "ema_cross", "value": "EMA20 > EMA50 (uptrend)", "weight": 0.25})
    elif trend_short:
        triggers.append({"type": "ema_cross", "value": "EMA20 < EMA50 (downtrend)", "weight": 0.25})

    # Règle 2 — RSI
    if current_rsi > 70:
        triggers.append({"type": "rsi", "value": f"RSI overbought {current_rsi:.1f}", "weight": 0.20})
    elif current_rsi < 30:
        triggers.append({"type": "rsi", "value": f"RSI oversold {current_rsi:.1f}", "weight": 0.20})
    elif current_rsi > 55:
        triggers.append({"type": "rsi", "value": f"RSI bullish {current_rsi:.1f}", "weight": 0.10})
    elif current_rsi < 45:
        triggers.append({"type": "rsi", "value": f"RSI bearish {current_rsi:.1f}", "weight": 0.10})

    # Règle 3 — MACD momentum shift
    macd_bull_cross = prev_hist <= 0 < current_hist
    macd_bear_cross = prev_hist >= 0 > current_hist
    if macd_bull_cross:
        triggers.append({"type": "macd", "value": "MACD bullish cross", "weight": 0.20})
    elif macd_bear_cross:
        triggers.append({"type": "macd", "value": "MACD bearish cross", "weight": 0.20})
    elif current_macd > current_signal:
        triggers.append({"type": "macd", "value": "MACD above signal", "weight": 0.10})
    elif current_macd < current_signal:
        triggers.append({"type": "macd", "value": "MACD below signal", "weight": 0.10})

    # Agrégation
    bull_score = 0.0
    bear_score = 0.0
    if trend_long:
        bull_score += 0.25
    if trend_short:
        bear_score += 0.25

    if current_rsi > 55 and current_rsi <= 70:
        bull_score += 0.15
    if current_rsi < 45 and current_rsi >= 30:
        bear_score += 0.15
    # Zones extrêmes = contrarian plutôt que trend-following
    if current_rsi > 70:
        bear_score += 0.10  # reversal risk
    if current_rsi < 30:
        bull_score += 0.10  # reversal opportunity

    if current_macd > current_signal:
        bull_score += 0.15
    if current_macd < current_signal:
        bear_score += 0.15
    if macd_bull_cross:
        bull_score += 0.15
    if macd_bear_cross:
        bear_score += 0.15

    # Direction
    if bull_score > bear_score + 0.15:
        direction: Literal["long", "short", "neutral"] = "long"
        confidence = min(bull_score, 1.0)
    elif bear_score > bull_score + 0.15:
        direction = "short"
        confidence = min(bear_score, 1.0)
    else:
        direction = "neutral"
        confidence = abs(bull_score - bear_score)

    # Evidence technique
    evidence.append(
        {
            "source": "binance_klines",
            "score": 0.85,
            "fact": f"RSI14={current_rsi:.1f}, EMA20/50={current_ema20:.2f}/{current_ema50:.2f}, MACD={current_macd:.3f}",
        }
    )

    # Contre-scénarios standards pour swing
    counter_scenarios = [
        {
            "name": "macro_shock",
            "probability": 0.15,
            "mitigation": "Monitor DXY spike and yield curve inversion",
        },
        {
            "name": "indicator_whipsaw",
            "probability": 0.20,
            "mitigation": "Confirm direction on multi-timeframe (1D trend)",
        },
    ]

    hypothesis = (
        f"Swing {direction} on {df.attrs.get('entity_id', 'entity')} "
        f"based on EMA/RSI/MACD confluence "
        f"(bull={bull_score:.2f}, bear={bear_score:.2f})"
    )

    return SwingDecision(
        entity_id=df.attrs.get("entity_id", "unknown"),
        timestamp=datetime.utcnow(),
        direction=direction,
        confidence=round(confidence, 3),
        hypothesis=hypothesis,
        counter_scenarios=counter_scenarios,
        evidence=evidence,
        triggers=triggers,
    )


async def analyze_swing_btc() -> SwingDecision:
    """Analyse swing BTC/USDT sur 4h."""
    df = await _fetch_binance_klines("BTCUSDT", "4h", 200)
    df.attrs["entity_id"] = "BTC"
    decision = _score_indicators(df)
    decision.entity_id = "BTC"
    return decision


async def analyze_swing_gold() -> SwingDecision:
    """Analyse swing Gold (GC=F) sur 1h/60d."""
    df = await _fetch_yahoo_klines("GC=F", "1h", "60d")
    df.attrs["entity_id"] = "GOLD"
    decision = _score_indicators(df)
    decision.entity_id = "GOLD"
    return decision
