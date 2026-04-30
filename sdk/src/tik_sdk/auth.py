"""Authentification SDK — pluggable façon ADR-001.

Aujourd'hui : `ApiKeyAuth` (header `Authorization: Bearer <key>`).
Demain : `OAuth2Auth`, `MtlsAuth`, etc., sans toucher au `TikClient` :
chaque méthode d'auth implémente l'interface `AuthMethod` et expose
les en-têtes HTTP à attacher à chaque requête.
"""

from abc import ABC, abstractmethod


class AuthMethod(ABC):
    """Interface pluggable d'authentification.

    Toute méthode d'auth doit savoir produire :
    - les en-têtes HTTP à injecter sur les requêtes REST (`headers`),
    - les query params à injecter sur l'URL WebSocket (`query_params`)
      — car le navigateur ne permet pas d'attacher des en-têtes
      personnalisés sur l'ouverture WS, donc le core attend la clé en
      query param sur `/ws/signals`.

    Par défaut, `query_params` retourne un dictionnaire vide ;
    l'implémentation l'override quand sa méthode d'auth a une variante
    pour le WS.
    """

    @abstractmethod
    def headers(self) -> dict[str, str]:
        """Retourne les en-têtes HTTP à ajouter à la requête REST."""
        raise NotImplementedError

    def query_params(self) -> dict[str, str]:
        """Retourne les query params à ajouter à l'URL WebSocket.

        Override dans les sous-classes qui authentifient le WS via URL.
        """
        return {}


class ApiKeyAuth(AuthMethod):
    """Authentification via clé API.

    - REST : header `Authorization: Bearer <key>`
    - WebSocket : query param `?api_key=<key>` (cf. `core/api/ws.py`)

    La clé est générée côté core Tik via le script
    `core/scripts/create_api_key.py`. Garder la clé hors du dépôt
    (variable d'environnement, fichier .env non versionné, secret manager).
    """

    def __init__(self, api_key: str) -> None:
        if not api_key:
            raise ValueError("api_key cannot be empty")
        self._api_key = api_key

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def query_params(self) -> dict[str, str]:
        return {"api_key": self._api_key}
