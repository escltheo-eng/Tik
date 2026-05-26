"""Mesure SHADOW de la valeur prédictive de Polymarket (BTC) — lecture seule.

Contexte
--------
L'ingester Polymarket tourne en SHADOW depuis le 2026-05-24 (cf.
`polymarket_ingester.py` + memory polymarket-shadow-live), il collecte sans
brancher quoi que ce soit sur le `combined_bias`. Ce script LIT cette donnée
(Redis `tik.polymarket.btc.history`) et tente de mesurer si les probas
implicites « money on the line » de Polymarket ont une valeur prédictive sur
le prix BTC à venir (IC Spearman / hit de signe / gain).

Il n'écrit RIEN, ne touche ni au pipeline ni à la base `signals`. Conforme
règle SHADOW vs ENRÔLEMENT (`docs/backlog-osint.md`) : mesurer ≠ enrôler.

Comment on dérive un signal directionnel
-----------------------------------------
On utilise UNIQUEMENT la famille « Bitcoin above ___ on <date>? » (échelle de
niveau quotidienne) :
  - pour un event donné, les marchés forment une courbe P(BTC > seuil)
    décroissante en seuil ;
  - on interpole le seuil où P = 0,5 → c'est le **prix médian implicite** du
    marché pour cette date ;
  - signal = prix_median_implicite / spot_au_fetch − 1  (>0 = marché haussier
    vs spot, <0 = baissier).
On EXCLUT volontairement :
  - « What price will Bitcoin hit/reach/dip $X <mois> » → sémantique de *touch*
    (≠ niveau) ET corrompue par un bug de parsing de seuil (cf. ci-dessous) ;
  - « Bitcoin price on <date> » (fourchettes) ;
  - les events dont `end_date` est déjà passé au moment du fetch (résolus).

⚠ Bug ingester détecté 2026-05-27 (À FIXER avant tout enrôlement)
-----------------------------------------------------------------
`_parse_threshold_usd` dans `polymarket_ingester.py` interprète le « M » de
« May »/« March » comme suffixe « million » : « reach $84,000 May 25-31 » →
threshold_usd = 84 000 000 000. Ça corrompt les familles « reach/hit/dip $X
<mois> ». La famille « above ___ on <date> » utilisée ici est ÉPARGNÉE (le
seuil est suivi de « on »). Ce script compte et signale ces seuils aberrants,
mais NE corrige PAS l'ingester (décision + correctif = session dédiée).

Limites majeures (à garder en tête)
------------------------------------
1. **N minuscule** : ~1 snapshot/h depuis le 24/05 → quelques dizaines de
   points seulement. Tout IC est PRÉLIMINAIRE, non concluant. Re-lancer après
   ~2 semaines d'accumulation.
2. **Pairs non indépendantes** : des snapshots horaires consécutifs pointent
   souvent le même event → forte autocorrélation (le N effectif est encore
   plus petit que le N affiché).
3. **Horizon intraday** : les marchés « above on <date> » résolvent souvent
   le jour même/lendemain → prix médian ≈ spot → signal faible par nature.
   Le signal directionnel riche viendrait des marchés mensuels, mais ils sont
   buggés (cf. ci-dessus) et de sémantique « touch ».

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_polymarket
    docker exec tik-core python -m tik_core.scripts.measure_polymarket --min-pairs 30
"""

from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_right
from datetime import datetime

import httpx
from redis import Redis

from tik_core.config import get_settings
from tik_core.scripts.backtest_numeric_sources import spearman_correlation
from tik_core.utils.time import now_utc

HISTORY_KEY = "tik.polymarket.btc.history"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# Bornes de sanité sur le seuil USD (BTC) : élimine le bug 84e9 et le bruit.
MIN_THRESHOLD = 1_000.0
MAX_THRESHOLD = 5_000_000.0
PRICE_TOL_MS = 10 * 60 * 1000  # 10 min de tolérance pour matcher un prix


