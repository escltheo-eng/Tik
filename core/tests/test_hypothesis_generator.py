"""Tests unitaires du générateur d'hypothèse contextuel (ADR-012).

Couvre :
- render_template_hypothesis (helper synchrone)
- TemplateHypothesisGenerator (fallback historique)
- OllamaHypothesisGenerator (LLM local) — mocké via AsyncMock
- apply_llm_hypothesis (helper modes disabled/shadow/active)
- build_hypothesis_generator (factory + ping santé Ollama)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import httpx
import pytest

from tik_core.scoring.hypothesis_generator import (
    HypothesisGenerator,
    OllamaHypothesisGenerator,
    TemplateHypothesisGenerator,
    apply_llm_hypothesis,
    build_hypothesis_generator,
    render_template_hypothesis,
)


# ===== Stub decision (duck-typed) =====


@dataclass
class StubDecision:
    """Stub minimal duck-typé pour les tests, équivalent à
    SwingDecision/FlashDecision sans avoir à importer les engines."""

    entity_id: str = "BTC"
    direction: str = "long"
    confidence: float = 0.78
    veracity: float = 0.92
    evidence: list[dict] = field(default_factory=list)
    triggers: list[dict] = field(default_factory=list)
    counter_scenarios: list[dict] = field(default_factory=list)
    circuit_breaker_status: str = "ok"
    advisory: dict = field(default_factory=dict)
    hypothesis: str = "Original template hypothesis"


def _rich_decision() -> StubDecision:
    """Decision avec evidence + triggers + counter_scenarios remplis,
    mimant un signal swing BTC enrichi multi-overlay."""
    return StubDecision(
        entity_id="BTC",
        direction="long",
        confidence=0.78,
        veracity=0.92,
        evidence=[
            {"source": "binance_klines", "score": 0.90,
             "fact": "RSI14=62.0, EMA20/50=104500/103200, MACD=0.045"},
            {"source": "alternative_me_fng", "score": 0.65,
             "fact": "FG=65 (Greed)"},
            {"source": "google_news_rss", "score": 0.70,
             "fact": "News score=+0.40 (bull=18, bear=8 on 50 BTC titles)"},
            {"source": "reddit_btc", "score": 0.65,
             "fact": "Reddit retail score=+0.30 (bull=12, bear=4)"},
        ],
        triggers=[
            {"type": "ema_cross", "value": "EMA20 > EMA50 (uptrend)",
             "weight": 0.25},
            {"type": "rsi", "value": "RSI bullish 62.0", "weight": 0.10},
            {"type": "macd", "value": "MACD above signal", "weight": 0.10},
            {"type": "fear_greed", "value": "FG=65 (greed → contrarian bear)",
             "weight": 0.10},
        ],
        counter_scenarios=[
            {"name": "macro_shock", "probability": 0.15,
             "mitigation": "Monitor DXY spike and yield curve inversion"},
            {"name": "indicator_whipsaw", "probability": 0.20,
             "mitigation": "Confirm direction on multi-timeframe (1D trend)"},
        ],
        circuit_breaker_status="ok",
    )


# ===== render_template_hypothesis =====


def test_render_template_long():
    decision = StubDecision(direction="long", entity_id="BTC",
                            confidence=0.75, veracity=0.90)
    text = render_template_hypothesis(decision, "swing")
    assert "Swing" in text
    assert "long" in text
    assert "BTC" in text
    assert "0.75" in text
    assert "0.90" in text


def test_render_template_short_flash():
    decision = StubDecision(direction="short", entity_id="GOLD",
                            confidence=0.50, veracity=0.78)
    text = render_template_hypothesis(decision, "flash")
    assert text.startswith("Flash short on GOLD")
    assert "0.50" in text and "0.78" in text


# ===== TemplateHypothesisGenerator =====


async def test_template_generator_returns_template_text():
    gen = TemplateHypothesisGenerator()
    decision = _rich_decision()
    text = await gen.generate(decision, "swing")
    assert "Swing long on BTC" in text
    assert "0.78" in text
    assert "0.92" in text


async def test_template_generator_method_name():
    assert TemplateHypothesisGenerator().method_name == "template"


async def test_template_generator_aclose_noop():
    # Doit pouvoir être appelé sans planter
    await TemplateHypothesisGenerator().aclose()


async def test_template_generator_reset_batch_noop():
    # Doit pouvoir être appelé sans planter (no-op)
    TemplateHypothesisGenerator().reset_batch()


# ===== OllamaHypothesisGenerator — formatters =====


def test_format_triggers_empty():
    text = OllamaHypothesisGenerator._format_triggers([])
    assert text == "  (none)"


def test_format_triggers_populated():
    triggers = [
        {"type": "ema_cross", "value": "EMA20 > EMA50", "weight": 0.25},
        {"type": "rsi", "value": "RSI bullish 62.0", "weight": 0.10},
    ]
    text = OllamaHypothesisGenerator._format_triggers(triggers)
    assert "ema_cross (weight 0.25)" in text
    assert "EMA20 > EMA50" in text
    assert "rsi (weight 0.10)" in text


def test_format_evidence_with_outlier():
    evidence = [
        {"source": "binance_klines", "score": 0.90, "fact": "RSI=62"},
        {"source": "reddit_btc", "score": 0.65, "fact": "Score=+0.95",
         "is_outlier": True},
    ]
    text = OllamaHypothesisGenerator._format_evidence(evidence)
    assert "binance_klines (credibility 0.90)" in text
    assert "[OUTLIER]" in text
    assert "reddit_btc" in text


def test_format_counter_scenarios():
    scenarios = [
        {"name": "macro_shock", "probability": 0.15,
         "mitigation": "Monitor DXY"},
    ]
    text = OllamaHypothesisGenerator._format_counter_scenarios(scenarios)
    assert "macro_shock (probability 0.15)" in text
    assert "Monitor DXY" in text


def test_format_outliers_none():
    decision = _rich_decision()  # tous evidence sans is_outlier
    text = OllamaHypothesisGenerator._format_outliers(decision)
    assert text == ""


def test_format_outliers_present():
    decision = _rich_decision()
    decision.evidence[2]["is_outlier"] = True  # google_news_rss flagué
    text = OllamaHypothesisGenerator._format_outliers(decision)
    assert "outliers detected" in text
    assert "google_news_rss" in text


# ===== OllamaHypothesisGenerator — sanitize =====


def test_sanitize_strips_markdown():
    raw = "**Verdict** : long.\n## Section\nContent ```code```"
    cleaned = OllamaHypothesisGenerator._sanitize_output(raw)
    assert "**" not in cleaned
    assert "##" not in cleaned
    assert "```" not in cleaned


def test_sanitize_compacts_blank_lines():
    raw = "Line 1\n\n\n\nLine 2"
    cleaned = OllamaHypothesisGenerator._sanitize_output(raw)
    assert "\n\n\n" not in cleaned


# ===== OllamaHypothesisGenerator — validation =====


def test_is_valid_output_minimum():
    decision = StubDecision(direction="long", entity_id="BTC")
    text = "Long position on BTC. " * 13  # 4 mots × 13 = 52 mots > MIN 50
    assert OllamaHypothesisGenerator._is_valid_output(text, decision)


def test_is_valid_output_too_short():
    decision = StubDecision(direction="long", entity_id="BTC")
    text = "BTC long short."  # < 50 mots
    assert not OllamaHypothesisGenerator._is_valid_output(text, decision)


def test_is_valid_output_too_long():
    decision = StubDecision(direction="long", entity_id="BTC")
    text = "BTC long position " * 200  # > 400 mots
    assert not OllamaHypothesisGenerator._is_valid_output(text, decision)


def test_is_valid_output_missing_direction():
    decision = StubDecision(direction="long", entity_id="BTC")
    text = "BTC analysis showing strong indicators. " * 20  # ne contient pas "LONG"
    assert not OllamaHypothesisGenerator._is_valid_output(text, decision)


def test_is_valid_output_missing_entity_id():
    decision = StubDecision(direction="long", entity_id="BTC")
    text = "Long position recommended with high confidence. " * 10
    assert not OllamaHypothesisGenerator._is_valid_output(text, decision)


def test_is_valid_output_case_insensitive():
    decision = StubDecision(direction="long", entity_id="BTC")
    text = "Long btc position recommended " * 15
    assert OllamaHypothesisGenerator._is_valid_output(text, decision)


# ===== OllamaHypothesisGenerator — generate (mocked) =====


async def test_ollama_generate_success(monkeypatch):
    gen = OllamaHypothesisGenerator(url="http://x", model="llama3.2:3b")
    valid = (
        "Long swing position recommended on BTC with confidence 0.78 "
        "and veracity 0.92. " * 8
    )
    monkeypatch.setattr(gen, "_call_ollama", AsyncMock(return_value=valid))
    decision = _rich_decision()
    text = await gen.generate(decision, "swing")
    assert text.startswith("Long swing position recommended on BTC")
    assert gen._consecutive_failures == 0


async def test_ollama_generate_falls_back_on_http_error(monkeypatch):
    gen = OllamaHypothesisGenerator(url="http://x", model="llama3.2:3b")
    monkeypatch.setattr(
        gen, "_call_ollama",
        AsyncMock(side_effect=httpx.ConnectError("ollama down")),
    )
    decision = _rich_decision()
    text = await gen.generate(decision, "swing")
    # Doit retourner le template fallback
    assert "Swing long on BTC" in text
    assert gen._consecutive_failures == 1


async def test_ollama_generate_invalid_output_falls_back(monkeypatch):
    """Sortie LLM invalide (trop courte) → fallback template, mais sans
    incrémenter le compteur d'échecs (pas un problème réseau)."""
    gen = OllamaHypothesisGenerator(url="http://x", model="llama3.2:3b")
    monkeypatch.setattr(gen, "_call_ollama", AsyncMock(return_value="hi"))
    decision = _rich_decision()
    text = await gen.generate(decision, "swing")
    assert "Swing long on BTC" in text  # Fallback template
    assert gen._consecutive_failures == 0  # Compteur intact


