"""Tests de la couche HTTP bas niveau via `httpx.MockTransport`.

Pas de dépendance externe (respx, pytest-httpx) : on utilise le transport
mock fourni nativement par httpx pour simuler les réponses du core.
"""

from collections.abc import Callable

import httpx
import pytest

from tik_sdk._http import HttpClient
from tik_sdk.auth import ApiKeyAuth
from tik_sdk.exceptions import (
    AuthError,
    NetworkError,
    NotFoundError,
    ServerError,
    TikError,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _make_client(handler: Handler) -> HttpClient:
    transport = httpx.MockTransport(handler)
    return HttpClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=transport,
    )


@pytest.mark.asyncio
async def test_get_returns_json_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/health"
        return httpx.Response(200, json={"status": "ok", "version": "0.1.0", "env": "test"})

    client = _make_client(handler)
    try:
        data = await client.get("/health", authenticated=False)
        assert data == {"status": "ok", "version": "0.1.0", "env": "test"}
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_attaches_bearer_when_authenticated() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    try:
        await client.get("/signals/latest")
    finally:
        await client.aclose()

    assert seen_headers["authorization"] == "Bearer tik_xxx"


@pytest.mark.asyncio
async def test_get_skips_auth_when_authenticated_false() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # /health ne doit jamais recevoir d'header Authorization
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"status": "ok", "version": "0.1.0", "env": "test"})

    client = _make_client(handler)
    try:
        await client.get("/health", authenticated=False)
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_get_sends_user_agent() -> None:
    seen_ua: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_ua.append(request.headers["user-agent"])
        return httpx.Response(200, json={})

    client = _make_client(handler)
    try:
        await client.get("/whatever", authenticated=False)
    finally:
        await client.aclose()

    assert seen_ua[0].startswith("tik-sdk/")


@pytest.mark.asyncio
async def test_get_passes_query_params() -> None:
    seen_qs: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_qs.append(request.url.query.decode("utf-8"))
        return httpx.Response(200, json=[])

    client = _make_client(handler)
    try:
        await client.get("/signals/latest", params={"entity": "BTC", "limit": 10})
    finally:
        await client.aclose()

    qs = seen_qs[0]
    assert "entity=BTC" in qs
    assert "limit=10" in qs


@pytest.mark.asyncio
async def test_401_raises_auth_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="invalid api key")

    client = _make_client(handler)
    try:
        with pytest.raises(AuthError):
            await client.get("/signals/latest")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_403_raises_auth_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="missing scope")

    client = _make_client(handler)
    try:
        with pytest.raises(AuthError):
            await client.get("/signals/latest")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_404_raises_not_found_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _make_client(handler)
    try:
        with pytest.raises(NotFoundError):
            await client.get("/signals/missing")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_500_raises_server_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _make_client(handler)
    try:
        with pytest.raises(ServerError):
            await client.get("/signals/latest")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_503_raises_server_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="service unavailable")

    client = _make_client(handler)
    try:
        with pytest.raises(ServerError):
            await client.get("/signals/latest")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unexpected_status_raises_tik_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(418, text="I'm a teapot")

    client = _make_client(handler)
    try:
        with pytest.raises(TikError):
            await client.get("/signals/latest")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_timeout_raises_network_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    client = _make_client(handler)
    try:
        with pytest.raises(NetworkError):
            await client.get("/signals/latest")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_transport_error_raises_network_error() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    client = _make_client(handler)
    try:
        with pytest.raises(NetworkError):
            await client.get("/signals/latest")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_base_url_trailing_slash_is_normalized() -> None:
    """`http://tik.test/` ne doit pas produire `http://tik.test//api/v1/...`."""
    captured: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json={"status": "ok", "version": "0.1.0", "env": "test"})

    transport = httpx.MockTransport(handler)
    client = HttpClient(
        base_url="http://tik.test/",
        auth=ApiKeyAuth("tik_xxx"),
        transport=transport,
    )
    try:
        await client.get("/health", authenticated=False)
    finally:
        await client.aclose()

    assert captured[0] == "http://tik.test/api/v1/health"


@pytest.mark.asyncio
async def test_async_context_manager_closes_client() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "version": "0.1.0", "env": "test"})

    transport = httpx.MockTransport(handler)
    async with HttpClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=transport,
    ) as client:
        await client.get("/health", authenticated=False)
    # Pas d'assertion : si la fermeture échoue, httpx lèverait au cleanup.
