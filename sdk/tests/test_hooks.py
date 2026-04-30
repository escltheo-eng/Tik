"""Tests du registry + dispatcher de hooks."""

import pytest

from tik_sdk.hooks import HookRegistry


def test_register_then_handlers_for() -> None:
    reg = HookRegistry()

    def handler(_x: object) -> None:
        pass

    reg.register("foo", handler)
    assert reg.handlers_for("foo") == [handler]
    assert reg.has("foo")
    assert not reg.has("bar")


def test_handlers_for_returns_defensive_copy() -> None:
    reg = HookRegistry()

    def handler(_x: object) -> None:
        pass

    reg.register("foo", handler)
    handlers = reg.handlers_for("foo")
    handlers.clear()
    # Le registre interne ne doit pas avoir été affecté
    assert reg.handlers_for("foo") == [handler]


def test_register_rejects_non_callable() -> None:
    reg = HookRegistry()
    with pytest.raises(TypeError):
        reg.register("foo", "not a function")  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_dispatch_calls_sync_handler() -> None:
    reg = HookRegistry()
    calls: list[object] = []

    def handler(payload: object) -> None:
        calls.append(payload)

    reg.register("foo", handler)
    await reg.dispatch("foo", "payload-1")

    assert calls == ["payload-1"]


@pytest.mark.asyncio
async def test_dispatch_awaits_async_handler() -> None:
    reg = HookRegistry()
    calls: list[object] = []

    async def handler(payload: object) -> None:
        calls.append(payload)

    reg.register("foo", handler)
    await reg.dispatch("foo", "payload-2")

    assert calls == ["payload-2"]


@pytest.mark.asyncio
async def test_dispatch_calls_multiple_handlers_in_order() -> None:
    reg = HookRegistry()
    order: list[str] = []

    def first(_p: object) -> None:
        order.append("first")

    async def second(_p: object) -> None:
        order.append("second")

    def third(_p: object) -> None:
        order.append("third")

    reg.register("foo", first)
    reg.register("foo", second)
    reg.register("foo", third)
    await reg.dispatch("foo", None)

    assert order == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_dispatch_isolates_exceptions() -> None:
    """Si un handler plante, les suivants doivent être appelés quand même.

    Critique en production : un bug dans un handler ne doit pas faire
    tomber la boucle WS du SDK ni les autres consommateurs des signaux.
    """
    reg = HookRegistry()
    seen: list[str] = []

    def boom(_p: object) -> None:
        seen.append("boom-called")
        raise RuntimeError("crash dans le handler")

    def survivor(_p: object) -> None:
        seen.append("survivor-called")

    reg.register("foo", boom)
    reg.register("foo", survivor)

    # Ne doit PAS lever
    await reg.dispatch("foo", None)

    assert seen == ["boom-called", "survivor-called"]


@pytest.mark.asyncio
async def test_dispatch_isolates_async_exception() -> None:
    reg = HookRegistry()
    seen: list[str] = []

    async def boom(_p: object) -> None:
        seen.append("boom-called")
        raise RuntimeError("async crash")

    async def survivor(_p: object) -> None:
        seen.append("survivor-called")

    reg.register("foo", boom)
    reg.register("foo", survivor)
    await reg.dispatch("foo", None)

    assert seen == ["boom-called", "survivor-called"]


@pytest.mark.asyncio
async def test_dispatch_no_handlers_is_noop() -> None:
    reg = HookRegistry()
    # Ne doit pas lever
    await reg.dispatch("never_registered", "anything")


@pytest.mark.asyncio
async def test_dispatch_handles_sync_handler_returning_coroutine() -> None:
    """Un handler 'sync' peut renvoyer une coroutine (lambda async, etc.)."""
    reg = HookRegistry()
    seen: list[object] = []

    async def inner(payload: object) -> None:
        seen.append(payload)

    # callable sync qui retourne une coroutine
    def wrapping_sync(payload: object) -> object:
        return inner(payload)

    reg.register("foo", wrapping_sync)
    await reg.dispatch("foo", "deep-payload")

    assert seen == ["deep-payload"]