async def test_ollama_circuit_breaker_opens_after_3_failures(monkeypatch):
    gen = OllamaHypothesisGenerator(url="http://x", model="llama3.2:3b")
    mock_call = AsyncMock(side_effect=httpx.ConnectError("down"))
    monkeypatch.setattr(gen, "_call_ollama", mock_call)
    decision = _rich_decision()

    for _ in range(3):
        await gen.generate(decision, "swing")

    assert mock_call.call_count == 3
    assert gen._batch_circuit_open is True

    # 4e appel : circuit ouvert → pas d'appel Ollama, fallback direct
    text = await gen.generate(decision, "swing")
    assert mock_call.call_count == 3  # inchangé
    assert "Swing long on BTC" in text


async def test_ollama_reset_batch_rearms_circuit(monkeypatch):
    gen = OllamaHypothesisGenerator(url="http://x", model="llama3.2:3b")
    mock_call = AsyncMock(side_effect=httpx.ConnectError("down"))
    monkeypatch.setattr(gen, "_call_ollama", mock_call)
    decision = _rich_decision()

    for _ in range(3):
        await gen.generate(decision, "swing")
    assert gen._batch_circuit_open is True

    gen.reset_batch()
    assert gen._batch_circuit_open is False
    assert gen._consecutive_failures == 0


