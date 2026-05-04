"""CryptoCompare news ingester (couche 6 — news / sentiment textuel).

Le système de votes upvotes/downvotes a été déprécié après le rachat
de CryptoCompare par CoinDesk en 2022. On classifie donc le sentiment
des titres via un `NewsClassifier` injecté (keywords ou LLM via Ollama).

API CryptoCompare (rebranded CoinDesk Data) : free tier ~11k req/mois,
plafond 250k à vie. On polle 1 fois par heure (≈720 req/mois).

Champ `headlines` (Phase 1 trading manuel J+10) : liste des titres bruts
classifiés, persistée dans le payload Redis aux côtés des agrégats. Cap
local à `MAX_HEADLINES = 25`. Le calcul du score reste strictement
inchangé — additif uniquement.
"""

import asyncio
import json
from datetime import datetime, timezone

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.aggregator.news_classifier import NewsClassifier

log = structlog.get_logger()

NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"
REDIS_TTL_S = 2 * 3600  # 2h, plus court que FG car les news bougent vite
MAX_HEADLINES = 25


class CryptoCompareIngester(BaseIngester):
    """Polle CryptoCompare news et calcule un score sentiment net via le classifier injecté."""

    name = "cryptocompare_ingester"
    layer = 6

    def __init__(
        self,
        redis: Redis,
        api_key: str,
        classifier: NewsClassifier,
        currency: str = "BTC",
        interval_s: int = 3600,
    ) -> None:
        self.redis = redis
        self.api_key = api_key
        self.classifier = classifier
        self.currency = currency
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.api_key:
            log.warning("cryptocompare.ingester.no_api_key_skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "cryptocompare.ingester.started",
            currency=self.currency,
            interval_s=self.interval_s,
            classifier=self.classifier.method_name,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.classifier.aclose()
        log.info("cryptocompare.ingester.stopped")

    @staticmethod
    def _verdict_to_sentiment(n_bull: int, n_bear: int) -> str:
        """Convertit le couple (n_bull, n_bear) du classifier en label trinaire."""
        if n_bull > n_bear:
            return "bull"
        if n_bear > n_bull:
            return "bear"
        return "neutral"

    @staticmethod
    def _parse_unix_iso(ts) -> str | None:
        """Convertit un UNIX timestamp (int/float/str) en ISO 8601 aware UTC."""
        if ts is None or ts == "":
            return None
        try:
            return datetime.fromtimestamp(int(float(ts)), tz=timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError, OSError):
            return None

    @staticmethod
    def _extract_publisher(article: dict) -> str:
        """Extrait le nom du publisher de `source_info.name` ou de `source` brut.

        CryptoCompare expose le publisher de deux façons selon l'article :
        - `source_info.name` (canonique, ex: "CoinDesk")
        - `source` (string brute, ex: "coindesk")
        """
        info = article.get("source_info") if isinstance(article, dict) else None
        if isinstance(info, dict):
            name = info.get("name")
            if name:
                return str(name).strip()
        raw = article.get("source")
        if raw:
            return str(raw).strip()
        return "unknown"

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        try:
            r = await client.get(
                NEWS_URL,
                params={
                    "categories": self.currency,
                    "lang": "EN",
                    "api_key": self.api_key,
                },
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("cryptocompare.fetch.error", error=str(exc))
            return None

        if data.get("Type") != 100:
            log.warning(
                "cryptocompare.api.error",
                message=data.get("Message"),
            )
            return None

        articles = data.get("Data", [])
        if not articles:
            return None

        # Réarme le circuit breaker du classifier en début de batch.
        self.classifier.reset_batch()

        n_bullish = 0
        n_bearish = 0
        n_neutral = 0
        headlines: list[dict] = []
        fetched_at = datetime.now(tz=timezone.utc).isoformat()
        for a in articles:
            title = a.get("title", "")
            n_bull, n_bear = await self.classifier.classify(title)
            sentiment = self._verdict_to_sentiment(n_bull, n_bear)
            if sentiment == "bull":
                n_bullish += 1
            elif sentiment == "bear":
                n_bearish += 1
            else:
                n_neutral += 1
            if len(headlines) < MAX_HEADLINES:
                headlines.append(
                    {
                        "title": str(title).strip(),
                        "url": a.get("url") or None,
                        "publisher": self._extract_publisher(a),
                        "sentiment": sentiment,
                        "published_at": self._parse_unix_iso(a.get("published_on")),
                        "fetched_at": fetched_at,
                    }
                )

        n_classified = n_bullish + n_bearish
        score = (n_bullish - n_bearish) / n_classified if n_classified > 0 else 0.0

        return {
            "source": "cryptocompare_news",
            "method": self.classifier.method_name,
            "currency": self.currency,
            "score": round(score, 4),
            "n_articles": len(articles),
            "n_bullish": n_bullish,
            "n_bearish": n_bearish,
            "n_neutral": n_neutral,
            "headlines": headlines,
            "fetched_at": fetched_at,
        }

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                point = await self._fetch(client)
                if point is not None:
                    payload = json.dumps(point)
                    key = f"tik.sentiment.cryptocompare.{self.currency.lower()}"
                    await self.redis.setex(key, REDIS_TTL_S, payload)
                    await self.redis.publish(key, payload)
                    log.info(
                        "cryptocompare.published",
                        currency=self.currency,
                        method=point["method"],
                        score=point["score"],
                        n_bullish=point["n_bullish"],
                        n_bearish=point["n_bearish"],
                        n_neutral=point["n_neutral"],
                        n_headlines=len(point["headlines"]),
                    )
                await asyncio.sleep(self.interval_s)
