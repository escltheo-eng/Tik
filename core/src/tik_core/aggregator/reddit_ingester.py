"""Reddit JSON ingester (couche 6 — sentiment textuel retail BTC).

Source publique gratuite, sans clé pour read-only, ~60 req/min anonyme.
Polling toutes les 30 min sur 2 subs (r/Bitcoin + r/CryptoMarkets), agrégés
en un score net pondéré par log(score+1) après filtrage stickied / NSFW /
score < 5.

Voir ADR-009 pour la justification des choix structurants (subs, pondération
log, mitigation brigading via filtres conservateurs).

Pas de Reddit pour GOLD : r/Gold trop petit, r/wallstreetbets trop bruité
et mal calibré pour le LLM 3B (ironie + argot WSB). GDELT évalué en
Session 3 comme alternative macro/géopol pour GOLD.

Champ `headlines` (Phase 1 trading manuel J+10) : liste des titres bruts
classifiés, persistée dans le payload Redis aux côtés des agrégats. Cap
local à `MAX_HEADLINES = 25`. Le calcul du score reste strictement
inchangé — additif uniquement.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import Counter
from datetime import datetime, timezone

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.aggregator.news_classifier import NewsClassifier

log = structlog.get_logger()

REDDIT_LISTING_TPL = "https://www.reddit.com/r/{sub}/hot.json"
USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"
REDIS_TTL_S = 2 * 3600  # 2h, comme les autres sources textuelles
REDIS_KEY_TPL = "tik.sentiment.reddit.{entity}"
MIN_SCORE_THRESHOLD = 5  # filtre brigading bas étage (cf. ADR-009 décision 3)
MAX_HEADLINES = 25


class RedditIngester(BaseIngester):
    """Polle Reddit `hot` sur N subs et calcule un score net pondéré par log(score+1)."""

    name = "reddit_ingester"
    layer = 6

    def __init__(
        self,
        redis: Redis,
        classifier: NewsClassifier,
        entity_id: str,
        subreddits: list[str],
        interval_s: int = 1800,
        limit_per_sub: int = 50,
        min_score: int = MIN_SCORE_THRESHOLD,
    ) -> None:
        self.redis = redis
        self.classifier = classifier
        self.entity_id = entity_id
        self.subreddits = list(subreddits)
        self.interval_s = interval_s
        self.limit_per_sub = limit_per_sub
        self.min_score = min_score
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "reddit.ingester.started",
            entity_id=self.entity_id,
            subreddits=self.subreddits,
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
        log.info("reddit.ingester.stopped", entity_id=self.entity_id)

    async def _fetch_sub(
        self, client: httpx.AsyncClient, sub: str
    ) -> list[dict] | None:
        """Fetch un sub. Retourne la liste de `children` ou None si erreur.

        Si un sub fail (réseau, 503, payload invalide), on log un warning
        et on retourne None — la boucle agrégée continue avec les autres
        subs (résilience par sub).
        """
        url = REDDIT_LISTING_TPL.format(sub=sub)
        try:
            r = await client.get(
                url,
                headers={"User-Agent": USER_AGENT},
                params={"limit": self.limit_per_sub},
                timeout=15.0,
                follow_redirects=True,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "reddit.fetch.error",
                entity_id=self.entity_id,
                sub=sub,
                error=str(exc),
            )
            return None

        try:
            children = data["data"]["children"]
        except (KeyError, TypeError):
            log.warning("reddit.parse.invalid_payload", sub=sub)
            return None

        return children

    @staticmethod
    def _filter_post(post_data: dict, min_score: int) -> bool:
        """True si le post est gardé pour classification.

        Filtres ADR-009 (mitigation brigading) :
        - stickied (post épinglé par mods, non représentatif)
        - over_18 (NSFW, pollution)
        - score < min_score (signal communautaire trop faible / facilement manipulable)
        """
        if post_data.get("stickied"):
            return False
        if post_data.get("over_18"):
            return False
        try:
            score = int(post_data.get("score", 0))
        except (TypeError, ValueError):
            return False
        return score >= min_score

    @staticmethod
    def _verdict_to_value(n_bull: int, n_bear: int) -> int:
        """Convertit le couple (n_bull, n_bear) du classifier en verdict trinaire."""
        if n_bull > n_bear:
            return 1
        if n_bear > n_bull:
            return -1
        return 0

    @staticmethod
    def _verdict_value_to_sentiment(verdict: int) -> str:
        """Convertit un verdict trinaire (-1/0/+1) en label string."""
        if verdict > 0:
            return "bull"
        if verdict < 0:
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
    def _build_permalink(permalink: str | None) -> str | None:
        """Reconstruit l'URL absolue d'un thread Reddit depuis le permalink relatif.

        Reddit JSON expose `permalink: /r/Bitcoin/comments/abc/title/` — on
        préfixe `https://www.reddit.com` pour avoir une URL cliquable.
        Préféré à `pdata["url"]` qui pointe parfois vers une ressource externe
        (image, vidéo, article relayé) plutôt que le thread lui-même.
        """
        if not permalink:
            return None
        s = str(permalink)
        if s.startswith("http"):
            return s
        if not s.startswith("/"):
            s = "/" + s
        return f"https://www.reddit.com{s}"

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        # 1. Récupérer les posts de tous les subs, filtrer
        all_posts: list[tuple[str, dict]] = []
        for sub in self.subreddits:
            children = await self._fetch_sub(client, sub)
            if not children:
                continue
            for c in children:
                if c.get("kind") != "t3":
                    continue
                pdata = c.get("data") or {}
                if self._filter_post(pdata, self.min_score):
                    all_posts.append((sub, pdata))

        if not all_posts:
            log.info(
                "reddit.fetch.empty_after_filter",
                entity_id=self.entity_id,
                subreddits=self.subreddits,
            )
            return None

        # 2. Classifier batch (réarmer le circuit breaker du classifier d'abord)
        self.classifier.reset_batch()

        n_bullish = 0
        n_bearish = 0
        n_neutral = 0
        weighted_numerator = 0.0
        weighted_denominator = 0.0
        sub_distribution: list[str] = []
        headlines: list[dict] = []
        fetched_at = datetime.now(tz=timezone.utc).isoformat()

        for sub, pdata in all_posts:
            title = pdata.get("title", "") or ""
            try:
                score = int(pdata.get("score", 0))
            except (TypeError, ValueError):
                score = 0
            n_bull, n_bear = await self.classifier.classify(title)
            verdict = self._verdict_to_value(n_bull, n_bear)
            sentiment = self._verdict_value_to_sentiment(verdict)
            if verdict > 0:
                n_bullish += 1
            elif verdict < 0:
                n_bearish += 1
            else:
                n_neutral += 1
            weight = math.log(score + 1)
            weighted_numerator += weight * verdict
            weighted_denominator += weight
            sub_distribution.append(sub)
            if len(headlines) < MAX_HEADLINES:
                headlines.append(
                    {
                        "title": str(title).strip(),
                        "url": self._build_permalink(pdata.get("permalink")),
                        "publisher": f"r/{sub}",
                        "sentiment": sentiment,
                        "published_at": self._parse_unix_iso(pdata.get("created_utc")),
                        "fetched_at": fetched_at,
                    }
                )

        # 3. Score net pondéré ∈ [-1, +1]
        score_net = (
            weighted_numerator / weighted_denominator
            if weighted_denominator > 0
            else 0.0
        )

        top_subs = [
            {"name": name, "count": count}
            for name, count in Counter(sub_distribution).most_common(5)
        ]

        return {
            "source": "reddit_btc",
            "method": self.classifier.method_name,
            "entity_id": self.entity_id,
            "subreddits": self.subreddits,
            "score": round(score_net, 4),
            "n_articles": len(all_posts),
            "n_bullish": n_bullish,
            "n_bearish": n_bearish,
            "n_neutral": n_neutral,
            "top_subreddits": top_subs,
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
                    await self.redis.setex(key, REDIS_TTL_S, payload)
                    await self.redis.publish(key, payload)
                    top = (
                        point["top_subreddits"][0]["name"]
                        if point["top_subreddits"]
                        else None
                    )
                    log.info(
                        "reddit.published",
                        entity_id=self.entity_id,
                        method=point["method"],
                        score=point["score"],
                        n_articles=point["n_articles"],
                        n_bullish=point["n_bullish"],
                        n_bearish=point["n_bearish"],
                        n_neutral=point["n_neutral"],
                        n_headlines=len(point["headlines"]),
                        top_sub=top,
                    )
                await asyncio.sleep(self.interval_s)
