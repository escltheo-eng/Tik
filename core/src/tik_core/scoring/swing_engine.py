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

from tik_core.config import get_settings
from tik_core.scoring.anomaly_detector import AnomalyResult
from tik_core.scoring.cross_validator import apply_cross_validation_to_decision
from tik_core.scoring.hypothesis_generator import (
    HypothesisGenerator,
    apply_llm_hypothesis,
)
from tik_core.scoring.indicators import ema, macd, rsi
from tik_core.scoring.source_credibility import (
    get_effective_score,
    preload_source_scores,
    reset_dynamic_scores,
    set_dynamic_scores,
)
from tik_core.utils.time import now_utc

log = structlog.get_logger()

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
UA = "Mozilla/5.0 (compatible; TikBot/0.1)"

# Binance = flux marché direct ; Yahoo = agrégateur délai 15min ;
# alternative.me FNG = sentiment indirect ; FRED DTWEXBGS = source officielle US gov ;
# CryptoCompare news = signal direct des news mais peut être manipulé/biaisé ;
# google_news_rss = agrégateur news mainstream (Reuters, Bloomberg, FT…), score
#   provisoire à 0.70 tant que dataset golden non mesuré (cf. ADR-008) ;
# reddit_btc = sentiment retail communautaire pondéré par log(upvotes), score
#   provisoire 0.65 — un cran sous mainstream pour refléter la nature retail
#   amateur, mais pas trop pénalisant (cf. ADR-009) ;
# gdelt_news = NLP scientifique mondial (GDELT 2.0 timelinetone), tone brut
#   non passé par Ollama, méthode différente des autres news textuelles
#   (cf. ADR-010) ; score 0.75 entre éditorial (0.70) et officiel chiffré (0.85) ;
# cftc_cot = source officielle US gov mais lag 3-4j (publié vendredi pour le mardi).
SOURCE_SCORES: dict[str, float] = {
    "binance_klines": 0.90,
    "yahoo_finance": 0.80,
    "alternative_me_fng": 0.65,
    "fred_dtwexbgs": 0.85,
    "cryptocompare_news": 0.70,
    "google_news_rss": 0.70,
    "reddit_btc": 0.65,
    "gdelt_news": 0.75,
    "cftc_cot": 0.80,
}

FG_REDIS_KEY = "tik.sentiment.fear_greed"
CC_REDIS_KEY_TPL = "tik.sentiment.cryptocompare.{currency}"
GN_REDIS_KEY_TPL = "tik.sentiment.google_news.{entity}"
RED_REDIS_KEY_TPL = "tik.sentiment.reddit.{entity}"
GDELT_REDIS_KEY_TPL = "tik.sentiment.gdelt.{entity}"
COT_REDIS_KEY = "tik.macro.cftc_cot.gold"
FRED_OBS_URL = "https://api.stlouisfed.org/fred/series/observations"
DXY_SERIES_ID = "DTWEXBGS"


@dataclass
class SwingDecision:
    """Résultat de l'analyse swing pour une entity.

    ADR-018 — Tik OSINT pure (refactor 2026-05-07) :
    - `direction` est dérivée du `combined_bias` OSINT cross-validé,
      pas de l'analyse technique RSI/MACD/EMA
    - `confidence` = magnitude du `combined_bias` ∈ [0, 1] (sémantique
      uniforme, plus de double sens long/short vs neutral)
    - Sans overlay OSINT disponible : direction = "neutral", confidence = 0
    - Les indicateurs techniques (RSI/MACD/EMA) restent calculés et
      affichés en `evidence` + `triggers` pour audit et contexte humain,
      mais n'influencent plus la décision directionnelle
    """

    entity_id: str
    timestamp: datetime
    direction: Literal["long", "short", "neutral"]
    confidence: float                      # 0..1 — magnitude du combined_bias OSINT (ADR-018)
    hypothesis: str
    veracity: float = 0.85                 # ajustée par cross-validation (0..1)
    counter_scenarios: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)
    circuit_breaker_status: str = "ok"     # ok | degraded | tripped (cf. ADR-011)
    advisory: dict = field(default_factory=dict)  # candidates LLM (ADR-012), etc.


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


