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
from datetime import timedelta

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.metrics.hit_rate import (
    HORIZON_DEFAULT_THRESHOLD_PCT,
    HORIZON_MEASURE_HOURS,
    compute_hit_rate,
    filter_signals_for_horizon,
    make_cache_key,
)
from tik_core.scripts.backtest import fetch_btc_history, fetch_gold_history
from tik_core.storage.database import get_session
from tik_core.storage.models import Signal
from tik_core.storage.schemas import HitRateOut
from tik_core.utils.time import now_utc, now_utc_naive

log = structlog.get_logger()

router = APIRouter(prefix="/metrics")

# TTL du cache Redis pour le résultat agrégé. 15 minutes : compromis entre
# fraîcheur (les nouveaux signaux apparaissent dans la mesure rapidement) et
# économie de fetch Binance/Yahoo répétés sous charge dashboard.
HIT_RATE_CACHE_TTL_SECONDS = 15 * 60


@router.get("/hit_rate", response_model=HitRateOut)
async def get_hit_rate(
    entity_id: str = Query(..., description="Identifiant entity Tik (ex: BTC, GOLD). Domain-agnostic."),
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
        threshold_pct
        if threshold_pct is not None
        else HORIZON_DEFAULT_THRESHOLD_PCT[horizon]
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
            sample_warning = (
                "Aucun signal éligible — fenêtre trop courte ou prix indisponibles."
            )
        elif stats["n_evaluated"] < 30:
            sample_warning = (
                f"Échantillon faible ({stats['n_evaluated']} signaux, "
                f"30 mini recommandé)."
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
        await redis.close()
