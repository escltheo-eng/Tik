"""Tests du TikStream — combine unit (process_message) + intégration (WS server).

Pour les tests d'intégration on monte un mini serveur WS avec
`websockets.serve()` sur localhost port 0 (port libre alloué auto), on y
connecte un TikStream avec un connect_fn pointant vers ce serveur, et on
vérifie le bout-en-bout (auth params dans l'URL, parsing, dispatch hooks,
reconnexion).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import websockets
from websockets.asyncio.server import ServerConnection

from tik_sdk import ApiKeyAuth, Signal, TikStream


# ============================================================================
# Tests unitaires : _process_message + _dispatch_signal (sans WS)
# ============================================================================


def _new_stream(threshold: float = 0.5) -> TikStream:
    """Construit un TikStream sans démarrer de connexion (pour unit tests)."""
    return TikStream(
        base_url="http://localhost:8200",
        auth=ApiKeyAuth("tik_xxx"),
        veracity_collapse_threshold=threshold,
    )


@pytest.mark.asyncio
async def test_process_message_signal_triggers_on_signal(signal_payload: dict[str, Any]) -> None:
    stream = _new_stream()
    received: list[Signal] = []

    stream.on_signal(lambda s: received.append(s))

    raw = json.dumps({"type": "signal", "payload": signal_payload})
    await stream._process_message(raw)

    assert len(received) == 1
    assert isinstance(received[0], Signal)
    assert received[0].id == "sig_001"


@pytest.mark.asyncio
async def test_process_message_heartbeat_does_not_dispatch() -> None:
    stream = _new_stream()
    received: list[object] = []
    stream.on_signal(lambda s: received.append(s))

    await stream._process_message(json.dumps({"type": "heartbeat"}))

    assert received == []


@pytest.mark.asyncio
async def test_process_message_unknown_type_is_ignored() -> None:
    stream = _new_stream()
    received: list[object] = []
    stream.on_signal(lambda s: received.append(s))

    await stream._process_message(json.dumps({"type": "future_event_type"}))

    assert received == []


@pytest.mark.asyncio
async def test_process_message_bad_json_is_ignored() -> None:
    stream = _new_stream()
    # Ne doit pas lever — log warning et continue
    await stream._process_message("not-json{{{")


@pytest.mark.asyncio
async def test_process_message_signal_validation_failure_is_ignored() -> None:
    stream = _new_stream()
    received: list[object] = []
    stream.on_signal(lambda s: received.append(s))

    bad = {"type": "signal", "payload": {"id": "x"}}  # missing required fields
    await stream._process_message(json.dumps(bad))

    assert received == []


@pytest.mark.asyncio
async def test_dispatch_veracity_collapse_below_threshold(signal_payload: dict[str, Any]) -> None:
    stream = _new_stream(threshold=0.5)
    received: list[Signal] = []
    stream.on_veracity_collapse(lambda s: received.append(s))

    # Force veracity sous le seuil
    payload = {**signal_payload, "veracity": 0.3}
    await stream._process_message(json.dumps({"type": "signal", "payload": payload}))

    assert len(received) == 1
    assert received[0].veracity == 0.3


@pytest.mark.asyncio
async def test_dispatch_veracity_collapse_not_triggered_above_threshold(
    signal_payload: dict[str, Any],
) -> None:
    stream = _new_stream(threshold=0.5)
    received: list[Signal] = []
    stream.on_veracity_collapse(lambda s: received.append(s))

    # signal_payload a veracity=0.91, au-dessus du seuil
    await stream._process_message(json.dumps({"type": "signal", "payload": signal_payload}))

    assert received == []


@pytest.mark.asyncio
async def test_dispatch_crash_warning_when_advisory_flag_set(signal_payload: dict[str, Any]) -> None:
    stream = _new_stream()
    received: list[Signal] = []
    stream.on_crash_warning(lambda s: received.append(s))

    payload = {**signal_payload, "advisory": {"macro_crash_warning": True}}
    await stream._process_message(json.dumps({"type": "signal", "payload": payload}))

    assert len(received) == 1


@pytest.mark.asyncio
async def test_dispatch_crash_warning_dormant_today(signal_payload: dict[str, Any]) -> None:
    """Sans le flag advisory.macro_crash_warning, le hook ne doit pas tirer."""
    stream = _new_stream()
    received: list[Signal] = []
    stream.on_crash_warning(lambda s: received.append(s))

    await stream._process_message(json.dumps({"type": "signal", "payload": signal_payload}))

    assert received == []


@pytest.mark.asyncio
async def test_dispatch_fake_news_when_circuit_breaker_tripped(
    signal_payload: dict[str, Any],
) -> None:
    stream = _new_stream()
    received: list[Signal] = []
    stream.on_fake_news_detected(lambda s: received.append(s))

    payload = {**signal_payload, "circuit_breaker_status": "tripped"}
    await stream._process_message(json.dumps({"type": "signal", "payload": payload}))

    assert len(received) == 1


@pytest.mark.asyncio
async def test_dispatch_all_hooks_in_one_signal(signal_payload: dict[str, Any]) -> None:
    """Un signal peut déclencher plusieurs hooks à la fois."""
    stream = _new_stream(threshold=0.5)
    seen: list[str] = []

    stream.on_signal(lambda _s: seen.append("signal"))
    stream.on_crash_warning(lambda _s: seen.append("crash"))
    stream.on_fake_news_detected(lambda _s: seen.append("fake_news"))
    stream.on_veracity_collapse(lambda _s: seen.append("collapse"))

    payload = {
        **signal_payload,
        "veracity": 0.2,
        "circuit_breaker_status": "tripped",
        "advisory": {"macro_crash_warning": True},
    }
    await stream._process_message(json.dumps({"type": "signal", "payload": payload}))

    assert seen == ["signal", "crash", "fake_news", "collapse"]


@pytest.mark.asyncio
async def test_handler_exception_does_not_break_dispatch(signal_payload: dict[str, Any]) -> None:
    """Crash d'un handler n'empêche pas les autres handlers du même événement."""
    stream = _new_stream()
    seen: list[str] = []

    def boom(_s: Signal) -> None:
        seen.append("boom")
        raise RuntimeError("oops")

    def survivor(_s: Signal) -> None:
        seen.append("survivor")

    stream.on_signal(boom)
    stream.on_signal(survivor)

    await stream._process_message(json.dumps({"type": "signal", "payload": signal_payload}))

    assert seen == ["boom", "survivor"]


def test_safe_url_masks_api_key() -> None:
    stream = _new_stream()
    safe = stream._safe_url()
    assert "tik_xxx" not in safe
    assert "api_key=***" in safe


def test_safe_url_preserves_other_params() -> None:
    stream = TikStream(
        base_url="http://localhost:8200",
        auth=ApiKeyAuth("tik_xxx"),
        entity="BTC",
        horizon="swing",
    )
    safe = stream._safe_url()
    assert "tik_xxx" not in safe
    assert "entity=BTC" in safe
    assert "horizon=swing" in safe


def test_constructor_rejects_auth_without_api_key_query_param() -> None:
    """Une AuthMethod custom dont query_params() ne renvoie pas d'api_key
    doit être rejetée explicitement (sinon erreur cryptique au handshake).
    """
    from tik_sdk.auth import AuthMethod

    class HeaderOnlyAuth(AuthMethod):
        def headers(self) -> dict[str, str]:
            return {"X-Custom": "abc"}

    with pytest.raises(ValueError, match="api_key"):
        TikStream(base_url="http://localhost:8200", auth=HeaderOnlyAuth())


# ============================================================================
# Tests d'intégration : vrai serveur WS sur localhost
# ============================================================================


@asynccontextmanager
async def _ws_server(handler: Any) -> AsyncIterator[tuple[str, Any]]:
    """Lance un serveur WS éphémère sur localhost port 0 (auto-allocated)."""
    server = await websockets.serve(handler, "127.0.0.1", 0)
    sock = next(iter(server.sockets))
    host, port = sock.getsockname()[:2]
    base_url = f"http://{host}:{port}"
    try:
        yield base_url, server
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_integration_receives_signal_via_ws(signal_payload: dict[str, Any]) -> None:
    """Bout-en-bout : SDK se connecte, serveur envoie 1 signal, hook tire."""
    received: list[Signal] = []

    async def server_handler(ws: ServerConnection) -> None:
        # On vérifie que le path est bon ET que api_key arrive en query
        path = ws.request.path
        parsed = urlparse(path)
        assert parsed.path == "/api/v1/ws/signals"
        params = parse_qs(parsed.query)
        assert params["api_key"] == ["tik_test"]
        # On envoie un signal puis on ferme proprement
        await ws.send(json.dumps({"type": "signal", "payload": signal_payload}))

    async with _ws_server(server_handler) as (base_url, _):
        stream = TikStream(base_url=base_url, auth=ApiKeyAuth("tik_test"))
        stream.on_signal(lambda s: received.append(s))

        run_task = asyncio.create_task(stream.run())
        try:
            # Attend la réception puis stop
            for _ in range(50):  # 5 s max
                if received:
                    break
                await asyncio.sleep(0.1)
            await stream.stop()
            await asyncio.wait_for(run_task, timeout=2.0)
        finally:
            if not run_task.done():
                run_task.cancel()
                with pytest.raises((asyncio.CancelledError, BaseException)):
                    await run_task

    assert len(received) == 1
    assert received[0].id == signal_payload["id"]


@pytest.mark.asyncio
async def test_integration_passes_entity_and_horizon_filters(
    signal_payload: dict[str, Any],
) -> None:
    seen_query: dict[str, list[str]] = {}

    async def server_handler(ws: ServerConnection) -> None:
        seen_query.update(parse_qs(urlparse(ws.request.path).query))
        await ws.send(json.dumps({"type": "signal", "payload": signal_payload}))

    received: list[Signal] = []

    async with _ws_server(server_handler) as (base_url, _):
        stream = TikStream(
            base_url=base_url,
            auth=ApiKeyAuth("tik_test"),
            entity="BTC",
            horizon="swing",
        )
        stream.on_signal(lambda s: received.append(s))

        run_task = asyncio.create_task(stream.run())
        try:
            for _ in range(50):
                if received:
                    break
                await asyncio.sleep(0.1)
            await stream.stop()
            await asyncio.wait_for(run_task, timeout=2.0)
        finally:
            if not run_task.done():
                run_task.cancel()

    assert seen_query["api_key"] == ["tik_test"]
    assert seen_query["entity"] == ["BTC"]
    assert seen_query["horizon"] == ["swing"]


@pytest.mark.asyncio
async def test_integration_heartbeat_does_not_trigger_signal_hook() -> None:
    received: list[object] = []

    async def server_handler(ws: ServerConnection) -> None:
        await ws.send(json.dumps({"type": "heartbeat"}))
        await ws.send(json.dumps({"type": "heartbeat"}))
        # Garde la connexion ouverte un instant pour éviter un disconnect immédiat
        await asyncio.sleep(0.2)

    async with _ws_server(server_handler) as (base_url, _):
        stream = TikStream(base_url=base_url, auth=ApiKeyAuth("tik_test"))
        stream.on_signal(lambda s: received.append(s))

        run_task = asyncio.create_task(stream.run())
        try:
            await stream.wait_connected(timeout=2.0)
            await asyncio.sleep(0.4)  # Laisse passer les heartbeats
            await stream.stop()
            await asyncio.wait_for(run_task, timeout=2.0)
        finally:
            if not run_task.done():
                run_task.cancel()

    assert received == []


@pytest.mark.asyncio
async def test_integration_reconnects_after_server_drop(signal_payload: dict[str, Any]) -> None:
    """On envoie un signal, on coupe, le serveur se relance, on en envoie un 2e."""
    received: list[Signal] = []
    connection_count = 0

    async def server_handler(ws: ServerConnection) -> None:
        nonlocal connection_count
        connection_count += 1
        # Adapte le payload pour différencier les 2 signaux
        payload = {**signal_payload, "id": f"sig_{connection_count}"}
        await ws.send(json.dumps({"type": "signal", "payload": payload}))
        # Premier appel : on ferme tout de suite pour forcer un reconnect
        if connection_count == 1:
            await ws.close()

    async with _ws_server(server_handler) as (base_url, _):
        stream = TikStream(base_url=base_url, auth=ApiKeyAuth("tik_test"))
        stream.on_signal(lambda s: received.append(s))

        run_task = asyncio.create_task(stream.run())
        try:
            # Attend la 2e reconnexion (+ 1.5 s de backoff initial)
            for _ in range(60):  # 6 s max
                if connection_count >= 2 and len(received) >= 2:
                    break
                await asyncio.sleep(0.1)
            await stream.stop()
            await asyncio.wait_for(run_task, timeout=3.0)
        finally:
            if not run_task.done():
                run_task.cancel()

    assert connection_count >= 2
    assert len(received) >= 2
    assert received[0].id == "sig_1"
    assert received[1].id == "sig_2"


@pytest.mark.asyncio
async def test_integration_stop_during_idle_returns_promptly() -> None:
    """Si on stop() pendant que la connexion est idle, run() doit sortir vite."""

    async def server_handler(ws: ServerConnection) -> None:
        # Reste connecté en silence
        await asyncio.sleep(10)

    async with _ws_server(server_handler) as (base_url, _):
        stream = TikStream(base_url=base_url, auth=ApiKeyAuth("tik_test"))

        run_task = asyncio.create_task(stream.run())
        try:
            await stream.wait_connected(timeout=2.0)
            await stream.stop()
            # run() doit sortir rapidement après stop()
            await asyncio.wait_for(run_task, timeout=2.0)
        finally:
            if not run_task.done():
                run_task.cancel()
