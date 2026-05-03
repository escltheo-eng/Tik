"""Scoring source dynamique (anti fake-news, ADR-011).

Maintient un score de crédibilité ajusté par source, recalibré quotidiennement
selon le hit rate des signaux Tik récents vs le marché réel.

**Architecture** :

- **Redis** : `tik.source_credibility.<source>` (TTL 8j) — lecture rapide à
  chaque cycle de calcul, fallback `SOURCE_SCORES` statique si miss.
- **Postgres** : table `source_credibility_history` — 1 row par source par
  cycle de recalibration, pour audit et compréhension de la dérive.
- **Job APScheduler** : `recalibrate_sources` quotidien à 03:00 UTC.

**Algorithme d'ajustement** asymétrique (paranoïa contrôlée — pénalité
plus rapide que récompense) :

- hit rate < 40 % sur ≥30 samples → score ÷ 1.2 (penalty)
- 40 % ≤ hit rate ≤ 70 % → score inchangé
- hit rate > 70 % sur ≥30 samples → score × 1.1 (reward)
- < 30 samples → score inchangé (statistique trop faible)

Cap final : `[0.30, 0.95]` — borne basse évite l'effondrement total d'une
source temporairement maladroite, borne haute évite la sur-confiance qui
masquerait une dérive future.

Voir docs/adr/011-anti-fake-news.md pour le contexte architectural.
"""

from __future__ import annotations

import asyncio
import contextvars
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.storage.models import Signal, SourceCredibilityHistory

# Note : pas d'import top-level de SOURCE_SCORES depuis swing_engine pour éviter
# le cycle (swing_engine importe set_dynamic_scores/get_effective_score d'ici).
# Le fallback statique est résolu via lazy import dans `_get_static_fallback`.

log = structlog.get_logger()

# ----- Constantes -----

REDIS_KEY_TPL = "tik.source_credibility.{source}"
SCORE_TTL_SEC = 8 * 86400        # 8 jours (>1 cycle daily, robustesse)
MIN_SCORE = 0.30
MAX_SCORE = 0.95

# Seuils d'ajustement
PENALTY_THRESHOLD = 0.40         # hit rate < 40% → pénalité
REWARD_THRESHOLD = 0.70          # hit rate > 70% → récompense
PENALTY_FACTOR = 1.2             # score ÷ 1.2
REWARD_FACTOR = 1.1              # score × 1.1
MIN_SAMPLES = 30                 # samples minimum pour ajuster
LOOKBACK_DAYS = 30
HORIZON_DAYS = 5                 # sweet spot identifié par le backtest existant
THRESHOLD_PCT = 0.5

# Sources qui peuvent être recalibrées (sentiment / overlays / positioning).
# On exclut volontairement les sources de prix de marché elles-mêmes
# (binance_klines, yahoo_finance, binance_klines_1m) — leur "crédibilité"
# n'a pas de sens dans ce contexte, ce sont les inputs techniques.
RECALIBRATABLE_SOURCES: frozenset[str] = frozenset({
    "alternative_me_fng",
    "cryptocompare_news",
    "google_news_rss",
    "reddit_btc",
    "gdelt_news",
    "fred_dtwexbgs",
    "cftc_cot",
    "binance_orderbook",
    "binance_aggtrades",
})


# ----- Context-var pour propager les scores dynamiques aux _enrich_with_<source> -----

_dynamic_scores_ctx: contextvars.ContextVar[dict[str, float] | None] = contextvars.ContextVar(
    "tik_dynamic_scores", default=None
)


def get_effective_score(source: str, fallback: dict[str, float]) -> float:
    """Score effectif d'une source.

    Si un dict de scores dynamiques est actif dans le context (set via
    `set_dynamic_scores`), le retourne. Sinon, fallback sur le dict statique
    fourni (typiquement `SOURCE_SCORES` ou `FLASH_SOURCE_SCORES`).

    Permet aux helpers `_enrich_with_<source>` de rester sync sans changer
    leur signature : c'est le caller (analyze_swing_btc/gold, analyze_flash_btc)
    qui définit le context au début de son exécution.
    """
    dyn = _dynamic_scores_ctx.get()
    if dyn is not None and source in dyn:
        return dyn[source]
    return fallback.get(source, 0.5)


def set_dynamic_scores(scores: dict[str, float] | None) -> contextvars.Token:
    """Active un dict de scores dynamiques pour le context courant. Retourne le token de reset."""
    return _dynamic_scores_ctx.set(scores)


