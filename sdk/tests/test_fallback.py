"""Tests d'intégration HTTP + cache + circuit breaker.

Vérifie le comportement du SDK quand le core tombe : fallback cache,
ouverture du circuit breaker, retour à la normale après reprise.
"""

from collections.abc import Callable

import httpx
import pytest

from tik_sdk import (
    ApiKeyAuth,
    CircuitBreaker,
    CircuitBreakerOpen,
    InMemoryCache,
    NetworkError,
    NoCache,
    TikClient,
)
from tik_sdk._http import HttpClient

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


def _http_with(
    handler: Handler,
    *,
    cache: InMemoryCache | None = None,
    cb: CircuitBreaker | None = None,
) -> HttpClient:
    return HttpClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
        cache=cache,
        circuit_breaker=cb,
    )


# ============================================================================
# Cache hit / miss
# ============================================================================


@pytest.mark.asyncio
async def test_cache_hit_skips_http_call() -> None:
    call_count = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"value": 42})

    cache = InMemoryCache()
    http = _http_with(handler, cache=cache)
    try:
        # Premier appel : HTTP
        data1 = await http.get("/x", cache_ttl_s=60)
        # Deuxième appel : cache
        data2 = await http.get("/x", cache_ttl_s=60)
    finally:
        await http.aclose()

    assert data1 == data2 == {"value": 42}
    assert call_count == 1  # un seul appel HTTP


@pytest.mark.asyncio
async def test_ttl_zero_does_not_cache() -> None:
    """Avec ttl=0 (ex: /health), chaque appel doit aller au HTTP."""
    call_count = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"status": "ok"})

    http = _http_with(handler, cache=InMemoryCache())
    try:
        await http.get("/health", cache_ttl_s=0)
        await http.get("/health", cache_ttl_s=0)
    finally:
        await http.aclose()

    assert call_count == 2


@pytest.mark.asyncio
async def test_cache_separates_keys_by_params() -> None:
    """Deux requêtes avec params différents → deux entrées distinctes."""
    call_count = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"q": req.url.query.decode()})

    http = _http_with(handler, cache=InMemoryCache())
    try:
        await http.get("/x", params={"entity": "BTC"}, cache_ttl_s=60)
        await http.get("/x", params={"entity": "GOLD"}, cache_ttl_s=60)
    finally:
        await http.aclose()

    assert call_count == 2  # cache miss sur l'autre entity


# ============================================================================
# Fallback cache sur NetworkError
# ============================================================================


@pytest.mark.asyncio
async def test_network_error_returns_cached_value_when_available() -> None:
    """Cas critique ADR-003 : Tik est down, Zeta continue avec le cache."""
    succeed = True

    def handler(_req: httpx.Request) -> httpx.Response:
        if succeed:
            return httpx.Response(200, json={"signal": "fresh"})
        raise httpx.ConnectError("connection refused")

    http = _http_with(handler, cache=InMemoryCache())
    try:
        # Premier appel OK → met en cache
        data = await http.get("/signals/latest", cache_ttl_s=300)
        assert data == {"signal": "fresh"}

        # Le core tombe
        succeed = False

        # Deuxième appel : NetworkError MAIS le cache sauve
        data = await http.get("/signals/latest", cache_ttl_s=300)
        assert data == {"signal": "fresh"}  # ← sert depuis le cache
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_network_error_propagates_when_no_cache_entry() -> None:
    """Si pas de cache hit, l'erreur réseau remonte."""

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    http = _http_with(handler, cache=InMemoryCache())
    try:
        with pytest.raises(NetworkError):
            await http.get("/signals/latest", cache_ttl_s=300)
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_network_error_propagates_without_cache_configured() -> None:
    """Sans cache, comportement identique à avant Session 3."""

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    http = _http_with(handler)  # pas de cache
    try:
        with pytest.raises(NetworkError):
            await http.get("/x", cache_ttl_s=60)
    finally:
        await http.aclose()


