"""Helpers internes pour le client WebSocket SDK.

Module privé (préfixe `_`) : usage interne uniquement. Les bots clients
passent par `TikStream` (`tik_sdk.stream`).

Trois responsabilités séparées (toutes pures, donc trivialement testables) :
    1. `http_to_ws` — convertit l'URL `http://` en `ws://` (et `https`→`wss`).
    2. `build_ws_url` — assemble l'URL finale `ws://host/api/v1/ws/signals?...`.
    3. `next_backoff` — calcule le prochain délai de reconnexion (exponentiel + jitter).

La boucle WS elle-même vit dans `stream.py` car elle a besoin du registry
de hooks et de la logique métier (parsing message, dispatch événement).
"""

from __future__ import annotations

import random
from urllib.parse import urlencode

WS_PATH = "/api/v1/ws/signals"

# Backoff de reconnexion : démarre à 1 s, double à chaque échec, plafond
# 60 s. Jitter additionnel jusqu'à 0.5 s pour éviter le thundering herd
# si plusieurs SDK reconnectent simultanément après un crash du core.
INITIAL_BACKOFF_S = 1.0
MAX_BACKOFF_S = 60.0
JITTER_MAX_S = 0.5


def http_to_ws(url: str) -> str:
    """Convertit une URL HTTP(S) en URL WS(S).

    >>> http_to_ws("http://localhost:8200")
    'ws://localhost:8200'
    >>> http_to_ws("https://tik.example.com")
    'wss://tik.example.com'
    """
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):]
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):]
    if url.startswith(("ws://", "wss://")):
        return url
    raise ValueError(f"unsupported URL scheme: {url}")


def build_ws_url(
    base_url: str,
    *,
    api_key_param: str,
    entity: str | None = None,
    horizon: str | None = None,
) -> str:
    """Assemble l'URL `/ws/signals` complète avec auth + filtres.

    `api_key_param` provient de `AuthMethod.query_params()["api_key"]`
    (cf. `auth.py`).
    """
    ws_base = http_to_ws(base_url.rstrip("/"))
    params: dict[str, str] = {"api_key": api_key_param}
    if entity is not None:
        params["entity"] = entity
    if horizon is not None:
        params["horizon"] = horizon
    return f"{ws_base}{WS_PATH}?{urlencode(params)}"


def next_backoff(current: float) -> float:
    """Calcule le prochain délai d'attente avant reconnexion.

    Doublage exponentiel plafonné à `MAX_BACKOFF_S`, plus jitter
    aléatoire dans [0, JITTER_MAX_S] ajouté à la fin pour désynchroniser
    plusieurs clients qui reconnectent en même temps.
    """
    next_value = min(current * 2, MAX_BACKOFF_S)
    return next_value + random.uniform(0, JITTER_MAX_S)
