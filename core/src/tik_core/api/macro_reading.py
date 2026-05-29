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

from tik_core.aggregator.macro_mechanisms import MECHANISMS
from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.scripts.measure_macro_reaction import compute_event_reactions
from tik_core.storage.schemas import MacroAssetReaction, MacroReactionStat, MacroReadingOut

log = structlog.get_logger()

router = APIRouter(prefix="/macro_reading")

CACHE_KEY = "tik.macro_reading.v1"
CACHE_TTL_S = 24 * 3600

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
