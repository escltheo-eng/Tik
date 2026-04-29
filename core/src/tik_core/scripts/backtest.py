"""Backtest des signaux Tik contre les cours réels.

Pour chaque signal en base : récupère le prix au moment du signal (t0)
et le prix à t0 + N jours, calcule le delta %, et juge si la direction
prédite était correcte.

Usage :
    python -m tik_core.scripts.backtest                      # défauts (horizon=3j, threshold=0.5%)
    python -m tik_core.scripts.backtest --horizon-days 5
    python -m tik_core.scripts.backtest --horizon-days 1 --threshold 0.3

Limitations connues (à garder en tête) :
- Petit échantillon : ~50 signaux suffisent pour des tendances grossières,
  pas pour conclure statistiquement.
- Coûts de transaction non comptés (spread, fees, slippage).
- Pas de gestion de risque (stops, take-profits, sizing).
"""

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.storage.models import Signal

log = structlog.get_logger()

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
UA = "Mozilla/5.0 (compatible; TikBot/0.1)"


# ----- Fetch des historiques -----

async def fetch_btc_history(client: httpx.AsyncClient) -> list[tuple[int, float]]:
    """Récupère les 1000 dernières klines 1h BTCUSDT (~41 jours).

    Retourne une liste [(timestamp_ms, close_price), ...] triée chronologiquement.
    """
    r = await client.get(
        BINANCE_KLINES,
        params={"symbol": "BTCUSDT", "interval": "1h", "limit": 1000},
        timeout=30.0,
    )
    r.raise_for_status()
    raw = r.json()
    return [(int(d[0]), float(d[4])) for d in raw]


async def fetch_gold_history(client: httpx.AsyncClient) -> list[tuple[int, float]]:
    """Récupère les klines 1h GOLD (GC=F) sur 60 jours via Yahoo.

    Retourne une liste [(timestamp_ms, close_price), ...] triée chronologiquement.
    """
    url = YAHOO_CHART.format(symbol="GC=F")
    r = await client.get(
        url,
        params={"interval": "1h", "range": "60d"},
        headers={"User-Agent": UA},
        timeout=30.0,
    )
    r.raise_for_status()
    data = r.json()
    res = data["chart"]["result"][0]
    ts_list = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out: list[tuple[int, float]] = []
    for t, c in zip(ts_list, closes, strict=False):
        if c is None:
            continue
        out.append((int(t) * 1000, float(c)))
    return out


def find_closest_price(history: list[tuple[int, float]], target: datetime) -> float | None:
    """Cherche dans l'historique le prix dont le timestamp est le plus proche.

    Retourne None si l'écart est > 6 heures (donnée trop éloignée → peu fiable).
    """
    if not history:
        return None
    target_ms = int(target.replace(tzinfo=timezone.utc).timestamp() * 1000) if target.tzinfo is None else int(target.timestamp() * 1000)
    best: tuple[int, float] | None = None
    best_diff = float("inf")
    for ts_ms, price in history:
        diff = abs(ts_ms - target_ms)
        if diff < best_diff:
            best_diff = diff
            best = (ts_ms, price)
    if best is None:
        return None
    if best_diff > 6 * 3600 * 1000:  # plus de 6h → trop loin
        return None
    return best[1]


# ----- Évaluation -----

def evaluate_signal(
    signal: Signal,
    horizon_days: int,
    threshold_pct: float,
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
) -> dict | None:
    ts0 = signal.timestamp
    ts1 = ts0 + timedelta(days=horizon_days)

    if signal.entity_id == "BTC":
        history = btc_history
    elif signal.entity_id == "GOLD":
        history = gold_history
    else:
        return None

    p0 = find_closest_price(history, ts0)
    p1 = find_closest_price(history, ts1)
    if p0 is None or p1 is None or p0 == 0:
        return None

    delta_pct = (p1 - p0) / p0 * 100

    if signal.direction == "long":
        success = delta_pct > threshold_pct
    elif signal.direction == "short":
        success = delta_pct < -threshold_pct
    else:  # neutral
        success = abs(delta_pct) < threshold_pct

    return {
        "id": signal.id,
        "entity": signal.entity_id,
        "direction": signal.direction,
        "confidence": float(signal.confidence),
        "veracity": float(signal.veracity),
        "p0": p0,
        "p1": p1,
        "delta_pct": delta_pct,
        "success": success,
        "ts": ts0.isoformat(),
    }


# ----- Rapport -----

def gain_for_direction(r: dict) -> float:
    """Gain réel selon la direction prédite (positif = bon coup)."""
    if r["direction"] == "long":
        return r["delta_pct"]
    if r["direction"] == "short":
        return -r["delta_pct"]
    # neutral : un signal "stable" est d'autant plus précis que le delta absolu est petit
    return -abs(r["delta_pct"])


