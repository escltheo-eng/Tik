"""Config YAML hot-reloadable pour le SDK Tik.

Usage typique :

    config = TikConfig.load_from_yaml("tik.yaml")
    async with TikClient.from_config(config) as client:
        # ...

Hot-reload via `ConfigWatcher` : poll toutes les 5 s la mtime du fichier.
Si elle change, on recharge + on appelle les handlers enregistrés.

Pourquoi polling et pas `watchdog` ? Pour ne pas ajouter une dépendance
système (inotify Linux / fsevents macOS). Polling 5 s est largement
suffisant pour de la config qui change rarement.

**Périmètre du hot-reload** :
- Mutables à chaud : TTL cache, seuil veracity_collapse stream
- **Non mutables** (warning loggué) : base_url, timeout, breaker
  thresholds, capacité queue feedback. Nécessitent un redémarrage.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
import yaml
from pydantic import BaseModel, Field

from tik_sdk.cache import DEFAULT_TTL_BY_HORIZON

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)

DEFAULT_POLL_INTERVAL_S = 5.0


# ----- Sous-modèles de config -----


class CoreConfig(BaseModel):
    """Connexion au core Tik."""

    base_url: str
    timeout_s: float = 10.0


class CacheConfig(BaseModel):
    """Cache local SDK (Session 3)."""

    enabled: bool = False
    maxsize: int = 1000
    ttl_by_horizon: dict[str, int] = Field(
        default_factory=lambda: dict(DEFAULT_TTL_BY_HORIZON)
    )


class CircuitBreakerConfig(BaseModel):
    """Circuit breaker LOCAL SDK (Session 3)."""

    enabled: bool = False
    failure_threshold: int = 5
    reset_timeout_s: float = 30.0


class StreamConfig(BaseModel):
    """Settings du WebSocket stream (Session 2)."""

    veracity_collapse_threshold: float = 0.5


class FeedbackConfig(BaseModel):
    """Telemetry queue feedback (Session 4)."""

    enabled: bool = True
    max_queue_size: int = 1000
    max_retries: int = 3


# ----- Config racine -----


class TikConfig(BaseModel):
    """Configuration complète du SDK Tik chargée depuis YAML."""

    core: CoreConfig
    cache: CacheConfig = Field(default_factory=CacheConfig)
    circuit_breaker: CircuitBreakerConfig = Field(default_factory=CircuitBreakerConfig)
    stream: StreamConfig = Field(default_factory=StreamConfig)
    feedback: FeedbackConfig = Field(default_factory=FeedbackConfig)

    @classmethod
    def load_from_yaml(cls, path: str | Path) -> TikConfig:
        """Charge et valide un fichier YAML."""
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"config file not found: {path}")
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls.model_validate(data)


# ----- Hot-reload watcher -----

# Type d'un handler de reload : reçoit l'ancien et le nouveau config
ReloadHandler = Callable[["TikConfig", "TikConfig"], None]


class ConfigWatcher:
    """Polling du mtime d'un fichier YAML, déclenche des handlers à chaque changement.

    Usage :

        watcher = ConfigWatcher("tik.yaml")
        watcher.on_reload(lambda old, new: client.apply_mutable_config(new))
        async with watcher:
            # poll en background
            await some_long_running_task()

    Les handlers sont appelés en mode best-effort : une exception dans un
    handler est loggée mais n'arrête pas la boucle de polling ni les
    autres handlers.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        """
        Args:
            path: chemin du fichier YAML à surveiller.
            poll_interval_s: intervalle entre 2 vérifications du mtime.
            time_fn: source de temps injectable (tests).
        """
        if poll_interval_s <= 0:
            raise ValueError("poll_interval_s must be > 0")
        self._path = Path(path)
        self._poll_interval_s = poll_interval_s
        self._time_fn = time_fn or time.monotonic
        self._handlers: list[ReloadHandler] = []
        self._current_config: TikConfig | None = None
        self._last_mtime: float | None = None
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def current_config(self) -> TikConfig | None:
        return self._current_config

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def on_reload(self, handler: ReloadHandler) -> None:
        """Enregistre un handler appelé à chaque rechargement réussi.

        Le handler reçoit `(old_config, new_config)`. Sync uniquement
        (la complexité d'un reload async ne se justifie pas ici).
        """
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._handlers.append(handler)

    async def start(self) -> TikConfig:
        """Charge le fichier une première fois et lance le polling.

        Returns:
            La config chargée à T0.
        """
        if self.is_running:
            assert self._current_config is not None
            return self._current_config

        # Premier chargement (synchrone, propage l'exception si fichier KO)
        self._current_config = TikConfig.load_from_yaml(self._path)
        self._last_mtime = self._path.stat().st_mtime
        log.info("tik_sdk.config.loaded", path=str(self._path))

        self._stop_event.clear()
        self._task = asyncio.create_task(self._poll_loop())
        return self._current_config

    async def stop(self) -> None:
        """Arrête le polling proprement."""
        if not self.is_running:
            return
        self._stop_event.set()
        assert self._task is not None
        try:
            await asyncio.wait_for(self._task, timeout=5.0)
        except asyncio.TimeoutError:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, BaseException):
                pass
        self._task = None

    async def __aenter__(self) -> ConfigWatcher:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    # --- internal ---

    async def _poll_loop(self) -> None:
        while not self._stop_event.is_set():
            # Sleep interruptible
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._poll_interval_s,
                )
                break  # stop_event signalé
            except asyncio.TimeoutError:
                pass

            try:
                self._check_and_reload()
            except Exception as exc:  # noqa: BLE001 — best-effort
                log.warning(
                    "tik_sdk.config.poll_failed",
                    path=str(self._path),
                    error=str(exc),
                )

    def _check_and_reload(self) -> None:
        """Vérifie le mtime et recharge si modifié."""
        try:
            current_mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            log.warning("tik_sdk.config.file_missing", path=str(self._path))
            return

        if self._last_mtime is None or current_mtime <= self._last_mtime:
            return

        # Le fichier a été modifié — on tente le reload
        try:
            new_config = TikConfig.load_from_yaml(self._path)
        except Exception as exc:  # noqa: BLE001 — YAML invalide ou Pydantic invalid
            log.error(
                "tik_sdk.config.reload_validation_failed",
                path=str(self._path),
                error=str(exc),
            )
            # On garde l'ancien config et l'ancien mtime (on retentera au prochain poll)
            return

        old_config = self._current_config
        assert old_config is not None
        self._current_config = new_config
        self._last_mtime = current_mtime
        log.info("tik_sdk.config.reloaded", path=str(self._path))

        # Dispatch aux handlers (isolation des exceptions)
        for handler in self._handlers:
            try:
                handler(old_config, new_config)
            except Exception as exc:  # noqa: BLE001
                log.error(
                    "tik_sdk.config.reload_handler_failed",
                    handler=getattr(handler, "__name__", repr(handler)),
                    error=str(exc),
                )


