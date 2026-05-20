"""Schémas Pydantic partagés (I/O API).

Sources de vérité pour les formats. Le SDK reprendra les mêmes schémas.

Sérialisation timezone-aware (cf. ADR-013) : tous les champs `datetime`
exposés dans les schémas Out sont sérialisés en JSON avec un suffixe
`Z` (UTC explicite). Si le datetime entrant est naïf (cas des lectures
SQLAlchemy depuis une colonne `DateTime` sans `timezone=True`), il est
considéré comme UTC sémantique et marqué `Z` à la sortie. Si déjà
aware, l'offset est converti en UTC puis restitué en `Z`.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from tik_core.utils.time import iso_utc

# ----- Entities -----


class EntityIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    domain: str
    namespace: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    domain: str
    namespace: str
    metadata_json: dict[str, Any] = Field(alias="metadata_json")
    active: bool
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at", when_used="json")
    def _ser_dt(self, value: datetime) -> str:
        return iso_utc(value)  # type: ignore[return-value]


# ----- Signals -----


class Evidence(BaseModel):
    source: str
    score: float = Field(ge=0, le=1)
    fact: str
    is_outlier: bool | None = None  # set par cross_validator (cf. ADR-011)


class Trigger(BaseModel):
    type: str
    value: str
    weight: float = Field(ge=0, le=1)


class CounterScenario(BaseModel):
    name: str
    probability: float = Field(ge=0, le=1)
    mitigation: str


class Advisory(BaseModel):
    bias_on_existing_positions: str | None = None
    macro_crash_warning: bool = False
    notes: str | None = None
    # Champs ADR-012 (LLM hypothesis generator) — optionnels.
    # Présents selon le mode TIK_LLM_HYPOTHESIS_MODE :
    #   shadow → llm_hypothesis_candidate (sortie LLM en validation passive)
    #   active → template_hypothesis (ancien template conservé pour audit)
    llm_hypothesis_candidate: str | None = None
    template_hypothesis: str | None = None


class SignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    timestamp: datetime
    entity_id: str
    horizon: str
    direction: str
    confidence: float
    veracity: float
    hypothesis: str | None = None
    counter_scenarios: list[CounterScenario] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    triggers: list[Trigger] = Field(default_factory=list)
    sources_count: int = 0
    expiry: datetime | None = None
    advisory: Advisory = Field(default_factory=Advisory)
    circuit_breaker_status: str = "ok"

    @field_serializer("timestamp", "expiry", when_used="json")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return iso_utc(value)


# ----- Feedback -----


class FeedbackIn(BaseModel):
    signal_id: str
    trade_id: str | None = None
    outcome: str = Field(pattern="^(win|loss|breakeven|not_taken)$")
    pnl_points: float | None = None
    pnl_pct: float | None = None
    duration_held_s: int | None = None
    exit_reason: str | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    signal_id: str
    client_id: str
    outcome: str
    received_at: datetime

    @field_serializer("received_at", when_used="json")
    def _ser_dt(self, value: datetime) -> str:
        return iso_utc(value)  # type: ignore[return-value]


# ----- Veracity -----


class VeracityStatus(BaseModel):
    global_veracity: float
    sources_count_active: int
    last_computed: datetime
    status: str  # "healthy" | "degraded" | "collapse"

    @field_serializer("last_computed", when_used="json")
    def _ser_dt(self, value: datetime) -> str:
        return iso_utc(value)  # type: ignore[return-value]


class SourceVeracity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    current_veracity: float
    tier: int
    active: bool


# ----- Headlines (Phase 1 trading manuel J+10) -----


class HeadlineOut(BaseModel):
    """Titre brut OSINT agrégé depuis les ingesters news.

    Pattern OSINT pro : données brutes citant leurs sources, l'humain
    interprète. Endpoint domain-agnostic — pas de logique trading-spécifique.
    """

    title: str
    url: str | None = None
    publisher: str
    source: str  # "google_news_rss" | "cryptocompare_news" | "reddit_btc" | …
    credibility: float = Field(ge=0, le=1)
    sentiment: str  # "bull" | "bear" | "neutral"
    published_at: datetime | None = None
    fetched_at: datetime

    @field_serializer("published_at", "fetched_at", when_used="json")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return iso_utc(value)


class HeadlineHistoryOut(BaseModel):
    """Titre OSINT historique persisté en DB (Lacune A, Phase 1.1 J+10).

    Identique à `HeadlineOut` + l'`id` UUID de la row pour permettre des
    références futures (linking signal↔titres si on faisait ADR-016 plus
    tard, audit forensic, etc.).
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_id: str
    title: str
    url: str | None = None
    publisher: str
    source: str
    credibility: float = Field(ge=0, le=1)
    sentiment: str
    published_at: datetime | None = None
    fetched_at: datetime

    @field_serializer("published_at", "fetched_at", when_used="json")
    def _ser_dt(self, value: datetime | None) -> str | None:
        return iso_utc(value)


