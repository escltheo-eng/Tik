"""Mesure SHADOW : signaux 'micro' (couche ML btc-research-lab) — Étape 4 ADR-030.

Question ouverte ADR-030 §6
---------------------------
La fusion macro+micro (ADR-030) ingère des signaux `horizon='micro'` produits
par le pipeline ML du labo (LightGBM/river sur klines 1m + microstructure L2)
via `POST /api/v1/signals/ingest`, en SHADOW STRICT (jamais branchés au
`combined_bias`, marqués `circuit_breaker_status='degraded'`). Avant TOUT
enrôlement, l'ADR impose de trancher par la MESURE :

  1. Le micro a-t-il un edge directionnel au-dessus des baselines naïves ?
     (hit rate + gain apparié vs Always LONG/SHORT/NEUTRAL et Random,
     en fenêtres NON chevauchantes).
  2. Est-il INDÉPENDANT du swing OSINT ? (Spearman des directions micro↔swing :
     > 0.5 = redondant → empiler ne crée pas d'edge, ça dilue — cf. ADR-018).

Ce script LIT la base et calcule le diagnostic. Il n'écrit RIEN. Mesurer ≠
enrôler : le NO-GO directionnel (2026-05-27) reste la position par défaut.

Méthode
-------
- Signaux `horizon='micro'`, entity BTC, sur la fenêtre --since/--until.
  Les 'degraded' sont INCLUS (marqueur shadow, pas un flag qualité —
  cf. metrics.hit_rate) ; les 'tripped' sont exclus.
- Évaluation au design horizon micro (2h, aligné EXPIRY_BY_HORIZON) sur
  klines 15m Binance ; seuil directionnalité 0.3 % (défaut micro).
- FENÊTRES NON CHEVAUCHANTES par défaut : on ne garde qu'un signal toutes
  les `horizon` heures (le premier de chaque fenêtre). Des rendements
  chevauchants gonflent artificiellement la significativité (cf. mémoire
  measurement-overlapping-returns + go/no-go 2026-05-27).
- Test apparié (z) du gain Tik-micro vs CHAQUE baseline constante — la bonne
  question n'est pas « bat-il Random ? » mais « ajoute-t-il du gain au-dessus
  de la baseline de TENDANCE ? » (colinéarité au trend = pas d'edge).
- Redondance : pour chaque signal micro retenu, direction du dernier signal
  swing BTC émis dans les `--corr-window-hours` précédentes → Spearman des
  scores {-1, 0, +1}.

Limites (engagement 13bis #8)
-----------------------------
1. **N minuscule au démarrage du shadow** : tout résultat < 30 signaux non
   chevauchants est PRÉLIMINAIRE. Relancer après ≥ 2 semaines de collecte.
2. La veracity des signaux micro est le défaut serveur conservateur (0.70)
   — elle ne segmente RIEN ici, ne pas l'interpréter.
3. Coûts de transaction non comptés (spread/fees/slippage). Le labo a mesuré
   qu'à haute fréquence les frais mangent tout (RESEARCH.md H1) — un hit rate
   brut > 50 % ne suffit PAS.
4. Fenêtre 2h unique : pas de balayage multi-horizons (anti data-snooping,
   cf. leçon window_selection_is_a_dof du labo). L'horizon est fixé par
   design AVANT la mesure.

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_micro_signals
    docker exec tik-core python -m tik_core.scripts.measure_micro_signals \\
        --since-iso 2026-07-01T00:00:00 --allow-overlap
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.metrics.hit_rate import (
    HORIZON_DEFAULT_THRESHOLD_PCT,
    HORIZON_MEASURE_HOURS,
)
from tik_core.scripts.backtest import (
    _success_for,
    evaluate_constant_baseline,
    evaluate_random_baseline,
    evaluate_tik_baseline,
    fetch_btc_history,
    find_closest_price,
    paired_gain_significance,
)
from tik_core.scripts.backtest_numeric_sources import spearman_correlation
from tik_core.storage.models import Signal
from tik_core.utils.time import now_utc_naive

# En dessous de ce N non chevauchant, on refuse de conclure (affiché en dur
# dans le rapport). Cohérent avec BASELINE_MIN_SAMPLE de metrics.hit_rate.
MIN_SAMPLE_FOR_VERDICT = 30

DIRECTION_SCORE = {"long": 1.0, "neutral": 0.0, "short": -1.0}


def _parse_iso(iso_str: str) -> datetime:
    """Parse une chaîne ISO UTC en datetime naïf (cohérent DB, cf. Bug 9)."""
    s = iso_str.rstrip("Z")
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def select_non_overlapping(signals: list[Signal], horizon_td: timedelta) -> list[Signal]:
    """Garde au plus un signal par fenêtre de mesure (le premier).

    Les signaux micro peuvent arriver à cadence bien plus fine (transitions +
    heartbeat 30 min) que l'horizon de mesure 2h : évaluer chaque signal ferait
    se chevaucher les rendements → pseudo-réplication, significativité gonflée.
    """
    kept: list[Signal] = []
    last_ts: datetime | None = None
    for sig in sorted(signals, key=lambda s: s.timestamp):
        if last_ts is None or sig.timestamp >= last_ts + horizon_td:
            kept.append(sig)
            last_ts = sig.timestamp
    return kept


def evaluate_micro_signal(
    signal: Signal,
    horizon_td: timedelta,
    threshold_pct: float,
    btc_history: list[tuple[int, float]],
) -> dict | None:
    """Évalue un signal micro : delta prix à t0+horizon, succès, gain.

    Retourne None si le prix n'est pas disponible (hors fenêtre klines).
    Tolérance de matching 30 min (klines 15m, horizon court).
    """
    ts0 = signal.timestamp
    ts1 = ts0 + horizon_td
    max_diff_ms = 30 * 60 * 1000

    p0 = find_closest_price(btc_history, ts0, max_diff_ms=max_diff_ms)
    p1 = find_closest_price(btc_history, ts1, max_diff_ms=max_diff_ms)
    if p0 is None or p1 is None or p0 == 0:
        return None

    delta_pct = (p1 - p0) / p0 * 100
    return {
        "id": signal.id,
        "entity": signal.entity_id,
        "direction": signal.direction,
        "confidence": float(signal.confidence),
        "veracity": float(signal.veracity),
        "delta_pct": delta_pct,
        "success": _success_for(signal.direction, delta_pct, threshold_pct),
        "ts": signal.timestamp,
    }


def correlate_micro_vs_swing(
    micro_signals: list[Signal],
    swing_signals: list[Signal],
    corr_window: timedelta,
) -> tuple[float | None, int]:
    """Spearman des directions micro ↔ dernier swing BTC dans la fenêtre.

    Pour chaque signal micro, prend le signal swing BTC le plus récent émis
    dans les `corr_window` précédentes (ou au même instant). Sans swing dans
    la fenêtre, la paire est ignorée. Retourne (rho, n_paires).
    ADR-030 §6 : rho > 0.5 = redondant avec le swing → pas d'apport indépendant.
    """
    swing_sorted = sorted(swing_signals, key=lambda s: s.timestamp)
    xs: list[float] = []
    ys: list[float] = []
    for m in micro_signals:
        best: Signal | None = None
        for s in swing_sorted:
            if s.timestamp > m.timestamp:
                break
            if m.timestamp - s.timestamp <= corr_window:
                best = s
        if best is None:
            continue
        xs.append(DIRECTION_SCORE.get(m.direction, 0.0))
        ys.append(DIRECTION_SCORE.get(best.direction, 0.0))
    if len(xs) < 3:
        return None, len(xs)
    return spearman_correlation(xs, ys), len(xs)


def print_report(
    *,
    results: list[dict],
    n_total: int,
    n_tripped: int,
    n_overlap_dropped: int,
    n_price_skipped: int,
    threshold_pct: float,
    horizon_hours: float,
    rho: float | None,
    n_pairs: int,
    allow_overlap: bool,
) -> None:
    """Rapport lisible : volumes, Tik vs baselines, tests appariés, redondance."""
    print("\n=== Mesure SHADOW signaux micro (ADR-030 Étape 4) ===")
    print(f"Horizon de mesure : {horizon_hours} h — seuil : {threshold_pct} %")
    print(f"Signaux micro BTC trouvés          : {n_total}")
    print(f"  exclus 'tripped'                 : {n_tripped}")
    if allow_overlap:
        print("  ⚠ MODE CHEVAUCHANT (--allow-overlap) : significativité GONFLÉE")
    else:
        print(f"  retirés (fenêtres chevauchantes) : {n_overlap_dropped}")
    print(f"  sans prix disponible             : {n_price_skipped}")
    print(f"  ÉVALUÉS                          : {len(results)}")

    if not results:
        print("\nAucun signal micro évaluable. Deux causes probables :")
        print("  1. Le bridge labo→Tik n'émet pas encore (cf. tik_bridge.py côté labo).")
        print("  2. La fenêtre --since/--until ne couvre pas la collecte shadow.")
        return

    strategies = [
        evaluate_tik_baseline(results, threshold_pct),
        evaluate_random_baseline(results, threshold_pct),
        evaluate_constant_baseline(results, "long", threshold_pct),
        evaluate_constant_baseline(results, "short", threshold_pct),
        evaluate_constant_baseline(results, "neutral", threshold_pct),
    ]
    print(f"\n{'Stratégie':<16} | {'n':>4} | {'hit rate':>8} | {'gain moyen %':>12}")
    print("-" * 52)
    for st in strategies:
        print(
            f"{st['name']:<16} | {st['n']:>4} | {st['hit_rate']:>8.1%} "
            f"| {st['avg_gain']:>12.3f}"
        )

    print("\n--- Test apparié du gain : micro vs baselines constantes ---")
    print("(z apparié ; la question = « le micro ajoute-t-il du gain AU-DESSUS")
    print(" de la baseline de tendance ? » — pas seulement « bat-il Random ? »)")
    for direction in ("long", "short", "neutral"):
        sig = paired_gain_significance(results, direction)
        if sig is None:
            continue
        z = f"{sig['z']:.2f}" if sig.get("z") is not None else "n/a"
        p = f"{sig['p']:.4f}" if sig.get("p") is not None else "n/a"
        print(
            f"  vs Always {direction.upper():<8}: Δgain moyen "
            f"{sig['mean_diff']:+.3f} % | z={z} | p={p}"
        )

    print("\n--- Redondance micro ↔ swing BTC (ADR-030 §6 point 3) ---")
    if rho is None:
        print(f"  Paires insuffisantes ({n_pairs} < 3) — pas de corrélation calculable.")
    else:
        verdict = "REDONDANT (pas d'apport indépendant)" if abs(rho) > 0.5 else "non redondant"
        print(f"  Spearman(directions) = {rho:+.3f} sur {n_pairs} paires → {verdict}")

    print("\n--- Caveats (à relire avant toute conclusion) ---")
    if len(results) < MIN_SAMPLE_FOR_VERDICT:
        print(
            f"  ⚠ N={len(results)} < {MIN_SAMPLE_FOR_VERDICT} non chevauchants : "
            "PRÉLIMINAIRE, ne rien conclure. Relancer après ≥ 2 semaines."
        )
    print("  - Frais/slippage non comptés : un hit rate brut > 50 % ne suffit pas")
    print("    (le labo a mesuré H1 RÉFUTÉE après frais réels, cf. RESEARCH.md).")
    print("  - Veracity micro = défaut serveur 0.70, non informative ici.")
    print("  - Mesurer ≠ enrôler : NO-GO directionnel (2026-05-27) inchangé.")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mesure shadow des signaux micro (ADR-030 Étape 4) — lecture seule."
    )
    parser.add_argument(
        "--horizon-hours",
        type=float,
        default=HORIZON_MEASURE_HOURS["micro"],
        help="Horizon de mesure en heures (défaut : design horizon micro 2h).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=HORIZON_DEFAULT_THRESHOLD_PCT["micro"],
        help="Seuil directionnalité en %% (défaut : 0.3).",
    )
    parser.add_argument("--since-iso", type=str, default=None, help="Début fenêtre (ISO UTC).")
    parser.add_argument("--until-iso", type=str, default=None, help="Fin fenêtre (ISO UTC).")
    parser.add_argument(
        "--allow-overlap",
        action="store_true",
        help="Évalue TOUS les signaux même à fenêtres chevauchantes (déconseillé).",
    )
    parser.add_argument(
        "--corr-window-hours",
        type=float,
        default=1.0,
        help="Fenêtre d'appariement micro↔swing pour la corrélation (défaut 1h).",
    )
    args = parser.parse_args()

    horizon_td = timedelta(hours=args.horizon_hours)
    now = now_utc_naive()
    since = _parse_iso(args.since_iso) if args.since_iso else None
    until = _parse_iso(args.until_iso) if args.until_iso else now - horizon_td

    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_maker() as session:
            stmt = select(Signal).where(
                Signal.horizon == "micro",
                Signal.entity_id == "BTC",
                Signal.timestamp <= until,
            )
            if since is not None:
                stmt = stmt.where(Signal.timestamp >= since)
            micro_signals = list((await session.execute(stmt)).scalars().all())

            swing_stmt = select(Signal).where(
                Signal.horizon == "swing",
                Signal.entity_id == "BTC",
            )
            if since is not None:
                swing_stmt = swing_stmt.where(
                    Signal.timestamp >= since - timedelta(hours=args.corr_window_hours)
                )
            swing_signals = list((await session.execute(swing_stmt)).scalars().all())
    finally:
        await engine.dispose()

    n_total = len(micro_signals)
    non_tripped = [s for s in micro_signals if s.circuit_breaker_status != "tripped"]
    n_tripped = n_total - len(non_tripped)

    if args.allow_overlap:
        kept = sorted(non_tripped, key=lambda s: s.timestamp)
        n_overlap_dropped = 0
    else:
        kept = select_non_overlapping(non_tripped, horizon_td)
        n_overlap_dropped = len(non_tripped) - len(kept)

    # Fenêtre klines : 15m × 1000 ≈ 10.4 j. Si la collecte shadow est plus
    # ancienne, les signaux hors fenêtre sortiront en "sans prix disponible"
    # (visible dans le rapport, pas silencieux).
    async with httpx.AsyncClient(timeout=30.0) as client:
        btc_history = await fetch_btc_history(client, interval="15m", limit=1000)

    results: list[dict] = []
    n_price_skipped = 0
    for sig in kept:
        r = evaluate_micro_signal(sig, horizon_td, args.threshold, btc_history)
        if r is None:
            n_price_skipped += 1
        else:
            results.append(r)

    rho, n_pairs = correlate_micro_vs_swing(
        kept, swing_signals, timedelta(hours=args.corr_window_hours)
    )

    print_report(
        results=results,
        n_total=n_total,
        n_tripped=n_tripped,
        n_overlap_dropped=n_overlap_dropped,
        n_price_skipped=n_price_skipped,
        threshold_pct=args.threshold,
        horizon_hours=args.horizon_hours,
        rho=rho,
        n_pairs=n_pairs,
        allow_overlap=args.allow_overlap,
    )


if __name__ == "__main__":
    asyncio.run(main())
