"""Endpoints metrics : hit rate live et autres mesures de performance.

Phase A.2 du plan trading manuel J+10 (cf. `docs/backlog.md` entry n°3).
Mesure la performance des décisions Tik émises sur une fenêtre temporelle
donnée, par horizon × entity. Réutilise la logique de `backtest.py` CLI
(qui reste utilisable indépendamment via `python -m tik_core.scripts.backtest`).

Architecture :
- Logique pure dans `tik_core.metrics.hit_rate` (filtrage + calcul testables
  sans HTTP/DB/Redis).
- Cet endpoint orchestre : lecture DB des signaux, fetch historiques de
  prix Binance/Yahoo, cache Redis du résultat (TTL 15 min).

Garde-fous opérationnels rappelés : Garde-fou 1 inchangé (Tik shadow vs
Zeta 3 mois), ADR-003 inchangé (pas de bypass V01-V15 — endpoint en lecture
seule), ADR-004 multi-overlay inchangé. Aucune modification des engines /
pipeline scoring / cross-validation.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.metrics.freshness import (
    DEFAULT_STALENESS_THRESHOLD_SECONDS,
    compute_signal_freshness,
)
from tik_core.metrics.hit_rate import (
    HORIZON_DEFAULT_THRESHOLD_PCT,
    HORIZON_MEASURE_HOURS,
    compute_hit_rate,
    compute_hit_rate_by_veracity,
    filter_signals_for_horizon,
    make_cache_key,
    make_cache_key_by_veracity,
)
from tik_core.metrics.signal_track_record import compute_track_record
from tik_core.scripts.backtest import fetch_btc_history, fetch_gold_history
from tik_core.storage.database import get_session
from tik_core.storage.models import Signal
from tik_core.storage.schemas import (
    HitRateByVeracityBucket,
    HitRateByVeracityOut,
    HitRateOut,
    SignalFreshnessOut,
    SignalTrackRecordOut,
    TrackRecordRow,
)
from tik_core.utils.time import now_utc, now_utc_naive

log = structlog.get_logger()

router = APIRouter(prefix="/metrics")

# TTL du cache Redis pour le résultat agrégé. 15 minutes : compromis entre
# fraîcheur (les nouveaux signaux apparaissent dans la mesure rapidement) et
# économie de fetch Binance/Yahoo répétés sous charge dashboard.
HIT_RATE_CACHE_TTL_SECONDS = 15 * 60

# TTL du cache Redis pour un track record ENTIÈREMENT résolu : 6h. Les prix
# passés ne changent plus → le résultat est immuable, on peut le garder
# longtemps.
TRACK_RECORD_CACHE_TTL_SECONDS = 6 * 3600

# TTL plancher quand le résultat contient encore des lignes "en_attente"
# (horizons futurs). Évite de marteler Binance/Yahoo si plusieurs lignes
# arrivent à échéance presque en même temps.
TRACK_RECORD_MIN_TTL_SECONDS = 60


def _track_record_cache_ttl(rows_dicts: list[dict], now: datetime) -> int:
    """TTL adaptatif du cache track record.

    Bug historique (Paquet 38) : un TTL fixe de 6h figeait un track record
    calculé alors que le signal était encore frais — toutes ses lignes étaient
    "en_attente" (sabliers) et le restaient 6h, bien au-delà de la fenêtre
    contractuelle (1h pour un flash). Un favori flash ouvert/sondé jeune
    restait donc "tout sablier" 6h, et son auto-résolution ne se débloquait
    jamais (elle tapait le même cache figé).

    Correctif : si une ligne est encore "en_attente", on expire le cache peu
    après que la PROCHAINE ligne devienne disponible (sa cible + petit buffer),
    borné entre TRACK_RECORD_MIN_TTL_SECONDS et TRACK_RECORD_CACHE_TTL_SECONDS.
    Quand tout est résolu → TTL long (6h), le résultat ne bougera plus.
    """
    pending = [r for r in rows_dicts if r["badge"] == "en_attente"]
    if not pending:
        return TRACK_RECORD_CACHE_TTL_SECONDS

    soonest = min(datetime.strptime(r["target_iso"], "%Y-%m-%dT%H:%M:%SZ") for r in pending)
    # +30s : laisse le temps à la bougie de l'horizon d'être fetchable.
    seconds_until = (soonest - now).total_seconds() + 30
    return int(
        max(
            TRACK_RECORD_MIN_TTL_SECONDS,
            min(seconds_until, TRACK_RECORD_CACHE_TTL_SECONDS),
        )
    )


# Paramètres de fetch klines selon l'horizon contractuel du signal (P5 plan
# fiabilité 2026-05-06 — refactor Paquet 12). La granularité s'adapte pour
# que les horizons mesurés (cf. HORIZON_SPECS_BY_SIGNAL_HORIZON) tombent sur
# des klines suffisamment fines.
#   flash → klines 15m × 672 ≈ 7j (mesure 15min/30min/45min/1h — cf. Paquet 17)
#   swing → klines 1h  × 1000 ≈ 41j (mesure 1h/6h/24h/5j — historique)
#   macro → klines 1d  × 365 = 1y  (mesure 1j/7j/30j/90j)
#
# La fenêtre flash a été étendue 2026-05-19 (Paquet 28 fix) de 96 (24h) à
# 672 (7j) car un signal flash émis il y a plus de 24h voyait son row 1h
# "résolu" mais tombait hors fenêtre klines → badge "données_manquantes"
# alors que les rows devraient être correct/raté. 672 reste sous le cap
# Binance limit=1000.
TRACK_RECORD_BINANCE_PARAMS: dict[str, dict] = {
    "flash": {"interval": "15m", "limit": 672},
    "swing": {"interval": "1h", "limit": 1000},
    "macro": {"interval": "1d", "limit": 365},
}
TRACK_RECORD_YAHOO_PARAMS: dict[str, dict] = {
    # Pas de flash GOLD (cf. ADR-005 — Yahoo a 15 min de délai, incompatible
    # avec l'horizon flash). L'endpoint fail-fast HTTP 400 si on tente.
    "swing": {"interval": "1h", "range_param": "60d"},
    "macro": {"interval": "1d", "range_param": "1y"},
}


@router.get("/hit_rate", response_model=HitRateOut)
async def get_hit_rate(
    entity_id: str = Query(
        ..., description="Identifiant entity Tik (ex: BTC, GOLD). Domain-agnostic."
    ),
    horizon: str = Query(
        ...,
        pattern="^(flash|swing|macro)$",
        description="Horizon Tik. flash=mesure 1h, swing=mesure 5j, macro=mesure 30j.",
    ),
    since_days: int = Query(30, ge=1, le=90, description="Fenêtre temporelle en jours (1-90)."),
    threshold_pct: float | None = Query(
        None,
        ge=0.01,
        le=10.0,
        description=(
            "Seuil de variation (%%) pour considérer un signal long/short comme réussi. "
            "Si non fourni, utilise le défaut par horizon (flash=0.3, swing=0.5, macro=1.5)."
        ),
    ),
    include_flagged: bool = Query(
        False,
        description=(
            "Si false (défaut), exclut les signaux flagués anti fake-news "
            "(circuit_breaker_status in {degraded, tripped}). Mesure les signaux "
            "non-flagués uniquement, considérés comme les vraies décisions Tik."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> HitRateOut:
    """Hit rate live des signaux Tik sur la fenêtre temporelle.

    Mesure la performance des décisions Tik en comparant la direction prédite
    au mouvement de prix observé sur l'horizon canonique de chaque signal :
    - flash → mesure du delta prix 1h après émission
    - swing → mesure 5j après (sweet spot validé backtest 2026-04-29)
    - macro → mesure 30j après

    Cache Redis TTL 15 min sur la combinaison
    (entity, horizon, since_days, threshold_pct, include_flagged).

    Limites assumées (cf. backtest.py) :
    - Coûts de transaction non comptés (spread, fees, slippage).
    - Échantillon limité aux signaux émis depuis la mise en service de Tik.
    - Sur fenêtre fortement trending, des baselines naïfs peuvent battre Tik.
    - Yahoo Finance peut retourner des données partielles sur GOLD (skipped).
    """
    effective_threshold = (
        threshold_pct if threshold_pct is not None else HORIZON_DEFAULT_THRESHOLD_PCT[horizon]
    )

    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    cache_key = make_cache_key(
        entity_id=entity_id,
        horizon=horizon,
        since_days=since_days,
        threshold_pct=effective_threshold,
        include_flagged=include_flagged,
    )

    try:
        # Cache lookup
        try:
            cached = await redis.get(cache_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics.hit_rate.cache_read_error", error=str(exc))
            cached = None

        if cached:
            try:
                data = json.loads(cached)
                data["cache_hit"] = True
                return HitRateOut(**data)
            except (TypeError, ValueError, KeyError) as exc:
                log.warning("metrics.hit_rate.cache_parse_error", error=str(exc))

        # Cache miss : recalcule
        now = now_utc_naive()
        cutoff_recent = now - timedelta(days=since_days)
        result = await session.execute(
            select(Signal)
            .where(Signal.timestamp >= cutoff_recent)
            .order_by(Signal.timestamp.desc())
        )
        all_signals = list(result.scalars().all())

        eligible, n_flagged_excluded = filter_signals_for_horizon(
            all_signals,
            horizon=horizon,
            entity_id=entity_id,
            since_days=since_days,
            now=now,
            include_flagged=include_flagged,
        )

        # Fetch history seulement pour l'entity demandée. Si entity inconnue
        # (futur multi-domaines), on saute le fetch et compute_hit_rate
        # retournera 0 évalués.
        btc_history: list[tuple[int, float]] = []
        gold_history: list[tuple[int, float]] = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if entity_id == "BTC":
                    btc_history = await fetch_btc_history(client)
                elif entity_id == "GOLD":
                    gold_history = await fetch_gold_history(client)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "metrics.hit_rate.history_fetch_error",
                entity_id=entity_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Impossible de récupérer l'historique de prix {entity_id} "
                    f"(Binance/Yahoo Finance temporairement indisponible)."
                ),
            ) from exc

        stats = compute_hit_rate(
            eligible,
            horizon=horizon,
            threshold_pct=effective_threshold,
            btc_history=btc_history,
            gold_history=gold_history,
        )

        sample_warning: str | None = None
        if stats["n_evaluated"] == 0:
            sample_warning = "Aucun signal éligible — fenêtre trop courte ou prix indisponibles."
        elif stats["n_evaluated"] < 30:
            sample_warning = (
                f"Échantillon faible ({stats['n_evaluated']} signaux, 30 mini recommandé)."
            )

        out = HitRateOut(
            entity_id=entity_id,
            horizon=horizon,
            since_days=since_days,
            threshold_pct=effective_threshold,
            measure_hours=HORIZON_MEASURE_HOURS[horizon],
            n_total=len(eligible) + n_flagged_excluded,
            n_evaluated=stats["n_evaluated"],
            n_skipped=stats["n_skipped"],
            n_success=stats["n_success"],
            n_flagged_excluded=n_flagged_excluded,
            include_flagged=include_flagged,
            hit_rate=stats["hit_rate"],
            avg_gain_pct=stats["avg_gain_pct"],
            sample_warning=sample_warning,
            computed_at=now_utc(),
            cache_hit=False,
        )

        try:
            await redis.set(
                cache_key,
                out.model_dump_json(),
                ex=HIT_RATE_CACHE_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics.hit_rate.cache_write_error", error=str(exc))

        return out
    finally:
        await redis.aclose()


@router.get("/hit_rate_by_veracity", response_model=HitRateByVeracityOut)
async def get_hit_rate_by_veracity(
    entity_id: str = Query(
        ..., description="Identifiant entity Tik (ex: BTC, GOLD). Domain-agnostic."
    ),
    horizon: str = Query(
        ...,
        pattern="^(flash|swing|macro)$",
        description="Horizon Tik. flash=mesure 1h, swing=mesure 5j, macro=mesure 30j.",
    ),
    since_days: int = Query(30, ge=1, le=90, description="Fenêtre temporelle en jours (1-90)."),
    threshold_pct: float | None = Query(
        None,
        ge=0.01,
        le=10.0,
        description=(
            "Seuil de variation (%%) pour considérer un signal long/short comme réussi. "
            "Si non fourni, utilise le défaut par horizon."
        ),
    ),
    include_flagged: bool = Query(
        False,
        description="Si false (défaut), exclut les signaux flagués anti fake-news.",
    ),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> HitRateByVeracityOut:
    """Hit rate segmenté par tranche de veracity (Phase A.2-bis J+10).

    Insight clé du backtest 2026-05-05 : le hit rate global brut est
    trompeur. Sur 156 signaux 5j, global=24% mais veracity 0.95+=67%.
    Cette mesure rend le filtre veracity exploitable pour calibrer le
    sizing avant un trade manuel.

    Buckets veracity (cohérents `comprendre_tik.md` section 6) :
    0.70-0.79 / 0.80-0.89 / 0.90-0.94 / 0.95-1.00.

    Cache Redis TTL 15 min sur la combinaison
    (entity, horizon, since_days, threshold_pct, include_flagged).

    Limites assumées (en plus de celles de /hit_rate) :
    - Buckets très peu peuplés (N<10) → hit rate volatile, marqué dans
      l'UI par un drapeau "échantillon faible".
    - Période bullish/bearish biaise toujours globalement (même filtre).
    """
    effective_threshold = (
        threshold_pct if threshold_pct is not None else HORIZON_DEFAULT_THRESHOLD_PCT[horizon]
    )

    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    cache_key = make_cache_key_by_veracity(
        entity_id=entity_id,
        horizon=horizon,
        since_days=since_days,
        threshold_pct=effective_threshold,
        include_flagged=include_flagged,
    )

    try:
        try:
            cached = await redis.get(cache_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics.hit_rate_by_veracity.cache_read_error", error=str(exc))
            cached = None

        if cached:
            try:
                data = json.loads(cached)
                data["cache_hit"] = True
                return HitRateByVeracityOut(**data)
            except (TypeError, ValueError, KeyError) as exc:
                log.warning("metrics.hit_rate_by_veracity.cache_parse_error", error=str(exc))

        now = now_utc_naive()
        cutoff_recent = now - timedelta(days=since_days)
        result = await session.execute(
            select(Signal)
            .where(Signal.timestamp >= cutoff_recent)
            .order_by(Signal.timestamp.desc())
        )
        all_signals = list(result.scalars().all())

        eligible, n_flagged_excluded = filter_signals_for_horizon(
            all_signals,
            horizon=horizon,
            entity_id=entity_id,
            since_days=since_days,
            now=now,
            include_flagged=include_flagged,
        )

        btc_history: list[tuple[int, float]] = []
        gold_history: list[tuple[int, float]] = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if entity_id == "BTC":
                    btc_history = await fetch_btc_history(client)
                elif entity_id == "GOLD":
                    gold_history = await fetch_gold_history(client)
        except Exception as exc:  # noqa: BLE001
            log.error(
                "metrics.hit_rate_by_veracity.history_fetch_error",
                entity_id=entity_id,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Impossible de récupérer l'historique de prix {entity_id} "
                    f"(Binance/Yahoo Finance temporairement indisponible)."
                ),
            ) from exc

        bucket_dicts = compute_hit_rate_by_veracity(
            eligible,
            horizon=horizon,
            threshold_pct=effective_threshold,
            btc_history=btc_history,
            gold_history=gold_history,
        )
        buckets = [HitRateByVeracityBucket(**b) for b in bucket_dicts]

        total_evaluated = sum(b.n_evaluated for b in buckets)
        sample_warning: str | None = None
        if total_evaluated == 0:
            sample_warning = "Aucun signal éligible — fenêtre trop courte ou prix indisponibles."
        elif total_evaluated < 30:
            sample_warning = (
                f"Échantillon faible (total {total_evaluated} signaux, 30 mini recommandé)."
            )

        out = HitRateByVeracityOut(
            entity_id=entity_id,
            horizon=horizon,
            since_days=since_days,
            threshold_pct=effective_threshold,
            measure_hours=HORIZON_MEASURE_HOURS[horizon],
            n_total_eligible=len(eligible),
            n_flagged_excluded=n_flagged_excluded,
            include_flagged=include_flagged,
            buckets=buckets,
            sample_warning=sample_warning,
            computed_at=now_utc(),
            cache_hit=False,
        )

        try:
            await redis.set(
                cache_key,
                out.model_dump_json(),
                ex=HIT_RATE_CACHE_TTL_SECONDS,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics.hit_rate_by_veracity.cache_write_error", error=str(exc))

        return out
    finally:
        await redis.aclose()


@router.get("/signal_track_record/{signal_id}", response_model=SignalTrackRecordOut)
async def get_signal_track_record(
    signal_id: str,
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> SignalTrackRecordOut:
    """Track record d'un signal individuel sur 4 horizons adaptés.

    La granularité des horizons mesurés s'adapte à l'horizon contractuel
    du signal (P5 plan fiabilité 2026-05-06 — refactor Paquet 12) :
      flash → 15min / 30min / 45min / 1h
      swing → 1h / 6h / 24h / 5j
      macro → 1j / 7j / 30j / 90j

    Pour chaque horizon, compare la direction prédite au mouvement de prix
    observé et retourne un badge :
    - correct          : direction validée par le marché
    - raté             : direction invalidée
    - en_attente       : horizon dans le futur
    - données_manquantes : historique de prix insuffisant

    Cache Redis à TTL adaptatif (cf. _track_record_cache_ttl) : court tant que
    des horizons sont "en_attente" (recalculé peu après chaque échéance), long
    (6h) une fois tout résolu — les prix passés ne bougent plus.

    Erreurs :
    - 400 : signal flash sur GOLD (cf. ADR-005 — Yahoo 15 min de délai
      incompatible avec l'horizon flash, pas de track record possible).
    - 404 : signal_id introuvable.
    - 503 : historique de prix Binance/Yahoo temporairement indisponible.

    Phase A.3 du plan trading manuel J+10 (cf. docs/backlog.md entry n°3).
    Garde-fous : Garde-fou 1 inchangé, ADR-003 inchangé (lecture seule),
    ADR-004 inchangé, ADR-005 (flash GOLD interdit) renforcé par fail-fast.
    """
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    # Version dans la clé : invalide les caches au déploiement.
    #   v2 : format des rows changé (horizons flash/macro adaptés, Paquet 17).
    #   v3 : fenêtre klines flash étendue 24h → 7j (Paquet 28).
    #   v4 : TTL adaptatif (Paquet 38) — invalide les résultats "tout sablier"
    #        figés 6h par l'ancien TTL fixe.
    cache_key = f"tik.track_record.v4.{signal_id}"

    try:
        try:
            cached = await redis.get(cache_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics.track_record.cache_read_error", error=str(exc))
            cached = None

        if cached:
            try:
                data = json.loads(cached)
                data["cache_hit"] = True
                return SignalTrackRecordOut(**data)
            except (TypeError, ValueError, KeyError) as exc:
                log.warning("metrics.track_record.cache_parse_error", error=str(exc))

        signal = await session.get(Signal, signal_id)
        if signal is None:
            raise HTTPException(status_code=404, detail="Signal not found")

        # Validation de l'horizon (cas DB corrompu : valeurs hors enum).
        if signal.horizon not in TRACK_RECORD_BINANCE_PARAMS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Horizon non supporté pour le track record : {signal.horizon!r}. "
                    "Valeurs attendues : flash, swing, macro."
                ),
            )

        # Fail-fast ADR-005 : pas de track record flash GOLD (Yahoo 15 min
        # de délai → incompatible avec mesure 15min/30min).
        if signal.horizon == "flash" and signal.entity_id == "GOLD":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Track record flash GOLD non disponible (cf. ADR-005). "
                    "Yahoo Finance a 15 min de délai sur GOLD, incompatible avec "
                    "la mesure flash. Pas de signaux flash GOLD émis par Tik."
                ),
            )

        btc_params = TRACK_RECORD_BINANCE_PARAMS[signal.horizon]
        # Yahoo n'a pas de flash → garde le branch sur swing/macro uniquement.
        gold_params = TRACK_RECORD_YAHOO_PARAMS.get(signal.horizon)

        btc_history: list[tuple[int, float]] = []
        gold_history: list[tuple[int, float]] = []
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                if signal.entity_id == "BTC":
                    btc_history = await fetch_btc_history(
                        client,
                        interval=btc_params["interval"],
                        limit=btc_params["limit"],
                    )
                elif signal.entity_id == "GOLD" and gold_params is not None:
                    gold_history = await fetch_gold_history(
                        client,
                        interval=gold_params["interval"],
                        range_param=gold_params["range_param"],
                    )
        except Exception as exc:  # noqa: BLE001
            log.error(
                "metrics.track_record.history_fetch_error",
                entity_id=signal.entity_id,
                horizon=signal.horizon,
                error=str(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"Impossible de récupérer l'historique de prix {signal.entity_id} "
                    "(Binance/Yahoo Finance temporairement indisponible)."
                ),
            ) from exc

        now = now_utc_naive()
        rows_dicts = compute_track_record(
            signal_timestamp=signal.timestamp,
            signal_direction=signal.direction,
            signal_horizon=signal.horizon,
            entity_id=signal.entity_id,
            btc_history=btc_history,
            gold_history=gold_history,
            now=now,
        )
        rows = [TrackRecordRow(**r) for r in rows_dicts]

        out = SignalTrackRecordOut(
            signal_id=signal.id,
            entity_id=signal.entity_id,
            direction=signal.direction,
            horizon=signal.horizon,
            rows=rows,
            computed_at=now_utc(),
            cache_hit=False,
        )

        try:
            await redis.set(
                cache_key,
                out.model_dump_json(),
                ex=_track_record_cache_ttl(rows_dicts, now),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("metrics.track_record.cache_write_error", error=str(exc))

        return out
    finally:
        await redis.aclose()


@router.get("/signal_freshness", response_model=SignalFreshnessOut)
async def get_signal_freshness(
    threshold_seconds: int = Query(
        DEFAULT_STALENESS_THRESHOLD_SECONDS,
        ge=60,
        le=86400,
        description=(
            "Âge (en secondes) au-delà duquel l'absence de signal est jugée "
            "anormale. Défaut 3600 (60 min) — un Tik sain publie un swing BTC "
            "toutes les 15 min."
        ),
    ),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> SignalFreshnessOut:
    """Fraîcheur de la production de signaux — détection de panne silencieuse (M4).

    Lit le timestamp du signal le plus récent (max sur la colonne indexée
    `signals.timestamp`) et le compare à maintenant. `stale=True` = aucun signal
    depuis plus de `threshold_seconds` → le dashboard affiche une bannière rouge.

    Lecture seule, pas de cache (une requête max() indexée est triviale).
    Garde-fou 1 inchangé, ADR-003 inchangé (pas d'action d'exécution).
    """
    result = await session.execute(select(func.max(Signal.timestamp)))
    last_ts = result.scalar_one_or_none()
    fr = compute_signal_freshness(last_ts, now_utc_naive(), threshold_seconds)
    return SignalFreshnessOut(
        last_signal_at=fr.last_signal_at,
        age_seconds=fr.age_seconds,
        stale=fr.stale,
        threshold_seconds=fr.threshold_seconds,
    )
