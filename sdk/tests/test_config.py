"""Tests du loader YAML + ConfigWatcher hot-reload."""

import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from tik_sdk import (
    ApiKeyAuth,
    ConfigWatcher,
    TikClient,
    TikConfig,
    diff_mutable_settings,
    warn_immutable_changes,
)


# ============================================================================
# TikConfig — chargement YAML
# ============================================================================


def test_load_minimal_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://localhost:8200
"""
    )
    config = TikConfig.load_from_yaml(yaml_path)
    assert config.core.base_url == "http://localhost:8200"
    assert config.core.timeout_s == 10.0  # défaut
    assert config.cache.enabled is False  # défaut
    assert config.feedback.enabled is True  # défaut
    assert config.stream.veracity_collapse_threshold == 0.5


def test_load_full_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: https://tik.example.com
  timeout_s: 15.0

cache:
  enabled: true
  maxsize: 5000
  ttl_by_horizon:
    flash: 30
    swing: 600
    macro: 7200
    default: 120

circuit_breaker:
  enabled: true
  failure_threshold: 10
  reset_timeout_s: 60

stream:
  veracity_collapse_threshold: 0.4

feedback:
  enabled: true
  max_queue_size: 5000
  max_retries: 5
"""
    )
    config = TikConfig.load_from_yaml(yaml_path)
    assert config.core.base_url == "https://tik.example.com"
    assert config.core.timeout_s == 15.0
    assert config.cache.enabled is True
    assert config.cache.maxsize == 5000
    assert config.cache.ttl_by_horizon["flash"] == 30
    assert config.circuit_breaker.failure_threshold == 10
    assert config.stream.veracity_collapse_threshold == 0.4
    assert config.feedback.max_queue_size == 5000


def test_load_yaml_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        TikConfig.load_from_yaml(tmp_path / "missing.yaml")


