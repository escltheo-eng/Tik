"""Polymarket ingester (couche 8 — marchés prédictifs, MODE SHADOW).

⚠ SHADOW STRICT (cf. backlog-osint.md « règle SHADOW vs ENRÔLEMENT » 2026-05-24).
Cet ingester collecte les probabilités implicites des marchés Polymarket
(« money on the line ») pour BTC **et GOLD** et les stocke dans Redis. Il
N'EST PAS branché sur le `combined_bias` des engines : aucun
`_enrich_with_polymarket` n'existe dans swing_engine/flash_engine, et les
engines lisent des clés Redis EXPLICITES (vérifié 2026-05-23) → les clés
`tik.sentiment.polymarket.{btc,gold}` n'influencent aucun signal. Pour le
retirer : enlever ces ingesters de run_ingesters.py.

GOLD ajouté le 2026-05-28 (Polymarket a des marchés OR riches et liquides :
« What will Gold (GC) hit by end of June? » à plusieurs M$ de volume). Sert
de **contexte de marché** pour le trader manuel, l'or étant léger côté signaux
Tik depuis la désactivation DXY/COT (ADR-018 P2). Reste un contexte, pas un
signal directionnel : la règle « ne pas trader le GOLD sur les signaux Tik »
tient (cf. Garde-fou 2-bis).

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
import math
import re
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

SEARCH_URL = "https://gamma-api.polymarket.com/public-search"
# Clés Redis par entité (snapshot courant + série temporelle cappée).
BTC_REDIS_KEY = "tik.sentiment.polymarket.btc"
BTC_HISTORY_KEY = "tik.polymarket.btc.history"
GOLD_REDIS_KEY = "tik.sentiment.polymarket.gold"
GOLD_HISTORY_KEY = "tik.polymarket.gold.history"
REDIS_TTL_S = 6 * 3600
HISTORY_MAX = 5000  # ~7 mois à 1 snapshot/heure
# Caps défensifs (audit 2026-05-24 H4) : on ne fait pas confiance au
# limit_per_type de l'API pour borner le payload. Un payload anormalement gros
# × HISTORY_MAX saturerait Redis (noeviction) → tout Tik tombe.
MAX_EVENTS = 30
MAX_MARKETS_PER_EVENT = 60
MAX_PAYLOAD_BYTES = 200_000

# Le suffixe multiplicateur (k/m) doit coller au nombre ET ne pas être suivi
# d'une lettre. Sinon « ...$84,000 May 25-31? » capte le « M » de « May » comme
# « million » → seuil aberrant 8,4e10 (bug shadow Polymarket trouvé 2026-05-27,
# familles « reach/dip $X <plage de dates> » sans « on »/« in »). Pas de \s*
# entre le nombre et le suffixe + lookahead négatif sur une lettre.
_USD_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)([kKmM]?)(?![A-Za-z])")


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


def _is_relevant_gold_event(title: str | None) -> bool:
    """Garde les familles de seuils OR à horizon swing, exclut l'intraday up/down.

    Familles observées (Gamma API, 2026-05-28) : « What will Gold (GC) hit by
    end of <mois>? », « What will Gold (XAUUSD) hit in <mois>? », « What will
    Gold (GC) settle at in <mois>? », « Gold (GC) above ___ end of <mois>? »,
    « Will Gold hit $X before <mois>? ».
    """
    if not title:
        return False
    t = title.lower()
    if "gold" not in t and "xauusd" not in t:
        return False
    if "up or down" in t:  # fenêtres intraday, hors horizon swing
        return False
    return (
        ("above" in t and ("end of" in t or " on " in t))
        or "what will gold" in t
        or "what price will gold" in t
        or ("hit" in t and ("end of" in t or "before" in t or " in " in t))
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
    # Rejette inf/nan : json.dumps lève dessus, ce qui tuerait la task _run
    # (audit 2026-05-24 H4).
    if vol is not None and not math.isfinite(vol):
        vol = None
    return {
        "question": market.get("question"),
        "threshold_usd": _parse_threshold_usd(market.get("question")),
        "yes_prob": prices[0],
        "no_prob": prices[1],
        "volume": vol,
        "clob_token_id": _first_clob_token_id(market.get("clobTokenIds")),
    }


def _build_snapshot(
    events: list[dict],
    fetched_at_iso: str,
    relevant_fn=_is_relevant_btc_event,
    *,
    entity: str = "BTC",
) -> dict:
    """Snapshot brut : par event pertinent, l'échelle de seuils + volumes.

    `relevant_fn` filtre les events selon l'entité (BTC par défaut, rétrocompat).
    Les events explicitement résolus (`closed=True`) sont écartés : leurs cotes
    sont figées à 0/1 → inutiles comme contexte et bruit pour la mesure shadow.
    """
    out_events: list[dict] = []
    for ev in events:
        if len(out_events) >= MAX_EVENTS:
            break
        if ev.get("closed") is True:  # marché résolu : cotes figées, on écarte
            continue
        if not relevant_fn(ev.get("title")):
            continue
        markets = (ev.get("markets") or [])[:MAX_MARKETS_PER_EVENT]
        entries = [e for m in markets if (e := _build_market_entry(m)) is not None]
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
        "entity": entity,
        "mode": "shadow",
        "fetched_at": fetched_at_iso,
        "n_events": len(out_events),
        "total_volume": sum(e["total_volume"] for e in out_events),
        "events": out_events,
    }


# Config par entité : requête de recherche, clés Redis, filtre de pertinence.
ENTITY_CONFIGS: dict[str, dict] = {
    "BTC": {
        "query": "bitcoin",
        "redis_key": BTC_REDIS_KEY,
        "history_key": BTC_HISTORY_KEY,
        "relevant_fn": _is_relevant_btc_event,
    },
    "GOLD": {
        "query": "gold",
        "redis_key": GOLD_REDIS_KEY,
        "history_key": GOLD_HISTORY_KEY,
        "relevant_fn": _is_relevant_gold_event,
    },
}


class PolymarketIngester(BaseIngester):
    """Polle les marchés prédictifs Polymarket par entité (SHADOW, non branché engines)."""

    name = "polymarket_ingester"
    layer = 8

    def __init__(self, redis: Redis, entity: str = "BTC", interval_s: int = 3600) -> None:
        if entity not in ENTITY_CONFIGS:
            raise ValueError(f"unknown polymarket entity {entity!r}")
        cfg = ENTITY_CONFIGS[entity]
        self.redis = redis
        self.entity = entity
        self.query: str = cfg["query"]
        self.redis_key: str = cfg["redis_key"]
        self.history_key: str = cfg["history_key"]
        self.relevant_fn = cfg["relevant_fn"]
        self.interval_s = interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "polymarket.ingester.started",
            entity=self.entity,
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
        log.info("polymarket.ingester.stopped")

    async def _fetch_and_build(self, client: httpx.AsyncClient) -> dict | None:
        try:
            r = await client.get(
                SEARCH_URL, params={"q": self.query, "limit_per_type": 25}, timeout=15.0
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("polymarket.fetch.error", entity=self.entity, error=str(exc))
            return None
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list):
            log.warning("polymarket.parse.error", entity=self.entity, reason="no_events_list")
            return None
        return _build_snapshot(
            events,
            datetime.now(tz=UTC).isoformat(),
            self.relevant_fn,
            entity=self.entity,
        )

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                snap = await self._fetch_and_build(client)
                if snap is not None and snap["n_events"] > 0:
                    try:
                        # json.dumps DANS le try : il lève sur inf/nan résiduel,
                        # ce qui tuerait la task _run sinon (audit 2026-05-24 H4).
                        payload = json.dumps(snap)
                        if len(payload) > MAX_PAYLOAD_BYTES:
                            log.warning(
                                "polymarket.payload_too_large",
                                entity=self.entity,
                                size=len(payload),
                                n_events=snap["n_events"],
                            )
                        else:
                            await self.redis.setex(self.redis_key, REDIS_TTL_S, payload)
                            await self.redis.lpush(self.history_key, payload)
                            await self.redis.ltrim(self.history_key, 0, HISTORY_MAX - 1)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("polymarket.redis.error", entity=self.entity, error=str(exc))
                    log.info(
                        "polymarket.published",
                        entity=self.entity,
                        n_events=snap["n_events"],
                        total_volume=round(snap["total_volume"], 0),
                    )
                await asyncio.sleep(self.interval_s)
