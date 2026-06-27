"""Mesure SHADOW : dérivés Binance BTC (funding / OI / long-short) — lecture seule.

Question ouverte ADR-023
------------------------
Le positionnement dérivés Binance collecte en SHADOW (`tik.deriv.binance.btc.history`)
depuis le déploiement de l'ADR-023. C'est une famille de données DIFFÉRENTE du
sentiment retardé (Fear & Greed, news, Reddit, CoinGecko). Avant tout enrôlement
comme overlay, deux questions doivent être tranchées par la MESURE, pas par
l'intuition :
  1. Ces métriques ont-elles une valeur PRÉDICTIVE sur le rendement BTC forward ?
     (IC de Spearman funding[t] / ls_ratio[t] vs rendement t→t+H).
  2. Sont-elles INDÉPENDANTES des sources sentiment déjà branchées ? (sinon =
     redondance → empiler ne crée pas d'edge, ça dilue — cf. ADR-018).

Ce script LIT l'historique shadow et calcule un premier diagnostic. Il n'écrit
RIEN, ne touche ni au pipeline ni à la base. Conforme à la règle SHADOW vs
ENRÔLEMENT : mesurer ≠ enrôler. Chaque snapshot porte son propre `mark_price`,
donc les rendements forward sont calculables depuis l'historique lui-même (pas
besoin d'aligner une source de prix externe).

Méthode
-------
- Snapshots horaires : funding_rate, open_interest_btc/usd, long_short_ratio
  (global = retail, top = « smart money »), mark_price, fetched_at.
- IC prédictif : pour un horizon H (en heures ≈ pas), rendement forward
  r[i] = (mark_price[i+H] − mark_price[i]) / mark_price[i], puis
  Spearman(metric[i], r[i]). Un funding élevé = foule longue/leveragée : si
  l'hypothèse contrarian tient, on attend un IC NÉGATIF (funding haut → repli).
  On REPORTE l'IC sans conclure — l'échantillon est minuscule au démarrage.

Limites (engagement 13bis #8)
-----------------------------
1. **N minuscule au démarrage** : shadow tout juste lancé → tout IC est
   PRÉLIMINAIRE et probablement non significatif. Re-lancer après ≥ 2 semaines.
2. Snapshots horaires chevauchants → un IC sur rendements chevauchants gonfle la
   significativité (cf. mémoire measurement-overlapping-returns). On rapporte
   AUSSI le N de points NON chevauchants (espacés de H) comme garde-fou.
3. IC ≠ edge tradable. Le go/no-go directionnel reste NO-GO → aucun enrôlement
   directionnel sans mesure complète (IC stable + gain apparié vs Always SHORT).
4. L'indépendance vs Fear & Greed n'est pas calculée ici (suit, comme
   measure_coingecko_divergence, une fois assez de données accumulées).

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_btc_derivatives
    docker exec tik-core python -m tik_core.scripts.measure_btc_derivatives --horizon-hours 24
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from statistics import NormalDist

from redis import Redis

from tik_core.config import get_settings
from tik_core.scripts.backtest_numeric_sources import spearman_correlation
from tik_core.utils.time import now_utc

DERIV_HISTORY_KEY = "tik.deriv.binance.btc.history"


def parse_iso(s: str | None) -> datetime | None:
    """ISO-8601 tolérant (Z ou offset). Aware ou None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_chronological(raw: list[str]) -> list[dict]:
    """Décode les snapshots JSON et les trie du plus ancien au plus récent.

    Redis `lpush` empile en tête → `lrange 0 -1` rend le plus récent en premier.
    On trie par `fetched_at` pour être robuste à l'ordre d'insertion.
    """
    snaps: list[dict] = []
    for s in raw:
        try:
            d = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(d, dict) and parse_iso(d.get("fetched_at")) is not None:
            snaps.append(d)
    snaps.sort(key=lambda d: parse_iso(d.get("fetched_at")))  # type: ignore[arg-type, return-value]
    return snaps


def _series(snaps: list[dict], field: str) -> list[float | None]:
    """Extrait une colonne numérique (None si champ absent/invalide)."""
    out: list[float | None] = []
    for s in snaps:
        v = s.get(field)
        out.append(float(v) if isinstance(v, int | float) else None)
    return out


def forward_returns(mark_prices: list[float | None], horizon: int) -> list[float | None]:
    """Rendement forward r[i] = (P[i+H] − P[i]) / P[i], aligné sur l'index i.

    None si P[i] ou P[i+H] manquant/nul, ou si i+H dépasse la série.
    """
    n = len(mark_prices)
    out: list[float | None] = [None] * n
    for i in range(n - horizon):
        p0 = mark_prices[i]
        p1 = mark_prices[i + horizon]
        if p0 and p1 and p0 != 0:
            out[i] = (p1 - p0) / p0
    return out


