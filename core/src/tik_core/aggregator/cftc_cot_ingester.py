"""CFTC COT ingester (couche 5 — positioning institutionnel).

API publique CFTC Socrata : pas de clé requise. Le rapport COT
(Commitments of Traders) est publié chaque vendredi 15:30 ET et reflète
les positions au mardi précédent (3-4 jours de lag).

On polle 1 fois par 24h (largement suffisant pour une donnée hebdomadaire)
et on stocke le dernier rapport GOLD COMEX (code 088691) dans Redis sous
`tik.macro.cftc_cot.gold` avec un TTL de 10 jours pour tolérer un
fournisseur indisponible quelques jours.

Sémantique exposée : positions des "Managed Money" (hedge funds, CTAs)
sous forme de net_pct = (long - short) / (long + short), entre -1 et +1.
La lecture contrarian de cette métrique est appliquée côté swing_engine.
"""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

CFTC_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
GOLD_COMEX_CODE = "088691"
REDIS_KEY = "tik.macro.cftc_cot.gold"
REDIS_TTL_S = 10 * 24 * 3600  # 10 jours, plus que le cycle hebdomadaire


class CftcCotIngester(BaseIngester):
    """Polle le rapport COT Disaggregated Futures Only pour GOLD COMEX."""

    name = "cftc_cot_ingester"
    layer = 5

    def __init__(self, redis: Redis, interval_s: int = 24 * 3600) -> None:
        self.redis = redis
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("cftc_cot.ingester.started", interval_s=self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("cftc_cot.ingester.stopped")

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        try:
            r = await client.get(
                CFTC_URL,
                params={
                    "$where": f"cftc_contract_market_code='{GOLD_COMEX_CODE}'",
                    "$order": "report_date_as_yyyy_mm_dd DESC",
                    "$limit": 1,
                },
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("cftc_cot.fetch.error", error=str(exc))
            return None

        if not data:
            log.warning("cftc_cot.empty_response")
            return None

        row = data[0]
        try:
            mm_long = int(row["m_money_positions_long_all"])
            mm_short = int(row["m_money_positions_short_all"])
            report_date = str(row["report_date_as_yyyy_mm_dd"])
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("cftc_cot.parse.error", error=str(exc))
            return None

        total = mm_long + mm_short
        if total == 0:
            log.warning("cftc_cot.zero_total_positions")
            return None
        net_pct = (mm_long - mm_short) / total

        # Variations hebdomadaires (utiles dans l'evidence pour le contexte)
        try:
            change_long = int(row.get("change_in_m_money_long_all", 0))
            change_short = int(row.get("change_in_m_money_short_all", 0))
        except (TypeError, ValueError):
            change_long = 0
            change_short = 0

        return {
            "source": "cftc_cot",
            "commodity": "gold",
            "report_date": report_date,
            "mm_long": mm_long,
            "mm_short": mm_short,
            "mm_net_pct": round(net_pct, 4),
            "change_mm_long": change_long,
            "change_mm_short": change_short,
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                point = await self._fetch(client)
                if point is not None:
                    payload = json.dumps(point)
                    await self.redis.setex(REDIS_KEY, REDIS_TTL_S, payload)
                    await self.redis.publish(REDIS_KEY, payload)
                    log.info(
                        "cftc_cot.published",
                        report_date=point["report_date"],
                        mm_long=point["mm_long"],
                        mm_short=point["mm_short"],
                        mm_net_pct=point["mm_net_pct"],
                    )
                await asyncio.sleep(self.interval_s)
