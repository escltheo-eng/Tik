"""Yahoo Finance ingester (couche 1 — Gold).

Polling des cotations Gold Futures (GC=F) via l'endpoint public Yahoo
(non officiel mais stable depuis des années). Polling 60s suffit pour
les horizons swing et macro.

Pour le flash Gold, il faudrait une source plus rapide (Alpha Vantage
ou payant) — non prévu dans le MVP gratuit.
"""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester, MarketTick
from tik_core.utils.time import now_utc

log = structlog.get_logger()

YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (compatible; TikBot/0.1; +https://tik.local)"


class YahooPoller(BaseIngester):
    """Polle Yahoo Finance périodiquement pour un symbole donné."""

    name = "yahoo_poller"
    layer = 1

    def __init__(
        self,
        redis: Redis,
        symbol: str = "GC=F",
        entity_id: str = "GOLD",
        interval_s: int = 60,
    ) -> None:
        self.redis = redis
        self.symbol = symbol
        self.entity_id = entity_id
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "yahoo.poller.started",
            symbol=self.symbol,
            entity=self.entity_id,
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
        log.info("yahoo.poller.stopped")

    async def _fetch_quote(self, client: httpx.AsyncClient) -> MarketTick | None:
        url = YAHOO_QUOTE_URL.format(symbol=self.symbol)
        try:
            r = await client.get(
                url,
                params={"interval": "1m", "range": "1d"},
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("yahoo.fetch.error", symbol=self.symbol, error=str(exc))
            return None

        try:
            chart = data["chart"]["result"][0]
            meta = chart["meta"]
            price = float(meta["regularMarketPrice"])
            ts_unix = int(meta.get("regularMarketTime", 0))
            ts = datetime.fromtimestamp(ts_unix, tz=timezone.utc) if ts_unix else now_utc()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            log.warning("yahoo.parse.error", error=str(exc))
            return None

        return MarketTick(
            entity_id=self.entity_id,
            source="yahoo",
            price=price,
            volume=None,
            timestamp=ts,
            extra={"symbol": self.symbol},
        )

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                tick = await self._fetch_quote(client)
                if tick is not None:
                    payload = {
                        "entity_id": tick.entity_id,
                        "source": tick.source,
                        "price": tick.price,
                        "volume": tick.volume,
                        "timestamp": tick.timestamp.isoformat(),
                        "extra": tick.extra or {},
                    }
                    await self.redis.publish(
                        f"tik.tick.{tick.entity_id}.{tick.source}",
                        json.dumps(payload),
                    )
                    await self.redis.setex(
                        f"tik.last_price.{tick.entity_id}",
                        300,
                        json.dumps(payload),
                    )
                await asyncio.sleep(self.interval_s)