def _aligned(xs: list[float | None], ys: list[float | None]) -> tuple[list[float], list[float]]:
    """Paires (x, y) où les deux sont non-None."""
    ax: list[float] = []
    ay: list[float] = []
    for x, y in zip(xs, ys, strict=True):
        if x is not None and y is not None:
            ax.append(x)
            ay.append(y)
    return ax, ay


def predictive_ic(
    metric: list[float | None], fwd: list[float | None], horizon: int
) -> dict[str, float | int | None]:
    """IC de Spearman metric[i] vs rendement forward, + N chevauchant et non chevauchant."""
    ax, ay = _aligned(metric, fwd)
    n_overlap = len(ax)
    # spearman_correlation exige ≥ 5 points (sinon None) — on aligne le seuil.
    ic = spearman_correlation(ax, ay) if n_overlap >= 5 else None
    # Sous-échantillon non chevauchant : un point tous les `horizon` pas.
    nx: list[float] = []
    ny: list[float] = []
    last = -(10**9)
    for i, (x, y) in enumerate(zip(metric, fwd, strict=True)):
        if x is not None and y is not None and i - last >= horizon:
            nx.append(x)
            ny.append(y)
            last = i
    n_indep = len(nx)
    ic_indep = spearman_correlation(nx, ny) if n_indep >= 5 else None
    return {"ic": ic, "n_overlap": n_overlap, "ic_indep": ic_indep, "n_indep": n_indep}


def ic_noise_band(n_indep: int | None, m_tests: int, alpha: float = 0.05) -> float | None:
    """|IC| critique sous H0 (pas de corrélation), corrigé multiple-testing.

    Sous H0, le rho de Spearman est ~ N(0, 1/(N−1)). On rejette « IC = bruit »
    si |IC| dépasse z_{α'/2} / sqrt(N−1), avec α' = α / m (Bonferroni : on teste
    m couples métrique×horizon, donc certains « sortent » par hasard sans
    correction). Retourne None si N trop faible (< 8) pour que ce soit honnête.
    """
    if n_indep is None or n_indep < 8:
        return None
    alpha_corr = alpha / max(1, m_tests)
    z = NormalDist().inv_cdf(1.0 - alpha_corr / 2.0)
    return z / math.sqrt(n_indep - 1)


def _stats(xs: list[float | None]) -> dict[str, float | int | None]:
    """Min/médiane/moyenne/max + N et % positifs d'une colonne (None ignorés)."""
    vals = [x for x in xs if x is not None]
    n = len(vals)
    if n == 0:
        return {"n": 0, "min": None, "median": None, "mean": None, "max": None, "pct_pos": None}
    s = sorted(vals)
    mid = n // 2
    median = s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0
    return {
        "n": n,
        "min": s[0],
        "median": median,
        "mean": sum(vals) / n,
        "max": s[-1],
        "pct_pos": sum(1 for v in vals if v > 0) / n * 100.0,
    }


