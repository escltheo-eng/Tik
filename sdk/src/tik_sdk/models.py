"""Modèles Pydantic du SDK — miroirs des schémas du core.

Source de vérité côté core : `core/src/tik_core/storage/schemas.py`.
Toute évolution là-bas implique une mise à jour ici. Le SDK est versionné
en parallèle du core ; à terme on pourra publier l'OpenAPI du core et
auto-générer ce fichier.

Note : on utilise des classes simples (pas de `from_attributes`) parce
que côté SDK on désérialise du JSON, pas des objets ORM.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ----- Health -----


class Health(BaseModel):
    """Réponse de `GET /api/v1/health`."""

    status: str
    version: str
    env: str


# ----- Entities -----


class Entity(BaseModel):
    """Entité observée par Tik (BTC, GOLD, et plus tard event_X)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    domain: str
    namespace: str
    metadata_json: dict[str, Any] = Field(default_factory=dict, alias="metadata_json")
    active: bool
    created_at: datetime
    updated_at: datetime


# ----- Signal sub-objects -----


class Evidence(BaseModel):
    """Une preuve qui soutient l'hypothèse du signal."""

    source: str
    score: float = Field(ge=0, le=1)
    fact: str


class Trigger(BaseModel):
    """Un déclencheur technique avec son poids dans la décision."""

    type: str
    value: str
    weight: float = Field(ge=0, le=1)


class CounterScenario(BaseModel):
    """Scénario qui invaliderait le signal (paranoïa contrôlée).

    Tik garantit au moins 2 contre-scénarios par signal.
    """

    name: str
    probability: float = Field(ge=0, le=1)
    mitigation: str


class Advisory(BaseModel):
    """Conseils non bloquants attachés au signal."""

    bias_on_existing_positions: str | None = None
    macro_crash_warning: bool = False
    notes: str | None = None


# ----- Signal principal -----


class Signal(BaseModel):
    """Un signal Tik émis pour une entité, sur un horizon donné.

    Champs clés :
    - `direction` : long | short | neutral
    - `confidence` : ∈ [0, 1] — **magnitude du `combined_bias` OSINT
      cross-validé** depuis le refactor ADR-018 (Paquet 18, 2026-05-07).
      **Pas un score d'analyse technique.** Voir `osint_conviction`
      ci-dessous pour l'alias sémantique recommandé.
    - `veracity`   : ∈ [0, 1] — dispersion des sources OSINT (faible
      dispersion → veracity élevée). Cf. ADR-018 décision 4.
    - `circuit_breaker_status` : "ok" | "degraded" | "tripped" — flag
      anti fake-news à respecter côté bot client (cf. ADR-011).

    ⚠️ **Sémantique de confidence post-Paquet 18** : avant le refactor
    OSINT pur, `confidence` était dérivée de l'analyse technique
    RSI/MACD/EMA. Depuis le 2026-05-07, elle est dérivée uniquement du
    biais OSINT cross-validé (Fear & Greed, news, Reddit, etc.). Le nom
    du champ JSON est resté `confidence` pour compatibilité rétroactive
    avec les 683 signaux historiques en DB. Pour le code de consommation
    nouveau, **préférer la propriété `osint_conviction`** qui rend la
    sémantique explicite et évite la confusion avec un score technique.
    """

    id: str
    timestamp: datetime
    entity_id: str
    horizon: str  # "flash" | "swing" | "macro"
    direction: str  # "long" | "short" | "neutral"
    confidence: float = Field(ge=0, le=1)
    veracity: float = Field(ge=0, le=1)
    hypothesis: str | None = None
    counter_scenarios: list[CounterScenario] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    triggers: list[Trigger] = Field(default_factory=list)
    sources_count: int = 0
    expiry: datetime | None = None
    advisory: Advisory = Field(default_factory=Advisory)
    circuit_breaker_status: str = "ok"

    @property
    def osint_conviction(self) -> float:
        """Alias sémantique de `confidence` (ADR-018, SDK 0.6.0+).

        Retourne strictement la même valeur que `self.confidence`.
        Le nom rend explicite que la « confidence » Tik est en réalité
        la magnitude du consensus OSINT cross-validé (biais combiné des
        sources sentiment news, Fear & Greed, etc.) — **pas** un score
        d'analyse technique RSI/MACD/EMA comme le mot pourrait le
        suggérer en convention trading.

        Usage recommandé pour tous les nouveaux consommateurs (Zeta,
        bots tiers, intégrations B2B). Le champ historique `confidence`
        reste disponible pour la rétrocompatibilité avec les 683
        signaux Tik émis avant le refactor du 2026-05-07.

        Voir aussi :
        - `docs/adr/018-tik-pure-osint-refactor.md` — décision et plan
          de migration OSINT pur
        - `docs/integration_zeta.md` — pattern d'overlay recommandé
          côté Zeta avec seuil minimum osint_conviction × veracity
        """
        return self.confidence


# ----- Veracity -----


class VeracityStatus(BaseModel):
    """État global de la véracité agrégée des sources actives."""

    global_veracity: float
    sources_count_active: int
    last_computed: datetime
    status: str  # "healthy" | "degraded" | "collapse"


class SourceVeracity(BaseModel):
    """Véracité courante d'une source individuelle."""

    id: str
    name: str
    category: str
    current_veracity: float = Field(ge=0, le=1)
    tier: int = Field(ge=1, le=5)
    active: bool
