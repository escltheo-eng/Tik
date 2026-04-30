"""Circuit breaker LOCAL — protège le SDK contre un core Tik en panne.

Le bot client (Zeta, Totem) ne doit pas marteler un core down : ça gaspille
des ressources, ça allonge ses propres latences, et ça empêche le core de
se rétablir. Le circuit breaker détecte les échecs réseau consécutifs et
"ouvre le circuit" — toutes les requêtes suivantes sont rejetées
immédiatement (sans tenter le HTTP) jusqu'à un délai de reset.

ADR-003 — Ce circuit breaker est **local au SDK** et indépendant de celui
du core. Il ne remplace pas le `circuit_breaker_status` qu'on lit dans
les signaux (qui, lui, est l'anti-fake-news du core).

Trois états :

    closed     — tout va bien, requêtes passent. On compte les échecs.
    open       — on rejette tout (CircuitBreakerOpen) pendant `reset_timeout_s`.
    half_open  — fenêtre exploratoire : on laisse passer 1 requête de test.
                 Succès → closed (reset compteur). Échec → open (reset timer).

Pas de dépendance externe. Pas asyncio.Lock — les méthodes ne font pas
d'await, elles sont atomiques côté event loop mono-thread.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

State = Literal["closed", "open", "half_open"]

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RESET_TIMEOUT_S = 30.0


class CircuitBreaker:
    """Compteur d'échecs + machine à états."""

    def __init__(
        self,
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        reset_timeout_s: float = DEFAULT_RESET_TIMEOUT_S,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        """
        Args:
            failure_threshold: nombre d'échecs consécutifs avant d'ouvrir.
            reset_timeout_s: délai après ouverture avant de tenter half_open.
            time_fn: source de temps injectable (tests). Défaut `time.monotonic`.
        """
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if reset_timeout_s <= 0:
            raise ValueError("reset_timeout_s must be > 0")

        self._failure_threshold = failure_threshold
        self._reset_timeout_s = reset_timeout_s
        self._time_fn = time_fn or time.monotonic

        self._state: State = "closed"
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> State:
        """Met à jour l'état si on est en `open` au-delà du reset_timeout, puis le renvoie."""
        if self._state == "open" and self._opened_at is not None:
            if (self._time_fn() - self._opened_at) >= self._reset_timeout_s:
                self._state = "half_open"
                log.info("tik_sdk.circuit_breaker.transition_to_half_open")
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def can_attempt(self) -> bool:
        """True si une requête peut être tentée maintenant.

        - closed → True
        - open → False (jusqu'au reset_timeout, après quoi on passe half_open)
        - half_open → True (probe)
        """
        return self.state in ("closed", "half_open")

    def record_success(self) -> None:
        """Une requête a réussi : reset compteur + retour à closed."""
        if self._state != "closed":
            log.info(
                "tik_sdk.circuit_breaker.transition_to_closed",
                from_state=self._state,
            )
        self._state = "closed"
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """Une requête a échoué (NetworkError) : incrémente, peut ouvrir.

        Comportement par état actuel (via la propriété qui auto-transitionne) :
        - closed : incrémente. Si seuil atteint → open.
        - half_open : la probe a échoué → on retourne open avec timer reset.
        - open : ne devrait pas arriver (can_attempt aurait dit False), mais
          défensif : reset le timer.
        """
        current = self.state  # peut basculer open → half_open via la propriété
        self._consecutive_failures += 1

        if current == "half_open":
            # Probe échouée : retour en open avec timer reset
            self._open()
            log.warning("tik_sdk.circuit_breaker.half_open_probe_failed")
            return

        if current == "closed" and self._consecutive_failures >= self._failure_threshold:
            self._open()
            log.warning(
                "tik_sdk.circuit_breaker.transition_to_open",
                consecutive_failures=self._consecutive_failures,
                reset_timeout_s=self._reset_timeout_s,
            )
            return

        if current == "open":
            # Cas défensif (ne devrait pas arriver mais on log)
            self._open()

    def _open(self) -> None:
        self._state = "open"
        self._opened_at = self._time_fn()
