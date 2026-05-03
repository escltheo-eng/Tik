"""Schémas Pydantic partagés (I/O API).

Sources de vérité pour les formats. Le SDK reprendra les mêmes schémas.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


# ----- Veracity -----

class VeracityStatus(BaseModel):
    global_veracity: float
    sources_count_active: int
    last_computed: datetime
    status: str  # "healthy" | "degraded" | "collapse"


class SourceVeracity(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    category: str
    current_veracity: float
    tier: int
    active: bool


# ----- Health -----

class HealthOut(BaseModel):
    status: str
    version: str
    env: str
