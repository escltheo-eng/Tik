"""Endpoint macro_events : calendrier macro/géopolitique programmé.

Lacune B Phase B1 du plan trading manuel J+10 (cf. ADR-017).

Lit la table `macro_events` peuplée par le `FredCalendarIngester` (cycle
daily) et expose deux vues :

- `GET /api/v1/macro_events/upcoming` — events à venir dans les N
  prochaines heures (défaut 168 h = 7 j). Carte Home dashboard +
  notification visuelle « FOMC dans 4h ».
- `GET /api/v1/macro_events/history` — events des N derniers jours.
  Audit ex-post côté dashboard (route détail `/macro/history`).

**Endpoint domain-agnostic** : `entity_id` filtré uniquement si fourni
(`BTC` ou `GOLD`). Sinon retourne tous les events. Cohérent avec le
pattern Phase A.1 (`/headlines/{entity_id}`) — `entity_id` est ici un
filtre query optionnel plutôt qu'un path param parce qu'un event macro
impacte généralement plusieurs assets simultanément.

**Cache Redis TTL 5 min** : les events macro changent une fois par jour
au plus. Pas besoin de re-query la DB à chaque request dashboard
(refresh 5 min côté UI).

**ADR-003 inchangé** : endpoint en lecture seule, pas de bypass guard.
**Garde-fou 1 inchangé** : Tik shadow vs Zeta. Cette feature est purement
informationnelle pour l'humain.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth import AuthContext, require_scope
from tik_core.config import get_settings
from tik_core.storage.database import get_session
from tik_core.storage.macro_events_repo import fetch_history, fetch_upcoming
from tik_core.storage.schemas import MacroEventOut
from tik_core.utils.time import iso_utc

log = structlog.get_logger()

router = APIRouter(prefix="/macro_events")

# Cache TTL 5 min : équilibre entre fraîcheur (ingester daily, donc pas
# de churn rapide) et économie de query DB sous charge dashboard.
MACRO_EVENTS_CACHE_TTL = 5 * 60

VALID_IMPORTANCE = {"HIGH", "MEDIUM", "LOW"}


def _parse_importance(raw: str | None) -> list[str] | None:
    """Parse `?importance=HIGH,MEDIUM` en liste validée. None = pas de filtre."""
    if not raw:
        return None
    parts = [p.strip().upper() for p in raw.split(",") if p.strip()]
    valid = [p for p in parts if p in VALID_IMPORTANCE]
    return valid or None


def _serialize_event(row) -> dict[str, Any]:
    """Sérialise une row `MacroEvent` SQLAlchemy en dict compatible MacroEventOut."""
    return {
        "id": row.id,
        "event_code": row.event_code,
        "event_name": row.event_name,
        "scheduled_for": iso_utc(row.scheduled_for),
        "importance": row.importance,
        "assets_impacted": list(row.assets_impacted or []),
        "source": row.source,
        "release_id": row.release_id,
    }


def _make_cache_key(
    kind: str,
    horizon_or_days: int,
    importance: list[str] | None,
    asset: str | None,
    limit: int,
) -> str:
    """Clé de cache Redis stable et lisible."""
    imp_part = ",".join(sorted(importance)) if importance else "all"
    asset_part = (asset or "all").upper()
    return (
        f"tik.cache.macro_events.{kind}."
        f"h{horizon_or_days}.imp_{imp_part}.asset_{asset_part}.lim{limit}"
    )


@router.get("/upcoming", response_model=list[MacroEventOut])
async def list_upcoming(
    hours: int = Query(168, ge=1, le=720, description="Fenêtre lookahead en heures"),
    importance: str | None = Query(
        None,
        description="Filtre csv: HIGH,MEDIUM,LOW. Aucun → tous niveaux.",
    ),
    entity_id: str | None = Query(
        None,
        description="Filtre asset (ex: BTC, GOLD). Aucun → tous assets.",
    ),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> list[MacroEventOut]:
    """Retourne les events macro programmés dans les `hours` prochaines heures.

    - Tri ASC par `scheduled_for` (le prochain en premier).
    - `importance` : filtre csv (`HIGH,MEDIUM`). Inconnu = ignoré.
    - `entity_id` : filtre par asset impacté.
    - Cache Redis TTL 5 min.
    """
    importance_filter = _parse_importance(importance)
    cache_key = _make_cache_key(
        "upcoming", hours, importance_filter, entity_id, limit
    )

    settings = get_settings()
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        try:
            cached = await redis.get(cache_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_events.cache_read_error", error=str(exc))
            cached = None
        if cached:
            try:
                data = json.loads(cached)
                return [MacroEventOut(**item) for item in data]
            except (TypeError, ValueError, KeyError):
                # Cache corrompu → on re-query
                pass

        rows = await fetch_upcoming(
            session,
            hours=hours,
            importance_filter=importance_filter,
            asset_filter=entity_id,
            limit=limit,
        )
        serialized = [_serialize_event(r) for r in rows]
        try:
            await redis.set(
                cache_key,
                json.dumps(serialized),
                ex=MACRO_EVENTS_CACHE_TTL,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_events.cache_write_error", error=str(exc))

        return [MacroEventOut(**item) for item in serialized]
    finally:
        await redis.close()


@router.get("/history", response_model=list[MacroEventOut])
async def list_history(
    since_days: int = Query(30, ge=1, le=365, description="Fenêtre passée en jours"),
    importance: str | None = Query(None),
    entity_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    _ctx: AuthContext = Depends(require_scope("read:signals")),
) -> list[MacroEventOut]:
    """Retourne les events macro programmés sur les `since_days` derniers jours.

    - Tri DESC par `scheduled_for` (le plus récent en premier).
    - Audit ex-post : permet de relier un mouvement de prix BTC/GOLD passé
      à un event macro identifié dans la fenêtre.
    - Pas de cache (utilisation rare, charge minime).
    """
    importance_filter = _parse_importance(importance)
    rows = await fetch_history(
        session,
        since_days=since_days,
        importance_filter=importance_filter,
        asset_filter=entity_id,
        limit=limit,
    )
    return [MacroEventOut(**_serialize_event(r)) for r in rows]
