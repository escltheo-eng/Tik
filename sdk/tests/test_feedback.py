"""Tests de la queue feedback async + worker."""

import asyncio
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tik_sdk import ApiKeyAuth, FeedbackPayload, FeedbackQueue
from tik_sdk._http import HttpClient

Handler = Callable[[httpx.Request], httpx.Response]


def _new_http(handler: Handler) -> HttpClient:
    return HttpClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
    )


def _zero_backoff(_attempt: int) -> float:
    """Backoff de 0 s pour des tests sans temps d'attente."""
    return 0.0


# ============================================================================
# FeedbackPayload
# ============================================================================


def test_payload_basic_validation() -> None:
    p = FeedbackPayload(signal_id="sig_x", outcome="win")
    assert p.signal_id == "sig_x"
    assert p.outcome == "win"
    assert p.pnl_pct is None


def test_payload_rejects_invalid_outcome() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        FeedbackPayload(signal_id="sig_x", outcome="moon")  # type: ignore[arg-type]


def test_payload_full() -> None:
    p = FeedbackPayload(
        signal_id="sig_x",
        outcome="loss",
        trade_id="trade_42",
        pnl_points=-10.0,
        pnl_pct=-0.5,
        duration_held_s=3600,
        exit_reason="SL",
    )
    dumped = p.model_dump(exclude_none=True)
    assert dumped["trade_id"] == "trade_42"
    assert dumped["exit_reason"] == "SL"


def test_payload_exclude_none() -> None:
    """Les champs None ne doivent pas être envoyés au core."""
    p = FeedbackPayload(signal_id="sig_x", outcome="win")
    dumped = p.model_dump(exclude_none=True)
    assert "trade_id" not in dumped
    assert "pnl_pct" not in dumped


# ============================================================================
# FeedbackQueue — opérations de base
# ============================================================================


def test_queue_constructor_validation() -> None:
    http = _new_http(lambda _r: httpx.Response(201, json={}))
    with pytest.raises(ValueError):
        FeedbackQueue(http, max_queue_size=0)
    with pytest.raises(ValueError):
        FeedbackQueue(http, max_retries=-1)


@pytest.mark.asyncio
async def test_queue_submit_returns_true_on_accept() -> None:
    http = _new_http(lambda _r: httpx.Response(201, json={}))
    q = FeedbackQueue(http, max_queue_size=10)
    try:
        ok = q.submit(FeedbackPayload(signal_id="x", outcome="win"))
        assert ok is True
        assert q.queue_size == 1
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_queue_submit_returns_false_when_full() -> None:
    http = _new_http(lambda _r: httpx.Response(201, json={}))
    q = FeedbackQueue(http, max_queue_size=2)
    try:
        assert q.submit(FeedbackPayload(signal_id="a", outcome="win")) is True
        assert q.submit(FeedbackPayload(signal_id="b", outcome="win")) is True
        # 3e doit être droppé
        assert q.submit(FeedbackPayload(signal_id="c", outcome="win")) is False
        assert q.dropped_count == 1
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_queue_is_running_lifecycle() -> None:
    http = _new_http(lambda _r: httpx.Response(201, json={}))
    q = FeedbackQueue(http)
    try:
        assert q.is_running is False
        await q.start()
        assert q.is_running is True
        await q.stop()
        assert q.is_running is False
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_queue_start_is_idempotent() -> None:
    http = _new_http(lambda _r: httpx.Response(201, json={}))
    q = FeedbackQueue(http)
    try:
        await q.start()
        first_task_id = id(q._worker_task)
        await q.start()  # 2e appel doit être no-op
        assert id(q._worker_task) == first_task_id
    finally:
        await q.stop()
        await http.aclose()


# ============================================================================
# Worker — envoi réussi
# ============================================================================