# ----- Helpers diff config -----


def diff_mutable_settings(old: TikConfig, new: TikConfig) -> dict[str, object]:
    """Renvoie un dict des settings mutables qui ont changé entre `old` et `new`.

    Les settings non mutables qui changent sont **ignorés** ici (cf. helper
    `warn_immutable_changes`). Settings mutables :
    - cache.ttl_by_horizon
    - stream.veracity_collapse_threshold
    """
    diff: dict[str, object] = {}
    if old.cache.ttl_by_horizon != new.cache.ttl_by_horizon:
        diff["cache.ttl_by_horizon"] = new.cache.ttl_by_horizon
    if old.stream.veracity_collapse_threshold != new.stream.veracity_collapse_threshold:
        diff["stream.veracity_collapse_threshold"] = new.stream.veracity_collapse_threshold
    return diff


def warn_immutable_changes(old: TikConfig, new: TikConfig) -> list[str]:
    """Retourne la liste (et logge) des settings non mutables qui ont changé.

    Ces changements **n'ont pas d'effet** sans redémarrage du SDK. Le caller
    décide quoi faire (continuer en silence, lever, alerter, etc.).
    """
    warnings_list: list[str] = []
    checks: list[tuple[str, object, object]] = [
        ("core.base_url", old.core.base_url, new.core.base_url),
        ("core.timeout_s", old.core.timeout_s, new.core.timeout_s),
        ("cache.enabled", old.cache.enabled, new.cache.enabled),
        ("cache.maxsize", old.cache.maxsize, new.cache.maxsize),
        ("circuit_breaker.enabled", old.circuit_breaker.enabled, new.circuit_breaker.enabled),
        (
            "circuit_breaker.failure_threshold",
            old.circuit_breaker.failure_threshold,
            new.circuit_breaker.failure_threshold,
        ),
        (
            "circuit_breaker.reset_timeout_s",
            old.circuit_breaker.reset_timeout_s,
            new.circuit_breaker.reset_timeout_s,
        ),
        ("feedback.enabled", old.feedback.enabled, new.feedback.enabled),
        ("feedback.max_queue_size", old.feedback.max_queue_size, new.feedback.max_queue_size),
        ("feedback.max_retries", old.feedback.max_retries, new.feedback.max_retries),
    ]
    for name, old_v, new_v in checks:
        if old_v != new_v:
            warnings_list.append(name)
            log.warning(
                "tik_sdk.config.immutable_changed_requires_restart",
                key=name,
                old=str(old_v),
                new=str(new_v),
            )
    return warnings_list
