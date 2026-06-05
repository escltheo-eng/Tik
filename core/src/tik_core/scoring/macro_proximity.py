"""Proximité d'un signal à un événement macro programmé (discipline ±4h).

Phase B1.5 / B2.5 — couplage signal ↔ calendrier macro (cf. ADR-017 Paquet 11
+ ADR-020 Paquet 23). Quand un signal est émis dans la fenêtre ±4h autour d'un
événement macro HIGH (NFP, CPI, FOMC, BCE, BoJ, BoE…) qui impacte son entité,
on pose un flag `near_macro_event` dans `decision.advisory`. Le dashboard
affiche alors un repère de discipline (Garde-fou 2-bis : ne pas entrer en swing
dans les ±4h, ou sizing divisé par 2).

IMPORTANT (ADR-017) : le calendrier macro est un outil de DISCIPLINE pour
l'humain, PAS un input des engines. Ce module ne touche JAMAIS la direction,
la conviction ni la veracity du signal — il ajoute uniquement des métadonnées
dans `advisory`. Best-effort : toute erreur est avalée (log warning), l'émission
du signal n'est jamais bloquée (cohérent `headlines_repo.persist_headlines` et
`macro_events_repo.upsert_many`).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.storage.models import MacroEvent
from tik_core.utils.time import iso_utc

log = structlog.get_logger()

# Fenêtre de discipline (cohérent Garde-fou 2-bis : ±4h autour d'un event HIGH).
NEAR_MACRO_WINDOW_HOURS = 4.0
# Niveaux d'importance qui déclenchent le flag (HIGH seul = discipline ±4h).
NEAR_MACRO_IMPORTANCE = ("HIGH",)


class _MacroEventLike(Protocol):
    event_code: str
    event_name: str
    scheduled_for: datetime
    importance: str


def _to_naive_utc(value: datetime) -> datetime:
    """Convertit un datetime aware → naïf UTC (cohérent colonnes DB / Bug 9)."""
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def find_nearest_macro_event(
    signal_ts: datetime,
    events: Iterable[_MacroEventLike],
    *,
    window_hours: float = NEAR_MACRO_WINDOW_HOURS,
) -> dict[str, Any] | None:
    """Renvoie l'event le plus proche (valeur absolue) dans ±window_hours, ou None.

    Fonction PURE, testable sans DB. `signal_ts` et `events[].scheduled_for`
    sont traités comme du UTC (aware → converti naïf). Le filtrage par
    importance et par entité est à la charge du caller (l'annotateur le fait
    via la requête SQL). Ici on ne gère que la fenêtre temporelle + le choix
    du plus proche.
    """
    ts = _to_naive_utc(signal_ts)
    window = timedelta(hours=window_hours)
    best: _MacroEventLike | None = None
    best_dist: timedelta | None = None
    for ev in events:
        sched = _to_naive_utc(ev.scheduled_for)
        dist = abs(sched - ts)
        if dist <= window and (best_dist is None or dist < best_dist):
            best = ev
            best_dist = dist
    if best is None:
        return None
    sched = _to_naive_utc(best.scheduled_for)
    hours_until = round((sched - ts).total_seconds() / 3600.0, 1)
    return {
        "event_code": best.event_code,
        "title": best.event_name,
        "scheduled_for": iso_utc(sched),
        "importance": best.importance,
        # Signé : > 0 = event à venir (signal émis AVANT), < 0 = event passé.
        "hours_until": hours_until,
    }


async def annotate_near_macro_event(
    session: AsyncSession,
    decision: Any,
    *,
    window_hours: float = NEAR_MACRO_WINDOW_HOURS,
    importance_levels: tuple[str, ...] = NEAR_MACRO_IMPORTANCE,
) -> None:
    """Pose `decision.advisory["near_macro_event"]` si le signal est émis dans
    la fenêtre ±window_hours d'un event macro HIGH impactant son entité.

    Best-effort : toute erreur (DB down, contention…) est avalée — l'émission
    du signal n'est JAMAIS bloquée. Ne modifie PAS direction/confidence/veracity.
    """
    try:
        ts_naive = _to_naive_utc(decision.timestamp)
        window = timedelta(hours=window_hours)
        stmt = (
            select(MacroEvent)
            .where(MacroEvent.scheduled_for >= ts_naive - window)
            .where(MacroEvent.scheduled_for <= ts_naive + window)
            .where(MacroEvent.importance.in_(list(importance_levels)))
            .order_by(MacroEvent.scheduled_for.asc())
        )
        result = await session.execute(stmt)
        rows = list(result.scalars().all())

        # Filtre par entité : la row est gardée si l'entité figure dans
        # `assets_impacted` (JSON), ou si `assets_impacted` est vide (= tous).
        entity = str(decision.entity_id).upper()
        rows = [
            r
            for r in rows
            if not r.assets_impacted or entity in [str(a).upper() for a in r.assets_impacted]
        ]

        near = find_nearest_macro_event(ts_naive, rows, window_hours=window_hours)
        if near is None:
            return

        if not isinstance(getattr(decision, "advisory", None), dict):
            decision.advisory = {}
        decision.advisory["near_macro_event"] = near
        log.info(
            "macro_proximity.flagged",
            entity=decision.entity_id,
            # NB: `event` est le nom positionnel réservé du bound logger structlog
            # (meth(event, **kw)). Passer `event=` en kwarg lève « got multiple
            # values for argument 'event' », exception avalée par le except
            # best-effort ci-dessous → log de succès perdu + faux warning. D'où
            # `event_code=`. Cf. bug découvert le 2026-06-05 (NFP).
            event_code=near["event_code"],
            hours_until=near["hours_until"],
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("macro_proximity.error", error=str(exc))
