"""Carnet de trades manuels — CRUD + calcul résultat + stats d'alignement Tik.

Levier B du plan « continuer Tik » (2026-06-03). Cf. modèle `ManualTrade`.

Objectif central : rendre l'apport réel de Tik **mesurable**. Chaque trade
porte un snapshot du contexte Tik à l'entrée (direction/véracité) et un
alignement dérivé (`with`/`against`/`none`). `compute_stats` agrège le hit
rate et le gain moyen PAR groupe d'alignement → répond à « trader AVEC Tik
a-t-il mieux réussi que CONTRE ou SANS ? ».

Cohérent ADR-013 / Bug 9 : `to_naive_utc` strippe la tzinfo avant tout INSERT
(colonnes `TIMESTAMP WITHOUT TIME ZONE`, asyncpg refuse les datetime aware).

ADR-003 / Garde-fou 1 inchangés : journal humain pur, zéro influence
exécution. Lecture/écriture réservées aux scopes `read:trades`/`write:trades`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.storage.models import ManualTrade
from tik_core.utils.time import now_utc_naive

log = structlog.get_logger()


def to_naive_utc(value: datetime) -> datetime:
    """Datetime aware → naïf UTC (cohérent ADR-013 / Bug 9).

    Les colonnes DB sont en `TIMESTAMP WITHOUT TIME ZONE` ; asyncpg refuse un
    datetime aware. Passage obligé avant l'insertion / la mise à jour.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def compute_alignment(direction: str, tik_direction: str | None) -> str:
    """Alignement du trade humain vs ce que disait Tik à l'entrée.

    - "with"    : même sens directionnel (long/long ou short/short)
    - "against" : sens opposé (long/short ou short/long)
    - "none"    : Tik neutre, absent, ou non directionnel à l'entrée

    Volontairement strict : seul un Tik clairement long/short compte comme
    une prise de position alignable. "neutral"/None → "none" (Tik ne
    "conseillait" rien, donc le trade n'est ni avec ni contre lui).
    """
    d = (direction or "").strip().lower()
    t = (tik_direction or "").strip().lower()
    if t not in ("long", "short") or d not in ("long", "short"):
        return "none"
    return "with" if d == t else "against"


def compute_result_pct(
    direction: str, entry_price: float, exit_price: float
) -> float:
    """Résultat du trade en %, basé sur le prix (toujours juste, sans spec broker).

    - long  : (exit - entry) / entry * 100
    - short : (entry - exit) / entry * 100

    En %, indépendant de la taille en lots et des specs contrat MT5 (P&L en $
    différé, cf. memory mt5-points-calibration-todo). `entry_price > 0`
    garanti par la validation Pydantic en amont.
    """
    raw = (exit_price - entry_price) / entry_price
    if (direction or "").strip().lower() == "short":
        raw = -raw
    return raw * 100.0


async def create_trade(
    session: AsyncSession,
    *,
    entity_id: str,
    direction: str,
    entry_price: float,
    size_lots: float,
    entry_time: datetime | None = None,
    stop_price: float | None = None,
    target_price: float | None = None,
    note: str | None = None,
    tik_signal_id: str | None = None,
    tik_direction: str | None = None,
    tik_veracity: float | None = None,
) -> ManualTrade:
    """Insère un trade ouvert et retourne l'objet persisté (alignement calculé)."""
    now = now_utc_naive()
    entry = to_naive_utc(entry_time) if entry_time is not None else now
    trade = ManualTrade(
        id=str(uuid4()),
        entity_id=entity_id.strip().upper(),
        direction=direction.strip().lower(),
        entry_time=entry,
        entry_price=entry_price,
        size_lots=size_lots,
        stop_price=stop_price,
        target_price=target_price,
        exit_time=None,
        exit_price=None,
        status="open",
        note=note,
        result_pct=None,
        tik_signal_id=tik_signal_id,
        tik_direction=(tik_direction.strip().lower() if tik_direction else None),
        tik_veracity=tik_veracity,
        tik_alignment=compute_alignment(direction, tik_direction),
        created_at=now,
        updated_at=now,
    )
    session.add(trade)
    await session.flush()
    return trade


