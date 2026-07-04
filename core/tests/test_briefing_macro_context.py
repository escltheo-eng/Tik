"""Contexte macro dans le briefing + alerte bascule risk-off (port commit 3a78a22).

Feature de CONTEXTE STRICT (ADR-028/029/035/036/037) : résumé macro dans le
briefing Telegram + alerte à l'entrée/sortie du régime `risk_off`. Ne touche
JAMAIS combined_bias/veracity/direction (NO-GO inchangé).

Fixtures alignées sur la vraie structure des blobs Redis (macro_regime_ingester,
stablecoins_ingester, cross_asset_ingester, rate_probabilities_ingester).
"""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tik_core.notify.alerts import (
    MACRO_REGIME_KEY,
    RISK_STATE_KEY,
    _check_risk_flip,
    format_risk_flip_alert,
    should_alert_risk_flip,
)
from tik_core.notify.briefing import (
    _fmt_macro_context_lines,
    format_briefing,
    summarize_macro_context,
)

# --- Fixtures : structure réelle des blobs Redis ---
REGIME = {
    "risk_regime": {
        "risk_state": "risk_on",
        "stress_percentile": 0.27,
        "vix": {"value": 16.45},
        "hy_oas": {"value": 3.10},
    },
    "global_liquidity": {"regime": "neutral"},
    "net_liquidity": {"regime": "expansion"},  # doit être ignoré (global prioritaire)
}
STABLECOINS = {"trend": "contraction", "pct_30d": -2.68}
CROSS_ASSET = {"behavior": "risk_asset", "assets": [{"key": "sp500", "corr_recent": 0.442}]}
RATE_PROB = {
    "meetings": [
        {"date": "2026-07-29", "hold": 0.7011, "hike": 0.2989, "cut": 0.0},
        {"date": "2026-09-16", "hold": 0.5, "hike": 0.5, "cut": 0.0},
    ]
}


# ---------------- summarize_macro_context ----------------


def test_summarize_all_none_returns_none():
    assert summarize_macro_context(None, None, None, None) is None


def test_summarize_full_extracts_everything():
    out = summarize_macro_context(REGIME, STABLECOINS, CROSS_ASSET, RATE_PROB)
    assert out["risk_state"] == "risk_on"
    assert out["vix"] == 16.45
    assert out["stress_pct"] == 0.27
    # global_liquidity prioritaire sur net_liquidity
    assert out["liquidity_regime"] == "neutral"
    assert out["stable_trend"] == "contraction"
    assert out["stable_pct_30d"] == -2.68
    assert out["behavior"] == "risk_asset"
    assert out["corr_sp500"] == 0.442
    # 1re réunion FOMC seulement, issue la plus probable
    assert out["fomc_date"] == "2026-07-29"
    assert out["fomc_label"] == "maintien"
    assert out["fomc_prob"] == 0.7011


def test_summarize_falls_back_to_net_liquidity():
    regime = {"net_liquidity": {"regime": "expansion"}}
    out = summarize_macro_context(regime, None, None, None)
    assert out["liquidity_regime"] == "expansion"
    assert out.get("risk_state") is None


def test_summarize_ignores_unknown_states():
    regime = {"risk_regime": {"risk_state": "unknown"}}
    assert summarize_macro_context(regime, {"trend": "??"}, None, None) is None


# ---------------- _fmt_macro_context_lines ----------------


def test_fmt_macro_lines_none_and_empty():
    assert _fmt_macro_context_lines(None) == []
    # Un contexte entièrement vide ne produit pas de section orpheline
    empty = summarize_macro_context({"risk_regime": {}}, None, None, None)
    assert _fmt_macro_context_lines(empty) == []


def test_fmt_macro_lines_full():
    macro = summarize_macro_context(REGIME, STABLECOINS, CROSS_ASSET, RATE_PROB)
    text = "\n".join(_fmt_macro_context_lines(macro))
    assert "Contexte macro" in text
    assert "risk-on" in text
    assert "VIX 16" in text
    assert "27ᵉ centile" in text
    assert "contraction" in text  # stablecoins
    assert "actif risqué" in text
    assert "corr S&P +0.44" in text
    assert "FOMC 29/07 : maintien 70%" in text
    # Honnêteté : la section se déclare contexte, pas signal
    assert "pas un signal" in text


def test_fmt_macro_lines_partial_risk_only():
    macro = summarize_macro_context(REGIME, None, None, None)
    text = "\n".join(_fmt_macro_context_lines(macro))
    assert "Risque" in text
    assert "FOMC" not in text
    assert "stablecoins" not in text.lower()


# ---------------- format_briefing (intégration) ----------------


def _minimal_briefing_kwargs():
    return {
        "window": "🌍 Matin Europe",
        "now": datetime(2026, 7, 2, 6, 0, tzinfo=UTC),
        "btc": None,
        "gold": None,
        "tech": None,
        "climate": None,
        "events": [],
        "headlines": [],
    }


def test_format_briefing_includes_macro_section():
    macro = summarize_macro_context(REGIME, STABLECOINS, CROSS_ASSET, RATE_PROB)
    text = format_briefing(**_minimal_briefing_kwargs(), macro_ctx=macro)
    assert "🌡" in text
    assert "risk-on" in text


def test_format_briefing_without_macro_section():
    text = format_briefing(**_minimal_briefing_kwargs())
    assert "🌡" not in text


