"""Mesure SHADOW : pouvoir PRÉDICTIF du régime macro sur BTC & GOLD — lecture seule.

Chantier « les deux » (cf. session refonte cosmique 2026-06-19) : la couche macro
(ADR-028) est aujourd'hui CONTEXTE STRICT — elle ne touche jamais la direction. La
SEULE voie honnête pour qu'elle devienne un jour un overlay directionnel est de
MESURER d'abord si elle PRÉCÈDE les mouvements de prix. Ce script fait cette mesure,
sans rien enrôler ni modifier (aucun garde-fou levé, NO-GO directionnel inchangé).

Signaux macro testés (re-fetchés depuis FRED — le régime n'est qu'un snapshot Redis,
pas un historique) :
  - Fed Net Liquidity   (WALCL − TGA − RRP)            → hyp. liquidité ↑ ⇒ risque ↑ (IC>0)
  - Liquidité mondiale  (Fed + ECB + BoJ, convertie $) → idem (IC>0)
  - Taux réel 10Y       (DFII10)                       → hyp. taux ↑ ⇒ or ↓ (IC<0 sur GOLD)

Prix : closes quotidiens Binance (BTCUSDT) + Yahoo (GC=F). Cadence macro = HEBDO
(WALCL le mercredi) → on apparie chaque mercredi macro au prix du jour et au
rendement forward à h semaines.

Méthode
-------
- IC = Spearman(signal_macro, rendement forward) → POUVOIR PRÉDICTIF et SENS.
  * niveau   : le NIVEAU du signal prédit-il le rendement à venir ?
  * Δ4 sem.  : la VARIATION sur 4 semaines (= « liquidité qui monte/descend ») prédit-elle ?
- Directionnel : Δ>0 ⇒ long, sinon short ; hit rate comparé à « Always SHORT »
  (baseline de tendance, PAS Random — cf. mémoire measurement-rigor-controls).
- IC aussi calculé sur le sous-échantillon NON CHEVAUCHANT (1 point tous les h pas).

⚠ LIMITES (engagement 13bis #8 ; mémoires measurement-overlapping-returns / -rigor-controls)
--------------------------------------------------------------------------------------------
1. **Régime-dépendant** : ~2-3 ans d'historique = essentiellement UN cycle. Un IC
   significatif peut n'être que de la colinéarité avec la tendance de la période.
2. **Chevauchement** : à h ≥ 2 sem. les fenêtres se chevauchent → p-value gonflée ;
   lire en priorité la colonne NON-CHEV.
3. **N hebdo modeste** (~100-140 pts) → IC à ±0.1-0.2 près. Indicatif, pas un verdict.
4. **Pouvoir prédictif mesuré ≠ edge tradable.** NO-GO directionnel inchangé ; cette
   mesure prépare une éventuelle décision d'enrôlement SHADOW, elle ne lève rien.

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_macro_predictive
    docker exec tik-core python -m tik_core.scripts.measure_macro_predictive --horizons 1,2,4,8
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

import httpx

from tik_core.aggregator.macro_regime_ingester import (
    compute_global_liquidity_series,
    compute_net_liquidity_series,
    parse_observations,
)
from tik_core.config import get_settings
from tik_core.scripts.backtest_numeric_sources import spearman_correlation
from tik_core.utils.time import now_utc

FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (Tik macro backtest; read-only)"
DELTA_WEEKS = 4
NON_FRAGILE_MIN = 30


# --------------------------------------------------------------------------- #
# Fetch (HTTP GET uniquement — aucune écriture)                               #
# --------------------------------------------------------------------------- #


def fetch_fred(api_key: str, series_id: str, limit: int) -> dict[str, float]:
    """{date_iso: valeur} d'une série FRED (desc). {} si échec."""
    try:
        with httpx.Client(timeout=25.0) as client:
            r = client.get(
                FRED_OBS,
                params={
                    "series_id": series_id,
                    "api_key": api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": limit,
                },
            )
            r.raise_for_status()
            return parse_observations(r.json().get("observations", []))
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ⚠ FRED {series_id}: {exc}", file=sys.stderr)
        return {}


def btc_daily_closes(limit: int = 1000) -> dict[date, float]:
    """{jour UTC: close BTC} depuis les klines quotidiens Binance. {} si échec."""
    try:
        with httpx.Client(timeout=25.0) as client:
            r = client.get(
                BINANCE_KLINES_URL,
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": limit},
            )
            r.raise_for_status()
            rows = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ⚠ Binance: {exc}", file=sys.stderr)
        return {}
    out: dict[date, float] = {}
    for k in rows:
        try:
            out[datetime.fromtimestamp(int(k[0]) / 1000, tz=UTC).date()] = float(k[4])
        except (TypeError, ValueError, IndexError):
            continue
    return out


