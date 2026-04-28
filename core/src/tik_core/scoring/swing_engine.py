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

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

import httpx
import pandas as pd
import structlog
from redis.asyncio import Redis

from tik_core.scoring.indicators import ema, macd, rsi

log = structlog.get_logger()

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
UA = "Mozilla/5.0 (compatible; TikBot/0.1)"

# Binance = flux marché direct, Yahoo = agrégateur avec délai 15min,
# alternative.me FNG = sentiment indirect (donc score modéré).
SOURCE_SCORES: dict[str, float] = {
    "binance_klines": 0.90,
    "yahoo_finance": 0.80,
    "alternative_me_fng": 0.65,
}

FG_REDIS_KEY = "tik.sentiment.fear_greed"


@dataclass
class SwingDecision:
    """Résultat de l'analyse swing pour une entity."""

    entity_id: str
    timestamp: datetime
    direction: Literal["long", "short", "neutral"]
    confidence: float                      # 0..1
    hypothesis: str
    veracity: float = 0.85                 # ajustée par cross-validation (0..1)
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
    source = df.attrs.get("source", "unknown")
    evidence.append(
        {
            "source": source,
            "score": SOURCE_SCORES.get(source, 0.5),
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


def _compute_fg_bias(value: int) -> tuple[float, str]:
    """Mappe une valeur FG (0..100) à un bias contrarian (-1..+1) + zone.

    -1 = sentiment très baissier sur le marché → contrarian SHORT bias.
    +1 = panique extrême sur le marché → contrarian LONG bias.
    """
    if value <= 25:
        return 1.0, "extreme_fear"
    if value <= 45:
        return 0.5, "fear"
    if value <= 55:
        return 0.0, "neutral"
    if value <= 74:
        return -0.5, "greed"
    return -1.0, "extreme_greed"


def _veracity_from_concordance(direction: str, fg_bias: float) -> float:
    """Veracity dynamique selon concordance entre direction technique et bias FG.

    Concordance = +1 (parfaite) → 0.95 ; -1 (opposition franche) → 0.70.
    """
    dir_score = {"long": 1.0, "short": -1.0, "neutral": 0.0}[direction]
    concordance = dir_score * fg_bias
    if concordance >= 0.9:
        return 0.95
    if concordance >= 0.4:
        return 0.90
    if concordance > -0.4:
        return 0.85
    if concordance > -0.9:
        return 0.78
    return 0.70


async def _read_fear_greed(redis: Redis) -> dict | None:
    raw = await redis.get(FG_REDIS_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _apply_fear_greed_overlay(decision: SwingDecision, fg: dict) -> SwingDecision:
    """Enrichit une décision swing avec l'overlay sentiment FG."""
    try:
        value = int(fg["value"])
        classification = str(fg.get("classification", "unknown"))
    except (KeyError, TypeError, ValueError):
        return decision

    bias, zone = _compute_fg_bias(value)
    bias_label = (
        "contrarian bull" if bias > 0
        else "contrarian bear" if bias < 0
        else "neutral"
    )

    decision.evidence.append(
        {
            "source": "alternative_me_fng",
            "score": SOURCE_SCORES.get("alternative_me_fng", 0.5),
            "fact": f"FG={value} ({classification})",
        }
    )
    decision.triggers.append(
        {
            "type": "fear_greed",
            "value": f"FG={value} ({zone} → {bias_label})",
            "weight": 0.10,
        }
    )
    decision.veracity = _veracity_from_concordance(decision.direction, bias)
    return decision


async def analyze_swing_btc(redis: Redis | None = None) -> SwingDecision:
    """Analyse swing BTC/USDT sur 4h, avec overlay sentiment Fear & Greed si dispo."""
    df = await _fetch_binance_klines("BTCUSDT", "4h", 200)
    df.attrs["entity_id"] = "BTC"
    df.attrs["source"] = "binance_klines"
    decision = _score_indicators(df)
    decision.entity_id = "BTC"

    if redis is not None:
        fg = await _read_fear_greed(redis)
        if fg is not None:
            decision = _apply_fear_greed_overlay(decision, fg)
        else:
            log.info("swing.btc.fear_greed_unavailable")

    return decision


async def analyze_swing_gold() -> SwingDecision:
    """Analyse swing Gold (GC=F) sur 1h/60d.

    Pas d'overlay FG : l'index Fear & Greed est crypto-spécifique.
    """
    df = await _fetch_yahoo_klines("GC=F", "1h", "60d")
    df.attrs["entity_id"] = "GOLD"
    df.attrs["source"] = "yahoo_finance"
    decision = _score_indicators(df)
    decision.entity_id = "GOLD"
    return decision
