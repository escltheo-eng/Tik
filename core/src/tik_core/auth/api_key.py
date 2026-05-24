"""ApiKeyProvider — authentification par clé API simple.

Format attendu : Header `Authorization: Bearer <key>` ou `X-Api-Key: <key>`.

La clé en clair n'est jamais stockée : seul le hash SHA-256 est persisté.
Les 4 derniers caractères sont conservés séparément pour affichage UI.
"""

import hashlib
import secrets
from datetime import timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tik_core.auth.provider import AuthContext, AuthProvider
from tik_core.storage.models import ApiKey
from tik_core.utils.time import now_utc_naive


def hash_key(raw_key: str) -> str:
    """Hash SHA-256 hexadécimal de la clé."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_key() -> tuple[str, str, str]:
    """Génère une nouvelle clé.

    Retourne (raw_key, hash, suffix_4_chars).
    Format : tik_<43 url-safe chars>.
    """
    raw = f"tik_{secrets.token_urlsafe(32)}"
    return raw, hash_key(raw), raw[-4:]


def _extract_key_from_request(request: Request) -> str | None:
    """Cherche la clé dans Authorization Bearer ou X-Api-Key."""
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip()
    x_api_key = request.headers.get("x-api-key")
    if x_api_key:
        return x_api_key.strip()
    return None


class ApiKeyProvider(AuthProvider):
    """Authentification par clé API."""

    async def authenticate(
        self,
        request: Request,
        session: AsyncSession,
    ) -> AuthContext:
        raw_key = _extract_key_from_request(request)
        if not raw_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key",
                headers={"WWW-Authenticate": "Bearer"},
            )

        key_hash_value = hash_key(raw_key)
        stmt = select(ApiKey).where(ApiKey.key_hash == key_hash_value)
        result = await session.execute(stmt)
        api_key: ApiKey | None = result.scalar_one_or_none()

        if api_key is None or not api_key.active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        if api_key.expires_at is not None and api_key.expires_at < now_utc_naive():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Expired API key",
            )

        # Mise à jour last_used_at throttlée (≤ 1×/h) : évite un write DB à
        # CHAQUE requête authentifiée (get_session commit derrière) tout en
        # gardant le signal d'audit "dernière utilisation" (audit 2026-05-24 M5).
        _now = now_utc_naive()
        if api_key.last_used_at is None or (_now - api_key.last_used_at) > timedelta(hours=1):
            api_key.last_used_at = _now

        return AuthContext(
            client_id=api_key.client_id,
            scopes=list(api_key.scopes or []),
            auth_method="api_key",
            extra={"key_id": api_key.id},
        )
