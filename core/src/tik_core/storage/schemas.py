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


class NearMacroEvent(BaseModel):
    """Proximité d'un événement macro HIGH au moment de l'émission du signal.

    Posé par `scoring/macro_proximity.py` quand le signal est émis dans la
    fenêtre ±4h d'un event HIGH impactant l'entité (discipline Garde-fou 2-bis).
    Métadonnée d'affichage — n'influence PAS la décision (ADR-017).
    """

    event_code: str
    title: str
    scheduled_for: str  # ISO-8601 UTC (suffixe Z), déjà formaté à l'émission
    importance: str
    hours_until: float  # signé : > 0 = event à venir, < 0 = event passé


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
    # Discipline macro (Phase B1.5) — posé par scoring/macro_proximity.py.
    near_macro_event: NearMacroEvent | None = None
    # Amplitude attendue (ADR-025) — volatilité réalisée typique sur l'horizon,
    # en % du prix (médiane des |variations| sur N barres). CONTEXTE de
    # volatilité (« de combien ça bouge »), PAS une prévision du sens : Tik n'a
    # aucun edge directionnel mesuré (go/no-go 2026-05-27). `ref_price` = prix
    # de clôture à l'émission, sert à convertir l'amplitude en points MT5.
    expected_amplitude_pct: float | None = None
    ref_price: float | None = None


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
    # Baseline constante "robot bête" sur les mêmes signaux (anti-surconfiance).
    # best_baseline_* = meilleur pari constant (long/short/neutral) et son hit rate.
    # beats_baseline = Tik bat-il cette baseline franchement (edge crédible) ? Quand
    # True, le dashboard masque l'avertissement "ce taux suit la tendance".
    # Défauts → les entrées de cache Redis antérieures parsent sans erreur.
    best_baseline_label: str | None = None  # "long" | "short" | "neutral" | None
    best_baseline_hit_rate: float | None = Field(default=None, ge=0, le=1)
    beats_baseline: bool = False
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


class SignalFreshnessOut(BaseModel):
    """Fraîcheur de la production de signaux (M4, audit 2026-05-24).

    `stale=True` signale une panne silencieuse probable (aucun signal récent).
    Le dashboard affiche une bannière rouge dans ce cas.
    """

    last_signal_at: datetime | None
    age_seconds: float | None
    stale: bool
    threshold_seconds: int

    @field_serializer("last_signal_at", when_used="json")
    def _ser_last(self, value: datetime | None) -> str | None:
        return iso_utc(value) if value is not None else None


class SourceHealthItem(BaseModel):
    """État d'une source OSINT (fraîcheur de sa clé Redis)."""

    name: str
    status: str  # "ok" | "stale" | "missing"
    age_seconds: float | None
    max_age_seconds: int
    critical: bool
    note: str


class SourceHealthOut(BaseModel):
    """Santé par source OSINT — détection de dégradation silencieuse (complète M4).

    `any_critical_down=True` = au moins une source dont l'absence dégrade la
    production de signaux actuelle (FG, CryptoCompare, Google News BTC, prix BTC).
    Les sources non critiques dégradées (Reddit Bug 11, shadow, GOLD-side) sont
    listées pour transparence sans déclencher d'alerte.
    """

    checked_at: datetime
    n_total: int
    n_ok: int
    n_stale: int
    n_missing: int
    any_critical_down: bool
    critical_down: list[str]
    sources: list[SourceHealthItem]

    @field_serializer("checked_at", when_used="json")
    def _ser_checked(self, value: datetime) -> str:
        return iso_utc(value)


# ----- Polymarket (marchés prédictifs, SHADOW — contexte) -----


class PolymarketMarketOut(BaseModel):
    """Une ligne de seuil d'un marché Polymarket : proba Yes/No + volume."""

    question: str | None = None
    threshold_usd: float | None = None
    yes_prob: float | None = None
    no_prob: float | None = None
    volume: float | None = None
    clob_token_id: str | None = None


class PolymarketEventOut(BaseModel):
    """Un event Polymarket (échelle de seuils à un horizon) + ses marchés."""

    title: str | None = None
    slug: str | None = None
    end_date: str | None = None
    n_markets: int = 0
    total_volume: float = 0.0
    markets: list[PolymarketMarketOut] = Field(default_factory=list)


class PolymarketSnapshotOut(BaseModel):
    """Snapshot Polymarket par entité (contexte de marché, mode shadow).

    `fetched_at` est une chaîne ISO produite par l'ingester (déjà UTC `+00:00`),
    pas un datetime SQLAlchemy — donc pas de field_serializer ici.
    """

    source: str = "polymarket"
    entity: str
    mode: str = "shadow"
    fetched_at: str | None = None
    n_events: int = 0
    total_volume: float = 0.0
    events: list[PolymarketEventOut] = Field(default_factory=list)