def reset_dynamic_scores(token: contextvars.Token) -> None:
    """Restaure le context précédent (cleanup à appeler dans un finally)."""
    _dynamic_scores_ctx.reset(token)


@dataclass
class RecalibrationResult:
    """Résultat de la recalibration pour une source."""

    source: str
    previous_score: float
    new_score: float
    hit_rate: float | None
    samples: int
    adjustment: str   # "unchanged" | "penalty" | "reward"


# ----- Logique pure : ajustement -----

def _compute_adjustment(
    current_score: float,
    hit_rate: float,
    samples: int,
) -> tuple[float, str]:
    """Calcule le nouveau score et le type d'ajustement.

    Pure logic — testable sans Redis/DB.

    Retourne (new_score, kind) où kind ∈ {"unchanged", "penalty", "reward"}.
    Asymétrique : pénalité (÷1.2) plus rapide que récompense (×1.1) — cohérent
    avec la philosophie "paranoïa contrôlée" du projet.
    """
    if samples < MIN_SAMPLES:
        return current_score, "unchanged"
    if hit_rate < PENALTY_THRESHOLD:
        new_score = max(MIN_SCORE, current_score / PENALTY_FACTOR)
        return round(new_score, 4), "penalty"
    if hit_rate > REWARD_THRESHOLD:
        new_score = min(MAX_SCORE, current_score * REWARD_FACTOR)
        return round(new_score, 4), "reward"
    return current_score, "unchanged"


def _capped(score: float) -> float:
    """Borne le score dans [MIN_SCORE, MAX_SCORE]."""
    return max(MIN_SCORE, min(MAX_SCORE, score))


# ----- Lecture / écriture Redis -----

def _get_static_fallback(source: str) -> float:
    """Lazy lookup de SOURCE_SCORES pour éviter le cycle d'import.

    Utilisé uniquement comme fallback (Redis miss). Au moment où ce code
    s'exécute, `swing_engine` est déjà importé.
    """
    from tik_core.scoring.swing_engine import SOURCE_SCORES
    return SOURCE_SCORES.get(source, 0.5)


async def get_source_score(redis: Redis | None, source: str) -> float | None:
    """Score dynamique d'une source depuis Redis.

    Retourne le score si présent dans `tik.source_credibility.<source>`,
    `None` si miss ou Redis indisponible. Le fallback statique est
    responsabilité du caller (cf. `get_effective_score`).
    """
    if redis is None:
        return None
    try:
        raw = await redis.get(REDIS_KEY_TPL.format(source=source))
        if raw is not None:
            return float(raw)
    except (ValueError, TypeError) as exc:
        log.warning(
            "source_credibility.redis_read_invalid",
            source=source,
            error=str(exc),
        )
    return None


async def set_source_score(
    redis: Redis,
    source: str,
    score: float,
    ttl_sec: int = SCORE_TTL_SEC,
) -> float:
    """Écrit le score (capé) dans Redis avec TTL.

    Retourne le score effectivement écrit (après cap).
    """
    capped = _capped(score)
    await redis.setex(
        REDIS_KEY_TPL.format(source=source),
        ttl_sec,
        f"{capped:.4f}",
    )
    return capped


async def preload_source_scores(
    redis: Redis | None,
    sources: list[str],
) -> dict[str, float]:
    """Précharge les scores Redis pour un set de sources.

    Retourne un dict ne contenant QUE les sources effectivement présentes
    en Redis. Les sources absentes ne sont pas dans le dict — c'est le rôle
    de `get_effective_score` (via context-var) de gérer le fallback statique.
    """
    if redis is None:
        return {}
    result: dict[str, float] = {}
    for s in sources:
        score = await get_source_score(redis, s)
        if score is not None:
            result[s] = score
    return result


# ----- Calcul des hit rates par source (réutilise la logique backtest) -----

