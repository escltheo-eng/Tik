"""CryptoCompare news ingester (couche 6 — news / sentiment textuel).

Le système de votes upvotes/downvotes a été déprécié après le rachat
de CryptoCompare par CoinDesk en 2022. On utilise donc une analyse par
mots-clés sur les titres pour déduire un score de sentiment net.

API CryptoCompare (rebranded CoinDesk Data) : free tier ~11k req/mois,
plafond 250k à vie. On polle 1 fois par heure (≈720 req/mois).

Évolution future : remplacer cette heuristique simple par un vrai modèle
NLP (FinBERT, ou un LLM local via Ollama).
"""

import asyncio
import json
import re
from datetime import datetime, timezone

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"
REDIS_TTL_S = 2 * 3600  # 2h, plus court que FG car les news bougent vite

# Listes volontairement courtes mais distinctives (anglais uniquement, on
# filtre lang=EN sur l'API). Match par "le mot apparaît dans le titre".
# Enrichies 2026-04-29 après analyse de 20 titres réels qui montraient des
# faux négatifs (bottoming = bull contextuel, ease = bull) et faux positifs
# (lowers target = bear malgré "outperform" en suite).
BULLISH_KEYWORDS: set[str] = {
    # Direction haussière classique
    "surge", "surges", "soar", "soars", "rally", "rallies", "jump", "jumps",
    "gain", "gains", "rise", "rises", "rising", "rose", "climb", "climbs",
    "advance", "rebound", "rebounds", "recover", "recovers", "recovery",
    "skyrocket",
    # Marqueurs bull / accumulation
    "bull", "bullish", "moon", "pump", "breakthrough", "milestone", "record",
    "ath", "high", "uptrend", "bullrun",
    "accumulate", "accumulating", "accumulation",
    # Retournement / fin de baisse
    "bottom", "bottoming", "ease", "eases", "easing",
    "support", "supports", "supporting",
    # Régulation / institutionnels positifs
    "approval", "approve", "approved", "adopt", "adoption",
    "launch", "launches", "partnership", "upgrade", "upgrades",
    # Sentiment positif
    "boost", "boosts", "outperform", "optimistic", "optimism",
    "confidence", "win", "wins", "winning",
}

BEARISH_KEYWORDS: set[str] = {
    # Direction baissière classique
    "crash", "crashes", "plunge", "plunges", "dump", "dumps", "drop", "drops",
    "fall", "falls", "fell", "collapse", "collapses", "tumble", "tumbles",
    "slump", "slumps", "slip", "slips", "slide", "slides", "decline", "declines",
    # Marqueurs bear
    "bear", "bearish", "fear", "panic", "selloff", "sell-off",
    "loss", "losses", "downtrend", "pessimistic", "weak", "weakness",
    # Révisions à la baisse / downgrades
    "lowers", "lowered", "cuts", "downgrade", "downgrades",
    # Régulation / juridique négatifs
    "ban", "banned", "bans", "crackdown", "lawsuit", "sue", "sued", "sues",
    "prison", "arrest", "arrested", "shutdown",
    "delist", "delisted", "freeze", "freezes",
    # Crime / risque
    "hack", "hacked", "exploit", "scam", "fraud", "breach",
    "liquidation", "liquidate", "liquidated", "bankruptcy", "insolvency",
    # Sentiment négatif
    "warning", "concern", "concerns", "risk", "risks", "crisis",
}

# Tokeniseur simple : extrait les "mots" (lettres + apostrophes/tirets internes).
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*")


def _classify_title(title: str) -> tuple[int, int]:
    """Compte combien de keywords bull/bear apparaissent dans un titre.

    Retourne (n_bullish, n_bearish). Les comptages sont dédupliqués par mot
    (un titre "bull bullish bull" compte 2, pas 3).
    """
    if not title:
        return 0, 0
    words = {w.lower() for w in WORD_RE.findall(title)}
    return len(words & BULLISH_KEYWORDS), len(words & BEARISH_KEYWORDS)


class CryptoCompareIngester(BaseIngester):
    """Polle CryptoCompare news et calcule un score sentiment net via keywords."""

    name = "cryptocompare_ingester"
    layer = 6

    def __init__(
        self,
        redis: Redis,
        api_key: str,
        currency: str = "BTC",
        interval_s: int = 3600,
    ) -> None:
        self.redis = redis
        self.api_key = api_key
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
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("cryptocompare.ingester.stopped")

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

        n_bullish = 0
        n_bearish = 0
        n_neutral = 0
        for a in articles:
            n_bull, n_bear = _classify_title(a.get("title", ""))
            if n_bull > n_bear:
                n_bullish += 1
            elif n_bear > n_bull:
                n_bearish += 1
            else:
                n_neutral += 1

        n_classified = n_bullish + n_bearish
        score = (n_bullish - n_bearish) / n_classified if n_classified > 0 else 0.0

        return {
            "source": "cryptocompare_news",
            "method": "title_keywords",
            "currency": self.currency,
            "score": round(score, 4),
            "n_articles": len(articles),
            "n_bullish": n_bullish,
            "n_bearish": n_bearish,
            "n_neutral": n_neutral,
            "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
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
                        score=point["score"],
                        n_bullish=point["n_bullish"],
                        n_bearish=point["n_bearish"],
                        n_neutral=point["n_neutral"],
                    )
                await asyncio.sleep(self.interval_s)