def parse_iso(s: str | None) -> datetime | None:
    """Parse ISO-8601 tolérant (Z ou +00:00). Retourne aware UTC ou None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_above_on_date(title: str | None) -> bool:
    if not title:
        return False
    t = title.lower()
    return ("bitcoin" in t or "btc" in t) and "above" in t and " on " in t


def implied_median(markets: list[dict]) -> float | None:
    """Prix médian implicite = seuil où P(BTC > seuil) croise 0,5 (interp. linéaire).

    Retourne None si pas de croisement clair (médiane hors de l'échelle de seuils).
    """
    pts: list[tuple[float, float]] = []
    for m in markets:
        thr = m.get("threshold_usd")
        p = m.get("yes_prob")
        if not isinstance(thr, int | float) or not isinstance(p, int | float):
            continue
        if not (MIN_THRESHOLD <= thr <= MAX_THRESHOLD):
            continue
        if not (0.0 <= p <= 1.0):
            continue
        pts.append((float(thr), float(p)))
    if len(pts) < 2:
        return None
    pts.sort(key=lambda x: x[0])  # seuil croissant ; P(above) doit décroître
    # cherche l'intervalle où p passe de >=0.5 à <0.5
    for (x_lo, p_lo), (x_hi, p_hi) in zip(pts, pts[1:], strict=False):
        if p_lo >= 0.5 >= p_hi and p_lo != p_hi:
            return x_lo + (0.5 - p_lo) / (p_hi - p_lo) * (x_hi - x_lo)
    return None


def count_buggy_thresholds(snapshots: list[dict]) -> int:
    """Compte les seuils aberrants (> MAX_THRESHOLD) — démontre le bug ingester."""
    n = 0
    for snap in snapshots:
        for ev in snap.get("events", []):
            for m in ev.get("markets", []):
                thr = m.get("threshold_usd")
                if isinstance(thr, int | float) and thr > MAX_THRESHOLD:
                    n += 1
    return n


def fetch_binance_klines(interval: str = "5m", limit: int = 1000) -> list[tuple[int, float]]:
    """(open_time_ms, close) triés croissant. Best-effort : [] si échec."""
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(
                BINANCE_KLINES_URL,
                params={"symbol": "BTCUSDT", "interval": interval, "limit": limit},
            )
            r.raise_for_status()
            data = r.json()
        return [(int(k[0]), float(k[4])) for k in data]
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        print(f"  ⚠ fetch Binance échoué: {exc}", file=sys.stderr)
        return []


def price_at(klines: list[tuple[int, float]], times: list[int], ts_ms: int) -> float | None:
    """Close de la kline la plus proche de ts_ms (tolérance PRICE_TOL_MS)."""
    if not klines:
        return None
    i = bisect_right(times, ts_ms)
    best: float | None = None
    best_diff = PRICE_TOL_MS + 1
    for j in (i - 1, i):
        if 0 <= j < len(klines):
            diff = abs(klines[j][0] - ts_ms)
            if diff < best_diff:
                best_diff = diff
                best = klines[j][1]
    return best


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mesure SHADOW de la valeur prédictive de Polymarket BTC (lecture seule)."
    )
    parser.add_argument("--min-pairs", type=int, default=20, help="N min pour un IC non-fragile.")
    args = parser.parse_args()

    print("=" * 76)
    print("  MESURE SHADOW POLYMARKET BTC — valeur prédictive (lecture seule)")
    print(f"  {now_utc().isoformat()}")
    print("=" * 76)

    r = Redis.from_url(get_settings().redis_url, decode_responses=True)
    raw = r.lrange(HISTORY_KEY, 0, -1)
    snapshots: list[dict] = []
    for s in raw:
        try:
            snapshots.append(json.loads(s))
        except (json.JSONDecodeError, TypeError):
            continue
    # tri chronologique (lpush => index 0 = plus récent)
    snapshots.sort(key=lambda x: x.get("fetched_at") or "")

    print(f"\nSnapshots dans Redis : {len(snapshots)}")
    if snapshots:
        print(f"  fenêtre : {snapshots[0].get('fetched_at')}  →  {snapshots[-1].get('fetched_at')}")
    buggy = count_buggy_thresholds(snapshots)
    if buggy:
        print(
            f"  ⚠ {buggy} seuils aberrants (>{MAX_THRESHOLD:.0f}) = bug ingester 'M de May' "
            "→ familles 'reach/hit $X <mois>' inutilisables tant que non corrigé."
        )
    if not snapshots:
        print("\nAucune donnée shadow. Rien à mesurer.")
        return 0

    klines = fetch_binance_klines()
    times = [k[0] for k in klines]
    print(f"  klines BTC 5m récupérées : {len(klines)}")

    now = now_utc()
    pairs: list[tuple[float, float]] = []  # (signal, outcome_return) sur events mûrs
    n_signals = 0  # signaux dérivables (event futur + croisement)
    n_no_crossing = 0  # event futur mais médiane hors échelle
    events_seen: set[str] = set()

    for snap in snapshots:
        fetched = parse_iso(snap.get("fetched_at"))
        if fetched is None:
            continue
        # events 'above on date' avec end_date futur AU MOMENT DU FETCH
        cands = []
        for ev in snap.get("events", []):
            if not is_above_on_date(ev.get("title")):
                continue
            end = parse_iso(ev.get("end_date"))
            if end is None or end <= fetched:
                continue
            cands.append((end, ev))
        if not cands:
            continue
        cands.sort(key=lambda x: x[0])  # nearest future end_date
        end_date, ev = cands[0]

        med = implied_median(ev.get("markets", []))
        if med is None:
            n_no_crossing += 1
            continue
        spot = price_at(klines, times, int(fetched.timestamp() * 1000))
        if spot is None or spot <= 0:
            continue
        signal = med / spot - 1.0
        n_signals += 1
        events_seen.add(ev.get("slug") or ev.get("title") or "?")

        # outcome connu seulement si l'event a résolu (end_date passé)
        if end_date <= now:
            close = price_at(klines, times, int(end_date.timestamp() * 1000))
            if close is not None and close > 0:
                pairs.append((signal, close / spot - 1.0))

    print(f"\nSignaux dérivés ('above on date', event futur, croisement P=0.5) : {n_signals}")
    print(f"  events distincts couverts : {len(events_seen)}")
    print(f"  snapshots sans croisement (médiane hors échelle) : {n_no_crossing}")
    print(f"  paires (signal, rendement réalisé) mûres : {len(pairs)}")

    if not pairs:
        print("\n→ Aucune paire mûre encore (events pas résolus / prix hors fenêtre).")
        print("  VERDICT : données shadow insuffisantes. Re-lancer après ~2 semaines.")
        return 0

    sig = [p[0] for p in pairs]
    ret = [p[1] for p in pairs]
    ic = spearman_correlation(sig, ret)
    eps = 1e-4
    directional = [(s, rr) for s, rr in pairs if abs(s) > eps]
    if directional:
        hits = sum(1 for s, rr in directional if (s > 0) == (rr > 0))
        hit_rate = hits / len(directional)
        gain = sum((rr if s > 0 else -rr) for s, rr in directional) / len(directional)
    else:
        hit_rate = gain = float("nan")

    print("\n--- Premier read (PRÉLIMINAIRE) ---")
    print(f"  IC Spearman(signal, rendement)   : {ic if ic is None else round(ic, 3)}")
    print(f"  signal moyen                     : {sum(sig) / len(sig) * 100:+.3f}%")
    print(f"  rendement réalisé moyen          : {sum(ret) / len(ret) * 100:+.3f}%")
    print(
        f"  hit de signe (|signal|>{eps})     : "
        f"{hit_rate * 100:.1f}% sur {len(directional)} signaux directionnels"
    )
    print(f"  gain moyen en suivant le signe   : {gain * 100:+.3f}%")

    print("\n--- VERDICT ---")
    if len(pairs) < args.min_pairs:
        print(f"  ⚠ N={len(pairs)} < {args.min_pairs} → NON CONCLUANT (échantillon trop faible).")
    print("  ⚠ Pairs autocorrélées (snapshots horaires sur mêmes events) → N effectif < N.")
    print("  ⚠ Régime baissier unique + horizon intraday → signal faible par nature.")
    print("  → Re-lancer après ~2 semaines d'accumulation shadow. AUCUN enrôlement à ce stade.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
