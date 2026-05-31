"""FRED Calendar ingester (couche 4 — macro-événementiel US).

Cf. ADR-017 — Calendrier macro/géopolitique (Phase B1 J+10).
Cf. ADR-020 — Multi-banques centrales (Phase B2) : FOMC + ECB + BoJ +
BoE sont désormais gérés par `MacroStaticIngester` séparément. Ce
ingester ne s'occupe plus que des 6 release FRED dynamiques.

Pour chaque release_id de la whitelist `macro_calendar_data.FRED_RELEASES` :

1. Polling daily du endpoint `/fred/release/dates` avec
   `realtime_end=9999-12-31` + `include_release_dates_with_no_data=true`
   pour récupérer les dates futures programmées.
2. Conversion date FRED (calendaire pure, sans heure) → datetime UTC en
   appliquant l'heure de release ET (Eastern Time) hardcodée par release_id
   et en utilisant `zoneinfo.ZoneInfo("America/New_York")` pour gérer
   automatiquement le DST (passage été/hiver).
3. Upsert dans la table `macro_events` via `macro_events_repo.upsert_many`.

**Polling daily** : interval 24h (configurable). Au boot, premier cycle
immédiat.

**Best-effort** : si l'API FRED renvoie une erreur, on log warning et on
continue avec les autres release_ids. Si `session_maker=None` ou
`api_key=""`, on saute le démarrage proprement (warning) mais on ne
crashe pas — `MacroStaticIngester` reste actif pour FOMC/ECB/BoJ/BoE.

**ADR-003 inchangé** : ce ingester est read-only (lecture FRED →
écriture table d'audit), aucune décision trading générée. ADR-004
multi-overlay inchangé.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.aggregator.base import BaseIngester
from tik_core.aggregator.macro_calendar_data import (
    FRED_RELEASES,
    FredReleaseSpec,
    build_event_from_fred,
)
from tik_core.storage.macro_events_repo import upsert_many
from tik_core.utils.time import now_utc

log = structlog.get_logger()

FRED_BASE = "https://api.stlouisfed.org/fred/release/dates"


# Réexport des helpers déplacés vers macro_calendar_data (rétrocompat tests B1).
# Les helpers eux-mêmes sont définis dans macro_calendar_data (Phase B2 ADR-020).
from tik_core.aggregator.macro_calendar_data import (  # noqa: E402, F401
    build_event_from_static,
    date_to_utc_release,
)


def filter_future_dates(dates: list[str], min_date: datetime | None = None) -> list[str]:
    """Filtre les dates ≥ aujourd'hui (UTC) — on ne s'intéresse qu'au futur.

    Pour la Phase B1, on persiste aussi les events passés récents (~30 j)
    pour permettre l'audit historique côté endpoint `/history`. Mais le
    polling FRED retourne potentiellement plusieurs années d'historique,
    on coupe les très anciens.
    """
    if min_date is None:
        min_date = now_utc() - timedelta(days=30)
    min_iso = min_date.date().isoformat()
    return [d for d in dates if d >= min_iso]


class FredCalendarIngester(BaseIngester):
    """Ingester du calendrier macro (FRED Releases dynamiques uniquement).

    Cf. ADR-017 (B1) + ADR-020 (B2 — séparation static/dynamic).

    Polling daily : interval 24h. Premier cycle au boot. Best-effort sur
    chaque release_id (un échec n'arrête pas les autres).

    Si `api_key=""` ou `session_maker=None`, le ingester ne démarre pas.
    Phase B2 : ce skip n'affecte plus les dates statiques FOMC, qui sont
    désormais gérées par `MacroStaticIngester` (sans clé FRED requise).
    """

    name = "fred_calendar_ingester"
    layer = 4

    def __init__(
        self,
        api_key: str,
        session_maker: async_sessionmaker[AsyncSession] | None,
        interval_s: int = 86400,
    ) -> None:
        self.api_key = api_key
        self.session_maker = session_maker
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.api_key:
            log.warning("fred_calendar.ingester.no_api_key_skipping")
            return
        if self.session_maker is None:
            log.warning("fred_calendar.ingester.no_session_maker_skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "fred_calendar.ingester.started",
            n_fred_releases=len(FRED_RELEASES),
            interval_s=self.interval_s,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("fred_calendar.ingester.stopped")

    async def _fetch_release_dates(
        self, client: httpx.AsyncClient, spec: FredReleaseSpec
    ) -> list[str]:
        """Fetch les dates calendaires d'un release_id FRED. Best-effort.

        ⚠️ `sort_order=desc` est **obligatoire** : FRED `/release/dates`
        retourne l'historique complet du release (pour NFP : 867 dates
        depuis 1776). Avec `sort_order=asc&limit=200`, on récupèrerait
        les 200 PREMIÈRES dates (toutes dans les années 1900) et aucune
        date future. Avec `desc`, on récupère les `limit` dernières
        publications, qui incluent les ~8-12 dates futures programmées
        grâce à `realtime_end=9999-12-31`.
        """
        try:
            r = await client.get(
                FRED_BASE,
                params={
                    "release_id": spec.release_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "realtime_end": "9999-12-31",
                    "include_release_dates_with_no_data": "true",
                    "sort_order": "desc",
                    "limit": 50,
                },
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "fred_calendar.fetch.error",
                release_id=spec.release_id,
                event_code=spec.event_code,
                error=str(exc),
            )
            return []

        release_dates = data.get("release_dates", [])
        return [str(item.get("date")) for item in release_dates if item.get("date")]

    async def _cycle(self) -> int:
        """Un cycle complet : fetch FRED dynamique + upsert. Retourne n_upserted.

        Phase B2 : ne gère plus les FOMC dates statiques (déplacé dans
        `MacroStaticIngester`). Si le static ingester n'est pas configuré,
        les FOMC dates ne seront PAS upsertées — c'est intentionnel pour
        garantir la séparation des responsabilités (cf. ADR-020).
        """
        events: list[dict[str, Any]] = []

        async with httpx.AsyncClient() as client:
            for spec in FRED_RELEASES:
                dates = await self._fetch_release_dates(client, spec)
                future_dates = filter_future_dates(dates)
                for iso_date in future_dates:
                    events.append(build_event_from_fred(spec, iso_date))
                # Rate limit FRED 120 req/min → marge confortable
                await asyncio.sleep(0.5)

        n_upserted = await upsert_many(self.session_maker, events)
        log.info(
            "fred_calendar.cycle_complete",
            n_events_built=len(events),
            n_upserted=n_upserted,
        )
        return n_upserted

    async def _run(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:  # noqa: BLE001
                log.warning("fred_calendar.cycle_error", error=str(exc))
            await asyncio.sleep(self.interval_s)
