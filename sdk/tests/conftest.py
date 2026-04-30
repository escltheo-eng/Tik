"""Fixtures partagées entre tests SDK."""

from typing import Any

import pytest


@pytest.fixture
def signal_payload() -> dict[str, Any]:
    """Payload JSON minimal valide d'un Signal côté core (cf. SignalOut)."""
    return {
        "id": "sig_001",
        "timestamp": "2026-04-30T12:00:00",
        "entity_id": "BTC",
        "horizon": "swing",
        "direction": "long",
        "confidence": 0.78,
        "veracity": 0.91,
        "hypothesis": "RSI sortant de zone de survente, MACD croisement haussier",
        "counter_scenarios": [
            {
                "name": "Cassure du support 60k",
                "probability": 0.25,
                "mitigation": "Surveiller volume vendeur > 1.5x moyenne 24h",
            },
            {
                "name": "Bull trap court terme",
                "probability": 0.20,
                "mitigation": "Confirmer breakout sur 4h, attendre clôture",
            },
        ],
        "evidence": [
            {"source": "binance_klines", "score": 0.9, "fact": "RSI=32 (survente)"},
            {"source": "fear_greed", "score": 0.7, "fact": "FG=18 extreme fear"},
        ],
        "triggers": [
            {"type": "rsi_oversold", "value": "32", "weight": 0.4},
            {"type": "macd_cross_up", "value": "bullish", "weight": 0.3},
        ],
        "sources_count": 3,
        "expiry": "2026-04-30T16:00:00",
        "advisory": {
            "bias_on_existing_positions": "hold",
            "macro_crash_warning": False,
            "notes": None,
        },
        "circuit_breaker_status": "ok",
    }
