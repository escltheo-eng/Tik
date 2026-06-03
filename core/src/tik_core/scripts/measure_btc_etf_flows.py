"""Mesure SHADOW : flux ETF spot BTC (inflow/outflow net quotidien) — lecture seule.

Question ouverte ADR-024
------------------------
Les flux ETF spot BTC US collectent en SHADOW (`tik.etf.btc.history`) depuis le
déploiement de l'ADR-024. C'est une famille de données DIFFÉRENTE du sentiment
retardé (Fear & Greed, news, Reddit, CoinGecko) et des dérivés (ADR-023) : c'est
de la demande institutionnelle réelle. Avant tout enrôlement comme overlay, deux
questions doivent être tranchées par la MESURE, pas par l'intuition :
  1. Le flux net quotidien a-t-il une valeur PRÉDICTIVE sur le rendement BTC
     forward ? (IC de Spearman flux[d] vs rendement d→d+H).
  2. Est-il INDÉPENDANT du prix (les flux suivent-ils simplement le prix —
     colinéaire au trend, comme tout le reste — ou apportent-ils une info en
     avance) ? (suit, une fois assez de données accumulées).

Ce script LIT l'historique shadow + des clôtures BTC quotidiennes (Binance
klines, lecture seule) et calcule un premier diagnostic. Il n'écrit RIEN, ne
touche ni au pipeline ni à la base. Conforme à la règle SHADOW vs ENRÔLEMENT :
mesurer ≠ enrôler.

BONUS backfill : SoSoValue renvoie tout l'historique ETF (plusieurs mois), donc
un IC PRÉLIMINAIRE est calculable dès maintenant — mais il est in-sample et
régime-dépendant (cf. limites), à confirmer hors échantillon.

Méthode
-------
- Flux quotidien net (USD) par jour de bourse US `d` (publié le soir de `d`).
- Anti-lookahead : on entre au close BTC de `d + lag` (défaut lag=1, le flux de
  `d` n'est connu qu'après la clôture US de `d`), on sort à `d + lag + H`.
  Rendement forward r = (close[d+lag+H] − close[d+lag]) / close[d+lag].
- IC = Spearman(flux[d], r). Hypothèse trend-following naïve : inflow positif →
  rendement positif → IC POSITIF attendu. On REPORTE l'IC sans conclure.

Limites (engagement 13bis #8)
-----------------------------
1. **N quotidien petit** : ~250 jours ouvrés/an au mieux, et le shadow propre ne
   démarre qu'aujourd'hui. L'IC backfill est PRÉLIMINAIRE et in-sample.
2. **Chevauchement si H > 1** : des fenêtres de H jours sur un pas quotidien se
   chevauchent → l'IC gonfle la significativité (mémoire
   measurement-overlapping-returns). On rapporte AUSSI un N non chevauchant.
3. **Colinéarité prix probable** : les inflows ETF peuvent simplement SUIVRE le
   prix (acheter quand ça monte) → redondant avec le trend, pas un edge. À
   mesurer, pas supposer. IC ≠ edge tradable. NO-GO directionnel inchangé.
4. **Source de prix externe** : on aligne sur les klines Binance (spot), pas sur
   le NAV implicite ETF (discount/premium parasite). Un échec réseau Binance ⇒
   pas de mesure (le script le dit, n'invente rien).

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_btc_etf_flows
    docker exec tik-core python -m tik_core.scripts.measure_btc_etf_flows --horizon-days 5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime, timedelta

import httpx
from redis import Redis

from tik_core.config import get_settings
from tik_core.scripts.backtest_numeric_sources import spearman_correlation
from tik_core.utils.time import now_utc

ETF_HISTORY_KEY = "tik.etf.btc.history"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


def _shift(date_str: str, days: int) -> str | None:
    """Décale une date 'YYYY-MM-DD' de `days` jours calendaires (None si invalide)."""
    try:
        y, m, d = (int(x) for x in date_str.split("-"))
        return (date(y, m, d) + timedelta(days=days)).isoformat()
    except (ValueError, TypeError):
        return None


def fetch_btc_daily_closes(limit: int = 1000) -> dict[str, float]:
    """Clôtures BTC quotidiennes (UTC) depuis Binance : {date 'YYYY-MM-DD' → close}.

    Lecture seule, source de prix externe pour la mesure (pas le pipeline).
    Retourne {} en cas d'échec réseau — l'appelant le signale.
    """
    try:
        r = httpx.get(
            BINANCE_KLINES_URL,
            params={"symbol": "BTCUSDT", "interval": "1d", "limit": limit},
            timeout=20.0,
        )
        r.raise_for_status()
        klines = r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ échec récupération klines Binance : {exc}")
        return {}
    out: dict[str, float] = {}
    for k in klines:
        try:
            open_ms = int(k[0])
            close = float(k[4])
        except (TypeError, ValueError, IndexError):
            continue
        d = datetime.fromtimestamp(open_ms / 1000, tz=UTC).strftime("%Y-%m-%d")
        out[d] = close
    return out


def load_daily(redis: Redis) -> list[dict]:
    """Charge la série quotidienne ETF depuis Redis, triée par date croissante."""
    raw = redis.get(ETF_HISTORY_KEY)
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    daily = obj.get("daily") if isinstance(obj, dict) else None
    if not isinstance(daily, list):
        return []
    rows = [r for r in daily if isinstance(r, dict) and isinstance(r.get("date"), str)]
    rows.sort(key=lambda r: r["date"])
    return rows


def aligned_flow_returns(
    daily: list[dict], closes: dict[str, float], lag: int, horizon: int
) -> tuple[list[float], list[float]]:
    """Paires (flux net[d], rendement forward) anti-lookahead. Voir docstring module."""
    flows: list[float] = []
    rets: list[float] = []
    for row in daily:
        f = row.get("net_inflow_usd")
        if not isinstance(f, int | float):
            continue
        d_entry = _shift(row["date"], lag)
        d_exit = _shift(row["date"], lag + horizon)
        if d_entry is None or d_exit is None:
            continue
        p0 = closes.get(d_entry)
        p1 = closes.get(d_exit)
        if p0 and p1 and p0 != 0:
            flows.append(float(f))
            rets.append((p1 - p0) / p0)
    return flows, rets


def _stats(vals: list[float]) -> dict[str, float | int | None]:
    """Min/médiane/moyenne/max + N et % positifs (liste déjà filtrée des None)."""
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


def _fmt(v: float | int | None, nd: int = 3) -> str:
    return "n/a" if v is None else f"{round(v, nd)}"


def _fmt_musd(v: float | int | None) -> str:
    """Formate un montant USD en millions, lisible."""
    return "n/a" if v is None else f"{v / 1e6:,.1f} M$"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mesure SHADOW flux ETF spot BTC (lecture seule, n'enrôle rien)."
    )
    parser.add_argument("--horizon-days", type=int, default=5, help="Horizon forward (jours).")
    parser.add_argument("--lag-days", type=int, default=1, help="Décalage anti-lookahead (jours).")
    parser.add_argument("--min-days", type=int, default=30, help="Plancher non-fragile (jours).")
    args = parser.parse_args()

    print("=" * 76)
    print("  MESURE SHADOW — Flux ETF spot BTC (inflow/outflow net quotidien)")
    print(f"  {now_utc().isoformat()}")
    print("=" * 76)

    r = Redis.from_url(get_settings().redis_url, decode_responses=True)
    daily = load_daily(r)
    print(f"\nJours ETF en historique shadow : {len(daily)}")
    if not daily:
        print("  Aucune donnée. (shadow tout juste démarré ? vérifier l'ingester)")
        return 0
    print(f"Fenêtre : {daily[0]['date']} → {daily[-1]['date']}")

    print("\n--- Distribution du flux net quotidien (USD) ---")
    flow_vals = [r_["net_inflow_usd"] for r_ in daily if isinstance(r_.get("net_inflow_usd"), int | float)]
    st = _stats([float(v) for v in flow_vals])
    print(
        f"  N={st['n']}  min={_fmt_musd(st['min'])}  méd={_fmt_musd(st['median'])}  "
        f"moy={_fmt_musd(st['mean'])}  max={_fmt_musd(st['max'])}  "
        f"%jours_inflow={_fmt(st['pct_pos'], 0)}"
    )

    print("\n--- IC prédictif (flux net → rendement BTC forward) ---")
    closes = fetch_btc_daily_closes()
    if not closes:
        print("  ⚠ Pas de clôtures BTC (échec Binance) → IC non calculable cette fois.")
        print("\n--- VERDICT ---")
        print("  ⚠ Mesure incomplète (prix indisponible). Re-lancer plus tard.")
        return 0
    print(f"  (clôtures BTC Binance disponibles : {len(closes)} jours)")

    horizon = args.horizon_days
    lag = args.lag_days
    flows, rets = aligned_flow_returns(daily, closes, lag, horizon)
    ic = spearman_correlation(flows, rets) if len(flows) >= 5 else None

    # Sous-échantillon non chevauchant : un point tous les `horizon` jours.
    nx: list[float] = []
    ny: list[float] = []
    last = -(10**9)
    for i, (x, y) in enumerate(zip(flows, rets, strict=True)):
        if i - last >= horizon:
            nx.append(x)
            ny.append(y)
            last = i
    ic_indep = spearman_correlation(nx, ny) if len(nx) >= 5 else None

    print(
        f"  IC(flux net → rendement {horizon}j, lag {lag}j) = {_fmt(ic)} "
        f"(N chevauchant={len(flows)}) | non chevauchant = {_fmt(ic_indep)} (N={len(nx)})"
    )

    print("\n--- VERDICT ---")
    if len(flows) < args.min_days:
        print(f"  ⚠ N={len(flows)} < {args.min_days} → PRÉLIMINAIRE (échantillon trop faible).")
    print("  ⚠ IC backfill = in-sample + régime-dépendant ; à confirmer hors échantillon.")
    print("  ⚠ Les inflows peuvent SUIVRE le prix (colinéaire au trend) → IC ≠ edge.")
    print("  ⚠ IC sur rendements chevauchants gonfle la significativité → se fier au N")
    print("    non chevauchant. NO-GO directionnel inchangé : aucun enrôlement sans")
    print("    mesure complète (IC stable + indépendance + gain apparié vs Always SHORT).")
    print("  → Re-lancer après ≥ 2 semaines d'accumulation shadow propre.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
