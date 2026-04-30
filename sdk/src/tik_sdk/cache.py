"""Cache local pour le SDK Tik (Strategy pattern, façon ADR-001/006).

Pourquoi un cache côté SDK ?
- **Latence** : éviter un round-trip HTTP quand on requête la même donnée
  plusieurs fois en quelques secondes (cas typique : `turbo_v2.py` qui
  consulte le dernier signal swing à chaque tick d'évaluation).
- **Fallback offline** : si le core Tik tombe, le SDK peut servir la
  dernière donnée connue au bot client plutôt que de lever une exception
  (cohérent avec ADR-003 — "si Tik est down, Zeta continue normalement").

Implémentations livrées en Session 3 :
    NoCache       — no-op, défaut (cache désactivé).
    InMemoryCache — TTL en RAM, sans dépendance externe.

À venir :
    RedisCache    — partage du cache entre processus, via extras `[redis]`.

Chaque implémentation respecte la même interface `Cache` (Strategy pattern),
donc on peut les permuter sans toucher au reste du SDK.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# TTL par défaut par horizon, en secondes. Aligné approximativement sur
# les durées d'expiry du publisher core (`scoring/publisher.py`).
DEFAULT_TTL_BY_HORIZON: dict[str, int] = {
    "flash": 60,       # 1 min — données qui bougent vite
    "swing": 300,      # 5 min
    "macro": 3600,     # 1 h
    "default": 300,    # 5 min — cas générique (entities, veracity, etc.)
}


class Cache(ABC):
    """Interface pluggable du cache SDK.

    Stocke et récupère du **JSON brut** (dict/list de types primitifs).
    La couche cache ne dépend pas des types métier (Pydantic) : c'est le
    `TikClient` qui valide les modèles après lecture du cache.
    """

    @abstractmethod
    async def get(self, key: str) -> Any | None:
        """Retourne la valeur si présente et non expirée, sinon None."""
        raise NotImplementedError

    @abstractmethod
    async def set(self, key: str, value: Any, ttl_s: int) -> None:
        """Stocke `value` sous `key` avec une durée de vie de `ttl_s` secondes.

        `ttl_s <= 0` est ignoré (no-op) : permet de désactiver le cache
        au cas par cas sans branchement côté appelant.
        """
        raise NotImplementedError

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Supprime `key` du cache. No-op si absent."""
        raise NotImplementedError

    @abstractmethod
    async def clear(self) -> None:
        """Vide tout le cache."""
        raise NotImplementedError


class NoCache(Cache):
    """Cache no-op — pratique pour désactiver le cache sans branchement.

    C'est le défaut du `TikClient` : un appelant qui ne configure rien
    ne paie aucun coût mémoire ni latence. Le cache est purement opt-in.
    """

    async def get(self, key: str) -> Any | None:
        return None

    async def set(self, key: str, value: Any, ttl_s: int) -> None:
        return None

    async def delete(self, key: str) -> None:
        return None

    async def clear(self) -> None:
        return None


class InMemoryCache(Cache):
    """Cache TTL en RAM avec éviction LRU au-delà de `maxsize`.

    Pas thread-safe. Asyncio mono-thread → suffisant pour tous les cas
    SDK actuels (un bot = un event loop).
    """

    def __init__(
        self,
        *,
        maxsize: int = 1000,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        """
        Args:
            maxsize: nombre max d'entrées avant éviction LRU. Min 1.
            time_fn: source de temps injectable pour les tests.
        """
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._time_fn = time_fn or time.monotonic
        # OrderedDict pour LRU : on déplace en fin à chaque accès.
        # Valeur = (expires_at_monotonic, value)
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None

        expires_at, value = entry
        now = self._time_fn()
        if now >= expires_at:
            # Expiré : on supprime et on signale miss
            del self._store[key]
            return None

        # Hit : on déplace en fin (LRU update)
        self._store.move_to_end(key)
        return value

    async def set(self, key: str, value: Any, ttl_s: int) -> None:
        if ttl_s <= 0:
            # ttl<=0 = "ne mets pas en cache" — utile pour /health
            return
        expires_at = self._time_fn() + ttl_s
        self._store[key] = (expires_at, value)
        self._store.move_to_end(key)

        # Éviction LRU si on dépasse la capacité
        while len(self._store) > self._maxsize:
            evicted_key, _ = self._store.popitem(last=False)
            log.debug("tik_sdk.cache.evicted_lru", key=evicted_key)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def clear(self) -> None:
        self._store.clear()

    # --- Helpers (introspection — pratiques pour debug + tests) ---

    def __len__(self) -> int:
        return len(self._store)

    def keys(self) -> list[str]:
        """Snapshot des clés actuellement présentes (peut contenir des entrées expirées)."""
        return list(self._store.keys())


def make_cache_key(method: str, path: str, params: dict[str, Any] | None = None) -> str:
    """Construit une clé de cache stable et lisible.

    Format : `<METHOD>:<path>?<sorted_params>`

    Exemple : `GET:/signals/latest?entity=BTC&horizon=swing&limit=10`
    """
    if not params:
        return f"{method.upper()}:{path}"
    # Tri pour stabilité (même params = même clé, peu importe l'ordre)
    parts = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{method.upper()}:{path}?{parts}"
