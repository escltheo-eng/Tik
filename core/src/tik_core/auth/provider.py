"""Interface abstraite des providers d'authentification.

ADR-001 : L'authentification est pluggable. Aujourd'hui, ApiKeyProvider.
Demain, si les besoins évoluent, OAuth2Provider peut être ajouté sans
toucher au code métier (endpoints, services).

Chaque endpoint utilise `Depends(get_auth_context)` qui résout le provider
courant via config (`TIK_AUTH_PROVIDER=api_key | oauth2`).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class AuthContext:
    """Contexte authentifié associé à une requête.

    Les endpoints utilisent ces champs, indépendants du provider.
    """

    client_id: str
    scopes: list[str] = field(default_factory=list)
    auth_method: str = "api_key"
    # Metadata libre (futur : token_id, issuer, etc.)
    extra: dict = field(default_factory=dict)

    def has_scope(self, scope: str) -> bool:
        # "admin" est super-scope. Autrement, match exact ou wildcard "read:*".
        if "admin" in self.scopes:
            return True
        if scope in self.scopes:
            return True
        prefix = scope.split(":")[0] + ":*"
        return prefix in self.scopes


class AuthProvider(ABC):
    """Interface d'un provider d'authentification."""

    @abstractmethod
    async def authenticate(
        self,
        request: Request,
        session: AsyncSession,
    ) -> AuthContext:
        """Authentifie la requête et retourne le contexte.

        Raise HTTPException(401) si l'auth échoue.
        """
        ...
