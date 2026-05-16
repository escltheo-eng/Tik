"""Macro Static ingester (couche 4 — calendrier macro statique).

Cf. ADR-020 — Phase B2 multi-banques centrales (FOMC + ECB + BoJ + BoE).

Gère exclusivement les dates statiques publiées 1 an à l'avance par les
banques centrales :

- **FOMC** (Federal Reserve, US, statement à 14h00 ET)
- **ECB** (Governing Council, Frankfurt, statement à 14h15 CET)
- **BoJ** (Monetary Policy Meeting, Tokyo, statement vers 12h00 JST)
- **BoE** (MPC Bank Rate decision, London, à 12h00 GMT/BST)

Sources des dates : voir `macro_calendar_data.py` (URLs des sites
officiels en tête de chaque liste).

**Pas de fetch HTTP** : tout est hardcodé dans `macro_calendar_data.py`.
L'ingester se contente d'itérer sur la concat `all_static_events()` et
d'upsert via `macro_events_repo.upsert_many` (idempotent par UNIQUE
constraint `(event_code, scheduled_for)`).

**Pas de clé API requise** : contrairement au `FredCalendarIngester` qui
a besoin d'une clé FRED, ce ingester tourne sans aucune dépendance
externe. Si la clé FRED n'est pas configurée, ce ingester reste actif et
les dates FOMC continuent d'être upsertées (fix bug latent Phase B1).

**Polling daily** : interval 24h. Premier cycle au boot, comme
`FredCalendarIngester`. Cohérent : un calendrier statique ne change pas
en intra-day, mais on re-upsert quand même chaque jour pour garantir
que toute correction manuelle de `macro_calendar_data.py` se propage.

**Best-effort** : si la transaction DB échoue, log warning + retourne 0.

**ADR-003 inchangé** : ingester read-only (écrit en table d'audit, ne
génère aucune décision trading). Garde-fou 1 inchangé.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tik_core.aggregator.base import BaseIngester
from tik_core.aggregator.macro_calendar_data import (
    all_static_events,
    build_event_from_static,
)
from tik_core.storage.macro_events_repo import upsert_many

log = structlog.get_logger()


class MacroStaticIngester(BaseIngester):
    """Ingester du calendrier macro statique (FOMC + ECB + BoJ + BoE).

    Cf. ADR-020.

    Polling daily : interval 24h (par défaut). Premier cycle au boot.
    Pas de clé API requise — tout est dans `macro_calendar_data.py`.
    Best-effort sur l'upsert (échec DB → log warning, continue).

    Si `session_maker=None`, le ingester ne démarre pas (warning).
    """

    name = "macro_static_ingester"
    layer = 4

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession] | None,
        interval_s: int = 86400,
    ) -> None:
        self.session_maker = session_maker
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self.session_maker is None:
            log.warning("macro_static.ingester.no_session_maker_skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "macro_static.ingester.started",
            n_static_events=len(all_static_events()),
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
        log.info("macro_static.ingester.stopped")

    async def _cycle(self) -> int:
        """Un cycle complet : itère sur all_static_events() et upsert.

        Retourne le nombre d'events insérés/mis à jour. Best-effort sur
        l'upsert global — un échec DB log warning et retourne 0.
        """
        events: list[dict[str, Any]] = [
            build_event_from_static(spec) for spec in all_static_events()
        ]
        n_upserted = await upsert_many(self.session_maker, events)
        log.info(
            "macro_static.cycle_complete",
            n_events_built=len(events),
            n_upserted=n_upserted,
        )
        return n_upserted

    async def _run(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:  # noqa: BLE001
                log.warning("macro_static.cycle_error", error=str(exc))
            await asyncio.sleep(self.interval_s)