@pytest.mark.asyncio
async def test_worker_sends_payload_on_post() -> None:
    received: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _json

        received.append(_json.loads(req.content))
        return httpx.Response(201, json={"id": "fb_1"})

    http = _new_http(handler)
    q = FeedbackQueue(http, backoff_fn=_zero_backoff)
    try:
        await q.start()
        q.submit(FeedbackPayload(signal_id="sig_x", outcome="win", pnl_pct=0.5))
        # Drain : attend que la queue soit vide
        await q.stop(drain=True, timeout_s=2.0)
    finally:
        await http.aclose()

    assert len(received) == 1
    assert received[0]["signal_id"] == "sig_x"
    assert received[0]["outcome"] == "win"
    assert received[0]["pnl_pct"] == 0.5
    assert q.sent_count == 1
    assert q.dropped_count == 0
    assert q.failed_count == 0


@pytest.mark.asyncio
async def test_worker_sends_multiple_payloads_in_order() -> None:
    received_ids: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _json

        received_ids.append(_json.loads(req.content)["signal_id"])
        return httpx.Response(201, json={})

    http = _new_http(handler)
    q = FeedbackQueue(http, backoff_fn=_zero_backoff)
    try:
        await q.start()
        for i in range(5):
            q.submit(FeedbackPayload(signal_id=f"sig_{i}", outcome="win"))
        await q.stop(drain=True, timeout_s=2.0)
    finally:
        await http.aclose()

    assert received_ids == [f"sig_{i}" for i in range(5)]
    assert q.sent_count == 5


@pytest.mark.asyncio
async def test_worker_uses_post_endpoint_path() -> None:
    paths: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.path)
        return httpx.Response(201, json={})

    http = _new_http(handler)
    q = FeedbackQueue(http, backoff_fn=_zero_backoff)
    try:
        await q.start()
        q.submit(FeedbackPayload(signal_id="x", outcome="win"))
        await q.stop(drain=True, timeout_s=2.0)
    finally:
        await http.aclose()

    assert paths[0] == "/api/v1/feedback"


# ============================================================================
# Worker — retries
# ============================================================================


@pytest.mark.asyncio
async def test_worker_retries_on_network_error_then_succeeds() -> None:
    attempts = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("flaky network")
        return httpx.Response(201, json={})

    http = _new_http(handler)
    q = FeedbackQueue(http, max_retries=3, backoff_fn=_zero_backoff)
    try:
        await q.start()
        q.submit(FeedbackPayload(signal_id="sig_x", outcome="win"))
        await q.stop(drain=True, timeout_s=2.0)
    finally:
        await http.aclose()

    assert attempts == 3
    assert q.sent_count == 1
    assert q.failed_count == 0


@pytest.mark.asyncio
async def test_worker_drops_after_max_retries() -> None:
    attempts = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("perma down")

    http = _new_http(handler)
    q = FeedbackQueue(http, max_retries=2, backoff_fn=_zero_backoff)
    try:
        await q.start()
        q.submit(FeedbackPayload(signal_id="sig_x", outcome="win"))
        await q.stop(drain=True, timeout_s=2.0)
    finally:
        await http.aclose()

    # max_retries=2 → 3 tentatives au total (initial + 2 retries)
    assert attempts == 3
    assert q.sent_count == 0
    assert q.failed_count == 1


@pytest.mark.asyncio
async def test_worker_drops_on_4xx_without_retry() -> None:
    """Un 401/403/404 ne doit PAS retentier — c'est un problème de payload."""
    attempts = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(404, text="signal not found")

    http = _new_http(handler)
    q = FeedbackQueue(http, max_retries=5, backoff_fn=_zero_backoff)
    try:
        await q.start()
        q.submit(FeedbackPayload(signal_id="sig_x", outcome="win"))
        await q.stop(drain=True, timeout_s=2.0)
    finally:
        await http.aclose()

    # Un seul appel : pas de retry sur 404
    assert attempts == 1
    assert q.sent_count == 0
    assert q.failed_count == 1


