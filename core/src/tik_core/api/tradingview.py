"""Endpoint recommandations techniques TradingView (SHADOW — contexte, ADR-031).

Lit les snapshots Redis publiés par le `TradingViewTAIngester` :
- `GET /api/v1/tradingview/macro` → panier macro-éco (DXY, S&P 500, US 10Y, Or, VIX
  en 1D), depuis `tik.tradingview.macro`.
- `GET /api/v1/tradingview/micro/{entity_id}` → microstructure d'un actif tradé
  (BTC ou GOLD, 5m/15m/1h), depuis `tik.tradingview.micro.{entity}`.

C'est de l'**analyse technique** (note agrégée de l'algo TradingView), du CONTEXTE,
PAS un signal Tik (SHADOW STRICT ADR-031 : aucun overlay branché, aucune influence
sur les signaux). Si aucun snapshot n'est présent (ingester pas encore passé),
retourne un snapshot vide — pas d'erreur.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.storage.schemas import TradingViewSnapshotOut

log = structlog.get_logger()

router = APIRouter(prefix="/tradingview")

REDIS_KEY_MACRO = "tik.tradingview.macro"
REDIS_KEY_MICRO_TPL = "tik.tradingview.micro.{entity}"


async def _read_snapshot(key: str, basket: str, entity: str | None) -> TradingViewSnapshotOut:
    """Lit un snapshot TradingView depuis Redis. Snapshot vide si absent/illisible."""
    empty = TradingViewSnapshotOut(basket=basket, entity=entity, fetched_at=None, items=[])
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        try:
            raw = await redis.get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("tradingview.api.redis_error", key=key, error=str(exc))
            return empty
        if not raw:
            return empty
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("tradingview.api.payload_parse_error", key=key)
            return empty
        if not isinstance(payload, dict):
            return empty
        payload.setdefault("basket", basket)
        if entity is not None:
            payload.setdefault("entity", entity)
        return TradingViewSnapshotOut(**payload)
    finally:
        await redis.aclose()


@router.get("/macro", response_model=TradingViewSnapshotOut)
async def get_tradingview_macro(
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> TradingViewSnapshotOut:
    """Recommandations techniques TradingView du panier macro-éco (1D). Vide si pas publié."""
    return await _read_snapshot(REDIS_KEY_MACRO, basket="macro", entity=None)


@router.get("/micro/{entity_id}", response_model=TradingViewSnapshotOut)
async def get_tradingview_micro(
    entity_id: str,
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> TradingViewSnapshotOut:
    """Recommandations techniques TradingView de la microstructure d'un actif (BTC/GOLD).

    Snapshot vide si l'ingester n'a pas encore publié pour cette entité.
    """
    entity = entity_id.upper()
    key = REDIS_KEY_MICRO_TPL.format(entity=entity_id.lower())
    return await _read_snapshot(key, basket="micro", entity=entity)
