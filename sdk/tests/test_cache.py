"""Tests du cache local — InMemoryCache + NoCache + make_cache_key."""

import pytest

from tik_sdk.cache import (
    DEFAULT_TTL_BY_HORIZON,
    InMemoryCache,
    NoCache,
    make_cache_key,
)


class FakeClock:
    """Source de temps avancable manuellement."""

    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ----- NoCache -----


@pytest.mark.asyncio
async def test_nocache_get_always_returns_none() -> None:
    c = NoCache()
    assert await c.get("any_key") is None


@pytest.mark.asyncio
async def test_nocache_set_does_nothing() -> None:
    c = NoCache()
    await c.set("k", "v", ttl_s=60)
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_nocache_delete_and_clear_no_op() -> None:
    c = NoCache()
    # Doivent juste ne pas planter
    await c.delete("k")
    await c.clear()


# ----- InMemoryCache : opérations de base -----


@pytest.mark.asyncio
async def test_in_memory_set_then_get() -> None:
    c = InMemoryCache()
    await c.set("k", {"signal": "data"}, ttl_s=60)
    assert await c.get("k") == {"signal": "data"}


@pytest.mark.asyncio
async def test_in_memory_get_missing_returns_none() -> None:
    c = InMemoryCache()
    assert await c.get("never_set") is None


@pytest.mark.asyncio
async def test_in_memory_set_ttl_zero_is_noop() -> None:
    """ttl_s <= 0 = ne pas mettre en cache (utile pour /health)."""
    c = InMemoryCache()
    await c.set("k", "v", ttl_s=0)
    assert await c.get("k") is None
    await c.set("k", "v", ttl_s=-5)
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_in_memory_overwrite() -> None:
    c = InMemoryCache()
    await c.set("k", "v1", ttl_s=60)
    await c.set("k", "v2", ttl_s=60)
    assert await c.get("k") == "v2"


@pytest.mark.asyncio
async def test_in_memory_delete() -> None:
    c = InMemoryCache()
    await c.set("k", "v", ttl_s=60)
    await c.delete("k")
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_in_memory_delete_missing_no_op() -> None:
    c = InMemoryCache()
    await c.delete("never_set")  # ne plante pas


@pytest.mark.asyncio
async def test_in_memory_clear() -> None:
    c = InMemoryCache()
    await c.set("k1", "v1", ttl_s=60)
    await c.set("k2", "v2", ttl_s=60)
    await c.clear()
    assert await c.get("k1") is None
    assert await c.get("k2") is None
    assert len(c) == 0


# ----- TTL & expiration -----


@pytest.mark.asyncio
async def test_in_memory_expiration_via_clock() -> None:
    clock = FakeClock()
    c = InMemoryCache(time_fn=clock)
    await c.set("k", "v", ttl_s=60)

    clock.advance(30)
    assert await c.get("k") == "v"

    clock.advance(30)  # à T+60, doit avoir expiré (>=)
    assert await c.get("k") is None


@pytest.mark.asyncio
async def test_in_memory_expiration_purges_entry() -> None:
    clock = FakeClock()
    c = InMemoryCache(time_fn=clock)
    await c.set("k", "v", ttl_s=10)
    clock.advance(20)
    await c.get("k")  # déclenche le purge silencieux
    assert len(c) == 0


# ----- LRU eviction -----


@pytest.mark.asyncio
async def test_in_memory_lru_eviction_when_maxsize_reached() -> None:
    c = InMemoryCache(maxsize=3)
    await c.set("k1", "v1", ttl_s=60)
    await c.set("k2", "v2", ttl_s=60)
    await c.set("k3", "v3", ttl_s=60)
    assert len(c) == 3

    # On accède à k1 → devient le plus récemment utilisé
    await c.get("k1")
    # Insertion de k4 → doit évincer le LRU (k2)
    await c.set("k4", "v4", ttl_s=60)
    assert await c.get("k2") is None
    assert await c.get("k1") == "v1"
    assert await c.get("k3") == "v3"
    assert await c.get("k4") == "v4"


@pytest.mark.asyncio
async def test_in_memory_overwrite_does_not_grow_size() -> None:
    c = InMemoryCache(maxsize=2)
    await c.set("k1", "v1", ttl_s=60)
    await c.set("k1", "v1bis", ttl_s=60)  # overwrite
    await c.set("k2", "v2", ttl_s=60)
    assert len(c) == 2  # pas 3
    assert await c.get("k1") == "v1bis"
    assert await c.get("k2") == "v2"


def test_in_memory_constructor_rejects_invalid_maxsize() -> None:
    with pytest.raises(ValueError):
        InMemoryCache(maxsize=0)
    with pytest.raises(ValueError):
        InMemoryCache(maxsize=-1)


# ----- Introspection -----


@pytest.mark.asyncio
async def test_in_memory_keys_snapshot() -> None:
    c = InMemoryCache()
    await c.set("k1", "v1", ttl_s=60)
    await c.set("k2", "v2", ttl_s=60)
    assert sorted(c.keys()) == ["k1", "k2"]


# ----- make_cache_key -----


def test_make_cache_key_no_params() -> None:
    assert make_cache_key("GET", "/health") == "GET:/health"


def test_make_cache_key_with_params() -> None:
    key = make_cache_key("GET", "/signals/latest", {"entity": "BTC", "limit": 10})
    assert key == "GET:/signals/latest?entity=BTC&limit=10"


def test_make_cache_key_params_order_stable() -> None:
    """Même params dans un autre ordre = même clé."""
    k1 = make_cache_key("GET", "/x", {"a": 1, "b": 2, "c": 3})
    k2 = make_cache_key("GET", "/x", {"c": 3, "a": 1, "b": 2})
    assert k1 == k2


def test_make_cache_key_method_uppercase() -> None:
    assert make_cache_key("get", "/x") == "GET:/x"


def test_make_cache_key_empty_params_treated_as_none() -> None:
    assert make_cache_key("GET", "/x", {}) == "GET:/x"


def test_make_cache_key_none_params() -> None:
    assert make_cache_key("GET", "/x", None) == "GET:/x"


def test_default_ttl_by_horizon_keys() -> None:
    """Les TTL par défaut couvrent les 3 horizons + un fallback."""
    assert "flash" in DEFAULT_TTL_BY_HORIZON
    assert "swing" in DEFAULT_TTL_BY_HORIZON
    assert "macro" in DEFAULT_TTL_BY_HORIZON
    assert "default" in DEFAULT_TTL_BY_HORIZON
    # Cohérence : flash < swing < macro
    assert DEFAULT_TTL_BY_HORIZON["flash"] < DEFAULT_TTL_BY_HORIZON["swing"]
    assert DEFAULT_TTL_BY_HORIZON["swing"] < DEFAULT_TTL_BY_HORIZON["macro"]
