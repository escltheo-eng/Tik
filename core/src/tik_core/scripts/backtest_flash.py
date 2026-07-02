"""Backtest DÉDIÉ au flash BTC (horizon minutes-heures).

Le `backtest.py` standard travaille en JOURS — inadapté au flash, qui vit en
minutes-heures. L'évaluer sur 1 jour donnerait un chiffre trompeur. Ce script :

- ne prend QUE les signaux **flash BTC** (`horizon='flash'`, `entity_id='BTC'`) ;
- récupère les klines Binance **1 minute** (paginées) couvrant la période des signaux ;
- évalue chaque flash sur un horizon en **MINUTES** (défaut 60) ;
- compare le hit rate Tik aux baselines (Always LONG/SHORT/NEUTRAL, Random) ;
- fait le **test apparié de gain vs Always SHORT et Always LONG** (le bon
  comparateur de tendance — cf. mémoire `measurement-rigor-controls`).

⚠ Limites connues (honnêtes) :
1. Les flash rapprochés (même heure) se **chevauchent** → pas indépendants ; le
   hit rate est INDICATIF, pas une preuve statistique
   (cf. `measurement-overlapping-returns`).
2. Mode SHADOW / **NO-GO directionnel** : ceci MESURE, ça ne fabrique pas un edge.
   Un bon chiffre sur peu de signaux ne prouve rien.
3. Pas de coûts de transaction / slippage comptés.
4. Klines 1m limitées à ~la période récente (pagination depuis le 1er signal).

Usage (depuis le VPS) :
    docker exec tik-core python -m tik_core.scripts.backtest_flash --horizon-minutes 60 --threshold 0.1
    docker exec tik-core python -m tik_core.scripts.backtest_flash --horizon-minutes 15 --threshold 0.05
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
from datetime import UTC, datetime, timedelta

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.scripts.backtest import (
    BINANCE_KLINES,
    UA,
    _gain_for,
    evaluate_constant_baseline,
    evaluate_random_baseline,
    evaluate_tik_baseline,
    paired_gain_significance,
)
from tik_core.storage.models import Signal
from tik_core.utils.time import now_utc_naive

log = structlog.get_logger()

# Tolérance de rapprochement prix pour des klines 1m : 2 min (si le kline le plus
# proche est à plus de 2 min du timestamp cible, on considère la donnée manquante).
MAX_DIFF_MS_1M = 2 * 60 * 1000


# ----- Récupération des klines 1m paginées -----


async def fetch_btc_1m_range(
    client: httpx.AsyncClient, start_ms: int, end_ms: int
) -> list[tuple[int, float]]:
    """Récupère les klines BTCUSDT 1m de start_ms à end_ms (pagination Binance).

    Binance limite à 1000 klines/appel (~16,6 h). On boucle en avançant le curseur
    sur le timestamp du dernier kline reçu. Retourne [(ts_ms, close), ...] trié.
    """
    out: list[tuple[int, float]] = []
    cursor = start_ms
    while cursor < end_ms:
        r = await client.get(
            BINANCE_KLINES,
            params={
                "symbol": "BTCUSDT",
                "interval": "1m",
                "startTime": cursor,
                "limit": 1000,
            },
            headers={"User-Agent": UA},
            timeout=30.0,
        )
        r.raise_for_status()
        raw = r.json()
        if not raw:
            break
        for d in raw:
            out.append((int(d[0]), float(d[4])))
        last_ts = int(raw[-1][0])
        if last_ts <= cursor:  # garde-fou anti-boucle
            break
        cursor = last_ts + 60_000
        if len(raw) < 1000:  # dernière page atteinte
            break
    return out


# ----- Index de prix rapide (recherche dichotomique) -----


class PriceIndex:
    """Index sur l'historique 1m (trié) pour retrouver un prix en O(log n).

    Le backtest journalier fait un balayage linéaire (OK sur ~1000 klines), mais
    le flash a des milliers de signaux × des dizaines de milliers de klines →
    balayage linéaire = milliards d'opérations. On précalcule la liste des
    timestamps une fois et on cherche par `bisect`.
    """

    def __init__(self, history: list[tuple[int, float]]) -> None:
        self.history = history
        self.ts = [t for t, _ in history]

    def at(self, target: datetime, max_diff_ms: int = MAX_DIFF_MS_1M) -> float | None:
        if not self.history:
            return None
        target_ms = (
            int(target.replace(tzinfo=UTC).timestamp() * 1000)
            if target.tzinfo is None
            else int(target.timestamp() * 1000)
        )
        i = bisect.bisect_left(self.ts, target_ms)
        best_price: float | None = None
        best_diff = float("inf")
        for j in (i - 1, i):  # le plus proche est l'un des deux voisins
            if 0 <= j < len(self.history):
                diff = abs(self.ts[j] - target_ms)
                if diff < best_diff:
                    best_diff = diff
                    best_price = self.history[j][1]
        if best_price is None or best_diff > max_diff_ms:
            return None
        return best_price


# ----- Évaluation d'un flash sur horizon minutes -----


def evaluate_flash_signal(
    signal: Signal,
    horizon_minutes: int,
    threshold_pct: float,
    prices: PriceIndex,
) -> dict | None:
    """Évalue un signal flash BTC sur un horizon en minutes.

    Retourne None si les prix (t0 ou t0+horizon) ne sont pas trouvables assez
    proches dans l'historique 1m (signal trop récent, trou de données…).
    """
    ts0 = signal.timestamp
    ts1 = ts0 + timedelta(minutes=horizon_minutes)

    p0 = prices.at(ts0)
    p1 = prices.at(ts1)
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
        "entity": "BTC",
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


def print_flash_report(results: list[dict], horizon_minutes: int, threshold_pct: float) -> None:
    n = len(results)
    print("\n" + "=" * 70)
    print(f"  RAPPORT BACKTEST FLASH BTC — horizon {horizon_minutes} min, seuil ±{threshold_pct}%")
    print("=" * 70)
    if n == 0:
        print("  Aucun signal flash évaluable (trop récents ou trou de klines 1m).")
        return

    n_succ = sum(1 for r in results if r["success"])
    avg = sum(_gain_for(r["direction"], r["delta_pct"]) for r in results) / n
    print(f"\n  {n} flash évalués — hit {n_succ}/{n} = {n_succ / n * 100:.1f}%, gain moy {avg:+.3f}%")

    # Répartition + hit par direction
    print("\n--- Par direction ---")
    for direction in ("long", "short", "neutral"):
        drs = [r for r in results if r["direction"] == direction]
        if not drs:
            print(f"  {direction:8s} : 0 signal")
            continue
        ds = sum(1 for r in drs if r["success"])
        davg = sum(_gain_for(direction, r["delta_pct"]) for r in drs) / len(drs)
        print(
            f"  {direction:8s} : {len(drs):4d} signaux, hit {ds}/{len(drs)} = "
            f"{ds / len(drs) * 100:5.1f}%, gain moy {davg:+.3f}%"
        )

    # Baselines
    print("\n--- Tik vs baselines naïfs (global BTC flash) ---")
    strategies = [
        ("Tik", lambda rs: evaluate_tik_baseline(rs, threshold_pct)),
        ("Random", lambda rs: evaluate_random_baseline(rs, threshold_pct)),
        ("Always LONG", lambda rs: evaluate_constant_baseline(rs, "long", threshold_pct)),
        ("Always SHORT", lambda rs: evaluate_constant_baseline(rs, "short", threshold_pct)),
        ("Always NEUTRAL", lambda rs: evaluate_constant_baseline(rs, "neutral", threshold_pct)),
    ]
    print(f"  {'Stratégie':<16} | {'hit / n':<12} | {'hit rate':<9} | gain moy")
    print("  " + "-" * 56)
    for name, fn in strategies:
        s = fn(results)
        succ = s.get("n_success", 0)
        succ_str = f"{succ:.1f}" if isinstance(succ, float) else str(succ)
        print(
            f"  {name:<16} | {succ_str + '/' + str(s['n']):<12} | "
            f"{s['hit_rate'] * 100:6.1f}%  | {s['avg_gain']:+.3f}%"
        )

    # Test apparié vs les baselines de tendance (le vrai juge)
    print("\n--- Tik ajoute-t-il du GAIN au-dessus de la tendance ? (test apparié) ---")
    for base_dir in ("short", "long"):
        sig = paired_gain_significance(results, base_dir)
        if sig is None:
            print(f"  vs Always {base_dir.upper():5s} : non calculable")
            continue
        p = sig.get("p")
        if p is None:
            verdict = "p non calculable (n<2 ou variance nulle)"
            p_str = "—"
        else:
            verdict = "SIGNIFICATIF" if p < 0.05 else "non significatif"
            p_str = f"{p:.3f}"
        print(
            f"  vs Always {base_dir.upper():5s} : Δgain moyen {sig['mean_diff']:+.3f}% "
            f"(p={p_str}) → {verdict}"
        )

    print("\n⚠ Rappels : flash rapprochés = chevauchants (hit rate indicatif, pas une preuve) ;")
    print("  NO-GO directionnel — un bon chiffre sur peu de signaux ne prouve pas d'edge.")


# ----- Main -----


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest flash BTC (horizon minutes)")
    parser.add_argument("--horizon-minutes", type=int, default=60, help="Horizon d'évaluation (min)")
    parser.add_argument("--threshold", type=float, default=0.1, help="Seuil directionnel en %%")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        stmt = (
            select(Signal)
            .where(Signal.horizon == "flash", Signal.entity_id == "BTC")
            .order_by(Signal.timestamp.asc())
        )
        signals = list((await session.execute(stmt)).scalars().all())
    await engine.dispose()

    print(f"\n{len(signals)} signaux flash BTC en base.")
    cutoff = now_utc_naive() - timedelta(minutes=args.horizon_minutes)
    eligible = [s for s in signals if s.timestamp <= cutoff]
    print(f"  → {len(eligible)} assez anciens pour l'horizon {args.horizon_minutes} min.")
    if not eligible:
        print("Aucun flash assez ancien. Réduis --horizon-minutes ou attends.")
        return

    # Fenêtre de klines à récupérer : du 1er signal éligible à maintenant.
    start_dt = eligible[0].timestamp - timedelta(minutes=5)
    start_ms = int(start_dt.replace(tzinfo=UTC).timestamp() * 1000)
    end_ms = int(datetime.now(tz=UTC).timestamp() * 1000)

    print(f"  Récupération des klines 1m depuis {start_dt.date()}… (peut prendre ~10-30 s)")
    async with httpx.AsyncClient() as client:
        btc_history = await fetch_btc_1m_range(client, start_ms, end_ms)
    print(f"  {len(btc_history)} klines 1m récupérées. Évaluation…", flush=True)

    prices = PriceIndex(btc_history)
    results: list[dict] = []
    for sig in eligible:
        ev = evaluate_flash_signal(sig, args.horizon_minutes, args.threshold, prices)
        if ev is not None:
            results.append(ev)

    print_flash_report(results, args.horizon_minutes, args.threshold)


if __name__ == "__main__":
    asyncio.run(main())
