"""Fear & Greed ingester (couche 7 — sentiment crypto).

API publique alternative.me : pas de clé requise, MAJ une fois par jour.
Polling 1h pour résilience (cache local Redis avec TTL 25h).
"""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

FNG_URL = "https://api.alternative.me/fng/"
REDIS_KEY = "tik.sentiment.fear_greed"
REDIS_TTL_S = 25 * 3600  # tolérance 1h au-delà du cycle quotidien


class FearGreedIngester(BaseIngester):
    """Polle le Fear & Greed Index crypto et le stocke dans Redis."""

    name = "fear_greed_ingester"
    layer = 7

    def __init__(self, redis: Redis, interval_s: int = 3600) -> None:
        self.redis = redis
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("fear_greed.ingester.started", interval_s=self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("fear_greed.ingester.stopped")

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        try:
            r = await client.get(FNG_URL, params={"limit": 1}, timeout=10.0)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("fear_greed.fetch.error", error=str(exc))
            return None

        try:
            point = data["data"][0]
            value = int(point["value"])
            classification = str(point["value_classification"])
            ts_unix = int(point["timestamp"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            log.warning("fear_greed.parse.error", error=str(exc))
            return None

        return {
            "source": "alternative_me_fng",
            "value": value,
            "classification": classification,
            "timestamp": datetime.fromtimestamp(ts_unix, tz=timezone.utc).isoformat(),
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                point = await self._fetch(client)
                if point is not None:
                    payload = json.dumps(point)
                    await self.redis.setex(REDIS_KEY, REDIS_TTL_S, payload)
                    await self.redis.publish("tik.sentiment.fear_greed", payload)
                    log.info(
                        "fear_greed.published",
                        value=point["value"],
                        classification=point["classification"],
                    )
                await asyncio.sleep(self.interval_s)
