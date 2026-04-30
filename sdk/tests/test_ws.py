"""Tests des helpers purs de _ws.py."""

import pytest

from tik_sdk._ws import (
    INITIAL_BACKOFF_S,
    JITTER_MAX_S,
    MAX_BACKOFF_S,
    build_ws_url,
    http_to_ws,
    next_backoff,
)


# ----- http_to_ws -----


def test_http_to_ws_converts_http() -> None:
    assert http_to_ws("http://localhost:8200") == "ws://localhost:8200"


def test_http_to_ws_converts_https() -> None:
    assert http_to_ws("https://tik.example.com") == "wss://tik.example.com"


def test_http_to_ws_passes_through_ws() -> None:
    assert http_to_ws("ws://localhost:8200") == "ws://localhost:8200"
    assert http_to_ws("wss://tik.example.com") == "wss://tik.example.com"


def test_http_to_ws_rejects_unknown_scheme() -> None:
    with pytest.raises(ValueError):
        http_to_ws("ftp://example.com")
    with pytest.raises(ValueError):
        http_to_ws("not-a-url")


def test_http_to_ws_preserves_path_and_port() -> None:
    assert http_to_ws("http://host:1234/foo/bar") == "ws://host:1234/foo/bar"


# ----- build_ws_url -----


def test_build_ws_url_minimal() -> None:
    url = build_ws_url("http://localhost:8200", api_key_param="tik_xxx")
    assert url == "ws://localhost:8200/api/v1/ws/signals?api_key=tik_xxx"


def test_build_ws_url_with_filters() -> None:
    url = build_ws_url(
        "http://localhost:8200",
        api_key_param="tik_xxx",
        entity="BTC",
        horizon="swing",
    )
    # Ordre des params garanti par urlencode (insertion order Python 3.7+)
    assert "api_key=tik_xxx" in url
    assert "entity=BTC" in url
    assert "horizon=swing" in url


def test_build_ws_url_strips_trailing_slash() -> None:
    """`http://host/` ne doit pas produire `ws://host//api/v1/...`."""
    url = build_ws_url("http://localhost:8200/", api_key_param="tik_xxx")
    assert url == "ws://localhost:8200/api/v1/ws/signals?api_key=tik_xxx"


def test_build_ws_url_https_to_wss() -> None:
    url = build_ws_url("https://tik.example.com", api_key_param="tik_xxx")
    assert url.startswith("wss://tik.example.com/api/v1/ws/signals?")


def test_build_ws_url_skips_none_filters() -> None:
    url = build_ws_url(
        "http://localhost:8200",
        api_key_param="tik_xxx",
        entity=None,
        horizon=None,
    )
    assert "entity=" not in url
    assert "horizon=" not in url


def test_build_ws_url_url_encodes_special_chars() -> None:
    """Une clé qui contient un `&` doit être encodée pour ne pas casser l'URL."""
    url = build_ws_url("http://localhost:8200", api_key_param="tik&weird=value")
    assert "api_key=tik%26weird%3Dvalue" in url


# ----- next_backoff -----


def test_next_backoff_doubles() -> None:
    next_v = next_backoff(1.0)
    assert 2.0 <= next_v <= 2.0 + JITTER_MAX_S


def test_next_backoff_caps_at_max() -> None:
    huge = MAX_BACKOFF_S * 10
    next_v = next_backoff(huge)
    # Plafonné à MAX_BACKOFF_S, plus jitter [0, JITTER_MAX_S]
    assert MAX_BACKOFF_S <= next_v <= MAX_BACKOFF_S + JITTER_MAX_S


def test_next_backoff_starts_from_initial() -> None:
    next_v = next_backoff(INITIAL_BACKOFF_S)
    assert 2.0 <= next_v <= 2.0 + JITTER_MAX_S
