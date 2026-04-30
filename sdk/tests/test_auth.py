"""Tests de la couche d'authentification."""

import pytest

from tik_sdk.auth import ApiKeyAuth, AuthMethod


def test_api_key_auth_produces_bearer_header() -> None:
    auth = ApiKeyAuth("tik_abc123")
    assert auth.headers() == {"Authorization": "Bearer tik_abc123"}


def test_api_key_auth_query_params_for_ws() -> None:
    """Le WS s'authentifie via `?api_key=...` (cf. core/api/ws.py)."""
    auth = ApiKeyAuth("tik_abc123")
    assert auth.query_params() == {"api_key": "tik_abc123"}


def test_api_key_auth_rejects_empty_key() -> None:
    with pytest.raises(ValueError):
        ApiKeyAuth("")


def test_api_key_auth_is_an_auth_method() -> None:
    auth = ApiKeyAuth("tik_abc")
    assert isinstance(auth, AuthMethod)


def test_auth_method_is_abstract() -> None:
    """L'interface ne doit pas pouvoir être instanciée directement."""
    with pytest.raises(TypeError):
        AuthMethod()  # type: ignore[abstract]


def test_auth_method_query_params_default_is_empty() -> None:
    """Une sous-classe qui n'override pas query_params() doit retourner {}."""

    class HeaderOnlyAuth(AuthMethod):
        def headers(self) -> dict[str, str]:
            return {"X-Custom": "abc"}

    auth = HeaderOnlyAuth()
    assert auth.query_params() == {}
