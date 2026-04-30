"""Registry et dispatcher de hooks événementiels.

Conçu pour le `TikStream` (Session 2) mais générique : utilisable pour
n'importe quel canal d'événements futur (telemetry, config-reload, etc.).

Caractéristiques :
- Accepte indifféremment des handlers **sync** et **async**.
- Supporte plusieurs handlers par événement (registrés dans l'ordre).
- **Isole les exceptions** : un handler qui plante n'arrête pas la boucle
  ni les autres handlers — l'exception est loggée et la dispatch continue.
  C'est essentiel pour un client de production qui tourne 24/7 derrière
  un bot de trading.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Un handler est soit une fonction sync, soit une coroutine. Le payload
# passé varie par événement (Signal pour signal/crash/fake_news/collapse,
# autre chose pour de futurs événements).
Handler = Callable[[Any], None] | Callable[[Any], Awaitable[None]]


class HookRegistry:
    """Stocke les handlers par nom d'événement.

    Pas thread-safe — destiné à un usage asyncio mono-thread (ce qui
    couvre tous les cas SDK actuels).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def register(self, event: str, handler: Handler) -> None:
        """Enregistre un handler pour un événement nommé."""
        if not callable(handler):
            raise TypeError(f"handler must be callable, got {type(handler).__name__}")
        self._handlers.setdefault(event, []).append(handler)

    def handlers_for(self, event: str) -> list[Handler]:
        """Retourne la liste (copie défensive) des handlers d'un événement."""
        return list(self._handlers.get(event, ()))

    def has(self, event: str) -> bool:
        return bool(self._handlers.get(event))

    async def dispatch(self, event: str, payload: Any) -> None:
        """Appelle tous les handlers d'un événement avec le payload donné.

        - Les handlers async sont awaités en séquence (préserve l'ordre,
          évite que l'engineering Zeta ait à raisonner sur la concurrence
          des handlers sur un même événement).
        - Les handlers sync sont appelés directement.
        - Toute exception est attrapée et loggée — la dispatch continue
          avec les handlers restants.
        """
        for handler in self._handlers.get(event, ()):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    result = handler(payload)
                    # Cas particulier : handler "sync" qui retourne en réalité une
                    # coroutine (callable wrappant une lambda async, etc.).
                    if asyncio.iscoroutine(result):
                        await result
            except Exception as exc:  # noqa: BLE001 — on isole délibérément
                # NB : on évite le kwarg `event=...` qui collisionne avec
                # le 1er argument de `log.error()` côté structlog.
                log.error(
                    "tik_sdk.hooks.handler_failed",
                    hook_event=event,
                    handler=getattr(handler, "__name__", repr(handler)),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