def _compute_technical_evidence(df: pd.DataFrame) -> SwingDecision:
    """Calcule les indicateurs techniques (RSI/MACD/EMA) et produit une SwingDecision
    avec evidence + triggers techniques mais SANS direction décisionnelle.

    ADR-018 — Tik OSINT pure (refactor 2026-05-07) :
    - Les indicateurs techniques sont calculés et **affichés** en evidence/triggers
      pour audit et contexte humain
    - Mais ils **n'influencent plus la décision directionnelle**
    - La direction et la confidence sont mises à 0/neutral par défaut, à dériver
      ultérieurement du `combined_bias` OSINT via `_derive_osint_decision()`
    - Cette séparation permet à Tik d'être une plateforme OSINT pure (cohérence
      stratégique vs Zeta qui fait l'analyse technique pour exécution)

    Renommée depuis `_score_indicators()` pour refléter le nouveau rôle :
    calcul d'evidence technique informative, pas de scoring décisionnel.
    """
    if len(df) < 60:
        return SwingDecision(
            entity_id="unknown",
            timestamp=now_utc(),
            direction="neutral",
            confidence=0.0,
            hypothesis="Insufficient historical data for swing analysis",
        )

    close = df["close"]
    rsi_14 = rsi(close, 14)
    ema_20 = ema(close, 20)
    ema_50 = ema(close, 50)
    macd_line, signal_line, hist = macd(close)

    current_rsi = rsi_14.iloc[-1]
    current_ema20 = ema_20.iloc[-1]
    current_ema50 = ema_50.iloc[-1]
    current_macd = macd_line.iloc[-1]
    current_signal = signal_line.iloc[-1]
    current_hist = hist.iloc[-1]
    prev_hist = hist.iloc[-2]

    triggers: list[dict] = []
    evidence: list[dict] = []

    # Indicateurs techniques affichés en triggers (informatifs uniquement,
    # plus utilisés pour décider — cf. ADR-018).

    # Règle 1 — EMA cross (informatif sur la micro-tendance technique)
    trend_long = current_ema20 > current_ema50
    trend_short = current_ema20 < current_ema50
    if trend_long:
        triggers.append({"type": "ema_cross", "value": "EMA20 > EMA50 (uptrend)", "weight": 0.0})
    elif trend_short:
        triggers.append({"type": "ema_cross", "value": "EMA20 < EMA50 (downtrend)", "weight": 0.0})

    # Règle 2 — RSI (informatif)
    if current_rsi > 70:
        triggers.append({"type": "rsi", "value": f"RSI overbought {current_rsi:.1f}", "weight": 0.0})
    elif current_rsi < 30:
        triggers.append({"type": "rsi", "value": f"RSI oversold {current_rsi:.1f}", "weight": 0.0})
    elif current_rsi > 55:
        triggers.append({"type": "rsi", "value": f"RSI bullish {current_rsi:.1f}", "weight": 0.0})
    elif current_rsi < 45:
        triggers.append({"type": "rsi", "value": f"RSI bearish {current_rsi:.1f}", "weight": 0.0})

    # Règle 3 — MACD (informatif)
    macd_bull_cross = prev_hist <= 0 < current_hist
    macd_bear_cross = prev_hist >= 0 > current_hist
    if macd_bull_cross:
        triggers.append({"type": "macd", "value": "MACD bullish cross", "weight": 0.0})
    elif macd_bear_cross:
        triggers.append({"type": "macd", "value": "MACD bearish cross", "weight": 0.0})
    elif current_macd > current_signal:
        triggers.append({"type": "macd", "value": "MACD above signal", "weight": 0.0})
    elif current_macd < current_signal:
        triggers.append({"type": "macd", "value": "MACD below signal", "weight": 0.0})

    # Evidence technique (informatif, weight 0.0 dans les nouveaux triggers
    # pour signaler qu'ils ne pèsent pas dans la décision OSINT pure).
    source = df.attrs.get("source", "unknown")
    evidence.append(
        {
            "source": source,
            "score": SOURCE_SCORES.get(source, 0.5),
            "fact": (
                f"RSI14={current_rsi:.1f}, "
                f"EMA20/50={current_ema20:.2f}/{current_ema50:.2f}, "
                f"MACD={current_macd:.3f}"
            ),
        }
    )

    # Contre-scénarios standards pour swing (inchangés)
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

    # Direction et confidence par défaut neutres — à mettre à jour par
    # `_derive_osint_decision()` une fois les overlays OSINT cross-validés.
    # Si pas d'OSINT disponible (Redis miss), reste à neutral/0 — cohérent
    # avec ADR-018 (Tik ne décide pas sans OSINT).
    hypothesis = (
        f"Swing analysis on {df.attrs.get('entity_id', 'entity')} — "
        f"awaiting OSINT cross-validation for direction"
    )

    return SwingDecision(
        entity_id=df.attrs.get("entity_id", "unknown"),
        timestamp=now_utc(),
        direction="neutral",
        confidence=0.0,
        hypothesis=hypothesis,
        counter_scenarios=counter_scenarios,
        evidence=evidence,
        triggers=triggers,
    )


# Alias rétrocompat — pointe vers la fonction renommée. Permet aux callers
# externes (tests, scripts) qui importaient `_score_indicators` de continuer
# à fonctionner. Sera supprimé après migration complète des tests.
_score_indicators = _compute_technical_evidence


