"""Couche HTTP bas niveau — wrapper httpx + cache + circuit breaker.

Module privé (préfixe `_`) : usage interne au SDK uniquement. Les bots
clients passent toujours par `TikClient` (api/client.py).

Responsabilités :
    - Préfixer automatiquement le path par `/api/v1`
    - Injecter les en-têtes d'auth via `AuthMethod`
    - Identifier le SDK via le User-Agent
    - Convertir les codes HTTP en exceptions SDK typées
    - Convertir les erreurs réseau httpx en `NetworkError`
    - **Cache local opt-in** (Session 3) : cache hit = pas de HTTP
    - **Circuit breaker LOCAL opt-in** (Session 3) : court-circuite si le
      core est détecté down

Flow d'une requête :

    1. Cache hit (entrée fraîche, TTL valide) → return immédiatement.
       (Pas de HTTP, pas de breaker — la donnée fraîche est toujours préférée.)
    2. Cache miss → check circuit breaker.
       - Si open → CircuitBreakerOpen (pas de HTTP).
       - Sinon → on tente HTTP.
    3. Tentative HTTP :
       - Succès → record_success, cache.set si ttl > 0, retour.
       - NetworkError (timeout, transport) → record_failure, raise.
       - ServerError (5xx) → record_failure, raise (le core a un souci).
       - AuthError (401/403), NotFoundError (404) : raise sans toucher au
         breaker (problème de requête, pas de disponibilité).

Note sur la sémantique du fallback : tant que la TTL du cache est valide,
le cache sert même si le core est down. Pour étendre la fenêtre offline,
augmenter le TTL des endpoints critiques. La gestion de cache "stale
servable" (TTL expirée mais retenue en RAM) est laissée pour plus tard.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from tik_sdk.auth import AuthMethod
from tik_sdk.cache import Cache, NoCache, make_cache_key
from tik_sdk.circuit_breaker import CircuitBreaker
from tik_sdk.exceptions import (
    AuthError,
    CircuitBreakerOpen,
    NetworkError,
    NotFoundError,
    ServerError,
    TikError,
)

log = structlog.get_logger(__name__)

DEFAULT_TIMEOUT = 10.0  # secondes
USER_AGENT = "tik-sdk/0.5.0"
API_PREFIX = "/api/v1"


class HttpClient:
    """Wrapper async autour de `httpx.AsyncClient` avec cache + circuit breaker."""

    def __init__(
        self,
        base_url: str,
        auth: AuthMethod,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        cache: Cache | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        # On retire le slash final pour éviter un `//api/v1/...` malformé
        normalized = base_url.rstrip("/")
        self._auth = auth
        # Défaut no-op : on peut toujours appeler get/set sans vérifier
        # `if cache is not None`. Aucun coût quand non configuré.
        self._cache: Cache = cache if cache is not None else NoCache()
        self._circuit_breaker: CircuitBreaker | None = circuit_breaker
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
        cache_ttl_s: int = 0,
    ) -> Any:
        """GET sur un endpoint relatif au préfixe `/api/v1`.

        Args:
            path: chemin relatif au préfixe `/api/v1` (ex `/signals/latest`).
            params: query params HTTP. Aussi utilisés comme part de la clé cache.
            authenticated: False pour `/health` uniquement.
            cache_ttl_s: durée de vie en cache en secondes. `0` ou négatif =
                ne pas mettre en cache (mais on tentera quand même la lecture
                au cas où une entrée existerait déjà — défensif).
        """
        cache_key = make_cache_key("GET", path, params)

        # 1. Cache hit (donnée fraîche) → retourne sans HTTP ni breaker
        cached = await self._cache.get(cache_key)
        if cached is not None:
            log.debug("tik_sdk.http.cache_hit", key=cache_key)
            return cached

        # 2. Cache miss → check circuit breaker
        if self._circuit_breaker is not None and not self._circuit_breaker.can_attempt():
            log.warning(
                "tik_sdk.http.circuit_open_no_cache",
                key=cache_key,
            )
            raise CircuitBreakerOpen(
                f"circuit breaker open and no cache entry for {cache_key}"
            )

        # 3. Tente HTTP
        headers = self._auth.headers() if authenticated else {}
        try:
            response = await self._client.get(path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning("tik_sdk.http.timeout", path=path, error=str(exc))
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise NetworkError(f"timeout calling {path}: {exc}") from exc
        except httpx.TransportError as exc:
            log.warning("tik_sdk.http.transport_error", path=path, error=str(exc))
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise NetworkError(f"transport error calling {path}: {exc}") from exc

        # 4. Parse + record breaker outcome.
        # IMPORTANT — l'ordre des except est crucial : ServerError est
        # une sous-classe de TikError, donc on doit la matcher AVANT
        # `except TikError` (sinon le breaker n'enregistre rien sur 5xx).
        try:
            data = self._parse(response)
        except ServerError:
            # 5xx → le core a un souci de disponibilité
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise
        except (AuthError, NotFoundError):
            # 4xx → problème de requête, pas de disponibilité. N'affecte pas le breaker.
            raise
        except TikError:
            # Cas inattendus (3xx redirects ratés, codes exotiques) — n'affecte pas le breaker.
            raise

        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()
        if cache_ttl_s > 0:
            await self._cache.set(cache_key, data, ttl_s=cache_ttl_s)
        return data

    async def post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        authenticated: bool = True,
    ) -> Any:
        """POST sur un endpoint relatif au préfixe `/api/v1`.

        Volontairement **sans cache et sans circuit breaker** :
        - Pas de cache : POST est mutating, le mettre en cache n'a pas de sens.
        - Pas de circuit breaker : le SDK utilise POST pour la telemetry
          (`/feedback`), gérée par une queue async avec son propre retry. Si
          le breaker fermait sur les POST échoués, il bloquerait aussi les
          GET de signaux — ce qu'on ne veut pas.
        """
        headers = self._auth.headers() if authenticated else {}
        try:
            response = await self._client.post(path, json=json, headers=headers)
        except httpx.TimeoutException as exc:
            log.warning("tik_sdk.http.post_timeout", path=path, error=str(exc))
            raise NetworkError(f"timeout calling {path}: {exc}") from exc
        except httpx.TransportError as exc:
            log.warning("tik_sdk.http.post_transport_error", path=path, error=str(exc))
            raise NetworkError(f"transport error calling {path}: {exc}") from exc

        return self._parse(response, expected_status=(200, 201))

    @staticmethod
    def _parse(response: httpx.Response, *, expected_status: tuple[int, ...] = (200,)) -> Any:
        status = response.status_code
        if status in expected_status:
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
