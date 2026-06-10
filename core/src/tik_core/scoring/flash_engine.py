"""Flash engine — horizon minutes-heures (BTC).

Pattern multi-overlay identique au swing engine (ADR-004), adapté au court
terme :
- Klines Binance 1m (240 dernières bougies = 4h glissante)
- EMA 9/21, RSI 14, MACD 12/26/9, ATR 14, momentum 15min
- Overlays REST :
  * Order Book Imbalance (top 20 niveaux du carnet)
  * Buyer/seller agression (1000 derniers aggTrades)
- Check fraîcheur : skip le cycle si `tik.last_price.BTC` > 60s
- Émission conditionnelle : transitions de direction + heartbeat 30 min
- Veracity dynamique via `_veracity_from_concordance` (mêmes paliers que swing)

Voir docs/adr/005-flash-engine.md pour le contexte architectural.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
import pandas as pd
import structlog
from redis.asyncio import Redis

from tik_core.config import get_settings
from tik_core.scoring.cross_validator import (
    apply_cross_validation_to_decision,
    veracity_shadow_fields,
)
from tik_core.scoring.hypothesis_generator import (
    HypothesisGenerator,
    apply_llm_hypothesis,
)
from tik_core.scoring.indicators import atr, ema, macd, median_abs_return_pct, rsi
from tik_core.scoring.source_credibility import (
    get_effective_score,
    preload_source_scores,
    reset_dynamic_scores,
    set_dynamic_scores,
)
from tik_core.utils.time import now_utc

log = structlog.get_logger()

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_DEPTH = "https://api.binance.com/api/v3/depth"
BINANCE_AGG_TRADES = "https://api.binance.com/api/v3/aggTrades"

# Sources spécifiques au flash (klines 1m, carnet, aggTrades). Distincts des
# SOURCE_SCORES du swing pour ne pas mélanger les sémantiques.
FLASH_SOURCE_SCORES: dict[str, float] = {
    "binance_klines_1m": 0.90,
    "binance_orderbook": 0.85,
    "binance_aggtrades": 0.85,
}

LAST_PRICE_KEY = "tik.last_price.BTC"
LAST_DIRECTION_KEY_TPL = "tik.flash.last_direction.{entity_id}"
LAST_DIRECTION_TTL_SEC = 86400  # 24h
HEARTBEAT_INTERVAL = timedelta(minutes=30)
STALE_THRESHOLD_SEC = 60


@dataclass
class FlashDecision:
    """Résultat de l'analyse flash pour une entity.

    ADR-018 — Tik OSINT pure (refactor 2026-05-07) :
    - `direction` est dérivée du `combined_bias` OSINT cross-validé
      (orderbook + aggression flow), pas de l'analyse technique RSI/MACD/EMA
    - `confidence` = magnitude du `combined_bias` ∈ [0, 1] (sémantique uniforme)
    - Sans overlay OSINT disponible : direction = "neutral", confidence = 0
    - Les indicateurs techniques (RSI/MACD/EMA, momentum 15m) restent
      calculés et affichés en `evidence` + `triggers` pour audit, mais
      n'influencent plus la décision directionnelle
    """

    entity_id: str
    timestamp: datetime
    direction: Literal["long", "short", "neutral"]
    confidence: float  # 0..1 — magnitude du combined_bias OSINT (ADR-018)
    hypothesis: str
    veracity: float = 0.85  # ajustée par cross-validation (0..1)
    counter_scenarios: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)
    circuit_breaker_status: str = "ok"  # ok | degraded | tripped (cf. ADR-011)
    advisory: dict = field(default_factory=dict)  # candidates LLM (ADR-012), etc.


@dataclass
class LastEmission:
    """État de la dernière émission flash, lu/écrit dans Redis."""

    direction: str
    timestamp: datetime


# ----- Fetchers REST -----


async def _fetch_klines_1m(symbol: str = "BTCUSDT", limit: int = 240) -> pd.DataFrame:
    """Récupère les klines 1m Binance pour le calcul d'indicateurs flash."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            BINANCE_KLINES,
            params={"symbol": symbol, "interval": "1m", "limit": limit},
        )
        r.raise_for_status()
        raw = r.json()

    df = pd.DataFrame(
        raw,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "_q",
            "_n",
            "_tb_base",
            "_tb_quote",
            "_ignore",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


async def _fetch_orderbook(symbol: str = "BTCUSDT", limit: int = 20) -> dict:
    """Récupère le carnet d'ordres Binance (top N niveaux)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            BINANCE_DEPTH,
            params={"symbol": symbol, "limit": limit},
        )
        r.raise_for_status()
        return r.json()


async def _fetch_agg_trades(symbol: str = "BTCUSDT", limit: int = 1000) -> list[dict]:
    """Récupère les N dernières transactions agrégées Binance (publiques)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            BINANCE_AGG_TRADES,
            params={"symbol": symbol, "limit": limit},
        )
        r.raise_for_status()
        return r.json()


