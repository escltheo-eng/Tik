"""Hacker News ingester (sentiment textuel tech/crypto BTC) — MODE SHADOW.

Candidat REMPLAÇANT de Reddit (ADR-039) : Reddit est IP-bannie depuis le
2026-05-18 (Bug 11, unban jamais obtenu à ~6 semaines) → BTC swing tourne
durablement avec un overlay sentiment en moins. Hacker News était l'option
préférée du backlog #10 (gratuit, JSON propre, audience tech+crypto).

Source : API Algolia HN Search (https://hn.algolia.com/api/v1/search),
gratuite, sans clé, limites généreuses (~10k req/h documentées — notre
polling 30 min = 48 req/jour, marge ~500×).

SHADOW STRICT (règle « mesurer ≥ 2 semaines avant tout enrôlement ») :
- écrit `tik.sentiment.hackernews.btc` (payload compatible overlays) + un
  historique cappé `tik.sentiment.hackernews.btc.history` pour la future
  mesure (IC / hit rate / gain apparié vs Always SHORT) ;
- il n'existe AUCUN `_enrich_with_hackernews` ni toggle : zéro ligne touchée
  dans les moteurs, le `combined_bias` ne peut pas le voir (NO-GO inchangé) ;
- pas de persistance `headlines` en DB (pas d'apparition dans l'UI) tant que
  la source n'est pas mesurée — retrait = retirer la ligne du runner.

Pondération par log(points+1) et filtre points >= 5, calqués sur Reddit
(ADR-009) pour que la future comparaison Reddit/HN soit à méthode égale.
Pas de détection brigading v1 (mécanique de vote HN différente de Reddit,
seuils non calibrés — à évaluer à la mesure).

⚠ Joignabilité de hn.algolia.com NON vérifiable depuis le bac à sable de dev
(réseau sortant restreint) : à valider sur le VPS au déploiement
(`curl -s "https://hn.algolia.com/api/v1/search?query=bitcoin&tags=story" | head -c 200`).
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.aggregator.news_classifier import NewsClassifier
from tik_core.aggregator.task_supervision import supervise_task

log = structlog.get_logger()

HN_SEARCH_URL = "https://hn.algolia.com/api/v1/search"
USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"
REDIS_TTL_S = 2 * 3600  # 2h, comme les autres sources textuelles
REDIS_KEY_TPL = "tik.sentiment.hackernews.{entity}"
HISTORY_KEY_TPL = "tik.sentiment.hackernews.{entity}.history"
HISTORY_MAX = 2000  # ~40 j à 1 point/30 min — assez pour la mesure ≥ 2 sem
MIN_POINTS_THRESHOLD = 5  # même filtre bas-étage que Reddit (ADR-009)
MAX_HEADLINES = 25
HITS_PER_PAGE = 30
DEFAULT_QUERIES = ("bitcoin", "btc")


class HackerNewsIngester(BaseIngester):
    """Recherche HN (Algolia) et calcule un score net pondéré par log(points+1)."""

    def __init__(
        self,
        redis: Redis,
        classifier: NewsClassifier,
        entity: str = "BTC",
        queries: tuple[str, ...] = DEFAULT_QUERIES,
        interval_s: int = 30 * 60,
        min_points: int = MIN_POINTS_THRESHOLD,
    ) -> None:
        self.redis = redis
        self.classifier = classifier
        self.entity_id = entity
        self.queries = queries
        self.interval_s = interval_s
        self.min_points = min_points
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        supervise_task(self._task, name="hackernews")
        log.info(
            "hackernews.ingester.started",
            entity_id=self.entity_id,
            queries=list(self.queries),
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
            except Exception as exc:  # noqa: BLE001 — task déjà morte : ne pas
                # casser l'arrêt gracieux du runner (audit 2026-07-02)
                log.warning("hackernews.stop.task_error", error=str(exc))
        if hasattr(self.classifier, "aclose"):
            await self.classifier.aclose()

    async def _fetch_query(self, client: httpx.AsyncClient, query: str) -> list[dict] | None:
        """Une recherche Algolia. Toute erreur → None + warning (best-effort)."""
        params = {
            "query": query,
            "tags": "story",
            "hitsPerPage": HITS_PER_PAGE,
            "numericFilters": f"points>={self.min_points}",
        }
        try:
            r = await client.get(
                HN_SEARCH_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=15,
            )
            r.raise_for_status()
            data = r.json()
            hits = data.get("hits") if isinstance(data, dict) else None
            if not isinstance(hits, list):
                log.warning("hackernews.fetch.malformed", query=query)
                return None
            return hits
        except Exception as exc:  # noqa: BLE001
            log.warning("hackernews.fetch.error", query=query, error=str(exc))
            return None

    @staticmethod
    def _verdict_to_value(n_bull: int, n_bear: int) -> int:
        if n_bull > n_bear:
            return 1
        if n_bear > n_bull:
            return -1
        return 0

    @staticmethod
    def _verdict_value_to_sentiment(verdict: int) -> str:
        if verdict > 0:
            return "bullish"
        if verdict < 0:
            return "bearish"
        return "neutral"

    @staticmethod
    def _parse_created_at(value) -> str | None:
        """created_at Algolia est déjà un ISO 8601 — on le garde tel quel."""
        if isinstance(value, str) and value:
            return value
        return None

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        # 1. Récupérer + dédupliquer (les requêtes bitcoin/btc se recouvrent)
        seen_ids: set[str] = set()
        stories: list[dict] = []
        for query in self.queries:
            hits = await self._fetch_query(client, query)
            if not hits:
                continue
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                object_id = str(hit.get("objectID", ""))
                title = hit.get("title") or ""
                if not object_id or object_id in seen_ids or not title:
                    continue
                seen_ids.add(object_id)
                stories.append(hit)

        if not stories:
            log.info("hackernews.fetch.empty", entity_id=self.entity_id)
            return None

        # 2. Classifier batch (même NewsClassifier DI que Reddit/CryptoCompare)
        self.classifier.reset_batch()

        n_bullish = 0
        n_bearish = 0
        n_neutral = 0
        weighted_numerator = 0.0
        weighted_denominator = 0.0
        headlines: list[dict] = []
        fetched_at = datetime.now(tz=UTC).isoformat()

        for hit in stories:
            title = str(hit.get("title", "")).strip()
            try:
                points = int(hit.get("points") or 0)
            except (TypeError, ValueError):
                points = 0
            n_bull, n_bear = await self.classifier.classify(title)
            verdict = self._verdict_to_value(n_bull, n_bear)
            if verdict > 0:
                n_bullish += 1
            elif verdict < 0:
                n_bearish += 1
            else:
                n_neutral += 1
            weight = math.log(points + 1)
            weighted_numerator += weight * verdict
            weighted_denominator += weight
            if len(headlines) < MAX_HEADLINES:
                headlines.append(
                    {
                        "title": title,
                        "url": hit.get("url")
                        or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                        "publisher": "hackernews",
                        "sentiment": self._verdict_value_to_sentiment(verdict),
                        "published_at": self._parse_created_at(hit.get("created_at")),
                        "fetched_at": fetched_at,
                    }
                )

        score_net = weighted_numerator / weighted_denominator if weighted_denominator > 0 else 0.0

        return {
            "source": "hackernews_btc",
            "method": self.classifier.method_name,
            "entity_id": self.entity_id,
            "queries": list(self.queries),
            "score": round(score_net, 4),
            "n_articles": len(stories),
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
                    key = REDIS_KEY_TPL.format(entity=self.entity_id.lower())
                    history_key = HISTORY_KEY_TPL.format(entity=self.entity_id.lower())
                    try:
                        # Écritures Redis protégées (pattern polymarket, audit
                        # 2026-07-02) : une panne Redis transitoire ne tue pas
                        # la boucle, on retentera au cycle suivant.
                        await self.redis.setex(key, REDIS_TTL_S, payload)
                        # Historique pour la future mesure shadow (pas de TTL :
                        # LPUSH + LTRIM cappé, comme Polymarket).
                        await self.redis.lpush(history_key, payload)
                        await self.redis.ltrim(history_key, 0, HISTORY_MAX - 1)
                    except Exception as exc:  # noqa: BLE001
                        log.warning(
                            "hackernews.redis.error",
                            entity_id=self.entity_id,
                            error=str(exc),
                        )
                    log.info(
                        "hackernews.published",
                        entity_id=self.entity_id,
                        method=point["method"],
                        score=point["score"],
                        n_articles=point["n_articles"],
                        n_bullish=point["n_bullish"],
                        n_bearish=point["n_bearish"],
                        n_neutral=point["n_neutral"],
                    )
                await asyncio.sleep(self.interval_s)