def _fmt(v: float | int | None, nd: int = 4) -> str:
    return "n/a" if v is None else f"{round(v, nd)}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mesure SHADOW dérivés Binance BTC (lecture seule, n'enrôle rien)."
    )
    parser.add_argument("--horizon-hours", type=int, default=24, help="Horizon forward (pas ≈ h).")
    parser.add_argument("--min-points", type=int, default=48, help="Plancher non-fragile (pts).")
    args = parser.parse_args()

    print("=" * 76)
    print("  MESURE SHADOW — Dérivés Binance BTC (funding / OI / long-short)")
    print(f"  {now_utc().isoformat()}")
    print("=" * 76)

    r = Redis.from_url(get_settings().redis_url, decode_responses=True)
    raw = r.lrange(DERIV_HISTORY_KEY, 0, -1)
    snaps = to_chronological(raw)
    print(f"\nSnapshots dérivés shadow : {len(snaps)}")
    if not snaps:
        print("  Aucune donnée. (shadow tout juste démarré ? vérifier l'ingester)")
        return 0
    first = parse_iso(snaps[0].get("fetched_at"))
    last = parse_iso(snaps[-1].get("fetched_at"))
    if first and last:
        span_h = (last - first).total_seconds() / 3600.0
        print(f"Fenêtre : {first.isoformat()} → {last.isoformat()}  (~{span_h:.0f} h)")

    print("\n--- Distributions ---")
    for field, label in (
        ("funding_rate", "funding rate (/8h)"),
        ("open_interest_usd", "open interest (USD)"),
        ("long_short_ratio_global", "L/S ratio retail"),
        ("long_short_ratio_top", "L/S ratio top traders"),
    ):
        st = _stats(_series(snaps, field))
        # nd=6 : le funding rate (~1e-5) serait affiché 0.0 à 4 décimales.
        print(
            f"  {label:24s} N={st['n']:<4} "
            f"min={_fmt(st['min'], 6)} méd={_fmt(st['median'], 6)} "
            f"moy={_fmt(st['mean'], 6)} max={_fmt(st['max'], 6)} "
            f"%+={_fmt(st['pct_pos'], 0)}"
        )

    # Divergence retail vs top traders (signal de positionnement classique).
    lg = _series(snaps, "long_short_ratio_global")
    lt = _series(snaps, "long_short_ratio_top")
    cg, ct = _aligned(lg, lt)
    if len(cg) >= 3:
        print(f"\n  Spearman(L/S retail, L/S top) : {_fmt(spearman_correlation(cg, ct), 3)} (N={len(cg)})")
        print("    (faible corrélation = retail et smart money divergent → info de positionnement)")

    print(f"\n--- IC prédictif (horizon {args.horizon_hours} h) ---")
    marks = _series(snaps, "mark_price")
    fwd = forward_returns(marks, args.horizon_hours)
    for field, label in (
        ("funding_rate", "funding rate"),
        ("long_short_ratio_global", "L/S retail"),
        ("long_short_ratio_top", "L/S top"),
    ):
        res = predictive_ic(_series(snaps, field), fwd, args.horizon_hours)
        print(
            f"  IC({label:12s} → ret) = {_fmt(res['ic'], 3)} "
            f"(N chevauchant={res['n_overlap']}) | "
            f"non chevauchant = {_fmt(res['ic_indep'], 3)} (N={res['n_indep']})"
        )

    # --- Balayage multi-horizon : IC NON chevauchant vs bande de bruit corrigée ---
    sweep_horizons = [6, 12, 24, 48]
    sweep_metrics = (
        ("funding_rate", "funding"),
        ("long_short_ratio_global", "L/S retail"),
        ("long_short_ratio_top", "L/S top"),
    )
    m_tests = len(sweep_horizons) * len(sweep_metrics)
    print(
        f"\n--- Balayage multi-horizon : IC NON chevauchant vs bruit "
        f"(Bonferroni m={m_tests}) ---"
    )
    robust: list[tuple[str, int, float, int]] = []
    for h in sweep_horizons:
        fwd_h = forward_returns(marks, h)
        for field, label in sweep_metrics:
            res = predictive_ic(_series(snaps, field), fwd_h, h)
            crit = ic_noise_band(res["n_indep"] if isinstance(res["n_indep"], int) else None, m_tests)
            ic_indep = res["ic_indep"]
            flag = ""
            if ic_indep is not None and crit is not None and abs(ic_indep) > crit:
                flag = "  ⟵ AU-DELÀ du bruit corrigé"
                robust.append((label, h, ic_indep, res["n_indep"] if isinstance(res["n_indep"], int) else 0))
            print(
                f"  {label:12s} @ {h:>2}h : IC_indep={_fmt(ic_indep, 3):>7} "
                f"(N={res['n_indep']:<4}) | bruit ±{_fmt(crit, 3)}{flag}"
            )

    print("\n--- VERDICT ---")
    n_pts = len([m for m in marks if m is not None])
    if n_pts < args.min_points:
        print(f"  ⚠ N={n_pts} points < {args.min_points} → NON CONCLUANT (échantillon trop faible).")
    if robust:
        print("  🟡 Signal(aux) CANDIDAT(s) au-delà du bruit (après correction multiple-testing) :")
        for label, h, ic, n in robust:
            print(f"     - {label} @ {h}h : IC_indep={round(ic, 3)} (N non chevauchant={n})")
        print("  → JUSTIFIE l'étape 2 : backtest TRADABLE (vs Always-SHORT apparié, hors-")
        print("    échantillon, après coûts). IC ≠ edge : à confirmer avant tout enrôlement.")
    else:
        print("  ⚪ AUCUN signal robuste au-delà du bruit (multiple-testing corrigé).")
        print("    → Pas d'edge dérivés détectable à ce stade — cohérent avec le NO-GO.")
        print("    Soit l'échantillon est encore trop court, soit l'edge n'existe pas ici.")
    print("  ⚠ Rappels : IC sur rendements chevauchants gonfle la significativité (se fier")
    print("    au N non chevauchant) ; IC ≠ edge tradable ; indépendance vs FG/news non")
    print("    mesurée ici ; NO-GO directionnel inchangé. Re-lancer en accumulant les données.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
