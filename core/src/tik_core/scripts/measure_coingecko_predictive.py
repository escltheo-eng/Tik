"""Mesure SHADOW : pouvoir PRÉDICTIF de CoinGecko sur le prix BTC — lecture seule.

Suite logique de `measure_coingecko_divergence.py`. Ce dernier répond à « CoinGecko
est-il INDÉPENDANT de Fear & Greed ? » (verdict 2026-06-11 : apport partiel). Mais
divergence ≠ valeur prédictive. AVANT d'enrôler CoinGecko comme overlay directionnel
(flip `TIK_COINGECKO_OVERLAY_ENABLED`), il faut savoir s'il **précède** les mouvements
BTC — et dans quel SENS (le mapping actuel `_compute_coingecko_bias` est contrarian
PROVISOIRE ; cette mesure dit s'il faut le garder contrarian ou le passer trend-following).

Méthode
-------
- CoinGecko : `up_pct ∈ [0,100]` agrégé en moyenne quotidienne (historique shadow Redis
  `tik.coingecko.btc.history`, depuis 2026-05-27).
- Prix BTC : closes quotidiens Binance (`/api/v3/klines` interval=1d, public, sans clé).
- Rendement forward à horizon h jours : ret(d) = close(d+h)/close(d) - 1.
- IC = Spearman(up_pct(d), ret(d)) sur les jours appariés.
  * IC POSITIF  → foule haussière précède hausse BTC → **trend-following** (le mapping
    contrarian actuel serait À L'ENVERS).
  * IC NÉGATIF  → foule haussière précède baisse BTC → **contrarian** confirmé.
  * IC ≈ 0      → pas de pouvoir prédictif (statu quo : ne pas enrôler).

⚠ LIMITES MAJEURES (engagement 13bis #8 + mémoire measurement-overlapping-returns)
----------------------------------------------------------------------------------
1. **N minuscule** : ~16 jours de shadow → IC sur ~15 points. L'intervalle de confiance
   à 95 % sur une corrélation N=15 est ÉNORME (≈ ±0.5). Tout verdict est PRÉLIMINAIRE
   et NON CONCLUANT — re-lancer avec ≥ 30-40 jours (≈ mi-juillet 2026).
2. **Chevauchement** : à horizon h ≥ 2 jours, les fenêtres se chevauchent → p-value
   gonflée. Seul l'horizon **1 jour** donne des rendements NON chevauchants (intervalles
   de prix disjoints) → c'est la lecture la moins biaisée. Les h ≥ 2 sont indicatifs.
3. Pouvoir prédictif mesuré ≠ edge tradable. Le go/no-go directionnel reste NO-GO ;
   cette mesure prépare une décision d'enrôlement SHADOW, elle ne lève aucun garde-fou.

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_coingecko_predictive
    docker exec tik-core python -m tik_core.scripts.measure_coingecko_predictive --horizons 1,2,3,5
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime

import httpx
from redis import Redis

from tik_core.config import get_settings
from tik_core.scripts.backtest_numeric_sources import spearman_correlation
from tik_core.scripts.measure_coingecko_divergence import daily_coingecko
from tik_core.utils.time import now_utc

CG_HISTORY_KEY = "tik.coingecko.btc.history"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
NON_FRAGILE_MIN_DAYS = 30


def btc_daily_closes(limit: int = 40) -> dict[date, float]:
    """{jour UTC : close BTC} depuis les klines quotidiens Binance. {} si échec."""
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                BINANCE_KLINES_URL,
                params={"symbol": "BTCUSDT", "interval": "1d", "limit": limit},
            )
            r.raise_for_status()
            rows = r.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  ⚠ fetch Binance échoué: {exc}", file=sys.stderr)
        return {}
    out: dict[date, float] = {}
    for k in rows:
        try:
            d = datetime.fromtimestamp(int(k[0]) / 1000, tz=UTC).date()
            out[d] = float(k[4])  # close
        except (TypeError, ValueError, IndexError):
            continue
    return out


def forward_pairs(
    cg_daily: dict[date, float], closes: dict[date, float], horizon_days: int
) -> list[tuple[float, float]]:
    """Paires (up_pct(d), rendement forward h jours) pour les jours exploitables."""
    pairs: list[tuple[float, float]] = []
    for d in sorted(cg_daily):
        d_fwd = date.fromordinal(d.toordinal() + horizon_days)
        if d in closes and d_fwd in closes and closes[d] > 0:
            ret = closes[d_fwd] / closes[d] - 1.0
            pairs.append((cg_daily[d], ret))
    return pairs


def interpret(ic: float | None) -> str:
    """Étiquette de sens depuis l'IC (foule haussière vs rendement forward)."""
    if ic is None:
        return "n/a (trop peu de points)"
    if abs(ic) < 0.15:
        return "≈ 0 → pas de pouvoir prédictif"
    if ic > 0:
        return "POSITIF → trend-following (mapping contrarian actuel = à l'envers)"
    return "NÉGATIF → contrarian confirmé (foule haussière précède baisse)"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mesure SHADOW pouvoir prédictif CoinGecko sur BTC (lecture seule)."
    )
    parser.add_argument("--horizons", default="1,2,3", help="Horizons en jours, ex: 1,2,3,5")
    args = parser.parse_args()
    horizons = [int(h) for h in args.horizons.split(",") if h.strip()]

    print("=" * 76)
    print("  MESURE SHADOW — pouvoir PRÉDICTIF CoinGecko (up%) sur le prix BTC")
    print(f"  {now_utc().isoformat()}")
    print("=" * 76)

    r = Redis.from_url(get_settings().redis_url, decode_responses=True)
    snapshots: list[dict] = []
    for s in r.lrange(CG_HISTORY_KEY, 0, -1):
        try:
            snapshots.append(json.loads(s))
        except (json.JSONDecodeError, TypeError):
            continue
    cg_daily = daily_coingecko(snapshots)
    print(f"\nJours CoinGecko shadow : {len(cg_daily)}")
    if not cg_daily:
        print("  Aucune donnée CoinGecko exploitable.")
        return 0

    closes = btc_daily_closes(limit=max(40, len(cg_daily) + max(horizons) + 5))
    print(f"Jours prix BTC (Binance daily) : {len(closes)}")

    print("\n--- IC = Spearman(up%, rendement BTC forward) par horizon ---")
    print("  (up% ↑ = foule haussière ; IC<0 = contrarian, IC>0 = trend-following)\n")
    headline_ic = None
    for h in horizons:
        pairs = forward_pairs(cg_daily, closes, h)
        up = [p[0] for p in pairs]
        ret = [p[1] for p in pairs]
        ic = spearman_correlation(up, ret)
        overlap = "" if h == 1 else "  [chevauchant — indicatif]"
        ic_str = "n/a" if ic is None else f"{ic:+.3f}"
        print(f"  h={h}j  N={len(pairs):2d}  IC={ic_str:>7}  → {interpret(ic)}{overlap}")
        if h == 1:
            headline_ic = ic

    print("\n--- VERDICT (préliminaire) ---")
    n1 = len(forward_pairs(cg_daily, closes, 1))
    print(f"  Lecture de référence (h=1j, non chevauchant) : IC = "
          f"{'n/a' if headline_ic is None else f'{headline_ic:+.3f}'}  sur N={n1}")
    if n1 < NON_FRAGILE_MIN_DAYS:
        print(f"  ⚠ N={n1} < {NON_FRAGILE_MIN_DAYS} → NON CONCLUANT (IC à ±0.5 près). "
              "Re-lancer avec ≥ 30-40 jours (~mi-juillet).")
    print("  ⚠ Pouvoir prédictif ≠ edge tradable. NO-GO directionnel inchangé.")
    print("  → Décision d'enrôlement (toggle + sens du mapping) SEULEMENT sur un IC")
    print("    stable et non trivial mesuré sur ≥ 30-40 jours.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
