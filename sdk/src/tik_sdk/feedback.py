"""Telemetry feedback — POST /feedback non bloquant via queue + worker async.

ADR-003 — Le feedback PnL Zeta → Tik ne doit JAMAIS bloquer un trade.
Implémentation conforme :
- `report_outcome()` enqueue + retourne immédiatement (put_nowait).
- Si la queue est pleine → drop avec log warning (on préfère perdre une
  ligne de telemetry plutôt que de bloquer le trader).
- Un worker async sort les payloads de la queue et les POST au core avec
  retry exponentiel borné. Au-delà du retry max → drop avec log error.
- `start()` lance le worker, `stop()` l'arrête proprement (drain optionnel).

Pas de queue persistante en Session 4 : si le SDK crash, les payloads en
file sont perdus. Acceptable car le core peut être recalibré au cycle de
signal suivant. Persistance (SQLite/Redis) si besoin ultérieur.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Literal

import structlog
from pydantic import BaseModel, Field

from tik_sdk.exceptions import NetworkError

if TYPE_CHECKING:
    from tik_sdk._http import HttpClient

log = structlog.get_logger(__name__)

Outcome = Literal["win", "loss", "breakeven", "not_taken"]

DEFAULT_MAX_QUEUE_SIZE = 1000
DEFAULT_MAX_RETRIES = 3
# Backoff par défaut : 1s → 2s → 4s
DEFAULT_BACKOFF_FN: Callable[[int], float] = lambda attempt: 1.0 * (2 ** attempt)
# Délai max d'attente quand on stop le worker proprement
DEFAULT_STOP_TIMEOUT_S = 5.0
# Polling interne du worker (entre 2 attentes sur la queue) — évite un
# blocage infini de await get() qui empêcherait stop_event de se propager.
WORKER_POLL_INTERVAL_S = 0.5


class FeedbackPayload(BaseModel):
    """Payload telemetry envoyé à `POST /api/v1/feedback`.

    Miroir du schéma `FeedbackIn` du core (`storage/schemas.py`).
    """

    signal_id: str
    outcome: Outcome
    trade_id: str | None = None
    pnl_points: float | None = None
    pnl_pct: float | None = None
    duration_held_s: int | None = None
    exit_reason: str | None = None


class FeedbackQueue:
    """File async + worker qui POST au core en arrière-plan."""

    def __init__(
        self,
        http_client: HttpClient,
        *,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_fn: Callable[[int], float] | None = None,
    ) -> None:
        """
        Args:
            http_client: instance `HttpClient` partagée avec `TikClient`.
            max_queue_size: capacité max de la file. Au-delà → drop.
            max_retries: nombre de tentatives par payload avant drop.
            backoff_fn: fonction `attempt → secondes_à_dormir`. Default
                = doublement exponentiel à partir de 1 s. Injectable pour
                des tests sans temps d'attente réel.
        """
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be >= 1")
        if max_retries < 0:
            raise ValueError("max_retries must be >= 0")

        self._http = http_client
        self._max_retries = max_retries
        self._backoff_fn = backoff_fn or DEFAULT_BACKOFF_FN
        self._queue: asyncio.Queue[FeedbackPayload] = asyncio.Queue(maxsize=max_queue_size)
        self._worker_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        # Compteurs publics pour observabilité + tests
        self.sent_count = 0
        self.dropped_count = 0
        self.failed_count = 0

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    async def start(self) -> None:
        """Démarre le worker en arrière-plan. No-op si déjà démarré."""
        if self.is_running:
            return
        self._stop_event.clear()
        self._worker_task = asyncio.create_task(self._worker_loop())
        log.info("tik_sdk.feedback.worker_started")

    async def stop(self, *, drain: bool = False, timeout_s: float = DEFAULT_STOP_TIMEOUT_S) -> None:
        """Arrête le worker proprement.

        Args:
            drain: si True, attend que la queue soit vide avant d'arrêter
                (avec timeout). Si False, drop tout ce qui reste.
            timeout_s: timeout max d'attente du worker.
        """
        if not self.is_running:
            return

        if drain:
            try:
                await asyncio.wait_for(self._queue.join(), timeout=timeout_s)
            except asyncio.TimeoutError:
                log.warning(
                    "tik_sdk.feedback.drain_timeout",
                    remaining=self._queue.qsize(),
                )

        self._stop_event.set()
        assert self._worker_task is not None
        try:
            await asyncio.wait_for(self._worker_task, timeout=timeout_s)
        except asyncio.TimeoutError:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, BaseException):
                pass

        # Drop ce qui reste si on n'a pas drainé
        dropped_on_stop = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
                dropped_on_stop += 1
            except asyncio.QueueEmpty:
                break

        if dropped_on_stop > 0:
            log.warning("tik_sdk.feedback.dropped_on_stop", count=dropped_on_stop)
            self.dropped_count += dropped_on_stop

        self._worker_task = None
        log.info(
            "tik_sdk.feedback.worker_stopped",
            sent=self.sent_count,
            dropped=self.dropped_count,
            failed=self.failed_count,
        )

    def submit(self, payload: FeedbackPayload) -> bool:
        """Enqueue **non-bloquant**. Retourne True si accepté, False si drop.

        Méthode synchrone : appelable depuis un trader sans `await`,
        garantie de retour immédiat.
        """
        try:
            self._queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            log.warning(
                "tik_sdk.feedback.queue_full_drop",
                signal_id=payload.signal_id,
                outcome=payload.outcome,
            )
            self.dropped_count += 1
            return False

    # ----- Worker interne -----

    async def _worker_loop(self) -> None:
        """Boucle principale du worker — sort un payload de la queue et le POST."""
        while not self._stop_event.is_set():
            try:
                payload = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=WORKER_POLL_INTERVAL_S,
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise

            try:
                await self._send_with_retry(payload)
            finally:
                self._queue.task_done()

    async def _send_with_retry(self, payload: FeedbackPayload) -> None:
        """POST avec retry exponentiel. Drop après `max_retries` échecs."""
        for attempt in range(self._max_retries + 1):
            try:
                await self._http.post(
                    "/feedback",
                    json=payload.model_dump(exclude_none=True),
                )
                self.sent_count += 1
                log.debug(
                    "tik_sdk.feedback.sent",
                    signal_id=payload.signal_id,
                    attempt=attempt + 1,
                )
                return
            except NetworkError as exc:
                if attempt >= self._max_retries:
                    log.error(
                        "tik_sdk.feedback.dropped_after_retries",
                        signal_id=payload.signal_id,
                        attempts=attempt + 1,
                        last_error=str(exc),
                    )
                    self.failed_count += 1
                    return
                wait_s = self._backoff_fn(attempt)
                log.warning(
                    "tik_sdk.feedback.send_failed_will_retry",
                    signal_id=payload.signal_id,
                    attempt=attempt + 1,
                    wait_s=wait_s,
                    error=str(exc),
                )
                # Sleep interruptible si stop_event est levé
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=wait_s)
                    # stop_event s'est levé → on sort sans retry
                    self.failed_count += 1
                    return
                except asyncio.TimeoutError:
                    pass  # cycle normal, on retente
            except Exception as exc:  # noqa: BLE001 — 4xx/5xx = pas de retry
                log.error(
                    "tik_sdk.feedback.dropped_non_network_error",
                    signal_id=payload.signal_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                self.failed_count += 1
                return
