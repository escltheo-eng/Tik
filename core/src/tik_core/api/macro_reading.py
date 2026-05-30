"""Endpoint /macro_reading — lecture macro éditoriale (SHADOW, lecture seule).

Associe, par type d'event US, DEUX couches clairement distinctes :
  - 🔗 mécanisme ÉDUCATIF curé (savoir général hedgé, `macro_mechanisms`) ;
  - 📊 réaction MESURÉE par Tik (BTC/OR, `measure_macro_reaction`).

Ne touche ni au pipeline, ni aux signaux, ni à l'identité (ADR-018) : pure
couche de présentation/culture. Réaction mesurée mise en cache 24h (historique,
change lentement). Si FRED indispo → mécanisme servi quand même, mesuré=None.

Réversible : retirer `app.include_router(macro_reading.router)` dans main.py +
supprimer ce fichier + `macro_mechanisms.py`. Zéro effet de bord.
"""

from __future__ import annotations

import json

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.aggregator.macro_mechanisms import MECHANISMS, get_mechanism
from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.scripts.backtest import (
    fetch_btc_history,
    fetch_gold_history,
    find_closest_price,
)
from tik_core.scripts.measure_macro_reaction import compute_event_reactions
from tik_core.storage.database import get_session
from tik_core.storage.macro_events_repo import fetch_history, fetch_upcoming
from tik_core.storage.schemas import (
    MacroAssetReaction,
    MacroLiveEvent,
    MacroLiveOut,
    MacroLiveRecent,
    MacroReactionStat,
    MacroReadingOut,
)
from tik_core.utils.time import iso_utc, now_utc_naive

log = structlog.get_logger()

router = APIRouter(prefix="/macro_reading")

CACHE_KEY = "tik.macro_reading.v1"
CACHE_TTL_S = 24 * 3600

# --- Lecture LIVE (se cale sur le calendrier réel) ---
# Cache court : le compte à rebours et le mouvement live changent vite, mais
# on évite de refetch les prix à chaque poll dashboard.
LIVE_CACHE_KEY = "tik.macro_reading.live.v1"
LIVE_CACHE_TTL_S = 180  # 3 min
# Un event "vient de tomber, réagis maintenant" s'il est dans cette fenêtre.
RECENT_WINDOW_H = 48
# On ne surface que les events qui bougent vraiment les marchés.
LIVE_IMPORTANCE = ["HIGH", "MEDIUM"]

# Importance par event curé (FOMC absent de FRED_RELEASES → fallback ici).
_IMPORTANCE = {
    "CPI": "HIGH",
    "NFP": "HIGH",
    "FOMC_MEETING": "HIGH",
    "PPI": "MEDIUM",
    "GDP": "MEDIUM",
}


def _stat(agg: dict | None) -> MacroReactionStat | None:
    """Convertit un agrégat brut {n,median,pct_up,mean_abs} → schéma (arrondi)."""
    if not agg:
        return None
    return MacroReactionStat(
        n=int(agg["n"]),
        median=round(float(agg["median"]), 2),
        pct_up=round(float(agg["pct_up"]), 0),
        mean_abs=round(float(agg["mean_abs"]), 2),
    )


def _asset(asset_aggs: dict | None) -> MacroAssetReaction | None:
    """Mappe {label: agg} (same_day/+1d/+3d) → MacroAssetReaction."""
    if not asset_aggs:
        return None
    out = MacroAssetReaction(
        same_day=_stat(asset_aggs.get("same_day")),
        d1=_stat(asset_aggs.get("+1d")),
        d3=_stat(asset_aggs.get("+3d")),
    )
    if out.same_day is None and out.d1 is None and out.d3 is None:
        return None
    return out


async def _load_reactions() -> dict:
    """Réactions mesurées (cache Redis 24h, sinon recompute). {} si indisponible."""
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        try:
            raw = await redis.get(CACHE_KEY)
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_reading.cache_read_error", error=str(exc))
            raw = None
        if raw:
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                pass
        if not settings.fred_api_key:
            log.warning("macro_reading.no_fred_key")
            return {}
        async with httpx.AsyncClient() as client:
            data = await compute_event_reactions(client, settings.fred_api_key)
        try:
            await redis.setex(CACHE_KEY, CACHE_TTL_S, json.dumps(data))
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_reading.cache_write_error", error=str(exc))
        return data
    finally:
        await redis.aclose()