def gold_daily_closes(rng: str = "3y") -> dict[date, float]:
    """{jour UTC: close GC=F} depuis Yahoo chart (daily). {} si échec/throttle."""
    try:
        with httpx.Client(timeout=25.0) as client:
            r = client.get(
                YAHOO_CHART_URL.format(symbol="GC=F"),
                params={"interval": "1d", "range": rng},
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            stamps = res["timestamp"]
            closes = res["indicators"]["quote"][0]["close"]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        print(f"  ⚠ Yahoo GC=F: {exc}", file=sys.stderr)
        return {}
    out: dict[date, float] = {}
    for t, cl in zip(stamps, closes, strict=False):
        if cl is None:
            continue
        try:
            out[datetime.fromtimestamp(int(t), tz=UTC).date()] = float(cl)
        except (TypeError, ValueError):
            continue
    return out


# --------------------------------------------------------------------------- #
# Helpers d'alignement                                                        #
# --------------------------------------------------------------------------- #


def price_on(closes: dict[date, float], target: date, tol_days: int = 4) -> float | None:
    """Close à `target` ou le plus proche en arrière (≤ tol_days). None sinon."""
    for i in range(tol_days + 1):
        d = date.fromordinal(target.toordinal() - i)
        if d in closes:
            return closes[d]
    return None


def weekly_from_series(series: list[tuple[str, float]]) -> dict[date, float]:
    """list[(date_iso, valeur)] → {date: valeur}."""
    return {date.fromisoformat(d): v for d, v in series}


def resample_weekly(daily_iso: dict[str, float], anchors: list[date], tol_days: int = 7) -> dict[date, float]:
    """Valeur d'une série quotidienne (clé ISO) sur/avant chaque date d'ancrage hebdo."""
    parsed = {date.fromisoformat(d): v for d, v in daily_iso.items()}
    out: dict[date, float] = {}
    for ad in anchors:
        for i in range(tol_days + 1):
            d = date.fromordinal(ad.toordinal() - i)
            if d in parsed:
                out[ad] = parsed[d]
                break
    return out


def _fmt_ic(ic: float | None) -> str:
    return "  n/a" if ic is None else f"{ic:+.3f}"


def _fmt_pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


# --------------------------------------------------------------------------- #
# Mesure d'un signal vs un actif                                              #
# --------------------------------------------------------------------------- #


def measure_signal(
    label: str,
    expect: str,
    closes: dict[date, float],
    signal: dict[date, float],
    horizons_w: list[int],
) -> None:
    """Affiche IC niveau / IC Δ / non-chev / directionnel pour chaque horizon."""
    dates = sorted(signal)
    print(f"\n  ▸ {label}")
    print(f"      attendu : {expect}")
    for h in horizons_w:
        level_pairs: list[tuple[float, float]] = []
        delta_pairs: list[tuple[float, float]] = []
        macro_hits = short_hits = n_dir = 0
        for idx, d in enumerate(dates):
            p0 = price_on(closes, d)
            if p0 is None or p0 <= 0:
                continue
            pf = price_on(closes, date.fromordinal(d.toordinal() + h * 7))
            if pf is None:
                continue
            ret = pf / p0 - 1.0
            level_pairs.append((signal[d], ret))
            if idx >= DELTA_WEEKS:
                delta = signal[d] - signal[dates[idx - DELTA_WEEKS]]
                delta_pairs.append((delta, ret))
                n_dir += 1
                pred_long = delta > 0
                if (pred_long and ret > 0) or (not pred_long and ret < 0):
                    macro_hits += 1
                if ret < 0:
                    short_hits += 1
        ic_level = spearman_correlation([p[0] for p in level_pairs], [p[1] for p in level_pairs])
        ic_delta = spearman_correlation([p[0] for p in delta_pairs], [p[1] for p in delta_pairs])
        nono = delta_pairs[::h]
        ic_nono = spearman_correlation([p[0] for p in nono], [p[1] for p in nono])
        mhr = macro_hits / n_dir if n_dir else None
        shr = short_hits / n_dir if n_dir else None
        print(
            f"      h={h:>2}sem  N={len(delta_pairs):3d}  "
            f"IC_niveau={_fmt_ic(ic_level)}  IC_Δ{DELTA_WEEKS}s={_fmt_ic(ic_delta)}  "
            f"[non-chev N={len(nono):2d} IC={_fmt_ic(ic_nono)}]  "
            f"dir Δ {_fmt_pct(mhr)} vs AlwaysSHORT {_fmt_pct(shr)}"
        )


# --------------------------------------------------------------------------- #
# main                                                                        #
# --------------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mesure SHADOW pouvoir prédictif du macro sur BTC & GOLD (lecture seule)."
    )
    parser.add_argument("--horizons", default="1,2,4", help="Horizons en SEMAINES, ex: 1,2,4,8")
    args = parser.parse_args()
    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]

    print("=" * 80)
    print("  MESURE SHADOW — pouvoir PRÉDICTIF du régime macro sur BTC & GOLD")
    print(f"  {now_utc().isoformat()}  (lecture seule — n'enrôle rien, NO-GO inchangé)")
    print("=" * 80)

    api_key = get_settings().fred_api_key
    if not api_key:
        print("  ⚠ FRED_API_KEY absente — impossible de mesurer.", file=sys.stderr)
        return 1

    # --- Séries macro (re-fetch FRED + fonctions pures de l'ingester) ---
    walcl = fetch_fred(api_key, "WALCL", 160)
    tga = fetch_fred(api_key, "WTREGEN", 160)
    rrp = fetch_fred(api_key, "RRPONTSYD", 1100)
    ecb = fetch_fred(api_key, "ECBASSETSW", 160)
    boj = fetch_fred(api_key, "JPNASSETS", 48)
    eurusd = fetch_fred(api_key, "DEXUSEU", 1100)
    jpyusd = fetch_fred(api_key, "DEXJPUS", 1100)
    dfii10 = fetch_fred(api_key, "DFII10", 1100)

    net_liq = weekly_from_series(compute_net_liquidity_series(walcl, tga, rrp))
    global_liq = weekly_from_series(
        compute_global_liquidity_series(walcl, ecb, boj, eurusd, jpyusd)
    )
    anchors = sorted(net_liq)
    real_rate = resample_weekly(dfii10, anchors)

    btc = btc_daily_closes(1000)
    gold = gold_daily_closes("3y")

    print(
        f"\nSéries : net_liq={len(net_liq)} sem · global_liq={len(global_liq)} sem · "
        f"real_rate={len(real_rate)} sem · BTC={len(btc)} j · GOLD={len(gold)} j"
    )
    if len(net_liq) < 20 or not btc:
        print("  ⚠ Données insuffisantes (FRED ou Binance KO) — mesure non fiable.", file=sys.stderr)
        return 1

    print("\n" + "-" * 80)
    print("  BTC")
    print("-" * 80)
    measure_signal("Fed Net Liquidity", "IC>0 si liquidité↑ ⇒ BTC↑", btc, net_liq, horizons)
    measure_signal("Liquidité mondiale", "IC>0 si liquidité↑ ⇒ BTC↑", btc, global_liq, horizons)
    measure_signal("Taux réel 10Y", "IC<0 si taux↑ ⇒ BTC↓ (risque)", btc, real_rate, horizons)

    if gold:
        print("\n" + "-" * 80)
        print("  GOLD")
        print("-" * 80)
        measure_signal("Fed Net Liquidity", "IC>0 si liquidité↑ ⇒ or↑", gold, net_liq, horizons)
        measure_signal("Liquidité mondiale", "IC>0 si liquidité↑ ⇒ or↑", gold, global_liq, horizons)
        measure_signal("Taux réel 10Y", "IC<0 si taux↑ ⇒ or↓ (classique)", gold, real_rate, horizons)
    else:
        print("\n  ⚠ GOLD non mesuré (Yahoo GC=F indisponible/throttle depuis cette IP).")

    print("\n" + "=" * 80)
    print("  LECTURE / GARDE-FOUS")
    print("=" * 80)
    print("  • IC ≈ 0 (|IC|<0.15) → pas de pouvoir prédictif → NE PAS enrôler.")
    print("  • IC franc et STABLE entre horizons + colonne non-chev → candidat à creuser.")
    print("  • Régime-dépendant (1 cycle) : un IC franc peut n'être que de la colinéarité")
    print("    avec la tendance. Re-mesurer sur un régime opposé avant toute conclusion.")
    print("  • Pouvoir prédictif ≠ edge tradable. NO-GO directionnel INCHANGÉ ; aucun")
    print("    enrôlement sans ≥ 2 semaines de shadow apparié vs Always SHORT (règle CLAUDE.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
