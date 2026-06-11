"""GDELT tone overlay ingester (couche 6 — sentiment news macro/géopol GOLD).

Premier overlay Tik à NE PAS passer par `OllamaClassifier` (cf. ADR-010).
Consomme le tone GDELT brut (calculé scientifiquement par GDELT 2.0)
plutôt que de classifier les titres nous-mêmes — diversification
méthodologique intentionnelle :

- Sentiment Ollama-LLM (llama3.2:3b) : CryptoCompare, Google News, Reddit
- Sentiment NLP scientifique GDELT : ce ingester (GOLD)

Source : GDELT 2.0 Doc API (https://api.gdeltproject.org/api/v2/doc/doc),
mode `timelinetone`, query `"gold price"`, filtre `sourcelang:eng`,
timespan 24 h. Polling toutes les 30 min.

Le tone brut [-10, +10] est mappé contrarian dans `_compute_gdelt_bias`
côté swing engine : tone négatif (tensions globales) → bull GOLD (safe
haven). Cohérent avec FG sur BTC (panique → contrarian bull crypto).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
# UA descriptif (pas un déguisement navigateur) — GDELT et autres APIs
# publiques de recherche tolèrent mieux les UAs identifiables que les UAs
# génériques type "Mozilla/5.0" qui peuvent déclencher des filtres anti-bot.
USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"
REDIS_TTL_S = 6 * 3600  # 6 h — garde le dernier tone valide malgré les 429 GDELT
# fréquents (~75 % d'échec mesuré 2026-06-11). Le tone est un agrégat journalier
# (timespan=1d) → une staleness ≤ 6 h est sans conséquence sur l'horizon swing 5 j,
# et réduit fortement les trous GDELT côté GOLD swing (était absent ~37 % du temps).
REDIS_KEY_TPL = "tik.sentiment.gdelt.{entity}"


class GdeltIngester(BaseIngester):
    """Polle GDELT timelinetone et publie le tone moyen + nombre d'articles agrégés.

    Pas de classifier injecté — utilise le tone brut calculé par GDELT.
    """

    name = "gdelt_ingester"
    layer = 6

    def __init__(
        self,
        redis: Redis,
        entity_id: str,
        query: str,
        timespan: str = "1d",
        lang: str = "eng",
        interval_s: int = 1800,
    ) -> None:
        self.redis = redis
        self.entity_id = entity_id
        self.query = query
        self.timespan = timespan
        self.lang = lang
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "gdelt.ingester.started",
            entity_id=self.entity_id,
            query=self.query,
            timespan=self.timespan,
            lang=self.lang,
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
        log.info("gdelt.ingester.stopped", entity_id=self.entity_id)

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        # GDELT V2 Doc API : la langue se filtre dans la query elle-même
        # via `sourcelang:eng`, pas via un paramètre séparé.
        params = {
            "query": f"{self.query} sourcelang:{self.lang}",
            "mode": "timelinetone",
            "format": "json",
            "timespan": self.timespan,
        }
        try:
            r = await client.get(
                GDELT_DOC_API_URL,
                params=params,
                headers={"User-Agent": USER_AGENT},
                timeout=20.0,
                follow_redirects=True,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "gdelt.fetch.error",
                entity_id=self.entity_id,
                error=str(exc),
            )
            return None

        # Format `timelinetone` :
        # {"timeline": [{"series": "...", "data": [{"date": "...", "value": -1.23}, ...]}]}
        valid_points = self._extract_tone_points(data)
        if not valid_points:
            log.info(
                "gdelt.fetch.no_valid_points",
                entity_id=self.entity_id,
                query=self.query,
            )
            return None

        avg_tone = sum(valid_points) / len(valid_points)

        return {
            "source": "gdelt_news",
            "method": "gdelt_tone_v2",
            "entity_id": self.entity_id,
            "query": self.query,
            "lang": self.lang,
            "timespan": self.timespan,
            "tone": round(avg_tone, 4),
            "n_points": len(valid_points),
            "fetched_at": datetime.now(tz=UTC).isoformat(),
        }

    @staticmethod
    def _extract_tone_points(data: dict) -> list[float]:
        """Extrait les valeurs de tone numériques du payload GDELT timelinetone.

        Tolère les variations de format (séries multiples, points malformés,
        valeurs non numériques) — on ignore silencieusement les entrées invalides.
        """
        valid_points: list[float] = []
        timeline = data.get("timeline") or []
        if not isinstance(timeline, list):
            return valid_points
        for series in timeline:
            if not isinstance(series, dict):
                continue
            entries = series.get("data") or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    valid_points.append(float(entry.get("value")))
                except (TypeError, ValueError):
                    continue
        return valid_points

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                point = await self._fetch(client)
                if point is not None:
                    payload = json.dumps(point)
                    key = REDIS_KEY_TPL.format(entity=self.entity_id.lower())
                    await self.redis.setex(key, REDIS_TTL_S, payload)
                    await self.redis.publish(key, payload)
                    log.info(
                        "gdelt.published",
                        entity_id=self.entity_id,
                        tone=point["tone"],
                        n_points=point["n_points"],
                        timespan=point["timespan"],
                    )
                await asyncio.sleep(self.interval_s)
