"""Collecte d'un dataset 'golden' pour calibrer les sources sentiment Tik.

Refetch on-the-fly N items textuels par asset depuis les sources de
production (Google News BTC + GOLD, CryptoCompare BTC, Reddit BTC), sans
passer par Redis. Stockage en JSON Lines versionnable git, resume-friendly
via un hash stable de l'item.

Pas de classification effectuée ici : la blindness de l'annotation manuelle
exige que les predictions du classifier soient générées **après** annotation
(cf. predict_golden.py). Idem pour le prix N jours après : voir backtest_golden.py.

Usage:
    docker compose exec core python -m tik_core.scripts.collect_golden \
        --asset all --n-per-asset 50

    docker compose exec core python -m tik_core.scripts.collect_golden \
        --asset btc --n-per-asset 50 --reset

Format de sortie (core/data/golden_dataset/raw_items.jsonl) :
    {
      "id": "<hash16>",
      "asset": "btc" | "gold",
      "source": "google_news" | "cryptocompare" | "reddit",
      "text": "<titre>",
      "metadata": {...},
      "fetched_at": "2026-05-01T15:00:00+00:00",
      "fetch_price": 102345.67
    }

Contexte : Paquet 4 Session 4 (calibration). Voir docs/methodology/calibration.md.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import httpx
import structlog

from tik_core.config import get_settings

log = structlog.get_logger()

DATA_DIR = Path("/app/data/golden_dataset")
RAW_ITEMS_FILE = DATA_DIR / "raw_items.jsonl"

# === URLs sources (identiques aux ingesters de prod pour garantir la
# représentativité du sample) ===

GOOGLE_NEWS_RSS_TPL = (
    "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
)
USER_AGENT_BROWSER = "Mozilla/5.0 (compatible; TikBot/0.1)"

CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"

REDDIT_LISTING_TPL = "https://www.reddit.com/r/{sub}/hot.json"
USER_AGENT_REDDIT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"
REDDIT_SUBS_BTC = ["Bitcoin", "CryptoMarkets"]
REDDIT_MIN_SCORE = 5

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


@dataclass
class CollectedItem:
    id: str
    asset: str
    source: str
    text: str
    metadata: dict
    fetched_at: str
    fetch_price: float | None

    def to_jsonl(self) -> str:
        return json.dumps(
            {
                "id": self.id,
                "asset": self.asset,
                "source": self.source,
                "text": self.text,
                "metadata": self.metadata,
                "fetched_at": self.fetched_at,
                "fetch_price": self.fetch_price,
            },
            ensure_ascii=False,
        )


def _make_id(asset: str, source: str, text: str) -> str:
    """Hash stable d'un item : sha256(asset|source|text)[:16]."""
    h = hashlib.sha256(f"{asset}|{source}|{text}".encode("utf-8")).hexdigest()
    return h[:16]


def _load_existing_ids(path: Path) -> set[str]:
    """Charge les IDs déjà présents dans le fichier de sortie (resume-friendly)."""
    if not path.exists():
        return set()
    ids: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "id" in obj:
                ids.add(obj["id"])
    return ids


# === Fetchers de prix ===

async def fetch_btc_price(client: httpx.AsyncClient) -> float | None:
    try:
        r = await client.get(
            BINANCE_TICKER_URL,
            params={"symbol": "BTCUSDT"},
            timeout=10.0,
        )
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception as exc:  # noqa: BLE001
        log.warning("collect_golden.btc_price.error", error=str(exc))
        return None


async def fetch_gold_price(client: httpx.AsyncClient) -> float | None:
    try:
        r = await client.get(
            YAHOO_QUOTE_URL.format(symbol="GC=F"),
            params={"interval": "1m", "range": "1d"},
            headers={"User-Agent": USER_AGENT_BROWSER},
            timeout=10.0,
        )
        r.raise_for_status()
        data = r.json()
        result = data["chart"]["result"][0]
        closes = result["indicators"]["quote"][0]["close"]
        valid = [c for c in closes if c is not None]
        return float(valid[-1]) if valid else None
    except Exception as exc:  # noqa: BLE001
        log.warning("collect_golden.gold_price.error", error=str(exc))
        return None


# === Fetchers de sources textuelles ===

def _extract_publisher(entry) -> str:
    """Logique identique à google_news_ingester._extract_publisher."""
    try:
        title = entry.source.title
        if title:
            return str(title).strip()
    except (AttributeError, KeyError, TypeError):
        pass
    raw_title = entry.get("title", "") if hasattr(entry, "get") else ""
    if " - " in raw_title:
        return raw_title.rsplit(" - ", 1)[-1].strip()
    return "unknown"


