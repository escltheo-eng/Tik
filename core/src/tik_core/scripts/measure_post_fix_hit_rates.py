"""Mesure manuelle hit rate post-fix Bug N=2 sur 3 niveaux de veracity.

Mesure le hit rate des signaux émis ≥ 2026-05-17 20:47 UTC (fix Bug N=2,
cf. CLAUDE.md Paquet 25) sur 3 niveaux simultanément :

- Niveau 2 global       : tous signaux (garde-fou contre régression
                          silencieuse — l'algo ADR-011 mesure le global)
- Niveau 1 transitoire  : veracity ≥ 0.85 (Garde-fou 2-bis transitoire
                          tant que Reddit IP-banni cf. Bug 11)
- Niveau 1 strict       : veracity ≥ 0.90 (audit comparatif post-retour
                          Reddit)

Pour chaque niveau : hit rate global + par asset + par direction +
baselines (Tik vs Random vs Always LONG/SHORT/NEUTRAL).

Usage :

    # Mesure SWING officielle à J+10 post-fix (à lancer 2026-05-27+) —
    # swing uniquement, à son horizon de design 5j
    python -m tik_core.scripts.measure_post_fix_hit_rates \\
        --signal-horizon swing --horizon-days 5

    # Mesure FLASH uniquement, à son horizon de design 1h
    python -m tik_core.scripts.measure_post_fix_hit_rates \\
        --signal-horizon flash --horizon-hours 1

    # Validation logique sur données pré-fix (anti-régression script,
    # doit reproduire approximativement les chiffres Paquet 27)
    python -m tik_core.scripts.measure_post_fix_hit_rates \\
        --since-iso 2026-05-10T00:00:00 \\
        --until-iso 2026-05-17T20:47:00 \\
        --horizon-days 5

Limitations connues :

- Seuil directionnalité par défaut 0.5 % (hérité backtest.py), pas la
  granularité Paquet 17 (flash 0.30 %, swing 0.50 %, macro 1 %+).
  Override via --threshold si besoin de la granularité fine.
- Séparation flash/swing/macro via --signal-horizon (flash|swing|macro|all).
  IMPORTANT : mélanger les horizons (défaut 'all') fausse la mesure — flash est
  conçu pour ~1h, swing pour ~5j. Toujours apparier --signal-horizon avec un
  --horizon-* cohérent (flash↔1h, swing↔5j).
- Seuil 0.85 transitoire codé en dur (MIN_VERACITY_TRANSITOIRE).
  Si Garde-fou 2-bis revient à 0.90 (retour Reddit), modifier la
  constante (1 ligne).
- Réutilise evaluate_constant_baseline / evaluate_random_baseline /
  evaluate_tik_baseline de backtest.py. Ne ré-implémente rien.
"""

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.scripts.backtest import (
    _gain_for,
    _success_for,
    evaluate_constant_baseline,
    evaluate_random_baseline,
    evaluate_tik_baseline,
    fetch_btc_history,
    fetch_gold_history,
    find_closest_price,
    paired_gain_significance,
)
from tik_core.storage.models import Signal
from tik_core.utils.time import now_utc_naive

# Fix Bug N=2 appliqué au commit 65d2818 le 2026-05-17 20:47 UTC.
# Cf. CLAUDE.md Paquet 25 + section 9 Bug 10.
FIX_BUG_N2_ISO = "2026-05-17T20:47:00"

# Garde-fou 2-bis transitoire (CLAUDE.md section 5) tant que Reddit
# IP-banni (Bug 11). À ramener à 0.90 quand Reddit revient.
MIN_VERACITY_TRANSITOIRE = 0.85
MIN_VERACITY_STRICT = 0.90


