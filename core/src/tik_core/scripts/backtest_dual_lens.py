"""Backtest dual-lens : lecture OPTIMISTE vs PARANOÏAQUE sur tous les slices Tik.

Pour un (signal_horizon, entity, horizon de mesure, seuil) donné, évalue les
signaux mûrs post-fix et reporte, pour CHAQUE sous-groupe (overall, par
direction, par bucket veracity, par statut anti-fake-news), DEUX lectures de la
même donnée :

- **Sans paranoïa** : hit rate + bat-il le baseline random ?
- **Avec paranoïa** : n, **gain moyen** (l'argent, pas le hit), p-value vs random
  (test z 2-proportions), survie à la correction de Bonferroni (nb de groupes
  testés), flag petit échantillon (< min-samples).

Motivation (cf. CLAUDE.md Paquet 33) : un hit rate flatteur peut ne pas survivre
au test du gain ni à la significativité. Ce script applique systématiquement les
deux lentilles pour éviter le cherry-picking et le multiple-testing.

Usage :
    python -m tik_core.scripts.backtest_dual_lens \\
        --signal-horizon swing --entity BTC --horizon-hours 6 --threshold 0.30

    # Balayage complet recommandé : lancer pour chaque (horizon, entity) :
    #   flash BTC @1h · swing BTC @6h · swing BTC @24h · swing GOLD @6h/@24h
    # La mesure 5j officielle (2026-05-27) : --signal-horizon swing --horizon-days 5

Reproductible, lecture seule, zéro modif pipeline. Réutilise les primitives de
backtest.py et les filtres de measure_post_fix_hit_rates.py (pas de duplication).
"""

import argparse
import asyncio
import math
from datetime import timedelta
from statistics import mean

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.scripts.backtest import (
    _gain_for,
    evaluate_random_baseline,
    fetch_btc_history,
    fetch_gold_history,
)
from tik_core.scripts.measure_post_fix_hit_rates import (
    FIX_BUG_N2_ISO,
    _evaluate_signal_td,
    _filter_by_entity,
    _filter_by_signal_horizon,
    _parse_iso,
)
from tik_core.storage.models import Signal
from tik_core.utils.time import now_utc_naive


def _normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _ztest_vs_null(hits: int, n: int, p_null: float) -> float | None:
    """p-value bilatérale d'un test z 1-proportion vs un taux nul donné."""
    if n == 0 or not (0.0 < p_null < 1.0):
        return None
    p_obs = hits / n
    se = math.sqrt(p_null * (1 - p_null) / n)
    if se == 0:
        return None
    z = (p_obs - p_null) / se
    return 2 * (1 - _normal_cdf(abs(z)))


def _group_stats(rows: list[dict], threshold: float) -> dict | None:
    """Stats d'un sous-groupe : hit, gain, baseline random, p vs random."""
    n = len(rows)
    if n == 0:
        return None
    hits = sum(1 for r in rows if r["success"])
    gain = mean(_gain_for(r["direction"], r["delta_pct"]) for r in rows)
    rnd = evaluate_random_baseline(rows, threshold)["hit_rate"]
    p = _ztest_vs_null(hits, n, rnd) if rnd else None
    return {
        "n": n,
        "hits": hits,
        "hit": hits / n,
        "gain": gain,
        "rnd": rnd,
        "p": p,
    }


def _build_groups(results: list[dict]) -> list[tuple[str, list[dict]]]:
    """Découpe les résultats en sous-groupes à tester (overall + dimensions)."""
    groups: list[tuple[str, list[dict]]] = [("overall", results)]
    for d in ("long", "short", "neutral"):
        rows = [r for r in results if r["direction"] == d]
        if rows:
            groups.append((f"direction={d}", rows))
    for label, lo, hi in (("veracity<0.85", 0.0, 0.85), ("veracity>=0.85", 0.85, 1.01)):
        rows = [r for r in results if lo <= r["veracity"] < hi]
        if rows:
            groups.append((label, rows))
    for st in ("ok", "degraded", "tripped"):
        rows = [r for r in results if r.get("cb_status") == st]
        if rows:
            groups.append((f"cb_status={st}", rows))
    return groups


def _verdicts(s: dict, bonferroni_threshold: float, min_samples: int) -> tuple[str, str]:
    """Retourne (lecture sans paranoïa, lecture avec paranoïa)."""
    beats_random = s["hit"] > s["rnd"]
    optimiste = f"{'bat' if beats_random else 'sous'} random ({s['rnd'] * 100:.0f}%)"

    flags = []
    if s["p"] is not None and s["p"] < 0.05:
        flags.append("sig0.05")
        flags.append("✓Bonf" if s["p"] < bonferroni_threshold else "✗Bonf")
    else:
        flags.append("non-sig")
    flags.append("gain+" if s["gain"] > 0 else "gain-")
    if s["n"] < min_samples:
        flags.append(f"n<{min_samples}")
    if beats_random and (s["p"] is None or s["p"] >= bonferroni_threshold or s["gain"] <= 0):
        flags.append("→ FRAGILE")
    paranoia = " ".join(flags)
    return optimiste, paranoia


