"""FRED Calendar ingester (couche 4 — macro-événementiel).

Cf. ADR-017 — Calendrier macro/géopolitique (Lacune B Phase B1 J+10).

Pour chaque release_id de la whitelist `macro_calendar_data.FRED_RELEASES` :
1. Polling daily du endpoint `/fred/release/dates` avec
   `realtime_end=9999-12-31` + `include_release_dates_with_no_data=true`
   pour récupérer les dates futures programmées.
2. Conversion date FRED (calendaire pure, sans heure) → datetime UTC en
   appliquant l'heure de release ET (Eastern Time) hardcodée par release_id
   et en utilisant `zoneinfo.ZoneInfo("America/New_York")` pour gérer
   automatiquement le DST (passage été/hiver).
3. Upsert dans la table `macro_events` via `macro_events_repo.upsert_many`.

En complément, le ingester upsert également les FOMC dates statiques
(2026-2027) listées dans `macro_calendar_data.FOMC_STATIC_DATES` — FRED
ne couvre pas proprement le statement+press conference FOMC, on les pose
nous-mêmes depuis le calendrier officiel Fed Reserve.

**Polling daily** : interval 24h (configurable). Au boot, premier cycle
immédiat. Cohérent avec FredIngester existant pour les séries
observations (DGS10, DXY…).

**Best-effort** : si l'API FRED renvoie une erreur, on log warning et on
continue avec les autres release_ids. Si `session_maker=None` (pas de
DB configurée), on saute la persistence — mais on ne crashe pas.

**ADR-003 inchangé** : ce ingester est read-only (lecture FRED →
écriture table d'audit), aucune décision trading générée. ADR-004
multi-overlay inchangé.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.aggregator.base import BaseIngester
from tik_core.aggregator.macro_calendar_data import (
    FOMC_STATIC_DATES,
    FRED_RELEASES,
    FredReleaseSpec,
    StaticEventSpec,
)
from tik_core.storage.macro_events_repo import upsert_many
from tik_core.utils.time import now_utc

log = structlog.get_logger()

FRED_BASE = "https://api.stlouisfed.org/fred/release/dates"
ET_TZ = ZoneInfo("America/New_York")


def date_to_utc_release(
    iso_date: str, release_hour_et: int, release_minute_et: int
) -> datetime:
    """Convertit une date calendaire ISO + heure ET en datetime UTC aware.

    Le DST (US/Eastern : EST UTC-5 hiver / EDT UTC-4 été) est géré
    automatiquement par `zoneinfo` :
    - 8h30 ET en janvier → 13h30 UTC
    - 8h30 ET en juin → 12h30 UTC
    - 14h00 ET en juillet → 18h00 UTC
    - 14h00 ET en décembre → 19h00 UTC

    Retourne un datetime UTC aware (`tzinfo=UTC`). Le caller convertira
    en naïf via `to_naive_utc()` avant insertion DB.
    """
    d = date.fromisoformat(iso_date)
    et_dt = datetime(
        d.year,
        d.month,
        d.day,
        release_hour_et,
        release_minute_et,
        tzinfo=ET_TZ,
    )
    return et_dt.astimezone(timezone.utc)


def build_event_from_fred(
    spec: FredReleaseSpec, iso_date: str
) -> dict[str, Any]:
    """Construit un dict event prêt pour `upsert_many` à partir d'un FRED spec."""
    return {
        "event_code": spec.event_code,
        "event_name": spec.event_name,
        "scheduled_for": date_to_utc_release(
            iso_date, spec.release_hour_et, spec.release_minute_et
        ),
        "importance": spec.importance,
        "assets_impacted": list(spec.assets_impacted),
        "source": "fred",
        "release_id": spec.release_id,
    }


def build_event_from_static(spec: StaticEventSpec) -> dict[str, Any]:
    """Construit un dict event prêt pour `upsert_many` à partir d'un Static spec."""
    return {
        "event_code": spec.event_code,
        "event_name": spec.event_name,
        "scheduled_for": date_to_utc_release(
            spec.iso_date, spec.release_hour_et, spec.release_minute_et
        ),
        "importance": spec.importance,
        "assets_impacted": list(spec.assets_impacted),
        "source": "fed_static",
        "release_id": None,
    }


def filter_future_dates(
    dates: list[str], min_date: datetime | None = None
) -> list[str]:
    """Filtre les dates ≥ aujourd'hui (UTC) — on ne s'intéresse qu'au futur.

    Pour la Phase B1, on persiste aussi les events passés récents (~30 j)
    pour permettre l'audit historique côté endpoint `/history`. Mais le
    polling FRED retourne potentiellement plusieurs années d'historique,
    on coupe les très anciens.
    """
    if min_date is None:
        # Garde 30 jours d'historique pour l'audit + tout le futur
        from datetime import timedelta
        min_date = now_utc() - timedelta(days=30)
    min_iso = min_date.date().isoformat()
    return [d for d in dates if d >= min_iso]


class FredCalendarIngester(BaseIngester):
    """Ingester du calendrier macro (FRED Releases + FOMC static).

    Cf. ADR-017.

    Polling daily : interval 24h. Premier cycle au boot. Best-effort sur
    chaque release_id (un échec n'arrête pas les autres).
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
            n_static_events=len(FOMC_STATIC_DATES),
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
        """Fetch les dates calendaires d'un release_id FRED. Best-effort."""
        try:
            r = await client.get(
                FRED_BASE,
                params={
                    "release_id": spec.release_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "realtime_end": "9999-12-31",
                    "include_release_dates_with_no_data": "true",
                    "sort_order": "asc",
                    "limit": 200,
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
        return [
            str(item.get("date"))
            for item in release_dates
            if item.get("date")
        ]

    async def _cycle(self) -> int:
        """Un cycle complet : fetch FRED + concat static + upsert. Retourne n_upserted."""
        events: list[dict[str, Any]] = []

        # 1. FOMC static dates
        for static_spec in FOMC_STATIC_DATES:
            events.append(build_event_from_static(static_spec))

        # 2. FRED dynamic releases
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