# ----- Check fraîcheur -----


async def is_realtime_data_fresh(redis: Redis, max_age_sec: int = STALE_THRESHOLD_SEC) -> bool:
    """Vérifie que `tik.last_price.BTC` a été mis à jour récemment.

    Si l'ingester WS Binance est down, ce cache est stale → on ne tourne
    pas le flash sur des données potentiellement déconnectées du marché.
    """
    raw = await redis.get(LAST_PRICE_KEY)
    if not raw:
        return False
    try:
        data = json.loads(raw)
        ts = datetime.fromisoformat(data["timestamp"])
    except (KeyError, TypeError, ValueError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    age = (datetime.now(UTC) - ts).total_seconds()
    return age <= max_age_sec


# ----- Scoring technique pur -----


def _compute_technical_evidence_flash(df: pd.DataFrame) -> FlashDecision:
    """Calcule les indicateurs techniques court terme et produit une FlashDecision
    avec evidence + triggers techniques mais SANS direction décisionnelle.

    ADR-018 — Tik OSINT pure (refactor 2026-05-07) :
    - Les indicateurs techniques (RSI 14, EMA 9/21, MACD, ATR, momentum 15m)
      sont calculés et **affichés** en evidence/triggers pour audit
    - Mais ils **n'influencent plus la décision directionnelle**
    - La direction et la confidence sont mises à 0/neutral par défaut, à dériver
      du `combined_bias` OSINT (orderbook + aggression) via
      `_derive_osint_decision_flash()`

    Renommée depuis `_score_flash_indicators()` pour refléter le nouveau rôle.
    """
    if len(df) < 60:
        return FlashDecision(
            entity_id="unknown",
            timestamp=now_utc(),
            direction="neutral",
            confidence=0.0,
            hypothesis="Insufficient historical data for flash analysis",
        )

    close = df["close"]
    rsi_14 = rsi(close, 14)
    ema_9 = ema(close, 9)
    ema_21 = ema(close, 21)
    macd_line, signal_line, hist = macd(close)
    atr_14 = atr(df["high"], df["low"], close, 14)

    last = df.iloc[-1]
    current_price = float(last["close"])
    current_rsi = float(rsi_14.iloc[-1])
    current_ema9 = float(ema_9.iloc[-1])
    current_ema21 = float(ema_21.iloc[-1])
    current_macd = float(macd_line.iloc[-1])
    current_signal = float(signal_line.iloc[-1])
    current_hist = float(hist.iloc[-1])
    prev_hist = float(hist.iloc[-2])
    current_atr = float(atr_14.iloc[-1])

    # Momentum 15m : variation % entre la dernière clôture et la clôture il y a 15 bougies
    momentum_15m_pct = (current_price / float(close.iloc[-15]) - 1.0) * 100.0

    triggers: list[dict] = []
    evidence: list[dict] = []

    # Indicateurs techniques affichés en triggers (informatifs uniquement,
    # plus utilisés pour décider — cf. ADR-018). Weight 0.0 indique qu'ils
    # ne pèsent pas dans la décision OSINT pure.

    # Règle 1 — EMA cross (informatif)
    trend_long = current_ema9 > current_ema21
    trend_short = current_ema9 < current_ema21
    if trend_long:
        triggers.append(
            {"type": "ema_cross", "value": "EMA9 > EMA21 (micro-uptrend)", "weight": 0.0}
        )
    elif trend_short:
        triggers.append(
            {"type": "ema_cross", "value": "EMA9 < EMA21 (micro-downtrend)", "weight": 0.0}
        )

    # Règle 2 — RSI (informatif, seuils 75/25)
    if current_rsi > 75:
        triggers.append(
            {"type": "rsi", "value": f"RSI overbought {current_rsi:.1f}", "weight": 0.0}
        )
    elif current_rsi < 25:
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

    # Règle 4 — Momentum 15min (informatif)
    if momentum_15m_pct > 0.5:
        triggers.append(
            {
                "type": "momentum_15m",
                "value": f"Momentum 15m {momentum_15m_pct:+.2f}% (bull)",
                "weight": 0.0,
            }
        )
    elif momentum_15m_pct < -0.5:
        triggers.append(
            {
                "type": "momentum_15m",
                "value": f"Momentum 15m {momentum_15m_pct:+.2f}% (bear)",
                "weight": 0.0,
            }
        )

    # Evidence technique informative
    source = df.attrs.get("source", "binance_klines_1m")
    evidence.append(
        {
            "source": source,
            "score": FLASH_SOURCE_SCORES.get(source, 0.5),
            "fact": (
                f"RSI14={current_rsi:.1f}, EMA9/21={current_ema9:.2f}/{current_ema21:.2f}, "
                f"MACD={current_macd:.3f}, mom15m={momentum_15m_pct:+.2f}%, ATR={current_atr:.2f}"
            ),
        }
    )

    counter_scenarios = [
        {
            "name": "micro_whipsaw",
            "probability": 0.30,
            "mitigation": "Confirm direction on multi-timeframe (1h confluence)",
        },
        {
            "name": "low_liquidity_spike",
            "probability": 0.15,
            "mitigation": "Check ATR/volume — wide ATR may signal noise rather than trend",
        },
    ]

    # Direction et confidence par défaut neutres — à mettre à jour par
    # `_derive_osint_decision_flash()` après cross-validation des overlays
    # OSINT (orderbook + aggression). Si pas d'OSINT disponible, reste à
    # neutral/0 (cohérent avec ADR-018).
    hypothesis = (
        f"Flash analysis on {df.attrs.get('entity_id', 'entity')} — "
        f"awaiting OSINT cross-validation for direction"
    )

    return FlashDecision(
        entity_id=df.attrs.get("entity_id", "unknown"),
        timestamp=now_utc(),
        direction="neutral",
        confidence=0.0,
        hypothesis=hypothesis,
        counter_scenarios=counter_scenarios,
        evidence=evidence,
        triggers=triggers,
    )


# Alias rétrocompat pour les tests/scripts qui importaient l'ancien nom.
_score_flash_indicators = _compute_technical_evidence_flash


def _derive_osint_decision_flash(
    decision: FlashDecision,
    combined_bias: float,
    threshold: float = 0.30,
) -> None:
    """Met à jour direction et confidence d'une FlashDecision selon le combined_bias OSINT.

    ADR-018 — Tik OSINT pure : direction et conviction dérivées uniquement
    du biais OSINT cross-validé (orderbook + aggression flow), pas de l'analyse
    technique.

    - combined_bias > +threshold → direction = "long"
    - combined_bias < -threshold → direction = "short"
    - sinon → direction = "neutral"

    confidence = abs(combined_bias) ∈ [0, 1]. Mute la decision en place.

    Note : duplication volontaire avec `_derive_osint_decision()` du swing.
    À factoriser dans un module partagé au prochain ajout d'engine
    (cohérent avec le commentaire `_veracity_from_concordance` ligne 326).
    """
    if combined_bias > threshold:
        decision.direction = "long"
    elif combined_bias < -threshold:
        decision.direction = "short"
    else:
        decision.direction = "neutral"

    decision.confidence = round(abs(combined_bias), 3)

    decision.hypothesis = (
        f"Flash {decision.direction} on {decision.entity_id} "
        f"based on OSINT cross-validation (combined_bias={combined_bias:+.2f}, "
        f"|conviction|={decision.confidence:.2f})"
    )


# ----- Veracity (dupliqué du swing pour ce paquet, factoriser au 3e usage) -----


def _veracity_from_concordance(direction: str, bias: float) -> float:
    """[LEGACY ADR-018] Veracity dynamique selon concordance direction technique ↔ bias.

    Conservée pour rétrocompat des tests existants. **Plus utilisée en
    runtime** depuis ADR-018 — utiliser `_veracity_from_dispersion()`.

    Mêmes paliers que le swing pour cohérence inter-horizons :
    concordance +1 → 0.95 ; -1 → 0.70.
    """
    dir_score = {"long": 1.0, "short": -1.0, "neutral": 0.0}[direction]
    concordance = dir_score * bias
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

    ADR-018 — Tik OSINT pure : la veracity mesure l'alignement des sources
    OSINT entre elles, pas la concordance technique vs sentiment.

    Mêmes paliers que swing pour cohérence inter-horizons :
    - dispersion < 0.2 → 0.95
    - dispersion < 0.4 → 0.90
    - dispersion < 0.6 → 0.85
    - dispersion < 0.8 → 0.78
    - dispersion ≥ 0.8 → 0.70

    Note : duplication volontaire avec swing_engine pour ce paquet,
    à factoriser au prochain ajout d'engine (cohérent commentaire
    `_veracity_from_concordance`).
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


