"""Tests basiques de validation Pydantic des modèles miroirs."""

from typing import Any

import pytest
from pydantic import ValidationError

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


def test_signal_round_trip(signal_payload: dict[str, Any]) -> None:
    sig = Signal.model_validate(signal_payload)
    assert sig.id == "sig_001"
    assert sig.entity_id == "BTC"
    assert sig.confidence == 0.78
    assert sig.veracity == 0.91
    assert len(sig.counter_scenarios) == 2
    assert isinstance(sig.counter_scenarios[0], CounterScenario)
    assert isinstance(sig.evidence[0], Evidence)
    assert isinstance(sig.triggers[0], Trigger)
    assert isinstance(sig.advisory, Advisory)


def test_signal_minimal_required_fields() -> None:
    """Un signal minimal doit valider — seuls les champs sans default sont obligatoires."""
    minimal = {
        "id": "sig_x",
        "timestamp": "2026-04-30T00:00:00",
        "entity_id": "BTC",
        "horizon": "flash",
        "direction": "neutral",
        "confidence": 0.5,
        "veracity": 0.7,
    }
    sig = Signal.model_validate(minimal)
    assert sig.counter_scenarios == []
    assert sig.evidence == []
    assert sig.triggers == []
    assert sig.advisory.macro_crash_warning is False
    assert sig.circuit_breaker_status == "ok"


def test_signal_rejects_missing_required() -> None:
    with pytest.raises(ValidationError):
        Signal.model_validate({"id": "x"})


def test_signal_rejects_confidence_out_of_range() -> None:
    bad = {
        "id": "x",
        "timestamp": "2026-04-30T00:00:00",
        "entity_id": "BTC",
        "horizon": "swing",
        "direction": "long",
        "confidence": 1.5,  # > 1
        "veracity": 0.7,
    }
    with pytest.raises(ValidationError):
        Signal.model_validate(bad)


def test_evidence_score_range() -> None:
    with pytest.raises(ValidationError):
        Evidence(source="x", score=-0.1, fact="y")
    with pytest.raises(ValidationError):
        Evidence(source="x", score=1.1, fact="y")


def test_health_model() -> None:
    h = Health(status="ok", version="0.1.0", env="dev")
    assert h.status == "ok"


def test_veracity_status_round_trip() -> None:
    v = VeracityStatus.model_validate(
        {
            "global_veracity": 0.85,
            "sources_count_active": 5,
            "last_computed": "2026-04-30T12:00:00",
            "status": "healthy",
        }
    )
    assert v.global_veracity == 0.85
    assert v.sources_count_active == 5


def test_source_veracity_round_trip() -> None:
    s = SourceVeracity.model_validate(
        {
            "id": "binance",
            "name": "Binance",
            "category": "market",
            "current_veracity": 0.9,
            "tier": 1,
            "active": True,
        }
    )
    assert s.tier == 1


def test_source_veracity_tier_range() -> None:
    bad = {
        "id": "x",
        "name": "x",
        "category": "x",
        "current_veracity": 0.5,
        "tier": 0,  # tier minimum = 1
        "active": True,
    }
    with pytest.raises(ValidationError):
        SourceVeracity.model_validate(bad)


def test_entity_round_trip() -> None:
    e = Entity.model_validate(
        {
            "id": "BTC",
            "domain": "crypto",
            "namespace": "spot",
            "metadata_json": {"exchange": "binance"},
            "active": True,
            "created_at": "2026-04-20T00:00:00",
            "updated_at": "2026-04-20T00:00:00",
        }
    )
    assert e.id == "BTC"
    assert e.metadata_json == {"exchange": "binance"}


def test_counter_scenario_round_trip() -> None:
    c = CounterScenario(name="x", probability=0.3, mitigation="y")
    assert c.probability == 0.3
