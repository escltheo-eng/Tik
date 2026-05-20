"""Backtest des items du golden dataset contre le prix réel multi-horizon.

Pour chaque item de raw_items.jsonl, on récupère le prix de l'asset à
plusieurs horizons après le `fetched_at` (1h, 6h, 24h, 5d par défaut) et on
calcule le delta % par rapport à `fetch_price`. C'est la **vérité de
référence objective** pour mesurer la calibration des sources Tik (humains
+ classifiers se jugent contre le mouvement réel du marché).

Multi-horizon parce que le sentiment news a une demi-vie variable selon
la source : flash news = effet sur quelques heures, news macro = effet sur
plusieurs jours. Permet de mesurer **sur quel horizon chaque source est
prédictive**.

Si l'horizon demandé dépasse `now()`, le delta est marqué `available=False`
(pas d'erreur, juste pas encore de prix futur). Tu peux donc lancer le
backtest dès la collecte (= deltas courts dispos) et le ré-exécuter plus
tard (= deltas longs maintenant dispos).

Le script regénère prices.jsonl à chaque exécution (pas d'append). Le coût
est minime (juste indexation dans la fenêtre d'historique en mémoire).

Usage:
    docker compose exec core python -m tik_core.scripts.backtest_golden
    docker compose exec core python -m tik_core.scripts.backtest_golden \
        --horizons 1h,6h,24h,5d,7d
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import structlog

from tik_core.scripts.backtest import (
    fetch_btc_history,
    fetch_gold_history,
    find_closest_price,
)

log = structlog.get_logger()

DATA_DIR = Path("/app/data/golden_dataset")
RAW_ITEMS_FILE = DATA_DIR / "raw_items.jsonl"
PRICES_FILE = DATA_DIR / "prices.jsonl"

DEFAULT_HORIZONS = ["1h", "6h", "24h", "5d"]


def _parse_horizon(token: str) -> int:
    """Convertit '1h' / '6h' / '24h' / '5d' / '7d' en secondes."""
    token = token.strip().lower()
    if token.endswith("h"):
        return int(token[:-1]) * 3600
    if token.endswith("d"):
        return int(token[:-1]) * 86400
    raise ValueError(f"Horizon non reconnu : {token!r} (attendu : Xh ou Xd)")


def _parse_dt(s: str) -> datetime:
    """Parse une datetime ISO 8601, normalisée en UTC."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _load_raw_items(path: Path) -> list[dict]:
    if not path.exists():
        print(
            f"Le fichier {path} n'existe pas. "
            f"Lance d'abord : python -m tik_core.scripts.collect_golden",
            file=sys.stderr,
        )
        sys.exit(1)
    items: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _compute_deltas_for_item(
    item: dict,
    history: list[tuple[int, float]],
    horizons: list[str],
    now: datetime,
) -> dict:
    """Calcule les deltas pour un item à chaque horizon."""
    fetch_price = item.get("fetch_price")
    fetched_at = _parse_dt(item["fetched_at"])

    deltas: dict[str, dict] = {}
    for h_str in horizons:
        h_sec = _parse_horizon(h_str)
        target = fetched_at + timedelta(seconds=h_sec)

        # Si l'horizon dépasse maintenant, prix futur pas encore disponible
        if target > now:
            deltas[h_str] = {
                "price": None,
                "delta_pct": None,
                "available": False,
                "reason": "horizon_in_future",
            }
            continue

        if fetch_price is None or fetch_price == 0:
            deltas[h_str] = {
                "price": None,
                "delta_pct": None,
                "available": False,
                "reason": "no_fetch_price",
            }
            continue

        price = find_closest_price(history, target)
        if price is None:
            deltas[h_str] = {
                "price": None,
                "delta_pct": None,
                "available": False,
                "reason": "no_price_in_window",
            }
            continue

        delta_pct = (price - fetch_price) / fetch_price * 100
        deltas[h_str] = {
            "price": price,
            "delta_pct": round(delta_pct, 4),
            "available": True,
        }

    return {
        "id": item["id"],
        "asset": item["asset"],
        "fetch_price": fetch_price,
        "fetched_at": item["fetched_at"],
        "deltas": deltas,
        "computed_at": datetime.now(tz=UTC).isoformat(),
    }


def _print_stats(records: list[dict], horizons: list[str]) -> None:
    """Stats agrégées : combien d'items ont un delta dispo par horizon, par asset."""
    print("\n--- Disponibilité des deltas par horizon ---")
    print(f"  {'horizon':<8s} | {'BTC dispo':>14s} | {'GOLD dispo':>14s}")
    print("  " + "-" * 42)
    for h in horizons:
        btc_total = sum(1 for r in records if r["asset"] == "btc")
        gold_total = sum(1 for r in records if r["asset"] == "gold")
        btc_avail = sum(1 for r in records if r["asset"] == "btc" and r["deltas"][h]["available"])
        gold_avail = sum(1 for r in records if r["asset"] == "gold" and r["deltas"][h]["available"])
        print(
            f"  {h:<8s} | "
            f"{btc_avail:>3d} / {btc_total:<3d} ({btc_avail / btc_total * 100 if btc_total else 0:5.1f}%) | "
            f"{gold_avail:>3d} / {gold_total:<3d} ({gold_avail / gold_total * 100 if gold_total else 0:5.1f}%)"
        )


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest des items du golden dataset (multi-horizon)."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=RAW_ITEMS_FILE,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PRICES_FILE,
    )
    parser.add_argument(
        "--horizons",
        type=str,
        default=",".join(DEFAULT_HORIZONS),
        help=(
            "Liste séparée par des virgules. Format : Xh (heures) ou Xd (jours). "
            f"Défaut : {','.join(DEFAULT_HORIZONS)}"
        ),
    )
    args = parser.parse_args()

    horizons = [h.strip() for h in args.horizons.split(",") if h.strip()]
    # Validation préalable : leve si parse impossible
    for h in horizons:
        _parse_horizon(h)

    items = _load_raw_items(args.input)
    print(f"Items chargés : {len(items)}")
    by_asset: dict[str, list[dict]] = {}
    for item in items:
        by_asset.setdefault(item["asset"], []).append(item)
    for asset, lst in by_asset.items():
        print(f"  {asset}: {len(lst)}")

    print("\nFetch des historiques de prix (BTC via Binance, GOLD via Yahoo)...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        coros = []
        if "btc" in by_asset:
            coros.append(fetch_btc_history(client))
        if "gold" in by_asset:
            coros.append(fetch_gold_history(client))
        results = await asyncio.gather(*coros)

    histories: dict[str, list[tuple[int, float]]] = {}
    idx = 0
    if "btc" in by_asset:
        histories["btc"] = results[idx]
        idx += 1
        print(f"  → BTC : {len(histories['btc'])} klines récupérées")
    if "gold" in by_asset:
        histories["gold"] = results[idx]
        idx += 1
        print(f"  → GOLD : {len(histories['gold'])} klines récupérées")

    now = datetime.now(tz=UTC)
    print(f"\nCalcul des deltas pour les horizons {horizons} (now = {now.isoformat()})")

    records: list[dict] = []
    for item in items:
        asset = item["asset"]
        history = histories.get(asset, [])
        record = _compute_deltas_for_item(item, history, horizons, now)
        records.append(record)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n{len(records)} records écrits dans {args.output}")
    _print_stats(records, horizons)


if __name__ == "__main__":
    asyncio.run(main())
