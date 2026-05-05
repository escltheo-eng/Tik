"""Calcul du track record d'un signal individuel sur 4 horizons.

Pour un signal donné, calcule le delta de prix observé à :
  - 1h  après émission (threshold 0.3%)
  - 6h  après émission (threshold 0.3%)
  - 24h après émission (threshold 0.5%)
  - 5j  après émission (threshold 0.5%)

Module pure logic (pas de DB, pas de HTTP, pas de Redis), testable unitairement.
Réutilise find_closest_price et _success_for de backtest.py.

Phase A.3 du plan trading manuel J+10 (cf. docs/backlog.md entry n°3).
"""

from datetime import datetime, timedelta

from tik_core.scripts.backtest import _success_for, find_closest_price

# Les 4 horizons affichés dans le track record, avec leur threshold de succès.
# 1h/6h alignés sur flash (0.3%), 24h/5j alignés sur swing (0.5%).
TRACK_RECORD_HORIZONS = [
    {"label": "1h",  "hours": 1.0,   "threshold_pct": 0.3},
    {"label": "6h",  "hours": 6.0,   "threshold_pct": 0.3},
    {"label": "24h", "hours": 24.0,  "threshold_pct": 0.5},
    {"label": "5j",  "hours": 120.0, "threshold_pct": 0.5},
]


def _badge_for(
    *,
    available: bool,
    p0: float | None,
    p1: float | None,
    success: bool | None,
) -> str:
    """Retourne le badge résumant le résultat d'un horizon donné.

    Priorité : en_attente > données_manquantes > correct | raté.
    """
    if not available:
        return "en_attente"
    if p0 is None or p1 is None:
        return "données_manquantes"
    if success is True:
        return "correct"
    return "raté"


def compute_track_record(
    *,
    signal_timestamp: datetime,
    signal_direction: str,
    entity_id: str,
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
    now: datetime,
) -> list[dict]:
    """Calcule les 4 lignes du track record pour un signal donné.

    Retourne une liste de 4 dicts, un par horizon (dans l'ordre 1h→5j) :
      label            : "1h" | "6h" | "24h" | "5j"
      measure_hours    : durée en heures
      threshold_pct    : seuil de succès en %
      available        : True si l'horizon est dans le passé
      target_iso       : timestamp ISO UTC de la cible (stable pour le cache)
      p0               : prix au moment du signal (None si historique insuffisant)
      p1               : prix à t0 + horizon (None si non disponible ou futur)
      delta_pct        : variation (p1-p0)/p0×100 (None si p0/p1 manquants)
      success          : direction correcte (None si données manquantes)
      badge            : "correct"|"raté"|"données_manquantes"|"en_attente"
    """
    if entity_id == "BTC":
        history = btc_history
    elif entity_id == "GOLD":
        history = gold_history
    else:
        history = []

    # Normalise les timestamps en naïf UTC pour les calculs (cohérent avec
    # find_closest_price qui attend un datetime naïf ou compare en ms).
    ts0 = signal_timestamp.replace(tzinfo=None) if signal_timestamp.tzinfo is not None else signal_timestamp
    now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now

    p0 = find_closest_price(history, ts0) if history else None

    rows: list[dict] = []
    for h in TRACK_RECORD_HORIZONS:
        target_dt = ts0 + timedelta(hours=h["hours"])
        available = now_naive >= target_dt

        p1 = find_closest_price(history, target_dt) if (available and p0 is not None and history) else None

        if p0 is not None and p1 is not None and p0 != 0:
            delta_pct = (p1 - p0) / p0 * 100
            success: bool | None = _success_for(signal_direction, delta_pct, h["threshold_pct"])
        else:
            delta_pct = None
            success = None

        rows.append({
            "label": h["label"],
            "measure_hours": h["hours"],
            "threshold_pct": h["threshold_pct"],
            "available": available,
            "target_iso": target_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "p0": p0,
            "p1": p1,
            "delta_pct": delta_pct,
            "success": success,
            "badge": _badge_for(available=available, p0=p0, p1=p1, success=success),
        })

    return rows