async def test_ollama_method_name():
    gen = OllamaHypothesisGenerator(url="http://x", model="llama3.2:3b")
    assert gen.method_name == "ollama:llama3.2:3b"


async def test_ollama_strips_markdown_in_response(monkeypatch):
    gen = OllamaHypothesisGenerator(url="http://x", model="llama3.2:3b")
    raw_with_md = (
        "**Verdict**: long position on BTC with high confidence. " * 10
    )
    monkeypatch.setattr(gen, "_call_ollama", AsyncMock(return_value=raw_with_md))
    decision = _rich_decision()
    text = await gen.generate(decision, "swing")
    assert "**" not in text


# ===== apply_llm_hypothesis (helper) =====


async def test_apply_disabled_is_noop():
    decision = _rich_decision()
    original = decision.hypothesis
    gen = TemplateHypothesisGenerator()
    await apply_llm_hypothesis(decision, "swing", gen, mode="disabled")
    assert decision.hypothesis == original
    assert decision.advisory == {}


async def test_apply_with_none_generator_is_noop():
    decision = _rich_decision()
    original = decision.hypothesis
    await apply_llm_hypothesis(decision, "swing", None, mode="active")
    assert decision.hypothesis == original
    assert decision.advisory == {}


async def test_apply_shadow_stores_in_advisory():
    decision = _rich_decision()
    original = decision.hypothesis
    gen = TemplateHypothesisGenerator()
    await apply_llm_hypothesis(decision, "swing", gen, mode="shadow")
    # hypothesis NE doit PAS être modifié en mode shadow
    assert decision.hypothesis == original
    # mais l'advisory doit contenir le candidate LLM
    assert "llm_hypothesis_candidate" in decision.advisory
    assert "Swing long on BTC" in decision.advisory["llm_hypothesis_candidate"]