# ----- Overlay 1 : Order Book Imbalance -----


def _compute_obi_bias(orderbook: dict) -> tuple[float, str, float] | None:
    """Order Book Imbalance : `(bid_vol - ask_vol) / total_vol` sur top N levels.

    Trend-following : carnet déséquilibré côté acheteurs (OBI > 0) → bias bull.
    """
    try:
        bids = orderbook["bids"]
        asks = orderbook["asks"]
    except (KeyError, TypeError):
        return None

    try:
        bid_vol = sum(float(qty) for _, qty in bids)
        ask_vol = sum(float(qty) for _, qty in asks)
    except (ValueError, TypeError):
        return None

    total = bid_vol + ask_vol
    if total == 0:
        return None

    obi = (bid_vol - ask_vol) / total

    if obi >= 0.4:
        return 1.0, "obi_strong_bid", obi
    if obi >= 0.15:
        return 0.5, "obi_bid", obi
    if obi <= -0.4:
        return -1.0, "obi_strong_ask", obi
    if obi <= -0.15:
        return -0.5, "obi_ask", obi
    return 0.0, "obi_balanced", obi


def _enrich_with_orderbook(decision: FlashDecision, orderbook: dict) -> float | None:
    """Ajoute evidence + trigger OBI à la décision, retourne le bias trend-following.

    NE set PAS la veracity — responsabilité du caller pour combiner plusieurs sources.
    Retourne None si la donnée est invalide ou vide.
    """
    result = _compute_obi_bias(orderbook)
    if result is None:
        return None
    bias, zone, obi = result

    bias_label = "bull" if bias > 0 else "bear" if bias < 0 else "neutral"

    decision.evidence.append(
        {
            "source": "binance_orderbook",
            "score": get_effective_score("binance_orderbook", FLASH_SOURCE_SCORES),
            "fact": f"OBI={obi:+.2f} (top-20 levels)",
        }
    )
    decision.triggers.append(
        {
            "type": "orderbook_imbalance",
            "value": f"{zone} (OBI={obi:+.2f}) → {bias_label}",
            "weight": 0.10,
        }
    )
    return bias


