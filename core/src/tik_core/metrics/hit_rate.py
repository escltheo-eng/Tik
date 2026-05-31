"""Calcul du hit rate live des signaux Tik.

Réutilise la logique de backtest.evaluate_signal pour mesurer la performance
des signaux émis par horizon et par entity sur une fenêtre temporelle donnée.

Module pure logic (pas de DB, pas de HTTP, pas de Redis), testable unitairement.
Le caller (api.metrics) orchestre :
  1. Fetch des signaux depuis la DB (filtrés par fenêtre temporelle)
  2. Fetch des historiques de prix Binance/Yahoo
  3. Appel de filter_signals_for_horizon + compute_hit_rate
  4. Cache Redis du résultat agrégé (TTL 15 min)

Conformément à ADR-002 (monorepo) et au plan trading manuel J+10
(docs/backlog.md entry n°3 Phase A.2 hit rate live).
"""

from datetime import datetime, timedelta
from statistics import mean
from typing import Literal

from tik_core.scripts.backtest import (
    _gain_for,
    _success_for,
    find_closest_price,
)
from tik_core.storage.models import Signal

HorizonName = Literal["flash", "swing", "macro"]

# Mapping horizon → durée canonique de mesure du delta prix (heures).
# Le sweet spot 5j swing est issu du backtest 2026-04-29 (cf. CLAUDE.md
# Paquet 1.x insights). Flash 1h aligné sur la fenêtre d'expiry du publisher.
# Macro 30j est provisoire — peu de signaux macro émis aujourd'hui.
HORIZON_MEASURE_HOURS: dict[str, float] = {
    "flash": 1.0,
    "swing": 24.0 * 5,
    "macro": 24.0 * 30,
}

# Threshold par défaut par horizon (% mouvement minimum pour considérer
# qu'un signal long/short a "réussi", ou |delta|<seuil pour neutral).
HORIZON_DEFAULT_THRESHOLD_PCT: dict[str, float] = {
    "flash": 0.3,
    "swing": 0.5,
    "macro": 1.5,
}


def filter_signals_for_horizon(
    signals: list[Signal],
    *,
    horizon: str,
    entity_id: str,
    since_days: int,
    now: datetime,
    include_flagged: bool,
) -> tuple[list[Signal], int]:
    """Filtre les signaux pertinents pour le calcul du hit rate.

    Critères :
    - signal.horizon == horizon
    - signal.entity_id == entity_id
    - signal.timestamp >= now - since_days (fenêtre récente)
    - signal.timestamp <= now - measure_hours (assez ancien pour être mesurable)
    - si include_flagged=False : exclut les signaux flagués degraded/tripped

    Retourne (signaux_eligibles, n_flagged_excluded).
    """
    if horizon not in HORIZON_MEASURE_HOURS:
        raise ValueError(f"Unknown horizon: {horizon}")
    measure_hours = HORIZON_MEASURE_HOURS[horizon]
    cutoff_recent = now - timedelta(days=since_days)
    cutoff_mature = now - timedelta(hours=measure_hours)

    eligible: list[Signal] = []
    n_flagged_excluded = 0

    for sig in signals:
        if sig.horizon != horizon:
            continue
        if sig.entity_id != entity_id:
            continue
        if sig.timestamp < cutoff_recent:
            continue
        if sig.timestamp > cutoff_mature:
            continue
        if not include_flagged and sig.circuit_breaker_status in ("degraded", "tripped"):
            n_flagged_excluded += 1
            continue
        eligible.append(sig)

    return eligible, n_flagged_excluded