async def get_trade(session: AsyncSession, trade_id: str) -> ManualTrade | None:
    """Récupère un trade par id, ou None."""
    result = await session.execute(
        select(ManualTrade).where(ManualTrade.id == trade_id)
    )
    return result.scalar_one_or_none()


async def list_trades(
    session: AsyncSession,
    *,
    status_filter: str | None = None,
    entity_filter: str | None = None,
    limit: int = 200,
) -> list[ManualTrade]:
    """Liste les trades, ouverts d'abord puis clôturés, plus récents en tête.

    Tri : `status` ASC ("closed" < "open" en alphabétique → on inverse via
    un tri explicite pour mettre les ouverts en premier), puis `entry_time`
    DESC. On garde simple : tri principal par entry_time DESC, le front
    regroupe ouverts/clôturés.
    """
    stmt = select(ManualTrade)
    if status_filter:
        stmt = stmt.where(ManualTrade.status == status_filter.strip().lower())
    if entity_filter:
        stmt = stmt.where(ManualTrade.entity_id == entity_filter.strip().upper())
    stmt = stmt.order_by(ManualTrade.entry_time.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def close_trade(
    session: AsyncSession,
    trade_id: str,
    *,
    exit_price: float,
    exit_time: datetime | None = None,
    note: str | None = None,
) -> ManualTrade | None:
    """Clôture un trade : fixe la sortie, calcule `result_pct`, passe en "closed".

    Retourne le trade mis à jour, ou None si introuvable. Idempotent au sens
    où re-clôturer un trade déjà clôturé recalcule simplement le résultat avec
    les nouvelles valeurs de sortie.
    """
    trade = await get_trade(session, trade_id)
    if trade is None:
        return None
    trade.exit_price = exit_price
    trade.exit_time = to_naive_utc(exit_time) if exit_time is not None else now_utc_naive()
    trade.result_pct = compute_result_pct(trade.direction, trade.entry_price, exit_price)
    trade.status = "closed"
    if note is not None:
        trade.note = note
    trade.updated_at = now_utc_naive()
    await session.flush()
    return trade


async def delete_trade(session: AsyncSession, trade_id: str) -> bool:
    """Supprime un trade. Retourne True si supprimé, False si introuvable."""
    trade = await get_trade(session, trade_id)
    if trade is None:
        return False
    await session.delete(trade)
    await session.flush()
    return True


def _group_metrics(trades: list[ManualTrade]) -> dict:
    """Métriques d'un groupe de trades clôturés : n, hit rate, gain moyen %."""
    closed = [t for t in trades if t.status == "closed" and t.result_pct is not None]
    n = len(closed)
    if n == 0:
        return {"n": 0, "win_rate": None, "avg_result_pct": None, "total_result_pct": 0.0}
    wins = sum(1 for t in closed if (t.result_pct or 0.0) > 0)
    total = sum(t.result_pct or 0.0 for t in closed)
    return {
        "n": n,
        "win_rate": wins / n,
        "avg_result_pct": total / n,
        "total_result_pct": total,
    }


def compute_stats(trades: list[ManualTrade]) -> dict:
    """Agrège le bilan global + la décomposition par alignement Tik.

    Le bloc `by_alignment` (with/against/none) est le cœur de la mesure :
    il ne devient parlant qu'avec un nombre de trades clôturés suffisant
    (≥ ~10 par groupe). Tant que les N sont petits, le caller affiche
    « pas encore assez de trades pour conclure ».
    """
    closed = [t for t in trades if t.status == "closed" and t.result_pct is not None]
    open_trades = [t for t in trades if t.status == "open"]
    overall = _group_metrics(closed)
    return {
        "n_total": len(trades),
        "n_open": len(open_trades),
        "n_closed": len(closed),
        "win_rate": overall["win_rate"],
        "avg_result_pct": overall["avg_result_pct"],
        "total_result_pct": overall["total_result_pct"],
        "by_alignment": {
            "with": _group_metrics([t for t in closed if t.tik_alignment == "with"]),
            "against": _group_metrics([t for t in closed if t.tik_alignment == "against"]),
            "none": _group_metrics(
                [t for t in closed if t.tik_alignment in (None, "none")]
            ),
        },
    }