# ----- Overlay 2 : Buyer/seller agression via aggTrades -----


def _compute_aggression_bias(trades: list[dict]) -> tuple[float, str, float] | None:
    """Agression taker : ratio `buy_vol / total_vol` sur les N dernières aggTrades.

    Convention Binance : `m=true` ⇒ le maker était l'acheteur (donc le taker
    était vendeur agressif). `m=false` ⇒ taker acheteur agressif.

    Trend-following : majorité d'acheteurs agressifs (ratio > 0.5) → bias bull.
    """
    if not trades:
        return None

    buy_vol = 0.0
    sell_vol = 0.0
    for t in trades:
        try:
            qty = float(t["q"])
            is_buyer_maker = bool(t["m"])
        except (KeyError, ValueError, TypeError):
            continue
        if is_buyer_maker:
            sell_vol += qty
        else:
            buy_vol += qty

    total = buy_vol + sell_vol
    if total == 0:
        return None

    buy_ratio = buy_vol / total

    if buy_ratio >= 0.65:
        return 1.0, "aggression_strong_bid", buy_ratio
    if buy_ratio >= 0.55:
        return 0.5, "aggression_bid", buy_ratio
    if buy_ratio <= 0.35:
        return -1.0, "aggression_strong_ask", buy_ratio
    if buy_ratio <= 0.45:
        return -0.5, "aggression_ask", buy_ratio
    return 0.0, "aggression_balanced", buy_ratio