def _parse_iso(iso_str: str) -> datetime:
    """Parse une chaîne ISO UTC en datetime naïf (cohérent DB Bug 9)."""
    s = iso_str.rstrip("Z")
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _evaluate_signal_td(
    signal: Signal,
    horizon_td: timedelta,
    threshold_pct: float,
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
) -> dict | None:
    """Version locale d'evaluate_signal qui accepte un timedelta arbitraire.

    L'original `evaluate_signal` de backtest.py prend horizon_days: int et ne
    permet donc pas horizon = 1h. On duplique la logique localement sans
    modifier la signature publique de backtest.py (rétrocompat).
    """
    ts0 = signal.timestamp
    ts1 = ts0 + horizon_td

    if signal.entity_id == "BTC":
        history = btc_history
    elif signal.entity_id == "GOLD":
        history = gold_history
    else:
        return None

    # Tolérance fetch : 30 min pour klines 15m (horizon court flash),
    # 6h pour klines 1h (horizon swing).
    if horizon_td <= timedelta(hours=4):
        max_diff_ms = 30 * 60 * 1000
    else:
        max_diff_ms = 6 * 3600 * 1000

    p0 = find_closest_price(history, ts0, max_diff_ms=max_diff_ms)
    p1 = find_closest_price(history, ts1, max_diff_ms=max_diff_ms)
    if p0 is None or p1 is None or p0 == 0:
        return None

    delta_pct = (p1 - p0) / p0 * 100
    success = _success_for(signal.direction, delta_pct, threshold_pct)

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


def _filter_by_veracity(results: list[dict], min_veracity: float) -> list[dict]:
    if min_veracity <= 0.0:
        return results
    return [r for r in results if r["veracity"] >= min_veracity]


def _filter_by_signal_horizon(signals: list[Signal], horizon: str) -> list[Signal]:
    """Filtre les signaux par leur horizon contractuel (flash/swing/macro).

    Crucial : flash est conçu pour ~1h, swing pour ~5j. Les mélanger dans
    une seule mesure à horizon forward unique fausse le hit rate des deux
    (un signal flash évalué à 5j, ou un swing évalué à 1h, n'a pas de sens).
    `all` désactive le filtre (rétrocompat, mais mesure peu concluante).
    """
    if horizon == "all":
        return signals
    return [s for s in signals if s.horizon == horizon]


def _filter_by_entity(signals: list[Signal], entity: str) -> list[Signal]:
    """Filtre les signaux par actif (BTC/GOLD).

    Utile pour mesurer un actif isolé : les baselines (Tik vs Random vs
    Always X) et les buckets veracity sont alors calculés sur cet actif
    seul, sans mélange. Ex : `--entity BTC` retire le bruit GOLD (signaux
    neutral haute-veracity qui polluent le bucket veracity ≥ 0.85).
    `all` désactive le filtre (rétrocompat).
    """
    if entity == "all":
        return signals
    return [s for s in signals if s.entity_id == entity]


def _filter_by_cb_status(signals: list[Signal], status: str) -> list[Signal]:
    """Filtre les signaux par statut anti-fake-news (circuit_breaker_status).

    Permet de TESTER la valeur prédictive de l'AFN : comparer le hit rate des
    signaux `ok` vs `degraded` vs `tripped` au même horizon. Si `ok` surperforme
    `degraded`, le flag AFN a une valeur démontrable. `all` désactive le filtre.
    """
    if status == "all":
        return signals
    return [s for s in signals if s.circuit_breaker_status == status]


