"""Google News RSS ingester (couche 6 — news / sentiment textuel multi-asset).

Source gratuite, sans clé, large couverture (Reuters, Bloomberg, FT, CNBC,
WSJ, CoinDesk…). Utilisée pour BTC et GOLD via deux instances séparées,
chacune avec son propre `NewsClassifier` asset-aware (cf. ADR-008).

Polling toutes les 30 min (~1440 req/mois total BTC+GOLD, sous radar de
tout rate-limit observé). 50 titres max par cycle pour rester comparable
à CryptoCompare.

Endpoint Google News RSS non officiellement documenté mais stable depuis
20 ans. En cas de fail (HTTP, parsing), on log un warning et on saute le
cycle — pas de circuit cassant globalement, le cycle suivant retentera.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import quote_plus

import feedparser
import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.aggregator.news_classifier import NewsClassifier

log = structlog.get_logger()

GOOGLE_NEWS_RSS_TPL = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)
USER_AGENT = "Mozilla/5.0 (compatible; TikBot/0.1)"
REDIS_TTL_S = 2 * 3600  # 2h, comme CryptoCompare
REDIS_KEY_TPL = "tik.sentiment.google_news.{entity}"


class GoogleNewsIngester(BaseIngester):
    """Polle Google News RSS et calcule un score sentiment net via le classifier injecté."""

    name = "google_news_ingester"
    layer = 6

    def __init__(
        self,
        redis: Redis,
        classifier: NewsClassifier,
        entity_id: str,
        query: str,
        interval_s: int = 1800,
        limit: int = 50,
    ) -> None:
        self.redis = redis
        self.classifier = classifier
        self.entity_id = entity_id
        self.query = query
        self.interval_s = interval_s
        self.limit = limit
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "google_news.ingester.started",
            entity_id=self.entity_id,
            query=self.query,
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
        log.info("google_news.ingester.stopped", entity_id=self.entity_id)

    def _build_url(self) -> str:
        return GOOGLE_NEWS_RSS_TPL.format(query=quote_plus(self.query))

    @staticmethod
    def _extract_publisher(entry) -> str:
        """Extrait le nom du publisher depuis `entry.source` ou depuis le suffix
        ' - X' du titre Google News.

        Google News expose le publisher de deux façons selon les flux :
        - balise `<source>Reuters</source>` → `entry.source.title` (FeedParserDict)
        - colle ` - Reuters` à la fin du `<title>`

        On tente la balise d'abord (canonique), puis le suffix en fallback,
        sinon `unknown`.
        """
        try:
            title = entry.source.title  # FeedParserDict supporte l'attr access
            if title:
                return str(title).strip()
        except (AttributeError, KeyError, TypeError):
            pass
        raw_title = entry.get("title", "") if hasattr(entry, "get") else ""
        if " - " in raw_title:
            return raw_title.rsplit(" - ", 1)[-1].strip()
        return "unknown"

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        url = self._build_url()
        try:
            r = await client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=15.0,
                follow_redirects=True,
            )
            r.raise_for_status()
            content = r.text
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "google_news.fetch.error",
                entity_id=self.entity_id,
                error=str(exc),
            )
            return None

        # feedparser est synchrone — on le détache pour ne pas bloquer la loop.
        feed = await asyncio.to_thread(feedparser.parse, content)

        entries = list(feed.entries or [])[: self.limit]
        if not entries:
            log.info(
                "google_news.fetch.empty",
                entity_id=self.entity_id,
                query=self.query,
            )
            return None

        # Réarme le circuit breaker du classifier en début de batch.
        self.classifier.reset_batch()

        n_bullish = 0
        n_bearish = 0
        n_neutral = 0
        publishers: list[str] = []
        for entry in entries:
            title = entry.get("title", "") if hasattr(entry, "get") else ""
            publishers.append(self._extract_publisher(entry))
            n_bull, n_bear = await self.classifier.classify(title)
            if n_bull > n_bear:
                n_bullish += 1
            elif n_bear > n_bull:
                n_bearish += 1
            else:
                n_neutral += 1

        n_classified = n_bullish + n_bearish
        score = (n_bullish - n_bearish) / n_classified if n_classified > 0 else 0.0

        top_publishers = [
            {"name": name, "count": count}
            for name, count in Counter(publishers).most_common(5)
        ]

        return {
            "source": "google_news_rss",
            "method": self.classifier.method_name,
            "entity_id": self.entity_id,
            "query": self.query,
            "score": round(score, 4),
            "n_articles": len(entries),
            "n_bullish": n_bullish,
            "n_bearish": n_bearish,
            "n_neutral": n_neutral,
            "top_publishers": top_publishers,
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        }

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                point = await self._fetch(client)
                if point is not None:
                    payload = json.dumps(point)
                    key = REDIS_KEY_TPL.format(entity=self.entity_id.lower())
                    await self.redis.setex(key, REDIS_TTL_S, payload)
                    await self.redis.publish(key, payload)
                    top = (
                        point["top_publishers"][0]["name"]
                        if point["top_publishers"]
                        else None
                    )
                    log.info(
                        "google_news.published",
                        entity_id=self.entity_id,
                        method=point["method"],
                        score=point["score"],
                        n_bullish=point["n_bullish"],
                        n_bearish=point["n_bearish"],
                        n_neutral=point["n_neutral"],
                        top_publisher=top,
                    )
                await asyncio.sleep(self.interval_s)