def _enrich_with_aggression(decision: FlashDecision, trades: list[dict]) -> float | None:
    """Ajoute evidence + trigger agression à la décision, retourne le bias trend-following."""
    result = _compute_aggression_bias(trades)
    if result is None:
        return None
    bias, zone, buy_ratio = result

    bias_label = "bull" if bias > 0 else "bear" if bias < 0 else "neutral"

    decision.evidence.append(
        {
            "source": "binance_aggtrades",
            "score": get_effective_score("binance_aggtrades", FLASH_SOURCE_SCORES),
            "fact": f"Taker buy_ratio={buy_ratio:.2f} (n={len(trades)} aggTrades)",
        }
    )
    decision.triggers.append(
        {
            "type": "trade_aggression",
            "value": f"{zone} (buy_ratio={buy_ratio:.2f}) → {bias_label}",
            "weight": 0.10,
        }
    )
    return bias


# ----- Émission conditionnelle (transition + heartbeat) -----


async def read_last_emission(redis: Redis, entity_id: str) -> LastEmission | None:
    raw = await redis.get(LAST_DIRECTION_KEY_TPL.format(entity_id=entity_id))
    if not raw:
        return None
    try:
        data = json.loads(raw)
        ts = datetime.fromisoformat(str(data["timestamp"]))
    except (KeyError, TypeError, ValueError):
        return None
    return LastEmission(direction=str(data["direction"]), timestamp=ts)


async def record_emission(redis: Redis, entity_id: str, decision: FlashDecision) -> None:
    payload = {
        "direction": decision.direction,
        "timestamp": decision.timestamp.isoformat(),
    }
    await redis.setex(
        LAST_DIRECTION_KEY_TPL.format(entity_id=entity_id),
        LAST_DIRECTION_TTL_SEC,
        json.dumps(payload),
    )


def should_emit(
    decision: FlashDecision,
    last: LastEmission | None,
    now: datetime,
    heartbeat: timedelta = HEARTBEAT_INTERVAL,
) -> bool:
    """Décide si un signal flash doit être persisté + publié.

    - Pas d'émission précédente : émettre.
    - Transition de direction : émettre.
    - Heartbeat : émettre si > `heartbeat` depuis la dernière émission.
    - Sinon : ne rien émettre (limite le volume DB / pub).
    """
    if last is None:
        return True
    if decision.direction != last.direction:
        return True
    if now - last.timestamp >= heartbeat:
        return True
    return False


# ----- Fonction d'analyse principale -----