async def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest dual-lens optimiste vs paranoïaque.")
    parser.add_argument(
        "--signal-horizon", choices=["flash", "swing", "macro", "all"], default="all"
    )
    parser.add_argument("--entity", choices=["BTC", "GOLD", "all"], default="all")
    parser.add_argument("--horizon-days", type=float, default=None)
    parser.add_argument("--horizon-hours", type=float, default=None)
    parser.add_argument("--threshold", type=float, default=0.30)
    parser.add_argument("--since-iso", type=str, default=FIX_BUG_N2_ISO)
    parser.add_argument("--until-iso", type=str, default=None)
    parser.add_argument("--min-samples", type=int, default=20)
    args = parser.parse_args()

    if args.horizon_hours is not None:
        horizon_td = timedelta(hours=args.horizon_hours)
        horizon_label = f"{args.horizon_hours:g}h"
    elif args.horizon_days is not None:
        horizon_td = timedelta(days=args.horizon_days)
        horizon_label = f"{args.horizon_days:g}j"
    else:
        horizon_td = timedelta(hours=6)
        horizon_label = "6h"

    since_dt = _parse_iso(args.since_iso)
    until_dt = _parse_iso(args.until_iso) if args.until_iso else now_utc_naive()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    print("=" * 92)
    print("  BACKTEST DUAL-LENS — lecture SANS paranoïa vs AVEC paranoïa")
    print("=" * 92)
    print(f"  Filtre   : horizon={args.signal_horizon} · entity={args.entity}")
    print(f"  Mesure   : {horizon_label} après émission · seuil ±{args.threshold}%")
    print(f"  Période  : {since_dt.isoformat()} → {until_dt.isoformat()} UTC")
    print("=" * 92)

    async with session_maker() as session:
        stmt = (
            select(Signal)
            .where(Signal.timestamp >= since_dt)
            .where(Signal.timestamp <= until_dt)
            .order_by(Signal.timestamp.asc())
        )
        signals = list((await session.execute(stmt)).scalars().all())

    signals = _filter_by_signal_horizon(signals, args.signal_horizon)
    signals = _filter_by_entity(signals, args.entity)
    cutoff = until_dt - horizon_td
    eligible = [s for s in signals if s.timestamp <= cutoff]
    print(f"\n  {len(eligible)} signaux mûrs à évaluer\n")
    if not eligible:
        print("  Aucun signal mûr pour cet horizon.\n")
        await engine.dispose()
        return

    use_fine = horizon_td <= timedelta(hours=4)
    btc_interval = "15m" if use_fine else "1h"
    gold_interval = "60m" if use_fine else "1h"
    async with httpx.AsyncClient(timeout=30.0) as client:
        btc_hist, gold_hist = await asyncio.gather(
            fetch_btc_history(client, interval=btc_interval, limit=1000),
            fetch_gold_history(client, interval=gold_interval, range_param="60d"),
        )

    results: list[dict] = []
    for sig in eligible:
        ev = _evaluate_signal_td(sig, horizon_td, args.threshold, btc_hist, gold_hist)
        if ev is not None:
            ev["cb_status"] = sig.circuit_breaker_status
            results.append(ev)
    if not results:
        print("  Aucun signal évaluable (prix hors fenêtre).\n")
        await engine.dispose()
        return

    groups = _build_groups(results)
    bonf_threshold = 0.05 / len(groups)
    print(
        f"  {len(results)} signaux évalués · {len(groups)} groupes testés "
        f"→ seuil Bonferroni = 0.05/{len(groups)} = {bonf_threshold:.4f}\n"
    )

    header = f"  {'groupe':<20} {'n':>4} {'hit%':>6} {'gain%':>7} {'p':>7}  {'SANS parano':<22} {'AVEC parano'}"
    print(header)
    print("  " + "-" * 104)
    for label, rows in groups:
        s = _group_stats(rows, args.threshold)
        if s is None:
            continue
        opt, par = _verdicts(s, bonf_threshold, args.min_samples)
        pstr = f"{s['p']:.3f}" if s["p"] is not None else "n/a"
        print(
            f"  {label:<20} {s['n']:>4} {s['hit'] * 100:>6.1f} {s['gain']:>+7.2f} "
            f"{pstr:>7}  {opt:<22} {par}"
        )

    print()
    print("  Légende — SANS parano : bat/sous le baseline random.")
    print("  AVEC parano : sig0.05 = p<0.05 ; ✓/✗Bonf = survit/non à la correction multiple ;")
    print("  gain+/- = gain moyen positif/négatif (l'argent) ; n<N = échantillon faible ;")
    print("  → FRAGILE = bat random MAIS ne survit pas Bonferroni OU gain négatif.")
    print()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
