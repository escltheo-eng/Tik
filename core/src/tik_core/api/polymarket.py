"""Endpoint Polymarket : cotes des marchés prédictifs (SHADOW — contexte).

Lit le snapshot Redis publié par le `PolymarketIngester` pour une entité
(`tik.sentiment.polymarket.{entity}`) et le retourne tel quel : familles de
seuils, proba Yes/No, volumes. C'est du **contexte de marché** (« money on the
line »), PAS un signal directionnel Tik (cf. SHADOW STRICT backlog-osint +
Garde-fou 2-bis : on ne trade pas le GOLD sur les signaux Tik).

Domain-agnostic : `entity_id` est passé tel quel (BTC, GOLD aujourd'hui).
Si aucun snapshot n'est présent (ingester pas encore passé, ou entité non
collectée), retourne un snapshot vide — pas d'erreur.
"""

from __future__ import annotations

import json

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Query

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.storage.schemas import PolymarketSnapshotOut

log = structlog.get_logger()

router = APIRouter(prefix="/polymarket")

REDIS_KEY_TPL = "tik.sentiment.polymarket.{entity}"


def _empty_snapshot(entity_id: str) -> PolymarketSnapshotOut:
    return PolymarketSnapshotOut(entity=entity_id.upper(), fetched_at=None)


def _finalize_payload(payload: dict, entity_id: str, limit: int) -> PolymarketSnapshotOut:
    """Normalise un snapshot Redis brut → PolymarketSnapshotOut (helper pur).

    - Injecte `entity` si absent (rétrocompat BTC pré-2026-05-28).
    - Trie les events par volume total décroissant (plus liquides d'abord).
    - Cap à `limit` events.
    """
    payload = dict(payload)
    payload.setdefault("entity", entity_id.upper())
    events = payload.get("events")
    if isinstance(events, list):
        events = sorted(events, key=lambda e: e.get("total_volume") or 0.0, reverse=True)
        payload["events"] = events[:limit]
    return PolymarketSnapshotOut(**payload)


@router.get("/{entity_id}", response_model=PolymarketSnapshotOut)
async def get_polymarket_markets(
    entity_id: str,
    limit: int = Query(10, ge=1, le=30),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> PolymarketSnapshotOut:
    """Retourne le snapshot Polymarket courant pour une entité (BTC/GOLD).

    - `entity_id` : identifiant entity Tik (`BTC`, `GOLD`). Domain-agnostic.
    - `limit` : nombre max d'events retournés (1-30, défaut 10), triés par
      volume total décroissant (marchés les plus liquides d'abord).

    Snapshot vide si l'ingester n'a pas encore publié pour cette entité.
    """
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        key = REDIS_KEY_TPL.format(entity=entity_id.lower())
        try:
            raw = await redis.get(key)
        except Exception as exc:  # noqa: BLE001
            log.warning("polymarket.api.redis_error", entity_id=entity_id, error=str(exc))
            return _empty_snapshot(entity_id)
        if not raw:
            return _empty_snapshot(entity_id)
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("polymarket.api.payload_parse_error", entity_id=entity_id)
            return _empty_snapshot(entity_id)
        if not isinstance(payload, dict):
            return _empty_snapshot(entity_id)
        return _finalize_payload(payload, entity_id, limit)
    finally:
        await redis.aclose()
