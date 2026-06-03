"""Tests des helpers dérivés du briefing Telegram (ADR-023, observation).

Pur, sans IO : résumé du positionnement, label funding, rendu des lignes, et
présence/absence de la section dans format_briefing.
"""

from datetime import UTC, datetime

from tik_core.notify.briefing import (
    _fmt_derivatives_lines,
    _funding_label,
    format_briefing,
    summarize_derivatives,
)

SNAP = {
    "funding_rate": 3.958e-05,
    "open_interest_usd": 7.2e9,
    "long_account_global": 0.6887,
    "long_account_top": 0.6902,
}


class TestFundingLabel:
    def test_neutral(self):
        assert _funding_label(0.003) == "neutre"

    def test_longs_pay(self):
        assert _funding_label(0.03) == "longs paient"

    def test_longs_pay_high(self):
        assert _funding_label(0.08) == "longs paient, élevé"

    def test_shorts_pay_high(self):
        assert _funding_label(-0.06) == "shorts paient, élevé"


class TestSummarizeDerivatives:
    def test_none_input(self):
        assert summarize_derivatives(None) is None
        assert summarize_derivatives("nope") is None

    def test_no_usable_fields(self):
        assert summarize_derivatives({"mark_price": 67000}) is None

    def test_full_aligned(self):
        s = summarize_derivatives(SNAP)
        assert s is not None
        assert abs(s["funding_pct"] - 0.003958) < 1e-6
        assert s["funding_label"] == "neutre"
        assert s["long_pct_retail"] == 68.87
        assert abs(s["long_pct_top"] - 69.02) < 1e-9
        assert s["divergent"] is False  # 0.6887 vs 0.6902 → écart < 5 pts

    def test_divergent(self):
        s = summarize_derivatives(
            {"funding_rate": 1e-4, "long_account_global": 0.75, "long_account_top": 0.55}
        )
        assert s["divergent"] is True  # écart 20 pts ≥ 5

    def test_only_funding(self):
        s = summarize_derivatives({"funding_rate": 1e-4})
        assert s is not None
        assert s["long_pct_retail"] is None
        assert s["divergent"] is None


class TestFmtDerivativesLines:
    def test_empty_when_none(self):
        assert _fmt_derivatives_lines(None) == []

    def test_full(self):
        lines = _fmt_derivatives_lines(summarize_derivatives(SNAP))
        joined = "\n".join(lines)
        assert "Positionnement dérivés BTC" in joined
        assert "observation, pas un signal" in joined
        assert "funding" in joined
        assert "OI" in joined
        assert "longs 69% retail" in joined
        assert "(alignés)" in joined

    def test_divergent_flag(self):
        lines = _fmt_derivatives_lines(
            summarize_derivatives(
                {"long_account_global": 0.75, "long_account_top": 0.55}
            )
        )
        assert "divergent" in "\n".join(lines)


class TestFormatBriefingIntegration:
    def _base_kwargs(self):
        return {
            "window": "🌍 Matin Europe",
            "now": datetime(2026, 6, 3, 6, 0, tzinfo=UTC),
            "btc": None,
            "gold": None,
            "tech": None,
            "climate": {"bull": 0, "bear": 0, "neutral": 0, "tilt": None},
            "events": [],
            "headlines": [],
        }

    def test_section_present_with_deriv(self):
        text = format_briefing(**self._base_kwargs(), deriv=summarize_derivatives(SNAP))
        assert "Positionnement dérivés BTC" in text
        assert "Contexte, pas prédiction" in text  # footer toujours là

    def test_section_absent_without_deriv(self):
        text = format_briefing(**self._base_kwargs())
        assert "Positionnement dérivés" not in text