def print_report(results: list[dict], horizon_days: int, threshold_pct: float) -> None:
    if not results:
        print("Pas de résultats à afficher.")
        return

    print()
    print("=" * 70)
    print(f"  RAPPORT BACKTEST — horizon {horizon_days}j, seuil ±{threshold_pct}%")
    print("=" * 70)

    n = len(results)
    n_success = sum(1 for r in results if r["success"])
    avg_pnl = mean(gain_for_direction(r) for r in results)
    print(f"\nSignaux évalués : {n}")
    print(f"Hit rate global  : {n_success}/{n} = {n_success / n * 100:.1f}%")
    print(f"Gain moyen       : {avg_pnl:+.2f}% par signal (selon direction)")

    # Par entity
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_entity[r["entity"]].append(r)

    print("\n--- Par entity ---")
    for entity in sorted(by_entity.keys()):
        rs = by_entity[entity]
        s = sum(1 for r in rs if r["success"])
        avg = mean(gain_for_direction(r) for r in rs)
        print(f"\n{entity} : {len(rs)} signaux, hit {s}/{len(rs)} = {s / len(rs) * 100:.1f}%, gain moy {avg:+.2f}%")
        by_dir: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            by_dir[r["direction"]].append(r)
        for direction in sorted(by_dir.keys()):
            drs = by_dir[direction]
            ds = sum(1 for r in drs if r["success"])
            davg = mean(gain_for_direction(r) for r in drs)
            print(f"   {direction:8s} : {len(drs):3d} signaux, hit {ds}/{len(drs)} = {ds / len(drs) * 100:5.1f}%, gain moy {davg:+.2f}%")

    # Par tranche de veracity
    print("\n--- Hit rate par tranche de veracity ---")
    veracity_buckets: dict[float, list[dict]] = defaultdict(list)
    for r in results:
        bucket = round(r["veracity"], 2)
        veracity_buckets[bucket].append(r)
    for bucket in sorted(veracity_buckets.keys()):
        rs = veracity_buckets[bucket]
        s = sum(1 for r in rs if r["success"])
        avg = mean(gain_for_direction(r) for r in rs)
        print(f"   veracity {bucket:.2f} : {len(rs):3d} signaux, hit {s:2d}/{len(rs):2d} = {s / len(rs) * 100:5.1f}%, gain moy {avg:+.2f}%")

    # Top best / worst
    sorted_by_gain = sorted(results, key=gain_for_direction, reverse=True)
    print("\n--- Top 3 BEST (gain le plus élevé selon direction) ---")
    for r in sorted_by_gain[:3]:
        print(f"   {r['entity']:5s} {r['direction']:8s} verac {r['veracity']:.2f} conf {r['confidence']:.2f} → delta {r['delta_pct']:+6.2f}% gain {gain_for_direction(r):+6.2f}% [{'OK' if r['success'] else 'KO'}]")
    print("\n--- Top 3 WORST (gain le plus négatif) ---")
    for r in sorted_by_gain[-3:]:
        print(f"   {r['entity']:5s} {r['direction']:8s} verac {r['veracity']:.2f} conf {r['confidence']:.2f} → delta {r['delta_pct']:+6.2f}% gain {gain_for_direction(r):+6.2f}% [{'OK' if r['success'] else 'KO'}]")

    print()
    print("=" * 70)
    print("  Note : ce backtest n'inclut pas les coûts de transaction")
    print("  (spread, fees, slippage). Les gains affichés sont théoriques.")
    print("=" * 70)
    print()


# ----- Main -----

async def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest des signaux Tik")
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=3,
        help="Nombre de jours après le signal pour mesurer le résultat (défaut 3)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Seuil de variation en %% pour qu'un signal soit considéré comme réussi (défaut 0.5)",
    )
    args = parser.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    print(f"\nLecture des signaux depuis la DB...")
    async with session_maker() as session:
        result = await session.execute(select(Signal).order_by(Signal.timestamp.asc()))
        signals = list(result.scalars().all())

    print(f"  → {len(signals)} signaux totaux en base")

    cutoff = datetime.utcnow() - timedelta(days=args.horizon_days)
    eligible = [s for s in signals if s.timestamp < cutoff]
    print(f"  → {len(eligible)} signaux éligibles (plus de {args.horizon_days}j d'âge)")

    if not eligible:
        print("\nAucun signal n'est encore assez ancien pour cet horizon. Réduis --horizon-days ou attends.")
        await engine.dispose()
        return

    print("\nFetch des historiques de prix (BTC via Binance, GOLD via Yahoo)...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        btc_history, gold_history = await asyncio.gather(
            fetch_btc_history(client),
            fetch_gold_history(client),
        )
    print(f"  → BTC : {len(btc_history)} klines 1h récupérées")
    print(f"  → GOLD : {len(gold_history)} klines 1h récupérées")

    print("\nÉvaluation des signaux...")
    results = []
    skipped = 0
    for sig in eligible:
        ev = evaluate_signal(sig, args.horizon_days, args.threshold, btc_history, gold_history)
        if ev is None:
            skipped += 1
            continue
        results.append(ev)
    print(f"  → {len(results)} évalués, {skipped} ignorés (prix non trouvé dans la fenêtre)")

    print_report(results, args.horizon_days, args.threshold)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