def test_load_yaml_invalid_yaml_raises(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text("not: valid: yaml: ::")
    with pytest.raises(Exception):  # yaml.YAMLError
        TikConfig.load_from_yaml(yaml_path)


def test_load_yaml_missing_required_field_raises(tmp_path: Path) -> None:
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text(
        """
cache:
  enabled: true
"""
    )
    # `core.base_url` est obligatoire
    with pytest.raises(ValidationError):
        TikConfig.load_from_yaml(yaml_path)


def test_load_yaml_empty_file_raises(tmp_path: Path) -> None:
    yaml_path = tmp_path / "empty.yaml"
    yaml_path.write_text("")
    # YAML vide → on tente {} → manque core
    with pytest.raises(ValidationError):
        TikConfig.load_from_yaml(yaml_path)


# ============================================================================
# Helpers diff
# ============================================================================


def _make_config(**overrides) -> TikConfig:
    base = {
        "core": {"base_url": "http://localhost:8200"},
    }
    base.update(overrides)
    return TikConfig.model_validate(base)


def test_diff_mutable_settings_no_change() -> None:
    c1 = _make_config()
    c2 = _make_config()
    assert diff_mutable_settings(c1, c2) == {}


def test_diff_mutable_ttl_change() -> None:
    c1 = _make_config()
    c2 = _make_config(cache={"enabled": True, "ttl_by_horizon": {"flash": 999}})
    diff = diff_mutable_settings(c1, c2)
    assert "cache.ttl_by_horizon" in diff


def test_diff_mutable_veracity_threshold_change() -> None:
    c1 = _make_config()
    c2 = _make_config(stream={"veracity_collapse_threshold": 0.3})
    diff = diff_mutable_settings(c1, c2)
    assert "stream.veracity_collapse_threshold" in diff
    assert diff["stream.veracity_collapse_threshold"] == 0.3


def test_warn_immutable_no_change() -> None:
    c1 = _make_config()
    c2 = _make_config()
    assert warn_immutable_changes(c1, c2) == []


def test_warn_immutable_base_url_change() -> None:
    c1 = _make_config()
    c2 = _make_config(core={"base_url": "https://other.example.com"})
    warns = warn_immutable_changes(c1, c2)
    assert "core.base_url" in warns


def test_warn_immutable_breaker_threshold_change() -> None:
    c1 = _make_config()
    c2 = _make_config(circuit_breaker={"enabled": True, "failure_threshold": 99})
    warns = warn_immutable_changes(c1, c2)
    assert "circuit_breaker.enabled" in warns
    assert "circuit_breaker.failure_threshold" in warns


# ============================================================================
# ConfigWatcher — polling et hot-reload
# ============================================================================


@pytest.mark.asyncio
async def test_watcher_loads_initial_config(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://localhost:8200
"""
    )
    watcher = ConfigWatcher(yaml_path, poll_interval_s=0.1)
    try:
        config = await watcher.start()
        assert config.core.base_url == "http://localhost:8200"
        assert watcher.current_config is config
        assert watcher.is_running is True
    finally:
        await watcher.stop()
        assert watcher.is_running is False


@pytest.mark.asyncio
async def test_watcher_detects_file_change_and_calls_handler(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://localhost:8200
stream:
  veracity_collapse_threshold: 0.5
"""
    )
    received_configs: list[TikConfig] = []

    def on_reload(_old: TikConfig, new: TikConfig) -> None:
        received_configs.append(new)

    watcher = ConfigWatcher(yaml_path, poll_interval_s=0.05)
    watcher.on_reload(on_reload)
    try:
        await watcher.start()

        # Modifier le fichier (advance mtime explicitement pour fiabilité)
        await asyncio.sleep(0.1)
        yaml_path.write_text(
            """
core:
  base_url: http://localhost:8200
stream:
  veracity_collapse_threshold: 0.7
"""
        )
        # Force mtime à un point futur (sinon certaines FS sont peu précises)
        import os

        new_mtime = yaml_path.stat().st_mtime + 1.0
        os.utime(yaml_path, (new_mtime, new_mtime))

        # Attend le reload
        for _ in range(50):
            if received_configs:
                break
            await asyncio.sleep(0.05)
    finally:
        await watcher.stop()

    assert len(received_configs) >= 1
    assert received_configs[-1].stream.veracity_collapse_threshold == 0.7


@pytest.mark.asyncio
async def test_watcher_keeps_old_config_on_invalid_reload(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://localhost:8200
"""
    )
    watcher = ConfigWatcher(yaml_path, poll_interval_s=0.05)
    received: list[TikConfig] = []
    watcher.on_reload(lambda _o, n: received.append(n))
    try:
        original = await watcher.start()

        # Casse le fichier
        await asyncio.sleep(0.1)
        yaml_path.write_text("not: valid: yaml: ::")
        import os

        new_mtime = yaml_path.stat().st_mtime + 1.0
        os.utime(yaml_path, (new_mtime, new_mtime))
        await asyncio.sleep(0.2)
    finally:
        await watcher.stop()

    # Aucun handler appelé ; current_config inchangé
    assert received == []
    assert watcher.current_config is original


@pytest.mark.asyncio
async def test_watcher_handler_exception_does_not_break_polling(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://localhost:8200
stream:
  veracity_collapse_threshold: 0.5
"""
    )
    survivor_called = False

    def boom(_o: TikConfig, _n: TikConfig) -> None:
        raise RuntimeError("crash dans handler")

    def survivor(_o: TikConfig, _n: TikConfig) -> None:
        nonlocal survivor_called
        survivor_called = True

    watcher = ConfigWatcher(yaml_path, poll_interval_s=0.05)
    watcher.on_reload(boom)
    watcher.on_reload(survivor)
    try:
        await watcher.start()

        await asyncio.sleep(0.1)
        yaml_path.write_text(
            """
core:
  base_url: http://localhost:8200
stream:
  veracity_collapse_threshold: 0.6
"""
        )
        import os

        new_mtime = yaml_path.stat().st_mtime + 1.0
        os.utime(yaml_path, (new_mtime, new_mtime))

        for _ in range(50):
            if survivor_called:
                break
            await asyncio.sleep(0.05)
    finally:
        await watcher.stop()

    assert survivor_called is True


@pytest.mark.asyncio
async def test_watcher_async_context_manager(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://localhost:8200
"""
    )
    async with ConfigWatcher(yaml_path, poll_interval_s=0.1) as w:
        assert w.is_running is True
        assert w.current_config is not None
    assert w.is_running is False


def test_watcher_constructor_validation(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text("core:\n  base_url: http://x")
    with pytest.raises(ValueError):
        ConfigWatcher(yaml_path, poll_interval_s=0)
    with pytest.raises(ValueError):
        ConfigWatcher(yaml_path, poll_interval_s=-1)


def test_watcher_register_non_callable_raises(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text("core:\n  base_url: http://x")
    w = ConfigWatcher(yaml_path)
    with pytest.raises(TypeError):
        w.on_reload("not callable")  # type: ignore[arg-type]


# ============================================================================
# TikClient.from_config
# ============================================================================


@pytest.mark.asyncio
async def test_from_config_minimal(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://tik.test
"""
    )
    config = TikConfig.load_from_yaml(yaml_path)
    client = TikClient.from_config(
        config,
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(200, json={"status": "ok", "version": "0.4.0", "env": "test"})
        ),
    )
    async with client:
        h = await client.get_health()
        assert h.status == "ok"


@pytest.mark.asyncio
async def test_from_config_with_cache_and_breaker(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://tik.test
cache:
  enabled: true
  maxsize: 100
  ttl_by_horizon:
    flash: 10
    swing: 60
    macro: 600
    default: 30
circuit_breaker:
  enabled: true
  failure_threshold: 7
  reset_timeout_s: 45.0
"""
    )
    config = TikConfig.load_from_yaml(yaml_path)

    call_count = 0

    def handler(_req: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=[])

    client = TikClient.from_config(
        config,
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(handler),
    )
    async with client:
        # Le cache est actif → 2 appels identiques = 1 HTTP
        await client.list_entities()
        await client.list_entities()
    assert call_count == 1


@pytest.mark.asyncio
async def test_apply_mutable_config_updates_ttls(tmp_path: Path) -> None:
    yaml_path = tmp_path / "tik.yaml"
    yaml_path.write_text(
        """
core:
  base_url: http://tik.test
cache:
  enabled: true
  ttl_by_horizon:
    flash: 60
    swing: 300
    macro: 3600
    default: 300
"""
    )
    config = TikConfig.load_from_yaml(yaml_path)
    client = TikClient.from_config(
        config,
        auth=ApiKeyAuth("tik_xxx"),
        transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=[])),
    )
    assert client._ttl_by_horizon["flash"] == 60

    new_config = TikConfig.model_validate(
        {
            "core": {"base_url": "http://tik.test"},
            "cache": {"enabled": True, "ttl_by_horizon": {"flash": 999, "swing": 1, "macro": 2, "default": 3}},
        }
    )
    client.apply_mutable_config(new_config)
    assert client._ttl_by_horizon["flash"] == 999

    await client.aclose()
