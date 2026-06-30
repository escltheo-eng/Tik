"""FRED macro ingester (couche 4 — macro-économique).

Fed Reserve Economic Data : gratuit, clé API gratuite sur demande.
Récupère les derniers points de séries clés (DGS10, DXY, CPIAUCSL, M2SL...).

Polling faible fréquence (1h suffit pour la plupart des séries).
"""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester, MacroDataPoint
from tik_core.utils.time import now_utc

log = structlog.get_logger()

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Séries utiles pour trading BTC/Gold
DEFAULT_SERIES = [
    "DGS10",  # 10-Year Treasury yield
    "DGS2",  # 2-Year Treasury yield (for curve)
    "DTWEXBGS",  # DXY-like (Broad Dollar Index)
    "CPIAUCSL",  # CPI All items
    "M2SL",  # M2 money supply
    "FEDFUNDS",  # Effective Fed Funds Rate
    "UNRATE",  # Unemployment rate
]


class FredIngester(BaseIngester):
    """Polle les séries FRED et publie sur Redis."""

    name = "fred_ingester"
    layer = 4

    def __init__(
        self,
        redis: Redis,
        api_key: str,
        series_ids: list[str] | None = None,
        interval_s: int = 3600,
    ) -> None:
        self.redis = redis
        self.api_key = api_key
        self.series_ids = series_ids or DEFAULT_SERIES
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.api_key:
            log.warning("fred.ingester.no_api_key_skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "fred.ingester.started",
            series=self.series_ids,
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
        log.info("fred.ingester.stopped")

    async def _fetch_series(
        self,
        client: httpx.AsyncClient,
        series_id: str,
    ) -> MacroDataPoint | None:
        try:
            r = await client.get(
                FRED_BASE,
                params={
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": 1,
                },
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("fred.fetch.error", series=series_id, error=str(exc))
            return None

        obs = data.get("observations", [])
        if not obs:
            return None

        last = obs[0]
        value_str = last.get("value")
        if value_str in (".", "", None):
            return None

        try:
            value = float(value_str)
        except ValueError:
            return None

        try:
            ts = datetime.fromisoformat(last["date"]).replace(tzinfo=UTC)
        except Exception:  # noqa: BLE001
            ts = now_utc()

        return MacroDataPoint(
            series_id=series_id,
            source="fred",
            value=value,
            timestamp=ts,
        )

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                for sid in self.series_ids:
                    point = await self._fetch_series(client, sid)
                    if point is not None:
                        payload = {
                            "series_id": point.series_id,
                            "source": point.source,
                            "value": point.value,
                            "timestamp": point.timestamp.isoformat(),
                        }
                        await self.redis.publish(
                            f"tik.macro.{point.series_id}",
                            json.dumps(payload),
                        )
                        # TTL 24h (ex=86400) : borne la péremption de la
                        # valeur. Sans TTL (bug audit 2026-06-24 finding A), si
                        # FRED décroche, une série périmée serait servie comme
                        # fraîche indéfiniment. 24h = ~24× l'intervalle de poll
                        # (1h) → survit à une coupure FRED longue tout en
                        # garantissant qu'au-delà d'un jour sans MAJ la clé
                        # disparaît (donnée absente = honnête, cf. leçon Bug 15
                        # CryptoCompare : ne PAS choisir un TTL < intervalle).
                        await self.redis.set(
                            f"tik.macro.last.{point.series_id}",
                            json.dumps(payload),
                            ex=86400,
                        )
                    # Rate limit FRED : 120 req/min. On laisse de la marge.
                    await asyncio.sleep(1)

                await asyncio.sleep(self.interval_s)