def compute_hit_rate(
    signals: list[Signal],
    *,
    horizon: str,
    threshold_pct: float,
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
) -> dict:
    """Calcule le hit rate sur les signaux filtrés.

    Les signaux doivent déjà avoir été filtrés par filter_signals_for_horizon.

    Retourne un dict avec :
    - n_evaluated : signaux pour lesquels on a pu calculer un delta prix
    - n_skipped : signaux dont le prix n'était pas disponible dans l'historique
    - n_success : signaux corrects
    - hit_rate : n_success / n_evaluated (0.0 si n_evaluated == 0)
    - avg_gain_pct : gain moyen % sur les signaux évalués
    """
    if horizon not in HORIZON_MEASURE_HOURS:
        raise ValueError(f"Unknown horizon: {horizon}")
    measure_hours = HORIZON_MEASURE_HOURS[horizon]

    n_evaluated = 0
    n_skipped = 0
    n_success = 0
    gains: list[float] = []

    for sig in signals:
        if sig.entity_id == "BTC":
            history = btc_history
        elif sig.entity_id == "GOLD":
            history = gold_history
        else:
            n_skipped += 1
            continue

        ts0 = sig.timestamp
        ts1 = ts0 + timedelta(hours=measure_hours)
        p0 = find_closest_price(history, ts0)
        p1 = find_closest_price(history, ts1)

        if p0 is None or p1 is None or p0 == 0:
            n_skipped += 1
            continue

        delta_pct = (p1 - p0) / p0 * 100
        success = _success_for(sig.direction, delta_pct, threshold_pct)
        gain = _gain_for(sig.direction, delta_pct)

        n_evaluated += 1
        if success:
            n_success += 1
        gains.append(gain)

    hit_rate = (n_success / n_evaluated) if n_evaluated > 0 else 0.0
    avg_gain_pct = mean(gains) if gains else 0.0

    return {
        "n_evaluated": n_evaluated,
        "n_skipped": n_skipped,
        "n_success": n_success,
        "hit_rate": hit_rate,
        "avg_gain_pct": avg_gain_pct,
    }


# ----- Baseline constante "robot bête" (anti-surconfiance, ADR-018 / colinéarité) -----
#
# En marché fortement tendanciel, un hit rate élevé peut n'être QUE l'effet de la
# tendance : un pari constant ("toujours short" dans une baisse) fait aussi bien
# sans aucune intelligence. On compare donc Tik à la meilleure baseline constante
# sur les MÊMES signaux. Si Tik ne la bat pas franchement, son hit rate n'est pas
# un edge (il suit la pente). Cf. analyze_colinearity.py + go/no-go 2026-05-27.

# Tik doit battre la meilleure baseline constante d'au moins ce delta (5 pts) pour
# qu'on considère son hit rate comme un avantage réel (et que le dashboard masque
# l'avertissement). Volontairement conservateur.
BASELINE_EDGE_MARGIN = 0.05
# Sous ce nombre de signaux évalués, on ne tranche pas (échantillon trop faible).
BASELINE_MIN_SAMPLE = 30


def compute_constant_baselines(
    signals: list[Signal],
    *,
    horizon: str,
    threshold_pct: float,
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
) -> dict:
    """Hit rate des stratégies constantes (toujours long / short / neutral).

    Évalué sur le MÊME ensemble de signaux que `compute_hit_rate` (même boucle de
    delta prix, mêmes skips) pour une comparaison apples-to-apples. Sert à savoir
    si le hit rate de Tik est un edge ou un simple suivi de tendance.

    Retourne ``{"n_evaluated": int, "hit_rates": {"long": .., "short": .., "neutral": ..}}``.
    """
    if horizon not in HORIZON_MEASURE_HOURS:
        raise ValueError(f"Unknown horizon: {horizon}")
    measure_hours = HORIZON_MEASURE_HOURS[horizon]

    counts = {"long": 0, "short": 0, "neutral": 0}
    n_evaluated = 0

    for sig in signals:
        if sig.entity_id == "BTC":
            history = btc_history
        elif sig.entity_id == "GOLD":
            history = gold_history
        else:
            continue

        ts0 = sig.timestamp
        ts1 = ts0 + timedelta(hours=measure_hours)
        p0 = find_closest_price(history, ts0)
        p1 = find_closest_price(history, ts1)
        if p0 is None or p1 is None or p0 == 0:
            continue

        delta_pct = (p1 - p0) / p0 * 100
        n_evaluated += 1
        for direction in ("long", "short", "neutral"):
            if _success_for(direction, delta_pct, threshold_pct):
                counts[direction] += 1

    hit_rates = {d: (counts[d] / n_evaluated if n_evaluated > 0 else 0.0) for d in counts}
    return {"n_evaluated": n_evaluated, "hit_rates": hit_rates}


