"""Exceptions du SDK Tik.

Hiérarchie :

    TikError              # base
    ├── AuthError         # 401 / 403
    ├── NotFoundError     # 404
    ├── ServerError       # 5xx côté core Tik
    └── NetworkError      # connexion impossible, timeout, DNS échec

Toujours capturer `TikError` côté bot client si on veut un fallback
unique (mode dégradé). Capturer un type plus précis quand on veut
réagir différemment (ex : `NetworkError` → utiliser le cache).
"""


class TikError(Exception):
    """Erreur de base du SDK Tik."""


class AuthError(TikError):
    """Authentification refusée par le core (401, 403, scope manquant)."""


class NotFoundError(TikError):
    """Ressource non trouvée (404)."""


class ServerError(TikError):
    """Erreur interne du core Tik (5xx)."""


class NetworkError(TikError):
    """Connexion impossible, timeout, DNS échec.

    En sessions futures, ce type d'erreur déclenchera le circuit breaker
    LOCAL côté SDK et basculera sur le cache si disponible.
    """
