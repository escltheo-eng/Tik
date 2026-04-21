"""Tests de la couche d'authentification par clé API."""

import pytest

from tik_core.auth.api_key import generate_key, hash_key
from tik_core.auth.provider import AuthContext


def test_generate_key_format():
    raw, hashed, suffix = generate_key()
    assert raw.startswith("tik_")
    assert len(raw) > 20
    assert len(hashed) == 64  # SHA-256 hex
    assert len(suffix) == 4


def test_hash_is_deterministic():
    raw, hashed, _ = generate_key()
    assert hash_key(raw) == hashed


def test_hash_differs_per_key():
    raw1, hash1, _ = generate_key()
    raw2, hash2, _ = generate_key()
    assert raw1 != raw2
    assert hash1 != hash2


def test_auth_context_scope_matching():
    ctx = AuthContext(
        client_id="zeta",
        scopes=["read:signals", "write:feedback"],
        auth_method="api_key",
    )
    assert ctx.has_scope("read:signals") is True
    assert ctx.has_scope("write:feedback") is True
    assert ctx.has_scope("write:entities") is False


def test_auth_context_wildcard_scope():
    ctx = AuthContext(
        client_id="zeta",
        scopes=["read:*"],
        auth_method="api_key",
    )
    assert ctx.has_scope("read:signals") is True
    assert ctx.has_scope("read:veracity") is True
    assert ctx.has_scope("write:feedback") is False


def test_auth_context_admin_scope():
    ctx = AuthContext(
        client_id="admin",
        scopes=["admin"],
        auth_method="api_key",
    )
    assert ctx.has_scope("anything:possible") is True
    assert ctx.has_scope("write:entities") is True