def assess_baseline_edge(
    tik_hit_rate: float,
    tik_n_evaluated: int,
    baseline_hit_rates: dict,
) -> dict:
    """Meilleure baseline constante + Tik la bat-il franchement ?

    ``beats=True`` (edge crédible) requiert : assez de signaux (≥ BASELINE_MIN_SAMPLE)
    ET Tik au-dessus de la meilleure baseline d'au moins BASELINE_EDGE_MARGIN.
    Quand ``beats`` devient True, le dashboard masque l'avertissement
    « ce taux suit la tendance » → l'avertissement disparaît automatiquement
    dès que Tik a un avantage démontré (auto-suppression demandée).

    Retourne ``{"best_label": str|None, "best_hit_rate": float|None, "beats": bool}``.
    """
    if not baseline_hit_rates:
        return {"best_label": None, "best_hit_rate": None, "beats": False}
    best_label = max(baseline_hit_rates, key=lambda d: baseline_hit_rates[d])
    best_hit_rate = baseline_hit_rates[best_label]
    beats = (
        tik_n_evaluated >= BASELINE_MIN_SAMPLE
        and tik_hit_rate >= best_hit_rate + BASELINE_EDGE_MARGIN
    )
    return {"best_label": best_label, "best_hit_rate": best_hit_rate, "beats": beats}


def make_cache_key(
    *,
    entity_id: str,
    horizon: str,
    since_days: int,
    threshold_pct: float,
    include_flagged: bool,
) -> str:
    """Clé Redis pour le cache du résultat hit rate (TTL 15 min côté caller)."""
    flagged_part = "all" if include_flagged else "clean"
    return (
        f"tik.metrics.hit_rate.{entity_id}.{horizon}.{since_days}."
        f"{threshold_pct:.2f}.{flagged_part}"
    )


# ----- Hit rate par tranche de veracity (Phase A.2-bis) -----

# Buckets cohérents avec les paliers natifs Tik (cf. comprendre_tik.md
# section 6 et les insights backtest 2026-05-05).
VERACITY_BUCKETS: list[tuple[float, float, str]] = [
    (0.70, 0.80, "0.70-0.79"),
    (0.80, 0.90, "0.80-0.89"),
    (0.90, 0.95, "0.90-0.94"),
    (0.95, 1.01, "0.95-1.00"),  # 1.01 pour inclure 1.00 strictement (< vmax)
]


def compute_hit_rate_by_veracity(
    signals: list[Signal],
    *,
    horizon: str,
    threshold_pct: float,
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
) -> list[dict]:
    """Calcule le hit rate segmenté par tranche de veracity.

    Retourne une liste de dicts (1 par bucket VERACITY_BUCKETS), même si
    un bucket est vide (n_evaluated=0). Permet à l'UI d'afficher tous les
    paliers même les non-peuplés (transparence — pattern OSINT pro).

    Réutilise compute_hit_rate sur chaque sous-ensemble. Pas d'optim
    prématurée — la complexité est O(n_signals × n_buckets) = 4n acceptable.
    """
    if horizon not in HORIZON_MEASURE_HOURS:
        raise ValueError(f"Unknown horizon: {horizon}")

    results: list[dict] = []
    for vmin, vmax, label in VERACITY_BUCKETS:
        bucket_signals = [
            s for s in signals if s.veracity is not None and vmin <= float(s.veracity) < vmax
        ]
        stats = compute_hit_rate(
            bucket_signals,
            horizon=horizon,
            threshold_pct=threshold_pct,
            btc_history=btc_history,
            gold_history=gold_history,
        )
        results.append(
            {
                "bucket_label": label,
                "veracity_min": vmin,
                "veracity_max": vmax,
                "n_evaluated": stats["n_evaluated"],
                "n_skipped": stats["n_skipped"],
                "n_success": stats["n_success"],
                "hit_rate": stats["hit_rate"],
                "avg_gain_pct": stats["avg_gain_pct"],
            }
        )
    return results


def make_cache_key_by_veracity(
    *,
    entity_id: str,
    horizon: str,
    since_days: int,
    threshold_pct: float,
    include_flagged: bool,
) -> str:
    """Clé Redis pour le cache du résultat hit rate par veracity."""
    flagged_part = "all" if include_flagged else "clean"
    return (
        f"tik.metrics.hit_rate_by_veracity.{entity_id}.{horizon}.{since_days}."
        f"{threshold_pct:.2f}.{flagged_part}"
    )