# ----- Dérivés Binance (positionnement, SHADOW — contexte, ADR-023) -----


class DerivativesSnapshotOut(BaseModel):
    """Snapshot positionnement dérivés Binance par entité (contexte, mode shadow).

    Reflète tel quel le snapshot Redis publié par `BinanceDerivativesIngester`
    (`tik.deriv.binance.{entity}`) : funding rate, open interest, ratios
    long/short retail + top traders. `fetched_at` est une chaîne ISO produite
    par l'ingester (déjà UTC `+00:00`). C'est du CONTEXTE de marché (argent +
    levier engagés), PAS un signal Tik — aucun overlay branché (ADR-023).
    """

    source: str = "binance_derivatives"
    entity: str = "BTC"
    mode: str = "shadow"
    fetched_at: str | None = None
    funding_rate: float | None = None
    mark_price: float | None = None
    next_funding_time: int | None = None
    open_interest_btc: float | None = None
    open_interest_usd: float | None = None
    long_short_ratio_global: float | None = None
    long_account_global: float | None = None
    short_account_global: float | None = None
    long_short_ratio_top: float | None = None
    long_account_top: float | None = None
    short_account_top: float | None = None


# Couche éducative « Lecture macro » supprimée 2026-05-30 sur décision trader
# (cf. memory macro-reading-removed-2026-05-30 pour rebuild guide). Schémas
# MacroReactionStat / MacroAssetReaction / MacroReadingOut / MacroLiveEvent /
# MacroLiveRecent / MacroLiveOut retirés en même temps que api/macro_reading.py,
# aggregator/macro_mechanisms.py et scripts/measure_macro_reaction.py.


# ----- Carnet de trades manuels (Levier B 2026-06-03) -----


class ManualTradeIn(BaseModel):
    """Saisie d'un nouveau trade manuel (ouverture).

    `entry_time` optionnel (défaut = maintenant côté serveur). Les champs
    `tik_*` sont le snapshot du contexte Tik à l'entrée, fournis par le
    dashboard qui dispose du dernier signal live ; absents → alignement "none".
    """

    entity_id: str = Field(pattern="^(BTC|GOLD)$")
    direction: str = Field(pattern="^(long|short)$")
    entry_price: float = Field(gt=0)
    size_lots: float = Field(gt=0)
    entry_time: datetime | None = None
    stop_price: float | None = Field(default=None, gt=0)
    target_price: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=1000)
    tik_signal_id: str | None = None
    tik_direction: str | None = Field(default=None, pattern="^(long|short|neutral)$")
    tik_veracity: float | None = Field(default=None, ge=0, le=1)


class ManualTradeCloseIn(BaseModel):
    """Clôture d'un trade : prix de sortie (+ heure/note optionnelles)."""

    exit_price: float = Field(gt=0)
    exit_time: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)


class ManualTradeOut(BaseModel):
    """Trade manuel exposé via l'API (lecture)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    entity_id: str
    direction: str
    entry_time: datetime
    entry_price: float
    size_lots: float
    stop_price: float | None = None
    target_price: float | None = None
    exit_time: datetime | None = None
    exit_price: float | None = None
    status: str
    note: str | None = None
    result_pct: float | None = None
    tik_signal_id: str | None = None
    tik_direction: str | None = None
    tik_veracity: float | None = None
    tik_alignment: str | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "entry_time", "exit_time", "created_at", "updated_at", when_used="json"
    )
    def _ser_dt(self, value: datetime | None) -> str | None:
        return iso_utc(value)


class ManualTradeGroupStats(BaseModel):
    """Métriques d'un groupe de trades clôturés (global ou par alignement)."""

    n: int
    win_rate: float | None = None
    avg_result_pct: float | None = None
    total_result_pct: float = 0.0


class ManualTradeStatsByAlignment(BaseModel):
    """Décomposition par alignement Tik — le cœur de la mesure « Tik aide ? »."""

    with_tik: ManualTradeGroupStats = Field(alias="with")
    against: ManualTradeGroupStats
    none: ManualTradeGroupStats

    model_config = ConfigDict(populate_by_name=True)


class ManualTradeStatsOut(BaseModel):
    """Bilan global du carnet + décomposition par alignement Tik."""

    n_total: int
    n_open: int
    n_closed: int
    win_rate: float | None = None
    avg_result_pct: float | None = None
    total_result_pct: float = 0.0
    by_alignment: ManualTradeStatsByAlignment