async def _fetch_histories() -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Fetch BTC + GOLD history en parallèle, via la logique du backtest existant."""
    from tik_core.scripts.backtest import fetch_btc_history, fetch_gold_history

    async with httpx.AsyncClient(timeout=30.0) as client:
        return await asyncio.gather(
            fetch_btc_history(client),
            fetch_gold_history(client),
        )


def _compute_hit_rates_by_source(
    signals: list[Signal],
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
    horizon_days: int = HORIZON_DAYS,
    threshold_pct: float = THRESHOLD_PCT,
) -> dict[str, tuple[int, int]]:
    """Pour chaque source mentionnée dans evidence, agrège (n_success, n_total).

    Pure logic — testable avec des Signal objects construits à la main.

    Note : le succès/échec est attribué au signal entier, donc à TOUTES les
    sources qui ont contribué (apparaissant dans evidence). C'est une
    approximation de premier ordre — une attribution plus fine demanderait
    des feedbacks granulaires (à venir quand Zeta enverra du POST /feedback).
    """
    from tik_core.scripts.backtest import find_closest_price, _success_for

    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [n_success, n_total]

    for sig in signals:
        if sig.entity_id == "BTC":
            history = btc_history
        elif sig.entity_id == "GOLD":
            history = gold_history
        else:
            continue

        ts0 = sig.timestamp
        ts1 = ts0 + timedelta(days=horizon_days)
        p0 = find_closest_price(history, ts0)
        p1 = find_closest_price(history, ts1)
        if p0 is None or p1 is None or p0 == 0:
            continue

        delta_pct = (p1 - p0) / p0 * 100
        success = _success_for(sig.direction, delta_pct, threshold_pct)

        sources_in_signal = {
            ev.get("source")
            for ev in (sig.evidence or [])
            if ev.get("source") in RECALIBRATABLE_SOURCES
        }
        for source in sources_in_signal:
            counts[source][1] += 1
            if success:
                counts[source][0] += 1

    return {source: (s[0], s[1]) for source, s in counts.items()}


# ----- Job orchestration -----

async def recalibrate_source(
    redis: Redis,
    session: AsyncSession,
    source: str,
    n_success: int,
    n_total: int,
    lookback_days: int = LOOKBACK_DAYS,
) -> RecalibrationResult:
    """Recalibre une source : calcule le nouveau score, persiste DB + Redis."""
    previous_dynamic = await get_source_score(redis, source)
    previous = previous_dynamic if previous_dynamic is not None else _get_static_fallback(source)
    hit_rate = (n_success / n_total) if n_total > 0 else 0.0
    new_score, kind = _compute_adjustment(previous, hit_rate, n_total)

    if new_score != previous:
        await set_source_score(redis, source, new_score)

    history_row = SourceCredibilityHistory(
        source=source,
        score=new_score,
        previous_score=previous,
        hit_rate=hit_rate if n_total > 0 else None,
        samples=n_total,
        lookback_days=lookback_days,
        adjustment=kind,
    )
    session.add(history_row)

    return RecalibrationResult(
        source=source,
        previous_score=previous,
        new_score=new_score,
        hit_rate=hit_rate if n_total > 0 else None,
        samples=n_total,
        adjustment=kind,
    )


async def recalibrate_sources(
    session_maker: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> list[RecalibrationResult]:
    """Job batch quotidien — recalibre toutes les sources via leur hit rate récent.

    Étapes :
    1. Charge les signaux des LOOKBACK_DAYS derniers jours, déjà mûrs (>HORIZON_DAYS).
    2. Fetch BTC + GOLD price histories pour calculer les deltas marché.
    3. Pour chaque source RECALIBRATABLE_SOURCES, agrège (n_success, n_total).
    4. Calcule l'ajustement asymétrique (penalty/reward/unchanged).
    5. Persiste en Redis (lecture runtime) + DB (audit).
    """
    cutoff_lookback = datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)
    cutoff_horizon = datetime.utcnow() - timedelta(days=HORIZON_DAYS)

    log.info("source_credibility.recalibrate.start", lookback_days=LOOKBACK_DAYS)

    async with session_maker() as session:
        result = await session.execute(
            select(Signal).where(
                Signal.timestamp >= cutoff_lookback,
                Signal.timestamp < cutoff_horizon,
            )
        )
        signals = list(result.scalars().all())

    log.info("source_credibility.recalibrate.signals_loaded", n=len(signals))

    if not signals:
        log.info("source_credibility.recalibrate.no_signals_skip")
        return []

    btc_history, gold_history = await _fetch_histories()
    hit_rates = _compute_hit_rates_by_source(signals, btc_history, gold_history)

    results: list[RecalibrationResult] = []
    async with session_maker() as session:
        for source in RECALIBRATABLE_SOURCES:
            n_success, n_total = hit_rates.get(source, (0, 0))
            res = await recalibrate_source(
                redis, session, source, n_success, n_total
            )
            results.append(res)
            log.info(
                "source_credibility.recalibrate.source",
                source=res.source,
                previous=res.previous_score,
                new=res.new_score,
                hit_rate=res.hit_rate,
                samples=res.samples,
                adjustment=res.adjustment,
            )
        await session.commit()

    log.info("source_credibility.recalibrate.done", n_sources=len(results))
    return results
