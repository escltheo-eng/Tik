"""Helper d'insertion (upsert) et lecture des événements macro programmés.

Cf. ADR-017 — Calendrier macro/géopolitique (Lacune B Phase B1 J+10).

Pattern OSINT pro : table d'audit des events programmés, mise à jour
quotidienne par le ingester FRED Calendar (cycle 06:00 UTC). Lecture
exposée par l'API `/api/v1/macro_events/upcoming` (Home dashboard) et
`/api/v1/macro_events/history` (audit, route détail).

**Idempotence** garantie par UNIQUE (event_code, scheduled_for) au niveau
DB et upsert via SQL `ON CONFLICT DO UPDATE` côté code. Si une release
est reportée de 24h (rare mais arrive), l'upsert détecte le conflit sur
event_code + nouvelle date et insert une nouvelle row, l'ancienne row
conflictuelle reste — ce n'est pas un cas géré en B1 (probabilité faible,
on accepte une duplication ponctuelle qui sera filtrable par le caller
via `scheduled_for >= now`).

**Best-effort** : si l'écriture DB échoue (Postgres down, contention),
on log warning et retourne 0 — l'ingester continue son cycle (cohérent
avec `headlines_repo.persist_headlines`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.storage.models import MacroEvent
from tik_core.utils.time import now_utc_naive

log = structlog.get_logger()


def to_naive_utc(value: datetime) -> datetime:
    """Convertit un datetime aware → naïf UTC (cohérent ADR-013 / Bug 9).

    Les colonnes DB sont en `TIMESTAMP WITHOUT TIME ZONE`, asyncpg refuse
    les datetime aware (cf. publisher.py:_publish_signal workaround). Cette
    fonction est le passage obligé à l'insertion.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def cutoff_horizon_naive(hours: int) -> tuple[datetime, datetime]:
    """Retourne (now_naive, now_naive + hours) en datetime naïf UTC.

    Utilisé par `fetch_upcoming` pour borner la fenêtre de lookahead.
    """
    now = now_utc_naive()
    return now, now + timedelta(hours=hours)


def cutoff_history_naive(days: int) -> datetime:
    """Retourne le cutoff naïf pour la lecture historique (`since_days`)."""
    return now_utc_naive() - timedelta(days=days)


async def upsert_macro_event(
    session: AsyncSession,
    *,
    event_code: str,
    event_name: str,
    scheduled_for: datetime,
    importance: str,
    assets_impacted: list[str],
    source: str,
    release_id: int | None,
) -> bool:
    """Upsert d'un event macro. Retourne True si créé/mis à jour, False si erreur.

    Utilise `ON CONFLICT (event_code, scheduled_for) DO UPDATE` côté Postgres
    pour rester idempotent : ré-exécutable autant de fois qu'on veut sans
    générer de doublons. Met à jour `updated_at`, `event_name`, `importance`,
    `assets_impacted`, `source`, `release_id` au cas où on aurait corrigé
    une métadonnée dans `macro_calendar_data.py`.
    """
    scheduled_for_naive = to_naive_utc(scheduled_for)
    now = now_utc_naive()
    stmt = pg_insert(MacroEvent).values(
        id=str(uuid4()),
        event_code=event_code,
        event_name=event_name,
        scheduled_for=scheduled_for_naive,
        importance=importance,
        assets_impacted=list(assets_impacted),
        source=source,
        release_id=release_id,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["event_code", "scheduled_for"],
        set_={
            "event_name": stmt.excluded.event_name,
            "importance": stmt.excluded.importance,
            "assets_impacted": stmt.excluded.assets_impacted,
            "source": stmt.excluded.source,
            "release_id": stmt.excluded.release_id,
            "updated_at": now,
        },
    )
    try:
        await session.execute(stmt)
        return True
    except SQLAlchemyError as exc:
        log.warning(
            "macro_events_repo.upsert_error",
            event_code=event_code,
            scheduled_for=str(scheduled_for_naive),
            error=str(exc),
        )
        return False


async def upsert_many(
    session_maker: async_sessionmaker[AsyncSession] | None,
    events: list[dict[str, Any]],
) -> int:
    """Upsert N events macro dans une seule transaction. Retourne le compte inséré/maj.

    **Best-effort** : si la transaction échoue, on log warning et retourne 0.

    Le caller (FredCalendarIngester) construit les dicts à partir des specs
    statiques + des release_dates fetchées par release_id.
    """
    if session_maker is None or not events:
        return 0

    n_ok = 0
    try:
        async with session_maker() as session:
            for ev in events:
                ok = await upsert_macro_event(
                    session,
                    event_code=ev["event_code"],
                    event_name=ev["event_name"],
                    scheduled_for=ev["scheduled_for"],
                    importance=ev["importance"],
                    assets_impacted=list(ev.get("assets_impacted", [])),
                    source=ev["source"],
                    release_id=ev.get("release_id"),
                )
                if ok:
                    n_ok += 1
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "macro_events_repo.upsert_many_error",
            n_events=len(events),
            error=str(exc),
        )
        return 0
    return n_ok


async def fetch_upcoming(
    session: AsyncSession,
    hours: int,
    importance_filter: list[str] | None = None,
    asset_filter: str | None = None,
    limit: int = 50,
) -> list[MacroEvent]:
    """Fetch les events programmés dans la fenêtre [now, now + hours].

    Tri ASC par `scheduled_for` (le prochain en premier). Filtres optionnels :
    - `importance_filter` : liste de niveaux ("HIGH", "MEDIUM", "LOW"). None = tous.
    - `asset_filter` : asset code ("BTC", "GOLD") — la row est gardée si l'asset
      figure dans `assets_impacted` (JSON). None = tous.
    """
    now, until = cutoff_horizon_naive(hours)
    stmt = (
        select(MacroEvent)
        .where(MacroEvent.scheduled_for >= now)
        .where(MacroEvent.scheduled_for < until)
        .order_by(MacroEvent.scheduled_for.asc())
        .limit(limit)
    )
    if importance_filter:
        stmt = stmt.where(MacroEvent.importance.in_(importance_filter))
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if asset_filter is None:
        return rows
    asset_filter_upper = asset_filter.upper()
    return [r for r in rows if asset_filter_upper in (r.assets_impacted or [])]


async def fetch_history(
    session: AsyncSession,
    since_days: int,
    importance_filter: list[str] | None = None,
    asset_filter: str | None = None,
    limit: int = 200,
) -> list[MacroEvent]:
    """Fetch les events programmés dans le passé sur `since_days` derniers jours.

    Tri DESC par `scheduled_for` (le plus récent en premier). Audit historique :
    sert à analyser ex-post quels events macro ont précédé tel mouvement de
    prix BTC/GOLD.
    """
    cutoff = cutoff_history_naive(since_days)
    now = now_utc_naive()
    stmt = (
        select(MacroEvent)
        .where(MacroEvent.scheduled_for >= cutoff)
        .where(MacroEvent.scheduled_for < now)
        .order_by(MacroEvent.scheduled_for.desc())
        .limit(limit)
    )
    if importance_filter:
        stmt = stmt.where(MacroEvent.importance.in_(importance_filter))
    result = await session.execute(stmt)
    rows = list(result.scalars().all())
    if asset_filter is None:
        return rows
    asset_filter_upper = asset_filter.upper()
    return [r for r in rows if asset_filter_upper in (r.assets_impacted or [])]