# ---------------- should_alert_risk_flip ----------------


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        ("risk_off", "risk_on", True),  # entrée en risk_off
        ("risk_off", "neutral", True),
        ("risk_on", "risk_off", True),  # sortie du risk_off
        ("neutral", "risk_off", True),
        ("neutral", "risk_on", False),  # bruit risk_on ↔ neutral
        ("risk_on", "neutral", False),
        ("risk_off", "risk_off", False),  # pas de changement
        ("risk_off", None, False),  # amorçage
        (None, "risk_on", False),
        ("unknown", "risk_off", False),  # état inconnu jamais alerté
    ],
)
def test_should_alert_risk_flip(current, previous, expected):
    assert should_alert_risk_flip(current, previous) is expected


# ---------------- format_risk_flip_alert ----------------


def test_format_risk_flip_into_risk_off():
    text = format_risk_flip_alert(
        current="risk_off", previous="risk_on", vix=28.3, hy_oas=4.51, stress_pct=0.85
    )
    assert "RISK-OFF" in text
    assert "risk-on → risk-off" in text
    assert "VIX 28.3" in text
    assert "spread HY 4.51%" in text
    assert "85ᵉ centile" in text
    assert "sizing ÷2" in text
    assert "pas une prédiction" in text


def test_format_risk_flip_out_of_risk_off():
    text = format_risk_flip_alert(
        current="neutral", previous="risk_off", vix=None, hy_oas=None, stress_pct=None
    )
    assert "sortie du risk-off" in text
    assert "se lève" in text
    # Aucune ligne de détail chiffré si les valeurs manquent → 4 lignes.
    assert "centile" not in text
    assert len(text.split("\n")) == 4


# ---------------- _check_risk_flip (IO, fake Redis) ----------------


class _KVRedis:
    """Fake Redis get/set minimal, stocke en dict."""

    def __init__(self, store: dict | None = None) -> None:
        self.store = dict(store or {})

    async def get(self, key):  # noqa: ANN001
        return self.store.get(key)

    async def set(self, key, value, ex=None):  # noqa: ANN001
        self.store[key] = value
        return True


def _regime_blob(risk_state: str) -> str:
    import json

    return json.dumps(
        {
            "risk_regime": {
                "risk_state": risk_state,
                "stress_percentile": 0.85,
                "vix": {"value": 28.3},
                "hy_oas": {"value": 4.51},
            }
        }
    )


_SETTINGS = SimpleNamespace(telegram_bot_token="x", telegram_chat_id="y")


@pytest.mark.asyncio
async def test_check_risk_flip_first_run_seeds_silently(monkeypatch):
    from tik_core.notify import alerts as al

    sent: list[str] = []

    async def _fake_send(token, chat, text):  # noqa: ANN001
        sent.append(text)
        return True

    monkeypatch.setattr(al, "send_message", _fake_send)
    redis = _KVRedis({MACRO_REGIME_KEY: _regime_blob("risk_off")})
    out = await _check_risk_flip(redis, _SETTINGS, dry_run=False)
    assert out is None
    assert sent == []
    assert redis.store[RISK_STATE_KEY] == "risk_off"  # amorcé sans alerter


@pytest.mark.asyncio
async def test_check_risk_flip_alerts_on_flip_and_updates_state(monkeypatch):
    from tik_core.notify import alerts as al

    sent: list[str] = []

    async def _fake_send(token, chat, text):  # noqa: ANN001
        sent.append(text)
        return True

    monkeypatch.setattr(al, "send_message", _fake_send)
    redis = _KVRedis({MACRO_REGIME_KEY: _regime_blob("risk_off"), RISK_STATE_KEY: "risk_on"})
    out = await _check_risk_flip(redis, _SETTINGS, dry_run=False)
    assert out is not None and "RISK-OFF" in out
    assert len(sent) == 1
    assert redis.store[RISK_STATE_KEY] == "risk_off"


@pytest.mark.asyncio
async def test_check_risk_flip_send_failure_keeps_state_for_retry(monkeypatch):
    from tik_core.notify import alerts as al

    async def _fake_send_fail(token, chat, text):  # noqa: ANN001
        return False

    monkeypatch.setattr(al, "send_message", _fake_send_fail)
    redis = _KVRedis({MACRO_REGIME_KEY: _regime_blob("risk_off"), RISK_STATE_KEY: "risk_on"})
    out = await _check_risk_flip(redis, _SETTINGS, dry_run=False)
    assert out is None
    # état non persisté → retenté au cycle suivant
    assert redis.store[RISK_STATE_KEY] == "risk_on"


@pytest.mark.asyncio
async def test_check_risk_flip_non_alertable_flip_updates_state(monkeypatch):
    from tik_core.notify import alerts as al

    sent: list[str] = []

    async def _fake_send(token, chat, text):  # noqa: ANN001
        sent.append(text)
        return True

    monkeypatch.setattr(al, "send_message", _fake_send)
    redis = _KVRedis({MACRO_REGIME_KEY: _regime_blob("neutral"), RISK_STATE_KEY: "risk_on"})
    out = await _check_risk_flip(redis, _SETTINGS, dry_run=False)
    assert out is None
    assert sent == []
    assert redis.store[RISK_STATE_KEY] == "neutral"  # suivi sans spam


@pytest.mark.asyncio
async def test_check_risk_flip_dry_run_writes_nothing(monkeypatch):
    from tik_core.notify import alerts as al

    async def _fake_send(token, chat, text):  # noqa: ANN001
        raise AssertionError("dry_run ne doit pas envoyer")

    monkeypatch.setattr(al, "send_message", _fake_send)
    redis = _KVRedis({MACRO_REGIME_KEY: _regime_blob("risk_off"), RISK_STATE_KEY: "risk_on"})
    out = await _check_risk_flip(redis, _SETTINGS, dry_run=True)
    assert out is not None and "RISK-OFF" in out
    assert redis.store[RISK_STATE_KEY] == "risk_on"  # aucun write
