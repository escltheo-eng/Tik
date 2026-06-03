"""Endpoint dérivés Binance : positionnement (SHADOW — contexte, ADR-023).

Lit le snapshot Redis publié par le `BinanceDerivativesIngester` pour une entité
(`tik.deriv.binance.{entity}`) et le retourne tel quel : funding rate, open
interest, ratios long/short retail + top traders. C'est du **contexte de marché**
(argent + levier engagés), PAS un signal directionnel Tik (SHADOW STRICT ADR-023 :
aucun overlay branché, aucune influence sur les signaux).

Si aucun snapshot n'est présent (ingester pas encore passé, ou entité non
collectée — seul BTC l'est aujourd'hui), retourne un snapshot vide — pas d'erreur.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.storage.schemas import DerivativesSnapshotOut

log = structlog.get_logger()

router = APIRouter(prefix="/derivatives")

REDIS_KEY_TPL = "tik.deriv.binance.{entity}"


def _empty_snapshot(entity_id: str) -> DerivativesSnapshotOut:
    return DerivativesSnapshotOut(entity=entity_id.upper(), fetched_at=None)


@router.get("/{entity_id}", response_model=DerivativesSnapshotOut)
async def get_derivatives(
    entity_id: str,
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> DerivativesSnapshotOut:
    """Retourne le snapshot positionnement dérivés courant pour une entité (BTC).

    Snapshot vide si l'ingester n'a pas encore publié pour cette entité.
    """
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = REDIS_KEY_TPL.format(entity=entity_id.lower())
        try:
            raw = await redis.get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("derivatives.api.redis_error", entity_id=entity_id, error=str(exc))
            return _empty_snapshot(entity_id)
        if not raw:
            return _empty_snapshot(entity_id)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("derivatives.api.payload_parse_error", entity_id=entity_id)
            return _empty_snapshot(entity_id)
        if not isinstance(payload, dict):
            return _empty_snapshot(entity_id)
        payload.setdefault("entity", entity_id.upper())
        return DerivativesSnapshotOut(**payload)
    finally:
        await redis.aclose()
