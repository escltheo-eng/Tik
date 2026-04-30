"""TikClient — client Python haut niveau pour le core Tik.

Usage minimal :

    import asyncio
    from tik_sdk import TikClient, ApiKeyAuth

    async def main():
        async with TikClient("http://localhost:8200", ApiKeyAuth("tik_xxx")) as client:
            health = await client.get_health()
            signals = await client.get_latest_signals(entity="BTC", horizon="swing", limit=5)

    asyncio.run(main())

Usage avec résilience (Session 3 — opt-in) :

    from tik_sdk import TikClient, ApiKeyAuth, InMemoryCache, CircuitBreaker

    async with TikClient(
        "http://localhost:8200",
        ApiKeyAuth("tik_xxx"),
        cache=InMemoryCache(maxsize=1000),
        circuit_breaker=CircuitBreaker(failure_threshold=5, reset_timeout_s=30),
    ) as client:
        signals = await client.get_latest_signals(entity="BTC", horizon="swing")

Usage avec config YAML + telemetry (Session 4) :

    from tik_sdk import TikClient, ApiKeyAuth, TikConfig

    config = TikConfig.load_from_yaml("tik.yaml")
    async with TikClient.from_config(config, auth=ApiKeyAuth("tik_xxx")) as client:
        # report_outcome est non-bloquant — retour immédiat, POST en background
        await client.report_outcome(
            signal_id="TIK-SWING-BTC-...",
            outcome="win",
            pnl_pct=1.4,
            duration_held_s=4200,
        )

ADR-003 — Le client expose UNIQUEMENT des opérations de lecture + un
report_outcome() asynchrone non bloquant. Aucune méthode d'exécution
d'ordre, aucun raccourci d'écriture vers Zeta. Le guard V01-V15 reste
systématique. Le `POST /feedback` est géré par une queue async (cf.
`tik_sdk.feedback`) qui retry en background ; un Tik down ne ralentit
JAMAIS un trade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from pydantic import TypeAdapter

from tik_sdk._http import DEFAULT_TIMEOUT, HttpClient
from tik_sdk.auth import AuthMethod
from tik_sdk.cache import DEFAULT_TTL_BY_HORIZON, Cache, InMemoryCache
from tik_sdk.circuit_breaker import CircuitBreaker
from tik_sdk.feedback import FeedbackPayload, FeedbackQueue, Outcome
from tik_sdk.models import (
    Entity,
    Health,
    Signal,
    SourceVeracity,
    VeracityStatus,
)

if TYPE_CHECKING:
    from tik_sdk.config import TikConfig
    from tik_sdk.stream import TikStream

# TypeAdapter — validation efficace des listes Pydantic
_SIGNALS_ADAPTER = TypeAdapter(list[Signal])
_ENTITIES_ADAPTER = TypeAdapter(list[Entity])
_SOURCES_ADAPTER = TypeAdapter(list[SourceVeracity])


def _ttl_for(horizon: str | None, ttl_by_horizon: dict[str, int]) -> int:
    """Renvoie le TTL applicable pour un horizon (ou 'default' si inconnu/None)."""
    if horizon and horizon in ttl_by_horizon:
        return ttl_by_horizon[horizon]
    return ttl_by_horizon.get("default", 300)


class TikClient:
    """Client async public du SDK Tik.

    Toutes les méthodes :
    - sont async et lisent depuis le core via HTTP,
    - lèvent une exception `TikError` (ou sous-classe) en cas d'erreur,
    - retournent des modèles Pydantic typés (cf. `tik_sdk.models`).

    Exception : `report_outcome()` enqueue + retourne immédiatement
    (telemetry non bloquante, cf. ADR-003).

    Utiliser en `async with` pour fermer proprement la connexion HTTP
    et drainer la queue feedback.

    Args:
        base_url: URL HTTP(S) du core, ex `http://localhost:8200`.
        auth: méthode d'authentification (cf. `auth.py`).
        timeout: timeout HTTP en secondes.
        transport: `httpx.AsyncBaseTransport` injecté pour les tests.
        cache: cache local opt-in (Session 3).
        circuit_breaker: circuit breaker LOCAL opt-in (Session 3).
        ttl_by_horizon: TTL par horizon en secondes (Session 3).
        feedback_queue: file telemetry. Si None et `enable_feedback`=True,
            une queue par défaut est créée. Si None et `enable_feedback`=False,
            les `report_outcome` lèvent (le SDK n'a pas de queue active).
        enable_feedback: active la queue feedback par défaut (Session 4).
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthMethod,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: Cache | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        ttl_by_horizon: dict[str, int] | None = None,
        feedback_queue: FeedbackQueue | None = None,
        enable_feedback: bool = True,
    ) -> None:
        # Conservés sur l'instance pour `client.stream(...)` qui réutilise
        # ces credentials côté WebSocket.
        self._base_url = base_url
        self._auth = auth
        self._ttl_by_horizon = dict(ttl_by_horizon) if ttl_by_horizon else dict(
            DEFAULT_TTL_BY_HORIZON
        )
        self._http = HttpClient(
            base_url=base_url,
            auth=auth,
            timeout=timeout,
            transport=transport,
            cache=cache,
            circuit_breaker=circuit_breaker,
        )

        # Queue feedback : créée par défaut sauf si on l'a explicitement
        # désactivée. Reste inactive (pas de worker démarré) jusqu'au
        # `__aenter__` ou `await client.start_feedback()`.
        if feedback_queue is not None:
            self._feedback_queue: FeedbackQueue | None = feedback_queue
        elif enable_feedback:
            self._feedback_queue = FeedbackQueue(self._http)
        else:
            self._feedback_queue = None

    # ----- Factory from YAML -----

    @classmethod
    def from_config(
        cls,
        config: TikConfig,
        auth: AuthMethod,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> TikClient:
        """Construit un `TikClient` à partir d'un `TikConfig` chargé depuis YAML.

        Applique tous les paramètres de la config (cache + breaker + feedback).
        """
        cache = (
            InMemoryCache(maxsize=config.cache.maxsize) if config.cache.enabled else None
        )
        cb = (
            CircuitBreaker(
                failure_threshold=config.circuit_breaker.failure_threshold,
                reset_timeout_s=config.circuit_breaker.reset_timeout_s,
            )
            if config.circuit_breaker.enabled
            else None
        )
        client = cls(
            base_url=config.core.base_url,
            auth=auth,
            timeout=config.core.timeout_s,
            transport=transport,
            cache=cache,
            circuit_breaker=cb,
            ttl_by_horizon=dict(config.cache.ttl_by_horizon),
            enable_feedback=config.feedback.enabled,
        )
        # Si feedback activé, applique les paramètres de queue
        if config.feedback.enabled and client._feedback_queue is not None:
            # Recrée la queue avec les bons paramètres
            client._feedback_queue = FeedbackQueue(
                client._http,
                max_queue_size=config.feedback.max_queue_size,
                max_retries=config.feedback.max_retries,
            )
        return client

    # ----- Lifecycle -----

    async def aclose(self) -> None:
        """Stop la queue feedback (fast shutdown, drop ce qui reste) et ferme le HTTP."""
        if self._feedback_queue is not None:
            await self._feedback_queue.stop(drain=False)
        await self._http.aclose()

    async def __aenter__(self) -> TikClient:
        # Démarre la queue feedback si configurée
        if self._feedback_queue is not None:
            await self._feedback_queue.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # ----- Health -----

    async def get_health(self) -> Health:
        """`GET /health` — pas d'auth requise. JAMAIS mis en cache."""
        data = await self._http.get("/health", authenticated=False, cache_ttl_s=0)
        return Health.model_validate(data)

    # ----- Entities -----

    async def list_entities(self, *, active_only: bool = True) -> list[Entity]:
        """`GET /entities` — liste des entités observées par Tik."""
        data = await self._http.get(
            "/entities",
            params={"active_only": active_only},
            cache_ttl_s=_ttl_for(None, self._ttl_by_horizon),
        )
        return _ENTITIES_ADAPTER.validate_python(data)

    async def get_entity(self, entity_id: str) -> Entity:
        """`GET /entities/{id}`."""
        data = await self._http.get(
            f"/entities/{entity_id}",
            cache_ttl_s=_ttl_for(None, self._ttl_by_horizon),
        )
        return Entity.model_validate(data)

    # ----- Signals -----

    async def get_latest_signals(
        self,
        *,
        entity: str | None = None,
        horizon: str | None = None,
        limit: int = 20,
    ) -> list[Signal]:
        """`GET /signals/latest` — derniers signaux émis (antéchronologique).

        TTL en cache adapté à l'horizon : flash 60 s, swing 5 min, macro 1 h.

        Les signaux expirés sont inclus : c'est au bot client de vérifier
        `expiry` et `circuit_breaker_status` avant d'agir.
        """
        params: dict[str, Any] = {"limit": limit}
        if entity is not None:
            params["entity"] = entity
        if horizon is not None:
            params["horizon"] = horizon
        data = await self._http.get(
            "/signals/latest",
            params=params,
            cache_ttl_s=_ttl_for(horizon, self._ttl_by_horizon),
        )
        return _SIGNALS_ADAPTER.validate_python(data)

    async def get_signal(self, signal_id: str) -> Signal:
        """`GET /signals/{id}`. TTL = `default`."""
        data = await self._http.get(
            f"/signals/{signal_id}",
            cache_ttl_s=_ttl_for(None, self._ttl_by_horizon),
        )
        return Signal.model_validate(data)

    async def search_signals(
        self,
        *,
        entity: str | None = None,
        horizon: str | None = None,
        direction: str | None = None,
        min_confidence: float = 0.0,
        min_veracity: float = 0.0,
        since_hours: int = 24,
        limit: int = 100,
    ) -> list[Signal]:
        """`GET /signals` — recherche multi-filtres. TTL adapté à l'horizon."""
        params: dict[str, Any] = {
            "min_confidence": min_confidence,
            "min_veracity": min_veracity,
            "since_hours": since_hours,
            "limit": limit,
        }
        if entity is not None:
            params["entity"] = entity
        if horizon is not None:
            params["horizon"] = horizon
        if direction is not None:
            params["direction"] = direction
        data = await self._http.get(
            "/signals",
            params=params,
            cache_ttl_s=_ttl_for(horizon, self._ttl_by_horizon),
        )
        return _SIGNALS_ADAPTER.validate_python(data)

    # ----- Veracity -----

    async def get_global_veracity(self) -> VeracityStatus:
        """`GET /veracity/global` — moyenne pondérée par tier des sources actives."""
        data = await self._http.get(
            "/veracity/global",
            cache_ttl_s=_ttl_for(None, self._ttl_by_horizon),
        )
        return VeracityStatus.model_validate(data)

    async def list_sources(self, *, active_only: bool = True) -> list[SourceVeracity]:
        """`GET /veracity/sources` — détail par source."""
        data = await self._http.get(
            "/veracity/sources",
            params={"active_only": active_only},
            cache_ttl_s=_ttl_for(None, self._ttl_by_horizon),
        )
        return _SOURCES_ADAPTER.validate_python(data)

    async def get_source(self, source_id: str) -> SourceVeracity:
        """`GET /veracity/sources/{id}`."""
        data = await self._http.get(
            f"/veracity/sources/{source_id}",
            cache_ttl_s=_ttl_for(None, self._ttl_by_horizon),
        )
        return SourceVeracity.model_validate(data)

    # ----- Telemetry feedback (Session 4) -----

    async def report_outcome(
        self,
        signal_id: str,
        outcome: Outcome,
        *,
        trade_id: str | None = None,
        pnl_points: float | None = None,
        pnl_pct: float | None = None,
        duration_held_s: int | None = None,
        exit_reason: str | None = None,
    ) -> bool:
        """Renvoie au core le résultat d'un trade pris sur un signal Tik.

        **Non bloquant** (ADR-003) : enqueue + retour immédiat. Le POST
        part en arrière-plan via `FeedbackQueue`. Si Tik est down, la
        queue retry. Si la queue est pleine ou les retries épuisés,
        le payload est dropé avec log.

        Args:
            signal_id: ID du signal Tik consommé (du champ `Signal.id`).
            outcome: 'win' | 'loss' | 'breakeven' | 'not_taken'.
            trade_id: ID du trade côté Zeta (optionnel mais recommandé).
            pnl_points: PnL en points / pips (optionnel).
            pnl_pct: PnL en pourcentage (optionnel).
            duration_held_s: durée de la position en secondes (optionnel).
            exit_reason: raison de sortie (TP, SL, manual, etc.) (optionnel).

        Returns:
            True si enqueue réussi, False si queue pleine (drop).

        Raises:
            RuntimeError: si la queue feedback est désactivée
                (`enable_feedback=False` au constructeur).
        """
        if self._feedback_queue is None:
            raise RuntimeError(
                "feedback queue is disabled — pass enable_feedback=True or "
                "provide a FeedbackQueue at TikClient construction"
            )
        payload = FeedbackPayload(
            signal_id=signal_id,
            outcome=outcome,
            trade_id=trade_id,
            pnl_points=pnl_points,
            pnl_pct=pnl_pct,
            duration_held_s=duration_held_s,
            exit_reason=exit_reason,
        )
        return self._feedback_queue.submit(payload)

    @property
    def feedback_queue(self) -> FeedbackQueue | None:
        """Accès à la queue feedback (utile pour observabilité, drain explicite)."""
        return self._feedback_queue

    # ----- Hot-reload de config mutable -----

    def apply_mutable_config(self, new_config: TikConfig) -> None:
        """Applique les settings mutables d'un nouveau `TikConfig`.

        Appelé typiquement comme handler de `ConfigWatcher.on_reload(...)`.
        Settings appliqués :
        - `cache.ttl_by_horizon` : nouveau TTL pour les requêtes futures.

        Settings ignorés (loggués comme nécessitant un redémarrage) :
        - `core.base_url`, `core.timeout_s`
        - `cache.enabled`, `cache.maxsize`
        - `circuit_breaker.*`
        - `feedback.*`

        `stream.veracity_collapse_threshold` se règle directement sur le
        `TikStream` (qui a sa propre méthode mutable).
        """
        self._ttl_by_horizon = dict(new_config.cache.ttl_by_horizon)

    # ----- Streaming WebSocket (Session 2) -----

    def stream(
        self,
        *,
        entity: str | None = None,
        horizon: str | None = None,
        veracity_collapse_threshold: float = 0.5,
    ) -> TikStream:
        """Crée un `TikStream` WebSocket réutilisant l'auth + base_url du client."""
        from tik_sdk.stream import TikStream

        return TikStream(
            base_url=self._base_url,
            auth=self._auth,
            entity=entity,
            horizon=horizon,
            veracity_collapse_threshold=veracity_collapse_threshold,
        )
