"""Couche HTTP bas niveau — wrapper httpx + mapping des erreurs en exceptions SDK.

Module privé (préfixe `_`) : usage interne au SDK uniquement. Les bots
clients passent toujours par `TikClient` (api/client.py).

Responsabilités :
    - Préfixer automatiquement le path par `/api/v1`
    - Injecter les en-têtes d'auth via `AuthMethod`
    - Identifier le SDK via le User-Agent
    - Convertir les codes HTTP en exceptions SDK typées
    - Convertir les erreurs réseau httpx en `NetworkError`

Pas de cache, pas de retry, pas de circuit breaker à ce stade. Ces
mécanismes seront ajoutés en Session 3 et viendront se brancher
*au-dessus* de cette couche.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from tik_sdk.auth import AuthMethod
from tik_sdk.exceptions import (
    AuthError,
    NetworkError,
    NotFoundError,
    ServerError,
    TikError,
)

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = 10.0  # secondes
USER_AGENT = "tik-sdk/0.1.0"
API_PREFIX = "/api/v1"


class HttpClient:
    """Wrapper async autour de `httpx.AsyncClient`."""

    def __init__(
        self,
        base_url: str,
        auth: AuthMethod,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # On retire le slash final pour éviter un `//api/v1/...` malformé
        normalized = base_url.rstrip("/")
        self._auth = auth
        self._client = httpx.AsyncClient(
            base_url=f"{normalized}{API_PREFIX}",
            timeout=timeout,
            transport=transport,
            headers={"User-Agent": USER_AGENT},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> HttpClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """GET sur un endpoint relatif au préfixe `/api/v1`.

        `authenticated=False` réservé à `/health` (seul endpoint public).
        """
        headers = self._auth.headers() if authenticated else {}
        try:
            response = await self._client.get(path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning("tik_sdk.http.timeout", path=path, error=str(exc))
            raise NetworkError(f"timeout calling {path}: {exc}") from exc
        except httpx.TransportError as exc:
            log.warning("tik_sdk.http.transport_error", path=path, error=str(exc))
            raise NetworkError(f"transport error calling {path}: {exc}") from exc

        return self._parse(response)

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        status = response.status_code
        if status == 200:
            return response.json()
        # Tronqué pour éviter de logger 5 MB d'HTML d'erreur en cas de proxy douteux
        body_excerpt = response.text[:200]
        if status in (401, 403):
            raise AuthError(f"{status} {response.reason_phrase}: {body_excerpt}")
        if status == 404:
            raise NotFoundError(f"404 not found: {body_excerpt}")
        if 500 <= status < 600:
            raise ServerError(f"{status} {response.reason_phrase}: {body_excerpt}")
        raise TikError(f"unexpected HTTP {status}: {body_excerpt}")
