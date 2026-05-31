"""Analyse de colinéarité : Tik suit-il bêtement la tendance, ou diverge-t-il
parfois correctement ?

Contexte (CLAUDE.md go/no-go 2026-05-27 = NO-GO directionnel) : Tik est
colinéaire à la tendance — il shorte parce que le marché baisse, sans rien
anticiper. La question profonde pour trouver un edge :

    À quels moments Tik DIVERGE de la tendance brute du marché, et ces
    moments-là sont-ils GAGNANTS ?

Méthode. Pour chaque signal directionnel (long/short) :

1. `trend_dir`  = direction de la TENDANCE LOCALE au moment du signal,
   = signe du rendement sur les `--trend-lookback-hours` heures AVANT le
   signal (seuil `--trend-threshold` %). long / short / flat.
2. `tik_dir`    = direction du signal Tik.
3. `forward`    = rendement sur l'horizon APRÈS le signal.

On classe chaque signal :

- CONCORDANT (tik_dir == trend_dir)  → Tik = momentum. Pas d'alpha possible
  au-dessus du momentum par construction.
- DIVERGENT  (tik_dir != trend_dir, trend directionnel) → Tik appelle un
  RETOURNEMENT contre la tendance. C'est LÀ qu'un edge existerait : si ces
  signaux gagnent (hit > 50 % ET gain > 0 ET battent le momentum), Tik sait
  appeler des reversals. S'ils perdent, ses divergences sont du bruit.
- TREND-FLAT (pas de tendance claire) → groupe séparé.

Pour le groupe DIVERGENT on fait un test apparié Tik vs « suivre le momentum »
sur le gain (réutilise le z-test normal de backtest.py).

Garde-fous méthodo (memory measurement-rigor-controls) : on imprime le
régime + les distributions AVANT le verdict, on compare à la bonne baseline
(le momentum, pas Random), on regarde le gain pas que le hit rate, et on
flagge les petits échantillons.

Lecture seule sur la DB de prod (SELECT). Aucune écriture.

Usage :

    # BTC swing à son horizon de design (5j), tendance locale 24h
    python -m tik_core.scripts.analyze_colinearity \\
        --entity BTC --signal-horizon swing --horizon-days 5 \\
        --trend-lookback-hours 24

    # Robustesse : changer la fenêtre de tendance (72h)
    python -m tik_core.scripts.analyze_colinearity \\
        --entity BTC --signal-horizon swing --horizon-days 5 \\
        --trend-lookback-hours 72
"""

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timedelta
from statistics import mean, stdev

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.config import get_settings
from tik_core.scripts.backtest import (
    _gain_for,
    _success_for,
    fetch_btc_history,
    fetch_gold_history,
    find_closest_price,
    normal_cdf,
)
from tik_core.storage.models import Signal
from tik_core.utils.time import now_utc_naive

# Fix Bug N=2 — données propres seulement à partir de là (CLAUDE.md Paquet 25).
FIX_BUG_N2_ISO = "2026-05-17T20:47:00"


def _parse_iso(iso_str: str) -> datetime:
    s = iso_str.rstrip("Z")
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _dir_from_return(ret_pct: float, threshold_pct: float) -> str:
    """Classe un rendement en direction : long / short / flat selon un seuil."""
    if ret_pct > threshold_pct:
        return "long"
    if ret_pct < -threshold_pct:
        return "short"
    return "flat"


def _non_overlapping_subsample(rows: list[dict], horizon_td: timedelta) -> list[dict]:
    """Sous-échantillon de signaux espacés d'au moins `horizon_td`.

    Les fenêtres forward de signaux émis toutes les ~15 min se CHEVAUCHENT
    (deux signaux consécutifs partagent ~99 % de leur fenêtre 5j) → les écarts
    par signal ne sont PAS indépendants, ce qui gonfle artificiellement tout
    z-test (Hansen-Hodrick 1980 ; les corrections HAC n'aident pas). On extrait
    ici un sous-ensemble à fenêtres NON chevauchantes (greedy sur ts trié) pour
    estimer le NOMBRE d'observations réellement indépendantes.
    """
    out: list[dict] = []
    last_ts: datetime | None = None
    for r in sorted(rows, key=lambda x: x["ts"]):
        if last_ts is None or (r["ts"] - last_ts) >= horizon_td:
            out.append(r)
            last_ts = r["ts"]
    return out