@router.get("", response_model=list[MacroReadingOut])
async def get_macro_reading(
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> list[MacroReadingOut]:
    """Lectures macro : mécanisme éducatif curé + réaction mesurée BTC/OR par event.

    Réaction mesurée = `null` pour les events sans données (ex. FOMC en v1,
    ou si FRED indisponible) ; le mécanisme éducatif reste servi.
    """
    reactions = await _load_reactions()
    out: list[MacroReadingOut] = []
    for code, mech in MECHANISMS.items():
        r = reactions.get(code)
        assets = r.get("assets") if r else None
        out.append(
            MacroReadingOut(
                event_code=code,
                event_name=(r["event_name"] if r else mech.one_liner),
                importance=(r["importance"] if r else _IMPORTANCE.get(code, "MEDIUM")),
                one_liner=mech.one_liner,
                mechanism=mech.mechanism,
                assets_in_play=list(mech.assets_in_play),
                regime_caveat=mech.regime_caveat,
                n_dates=(int(r["n_dates"]) if r else 0),
                measured_available=bool(r),
                btc=_asset(assets.get("BTC") if assets else None),
                gold=_asset(assets.get("GOLD") if assets else None),
            )
        )
    return out


def _move_since(
    history: list[tuple[int, float]], event_dt, *, max_diff_ms: int
) -> float | None:
    """Variation brute (%) prix(dernier kline) vs prix(à l'heure de l'annonce).

    None si pas d'historique, pas de kline assez proche de l'annonce, ou prix nul.
    BRUT : conflate l'event avec tout le reste — PAS isolé à la surprise.
    """
    if not history:
        return None
    p0 = find_closest_price(history, event_dt, max_diff_ms=max_diff_ms)
    if p0 is None or p0 == 0:
        return None
    last = history[-1][1]
    return round((last - p0) / p0 * 100, 2)


def _live_event(row) -> MacroLiveEvent:
    return MacroLiveEvent(
        event_code=row.event_code,
        event_name=row.event_name,
        importance=row.importance,
        scheduled_for=iso_utc(row.scheduled_for),
        one_liner=get_mechanism(row.event_code).one_liner,
    )


@router.get("/live", response_model=MacroLiveOut)
async def get_macro_reading_live(
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> MacroLiveOut:
    """Lecture macro LIVE : prochain event (compte à rebours) + dernier event
    récent (±48h) avec le mouvement RÉEL BTC/OR depuis l'annonce.

    Réagit à l'actu du calendrier (avant / pendant / après). Le mouvement live
    est BRUT (pas isolé à la surprise — pas de consensus dispo). Contexte, pas
    une prédiction. Cache court (3 min) pour limiter les fetch prix.
    """
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        try:
            raw = await redis.get(LIVE_CACHE_KEY)
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_reading.live_cache_read_error", error=str(exc))
            raw = None
        if raw:
            try:
                return MacroLiveOut.model_validate_json(raw)
            except (TypeError, ValueError):
                pass

        # Prochain event programmé (HIGH/MEDIUM) → compte à rebours.
        upcoming = await fetch_upcoming(
            session, hours=168, importance_filter=LIVE_IMPORTANCE, limit=10
        )
        next_event = _live_event(upcoming[0]) if upcoming else None

        # Dernier event passé dans la fenêtre récente → mouvement live.
        history = await fetch_history(
            session, since_days=3, importance_filter=LIVE_IMPORTANCE, limit=20
        )
        recent_event: MacroLiveRecent | None = None
        if history:
            row = history[0]  # le plus récent (tri DESC)
            age_h = (now_utc_naive() - row.scheduled_for).total_seconds() / 3600
            if 0 <= age_h <= RECENT_WINDOW_H:
                btc_move = gold_move = None
                try:
                    async with httpx.AsyncClient() as client:
                        btc_hist = await fetch_btc_history(client, interval="5m", limit=1000)
                        btc_move = _move_since(
                            btc_hist, row.scheduled_for, max_diff_ms=15 * 60 * 1000
                        )
                        gold_hist = await fetch_gold_history(
                            client, interval="15m", range_param="5d"
                        )
                        gold_move = _move_since(
                            gold_hist, row.scheduled_for, max_diff_ms=45 * 60 * 1000
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("macro_reading.live_price_error", error=str(exc))
                base = _live_event(row)
                recent_event = MacroLiveRecent(
                    **base.model_dump(),
                    btc_move_pct=btc_move,
                    gold_move_pct=gold_move,
                )

        out = MacroLiveOut(
            now=iso_utc(now_utc_naive()),
            next_event=next_event,
            recent_event=recent_event,
        )
        try:
            await redis.setex(LIVE_CACHE_KEY, LIVE_CACHE_TTL_S, out.model_dump_json())
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_reading.live_cache_write_error", error=str(exc))
        return out
    finally:
        await redis.aclose()
