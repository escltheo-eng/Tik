"""Binance WebSocket ingester (couche 1 — données de marché temps réel).

Stream public gratuit, pas de clé nécessaire.
Endpoint : wss://stream.binance.com:9443/ws/btcusdt@trade

Normalise les trades en MarketTick et les publie sur Redis pour que les
engines puissent les consommer.
"""

import asyncio
import json
from datetime import UTC, datetime

import structlog
import websockets
from redis.asyncio import Redis
from tenacity import retry, stop_after_attempt, wait_exponential

from tik_core.aggregator.base import BaseIngester, MarketTick

log = structlog.get_logger()

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"


class BinanceTradesIngester(BaseIngester):
    """Subscribe aux trades BTC/USDT et publie sur Redis."""

    name = "binance_trades"
    layer = 1

    def __init__(
        self,
        redis: Redis,
        symbol: str = "btcusdt",
        entity_id: str = "BTC",
    ) -> None:
        self.redis = redis
        self.symbol = symbol.lower()
        self.entity_id = entity_id
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("binance.ingester.started", symbol=self.symbol, entity=self.entity_id)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("binance.ingester.stopped")

    @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=2, max=30))
    async def _connect_and_stream(self) -> None:
        url = f"{BINANCE_WS_URL}/{self.symbol}@trade"
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            log.info("binance.ws.connected", url=url)
            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=60)
                except TimeoutError:
                    log.warning("binance.ws.timeout")
                    break
                await self._handle_message(raw)

    async def _handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("binance.ws.bad_json")
            return

        if msg.get("e") != "trade":
            return

        tick = MarketTick(
            entity_id=self.entity_id,
            source="binance",
            price=float(msg["p"]),
            volume=float(msg["q"]),
            timestamp=datetime.fromtimestamp(msg["T"] / 1000, tz=UTC),
            extra={"trade_id": msg.get("t"), "is_buyer_maker": msg.get("m")},
        )

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
        # Cache du dernier prix pour query rapide par les engines
        await self.redis.setex(
            f"tik.last_price.{tick.entity_id}",
            300,  # TTL 5 min
            json.dumps(payload),
        )

    async def _run(self) -> None:
        while self._running:
            try:
                await self._connect_and_stream()
            except Exception as exc:  # noqa: BLE001
                log.error("binance.ws.error", error=str(exc))
                await asyncio.sleep(5)
