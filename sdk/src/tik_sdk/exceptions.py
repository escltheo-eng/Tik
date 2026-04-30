"""Exceptions du SDK Tik.

Hiérarchie :

    TikError                   # base
    ├── AuthError              # 401 / 403
    ├── NotFoundError          # 404
    ├── ServerError            # 5xx côté core Tik
    ├── NetworkError           # connexion impossible, timeout, DNS échec
    └── CircuitBreakerOpen     # circuit breaker LOCAL ouvert, requête refusée

Toujours capturer `TikError` côté bot client si on veut un fallback
unique (mode dégradé). Capturer un type plus précis quand on veut
réagir différemment (ex : `NetworkError` → utiliser le cache,
`CircuitBreakerOpen` → attendre un cycle).
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

    Quand un cache + un circuit breaker sont configurés sur le `TikClient`,
    cette erreur déclenche d'abord une tentative de fallback via cache.
    Si le cache est miss, l'erreur est propagée.
    """


class CircuitBreakerOpen(TikError):
    """Le circuit breaker LOCAL du SDK a ouvert le circuit.

    Levée quand le SDK détecte que le core Tik est probablement down
    (suite à `failure_threshold` échecs consécutifs) et refuse les
    nouvelles requêtes pour laisser le core se rétablir. Si un cache
    est configuré, le fallback cache est essayé d'abord ; cette
    exception n'est levée qu'en cas de cache miss.
    """
