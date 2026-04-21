"""Authentification pluggable (API key actuel, OAuth2 futur — cf. ADR-001)."""

from tik_core.auth.provider import AuthProvider, AuthContext
from tik_core.auth.api_key import ApiKeyProvider
from tik_core.auth.dependencies import get_auth_context, require_scope

__all__ = [
    "AuthProvider",
    "AuthContext",
    "ApiKeyProvider",
    "get_auth_context",
    "require_scope",
]
