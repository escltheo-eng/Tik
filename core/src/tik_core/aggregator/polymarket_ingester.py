"""Polymarket ingester (couche 8 — marchés prédictifs, MODE SHADOW).

⚠ SHADOW STRICT (cf. backlog-osint.md « règle SHADOW vs ENRÔLEMENT » 2026-05-24).
Cet ingester collecte les probabilités implicites des marchés BTC de Polymarket
(« money on the line ») et les stocke dans Redis. Il N'EST PAS branché sur le
`combined_bias` des engines : aucun `_enrich_with_polymarket` n'existe dans
swing_engine/flash_engine, et les engines lisent des clés Redis EXPLICITES
(vérifié 2026-05-23) → la clé `tik.sentiment.polymarket.btc` n'influence aucun
signal. Pour le retirer : enlever cet ingester de run_ingesters.py.

But du shadow : construire l'historique nécessaire pour mesurer plus tard la
valeur prédictive (IC Spearman / hit rate / gain) AVANT tout enrôlement. On ne
dérive volontairement AUCUN bias ici — on stocke les échelles de seuils brutes ;
la logique de dérivation se décidera à l'enrôlement (quand on saura ce qui
prédit). Cf. Tik n'a aucun edge directionnel démontré à ce jour (Paquet 33/35).

Source : Gamma API publique (https://gamma-api.polymarket.com), sans clé.
Marchés ciblés (familles de seuils à horizon swing) :
  - « Bitcoin above ___ on <date>? »      (échelle de niveau quotidienne)
  - « What price will Bitcoin hit in <X>? » (échelle de touch mensuelle/hebdo)
  - « Bitcoin price on <date>? »            (échelle quotidienne)
Exclus : « Up or Down » (fenêtres 5 min intraday, trop bruité pour le swing).
"""

import asyncio
import json
import re
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
REDIS_KEY = "tik.sentiment.polymarket.btc"  # snapshot courant
REDIS_HISTORY_KEY = "tik.polymarket.btc.history"  # série temporelle (liste cappée)
REDIS_TTL_S = 6 * 3600
HISTORY_MAX = 5000  # ~7 mois à 1 snapshot/heure

_USD_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*([kKmM]?)")


def _parse_outcome_prices(raw: object) -> tuple[float, float] | None:
    """Extrait (prob_yes, prob_no) depuis outcomePrices (string JSON ou liste)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, list | tuple) or len(raw) < 2:
        return None
    try:
        return (float(raw[0]), float(raw[1]))
    except (TypeError, ValueError):
        return None


def _parse_threshold_usd(question: str | None) -> float | None:
    """Extrait le seuil en USD d'une question (« ...above $68,000 on... » → 68000).

    Gère « $115,000 », « $150k », « $1m ». Retourne None si pas de montant.
    """
    if not question:
        return None
    m = _USD_RE.search(question)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = m.group(2).lower()
    if suffix == "k":
        val *= 1_000
    elif suffix == "m":
        val *= 1_000_000
    return val


def _first_clob_token_id(raw: object) -> str | None:
    """1er clobTokenId (token « Yes ») — utile pour fetcher l'historique officiel."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if isinstance(raw, list | tuple) and raw:
        return str(raw[0])
    return None


def _is_relevant_btc_event(title: str | None) -> bool:
    """Garde les familles de seuils BTC à horizon swing, exclut l'intraday 5 min."""
    if not title:
        return False
    t = title.lower()
    if "bitcoin" not in t and "btc" not in t:
        return False
    if "up or down" in t:  # fenêtres 5 min intraday, hors horizon swing
        return False
    return (
        ("above" in t and " on " in t)
        or "what price will bitcoin hit" in t
        or "bitcoin price on" in t
    )


def _build_market_entry(market: dict) -> dict | None:
    """Une ligne de seuil : question, seuil $, prob Yes/No, volume, token id."""
    prices = _parse_outcome_prices(market.get("outcomePrices"))
    if prices is None:
        return None
    vol = market.get("volume")
    try:
        vol = float(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol = None
    return {
        "question": market.get("question"),
        "threshold_usd": _parse_threshold_usd(market.get("question")),
        "yes_prob": prices[0],
        "no_prob": prices[1],
        "volume": vol,
        "clob_token_id": _first_clob_token_id(market.get("clobTokenIds")),
    }


def _build_snapshot(events: list[dict], fetched_at_iso: str) -> dict:
    """Snapshot brut : par event pertinent, l'échelle de seuils + volumes."""
    out_events: list[dict] = []
    for ev in events:
        if not _is_relevant_btc_event(ev.get("title")):
            continue
        entries = [
            e for m in (ev.get("markets") or []) if (e := _build_market_entry(m)) is not None
        ]
        if not entries:
            continue
        total_vol = sum(e["volume"] for e in entries if e["volume"] is not None)
        out_events.append(
            {
                "title": ev.get("title"),
                "slug": ev.get("slug"),
                "end_date": ev.get("endDate"),
                "n_markets": len(entries),
                "total_volume": total_vol,
                "markets": entries,
            }
        )
    return {
        "source": "polymarket",
        "mode": "shadow",
        "fetched_at": fetched_at_iso,
        "n_events": len(out_events),
        "total_volume": sum(e["total_volume"] for e in out_events),
        "events": out_events,
    }


class PolymarketIngester(BaseIngester):
    """Polle les marchés prédictifs BTC de Polymarket (SHADOW, non branché engines)."""

    name = "polymarket_ingester"
    layer = 8

    def __init__(self, redis: Redis, interval_s: int = 3600) -> None:
        self.redis = redis
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("polymarket.ingester.started", interval_s=self.interval_s, mode="shadow")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("polymarket.ingester.stopped")

    async def _fetch_and_build(self, client: httpx.AsyncClient) -> dict | None:
        try:
            r = await client.get(
                SEARCH_URL, params={"q": "bitcoin", "limit_per_type": 25}, timeout=15.0
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("polymarket.fetch.error", error=str(exc))
            return None
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list):
            log.warning("polymarket.parse.error", reason="no_events_list")
            return None
        return _build_snapshot(events, datetime.now(tz=UTC).isoformat())

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                snap = await self._fetch_and_build(client)
                if snap is not None and snap["n_events"] > 0:
                    payload = json.dumps(snap)
                    try:
                        await self.redis.setex(REDIS_KEY, REDIS_TTL_S, payload)
                        await self.redis.lpush(REDIS_HISTORY_KEY, payload)
                        await self.redis.ltrim(REDIS_HISTORY_KEY, 0, HISTORY_MAX - 1)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("polymarket.redis.error", error=str(exc))
                    log.info(
                        "polymarket.published",
                        n_events=snap["n_events"],
                        total_volume=round(snap["total_volume"], 0),
                    )
                await asyncio.sleep(self.interval_s)
