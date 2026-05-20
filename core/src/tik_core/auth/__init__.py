"""Authentification pluggable (API key actuel, OAuth2 futur — cf. ADR-001)."""

from tik_core.auth.api_key import ApiKeyProvider
from tik_core.auth.dependencies import get_auth_context, require_scope
from tik_core.auth.provider import AuthContext, AuthProvider

__all__ = [
    "AuthProvider",
    "AuthContext",
    "ApiKeyProvider",
    "get_auth_context",
    "require_scope",
]