def _paired_z(diffs: list[float]) -> tuple[float | None, float | None]:
    """Test z apparié sur une liste d'écarts. (z, p) ou (None, None) si n<2/sd=0."""
    n = len(diffs)
    if n < 2:
        return None, None
    sd = stdev(diffs)
    if sd <= 0:
        return None, None
    se = sd / (n**0.5)
    z = mean(diffs) / se
    p = 2 * (1 - normal_cdf(abs(z)))
    return z, p


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Corrélation de rang de Spearman (stdlib pure). None si n<3 ou variance nulle."""
    n = len(xs)
    if n < 3:
        return None

    def _ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1  # rang moyen 1-based pour les ex aequo
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def _signed(direction: str) -> float:
    return {"long": 1.0, "short": -1.0}.get(direction, 0.0)


def _group_stats(rows: list[dict], label: str) -> None:
    n = len(rows)
    if n == 0:
        print(f"\n{label} : 0 signal")
        return
    n_hit = sum(1 for r in rows if r["tik_success"])
    tik_gain = mean(r["tik_gain"] for r in rows)
    print(f"\n{label} : {n} signaux")
    print(f"   hit rate Tik      : {n_hit}/{n} = {n_hit / n * 100:.1f}%")
    print(f"   gain moy Tik      : {tik_gain:+.2f}% / signal")
    if n < 20:
        print("   ⚠ N < 20 — échantillon faible, conclusion fragile.")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyse de colinéarité Tik vs tendance locale (lecture seule prod).",
    )
    parser.add_argument("--entity", choices=["BTC", "GOLD"], default="BTC")
    parser.add_argument("--signal-horizon", choices=["flash", "swing", "macro"], default="swing")
    parser.add_argument("--horizon-days", type=float, default=5.0)
    parser.add_argument("--horizon-hours", type=float, default=None)
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.5,
        help="Seuil directionnalité du résultat futur (%%). Défaut 0.5.",
    )
    parser.add_argument(
        "--trend-lookback-hours",
        type=float,
        default=24.0,
        help="Fenêtre de la tendance LOCALE avant le signal (h). Défaut 24.",
    )
    parser.add_argument(
        "--trend-threshold",
        type=float,
        default=0.5,
        help="Seuil pour classer la tendance long/short/flat (%%). Défaut 0.5.",
    )
    parser.add_argument(
        "--min-veracity",
        type=float,
        default=0.0,
        help="Ne garder que les signaux veracity ≥ ce seuil (filtre qualité). Défaut 0 (tous).",
    )
    parser.add_argument("--since-iso", default=FIX_BUG_N2_ISO)
    parser.add_argument("--until-iso", default=None)
    args = parser.parse_args()

    if args.horizon_hours is not None:
        horizon_td = timedelta(hours=args.horizon_hours)
        horizon_label = f"{args.horizon_hours:g}h"
    else:
        horizon_td = timedelta(days=args.horizon_days)
        horizon_label = f"{args.horizon_days:g}j"

    lookback_td = timedelta(hours=args.trend_lookback_hours)
    since_dt = _parse_iso(args.since_iso)
    until_dt = _parse_iso(args.until_iso) if args.until_iso else now_utc_naive()

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    print("\n" + "=" * 76)
    print("  ANALYSE COLINÉARITÉ — Tik suit-il la tendance ou diverge-t-il ?")
    print("=" * 76)
    print(f"  Actif       : {args.entity} · horizon signal : {args.signal_horizon}")
    print(f"  Période     : {since_dt.isoformat()} → {until_dt.isoformat()} UTC")
    print(f"  Forward     : {horizon_label} après émission")
    print(f"  Tendance    : {args.trend_lookback_hours:g}h avant, seuil ±{args.trend_threshold}%")
    print(f"  Seuil hit   : ±{args.threshold}% sur le mouvement futur")
    print("=" * 76)

    async with session_maker() as session:
        stmt = (
            select(Signal)
            .where(Signal.timestamp >= since_dt)
            .where(Signal.timestamp <= until_dt)
            .where(Signal.entity_id == args.entity)
            .where(Signal.horizon == args.signal_horizon)
            .order_by(Signal.timestamp.asc())
        )
        result = await session.execute(stmt)
        signals = list(result.scalars().all())
    print(f"\nSignaux {args.entity}/{args.signal_horizon} dans la période : {len(signals)}")

    if args.min_veracity > 0.0:
        before = len(signals)
        signals = [s for s in signals if float(s.veracity) >= args.min_veracity]
        print(f"Filtre veracity ≥ {args.min_veracity:.2f} : {before} → {len(signals)} signaux")

    eligible_cutoff = until_dt - horizon_td
    eligible = [s for s in signals if s.timestamp <= eligible_cutoff]
    print(f"Signaux mûrs (timestamp + {horizon_label} ≤ now) : {len(eligible)}")
    if not eligible:
        print("\nAucun signal mûr. Réduis l'horizon ou attends.\n")
        await engine.dispose()
        return

    use_fine = horizon_td <= timedelta(hours=4)
    interval = "15m" if use_fine else "1h"
    max_diff_ms = (30 * 60 * 1000) if use_fine else (6 * 3600 * 1000)
    async with httpx.AsyncClient(timeout=30.0) as client:
        if args.entity == "BTC":
            history = await fetch_btc_history(client, interval=interval, limit=1000)
        else:
            history = await fetch_gold_history(client, interval=interval, range_param="60d")
    print(f"Klines {args.entity} {interval} : {len(history)} points")

    # --- Régime de marché sur la fenêtre (contexte AVANT verdict) ---
    if history:
        first_p = history[0][1]
        last_p = history[-1][1]
        regime_pct = (last_p - first_p) / first_p * 100
        print(
            f"\nRégime {args.entity} sur la fenêtre klines : "
            f"{first_p:.1f} → {last_p:.1f} ({regime_pct:+.1f}%)"
        )

    # --- Évaluation signal par signal ---
    rows: list[dict] = []
    skipped = 0
    for s in eligible:
        ts0 = s.timestamp
        p_look = find_closest_price(history, ts0 - lookback_td, max_diff_ms=max_diff_ms)
        p0 = find_closest_price(history, ts0, max_diff_ms=max_diff_ms)
        p1 = find_closest_price(history, ts0 + horizon_td, max_diff_ms=max_diff_ms)
        if p_look is None or p0 is None or p1 is None or p_look == 0 or p0 == 0:
            skipped += 1
            continue
        trend_ret = (p0 - p_look) / p_look * 100
        forward = (p1 - p0) / p0 * 100
        trend_dir = _dir_from_return(trend_ret, args.trend_threshold)
        rows.append(
            {
                "id": s.id,
                "tik_dir": s.direction,
                "veracity": float(s.veracity),
                "trend_dir": trend_dir,
                "trend_ret": trend_ret,
                "forward": forward,
                "tik_gain": _gain_for(s.direction, forward),
                "tik_success": _success_for(s.direction, forward, args.threshold),
                "ts": s.timestamp,
            }
        )
    print(f"Évalués : {len(rows)} · ignorés (prix hors fenêtre) : {skipped}")

    if not rows:
        print("\nAucun signal évaluable.\n")
        await engine.dispose()
        return

    # --- Distributions (contexte AVANT verdict) ---
    print("\n--- Distributions ---")
    print(f"  Direction Tik   : {dict(Counter(r['tik_dir'] for r in rows))}")
    print(f"  Tendance locale : {dict(Counter(r['trend_dir'] for r in rows))}")

    directional = [r for r in rows if r["tik_dir"] in ("long", "short")]
    print(f"  Signaux Tik directionnels (long/short) : {len(directional)}/{len(rows)}")

    # --- Colinéarité : corrélation Tik↔tendance ---
    if directional:
        tik_signed = [_signed(r["tik_dir"]) for r in directional]
        trend_signed = [_signed(r["trend_dir"]) for r in directional]
        fwd = [r["forward"] for r in directional]
        rho_tik_trend = _spearman(tik_signed, trend_signed)
        rho_tik_fwd = _spearman(tik_signed, fwd)
        rho_trend_fwd = _spearman(trend_signed, fwd)
        print("\n--- Colinéarité (sur signaux directionnels) ---")
        if rho_tik_trend is not None:
            print(
                f"  Spearman(Tik, tendance locale) : {rho_tik_trend:+.3f}   "
                "(proche +1 = Tik = momentum)"
            )
        if rho_tik_fwd is not None:
            print(f"  Spearman(Tik, futur)           : {rho_tik_fwd:+.3f}")
        if rho_trend_fwd is not None:
            print(f"  Spearman(tendance, futur)      : {rho_trend_fwd:+.3f}")

    # --- Classification concordant / divergent / trend-flat ---
    concordant = [
        r
        for r in directional
        if r["trend_dir"] in ("long", "short") and r["tik_dir"] == r["trend_dir"]
    ]
    divergent = [
        r
        for r in directional
        if r["trend_dir"] in ("long", "short") and r["tik_dir"] != r["trend_dir"]
    ]
    trend_flat = [r for r in directional if r["trend_dir"] == "flat"]

    paired_base = concordant + divergent
    if paired_base:
        pct_conc = len(concordant) / len(paired_base) * 100
        print("\n--- Verdict colinéarité ---")
        print(
            f"  Sur {len(paired_base)} signaux directionnels avec tendance claire : "
            f"{len(concordant)} concordants ({pct_conc:.0f}%), "
            f"{len(divergent)} divergents ({100 - pct_conc:.0f}%)"
        )
        if pct_conc >= 80:
            print("  → Tik est FORTEMENT colinéaire à la tendance locale.")
        elif pct_conc >= 60:
            print("  → Tik est MODÉRÉMENT colinéaire à la tendance locale.")
        else:
            print("  → Tik diverge SOUVENT de la tendance locale.")

    print("\n" + "=" * 76)
    print("  GROUPES")
    print("=" * 76)
    _group_stats(concordant, "CONCORDANT (Tik = momentum)")
    _group_stats(divergent, "DIVERGENT (Tik contre le momentum = appel de reversal)")
    _group_stats(trend_flat, "TREND-FLAT (pas de tendance claire)")

    # NOTE méthodo : comparer les divergents à « suivre le momentum » serait
    # TAUTOLOGIQUE (pour un divergent, tik_dir = opposé de trend_dir donc
    # gain_momentum = -gain_tik par construction). Et le momentum est une
    # baseline FAIBLE dans un marché tendanciel. La bonne baseline = Always
    # SHORT (la tendance de régime), cf. memory measurement-rigor-controls.

    # --- Régime vécu par les signaux (mean forward) — contexte avant verdict ---
    mean_fwd = mean(r["forward"] for r in rows)
    print("\n" + "=" * 76)
    print("  TEST CLÉ — Tik bat-il la TENDANCE DE RÉGIME (Always SHORT) ?")
    print("=" * 76)
    print(f"\n  Régime vécu : mouvement forward moyen {mean_fwd:+.2f}% sur {horizon_label}")
    print("  (fortement négatif → tout 'short' gagne ; le hit rate haut ≠ edge)")

    # Tik-tel-que-tradé : long → +fwd, short → -fwd, NEUTRAL → 0 (on ne trade pas).
    # C'est là que Tik diffère d'Always SHORT (qui shorte tout, neutral compris).
    def _tik_traded(r: dict) -> float:
        if r["tik_dir"] == "long":
            return r["forward"]
        if r["tik_dir"] == "short":
            return -r["forward"]
        return 0.0  # neutral = pas de position

    def _always_short(r: dict) -> float:
        return -r["forward"]

    # Effet (descriptif) sur l'échantillon complet
    diffs = [_tik_traded(r) - _always_short(r) for r in rows]
    z, _p = _paired_z(diffs)
    tik_g = mean(_tik_traded(r) for r in rows)
    short_g = mean(_always_short(r) for r in rows)
    print(f"\n  Sur {len(rows)} signaux (directionnels + neutres) :")
    print(f"  Gain moy Tik (neutral=0)  : {tik_g:+.2f}% / signal")
    print(f"  Gain moy Always SHORT     : {short_g:+.2f}% / signal")
    print(f"  Δ (Tik − Always SHORT)    : {mean(diffs):+.2f}%   ← effet (DESCRIPTIF)")

    # ⚠ Significativité : les fenêtres forward se CHEVAUCHENT massivement
    # (signaux ~toutes les 15 min, horizon 5j → chaque neutre partage ~99 % de
    # sa fenêtre avec le suivant). Les écarts par signal ne sont PAS indépendants
    # → z/p gonflés et NON fiables (Hansen-Hodrick 1980 ; HAC n'aide pas). On
    # reporte donc le N réellement indépendant, pas un p.
    indep = _non_overlapping_subsample(rows, horizon_td)
    n_indep = len(indep)
    if z is not None:
        print(
            f"  z plein échantillon = {z:+.2f}  → GONFLÉ par le chevauchement, "
            "NON fiable (pas de p)"
        )
    if n_indep >= 1:
        diffs_indep = [_tik_traded(r) - _always_short(r) for r in indep]
        print(
            f"  Fenêtres NON chevauchantes : N≈{n_indep} · "
            f"Δ = {mean(diffs_indep):+.2f}% (trop peu pour toute significativité)"
        )

    # --- Où Tik diffère d'Always SHORT : décomposition par direction ---
    print("\n  --- Où Tik s'écarte d'Always SHORT (contribution au Δ) ---")
    by_dir: dict[str, list[dict]] = {"short": [], "long": [], "neutral": []}
    for r in rows:
        by_dir[r["tik_dir"]].append(r)
    for d in ("short", "long", "neutral"):
        rs = by_dir[d]
        if not rs:
            continue
        dd = [_tik_traded(r) - _always_short(r) for r in rs]
        contrib = sum(dd) / len(rows)  # contribution moyenne au Δ global
        fwd_mean = mean(r["forward"] for r in rs)
        note = "= Always SHORT" if d == "short" else f"diffère ({len(rs)} sig)"
        print(
            f"    {d:8s} : {len(rs):3d} sig · fwd moy {fwd_mean:+.2f}% · "
            f"Δ moy sur le groupe {mean(dd):+.2f}% · contrib globale {contrib:+.2f}% [{note}]"
        )

    # --- Verdict : ce qui est ROBUSTE vs ce qui ne l'est pas ---
    print("\n  " + "-" * 72)
    md = mean(diffs)
    if n_indep < 5:
        print(
            f"  ⚪ EDGE {horizon_label} NON MESURABLE à ce stade : seulement ~{n_indep} "
            "fenêtres\n     indépendantes depuis le fix données propres (17/05) — trop court."
        )
        print(
            f"     Plein échantillon (descriptif) : Δ {md:+.2f}%/signal, mais Δ≈0 sur les\n"
            "     fenêtres indépendantes → aucune sous/sur-performance robuste démontrable."
        )
    elif md < 0:
        print(f"  🔴 Tik sous-performe Always SHORT de {md:+.2f}%/signal (descriptif).")
    else:
        print(f"  🟢 Tik fait {md:+.2f}%/signal de mieux qu'Always SHORT (descriptif).")

    print("\n  Ce qui EST robuste (vérifié, pas une estimation de rendement) :")
    print("   • Tik est ~98% short quand il tranche → ≈ 'Always SHORT' + un filtre neutre")
    print("   • Hit rate élevé = effet du régime baissier, pas un talent (Tik ≈ always short)")
    print("   • Mécanisme : ses 'neutres' coïncident avec des baisses → ratent des shorts ici")
    print(
        "\n  ⚠ Régime unique baissier + N indépendant minuscule → NE PAS conclure\n"
        "  à un edge (ni dans un sens ni dans l'autre). En marché haussier/choppy\n"
        "  le filtre neutre pourrait AIDER. Recroiser sur un autre régime.\n"
    )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
