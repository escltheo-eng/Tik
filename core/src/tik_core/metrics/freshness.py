"""Fraîcheur des signaux — détection de panne silencieuse (M4, audit 2026-05-24).

Tik émet en continu (un swing BTC toutes les 15 min quand il est sain). Si plus
aucun signal n'est produit pendant un certain temps, c'est le symptôme d'une
panne silencieuse (scheduler bloqué, engines qui lèvent à chaque cycle, ingesters
morts) — historiquement avalée en `log.warning` que personne ne lit (cf. CLAUDE.md
Issue #3 Paquet 26, Bug 9 qui a tourné 4h sans détection). Ce module fournit le
calcul pur ; l'endpoint `/metrics/signal_freshness` l'expose, et le dashboard
affiche une bannière rouge quand `stale=True`.

Logique pure, zéro IO (DB/Redis/HTTP) — testable directement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# Seuil par défaut : 60 min (décision M4 2026-05-24). Un Tik sain publie un swing
# BTC toutes les 15 min ; 60 min sans AUCUN signal = anomalie quasi-certaine, avec
# très peu de faux positifs (un redémarrage ne dure que ~30s).
DEFAULT_STALENESS_THRESHOLD_SECONDS = 60 * 60


@dataclass(frozen=True)
class SignalFreshness:
    last_signal_at: datetime | None
    age_seconds: float | None
    stale: bool
    threshold_seconds: int


def compute_signal_freshness(
    last_signal_at: datetime | None,
    now: datetime,
    threshold_seconds: int = DEFAULT_STALENESS_THRESHOLD_SECONDS,
) -> SignalFreshness:
    """Indique si la production de signaux est 'muette' (anormale).

    `last_signal_at` et `now` sont comparés tels quels (attendus naïfs UTC,
    cohérent avec les timestamps DB strippés — cf. Bug 9).

    - `last_signal_at is None` (aucun signal en base) → stale=True : un Tik en
      fonctionnement devrait toujours avoir produit au moins un signal.
    - âge négatif (clock skew) → ramené à 0 (considéré frais).
    """
    if last_signal_at is None:
        return SignalFreshness(
            last_signal_at=None,
            age_seconds=None,
            stale=True,
            threshold_seconds=threshold_seconds,
        )
    age = max(0.0, (now - last_signal_at).total_seconds())
    return SignalFreshness(
        last_signal_at=last_signal_at,
        age_seconds=age,
        stale=age > threshold_seconds,
        threshold_seconds=threshold_seconds,
    )