def _derive_osint_decision(
    decision: SwingDecision,
    combined_bias: float,
    threshold: float = 0.30,
) -> None:
    """Met à jour direction et confidence d'une SwingDecision selon le combined_bias OSINT.

    ADR-018 — Tik OSINT pure : la direction et la conviction sont dérivées
    uniquement du biais OSINT cross-validé, pas de l'analyse technique.

    - combined_bias > +threshold → direction = "long"
    - combined_bias < -threshold → direction = "short"
    - sinon → direction = "neutral"

    confidence = abs(combined_bias) ∈ [0, 1] (magnitude de la conviction OSINT).

    Mute la decision en place. Met aussi à jour la hypothesis pour refléter
    la décision OSINT.
    """
    if combined_bias > threshold:
        decision.direction = "long"
    elif combined_bias < -threshold:
        decision.direction = "short"
    else:
        decision.direction = "neutral"

    decision.confidence = round(abs(combined_bias), 3)

    # Hypothèse mise à jour pour refléter la décision OSINT
    decision.hypothesis = (
        f"Swing {decision.direction} on {decision.entity_id} "
        f"based on OSINT cross-validation (combined_bias={combined_bias:+.2f}, "
        f"|conviction|={decision.confidence:.2f})"
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
    """[LEGACY ADR-018] Veracity dynamique selon concordance direction technique ↔ bias FG.

    Conservée pour rétrocompat des tests existants. **Plus utilisée en
    runtime** depuis ADR-018 (refactor pur OSINT 2026-05-07) — utiliser
    `_veracity_from_dispersion()` à la place.

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


def _veracity_from_dispersion(dispersion: float) -> float:
    """Veracity dynamique selon dispersion (std) des biais sources OSINT.

    ADR-018 — Tik OSINT pure (refactor 2026-05-07) : la veracity mesure
    désormais l'alignement des sources OSINT entre elles, pas la concordance
    technique vs sentiment (qui n'a plus de sens depuis que la direction
    est dérivée du combined_bias OSINT lui-même).

    Sur des biais bornés [-1, +1], l'écart-type max théorique est ~1.0
    (N=2 aux extrêmes ±1) ou ~1.15 (N≥4 split 50/50). Seuils calibrés
    sur cette échelle :

    - dispersion < 0.2 → 0.95 (sources très alignées, forte conviction)
    - dispersion < 0.4 → 0.90 (alignement raisonnable)
    - dispersion < 0.6 → 0.85 (alignement modéré)
    - dispersion < 0.8 → 0.78 (sources éclatées, prudence)
    - dispersion ≥ 0.8 → 0.70 (sources très divergentes, désaccord)

    Résout le bug #2 identifié dans l'audit Paquet 17 P5 : la veracity
    n'est plus figée à 0.85 pour les signaux neutral (cas où dir_score=0
    rendait concordance=0 toujours dans l'ancienne formule).

    Calibration provisoire des seuils, à réviser empiriquement post-J+30.
    """
    if dispersion < 0.2:
        return 0.95
    if dispersion < 0.4:
        return 0.90
    if dispersion < 0.6:
        return 0.85
    if dispersion < 0.8:
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


def _apply_anomaly_pondération(
    decision: SwingDecision,
    source_label: str,
    bias: float,
    anomaly: dict | None,
) -> float:
    """Applique la pondération P6 sur le bias selon le résultat anomaly.

    Cohérent CLAUDE.md Paquet 21 P6 décision D-P6-1 (verdict bias /2 sur high) :

    - severity=high → bias divisé par 2 + flag dans evidence (réduit l'influence
      sans supprimer)
    - severity=medium → bias inchangé + flag dans evidence (transparence)
    - severity=ok ou anomaly None → bias inchangé, pas de flag

    Args:
        decision: la SwingDecision à enrichir avec evidence si applicable.
        source_label: nom de la source pour le message evidence
            (ex. "reddit_btc", "google_news_rss", "cryptocompare_news").
        bias: bias brut calculé par l'overlay, à pondérer.
        anomaly: payload `anomaly` lu depuis Redis (peut être None pour
            rétrocompat avec les payloads pre-fix qui n'ont pas le champ).

    Returns:
        Bias pondéré (divisé par 2 si severity=high, inchangé sinon).
    """
    if not isinstance(anomaly, dict):
        return bias
    severity = anomaly.get("severity")
    if severity not in ("high", "medium"):
        return bias

    anomaly_type = anomaly.get("type", "unknown")
    detail = str(anomaly.get("detail", ""))
    action = "/2" if severity == "high" else "kept"
    decision.evidence.append(
        {
            "source": "anomaly_detector",
            "score": 1.0,  # Détecteur interne, on trust son verdict
            "fact": (
                f"P6 anomaly on {source_label}: {anomaly_type} "
                f"severity={severity} → bias {action} ({detail})"
            ),
        }
    )

    if severity == "high":
        return bias / 2
    return bias


def _enrich_with_fear_greed(decision: SwingDecision, fg: dict) -> float | None:
    """Ajoute evidence + trigger FG à la décision, retourne le bias contrarian.

    NE set PAS la veracity — responsabilité du caller pour combiner plusieurs sources.
    Retourne None si la donnée FG est invalide.
    """
    try:
        value = int(fg["value"])
        classification = str(fg.get("classification", "unknown"))
    except (KeyError, TypeError, ValueError):
        return None

    bias, zone = _compute_fg_bias(value)
    bias_label = (
        "contrarian bull" if bias > 0
        else "contrarian bear" if bias < 0
        else "neutral"
    )

    decision.evidence.append(
        {
            "source": "alternative_me_fng",
            "score": get_effective_score("alternative_me_fng", SOURCE_SCORES),
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
    return bias


async def _read_cryptocompare(redis: Redis, currency: str = "BTC") -> dict | None:
    raw = await redis.get(CC_REDIS_KEY_TPL.format(currency=currency.lower()))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _compute_cryptocompare_bias(score: float) -> tuple[float, str]:
    """Mappe un score net CryptoCompare (-1..+1) à un bias trend-following.

    Contrairement à FG (contrarian), pour les news on suit le sentiment :
    news bullish → bias bull, news bearish → bias bear.
    """
    if score >= 0.4:
        return 1.0, "news_strong_bullish"
    if score >= 0.1:
        return 0.5, "news_bullish"
    if score <= -0.4:
        return -1.0, "news_strong_bearish"
    if score <= -0.1:
        return -0.5, "news_bearish"
    return 0.0, "news_neutral"


def _enrich_with_cryptocompare(decision: SwingDecision, cc: dict) -> float | None:
    """Ajoute evidence + trigger CryptoCompare news, retourne le bias trend-following.

    P6 (Paquet 21) : si le payload contient un champ `anomaly` avec
    severity=high (volume spike anormal), le bias est divisé par 2 et un
    flag est ajouté à l'evidence (cf. `_apply_anomaly_pondération`).
    """
    try:
        score = float(cc["score"])
        n_articles = int(cc.get("n_articles", 0))
        n_bull = int(cc.get("n_bullish", 0))
        n_bear = int(cc.get("n_bearish", 0))
    except (KeyError, TypeError, ValueError):
        return None

    bias, zone = _compute_cryptocompare_bias(score)
    bias_label = (
        "bull" if bias > 0
        else "bear" if bias < 0
        else "neutral"
    )

    decision.evidence.append(
        {
            "source": "cryptocompare_news",
            "score": get_effective_score("cryptocompare_news", SOURCE_SCORES),
            "fact": f"News score={score:+.2f} (bull={n_bull}, bear={n_bear} on {n_articles} BTC titles)",
        }
    )
    decision.triggers.append(
        {
            "type": "news_sentiment",
            "value": f"News {zone} (score={score:+.2f}) → {bias_label}",
            "weight": 0.10,
        }
    )
    return _apply_anomaly_pondération(
        decision, "cryptocompare_news", bias, cc.get("anomaly")
    )


async def _read_google_news(redis: Redis, entity_id: str) -> dict | None:
    raw = await redis.get(GN_REDIS_KEY_TPL.format(entity=entity_id.lower()))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _compute_google_news_bias(score: float) -> tuple[float, str]:
    """Mappe un score net Google News (-1..+1) à un bias trend-following.

    Paliers identiques à CryptoCompare pour cohérence multi-source news
    textuelle (cf. ADR-008). Si une source diverge fortement de l'autre,
    leurs biais se neutralisent dans la moyenne et la veracity baisse via
    `_veracity_from_concordance` — c'est le contrat ADR-004.
    """
    if score >= 0.4:
        return 1.0, "news_strong_bullish"
    if score >= 0.1:
        return 0.5, "news_bullish"
    if score <= -0.4:
        return -1.0, "news_strong_bearish"
    if score <= -0.1:
        return -0.5, "news_bearish"
    return 0.0, "news_neutral"


def _enrich_with_google_news(decision: SwingDecision, gn: dict) -> float | None:
    """Ajoute evidence + trigger Google News, retourne le bias trend-following.

    NE set PAS la veracity — responsabilité du caller pour combiner plusieurs sources.
    Retourne None si la donnée Google News est invalide ou incomplète.
    """
    try:
        score = float(gn["score"])
        n_articles = int(gn.get("n_articles", 0))
        n_bull = int(gn.get("n_bullish", 0))
        n_bear = int(gn.get("n_bearish", 0))
        top_publishers = gn.get("top_publishers") or []
    except (KeyError, TypeError, ValueError):
        return None

    bias, zone = _compute_google_news_bias(score)
    bias_label = (
        "bull" if bias > 0
        else "bear" if bias < 0
        else "neutral"
    )

    top_names = [
        p.get("name", "?")
        for p in top_publishers[:3]
        if isinstance(p, dict)
    ]
    pubs_str = f", top: {', '.join(top_names)}" if top_names else ""

    decision.evidence.append(
        {
            "source": "google_news_rss",
            "score": get_effective_score("google_news_rss", SOURCE_SCORES),
            "fact": (
                f"News score={score:+.2f} (bull={n_bull}, bear={n_bear} "
                f"on {n_articles} {decision.entity_id} titles{pubs_str})"
            ),
        }
    )
    decision.triggers.append(
        {
            "type": "news_sentiment_google",
            "value": f"Google News {zone} (score={score:+.2f}) → {bias_label}",
            "weight": 0.10,
        }
    )
    # P6 (Paquet 21) : si publisher_dominance severity=high, bias /= 2.
    return _apply_anomaly_pondération(
        decision, "google_news_rss", bias, gn.get("anomaly")
    )


async def _read_reddit(redis: Redis, entity_id: str) -> dict | None:
    raw = await redis.get(RED_REDIS_KEY_TPL.format(entity=entity_id.lower()))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _compute_reddit_bias(score: float) -> tuple[float, str]:
    """Mappe un score net Reddit pondéré par log(upvotes+1) à un bias trend-following.

    Paliers identiques aux autres sources news textuelles (cohérence ADR-004).
    Le score reçu est déjà pondéré côté ingester (cf. ADR-009) — la
    pondération log(upvotes) reflète le poids communautaire de chaque post.
    """
    if score >= 0.4:
        return 1.0, "reddit_strong_bullish"
    if score >= 0.1:
        return 0.5, "reddit_bullish"
    if score <= -0.4:
        return -1.0, "reddit_strong_bearish"
    if score <= -0.1:
        return -0.5, "reddit_bearish"
    return 0.0, "reddit_neutral"


def _enrich_with_reddit(decision: SwingDecision, rd: dict) -> float | None:
    """Ajoute evidence + trigger Reddit (sentiment retail), retourne le bias.

    NE set PAS la veracity — responsabilité du caller pour combiner plusieurs sources.
    Retourne None si la donnée Reddit est invalide ou incomplète.
    """
    try:
        score = float(rd["score"])
        n_articles = int(rd.get("n_articles", 0))
        n_bull = int(rd.get("n_bullish", 0))
        n_bear = int(rd.get("n_bearish", 0))
        top_subs = rd.get("top_subreddits") or []
    except (KeyError, TypeError, ValueError):
        return None

    bias, zone = _compute_reddit_bias(score)
    bias_label = (
        "bull" if bias > 0
        else "bear" if bias < 0
        else "neutral"
    )

    top_names = [
        f"r/{s.get('name', '?')}"
        for s in top_subs[:3]
        if isinstance(s, dict)
    ]
    subs_str = f", top: {', '.join(top_names)}" if top_names else ""

    decision.evidence.append(
        {
            "source": "reddit_btc",
            "score": get_effective_score("reddit_btc", SOURCE_SCORES),
            "fact": (
                f"Reddit retail score={score:+.2f} "
                f"(bull={n_bull}, bear={n_bear} on {n_articles} weighted posts{subs_str})"
            ),
        }
    )
    decision.triggers.append(
        {
            "type": "news_sentiment_reddit",
            "value": f"Reddit {zone} (score={score:+.2f}) → {bias_label}",
            "weight": 0.10,
        }
    )
    # P6 (Paquet 21) : si brigading_reddit severity=high, bias /= 2.
    return _apply_anomaly_pondération(
        decision, "reddit_btc", bias, rd.get("anomaly")
    )


async def analyze_swing_btc(
    redis: Redis | None = None,
    hypothesis_generator: HypothesisGenerator | None = None,
) -> SwingDecision:
    """Analyse swing BTC/USDT sur 4h avec overlays multi-sources.

    Overlays actifs (cf. ADR-004 / ADR-008 / ADR-009) :
    - Fear & Greed (Redis, contrarian)
    - CryptoCompare news (Redis, trend-following, crypto-éditorial)
    - Google News BTC (Redis, trend-following, mainstream-éditorial)
    - Reddit BTC (Redis, trend-following, retail-communautaire pondéré log)

    La veracity finale est calculée sur la concordance moyenne des biais
    des sources de sentiment disponibles. Permet d'ajouter facilement de
    nouvelles sources via le pattern `_enrich_with_<source>`.

    Si `hypothesis_generator` est fourni, génère une hypothèse contextuelle
    via LLM après la cross-validation (cf. ADR-012). Le mode (disabled /
    shadow / active) est lu depuis `settings.llm_hypothesis_mode`.
    """
    df = await _fetch_binance_klines("BTCUSDT", "4h", 200)
    df.attrs["entity_id"] = "BTC"
    df.attrs["source"] = "binance_klines"
    decision = _score_indicators(df)
    decision.entity_id = "BTC"

    settings = get_settings()

    if redis is None:
        await apply_llm_hypothesis(
            decision, "swing", hypothesis_generator,
            settings.llm_hypothesis_mode,
        )
        return decision

    # Précharge les scores dynamiques (override Redis sur SOURCE_SCORES) — ADR-011
    dynamic_scores = await preload_source_scores(
        redis,
        ["alternative_me_fng", "cryptocompare_news", "google_news_rss", "reddit_btc"],
    )
    token = set_dynamic_scores(dynamic_scores)
    try:
        biases_by_source: dict[str, float] = {}

        fg = await _read_fear_greed(redis)
        if fg is not None:
            bias = _enrich_with_fear_greed(decision, fg)
            if bias is not None:
                biases_by_source["alternative_me_fng"] = bias
        else:
            log.info("swing.btc.fear_greed_unavailable")

        cc = await _read_cryptocompare(redis, currency="BTC")
        if cc is not None:
            bias = _enrich_with_cryptocompare(decision, cc)
            if bias is not None:
                biases_by_source["cryptocompare_news"] = bias
        else:
            log.info("swing.btc.cryptocompare_unavailable")

        gn = await _read_google_news(redis, entity_id="BTC")
        if gn is not None:
            bias = _enrich_with_google_news(decision, gn)
            if bias is not None:
                biases_by_source["google_news_rss"] = bias
        else:
            log.info("swing.btc.google_news_unavailable")

        rd = await _read_reddit(redis, entity_id="BTC")
        if rd is not None:
            bias = _enrich_with_reddit(decision, rd)
            if bias is not None:
                biases_by_source["reddit_btc"] = bias
        else:
            log.info("swing.btc.reddit_unavailable")

        if biases_by_source:
            cv = apply_cross_validation_to_decision(
                decision, biases_by_source, mode=settings.antifakenews_mode
            )
            # ADR-018 — Tik OSINT pure : direction et confidence dérivées
            # du combined_bias OSINT (pas de l'analyse technique).
            _derive_osint_decision(decision, cv.combined_bias)
            # Veracity dérivée de la dispersion des sources OSINT
            # (résout bug #2 audit Paquet 17 — veracity neutral figée à 0.85).
            decision.veracity = _veracity_from_dispersion(cv.dispersion)
            if cv.circuit_breaker_status != "ok":
                log.info(
                    "anti_fake_news.flagged",
                    entity_id=decision.entity_id,
                    horizon="swing",
                    status=cv.circuit_breaker_status,
                    outliers=list(cv.outlier_sources),
                    method=cv.method,
                    mode=settings.antifakenews_mode,
                )

        # Génération hypothèse contextuelle LLM (post-enrichissements + post-CV)
        await apply_llm_hypothesis(
            decision, "swing", hypothesis_generator,
            settings.llm_hypothesis_mode,
        )

        return decision
    finally:
        reset_dynamic_scores(token)


async def _fetch_dxy_history(api_key: str, limit: int = 10) -> list[dict]:
    """Récupère les N derniers points du DXY (DTWEXBGS) depuis FRED."""
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                FRED_OBS_URL,
                params={
                    "series_id": DXY_SERIES_ID,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": limit,
                },
            )
            r.raise_for_status()
            return r.json().get("observations", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("swing.gold.dxy_fetch_error", error=str(exc))
        return []


def _compute_dxy_bias(history: list[dict]) -> tuple[float, str, float, float] | None:
    """Variation % du DXY sur ~5 jours ouvrés et bias contrarian sur GOLD.

    Corrélation négative classique : DXY ↑ → GOLD ↓ (bias bear sur GOLD).
    Retourne (bias, zone, valeur_recente, valeur_passee) ou None si données insuffisantes.
    """
    valid_values: list[float] = []
    for obs in history:
        v = obs.get("value")
        if v in (".", "", None):
            continue
        try:
            valid_values.append(float(v))
        except (TypeError, ValueError):
            continue

    if len(valid_values) < 5:
        return None

    recent = valid_values[0]
    past_idx = min(5, len(valid_values) - 1)
    past = valid_values[past_idx]
    if past == 0:
        return None
    var_pct = (recent - past) / past * 100

    if var_pct >= 1.0:
        return -1.0, "dxy_strong_up", recent, past
    if var_pct >= 0.3:
        return -0.5, "dxy_up", recent, past
    if var_pct <= -1.0:
        return 1.0, "dxy_strong_down", recent, past
    if var_pct <= -0.3:
        return 0.5, "dxy_down", recent, past
    return 0.0, "dxy_stable", recent, past


def _enrich_with_dxy(decision: SwingDecision, history: list[dict]) -> float | None:
    """Ajoute evidence + trigger DXY à la décision, retourne le bias contrarian.

    NE set PAS la veracity — responsabilité du caller pour combiner plusieurs sources.
    Retourne None si la donnée DXY est insuffisante.
    """
    result = _compute_dxy_bias(history)
    if result is None:
        return None
    bias, zone, recent, past = result
    var_pct = (recent - past) / past * 100

    bias_label = (
        "contrarian bull GOLD" if bias > 0
        else "contrarian bear GOLD" if bias < 0
        else "neutral"
    )

    decision.evidence.append(
        {
            "source": "fred_dtwexbgs",
            "score": get_effective_score("fred_dtwexbgs", SOURCE_SCORES),
            "fact": f"DXY={recent:.2f} (var 5d {var_pct:+.2f}%)",
        }
    )
    decision.triggers.append(
        {
            "type": "dxy_correlation",
            "value": f"DXY {zone} ({var_pct:+.2f}%) → {bias_label}",
            "weight": 0.10,
        }
    )
    return bias


async def _read_cot(redis: Redis) -> dict | None:
    raw = await redis.get(COT_REDIS_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _compute_cot_bias(net_pct: float) -> tuple[float, str]:
    """Mappe un net_pct Managed Money (-1..+1) à un bias contrarian sur GOLD.

    Lecture contrarian classique du COT : positions surchargées d'un côté
    signalent un risque de retournement (foule trop unanime → smart money
    sortira). Symétrique pour les deux extrêmes.

    -1 = MM extrêmement net long (foule bullish) → contrarian SHORT bias.
    +1 = MM extrêmement net short (foule bearish) → contrarian LONG bias.
    """
    if net_pct >= 0.7:
        return -1.0, "mm_extreme_long"
    if net_pct >= 0.4:
        return -0.5, "mm_net_long"
    if net_pct <= -0.7:
        return 1.0, "mm_extreme_short"
    if net_pct <= -0.4:
        return 0.5, "mm_net_short"
    return 0.0, "mm_balanced"


def _enrich_with_cot(decision: SwingDecision, cot: dict) -> float | None:
    """Ajoute evidence + trigger COT à la décision, retourne le bias contrarian.

    NE set PAS la veracity — responsabilité du caller pour combiner plusieurs sources.
    Retourne None si la donnée COT est invalide ou incomplète.
    """
    try:
        mm_long = int(cot["mm_long"])
        mm_short = int(cot["mm_short"])
        net_pct = float(cot["mm_net_pct"])
        report_date = str(cot.get("report_date", "unknown"))
    except (KeyError, TypeError, ValueError):
        return None

    bias, zone = _compute_cot_bias(net_pct)
    bias_label = (
        "contrarian bull GOLD" if bias > 0
        else "contrarian bear GOLD" if bias < 0
        else "neutral"
    )

    decision.evidence.append(
        {
            "source": "cftc_cot",
            "score": get_effective_score("cftc_cot", SOURCE_SCORES),
            "fact": (
                f"COT MM long={mm_long} short={mm_short} "
                f"(net {net_pct:+.2f}, report {report_date[:10]})"
            ),
        }
    )
    decision.triggers.append(
        {
            "type": "cot_positioning",
            "value": f"COT {zone} (net {net_pct:+.2f}) → {bias_label}",
            "weight": 0.10,
        }
    )
    return bias


async def _read_gdelt(redis: Redis, entity_id: str) -> dict | None:
    raw = await redis.get(GDELT_REDIS_KEY_TPL.format(entity=entity_id.lower()))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def _compute_gdelt_bias(tone: float) -> tuple[float, str]:
    """Mappe le tone GDELT [-10, +10] à un bias contrarian sur GOLD.

    Tone négatif = tensions globales (guerre, crises, sanctions, banques en
    faillite) = rotation safe haven = **bull GOLD**. Cohérent avec FG sur
    BTC mais inversé : tone GDELT ≈ « global mood very negative » →
    GOLD bull, similaire à FG faible → BTC bull contrarian.

    Calibration provisoire des seuils ±1, ±3 issus de la littérature
    GDELT (cf. ADR-010), à réévaluer Session 4 après dataset golden.
    """
    if tone <= -3.0:
        return 1.0, "tensions_extreme"
    if tone <= -1.0:
        return 0.5, "tensions_moderate"
    if tone >= 3.0:
        return -1.0, "euphoria"
    if tone >= 1.0:
        return -0.5, "optimism"
    return 0.0, "neutral_climate"


def _enrich_with_gdelt(decision: SwingDecision, gd: dict) -> float | None:
    """Ajoute evidence + trigger GDELT, retourne le bias contrarian.

    NE set PAS la veracity — responsabilité du caller pour combiner plusieurs sources.
    Retourne None si le payload GDELT est invalide ou incomplet.
    """
    try:
        tone = float(gd["tone"])
        n_points = int(gd.get("n_points", 0))
        timespan = str(gd.get("timespan", "?"))
    except (KeyError, TypeError, ValueError):
        return None

    bias, zone = _compute_gdelt_bias(tone)
    bias_label = (
        "contrarian bull GOLD" if bias > 0
        else "contrarian bear GOLD" if bias < 0
        else "neutral"
    )

    decision.evidence.append(
        {
            "source": "gdelt_news",
            "score": get_effective_score("gdelt_news", SOURCE_SCORES),
            "fact": (
                f"GDELT tone={tone:+.2f} (zone={zone}, "
                f"agg {n_points} pts / {timespan})"
            ),
        }
    )
    decision.triggers.append(
        {
            "type": "gdelt_tone",
            "value": f"GDELT {zone} (tone={tone:+.2f}) → {bias_label}",
            "weight": 0.10,
        }
    )
    return bias


async def analyze_swing_gold(
    fred_api_key: str | None = None,
    redis: Redis | None = None,
    hypothesis_generator: HypothesisGenerator | None = None,
) -> SwingDecision:
    """Analyse swing Gold (GC=F) sur 1h/60d, avec overlays multi-sources.

    Overlays par défaut (cf. ADR-004 / ADR-008 / ADR-010) :
    - Google News GOLD (Redis, trend-following) : sentiment éditorial mainstream
    - GDELT tone (Redis, contrarian) : NLP scientifique mondial, capte les
      tensions globales / climat éditorial macro / dimension géopolitique
      que les autres overlays ne couvrent pas. **Méthode non-LLM**, premier
      overlay Tik à diversification méthodologique pure (cf. ADR-010).

    Overlays opt-in via `settings.gold_dxy_cot_overlays_enabled` (défaut False) :
    - DXY (FRED, contrarian) : corrélation négative GOLD/USD
    - CFTC COT Managed Money (Redis, contrarian) : positioning institutionnel

    Désactivés par défaut suite au backtest empirique 12m du 2026-05-07
    (P2 plan stratégique fiabilité, ADR-018 amendement) qui a mesuré les
    deux contrarian inversés (DXY IC +0.23 à 120h, COT IC +0.43 à 720h).
    À réactiver post-J+30 après mesure sur période bear gold pour
    confirmer si l'inversion est régime-spécifique 2025-2026.

    La veracity finale est calculée sur la moyenne des biais disponibles —
    même architecture que analyze_swing_btc, prête à accueillir d'autres
    sources GOLD plus tard (on-chain miners, ETF flows, etc.).

    Pas d'overlay Fear & Greed : l'index FG est crypto-spécifique.

    Si `hypothesis_generator` est fourni, génère une hypothèse contextuelle
    via LLM après la cross-validation (cf. ADR-012).
    """
    df = await _fetch_yahoo_klines("GC=F", "1h", "60d")
    df.attrs["entity_id"] = "GOLD"
    df.attrs["source"] = "yahoo_finance"
    decision = _score_indicators(df)
    decision.entity_id = "GOLD"

    settings = get_settings()

    # Précharge les scores dynamiques (override Redis sur SOURCE_SCORES) — ADR-011
    dynamic_scores = await preload_source_scores(
        redis,
        ["fred_dtwexbgs", "cftc_cot", "google_news_rss", "gdelt_news"],
    )
    token = set_dynamic_scores(dynamic_scores)
    try:
        biases_by_source: dict[str, float] = {}

        # ADR-018 amendement P2 : DXY et COT contrarian mesurés inversés sur
        # 12m 2025-2026 (DXY IC +0.23 / COT IC +0.43, signes opposés
        # contrarian attendu). Désactivés par défaut via settings, à
        # réactiver post-J+30 sur période bear.
        if fred_api_key and settings.gold_dxy_cot_overlays_enabled:
            history = await _fetch_dxy_history(fred_api_key)
            if history:
                bias = _enrich_with_dxy(decision, history)
                if bias is not None:
                    biases_by_source["fred_dtwexbgs"] = bias
            else:
                log.info("swing.gold.dxy_unavailable")
        elif fred_api_key:
            log.info("swing.gold.dxy_skipped_overlay_disabled")

        if redis is not None:
            if settings.gold_dxy_cot_overlays_enabled:
                cot = await _read_cot(redis)
                if cot is not None:
                    bias = _enrich_with_cot(decision, cot)
                    if bias is not None:
                        biases_by_source["cftc_cot"] = bias
                else:
                    log.info("swing.gold.cot_unavailable")
            else:
                log.info("swing.gold.cot_skipped_overlay_disabled")

            gn = await _read_google_news(redis, entity_id="GOLD")
            if gn is not None:
                bias = _enrich_with_google_news(decision, gn)
                if bias is not None:
                    biases_by_source["google_news_rss"] = bias
            else:
                log.info("swing.gold.google_news_unavailable")

            gd = await _read_gdelt(redis, entity_id="GOLD")
            if gd is not None:
                bias = _enrich_with_gdelt(decision, gd)
                if bias is not None:
                    biases_by_source["gdelt_news"] = bias
            else:
                log.info("swing.gold.gdelt_unavailable")

        if biases_by_source:
            cv = apply_cross_validation_to_decision(
                decision, biases_by_source, mode=settings.antifakenews_mode
            )
            # ADR-018 — Tik OSINT pure : direction et confidence dérivées
            # du combined_bias OSINT (pas de l'analyse technique).
            _derive_osint_decision(decision, cv.combined_bias)
            # Veracity dérivée de la dispersion des sources OSINT.
            decision.veracity = _veracity_from_dispersion(cv.dispersion)
            if cv.circuit_breaker_status != "ok":
                log.info(
                    "anti_fake_news.flagged",
                    entity_id=decision.entity_id,
                    horizon="swing",
                    status=cv.circuit_breaker_status,
                    outliers=list(cv.outlier_sources),
                    method=cv.method,
                    mode=settings.antifakenews_mode,
                )

        # Génération hypothèse contextuelle LLM (post-enrichissements + post-CV)
        await apply_llm_hypothesis(
            decision, "swing", hypothesis_generator,
            settings.llm_hypothesis_mode,
        )

        return decision
    finally:
        reset_dynamic_scores(token)