def _print_level_section(
    results: list[dict],
    *,
    level_name: str,
    min_veracity: float,
    threshold_pct: float,
    min_samples: int,
) -> None:
    filtered = _filter_by_veracity(results, min_veracity)
    n = len(filtered)

    print()
    print("=" * 76)
    suffix = f" (veracity ≥ {min_veracity:.2f})" if min_veracity > 0 else ""
    print(f"  {level_name}{suffix}")
    print("=" * 76)
    print(f"\nSignaux dans le bucket : {n}")

    if n == 0:
        print("  ⚠ Bucket vide — aucun signal au-dessus du seuil.\n")
        return
    if n < min_samples:
        print(
            f"  ⚠ Échantillon faible (N < {min_samples}) — biais significatif, "
            "à interpréter avec prudence.\n"
        )

    n_success = sum(1 for r in filtered if r["success"])
    avg_pnl = mean(_gain_for(r["direction"], r["delta_pct"]) for r in filtered)
    print(f"Hit rate global  : {n_success}/{n} = {n_success / n * 100:.1f}%")
    print(f"Gain moyen       : {avg_pnl:+.2f}% par signal (selon direction prédite)")

    # Par asset × direction
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in filtered:
        by_entity[r["entity"]].append(r)

    print("\n--- Par asset × direction ---")
    for entity in sorted(by_entity.keys()):
        rs = by_entity[entity]
        s = sum(1 for r in rs if r["success"])
        avg = mean(_gain_for(r["direction"], r["delta_pct"]) for r in rs)
        print(
            f"\n{entity} : {len(rs)} sig, hit {s}/{len(rs)} = "
            f"{s / len(rs) * 100:.1f}%, gain moy {avg:+.2f}%"
        )
        by_dir: dict[str, list[dict]] = defaultdict(list)
        for r in rs:
            by_dir[r["direction"]].append(r)
        for direction in sorted(by_dir.keys()):
            drs = by_dir[direction]
            ds = sum(1 for r in drs if r["success"])
            davg = mean(_gain_for(direction, r["delta_pct"]) for r in drs)
            print(
                f"   {direction:8s} : {len(drs):3d} sig, "
                f"hit {ds}/{len(drs)} = {ds / len(drs) * 100:5.1f}%, "
                f"gain moy {davg:+.2f}%"
            )

    # Baselines (Tik / Random / Always X)
    print("\n--- vs baselines naïfs ---")
    strategies = [
        ("Tik", evaluate_tik_baseline(filtered, threshold_pct)),
        ("Random", evaluate_random_baseline(filtered, threshold_pct)),
        ("Always LONG", evaluate_constant_baseline(filtered, "long", threshold_pct)),
        ("Always SHORT", evaluate_constant_baseline(filtered, "short", threshold_pct)),
        ("Always NEUTRAL", evaluate_constant_baseline(filtered, "neutral", threshold_pct)),
    ]
    print(f"\n{'Stratégie':<16} | {'hit / n':<14} | {'%':>7} | {'gain moy':>9}")
    print("-" * 56)
    for name, s in strategies:
        if s["n"] == 0:
            continue
        n_succ = s.get("n_success", 0)
        hit_str = f"{n_succ:.1f}/{s['n']}" if isinstance(n_succ, float) else f"{n_succ}/{s['n']}"
        print(f"{name:<16} | {hit_str:<14} | {s['hit_rate'] * 100:6.1f}% | {s['avg_gain']:+8.2f}%")
    print()

    _print_trend_baseline_comparison(filtered, min_samples=min_samples)


