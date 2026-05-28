"""Mesure SHADOW : CoinGecko vote communautaire vs Fear & Greed — lecture seule.

Question ouverte ADR-021 (D4)
-----------------------------
CoinGecko collecte en SHADOW (depuis 2026-05-27) le `sentiment_votes_up_percentage`
de BTC (vote communautaire « bon/mauvais » sur la page CoinGecko). Fear & Greed
(alternative.me) est déjà un overlay sentiment BTC. **Les deux mesurent un
sentiment de foule sur une échelle 0-100.** Avant d'enrôler CoinGecko comme 4e
overlay (suite au ban Reddit Bug 11), il faut savoir s'il apporte une information
INDÉPENDANTE ou s'il est **redondant** avec Fear & Greed. Empiler une source
redondante ne crée pas d'edge (cf. ADR-018 : plus de sources ≠ plus d'edge) et
n'aiderait pas à restaurer la veracity capée.

Ce script LIT l'historique shadow CoinGecko (`tik.coingecko.btc.history`) + va
chercher l'historique Fear & Greed (API publique alternative.me, quotidien),
les apparie par jour, et mesure leur corrélation / divergence. Il n'écrit RIEN,
ne touche ni au pipeline ni à la base. Conforme règle SHADOW vs ENRÔLEMENT
(`docs/backlog-osint.md`) : mesurer ≠ enrôler.

Méthode
-------
- CoinGecko : `up_pct ∈ [0,100]` (↑ = communauté haussière). Horaire → on agrège
  en moyenne quotidienne (FG est quotidien).
- Fear & Greed : `value ∈ [0,100]` (↑ = greed = sentiment haussier). Même sens
  d'échelle que up_pct → on peut comparer les niveaux directement.
- Appariement par jour, puis : Spearman(up_pct_jour, fg_jour), divergence absolue
  moyenne normalisée, et accord directionnel (les deux du même côté de 50 ?).

Lecture du verdict (seuils pifomètre raisonné, à affiner)
---------------------------------------------------------
- |Spearman| ≥ 0.70 → forte corrélation → CoinGecko ≈ FG → **probablement
  redondant** (n'enrôler que s'il apporte un gain prédictif PROPRE démontré).
- 0.40 ≤ |Spearman| < 0.70 → corrélation modérée → apport partiel.
- |Spearman| < 0.40 → faible corrélation → **probablement complémentaire**
  (candidat sérieux au 4e overlay, à confirmer par sa valeur prédictive propre).

Limites (engagement 13bis #8)
-----------------------------
1. **N minuscule au démarrage** : CoinGecko shadow depuis le 27/05 → quelques
   jours seulement. Tout verdict est PRÉLIMINAIRE. Re-lancer après ≥ 2 semaines.
2. Divergence ≠ valeur prédictive. Si NON redondant, il restera à mesurer si
   CoinGecko PRÉDIT le prix BTC (instrument séparé, comme measure_polymarket) —
   et le go/no-go directionnel reste NO-GO (pas d'enrôlement directionnel).
3. FG est un indice composite (volatilité, momentum, social…), CoinGecko un vote
   binaire : une divergence est plausible et attendue ; ce script la quantifie.

Usage
-----
    docker exec tik-core python -m tik_core.scripts.measure_coingecko_divergence
    docker exec tik-core python -m tik_core.scripts.measure_coingecko_divergence --min-days 14
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
from tik_core.utils.time import now_utc

CG_HISTORY_KEY = "tik.coingecko.btc.history"
FNG_URL = "https://api.alternative.me/fng/"

REDUNDANT_THRESHOLD = 0.70
COMPLEMENTARY_THRESHOLD = 0.40


def parse_iso(s: str | None) -> datetime | None:
    """ISO-8601 tolérant (Z ou offset). Aware ou None."""
    if not s or not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def daily_coingecko(snapshots: list[dict]) -> dict[date, float]:
    """Moyenne quotidienne de up_pct depuis les snapshots shadow CoinGecko.

    Ignore les entrées sans up_pct numérique valide ou sans fetched_at parseable.
    """
    acc: dict[date, list[float]] = {}
    for snap in snapshots:
        up = snap.get("up_pct")
        dt = parse_iso(snap.get("fetched_at"))
        if dt is None or not isinstance(up, int | float):
            continue
        if not (0.0 <= float(up) <= 100.0):
            continue
        acc.setdefault(dt.date(), []).append(float(up))
    return {d: sum(v) / len(v) for d, v in acc.items()}


def fg_by_day(fng_data: list[dict]) -> dict[date, float]:
    """{jour : valeur FG} depuis le payload alternative.me (timestamp unix, value str)."""
    out: dict[date, float] = {}
    for e in fng_data:
        ts = e.get("timestamp")
        val = e.get("value")
        try:
            d = datetime.fromtimestamp(int(ts), tz=UTC).date()
            v = float(val)
        except (TypeError, ValueError):
            continue
        if 0.0 <= v <= 100.0:
            out[d] = v
    return out


def pair_by_day(
    cg_daily: dict[date, float], fg_daily: dict[date, float]
) -> list[tuple[float, float]]:
    """Paires (up_pct, fg_value) pour les jours présents dans LES DEUX séries."""
    return [(cg_daily[d], fg_daily[d]) for d in sorted(cg_daily) if d in fg_daily]


def directional_agreement(pairs: list[tuple[float, float]], midpoint: float = 50.0) -> float | None:
    """% de jours où up_pct et fg sont du même côté du midpoint (les deux ↑ ou ↓).

    Les jours où l'une des deux valeurs est exactement au midpoint sont exclus.
    Retourne None si aucun jour exploitable.
    """
    usable = [(a, b) for a, b in pairs if a != midpoint and b != midpoint]
    if not usable:
        return None
    agree = sum(1 for a, b in usable if (a > midpoint) == (b > midpoint))
    return agree / len(usable) * 100.0


def divergence_stats(pairs: list[tuple[float, float]]) -> dict[str, float | None]:
    """Spearman, divergence absolue moyenne normalisée [0,1], accord directionnel."""
    if not pairs:
        return {"spearman": None, "mean_abs_norm_diff": None, "directional_agreement_pct": None}
    cg = [p[0] for p in pairs]
    fg = [p[1] for p in pairs]
    ic = spearman_correlation(cg, fg)
    mad = sum(abs(a - b) for a, b in pairs) / len(pairs) / 100.0
    return {
        "spearman": ic,
        "mean_abs_norm_diff": mad,
        "directional_agreement_pct": directional_agreement(pairs),
    }


def verdict_label(spearman: float | None) -> str:
    """Étiquette redondant / partiel / complémentaire depuis |Spearman|."""
    if spearman is None:
        return "indéterminé (pas de corrélation calculable)"
    a = abs(spearman)
    if a >= REDUNDANT_THRESHOLD:
        return "probablement REDONDANT avec Fear & Greed"
    if a >= COMPLEMENTARY_THRESHOLD:
        return "apport PARTIEL (corrélation modérée)"
    return "probablement COMPLÉMENTAIRE (faible corrélation)"


# --- IO (réseau / Redis) — non testé unitairement ----------------------------


def fetch_fng_history(limit: int = 60) -> list[dict]:
    """Historique Fear & Greed (alternative.me). Best-effort : [] si échec."""
    try:
        with httpx.Client(timeout=20.0) as client:
            r = client.get(FNG_URL, params={"limit": limit, "format": "json"})
            r.raise_for_status()
            return r.json().get("data", [])
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        print(f"  ⚠ fetch Fear & Greed échoué: {exc}", file=sys.stderr)
        return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mesure SHADOW divergence CoinGecko vs Fear & Greed (lecture seule)."
    )
    parser.add_argument("--min-days", type=int, default=14, help="N jours min pour non-fragile.")
    args = parser.parse_args()

    print("=" * 76)
    print("  MESURE SHADOW — CoinGecko (vote communautaire) vs Fear & Greed")
    print(f"  {now_utc().isoformat()}")
    print("=" * 76)

    r = Redis.from_url(get_settings().redis_url, decode_responses=True)
    raw = r.lrange(CG_HISTORY_KEY, 0, -1)
    snapshots: list[dict] = []
    for s in raw:
        try:
            snapshots.append(json.loads(s))
        except (json.JSONDecodeError, TypeError):
            continue

    cg_daily = daily_coingecko(snapshots)
    print(f"\nSnapshots CoinGecko shadow : {len(snapshots)}  → {len(cg_daily)} jour(s) distinct(s)")
    if not cg_daily:
        print("  Aucune donnée CoinGecko exploitable. (shadow démarré le 27/05)")
        return 0

    fng = fetch_fng_history(limit=max(30, len(cg_daily) + 10))
    fg_daily = fg_by_day(fng)
    print(f"Jours Fear & Greed récupérés : {len(fg_daily)}")

    pairs = pair_by_day(cg_daily, fg_daily)
    print(f"Jours appariés (présents dans les deux) : {len(pairs)}")

    if pairs:
        print("\n--- Détail par jour (CoinGecko up% | Fear&Greed) ---")
        for d in sorted(cg_daily):
            if d in fg_daily:
                print(f"  {d.isoformat()} : up%={cg_daily[d]:5.1f}  FG={fg_daily[d]:5.1f}")

    stats = divergence_stats(pairs)
    print("\n--- Divergence (PRÉLIMINAIRE) ---")
    sp = stats["spearman"]
    print(f"  Spearman(up%, FG)            : {'n/a' if sp is None else round(sp, 3)}")
    mad = stats["mean_abs_norm_diff"]
    print(f"  divergence abs. moy. (0-1)   : {'n/a' if mad is None else round(mad, 3)}")
    ag = stats["directional_agreement_pct"]
    print(f"  accord directionnel (vs 50)  : {'n/a' if ag is None else f'{ag:.0f}%'}")

    print("\n--- VERDICT ---")
    print(f"  → {verdict_label(sp)}")
    if len(pairs) < args.min_days:
        print(
            f"  ⚠ N={len(pairs)} jours < {args.min_days} → NON CONCLUANT (échantillon trop faible)."
        )
    print("  ⚠ Divergence ≠ valeur prédictive (si non redondant : mesurer le pouvoir")
    print("    prédictif propre ensuite). NO-GO directionnel inchangé → aucun enrôlement.")
    print("  → Re-lancer après ≥ 2 semaines d'accumulation shadow CoinGecko.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
