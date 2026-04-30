"""TikStream — client WebSocket public avec reconnexion auto + hooks.

Usage typique côté bot client :

    async with TikClient("http://localhost:8200", ApiKeyAuth("tik_xxx")) as client:
        stream = client.stream(entity="BTC", horizon="swing")
        stream.on_signal(handle_signal)
        stream.on_veracity_collapse(handle_collapse)
        async with stream:
            await stream.run()  # bloque jusqu'à stream.stop() ou Ctrl+C

Comportement :
- Se connecte à `/api/v1/ws/signals?api_key=...&entity=...&horizon=...`
- Parse chaque message reçu, ignore les heartbeats côté hook.
- En cas de déconnexion : reconnecte avec backoff exponentiel + jitter
  (cf. `_ws.next_backoff`). Reset du backoff à chaque connexion réussie.
- Quatre événements émis :
    * `signal` — Signal Pydantic complet
    * `crash_warning` — `signal.advisory.macro_crash_warning is True`
    * `fake_news_detected` — `signal.circuit_breaker_status != "ok"`
    * `veracity_collapse` — `signal.veracity < veracity_collapse_threshold`

Forward-compat :
- `crash_warning` et `fake_news_detected` sont **dormants** aujourd'hui :
  le core n'émet pas encore ces flags, mais la détection est en place.
- `veracity_collapse` est actif dès maintenant (cf. ADR-004).

ADR-003 — Le stream est read-only. Aucun message n'est envoyé du SDK
vers le core par le canal WS (pas de "force signal" possible).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import suppress
from types import TracebackType
from typing import Any

import structlog
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from tik_sdk._ws import INITIAL_BACKOFF_S, build_ws_url, next_backoff
from tik_sdk.auth import AuthMethod
from tik_sdk.exceptions import AuthError
from tik_sdk.hooks import Handler, HookRegistry
from tik_sdk.models import Signal

log = structlog.get_logger(__name__)

# Type alias pour la fonction de connexion WS (injectable pour tests).
# Signature : (url) -> async context manager qui yield un truc itérable
# de messages (str ou bytes).
ConnectFn = Callable[[str], Any]

# Seuil par défaut : on déclenche `veracity_collapse` quand un signal
# isolé descend sous ce niveau. Détection plus fine (rolling avg, sudden
# drop) prévue en Session 4 avec config YAML.
DEFAULT_VERACITY_COLLAPSE_THRESHOLD = 0.5

# Noms d'événements (centralisés pour éviter typos)
EVENT_SIGNAL = "signal"
EVENT_CRASH_WARNING = "crash_warning"
EVENT_FAKE_NEWS_DETECTED = "fake_news_detected"
EVENT_VERACITY_COLLAPSE = "veracity_collapse"


class TikStream:
    """Stream WebSocket avec reconnexion automatique et dispatch d'événements."""

    def __init__(
        self,
        base_url: str,
        auth: AuthMethod,
        *,
        entity: str | None = None,
        horizon: str | None = None,
        veracity_collapse_threshold: float = DEFAULT_VERACITY_COLLAPSE_THRESHOLD,
        connect_fn: ConnectFn | None = None,
    ) -> None:
        """
        Args:
            base_url: URL HTTP(S) du core, ex `http://localhost:8200`. Sera
                convertie en ws:// automatiquement.
            auth: méthode d'auth pluggable (cf. `auth.py`). Doit fournir
                un `query_params()["api_key"]`.
            entity: filtre côté serveur (ex `"BTC"`). None = tout.
            horizon: filtre côté serveur (`"flash"` | `"swing"` | `"macro"`).
            veracity_collapse_threshold: seuil sous lequel on déclenche
                `veracity_collapse`. Défaut 0.5.
            connect_fn: injection de dépendance pour les tests. En prod,
                None → utilise `websockets.connect`.
        """
        params = auth.query_params()
        api_key = params.get("api_key")
        if not api_key:
            raise ValueError(
                "auth method does not provide an 'api_key' query param "
                "(required for /ws/signals authentication)"
            )

        self._url = build_ws_url(
            base_url,
            api_key_param=api_key,
            entity=entity,
            horizon=horizon,
        )
        self._veracity_collapse_threshold = veracity_collapse_threshold
        self._connect_fn: ConnectFn = connect_fn or websockets.connect

        self._hooks = HookRegistry()
        self._stop_event = asyncio.Event()
        self._connected_event = asyncio.Event()  # Set à chaque (re)connexion réussie
        # Référence à la connexion WS active. Permet à stop() de la fermer
        # explicitement pour interrompre `async for raw in ws:` quand la
        # connexion est silencieuse (sinon stop() ne sort jamais).
        self._active_ws: Any = None

    # ----- API publique : registration des hooks -----

    def on_signal(self, handler: Handler) -> None:
        """Enregistre un handler appelé à chaque signal reçu (sync ou async)."""
        self._hooks.register(EVENT_SIGNAL, handler)

    def on_crash_warning(self, handler: Handler) -> None:
        """Handler appelé quand `signal.advisory.macro_crash_warning is True`.

        Dormant aujourd'hui : le core ne positionne pas encore ce flag.
        """
        self._hooks.register(EVENT_CRASH_WARNING, handler)

    def on_fake_news_detected(self, handler: Handler) -> None:
        """Handler appelé quand `signal.circuit_breaker_status != "ok"`.

        Dormant aujourd'hui : le core ne déclenche pas encore son
        circuit breaker (anti-fake-news pas encore branché).
        """
        self._hooks.register(EVENT_FAKE_NEWS_DETECTED, handler)

    def on_veracity_collapse(self, handler: Handler) -> None:
        """Handler appelé quand `signal.veracity < threshold` (défaut 0.5).

        Actif dès maintenant. Cf. ADR-004 pour le calcul de la veracity.
        """
        self._hooks.register(EVENT_VERACITY_COLLAPSE, handler)

    # ----- Lifecycle -----

    async def __aenter__(self) -> TikStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()

    async def stop(self) -> None:
        """Demande l'arrêt propre du stream.

        - Set le stop event pour empêcher toute reconnexion ultérieure.
        - Ferme la connexion WS active si présente, ce qui fait lever
          `ConnectionClosed` dans `async for raw in ws:` et permet à
          `run()` de sortir promptement.
        """
        self._stop_event.set()
        ws = self._active_ws
        if ws is not None:
            with suppress(Exception):
                await ws.close()

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set()

    async def wait_connected(self, timeout: float | None = None) -> None:
        """Bloque jusqu'à la première connexion réussie. Utile pour tests."""
        await asyncio.wait_for(self._connected_event.wait(), timeout=timeout)

    async def run(self) -> None:
        """Boucle principale : connecte, lit les messages, reconnecte sur erreur.

        Bloque jusqu'à `await stream.stop()` ou `asyncio.CancelledError`.
        """
        backoff = INITIAL_BACKOFF_S
        while not self._stop_event.is_set():
            try:
                async with self._connect_fn(self._url) as ws:
                    self._active_ws = ws
                    log.info("tik_sdk.ws.connected", url=self._safe_url())
                    self._connected_event.set()
                    backoff = INITIAL_BACKOFF_S  # reset après succès

                    try:
                        async for raw in ws:
                            if self._stop_event.is_set():
                                break
                            await self._process_message(raw)
                    finally:
                        self._active_ws = None

            except asyncio.CancelledError:
                # Cancellation externe : on respecte et on sort.
                raise
            except InvalidStatus as exc:
                # Handshake refusé — souvent une mauvaise clé. Pas la peine de retry.
                status = getattr(exc.response, "status_code", None)
                if status in (401, 403):
                    log.error("tik_sdk.ws.auth_refused", status=status)
                    raise AuthError(f"WS handshake refused: HTTP {status}") from exc
                log.warning("tik_sdk.ws.invalid_status", status=status, error=str(exc))
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                log.warning(
                    "tik_sdk.ws.disconnected",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

            if self._stop_event.is_set():
                break

            # Pause avant tentative de reconnexion. interruptible si stop().
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._stop_event.wait(), timeout=backoff)
            backoff = next_backoff(backoff)

        log.info("tik_sdk.ws.stopped")

    # ----- Parsing + dispatch -----

    async def _process_message(self, raw: str | bytes) -> None:
        """Parse un message brut et dispatch les événements correspondants.

        Pure-ish (mute le HookRegistry) : trivialement testable sans WS.
        """
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("tik_sdk.ws.bad_json", error=str(exc), raw_excerpt=str(raw)[:100])
            return

        if not isinstance(message, dict):
            log.warning("tik_sdk.ws.unexpected_message_shape", message_type=type(message).__name__)
            return

        msg_type = message.get("type")

        if msg_type == "heartbeat":
            log.debug("tik_sdk.ws.heartbeat")
            return

        if msg_type != "signal":
            log.debug("tik_sdk.ws.unknown_message_type", type=msg_type)
            return

        payload = message.get("payload")
        if not isinstance(payload, dict):
            log.warning("tik_sdk.ws.signal_without_payload")
            return

        try:
            signal = Signal.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 — payload mal formé : on log et on ignore
            log.warning(
                "tik_sdk.ws.signal_validation_failed",
                error=str(exc),
                payload_id=payload.get("id"),
            )
            return

        await self._dispatch_signal(signal)

    async def _dispatch_signal(self, signal: Signal) -> None:
        """Détermine quels événements émettre pour ce signal, et dispatch."""
        # `on_signal` toujours
        await self._hooks.dispatch(EVENT_SIGNAL, signal)

        # Conditions dérivées
        if signal.advisory.macro_crash_warning:
            await self._hooks.dispatch(EVENT_CRASH_WARNING, signal)

        if signal.circuit_breaker_status != "ok":
            await self._hooks.dispatch(EVENT_FAKE_NEWS_DETECTED, signal)

        if signal.veracity < self._veracity_collapse_threshold:
            await self._hooks.dispatch(EVENT_VERACITY_COLLAPSE, signal)

    # ----- Helpers -----

    def _safe_url(self) -> str:
        """URL avec api_key masquée (pour les logs)."""
        if "api_key=" not in self._url:
            return self._url
        prefix, _, rest = self._url.partition("api_key=")
        # Tronque la valeur et ré-attache les éventuels params suivants
        end = rest.find("&")
        masked = "***"
        suffix = rest[end:] if end != -1 else ""
        return f"{prefix}api_key={masked}{suffix}"


__all__ = ["TikStream"]
