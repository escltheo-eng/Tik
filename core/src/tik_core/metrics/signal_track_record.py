"""Calcul du track record d'un signal individuel sur 4 horizons adaptés.

La granularité des horizons mesurés s'adapte à l'horizon contractuel du
signal (Paquet 17 — P5 du plan stratégique post-audit fiabilité signaux) :

  flash → 15min / 30min / 45min / 1h   (dans la fenêtre TTL signal Tik)
  swing → 1h / 6h / 24h / 5j           (calibration historique Paquet 12)
  macro → 1j / 7j / 30j / 90j          (mesure du cycle long)

Ce dispatch évite à un signal flash de perdre 75 % de son track record sur
des horizons hors-fenêtre contractuelle (24h/5j inutiles pour flash) et
améliore la précision de calibration source-credibility (P4 du plan).

Choix flash 1h max (et non 4h comme la fenêtre d'analyse klines 1m × 240) :
le horizon flash dans le pipeline Tik est défini par EXPIRY_BY_HORIZON[
"flash"] = 1h (TTL signal) ET HORIZON_MEASURE_HOURS["flash"] = 1.0 (hit
rate Phase A.2 Paquet 10). Mesurer le track record dans cette fenêtre
maintient la cohérence inter-cartes du dashboard. Le scalping 5min n'est
pas couvert (klines 15m natives insuffisamment fines, bruit microstructure
sous le seuil — un futur ADR "flash micro-scalping" devrait fetch klines
1m si on veut y aller).

Les seuils directionnalité sont calibrés au pifomètre raisonné — plus
l'horizon est court, plus la volatilité absolue typique est faible →
seuil plus bas pour distinguer mouvement réel vs bruit. Révision
empirique post-J+30 inscrite au backlog.

Module pure logic (pas de DB, pas de HTTP, pas de Redis), testable
unitairement. Réutilise find_closest_price et _success_for de backtest.py.

Phase A.3 du plan trading manuel J+10 (cf. docs/backlog.md entry n°3),
refactorée par P5 du plan stratégique fiabilité signaux (2026-05-06).
"""

from datetime import datetime, timedelta

from tik_core.scripts.backtest import _success_for, find_closest_price

# Specs par horizon contractuel du signal. Chaque entrée porte :
#   rows  : 4 horizons mesurés (label/hours/threshold_pct)
#   price_match_tolerance_ms : tolérance max entre la cible et le kline
#                              le plus proche, calibrée sur la granularité
#                              des klines fetchées par l'endpoint :
#                                flash → klines 15m → 30 min de tolérance
#                                swing → klines 1h  → 6 h (historique)
#                                macro → klines 1d  → 24 h (cycle long)
HORIZON_SPECS_BY_SIGNAL_HORIZON: dict[str, dict] = {
    "flash": {
        "rows": [
            {"label": "15min", "hours": 0.25, "threshold_pct": 0.10},
            {"label": "30min", "hours": 0.50, "threshold_pct": 0.15},
            {"label": "45min", "hours": 0.75, "threshold_pct": 0.20},
            {"label": "1h",    "hours": 1.00, "threshold_pct": 0.30},
        ],
        "price_match_tolerance_ms": 30 * 60 * 1000,
    },
    "swing": {
        "rows": [
            {"label": "1h",  "hours": 1.0,   "threshold_pct": 0.3},
            {"label": "6h",  "hours": 6.0,   "threshold_pct": 0.3},
            {"label": "24h", "hours": 24.0,  "threshold_pct": 0.5},
            {"label": "5j",  "hours": 120.0, "threshold_pct": 0.5},
        ],
        "price_match_tolerance_ms": 6 * 3600 * 1000,
    },
    "macro": {
        "rows": [
            {"label": "1j",  "hours": 24.0,   "threshold_pct": 0.5},
            {"label": "7j",  "hours": 168.0,  "threshold_pct": 1.0},
            {"label": "30j", "hours": 720.0,  "threshold_pct": 2.0},
            {"label": "90j", "hours": 2160.0, "threshold_pct": 3.0},
        ],
        "price_match_tolerance_ms": 24 * 3600 * 1000,
    },
}


# Alias rétrocompatible — pointe vers les specs swing (comportement Paquet 12).
TRACK_RECORD_HORIZONS = HORIZON_SPECS_BY_SIGNAL_HORIZON["swing"]["rows"]


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
    signal_horizon: str,
    entity_id: str,
    btc_history: list[tuple[int, float]],
    gold_history: list[tuple[int, float]],
    now: datetime,
) -> list[dict]:
    """Calcule les 4 lignes du track record pour un signal donné.

    Args:
        signal_horizon: horizon contractuel du signal ("flash"|"swing"|"macro").
            Détermine les 4 horizons mesurés et les seuils directionnalité
            via HORIZON_SPECS_BY_SIGNAL_HORIZON.

    Retourne une liste de 4 dicts, un par horizon (dans l'ordre croissant) :
      label            : ex. "15min", "1h", "5j", "90j" — selon signal_horizon
      measure_hours    : durée en heures
      threshold_pct    : seuil de succès en %
      available        : True si l'horizon est dans le passé
      target_iso       : timestamp ISO UTC de la cible (stable pour le cache)
      p0               : prix au moment du signal (None si historique insuffisant)
      p1               : prix à t0 + horizon (None si non disponible ou futur)
      delta_pct        : variation (p1-p0)/p0×100 (None si p0/p1 manquants)
      success          : direction correcte (None si données manquantes)
      badge            : "correct"|"raté"|"données_manquantes"|"en_attente"

    Raises:
        ValueError: si signal_horizon n'est pas dans flash/swing/macro.
    """
    if signal_horizon not in HORIZON_SPECS_BY_SIGNAL_HORIZON:
        raise ValueError(
            f"signal_horizon must be one of {list(HORIZON_SPECS_BY_SIGNAL_HORIZON)}, "
            f"got {signal_horizon!r}"
        )

    spec = HORIZON_SPECS_BY_SIGNAL_HORIZON[signal_horizon]
    horizons = spec["rows"]
    tolerance_ms = spec["price_match_tolerance_ms"]

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

    p0 = find_closest_price(history, ts0, max_diff_ms=tolerance_ms) if history else None

    rows: list[dict] = []
    for h in horizons:
        target_dt = ts0 + timedelta(hours=h["hours"])
        available = now_naive >= target_dt

        p1 = (
            find_closest_price(history, target_dt, max_diff_ms=tolerance_ms)
            if (available and p0 is not None and history)
            else None
        )

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