async def analyze_flash_btc(
    redis: Redis | None = None,
    hypothesis_generator: HypothesisGenerator | None = None,
) -> FlashDecision:
    """Analyse flash BTC sur klines 1m + overlays REST OBI + agression.

    Si Redis est fourni et que les données temps réel sont stale (>60s),
    retourne une décision neutre `confidence=0` avec hypothesis explicite —
    le scheduler peut alors skip l'émission.

    Si `hypothesis_generator` est fourni et que la décision n'est pas
    skippée pour cause de données stale, génère une hypothèse contextuelle
    via LLM après la cross-validation (cf. ADR-012). Le scheduler appelle
    quand même `should_emit()` après — la génération LLM ne se fait pas
    "pour rien" puisque le coût est négligeable comparé au cycle complet
    et qu'on évite de complexifier l'API en propageant should_emit ici.
    """
    if redis is not None and not await is_realtime_data_fresh(redis):
        log.warning("flash.btc.stale_data_skip")
        return FlashDecision(
            entity_id="BTC",
            timestamp=now_utc(),
            direction="neutral",
            confidence=0.0,
            hypothesis="Realtime feed stale (>60s old) — flash analysis skipped",
        )

    df = await _fetch_klines_1m("BTCUSDT", 240)
    df.attrs["entity_id"] = "BTC"
    df.attrs["source"] = "binance_klines_1m"
    decision = _score_flash_indicators(df)
    decision.entity_id = "BTC"
    # Amplitude attendue (ADR-025) : volatilité réalisée typique sur l'horizon
    # flash (~1 h). Bougies 1m → 1 h = 60 barres. CONTEXTE de volatilité, PAS
    # une prévision du sens (cf. ADR-018 / ADR-025).
    decision.advisory["expected_amplitude_pct"] = median_abs_return_pct(df["close"], 60)
    decision.advisory["ref_price"] = round(float(df["close"].iloc[-1]), 2)

    settings = get_settings()

    # Précharge les scores dynamiques (override Redis sur FLASH_SOURCE_SCORES) — ADR-011
    dynamic_scores = await preload_source_scores(
        redis,
        ["binance_orderbook", "binance_aggtrades"],
    )
    token = set_dynamic_scores(dynamic_scores)
    try:
        biases_by_source: dict[str, float] = {}

        try:
            orderbook = await _fetch_orderbook("BTCUSDT", 20)
            bias = _enrich_with_orderbook(decision, orderbook)
            if bias is not None:
                biases_by_source["binance_orderbook"] = bias
        except Exception as exc:  # noqa: BLE001
            log.info("flash.btc.orderbook_unavailable", error=str(exc))

        try:
            trades = await _fetch_agg_trades("BTCUSDT", 1000)
            bias = _enrich_with_aggression(decision, trades)
            if bias is not None:
                biases_by_source["binance_aggtrades"] = bias
        except Exception as exc:  # noqa: BLE001
            log.info("flash.btc.aggtrades_unavailable", error=str(exc))

        if biases_by_source:
            cv = apply_cross_validation_to_decision(
                decision, biases_by_source, mode=settings.antifakenews_mode
            )
            # ADR-018 — Tik OSINT pure : direction et confidence dérivées
            # du combined_bias OSINT (orderbook + aggression flow), pas de
            # l'analyse technique.
            _derive_osint_decision_flash(decision, cv.combined_bias)
            # Veracity dérivée de la dispersion des sources OSINT
            # (résout bug #2 audit Paquet 17 — veracity neutral figée à 0.85).
            decision.veracity = _veracity_from_dispersion(cv.dispersion)
            # Shadow ADR-026 (Lot 2) : trace dispersion + biais. Observation pure.
            log.info(
                "veracity.shadow",
                horizon="flash",
                **veracity_shadow_fields(decision, cv, biases_by_source),
            )
            if cv.circuit_breaker_status != "ok":
                log.info(
                    "anti_fake_news.flagged",
                    entity_id=decision.entity_id,
                    horizon="flash",
                    status=cv.circuit_breaker_status,
                    outliers=list(cv.outlier_sources),
                    method=cv.method,
                    mode=settings.antifakenews_mode,
                )

        # Génération hypothèse contextuelle LLM (post-enrichissements + post-CV).
        # Le scheduler peut ensuite skip via should_emit() — l'hypothèse LLM
        # est alors perdue, mais le coût est négligeable (~2s/cycle skippé,
        # ~10 min/jour cumulé) face à la simplicité d'avoir une fonction
        # analyze_flash_btc self-contained pour tests / backtests directs.
        await apply_llm_hypothesis(
            decision,
            "flash",
            hypothesis_generator,
            settings.llm_hypothesis_mode,
        )

        return decision
    finally:
        reset_dynamic_scores(token)
