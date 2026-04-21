"""Dépendances FastAPI pour l'authentification.

Les endpoints importent `get_auth_context` ou `require_scope(...)` sans
se préoccuper du provider courant (api_key ou oauth2).
"""

from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth.api_key import ApiKeyProvider
from tik_core.auth.provider import AuthContext, AuthProvider
from tik_core.config import get_settings
from tik_core.storage.database import get_session


@lru_cache
def _get_provider() -> AuthProvider:
    """Résout le provider courant depuis la config."""
    settings = get_settings()
    if settings.auth_provider == "api_key":
        return ApiKeyProvider()
    if settings.auth_provider == "oauth2":
        # Placeholder : lorsqu'on ajoutera OAuth2, retourner OAuth2Provider() ici.
        # Pour l'instant, on lève une erreur explicite.
        raise NotImplementedError(
            "OAuth2 provider not implemented yet. Set TIK_AUTH_PROVIDER=api_key."
        )
    raise ValueError(f"Unknown auth provider: {settings.auth_provider}")


async def get_auth_context(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    """Dépendance principale : retourne le contexte auth ou lève 401."""
    provider = _get_provider()
    return await provider.authenticate(request, session)


def require_scope(scope: str):
    """Usage : `Depends(require_scope("write:feedback"))`."""

    async def _check(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
        if not ctx.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing scope: {scope}",
            )
        return ctx

    return _check