async def test_apply_active_replaces_hypothesis():
    decision = _rich_decision()
    original = decision.hypothesis
    gen = TemplateHypothesisGenerator()
    await apply_llm_hypothesis(decision, "swing", gen, mode="active")
    # hypothesis remplacée
    assert decision.hypothesis != original
    assert "Swing long on BTC" in decision.hypothesis
    # ancien template conservé pour audit
    assert decision.advisory["template_hypothesis"] == original


async def test_apply_handles_timeout():
    """Si generate() dépasse timeout_s, no-op (decision inchangée)."""
    decision = _rich_decision()
    original = decision.hypothesis

    class SlowGenerator(HypothesisGenerator):
        method_name = "slow"

        async def generate(self, decision, horizon):
            await asyncio.sleep(2.0)  # > timeout
            return "should never return"

    await apply_llm_hypothesis(
        decision, "swing", SlowGenerator(), mode="active", timeout_s=0.05
    )
    assert decision.hypothesis == original
    assert "template_hypothesis" not in decision.advisory


async def test_apply_handles_exception():
    """Si generate() raise, no-op (decision inchangée)."""
    decision = _rich_decision()
    original = decision.hypothesis

    class FailingGenerator(HypothesisGenerator):
        method_name = "failing"

        async def generate(self, decision, horizon):
            raise RuntimeError("boom")

    await apply_llm_hypothesis(
        decision, "swing", FailingGenerator(), mode="active"
    )
    assert decision.hypothesis == original
    assert "template_hypothesis" not in decision.advisory


async def test_apply_unknown_mode_is_noop():
    decision = _rich_decision()
    original = decision.hypothesis
    gen = TemplateHypothesisGenerator()
    await apply_llm_hypothesis(decision, "swing", gen, mode="bogus")
    assert decision.hypothesis == original


async def test_apply_handles_advisory_not_dict():
    """Si decision.advisory n'est pas un dict (ex: None), on le réinitialise."""
    decision = _rich_decision()
    decision.advisory = None  # type: ignore[assignment]
    gen = TemplateHypothesisGenerator()
    await apply_llm_hypothesis(decision, "swing", gen, mode="shadow")
    assert isinstance(decision.advisory, dict)
    assert "llm_hypothesis_candidate" in decision.advisory


# ===== build_hypothesis_generator (factory) =====


async def test_build_template_type():
    gen = await build_hypothesis_generator(
        generator_type="template",
        ollama_url="http://x",
        ollama_model="any",
    )
    assert isinstance(gen, TemplateHypothesisGenerator)


async def test_build_ollama_alive_with_model(monkeypatch):
    """Ollama répond + modèle dispo → OllamaHypothesisGenerator."""
    fake_data = {"models": [{"name": "llama3.2:3b"}, {"name": "other"}]}

    class _MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return fake_data

    class _MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    gen = await build_hypothesis_generator(
        generator_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
    )
    assert isinstance(gen, OllamaHypothesisGenerator)


async def test_build_ollama_unreachable_falls_back(monkeypatch):
    """Ping Ollama échoue → fallback Template."""

    class _FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx, "AsyncClient", _FailingClient)
    gen = await build_hypothesis_generator(
        generator_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
    )
    assert isinstance(gen, TemplateHypothesisGenerator)


async def test_build_ollama_model_missing_falls_back(monkeypatch):
    """Ollama répond mais le modèle demandé n'est pas listé → fallback."""
    fake_data = {"models": [{"name": "other-model"}]}

    class _MockResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return fake_data

    class _MockClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            return _MockResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    gen = await build_hypothesis_generator(
        generator_type="ollama",
        ollama_url="http://x",
        ollama_model="llama3.2:3b",
    )
    assert isinstance(gen, TemplateHypothesisGenerator)
