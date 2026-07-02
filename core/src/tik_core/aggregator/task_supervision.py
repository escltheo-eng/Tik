"""Supervision des tasks asyncio des ingesters (audit 2026-07-02, chantier T3).

Historiquement, les `asyncio.create_task(self._run())` des `start()` d'ingesters
n'avaient AUCUN done-callback : une exception non captée dans la boucle `_run`
(ex. panne Redis au `setex`) tuait la task **en silence** — asyncio n'émet le
fameux « Task exception was never retrieved » qu'à la destruction de l'objet
task, souvent jamais tant que l'ingester garde la référence. Résultat mesuré :
un ingester mort jusqu'au restart du conteneur, sans une seule ligne de log.

Ce helper attache un done-callback qui logge en `error` toute mort de task sur
exception (événement `ingester.task_died`), en ignorant l'annulation normale
(`CancelledError`, arrêt gracieux via `stop()`).
"""

from __future__ import annotations

import asyncio

import structlog

log = structlog.get_logger()


def supervise_task(task: asyncio.Task, name: str) -> asyncio.Task:
    """Attache un done-callback de supervision à une task d'ingester.

    - task annulée (arrêt gracieux) → rien à logger ;
    - task terminée sur exception → `log.error("ingester.task_died", ...)` :
      la mort de la boucle devient visible dans les logs (et donc détectable
      par un opérateur / une alerte), au lieu d'être avalée.

    Retourne la task telle quelle pour permettre l'écriture en une ligne :
    `self._task = supervise_task(asyncio.create_task(self._run()), self.name)`.
    """

    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.error("ingester.task_died", ingester=name, error=repr(exc))

    task.add_done_callback(_on_done)
    return task
