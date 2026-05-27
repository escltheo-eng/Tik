"""CoinGecko community sentiment ingester (couche 7 — sentiment crypto, MODE SHADOW).

⚠ SHADOW (ADR-021) : collecte le vote communautaire haussier/baissier de la page
BTC de CoinGecko (`sentiment_votes_up_percentage`) et le stocke dans Redis.
L'overlay swing correspondant (`_enrich_with_coingecko` dans swing_engine) est
DÉSACTIVÉ par défaut via `settings.coingecko_overlay_enabled` (toggle env
`TIK_COINGECKO_OVERLAY_ENABLED`). Tant que le toggle est OFF, cette clé Redis
n'influence AUCUN signal — elle ne fait qu'accumuler de l'historique.

But du shadow : mesurer si ce sentiment diverge vraiment du Fear & Greed (apport
d'information indépendant ?) AVANT de l'enrôler dans le `combined_bias`.

Contexte : Reddit IP-banni depuis le déploiement HP (Bug 11) → BTC tourne à 3/4
overlays sentiment. CoinGecko est le seul candidat gratuit JOIGNABLE depuis ce
VPS (mesuré 2026-05-27 : HN quasi vide pour BTC, StockTwits/Bluesky bloqués 403).

Source : API publique CoinGecko (https://api.coingecko.com/api/v3), sans clé.
Un appel/heure, largement sous les limites du free tier public.
"""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/bitcoin"
COINGECKO_PARAMS = {
    "localization": "false",
    "tickers": "false",
    "market_data": "false",
    "community_data": "true",
    "developer_data": "false",
    "sparkline": "false",
}
USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"
REDIS_KEY = "tik.sentiment.coingecko.btc"  # snapshot courant
REDIS_HISTORY_KEY = "tik.coingecko.btc.history"  # série temporelle (liste cappée)
REDIS_TTL_S = 25 * 3600  # tolérance au-delà du cycle horaire
HISTORY_MAX = 2000  # ~83 jours à 1 snapshot/heure


def _build_snapshot(data: dict, fetched_at_iso: str) -> dict | None:
    """Extrait le sentiment communautaire d'une réponse CoinGecko /coins/bitcoin.

    `sentiment_votes_up_percentage` est au niveau racine de la réponse.
    Retourne None si le champ est absent / non numérique / hors [0, 100].
    """
    if not isinstance(data, dict):
        return None
    up = data.get("sentiment_votes_up_percentage")
    down = data.get("sentiment_votes_down_percentage")
    try:
        up_pct = float(up) if up is not None else None
        down_pct = float(down) if down is not None else None
    except (TypeError, ValueError):
        return None
    if up_pct is None or not (0.0 <= up_pct <= 100.0):
        return None
    return {
        "source": "coingecko_sentiment",
        "up_pct": up_pct,
        "down_pct": down_pct,
        "fetched_at": fetched_at_iso,
    }


class CoinGeckoSentimentIngester(BaseIngester):
    """Polle le sentiment communautaire CoinGecko BTC et le stocke (SHADOW)."""

    name = "coingecko_sentiment_ingester"
    layer = 7

    def __init__(self, redis: Redis, interval_s: int = 3600) -> None:
        self.redis = redis
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "coingecko_sentiment.ingester.started",
            interval_s=self.interval_s,
            mode="shadow",
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("coingecko_sentiment.ingester.stopped")

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        try:
            r = await client.get(
                COINGECKO_URL,
                params=COINGECKO_PARAMS,
                headers={"User-Agent": USER_AGENT},
                timeout=15.0,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("coingecko_sentiment.fetch.error", error=str(exc))
            return None
        return _build_snapshot(data, datetime.now(tz=UTC).isoformat())

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                snap = await self._fetch(client)
                if snap is not None:
                    try:
                        payload = json.dumps(snap)
                        await self.redis.setex(REDIS_KEY, REDIS_TTL_S, payload)
                        await self.redis.lpush(REDIS_HISTORY_KEY, payload)
                        await self.redis.ltrim(REDIS_HISTORY_KEY, 0, HISTORY_MAX - 1)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("coingecko_sentiment.redis.error", error=str(exc))
                    log.info(
                        "coingecko_sentiment.published",
                        up_pct=snap["up_pct"],
                        down_pct=snap["down_pct"],
                    )
                await asyncio.sleep(self.interval_s)
