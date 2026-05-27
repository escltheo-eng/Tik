"""Tests purs de l'instrument de mesure surprise macro (ForexFactory + FRED).

Aucune dépendance réseau/DB/Redis : on teste les helpers déterministes (parsing
du consensus, mapping de période, conversions d'unités FRED -> unité FF, surprise
relative). Les valeurs FRED utilisées comme oracles ont été vérifiées en live
le 2026-05-27 (curl FRED VPS).
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from tik_core.scripts.measure_forexfactory_surprise import (
    US_EVENT_MAP,
    _add_months,
    derive_actual,
    expected_reference_date,
    normalize_title,
    parse_macro_value,
    relative_surprise,
)


class TestParseMacroValue:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0.3%", 0.3),
            ("2.0%", 2.0),
            ("4.25%", 4.25),
            ("150K", 150.0),
            ("661K", 661.0),
            ("-3.8M", -3.8),
            ("96B", 96.0),
            ("91.9", 91.9),
            ("4", 4.0),
            ("-52", -52.0),
            ("1,234K", 1234.0),
            ("0.0%", 0.0),
        ],
    )
    def test_values(self, raw, expected):
        assert parse_macro_value(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["", None, "   ", "n/a", "tentative"])
    def test_empty_or_garbage(self, raw):
        assert parse_macro_value(raw) is None

    def test_m_of_month_not_taken_as_million(self):
        # Garde-fou leçon Polymarket : un 'M' suivi d'une lettre (mois) n'est PAS
        # un suffixe million. "5 May" -> 5.0 (le mois est ignoré), pas 5e6.
        assert parse_macro_value("5 May") == pytest.approx(5.0)
        assert parse_macro_value("84,000 May 25-31") == pytest.approx(84000.0)

    def test_suffix_must_be_adjacent_real(self):
        # Vrai suffixe collé au nombre -> pris comme unité (mais NON multiplié).
        assert parse_macro_value("1.5m") == pytest.approx(1.5)
        assert parse_macro_value("150k") == pytest.approx(150.0)


class TestNormalizeTitle:
    def test_lowercase_and_compact(self):
        assert normalize_title("  Core  PCE Price Index m/m ") == "core pce price index m/m"

    def test_none_empty(self):
        assert normalize_title(None) == ""
        assert normalize_title("") == ""

    def test_all_map_keys_are_normalized(self):
        # Toutes les clés du map doivent être leur propre forme normalisée
        for k in US_EVENT_MAP:
            assert normalize_title(k) == k


class TestAddMonths:
    @pytest.mark.parametrize(
        "d,n,expected",
        [
            (date(2026, 5, 1), -1, date(2026, 4, 1)),
            (date(2026, 1, 1), -1, date(2025, 12, 1)),
            (date(2026, 4, 1), -3, date(2026, 1, 1)),
            (date(2026, 1, 1), -12, date(2025, 1, 1)),
            (date(2026, 12, 1), 1, date(2027, 1, 1)),
            (date(2026, 3, 15), -1, date(2026, 2, 1)),  # ramène au 1er
        ],
    )
    def test_add(self, d, n, expected):
        assert _add_months(d, n) == expected


class TestExpectedReferenceDate:
    def _dt(self, s):
        return datetime.fromisoformat(s)

    def test_monthly_core_pce_may(self):
        # Core PCE release 2026-05-28 couvre avril -> ref 2026-04-01
        rel = self._dt("2026-05-28T08:30:00-04:00")
        assert expected_reference_date(rel, "monthly") == date(2026, 4, 1)

    def test_monthly_nfp_june(self):
        # NFP de mai publié début juin -> ref mai
        rel = self._dt("2026-06-05T08:30:00-04:00")
        assert expected_reference_date(rel, "monthly") == date(2026, 5, 1)

    def test_monthly_january_release_crosses_year(self):
        rel = self._dt("2026-01-09T08:30:00-04:00")
        assert expected_reference_date(rel, "monthly") == date(2025, 12, 1)

    def test_quarterly_prelim_gdp_may(self):
        # Prelim GDP release 2026-05-28 (Q2) -> dernier trim achevé Q1 -> 2026-01-01
        rel = self._dt("2026-05-28T08:30:00-04:00")
        assert expected_reference_date(rel, "quarterly") == date(2026, 1, 1)

    def test_quarterly_feb_release_is_q4_prev_year(self):
        rel = self._dt("2026-02-26T08:30:00-04:00")
        assert expected_reference_date(rel, "quarterly") == date(2025, 10, 1)

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            expected_reference_date(self._dt("2026-05-28T08:30:00-04:00"), "weekly")


class TestDeriveActual:
    def test_direct(self):
        obs = {date(2026, 1, 1): 2.0}
        assert derive_actual(obs, date(2026, 1, 1), "direct") == 2.0

    def test_direct_pending(self):
        obs = {date(2025, 10, 1): 0.5}
        assert derive_actual(obs, date(2026, 1, 1), "direct") is None

    def test_mom_pct_core_pce_march(self):
        # PCEPILFE 2026-03=129.279, 2026-02=128.901 -> ~0.2932 %
        obs = {date(2026, 3, 1): 129.279, date(2026, 2, 1): 128.901}
        assert derive_actual(obs, date(2026, 3, 1), "mom_pct") == pytest.approx(0.2932, abs=1e-3)

    def test_mom_pct_prev_missing(self):
        obs = {date(2026, 3, 1): 129.279}
        assert derive_actual(obs, date(2026, 3, 1), "mom_pct") is None

    def test_mom_pct_prev_zero(self):
        obs = {date(2026, 3, 1): 100.0, date(2026, 2, 1): 0.0}
        assert derive_actual(obs, date(2026, 3, 1), "mom_pct") is None

    def test_yoy_pct(self):
        obs = {date(2026, 4, 1): 332.407, date(2025, 4, 1): 320.0}
        assert derive_actual(obs, date(2026, 4, 1), "yoy_pct") == pytest.approx(3.877, abs=1e-2)

    def test_mom_diff_k_payems_april(self):
        # PAYEMS 2026-04=158736, 2026-03=158621 -> +115 (milliers)
        obs = {date(2026, 4, 1): 158736.0, date(2026, 3, 1): 158621.0}
        assert derive_actual(obs, date(2026, 4, 1), "mom_diff_k") == pytest.approx(115.0)

    def test_actual_pending_when_ref_absent(self):
        # Core PCE d'avril pas encore publié par FRED -> ref absent -> None (pas de faux positif)
        obs = {date(2026, 3, 1): 129.279, date(2026, 2, 1): 128.901}
        assert derive_actual(obs, date(2026, 4, 1), "mom_pct") is None

    def test_unknown_unit_raises(self):
        with pytest.raises(ValueError):
            derive_actual({date(2026, 1, 1): 1.0}, date(2026, 1, 1), "bogus")


class TestRelativeSurprise:
    def test_normal(self):
        # actual 0.5, forecast 0.3 -> (0.5-0.3)/0.3 = +0.6667
        assert relative_surprise(0.5, 0.3) == pytest.approx(0.6667, abs=1e-3)

    def test_sign_preserved_negative(self):
        assert relative_surprise(0.1, 0.3) < 0

    def test_forecast_zero(self):
        assert relative_surprise(1.2, 0.0) == 1.2


class TestUsEventMapIntegrity:
    def test_units_and_periods_valid(self):
        valid_units = {"direct", "mom_pct", "yoy_pct", "mom_diff_k"}
        valid_periods = {"monthly", "quarterly"}
        for _title, (series, period, unit) in US_EVENT_MAP.items():
            assert series and isinstance(series, str)
            assert period in valid_periods
            assert unit in valid_units