# ----- Macro events (Lacune B Phase B1 J+10) -----


class MacroEventOut(BaseModel):
    """Événement macro programmé exposé via l'API.

    Cf. ADR-017 — Calendrier macro/géopolitique.

    Pattern OSINT pro : sources officielles citées (FRED Releases API ou
    Fed Reserve calendar), importance documentée, assets impactés
    transparents. L'humain interprète, pas de signal trading généré.
    """

    model_config = ConfigDict(from_attributes=True)

    id: str
    event_code: str  # "FOMC_MEETING" | "NFP" | "CPI" | …
    event_name: str  # libellé humain
    scheduled_for: datetime
    importance: str  # "HIGH" | "MEDIUM" | "LOW"
    assets_impacted: list[str]
    source: str  # "fred" | "fed_static"
    release_id: int | None = None

    @field_serializer("scheduled_for", when_used="json")
    def _ser_dt(self, value: datetime) -> str:
        return iso_utc(value) or ""


# ----- Metrics -----


class HitRateOut(BaseModel):
    """Hit rate live des signaux Tik sur une fenêtre temporelle.

    Phase A.2 du plan trading manuel J+10 (cf. `docs/backlog.md` entry n°3).
    Mesure la performance des décisions Tik par horizon × entity sur
    les `since_days` derniers jours.
    """

    entity_id: str
    horizon: str  # "flash" | "swing" | "macro"
    since_days: int
    threshold_pct: float
    measure_hours: float  # durée canonique de mesure du delta prix
    n_total: int  # signaux totaux trouvés (avant filtrage)
    n_evaluated: int  # signaux pour lesquels on a pu calculer un delta prix
    n_skipped: int  # signaux dont le prix n'était pas disponible
    n_success: int  # signaux corrects
    n_flagged_excluded: int  # signaux degraded/tripped exclus (si include_flagged=False)
    include_flagged: bool
    hit_rate: float = Field(ge=0, le=1)
    avg_gain_pct: float
    sample_warning: str | None = None  # ex: "Échantillon faible (12 signaux, 30 mini recommandé)"
    computed_at: datetime
    cache_hit: bool = False  # diagnostic : valeur servie depuis le cache Redis

    @field_serializer("computed_at", when_used="json")
    def _ser_computed_at(self, value: datetime) -> str:
        return iso_utc(value) or ""


class HitRateByVeracityBucket(BaseModel):
    """Une tranche de veracity dans le rapport hit_rate_by_veracity."""

    bucket_label: str  # ex: "0.90-0.94"
    veracity_min: float = Field(ge=0, le=1)
    veracity_max: float = Field(gt=0)  # peut être 1.01 (cf. compute logic)
    n_evaluated: int
    n_skipped: int
    n_success: int
    hit_rate: float = Field(ge=0, le=1)
    avg_gain_pct: float


class HitRateByVeracityOut(BaseModel):
    """Hit rate segmenté par tranche de veracity (Phase A.2-bis J+10).

    L'insight clé du backtest 2026-05-05 : sur 156 signaux 5j, hit rate
    global 24% mais 67% sur veracity 0.95+. Cette carte rend visible le
    bénéfice du filtre veracity côté dashboard pour calibrer le sizing.
    """

    entity_id: str
    horizon: str
    since_days: int
    threshold_pct: float
    measure_hours: float
    n_total_eligible: int
    n_flagged_excluded: int
    include_flagged: bool
    buckets: list[HitRateByVeracityBucket]
    sample_warning: str | None = None
    computed_at: datetime
    cache_hit: bool = False

    @field_serializer("computed_at", when_used="json")
    def _ser_computed_at(self, value: datetime) -> str:
        return iso_utc(value) or ""


# ----- Track record (Phase A.3 trading manuel J+10) -----


class TrackRecordRow(BaseModel):
    """Une ligne du track record : résultat d'un signal à un horizon donné."""

    label: str  # "1h" | "6h" | "24h" | "5j"
    measure_hours: float
    threshold_pct: float
    available: bool  # horizon dans le passé
    target_iso: str  # ISO UTC absolu de la cible (pour calcul "dans X" côté client)
    p0: float | None  # prix au moment du signal
    p1: float | None  # prix à t0 + horizon
    delta_pct: float | None
    success: bool | None
    badge: str  # "correct" | "raté" | "données_manquantes" | "en_attente"


class SignalTrackRecordOut(BaseModel):
    """Track record d'un signal sur 4 horizons (1h / 6h / 24h / 5j).

    Phase A.3 du plan trading manuel J+10 (cf. docs/backlog.md entry n°3).
    """

    signal_id: str
    entity_id: str
    direction: str
    horizon: str
    rows: list[TrackRecordRow]
    computed_at: datetime
    cache_hit: bool = False

    @field_serializer("computed_at", when_used="json")
    def _ser_dt(self, value: datetime) -> str:
        return iso_utc(value) or ""


# ----- Health -----


class HealthOut(BaseModel):
    status: str
    version: str
    env: str
