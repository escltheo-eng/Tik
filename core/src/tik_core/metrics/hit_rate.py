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