# ============================================================================
# Circuit breaker
# ============================================================================


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_threshold_failures() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    cb = CircuitBreaker(failure_threshold=3, reset_timeout_s=30)
    http = _http_with(handler, cb=cb)
    try:
        # 3 échecs consécutifs
        for _ in range(3):
            with pytest.raises(NetworkError):
                await http.get("/x", cache_ttl_s=0)
        assert cb.state == "open"

        # 4e tentative : circuit ouvert + pas de cache → CircuitBreakerOpen
        with pytest.raises(CircuitBreakerOpen):
            await http.get("/x", cache_ttl_s=0)
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_circuit_open_still_serves_fresh_cache() -> None:
    """Quand le breaker est ouvert, un cache hit (TTL valide) est quand même servi.

    Scénario réaliste : Zeta a interrogé `/signals/latest` (cache populé).
    Plus tard, le core devient injoignable, plein d'autres appels échouent
    et ouvrent le breaker. Quand Zeta redemande `/signals/latest`, le SDK
    sert le cache court-circuit avant même de regarder le breaker — c'est
    exactement ce qu'on veut pour ADR-003.
    """
    state = {"down": False, "calls": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["down"]:
            raise httpx.ConnectError("down")
        if req.url.path.endswith("/signals/latest"):
            return httpx.Response(200, json={"signal": "fresh"})
        return httpx.Response(200, json={"other": "data"})

    cb = CircuitBreaker(failure_threshold=2, reset_timeout_s=30)
    http = _http_with(handler, cache=InMemoryCache(), cb=cb)
    try:
        # 1. Populate cache avec /signals/latest
        await http.get("/signals/latest", cache_ttl_s=300)
        assert state["calls"] == 1

        # 2. Le core tombe
        state["down"] = True

        # 3. 2 échecs sur /other (pas en cache) → circuit open
        for _ in range(2):
            with pytest.raises(NetworkError):
                await http.get("/other", cache_ttl_s=0)
        assert cb.state == "open"

        # 4. Re-demande de /signals/latest : cache hit court-circuit le breaker
        calls_before = state["calls"]
        data = await http.get("/signals/latest", cache_ttl_s=300)
        assert data == {"signal": "fresh"}
        # Pas de nouvel appel HTTP : le cache a servi
        assert state["calls"] == calls_before
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_circuit_open_no_cache_raises_circuit_open() -> None:
    """Sans cache et circuit ouvert : CircuitBreakerOpen, pas de HTTP."""

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    cb = CircuitBreaker(failure_threshold=2, reset_timeout_s=30)
    http = _http_with(handler, cb=cb)  # pas de cache
    try:
        for _ in range(2):
            with pytest.raises(NetworkError):
                await http.get("/x", cache_ttl_s=0)
        assert cb.state == "open"

        # 3e tentative : pas de HTTP du tout, CircuitBreakerOpen direct
        with pytest.raises(CircuitBreakerOpen):
            await http.get("/x", cache_ttl_s=0)
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_circuit_breaker_recovers_after_reset_timeout() -> None:
    """Après le reset_timeout, le circuit retente et peut se refermer."""
    state = {"down": True}

    def handler(_req: httpx.Request) -> httpx.Response:
        if state["down"]:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"signal": "back"})

    clock = FakeClock()
    cb = CircuitBreaker(failure_threshold=2, reset_timeout_s=10.0, time_fn=clock)
    http = _http_with(handler, cb=cb)
    try:
        # 2 échecs → open
        for _ in range(2):
            with pytest.raises(NetworkError):
                await http.get("/x", cache_ttl_s=0)
        assert cb.state == "open"

        # Le core revient
        state["down"] = False

        # Avant reset_timeout : circuit toujours open
        clock.advance(5.0)
        with pytest.raises(CircuitBreakerOpen):
            await http.get("/x", cache_ttl_s=0)

        # Après reset_timeout : half_open → tente la requête → succès → closed
        clock.advance(5.0)
        data = await http.get("/x", cache_ttl_s=0)
        assert data == {"signal": "back"}
        assert cb.state == "closed"
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_5xx_counts_as_failure_for_circuit_breaker() -> None:
    """Un 500 côté core indique aussi un problème de disponibilité."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    from tik_sdk.exceptions import ServerError

    cb = CircuitBreaker(failure_threshold=2, reset_timeout_s=30)
    http = _http_with(handler, cb=cb)
    try:
        for _ in range(2):
            with pytest.raises(ServerError):
                await http.get("/x", cache_ttl_s=0)
        assert cb.state == "open"
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_4xx_does_not_trigger_circuit_breaker() -> None:
    """404, 401, 403 = problème de requête, pas de disponibilité du core."""

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    from tik_sdk.exceptions import NotFoundError

    cb = CircuitBreaker(failure_threshold=2, reset_timeout_s=30)
    http = _http_with(handler, cb=cb)
    try:
        for _ in range(5):
            with pytest.raises(NotFoundError):
                await http.get("/x", cache_ttl_s=0)
        # 5 × 404 ne doivent jamais ouvrir le breaker
        assert cb.state == "closed"
        assert cb.consecutive_failures == 0
    finally:
        await http.aclose()


# ============================================================================
# Tests via TikClient (vérifie le câblage end-to-end)
# ============================================================================


@pytest.mark.asyncio
async def test_tikclient_with_cache_and_breaker_reuses_cache_on_failure(
    signal_payload: dict,
) -> None:
    """End-to-end : TikClient avec cache + breaker, NetworkError → cache."""
    succeed = True

    def handler(req: httpx.Request) -> httpx.Response:
        if succeed:
            return httpx.Response(200, json=[signal_payload])
        raise httpx.ConnectError("down")

    client = TikClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
        cache=InMemoryCache(),
        circuit_breaker=CircuitBreaker(failure_threshold=10, reset_timeout_s=30),
    )
    async with client:
        # Premier appel : OK + mise en cache
        signals = await client.get_latest_signals(entity="BTC", horizon="swing")
        assert len(signals) == 1
        assert signals[0].id == signal_payload["id"]

        # Le core tombe
        succeed = False

        # Deuxième appel : NetworkError mais cache → retourne le même Pydantic
        signals = await client.get_latest_signals(entity="BTC", horizon="swing")
        assert signals[0].id == signal_payload["id"]


@pytest.mark.asyncio
async def test_tikclient_default_no_cache_no_breaker_unchanged_behavior() -> None:
    """Sans cache ni breaker : SDK se comporte comme avant Session 3."""

    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = TikClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
    )
    async with client:
        with pytest.raises(NetworkError):
            await client.get_latest_signals()


@pytest.mark.asyncio
async def test_tikclient_health_never_cached() -> None:
    """`/health` doit aller au HTTP à chaque appel, même avec cache."""
    call_count = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"status": "ok", "version": "0.3.0", "env": "test"})

    client = TikClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
        cache=InMemoryCache(),
    )
    async with client:
        await client.get_health()
        await client.get_health()
        await client.get_health()

    assert call_count == 3


@pytest.mark.asyncio
async def test_tikclient_ttl_per_horizon(signal_payload: dict) -> None:
    """Chaque horizon utilise son propre TTL — observable via le call_count."""
    call_count = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=[signal_payload])

    client = TikClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
        cache=InMemoryCache(),
    )
    async with client:
        # 1er appel pour swing
        await client.get_latest_signals(entity="BTC", horizon="swing")
        # 2e appel identique → cache hit
        await client.get_latest_signals(entity="BTC", horizon="swing")
        assert call_count == 1

        # Appel pour flash → clé cache différente (params différents) → HTTP
        await client.get_latest_signals(entity="BTC", horizon="flash")
        assert call_count == 2


def test_nocache_is_a_cache() -> None:
    """NoCache implémente bien l'interface Cache (smoke test)."""
    from tik_sdk.cache import Cache

    assert isinstance(NoCache(), Cache)
    assert isinstance(InMemoryCache(), Cache)
