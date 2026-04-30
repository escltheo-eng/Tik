"""Tests du client haut niveau — vérifie le mapping JSON → modèles Pydantic."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tik_sdk import ApiKeyAuth, TikClient
from tik_sdk.models import Entity, Health, Signal, SourceVeracity, VeracityStatus

Handler = Callable[[httpx.Request], httpx.Response]


def _client_with(handler: Handler) -> TikClient:
    transport = httpx.MockTransport(handler)
    return TikClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=transport,
    )


@pytest.mark.asyncio
async def test_get_health_returns_health_model() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "version": "0.2.3", "env": "dev"})

    async with _client_with(handler) as client:
        h = await client.get_health()

    assert isinstance(h, Health)
    assert h.status == "ok"
    assert h.version == "0.2.3"
    assert h.env == "dev"


@pytest.mark.asyncio
async def test_list_entities_returns_list_of_entity() -> None:
    payload: list[dict[str, Any]] = [
        {
            "id": "BTC",
            "domain": "crypto",
            "namespace": "spot",
            "metadata_json": {"exchange": "binance"},
            "active": True,
            "created_at": "2026-04-20T00:00:00",
            "updated_at": "2026-04-20T00:00:00",
        }
    ]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with _client_with(handler) as client:
        entities = await client.list_entities()

    assert len(entities) == 1
    assert isinstance(entities[0], Entity)
    assert entities[0].id == "BTC"
    assert entities[0].metadata_json == {"exchange": "binance"}


@pytest.mark.asyncio
async def test_get_entity_calls_correct_path() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(
            200,
            json={
                "id": "GOLD",
                "domain": "commodity",
                "namespace": "spot",
                "metadata_json": {},
                "active": True,
                "created_at": "2026-04-20T00:00:00",
                "updated_at": "2026-04-20T00:00:00",
            },
        )

    async with _client_with(handler) as client:
        e = await client.get_entity("GOLD")

    assert paths[0] == "/api/v1/entities/GOLD"
    assert e.id == "GOLD"


@pytest.mark.asyncio
async def test_get_latest_signals_passes_filters(signal_payload: dict[str, Any]) -> None:
    seen_qs: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_qs.append(req.url.query.decode("utf-8"))
        return httpx.Response(200, json=[signal_payload])

    async with _client_with(handler) as client:
        signals = await client.get_latest_signals(entity="BTC", horizon="swing", limit=5)

    assert len(signals) == 1
    assert isinstance(signals[0], Signal)
    qs = seen_qs[0]
    assert "entity=BTC" in qs
    assert "horizon=swing" in qs
    assert "limit=5" in qs


@pytest.mark.asyncio
async def test_get_latest_signals_skips_none_filters(signal_payload: dict[str, Any]) -> None:
    """Les filtres None ne doivent pas être envoyés à l'API."""
    seen_qs: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_qs.append(req.url.query.decode("utf-8"))
        return httpx.Response(200, json=[signal_payload])

    async with _client_with(handler) as client:
        await client.get_latest_signals(limit=10)

    qs = seen_qs[0]
    assert "entity=" not in qs
    assert "horizon=" not in qs
    assert "limit=10" in qs


@pytest.mark.asyncio
async def test_get_signal_by_id(signal_payload: dict[str, Any]) -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(200, json=signal_payload)

    async with _client_with(handler) as client:
        sig = await client.get_signal("sig_001")

    assert paths[0] == "/api/v1/signals/sig_001"
    assert sig.id == "sig_001"
    assert sig.entity_id == "BTC"
    assert sig.confidence == 0.78
    assert len(sig.counter_scenarios) == 2  # paranoïa contrôlée respectée


@pytest.mark.asyncio
async def test_search_signals_default_params(signal_payload: dict[str, Any]) -> None:
    seen_qs: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_qs.append(req.url.query.decode("utf-8"))
        return httpx.Response(200, json=[signal_payload])

    async with _client_with(handler) as client:
        await client.search_signals()

    qs = seen_qs[0]
    assert "min_confidence=0.0" in qs
    assert "min_veracity=0.0" in qs
    assert "since_hours=24" in qs
    assert "limit=100" in qs


@pytest.mark.asyncio
async def test_search_signals_with_all_filters(signal_payload: dict[str, Any]) -> None:
    seen_qs: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_qs.append(req.url.query.decode("utf-8"))
        return httpx.Response(200, json=[signal_payload])

    async with _client_with(handler) as client:
        await client.search_signals(
            entity="BTC",
            horizon="flash",
            direction="long",
            min_confidence=0.5,
            min_veracity=0.7,
            since_hours=48,
            limit=50,
        )

    qs = seen_qs[0]
    assert "entity=BTC" in qs
    assert "horizon=flash" in qs
    assert "direction=long" in qs
    assert "min_confidence=0.5" in qs
    assert "min_veracity=0.7" in qs
    assert "since_hours=48" in qs
    assert "limit=50" in qs


@pytest.mark.asyncio
async def test_get_global_veracity() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "global_veracity": 0.83,
                "sources_count_active": 7,
                "last_computed": "2026-04-30T12:00:00",
                "status": "healthy",
            },
        )

    async with _client_with(handler) as client:
        v = await client.get_global_veracity()

    assert isinstance(v, VeracityStatus)
    assert v.status == "healthy"
    assert v.global_veracity == 0.83


@pytest.mark.asyncio
async def test_list_sources() -> None:
    payload = [
        {
            "id": "binance_klines",
            "name": "Binance Klines",
            "category": "market",
            "current_veracity": 0.9,
            "tier": 1,
            "active": True,
        }
    ]

    def handler(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with _client_with(handler) as client:
        sources = await client.list_sources()

    assert len(sources) == 1
    assert isinstance(sources[0], SourceVeracity)
    assert sources[0].tier == 1


@pytest.mark.asyncio
async def test_get_source_calls_correct_path() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(
            200,
            json={
                "id": "fred_dtwexbgs",
                "name": "FRED DXY",
                "category": "macro",
                "current_veracity": 0.85,
                "tier": 1,
                "active": True,
            },
        )

    async with _client_with(handler) as client:
        s = await client.get_source("fred_dtwexbgs")

    assert paths[0] == "/api/v1/veracity/sources/fred_dtwexbgs"
    assert s.id == "fred_dtwexbgs"


# ----- Garde-fou ADR-003 : aucune méthode d'exécution ne doit fuiter -----


def test_client_does_not_expose_execution_methods() -> None:
    """ADR-003 — Le SDK ne doit JAMAIS exposer de méthode qui placerait
    un ordre, contournerait le guard V01-V15, ou enverrait un signal
    forcé à Zeta. Garde-fou automatique au cas où une session future
    introduirait par mégarde une telle méthode.
    """
    forbidden = {
        "place_order",
        "send_order",
        "submit_order",
        "execute",
        "execute_signal",
        "force_signal",
        "trade",
        "buy",
        "sell",
        "open_position",
        "close_position",
        "bypass_guard",
    }
    public_methods = {m for m in dir(TikClient) if not m.startswith("_")}
    intersection = forbidden & public_methods
    assert not intersection, (
        f"TikClient ne doit exposer aucune méthode d'exécution (ADR-003). "
        f"Méthodes interdites trouvées : {intersection}"
    )