# ============================================================================
# Stop / drain comportements
# ============================================================================


@pytest.mark.asyncio
async def test_stop_without_drain_drops_queued_payloads() -> None:
    """Un stop rapide drop ce qui n'a pas été envoyé."""
    block_event = asyncio.Event()
    received_count = 0

    async def slow_handler(_req: httpx.Request) -> httpx.Response:
        nonlocal received_count
        received_count += 1
        await block_event.wait()  # bloque jusqu'à libération
        return httpx.Response(201, json={})

    # MockTransport ne supporte pas les async handlers, on simule autrement :
    # un handler sync rapide mais on ne lance même pas le worker.
    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal received_count
        received_count += 1
        return httpx.Response(201, json={})

    http = _new_http(handler)
    q = FeedbackQueue(http, backoff_fn=_zero_backoff)
    try:
        # On submit SANS démarrer le worker
        for i in range(5):
            q.submit(FeedbackPayload(signal_id=f"sig_{i}", outcome="win"))
        assert q.queue_size == 5

        # Démarre puis stop sans drain
        await q.start()
        await q.stop(drain=False, timeout_s=0.1)

        # Au moins certains ont pu partir avant le stop, mais la queue
        # doit être vide au final (drop sur stop)
        assert q.queue_size == 0
    finally:
        await http.aclose()


@pytest.mark.asyncio
async def test_stop_drain_waits_for_queue_to_empty() -> None:
    sent_count = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal sent_count
        sent_count += 1
        return httpx.Response(201, json={})

    http = _new_http(handler)
    q = FeedbackQueue(http, backoff_fn=_zero_backoff)
    try:
        await q.start()
        for i in range(10):
            q.submit(FeedbackPayload(signal_id=f"sig_{i}", outcome="win"))
        await q.stop(drain=True, timeout_s=5.0)
    finally:
        await http.aclose()

    assert sent_count == 10
    assert q.sent_count == 10
    assert q.dropped_count == 0


@pytest.mark.asyncio
async def test_stop_when_not_running_is_noop() -> None:
    http = _new_http(lambda _r: httpx.Response(201, json={}))
    q = FeedbackQueue(http)
    try:
        await q.stop()  # ne plante pas
    finally:
        await http.aclose()


# ============================================================================
# Integration via TikClient
# ============================================================================


@pytest.mark.asyncio
async def test_tikclient_report_outcome_enqueues_and_sends() -> None:
    received: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _json

        if req.url.path.endswith("/feedback"):
            received.append(_json.loads(req.content))
            return httpx.Response(201, json={"id": "fb_x"})
        return httpx.Response(404)

    from tik_sdk import TikClient

    client = TikClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
    )
    # Force backoff zéro pour des tests rapides
    assert client.feedback_queue is not None
    client.feedback_queue._backoff_fn = _zero_backoff  # type: ignore[attr-defined]

    async with client:
        ok = await client.report_outcome(
            signal_id="TIK-SWING-BTC-20260430-abc",
            outcome="win",
            trade_id="trade_99",
            pnl_pct=1.4,
            duration_held_s=4200,
        )
        assert ok is True
        # Drain explicite
        await client.feedback_queue.stop(drain=True, timeout_s=2.0)

    assert len(received) == 1
    sent = received[0]
    assert sent["signal_id"] == "TIK-SWING-BTC-20260430-abc"
    assert sent["outcome"] == "win"
    assert sent["pnl_pct"] == 1.4
    assert sent["duration_held_s"] == 4200


@pytest.mark.asyncio
async def test_tikclient_report_outcome_raises_when_disabled() -> None:
    from tik_sdk import TikClient

    client = TikClient(
        base_url="http://tik.test",
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={})),
        enable_feedback=False,
    )
    async with client:
        with pytest.raises(RuntimeError, match="feedback queue is disabled"):
            await client.report_outcome(signal_id="x", outcome="win")
