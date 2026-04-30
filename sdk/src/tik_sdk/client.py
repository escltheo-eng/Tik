"""TikClient — client Python haut niveau pour le core Tik.

Usage minimal :

    import asyncio
    from tik_sdk import TikClient, ApiKeyAuth

    async def main():
        async with TikClient("http://localhost:8200", ApiKeyAuth("tik_xxx")) as client:
            health = await client.get_health()
            print(health.status, health.version)

            signals = await client.get_latest_signals(entity="BTC", horizon="swing", limit=5)
            for s in signals:
                print(s.id, s.direction, s.confidence, s.veracity)

    asyncio.run(main())

ADR-003 — Le client expose UNIQUEMENT des opérations de lecture.
Aucune méthode d'exécution d'ordre, aucun raccourci d'écriture vers
Zeta. Tik n'est jamais un canal d'exécution privilégié, le guard
V01-V15 reste systématique. Le `POST /feedback` (telemetry retour
asynchrone non bloquant pour Zeta) sera ajouté en Session 4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
from pydantic import TypeAdapter

from tik_sdk._http import DEFAULT_TIMEOUT, HttpClient
from tik_sdk.auth import AuthMethod
from tik_sdk.models import (
    Entity,
    Health,
    Signal,
    SourceVeracity,
    VeracityStatus,
)

if TYPE_CHECKING:
    from tik_sdk.stream import TikStream

# TypeAdapter — validation efficace des listes Pydantic
_SIGNALS_ADAPTER = TypeAdapter(list[Signal])
_ENTITIES_ADAPTER = TypeAdapter(list[Entity])
_SOURCES_ADAPTER = TypeAdapter(list[SourceVeracity])


class TikClient:
    """Client async public du SDK Tik.

    Toutes les méthodes :
    - sont async et lisent depuis le core via HTTP,
    - lèvent une exception `TikError` (ou sous-classe) en cas d'erreur,
    - retournent des modèles Pydantic typés (cf. `tik_sdk.models`).

    Utiliser en `async with` pour fermer proprement la connexion HTTP.
    """

    def __init__(
        self,
        base_url: str,
        auth: AuthMethod,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Conservés sur l'instance pour pouvoir construire un `TikStream`
        # via `client.stream(...)` qui réutilise les mêmes credentials.
        self._base_url = base_url
        self._auth = auth
        self._http = HttpClient(
            base_url=base_url,
            auth=auth,
            timeout=timeout,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> TikClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # ----- Health -----

    async def get_health(self) -> Health:
        """`GET /health` — pas d'auth requise."""
        data = await self._http.get("/health", authenticated=False)
        return Health.model_validate(data)

    # ----- Entities -----

    async def list_entities(self, *, active_only: bool = True) -> list[Entity]:
        """`GET /entities` — liste des entités observées par Tik."""
        data = await self._http.get("/entities", params={"active_only": active_only})
        return _ENTITIES_ADAPTER.validate_python(data)

    async def get_entity(self, entity_id: str) -> Entity:
        """`GET /entities/{id}`."""
        data = await self._http.get(f"/entities/{entity_id}")
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

        Les signaux expirés sont inclus : c'est au bot client de vérifier
        `expiry` et `circuit_breaker_status` avant d'agir.
        """
        params: dict[str, Any] = {"limit": limit}
        if entity is not None:
            params["entity"] = entity
        if horizon is not None:
            params["horizon"] = horizon
        data = await self._http.get("/signals/latest", params=params)
        return _SIGNALS_ADAPTER.validate_python(data)

    async def get_signal(self, signal_id: str) -> Signal:
        """`GET /signals/{id}`."""
        data = await self._http.get(f"/signals/{signal_id}")
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
        """`GET /signals` — recherche multi-filtres."""
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
        data = await self._http.get("/signals", params=params)
        return _SIGNALS_ADAPTER.validate_python(data)

    # ----- Veracity -----

    async def get_global_veracity(self) -> VeracityStatus:
        """`GET /veracity/global` — moyenne pondérée par tier des sources actives."""
        data = await self._http.get("/veracity/global")
        return VeracityStatus.model_validate(data)

    async def list_sources(self, *, active_only: bool = True) -> list[SourceVeracity]:
        """`GET /veracity/sources` — détail par source."""
        data = await self._http.get("/veracity/sources", params={"active_only": active_only})
        return _SOURCES_ADAPTER.validate_python(data)

    async def get_source(self, source_id: str) -> SourceVeracity:
        """`GET /veracity/sources/{id}`."""
        data = await self._http.get(f"/veracity/sources/{source_id}")
        return SourceVeracity.model_validate(data)

    # ----- Streaming WebSocket (Session 2) -----

    def stream(
        self,
        *,
        entity: str | None = None,
        horizon: str | None = None,
        veracity_collapse_threshold: float = 0.5,
    ) -> TikStream:
        """Crée un `TikStream` WebSocket réutilisant l'auth + base_url du client.

        Le stream n'est pas démarré ici : appeler `await stream.run()`
        pour bloquer dans la boucle d'écoute. Cf. `tik_sdk.stream`.
        """
        # Import local pour éviter le cycle (stream.py importera Signal du client.py).
        from tik_sdk.stream import TikStream

        return TikStream(
            base_url=self._base_url,
            auth=self._auth,
            entity=entity,
            horizon=horizon,
            veracity_collapse_threshold=veracity_collapse_threshold,
        )
