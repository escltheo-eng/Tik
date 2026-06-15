"""Endpoints Macro Regime / Cockpit (ADR-028 — CONTEXTE objectif, lecture seule).

- `GET /api/v1/macro/regime` — blob régime macro objectif (Fed Net Liquidity +
  taux réels + proba récession + pente courbe + conditions financières), publié
  par `MacroRegimeIngester` dans `tik.macro.regime`. Reproduit le *menu de données*
  de centralbank.watch via les sources primaires FRED (gratuites).
- `GET /api/v1/macro/cockpit` — vue agrégée (1 appel) : régime macro + snapshots
  shadow déjà collectés (Fear&Greed, dérivés Binance/DMX, flux ETF, COT or,
  Polymarket) + prochain event macro. Inspiré du « Direction Overview » de
  novex.trading.

⚠️ CONTEXTE STRICT (ADR-028) : 100 % lecture seule. Aucune section ne génère ni
n'influence un signal Tik (pas de combined_bias, pas de veracity, NO-GO intact).
Snapshot vide plutôt qu'erreur si une source n'a pas encore publié.
"""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.storage.database import get_session
from tik_core.storage.macro_events_repo import fetch_upcoming
from tik_core.storage.schemas import MacroCockpitOut, MacroRegimeOut
from tik_core.utils.time import iso_utc

log = structlog.get_logger()

router = APIRouter(prefix="/macro")

REGIME_KEY = "tik.macro.regime"
FEAR_GREED_KEY = "tik.sentiment.fear_greed"
DERIV_KEY = "tik.deriv.binance.btc"
ETF_KEY = "tik.etf.btc"
COT_GOLD_KEY = "tik.macro.cftc_cot.gold"
POLYMARKET_BTC_KEY = "tik.sentiment.polymarket.btc"


async def _read_json(redis: aioredis.Redis, key: str) -> dict | None:
    """Lit une clé Redis JSON. None si absente, vide, illisible ou non-dict."""
    try:
        raw = await redis.get(key)
    except Exception as exc:  # noqa: BLE001
        log.warning("macro.cockpit.redis_error", key=key, error=str(exc))
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        log.warning("macro.cockpit.parse_error", key=key)
        return None
    return payload if isinstance(payload, dict) else None


def _subset(d: dict | None, fields: list[str]) -> dict | None:
    """Sous-ensemble de champs d'un dict (None si dict absent)."""
    if not d:
        return None
    return {f: d.get(f) for f in fields}


def _polymarket_summary(d: dict | None) -> dict | None:
    """Résumé compact du payload Polymarket (le brut est volumineux)."""
    if not d:
        return None
    events = d.get("events") or []
    return {
        "n_events": d.get("n_events"),
        "total_volume": d.get("total_volume"),
        "fetched_at": d.get("fetched_at"),
        "events": [
            {"title": e.get("title"), "end_date": e.get("end_date")}
            for e in events[:3]
        ],
    }


@router.get("/regime", response_model=MacroRegimeOut)
async def get_macro_regime(
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> MacroRegimeOut:
    """Régime macro objectif (Net Liquidity + indicateurs FRED). Vide si pas encore publié."""
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        payload = await _read_json(redis, REGIME_KEY)
        if not payload:
            return MacroRegimeOut(available=False)
        payload.setdefault("available", True)
        return MacroRegimeOut(**payload)
    finally:
        await redis.aclose()


@router.get("/cockpit", response_model=MacroCockpitOut)
async def get_macro_cockpit(
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> MacroCockpitOut:
    """Vue cockpit agrégée : régime macro + snapshots shadow + prochain event macro.

    Chaque section est best-effort (None si absente). LECTURE SEULE, contexte pur.
    """
    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        regime_raw = await _read_json(redis, REGIME_KEY)
        regime = (
            MacroRegimeOut(**{**regime_raw, "available": True})
            if regime_raw
            else MacroRegimeOut(available=False)
        )

        fear_greed = _subset(
            await _read_json(redis, FEAR_GREED_KEY),
            ["value", "classification", "timestamp"],
        )
        derivatives_btc = _subset(
            await _read_json(redis, DERIV_KEY),
            [
                "funding_rate",
                "open_interest_usd",
                "long_short_ratio_global",
                "long_account_global",
                "long_short_ratio_top",
                "long_account_top",
                "fetched_at",
            ],
        )
        etf_flows_btc = _subset(
            await _read_json(redis, ETF_KEY),
            [
                "data_date",
                "daily_net_inflow_usd",
                "cum_net_inflow_usd",
                "total_net_assets_usd",
                "n_funds",
            ],
        )
        cot_gold = _subset(
            await _read_json(redis, COT_GOLD_KEY),
            ["report_date", "mm_net_pct", "change_mm_long", "change_mm_short"],
        )
        polymarket_btc = _polymarket_summary(await _read_json(redis, POLYMARKET_BTC_KEY))

        next_macro_event: dict[str, Any] | None = None
        try:
            rows = await fetch_upcoming(
                session,
                hours=336,
                importance_filter=None,
                asset_filter=None,
                limit=1,
            )
            if rows:
                r = rows[0]
                next_macro_event = {
                    "event_code": r.event_code,
                    "event_name": r.event_name,
                    "scheduled_for": iso_utc(r.scheduled_for),
                    "importance": r.importance,
                }
        except Exception as exc:  # noqa: BLE001
            log.warning("macro.cockpit.next_event_error", error=str(exc))

        return MacroCockpitOut(
            regime=regime,
            fear_greed=fear_greed,
            derivatives_btc=derivatives_btc,
            etf_flows_btc=etf_flows_btc,
            cot_gold=cot_gold,
            polymarket_btc=polymarket_btc,
            next_macro_event=next_macro_event,
        )
    finally:
        await redis.aclose()
