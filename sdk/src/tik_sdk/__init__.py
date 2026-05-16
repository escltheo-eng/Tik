"""Tik SDK — client Python pour consommer les signaux du core Tik.

À destination des bots clients (Zeta, Totem et futurs).

ADR-003 — Le SDK n'expose AUCUNE méthode d'exécution d'ordre.
Tik est une source d'edge additionnelle ; tout passe systématiquement
par le guard V01-V15 et le risk_engine de Zeta. Le SDK fournit
uniquement de la lecture de signaux + un `report_outcome` non-bloquant
(POST /feedback async via queue + worker).
"""

from tik_sdk.auth import ApiKeyAuth, AuthMethod
from tik_sdk.cache import (
    DEFAULT_TTL_BY_HORIZON,
    Cache,
    InMemoryCache,
    NoCache,
    make_cache_key,
)
from tik_sdk.circuit_breaker import CircuitBreaker
from tik_sdk.client import TikClient
from tik_sdk.config import (
    CacheConfig,
    CircuitBreakerConfig,
    ConfigWatcher,
    CoreConfig,
    FeedbackConfig,
    StreamConfig,
    TikConfig,
    diff_mutable_settings,
    warn_immutable_changes,
)
from tik_sdk.exceptions import (
    AuthError,
    CircuitBreakerOpen,
    NetworkError,
    NotFoundError,
    ServerError,
    TikError,
)
from tik_sdk.feedback import FeedbackPayload, FeedbackQueue
from tik_sdk.hooks import HookRegistry
from tik_sdk.models import (
    Advisory,
    CounterScenario,
    Entity,
    Evidence,
    Health,
    Signal,
    SourceVeracity,
    Trigger,
    VeracityStatus,
)
from tik_sdk.stream import TikStream

__version__ = "0.6.0"

__all__ = [
    "Advisory",
    "ApiKeyAuth",
    "AuthError",
    "AuthMethod",
    "Cache",
    "CacheConfig",
    "CircuitBreaker",
    "CircuitBreakerConfig",
    "CircuitBreakerOpen",
    "ConfigWatcher",
    "CoreConfig",
    "CounterScenario",
    "DEFAULT_TTL_BY_HORIZON",
    "Entity",
    "Evidence",
    "FeedbackConfig",
    "FeedbackPayload",
    "FeedbackQueue",
    "Health",
    "HookRegistry",
    "InMemoryCache",
    "NetworkError",
    "NoCache",
    "NotFoundError",
    "ServerError",
    "Signal",
    "SourceVeracity",
    "StreamConfig",
    "TikClient",
    "TikConfig",
    "TikError",
    "TikStream",
    "Trigger",
    "VeracityStatus",
    "__version__",
    "diff_mutable_settings",
    "make_cache_key",
    "warn_immutable_changes",
]