async def fetch_google_news(
    client: httpx.AsyncClient,
    query: str,
    asset: str,
    fetch_price: float | None,
    fetched_at: str,
    limit: int = 200,
) -> list[CollectedItem]:
    url = GOOGLE_NEWS_RSS_TPL.format(query=quote_plus(query))
    try:
        r = await client.get(
            url,
            headers={"User-Agent": USER_AGENT_BROWSER},
            timeout=15.0,
            follow_redirects=True,
        )
        r.raise_for_status()
        content = r.text
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "collect_golden.google_news.error", error=str(exc), asset=asset
        )
        return []

    feed = await asyncio.to_thread(feedparser.parse, content)
    entries = list(feed.entries or [])[:limit]

    items: list[CollectedItem] = []
    for entry in entries:
        title = entry.get("title", "") if hasattr(entry, "get") else ""
        if not title:
            continue
        items.append(
            CollectedItem(
                id=_make_id(asset, "google_news", title),
                asset=asset,
                source="google_news",
                text=title,
                metadata={
                    "publisher": _extract_publisher(entry),
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                },
                fetched_at=fetched_at,
                fetch_price=fetch_price,
            )
        )
    return items


async def fetch_cryptocompare(
    client: httpx.AsyncClient,
    api_key: str,
    fetch_price: float | None,
    fetched_at: str,
    limit: int = 200,
) -> list[CollectedItem]:
    if not api_key:
        log.warning("collect_golden.cryptocompare.no_api_key")
        return []
    try:
        r = await client.get(
            CRYPTOCOMPARE_NEWS_URL,
            params={"categories": "BTC", "lang": "EN", "api_key": api_key},
            timeout=15.0,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("collect_golden.cryptocompare.error", error=str(exc))
        return []

    if data.get("Type") != 100:
        log.warning(
            "collect_golden.cryptocompare.api_error",
            message=data.get("Message"),
        )
        return []

    articles = (data.get("Data") or [])[:limit]

    items: list[CollectedItem] = []
    for a in articles:
        title = (a.get("title") or "").strip()
        if not title:
            continue
        source_name = (
            (a.get("source_info") or {}).get("name") or a.get("source") or ""
        )
        items.append(
            CollectedItem(
                id=_make_id("btc", "cryptocompare", title),
                asset="btc",
                source="cryptocompare",
                text=title,
                metadata={
                    "url": a.get("url", ""),
                    "source_name": source_name,
                    "published_on": a.get("published_on"),
                    "categories": a.get("categories", ""),
                },
                fetched_at=fetched_at,
                fetch_price=fetch_price,
            )
        )
    return items


async def fetch_reddit_btc(
    client: httpx.AsyncClient,
    subs: list[str],
    fetch_price: float | None,
    fetched_at: str,
    limit_per_sub: int = 50,
    min_score: int = REDDIT_MIN_SCORE,
) -> list[CollectedItem]:
    items: list[CollectedItem] = []
    for sub in subs:
        url = REDDIT_LISTING_TPL.format(sub=sub)
        try:
            r = await client.get(
                url,
                headers={"User-Agent": USER_AGENT_REDDIT},
                params={"limit": limit_per_sub},
                timeout=15.0,
                follow_redirects=True,
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("collect_golden.reddit.error", sub=sub, error=str(exc))
            continue
        try:
            children = data["data"]["children"]
        except (KeyError, TypeError):
            log.warning("collect_golden.reddit.invalid_payload", sub=sub)
            continue

        for c in children:
            if c.get("kind") != "t3":
                continue
            pdata = c.get("data") or {}
            if pdata.get("stickied") or pdata.get("over_18"):
                continue
            try:
                score = int(pdata.get("score", 0))
            except (TypeError, ValueError):
                continue
            if score < min_score:
                continue
            title = (pdata.get("title") or "").strip()
            if not title:
                continue
            items.append(
                CollectedItem(
                    id=_make_id("btc", "reddit", title),
                    asset="btc",
                    source="reddit",
                    text=title,
                    metadata={
                        "subreddit": sub,
                        "score": score,
                        "num_comments": pdata.get("num_comments", 0),
                        "permalink": (
                            f"https://www.reddit.com{pdata.get('permalink', '')}"
                        ),
                        "created_utc": pdata.get("created_utc"),
                    },
                    fetched_at=fetched_at,
                    fetch_price=fetch_price,
                )
            )
    return items


# === Quotas par asset ===

def quotas_for(asset: str, n_total: int) -> dict[str, int]:
    """Répartit n_total items entre les sources d'un asset.

    BTC : 3 sources (google_news, cryptocompare, reddit). 50 → 17/17/16.
    GOLD : 1 source (google_news). 50 → 50.
    """
    if asset == "btc":
        per = n_total // 3
        rest = n_total - per * 3
        return {
            "google_news": per + (1 if rest > 0 else 0),
            "cryptocompare": per + (1 if rest > 1 else 0),
            "reddit": per,
        }
    if asset == "gold":
        return {"google_news": n_total}
    raise ValueError(f"Unknown asset: {asset}")


def pick_new(
    items: list[CollectedItem],
    quota: int,
    existing_ids: set[str],
) -> list[CollectedItem]:
    """Garde les `quota` premiers items dont l'id n'est pas déjà connu.

    Préserve l'ordre source (= ordre Google News / CryptoCompare / Reddit hot)
    pour rester fidèle à ce que verrait l'ingester en production.

    Si `quota <= 0`, retourne immédiatement une liste vide (utile si la
    config demande zéro items pour une source donnée).
    """
    if quota <= 0:
        return []
    out: list[CollectedItem] = []
    seen_in_batch: set[str] = set()
    for item in items:
        if item.id in existing_ids or item.id in seen_in_batch:
            continue
        out.append(item)
        seen_in_batch.add(item.id)
        if len(out) >= quota:
            break
    return out


# === Pipeline principal ===

async def collect_for_asset(
    client: httpx.AsyncClient,
    asset: str,
    n_total: int,
    existing_ids: set[str],
    settings,
) -> list[CollectedItem]:
    quotas = quotas_for(asset, n_total)
    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    if asset == "btc":
        # Prix snapshoté une seule fois, partagé entre les 3 sources BTC
        # (cohérent : c'est le prix au moment de la collecte, pas par source).
        price = await fetch_btc_price(client)

        gn_task = fetch_google_news(
            client, "Bitcoin", "btc", price, fetched_at,
        )
        cc_task = fetch_cryptocompare(
            client, settings.cryptocompare_api_key, price, fetched_at,
        )
        rd_task = fetch_reddit_btc(
            client, REDDIT_SUBS_BTC, price, fetched_at,
        )
        gn_items, cc_items, rd_items = await asyncio.gather(
            gn_task, cc_task, rd_task
        )

        new_items: list[CollectedItem] = []
        new_items.extend(
            pick_new(gn_items, quotas["google_news"], existing_ids)
        )
        new_items.extend(
            pick_new(cc_items, quotas["cryptocompare"], existing_ids)
        )
        new_items.extend(pick_new(rd_items, quotas["reddit"], existing_ids))
        return new_items

    if asset == "gold":
        price = await fetch_gold_price(client)
        gn_items = await fetch_google_news(
            client, '"gold price"', "gold", price, fetched_at,
        )
        return pick_new(gn_items, quotas["google_news"], existing_ids)

    raise ValueError(f"Unknown asset: {asset}")


def append_items(path: Path, items: list[CollectedItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for item in items:
            f.write(item.to_jsonl() + "\n")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Collecte un dataset golden Tik (Paquet 4 Session 4)."
    )
    parser.add_argument(
        "--asset",
        choices=["btc", "gold", "all"],
        default="all",
        help="Asset(s) à collecter (défaut all).",
    )
    parser.add_argument(
        "--n-per-asset",
        type=int,
        default=50,
        help="Nombre cible d'items par asset (défaut 50).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RAW_ITEMS_FILE,
        help=f"Fichier de sortie JSON Lines (défaut: {RAW_ITEMS_FILE}).",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Vide le fichier de sortie avant de collecter (sinon resume).",
    )
    args = parser.parse_args()

    settings = get_settings()

    if args.reset and args.output.exists():
        args.output.unlink()
        print(f"--reset : {args.output} supprimé.")

    existing_ids = _load_existing_ids(args.output)
    print(f"Items déjà en stock : {len(existing_ids)}")

    assets_to_collect = (
        ["btc", "gold"] if args.asset == "all" else [args.asset]
    )

    total_new = 0
    async with httpx.AsyncClient() as client:
        for asset in assets_to_collect:
            print(
                f"\n--- Collecte pour {asset.upper()} "
                f"(cible: {args.n_per_asset}) ---"
            )
            new_items = await collect_for_asset(
                client, asset, args.n_per_asset, existing_ids, settings,
            )

            by_source: dict[str, int] = {}
            for item in new_items:
                by_source[item.source] = by_source.get(item.source, 0) + 1

            print(f"  → {len(new_items)} nouveaux items collectés")
            for src, n in sorted(by_source.items()):
                print(f"     {src:20s}: {n}")

            append_items(args.output, new_items)
            existing_ids.update(item.id for item in new_items)
            total_new += len(new_items)

    print(f"\nTotal nouveaux items écrits dans {args.output} : {total_new}")
    print(f"Total items en stock : {len(existing_ids)}")


if __name__ == "__main__":
    asyncio.run(main())