def _print_trend_baseline_comparison(filtered: list[dict], *, min_samples: int) -> None:
    """Tik vs baselines constantes : test apparié sur le GAIN + significativité.

    Répond à « Tik bat-il la TENDANCE, ou seulement Random ? ». En marché
    tendanciel, Random est trivial à battre ; le vrai juge est la meilleure
    baseline constante (souvent Always SHORT/LONG). Si Tik ne bat pas
    *significativement* la meilleure baseline constante sur le gain → aucun
    edge directionnel démontré au-dessus de la tendance.
    """
    print("--- Tik vs baselines constantes : test apparié sur le GAIN ---")
    print("    (Tik ajoute-t-il de l'alpha AU-DESSUS de la tendance, ou est-il colinéaire ?)\n")

    tests = [
        t
        for t in (paired_gain_significance(filtered, d) for d in ("short", "long", "neutral"))
        if t is not None
    ]
    if not tests:
        print("    (aucun signal)\n")
        return

    print(
        f"    {'comparaison':<18} | {'Tik gain':>9} | {'base gain':>9} | "
        f"{'Δ gain':>8} | {'z':>6} | {'p':>6} | verdict"
    )
    print("    " + "-" * 92)
    for t in tests:
        if t["p"] is None:
            verdict = "n/a (Tik ≡ baseline)"
        elif t["p"] < 0.05 and t["mean_diff"] > 0:
            verdict = "Tik GAGNE (sig.)"
        elif t["p"] < 0.05 and t["mean_diff"] < 0:
            verdict = "Tik PERD (sig.)"
        else:
            verdict = "égalité (non-sig.)"
        zstr = f"{t['z']:+.1f}" if t["z"] is not None else "n/a"
        pstr = f"{t['p']:.3f}" if t["p"] is not None else "n/a"
        print(
            f"    vs Always {t['baseline_direction'].upper():<8} | "
            f"{t['tik_gain']:>+8.2f}% | {t['baseline_gain']:>+8.2f}% | "
            f"{t['mean_diff']:>+7.2f}% | {zstr:>6} | {pstr:>6} | {verdict}"
        )

    # Conclusion : Tik bat-il la MEILLEURE baseline constante (par gain) ?
    best = max(tests, key=lambda t: t["baseline_gain"])
    print()
    if best["mean_diff"] > 0 and best["p"] is not None and best["p"] < 0.05:
        print(
            f"    ✅ Tik AJOUTE de l'alpha au-dessus de la meilleure baseline "
            f"(Always {best['baseline_direction'].upper()} {best['baseline_gain']:+.2f}%) : "
            f"Δ {best['mean_diff']:+.2f}% p={best['p']:.3f}"
        )
    else:
        pstr = f"p={best['p']:.3f}" if best["p"] is not None else "p=n/a"
        print(
            f"    ⚠ Tik N'AJOUTE PAS d'alpha au-dessus de la meilleure baseline "
            f"(Always {best['baseline_direction'].upper()} {best['baseline_gain']:+.2f}%) : "
            f"Tik {best['tik_gain']:+.2f}%, Δ {best['mean_diff']:+.2f}% {pstr}"
        )
    if best["n"] < min_samples:
        print(f"    ⚠ N={best['n']} < {min_samples} — conclusion fragile (échantillon faible).")
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Mesure manuelle hit rate post-fix Bug N=2 sur 3 niveaux veracity. "
            "Cf. CLAUDE.md Paquet 25 + section 5 Garde-fou 2-bis."
        ),
    )
    parser.add_argument(
        "--horizon-days",
        type=float,
        default=5.0,
        help="Horizon mesure en jours. Défaut 5j (swing).",
    )
    parser.add_argument(
        "--horizon-hours",
        type=float,
        default=None,
        help="Alternative à --horizon-days (ex --horizon-hours 1 pour flash).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Seuil de variation en %% pour validation directionnelle. Défaut 0.5.",
    )
    parser.add_argument(
        "--signal-horizon",
        type=str,
        choices=["flash", "swing", "macro", "all"],
        default="all",
        help=(
            "Filtre les signaux par horizon contractuel. Apparier avec "
            "--horizon-* (flash<->1h, swing<->5j). Défaut 'all' (rétrocompat, "
            "mais mélange les horizons -> mesure peu concluante)."
        ),
    )
    parser.add_argument(
        "--entity",
        type=str,
        choices=["BTC", "GOLD", "all"],
        default="all",
        help=(
            "Filtre les signaux par actif. Baselines + buckets veracity "
            "calculés sur cet actif seul. Ex '--entity BTC' retire le bruit "
            "GOLD. Défaut 'all'."
        ),
    )
    parser.add_argument(
        "--cb-status",
        type=str,
        choices=["ok", "degraded", "tripped", "all"],
        default="all",
        help=(
            "Filtre par statut anti-fake-news (circuit_breaker_status). Pour "
            "TESTER la valeur prédictive de l'AFN : comparer le hit rate "
            "'ok' vs 'degraded' au même horizon. Défaut 'all'."
        ),
    )
    parser.add_argument(
        "--since-iso",
        type=str,
        default=FIX_BUG_N2_ISO,
        help=f"ISO UTC date début. Défaut fix Bug N=2 ({FIX_BUG_N2_ISO}).",
    )
    parser.add_argument(
        "--until-iso",
        type=str,
        default=None,
        help="ISO UTC date fin optionnelle. Défaut = maintenant.",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=20,
        help="Seuil N en-dessous duquel un warning biais s'affiche. Défaut 20.",
    )
    args = parser.parse_args()

    if args.horizon_hours is not None:
        horizon_td = timedelta(hours=args.horizon_hours)
        horizon_label = f"{args.horizon_hours:g}h"
    else:
        horizon_td = timedelta(days=args.horizon_days)
        horizon_label = f"{args.horizon_days:g}j"

    since_dt = _parse_iso(args.since_iso)
    until_dt = _parse_iso(args.until_iso) if args.until_iso else now_utc_naive()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    print()
    print("=" * 76)
    print("  MESURE POST-FIX BUG N=2 — 3 niveaux veracity")
    print("=" * 76)
    print(f"  Période  : {since_dt.isoformat()} → {until_dt.isoformat()} UTC")
    print(f"  Horizon  : {horizon_label} après émission signal")
    print(
        f"  Filtre   : signal-horizon={args.signal_horizon} · entity={args.entity}"
        f" · cb_status={args.cb_status}"
    )
    print(f"  Seuil    : ±{args.threshold}% (directionnalité)")
    print(f"  Warning  : si bucket N < {args.min_samples}")
    print("=" * 76)

    # Fetch signaux dans la fenêtre
    print("\nLecture signaux DB...")
    async with session_maker() as session:
        stmt = (
            select(Signal)
            .where(Signal.timestamp >= since_dt)
            .where(Signal.timestamp <= until_dt)
            .order_by(Signal.timestamp.asc())
        )
        result = await session.execute(stmt)
        signals = list(result.scalars().all())
    print(f"  → {len(signals)} signaux dans la période")

    # Filtre par horizon contractuel (flash/swing/macro) AVANT la maturité —
    # ne pas mélanger des horizons de design différents dans une même mesure.
    signals = _filter_by_signal_horizon(signals, args.signal_horizon)
    if args.signal_horizon != "all":
        print(f"  → {len(signals)} signaux après filtre horizon='{args.signal_horizon}'")
    signals = _filter_by_entity(signals, args.entity)
    if args.entity != "all":
        print(f"  → {len(signals)} signaux après filtre entity='{args.entity}'")
    signals = _filter_by_cb_status(signals, args.cb_status)
    if args.cb_status != "all":
        print(f"  → {len(signals)} signaux après filtre cb_status='{args.cb_status}'")

    # Filtre éligibilité (signal + horizon ≤ until_dt = signal mûr)
    eligible_cutoff = until_dt - horizon_td
    eligible = [s for s in signals if s.timestamp <= eligible_cutoff]
    print(f"  → {len(eligible)} signaux mûrs (timestamp + horizon ≤ until_dt)")

    if not eligible:
        print(
            "\nAucun signal n'est encore assez ancien pour cet horizon. "
            "Réduis --horizon-days/hours ou attends.\n"
        )
        await engine.dispose()
        return

    # Fetch prix BTC + GOLD selon horizon
    print("\nFetch historiques prix...")
    use_fine_klines = horizon_td <= timedelta(hours=4)
    btc_interval = "15m" if use_fine_klines else "1h"
    btc_limit = 1000
    gold_interval = "60m" if use_fine_klines else "1h"
    gold_range = "60d"

    async with httpx.AsyncClient(timeout=30.0) as client:
        btc_history, gold_history = await asyncio.gather(
            fetch_btc_history(client, interval=btc_interval, limit=btc_limit),
            fetch_gold_history(client, interval=gold_interval, range_param=gold_range),
        )
    print(f"  → BTC : {len(btc_history)} klines {btc_interval}")
    print(f"  → GOLD : {len(gold_history)} klines {gold_interval}")

    # Évaluation
    print("\nÉvaluation signaux...")
    results: list[dict] = []
    skipped = 0
    for sig in eligible:
        ev = _evaluate_signal_td(
            sig,
            horizon_td,
            args.threshold,
            btc_history,
            gold_history,
        )
        if ev is None:
            skipped += 1
            continue
        results.append(ev)
    print(f"  → {len(results)} évalués, {skipped} ignorés (prix hors fenêtre)\n")

    if not results:
        print("Aucun signal évaluable. Fin.\n")
        await engine.dispose()
        return

    # 3 niveaux veracity
    levels = [
        ("NIVEAU 2 — global (garde-fou régression silencieuse)", 0.0),
        (
            "NIVEAU 1 transitoire — Garde-fou 2-bis (Reddit IP-banni Bug 11)",
            MIN_VERACITY_TRANSITOIRE,
        ),
        ("NIVEAU 1 strict — audit post-retour Reddit", MIN_VERACITY_STRICT),
    ]
    for label, min_v in levels:
        _print_level_section(
            results,
            level_name=label,
            min_veracity=min_v,
            threshold_pct=args.threshold,
            min_samples=args.min_samples,
        )

    print()
    print("=" * 76)
    print("  Note : ce script n'inclut pas les coûts de transaction.")
    print("  Cf. CLAUDE.md section 5 Garde-fou 2-bis pour interprétation.")
    print("=" * 76)
    print()

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
