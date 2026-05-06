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
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.storage.models import BacktestRun, Signal
from tik_core.utils.time import now_utc_naive

log = structlog.get_logger()

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
UA = "Mozilla/5.0 (compatible; TikBot/0.1)"


# ----- Fetch des historiques -----

async def fetch_btc_history(
    client: httpx.AsyncClient,
    *,
    interval: str = "1h",
    limit: int = 1000,
) -> list[tuple[int, float]]:
    """Récupère les klines BTCUSDT depuis Binance.

    Args:
        interval: granularité Binance (1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h,
            12h, 1d, …). Défaut "1h" — comportement historique inchangé.
        limit: nombre de klines (max 1000 côté Binance). Défaut 1000.

    Retourne une liste [(timestamp_ms, close_price), ...] triée chronologiquement.
    """
    r = await client.get(
        BINANCE_KLINES,
        params={"symbol": "BTCUSDT", "interval": interval, "limit": limit},
        timeout=30.0,
    )
    r.raise_for_status()
    raw = r.json()
    return [(int(d[0]), float(d[4])) for d in raw]


async def fetch_gold_history(
    client: httpx.AsyncClient,
    *,
    interval: str = "1h",
    range_param: str = "60d",
) -> list[tuple[int, float]]:
    """Récupère les klines GOLD (GC=F) via Yahoo Finance.

    Args:
        interval: granularité Yahoo (1m, 5m, 15m, 30m, 60m, 1h, 1d, …).
            Défaut "1h" — comportement historique inchangé.
        range_param: fenêtre historique Yahoo (60d, 1y, 2y, …). Défaut "60d".

    Retourne une liste [(timestamp_ms, close_price), ...] triée chronologiquement.
    """
    url = YAHOO_CHART.format(symbol="GC=F")
    r = await client.get(
        url,
        params={"interval": interval, "range": range_param},
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


def find_closest_price(
    history: list[tuple[int, float]],
    target: datetime,
    *,
    max_diff_ms: int = 6 * 3600 * 1000,
) -> float | None:
    """Cherche dans l'historique le prix dont le timestamp est le plus proche.

    Args:
        max_diff_ms: tolérance max (ms) entre target et le kline le plus proche.
            Défaut 6h — adapté aux klines 1h. À élargir pour klines 1d (24h)
            ou resserrer pour klines 15m (30min).

    Retourne None si l'écart dépasse `max_diff_ms` (donnée trop éloignée).
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
    if best_diff > max_diff_ms:
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


# ----- Helpers de scoring partagés -----

def _gain_for(direction: str, delta_pct: float) -> float:
    """Gain réel d'une décision selon la direction prise et le delta observé.

    - long : on profite du delta tel quel (positif si le marché monte)
    - short : on profite de l'inverse du delta (positif si le marché baisse)
    - neutral : on considère réussi un signal stable, donc précis quand |delta| est petit
    """
    if direction == "long":
        return delta_pct
    if direction == "short":
        return -delta_pct
    return -abs(delta_pct)


def _success_for(direction: str, delta_pct: float, threshold_pct: float) -> bool:
    if direction == "long":
        return delta_pct > threshold_pct
    if direction == "short":
        return delta_pct < -threshold_pct
    return abs(delta_pct) < threshold_pct


# ----- Rapport -----

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
    avg_pnl = mean(_gain_for(r["direction"], r["delta_pct"]) for r in results)
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
        avg = mean(_gain_for(r["direction"], r["delta_pct"]) for r in rs)
        print(f"\n{entity} : {len(rs)} signaux, hit {s}/{len(rs)} = {s / len(rs) * 100:.1f}%, gain moy {avg:+.2f}%")
        by_dir: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            by_dir[r["direction"]].append(r)
        for direction in sorted(by_dir.keys()):
            drs = by_dir[direction]
            ds = sum(1 for r in drs if r["success"])
            davg = mean(_gain_for(r["direction"], r["delta_pct"]) for r in drs)
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
        avg = mean(_gain_for(r["direction"], r["delta_pct"]) for r in rs)
        print(f"   veracity {bucket:.2f} : {len(rs):3d} signaux, hit {s:2d}/{len(rs):2d} = {s / len(rs) * 100:5.1f}%, gain moy {avg:+.2f}%")

    # Top best / worst
    def _row(r: dict) -> str:
        gain = _gain_for(r["direction"], r["delta_pct"])
        status = "OK" if r["success"] else "KO"
        return (
            f"   {r['entity']:5s} {r['direction']:8s} verac {r['veracity']:.2f} "
            f"conf {r['confidence']:.2f} → delta {r['delta_pct']:+6.2f}% "
            f"gain {gain:+6.2f}% [{status}]"
        )

    sorted_by_gain = sorted(results, key=lambda r: _gain_for(r["direction"], r["delta_pct"]), reverse=True)
    print("\n--- Top 3 BEST (gain le plus élevé selon direction) ---")
    for r in sorted_by_gain[:3]:
        print(_row(r))
    print("\n--- Top 3 WORST (gain le plus négatif) ---")
    for r in sorted_by_gain[-3:]:
        print(_row(r))

    print_baselines_comparison(results, threshold_pct)

    print()
    print("=" * 70)
    print("  Note : ce backtest n'inclut pas les coûts de transaction")
    print("  (spread, fees, slippage). Les gains affichés sont théoriques.")
    print("=" * 70)
    print()


# ----- Baselines -----

def evaluate_constant_baseline(
    results: list[dict],
    direction: str,
    threshold_pct: float,
) -> dict:
    """Évalue une stratégie qui prédit toujours la même direction."""
    n = len(results)
    if n == 0:
        return {"name": f"always {direction}", "n": 0, "hit_rate": 0.0, "avg_gain": 0.0}
    n_success = sum(1 for r in results if _success_for(direction, r["delta_pct"], threshold_pct))
    avg_gain = mean(_gain_for(direction, r["delta_pct"]) for r in results)
    return {
        "name": f"always {direction}",
        "n": n,
        "n_success": n_success,
        "hit_rate": n_success / n,
        "avg_gain": avg_gain,
    }


def evaluate_random_baseline(
    results: list[dict],
    threshold_pct: float,
    n_runs: int = 100,
    seed: int = 42,
) -> dict:
    """Évalue une stratégie random uniforme (1/3 long, 1/3 short, 1/3 neutral)
    moyennée sur n_runs simulations indépendantes pour stabiliser le résultat.
    """
    n = len(results)
    if n == 0:
        return {"name": "random", "n": 0, "hit_rate": 0.0, "avg_gain": 0.0}
    rng = random.Random(seed)
    choices = ("long", "short", "neutral")
    total_success = 0
    total_gain = 0.0
    for _ in range(n_runs):
        for r in results:
            d = rng.choice(choices)
            if _success_for(d, r["delta_pct"], threshold_pct):
                total_success += 1
            total_gain += _gain_for(d, r["delta_pct"])
    total_evals = n * n_runs
    return {
        "name": "random (avg 100 runs)",
        "n": n,
        "n_success": total_success / n_runs,
        "hit_rate": total_success / total_evals,
        "avg_gain": total_gain / total_evals,
    }


def evaluate_tik_baseline(results: list[dict], threshold_pct: float) -> dict:
    """Stats Tik (rappel pour la comparaison, recalculé sur les mêmes signaux)."""
    n = len(results)
    if n == 0:
        return {"name": "Tik", "n": 0, "hit_rate": 0.0, "avg_gain": 0.0}
    n_success = sum(1 for r in results if r["success"])
    avg_gain = mean(_gain_for(r["direction"], r["delta_pct"]) for r in results)
    return {
        "name": "Tik",
        "n": n,
        "n_success": n_success,
        "hit_rate": n_success / n,
        "avg_gain": avg_gain,
    }


def print_baselines_comparison(results: list[dict], threshold_pct: float) -> None:
    """Tableau comparatif Tik vs baselines naïfs, global puis par entity."""
    if not results:
        return

    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_entity[r["entity"]].append(r)

    strategies = [
        ("Tik", evaluate_tik_baseline),
        ("Random", lambda rs, t: evaluate_random_baseline(rs, t)),
        ("Always LONG", lambda rs, t: evaluate_constant_baseline(rs, "long", t)),
        ("Always SHORT", lambda rs, t: evaluate_constant_baseline(rs, "short", t)),
        ("Always NEUTRAL", lambda rs, t: evaluate_constant_baseline(rs, "neutral", t)),
    ]

    print("\n--- Tik vs baselines naïfs ---")
    print(f"\n{'Stratégie':<18} | {'Global':<22} | {'BTC':<22} | {'GOLD':<22}")
    print(f"{'':18} | {'hit / n   gain':<22} | {'hit / n   gain':<22} | {'hit / n   gain':<22}")
    print("-" * 92)

    for name, fn in strategies:
        global_stats = fn(results, threshold_pct)
        btc_stats = fn(by_entity.get("BTC", []), threshold_pct)
        gold_stats = fn(by_entity.get("GOLD", []), threshold_pct)

        def fmt(s):
            if s["n"] == 0:
                return f"{'-/-':<10}{'':>12}"
            n_succ = s.get("n_success", 0)
            if isinstance(n_succ, float):
                hit_str = f"{n_succ:.1f}/{s['n']}"
            else:
                hit_str = f"{n_succ}/{s['n']}"
            return f"{hit_str:<10} {s['hit_rate'] * 100:5.1f}% {s['avg_gain']:+5.2f}%"

        print(f"{name:<18} | {fmt(global_stats):<22} | {fmt(btc_stats):<22} | {fmt(gold_stats):<22}")

    print()
    print("Lecture du tableau :")
    print("  - hit/n   = nombre de signaux réussis / nombre total")
    print("  - %       = hit rate")
    print("  - +X.XX%  = gain moyen par signal selon direction prédite")
    print("  - Si Tik fait pire qu'un baseline, il n'apporte pas de valeur sur ce segment.")


# ----- Persistance des runs -----

def _build_run_stats(results: list[dict], threshold_pct: float) -> dict:
    """Construit le dict des stats détaillées à stocker dans BacktestRun (JSON columns)."""
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_entity[r["entity"]].append(r)

    stats_by_entity: dict[str, dict] = {}
    for entity, rs in by_entity.items():
        n = len(rs)
        s = sum(1 for r in rs if r["success"])
        avg = mean(_gain_for(r["direction"], r["delta_pct"]) for r in rs)
        per_dir: dict[str, dict] = {}
        for direction in ("long", "short", "neutral"):
            drs = [r for r in rs if r["direction"] == direction]
            if not drs:
                continue
            ds = sum(1 for r in drs if r["success"])
            davg = mean(_gain_for(direction, r["delta_pct"]) for r in drs)
            per_dir[direction] = {"n": len(drs), "n_success": ds, "hit_rate": ds / len(drs), "avg_gain_pct": davg}
        stats_by_entity[entity] = {
            "n": n,
            "n_success": s,
            "hit_rate": s / n if n else 0.0,
            "avg_gain_pct": avg,
            "by_direction": per_dir,
        }

    veracity_buckets: dict[float, list[dict]] = defaultdict(list)
    for r in results:
        veracity_buckets[round(r["veracity"], 2)].append(r)
    stats_by_veracity = {
        f"{bucket:.2f}": {
            "n": len(rs),
            "n_success": sum(1 for r in rs if r["success"]),
            "hit_rate": sum(1 for r in rs if r["success"]) / len(rs),
            "avg_gain_pct": mean(_gain_for(r["direction"], r["delta_pct"]) for r in rs),
        }
        for bucket, rs in veracity_buckets.items()
    }

    baselines = {
        "tik": evaluate_tik_baseline(results, threshold_pct),
        "random": evaluate_random_baseline(results, threshold_pct),
        "always_long": evaluate_constant_baseline(results, "long", threshold_pct),
        "always_short": evaluate_constant_baseline(results, "short", threshold_pct),
        "always_neutral": evaluate_constant_baseline(results, "neutral", threshold_pct),
    }
    # Cleanup : "name" est redondant (clé du dict)
    for v in baselines.values():
        v.pop("name", None)

    return {
        "stats_by_entity": stats_by_entity,
        "stats_by_veracity": stats_by_veracity,
        "baselines": baselines,
    }


async def _persist_run(
    session_maker,
    *,
    horizon_days: int,
    threshold_pct: float,
    total_signals: int,
    n_eligible: int,
    results: list[dict],
    notes: str | None = None,
) -> str:
    """Insère un BacktestRun dans la DB et retourne son id."""
    n_eval = len(results)
    n_success = sum(1 for r in results if r["success"])
    hit_rate = n_success / n_eval if n_eval else 0.0
    avg_gain = (
        mean(_gain_for(r["direction"], r["delta_pct"]) for r in results)
        if n_eval else 0.0
    )
    stats = _build_run_stats(results, threshold_pct)

    run = BacktestRun(
        horizon_days=horizon_days,
        threshold_pct=threshold_pct,
        total_signals=total_signals,
        n_eligible=n_eligible,
        n_evaluated=n_eval,
        hit_rate=hit_rate,
        avg_gain_pct=avg_gain,
        stats_by_entity=stats["stats_by_entity"],
        stats_by_veracity=stats["stats_by_veracity"],
        baselines=stats["baselines"],
        notes=notes,
    )
    async with session_maker() as session:
        session.add(run)
        await session.commit()
        await session.refresh(run)
    return run.id


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
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Ne pas archiver le run dans la table backtest_runs (utile en dev/debug).",
    )
    parser.add_argument(
        "--notes",
        type=str,
        default=None,
        help="Note libre stockée avec le run (ex: 'avant refactor seuil NEUTRAL').",
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

    cutoff = now_utc_naive() - timedelta(days=args.horizon_days)
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

    if args.no_save:
        print("(--no-save activé : run non archivé en DB)\n")
    else:
        run_id = await _persist_run(
            session_maker,
            horizon_days=args.horizon_days,
            threshold_pct=args.threshold,
            total_signals=len(signals),
            n_eligible=len(eligible),
            results=results,
            notes=args.notes,
        )
        print(f"Run archivé en DB sous l'id : {run_id}\n")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
