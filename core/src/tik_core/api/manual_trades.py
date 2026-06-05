"""Endpoint carnet de trades manuels — Levier B (2026-06-03).

Journal personnel de la trader : ses *vrais* trades (entrée, sortie, taille
en lots MT5, note) + un snapshot du contexte Tik à l'entrée. Le but est de
rendre l'apport réel de Tik **mesurable** : le bilan décompose le hit rate et
le gain moyen selon que le trade a été pris AVEC Tik, CONTRE, ou SANS signal.

Routes (scopes dédiés `read:trades` / `write:trades`) :
- `POST   /api/v1/trades`              — ouvrir un trade
- `GET    /api/v1/trades`              — lister (filtres status / entity)
- `GET    /api/v1/trades/stats`        — bilan + décomposition par alignement
- `PATCH  /api/v1/trades/{id}/close`   — clôturer (prix de sortie → résultat %)
- `DELETE /api/v1/trades/{id}`         — supprimer

ADR-003 / Garde-fou 1 inchangés : journal humain pur, Tik reste shadow, aucune
influence sur l'exécution. ADR-001 : auth pluggable via require_scope.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.storage.database import get_session
from tik_core.storage.manual_trades_repo import (
    close_trade,
    compute_stats,
    create_trade,
    delete_trade,
    list_trades,
)
from tik_core.storage.schemas import (
    ManualTradeCloseIn,
    ManualTradeIn,
    ManualTradeOut,
    ManualTradeStatsOut,
)

log = structlog.get_logger()

router = APIRouter(prefix="/trades")


@router.post("", response_model=ManualTradeOut, status_code=status.HTTP_201_CREATED)
async def open_trade(
    payload: ManualTradeIn,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scope("write:trades")),
) -> ManualTradeOut:
    """Ouvre un trade manuel. L'alignement vs Tik est calculé côté serveur."""
    trade = await create_trade(
        session,
        entity_id=payload.entity_id,
        direction=payload.direction,
        entry_price=payload.entry_price,
        size_lots=payload.size_lots,
        entry_time=payload.entry_time,
        stop_price=payload.stop_price,
        target_price=payload.target_price,
        note=payload.note,
        tik_signal_id=payload.tik_signal_id,
        tik_direction=payload.tik_direction,
        tik_veracity=payload.tik_veracity,
    )
    log.info(
        "manual_trade.opened",
        trade_id=trade.id,
        client_id=ctx.client_id,
        entity=trade.entity_id,
        direction=trade.direction,
        alignment=trade.tik_alignment,
    )
    return ManualTradeOut.model_validate(trade)


@router.get("", response_model=list[ManualTradeOut])
async def get_trades(
    status_filter: str | None = Query(
        None, alias="status", description="Filtre: open | closed"
    ),
    entity_id: str | None = Query(None, description="Filtre asset: BTC | GOLD"),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:trades")),
) -> list[ManualTradeOut]:
    """Liste les trades (plus récents en tête)."""
    rows = await list_trades(
        session,
        status_filter=status_filter,
        entity_filter=entity_id,
        limit=limit,
    )
    return [ManualTradeOut.model_validate(r) for r in rows]


@router.get("/stats", response_model=ManualTradeStatsOut)
async def get_trade_stats(
    entity_id: str | None = Query(None, description="Filtre asset: BTC | GOLD"),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:trades")),
) -> ManualTradeStatsOut:
    """Bilan du carnet + décomposition par alignement Tik (with/against/none)."""
    rows = await list_trades(session, entity_filter=entity_id, limit=500)
    return ManualTradeStatsOut.model_validate(compute_stats(rows))


@router.patch("/{trade_id}/close", response_model=ManualTradeOut)
async def close_manual_trade(
    trade_id: str,
    payload: ManualTradeCloseIn,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scope("write:trades")),
) -> ManualTradeOut:
    """Clôture un trade : fixe la sortie et calcule le résultat en %."""
    trade = await close_trade(
        session,
        trade_id,
        exit_price=payload.exit_price,
        exit_time=payload.exit_time,
        note=payload.note,
    )
    if trade is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trade introuvable"
        )
    log.info(
        "manual_trade.closed",
        trade_id=trade.id,
        client_id=ctx.client_id,
        result_pct=trade.result_pct,
    )
    return ManualTradeOut.model_validate(trade)


@router.delete("/{trade_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_trade(
    trade_id: str,
    session: AsyncSession = Depends(get_session),
    ctx: AuthContext = Depends(require_scope("write:trades")),
) -> None:
    """Supprime un trade du carnet."""
    deleted = await delete_trade(session, trade_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Trade introuvable"
        )
    log.info("manual_trade.deleted", trade_id=trade_id, client_id=ctx.client_id)
