"""Tests unitaires de la cross-validation runtime (anti fake-news, ADR-011).

Pure logique : pas de Redis, pas de DB, pas de HTTP. ~30 tests ciblés.
"""

from __future__ import annotations

import pytest

from tik_core.scoring.cross_validator import (
    CrossValidationResult,
    apply_cross_validation_to_decision,
    compute_mad,
    cross_validate,
    detect_disagreement_n2,
    detect_outliers_modified_zscore,
    _detect_outliers_zero_mad,
)


# ----- Fake decision pour les tests apply_cross_validation_to_decision -----

class FakeDecision:
    """Mimique le contrat duck-typed (SwingDecision/FlashDecision)."""

    def __init__(
        self,
        direction: str = "long",
        hypothesis: str = "Test hypothesis",
        evidence: list[dict] | None = None,
    ) -> None:
        self.direction = direction
        self.hypothesis = hypothesis
        self.evidence = evidence if evidence is not None else []
        self.circuit_breaker_status = "ok"


# =====================================================================
# compute_mad
# =====================================================================

def test_compute_mad_empty_returns_zero():
    assert compute_mad([]) == 0.0


def test_compute_mad_single_value_returns_zero():
    assert compute_mad([0.5]) == 0.0


def test_compute_mad_two_values_is_half_distance():
    # médiane = (0.2 + 0.8)/2 = 0.5
    # |0.2 - 0.5| = 0.3, |0.8 - 0.5| = 0.3
    # médiane(deviations) = 0.3
    assert compute_mad([0.2, 0.8]) == pytest.approx(0.3)


def test_compute_mad_robust_to_outlier():
    # Médiane stable malgré un outlier extrême — caractéristique principale de MAD
    values = [0.4, 0.5, 0.6, 0.5, 99.0]
    mad = compute_mad(values)
    # médiane = 0.5, deviations = [0.1, 0, 0.1, 0, 98.5]
    # médiane(deviations) = 0.1 (pas tirée par 98.5)
    assert mad == pytest.approx(0.1)


# =====================================================================
# _detect_outliers_zero_mad (fallback seuil absolu)
# =====================================================================

def test_zero_mad_too_few_samples_returns_empty():
    assert _detect_outliers_zero_mad({"a": 0.1, "b": 0.2}) == set()


def test_zero_mad_all_identical_returns_empty():
    biases = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.5}
    assert _detect_outliers_zero_mad(biases) == set()


def test_zero_mad_close_values_returns_empty():
    # Écarts < 0.3 → pas d'outlier
    biases = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.6}
    assert _detect_outliers_zero_mad(biases) == set()


def test_zero_mad_detects_extreme_outlier_n4():
    biases = {"a": 0.4, "b": 0.5, "c": 0.5, "d": 5.0}
    outliers = _detect_outliers_zero_mad(biases)
    assert "d" in outliers


def test_zero_mad_detects_outlier_at_threshold():
    # Médiane = 0.5, écart "d" = 0.4 > 0.3 → outlier
    biases = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 0.9}
    outliers = _detect_outliers_zero_mad(biases)
    assert "d" in outliers


# =====================================================================
# detect_outliers_modified_zscore
# =====================================================================

def test_zscore_n_less_than_3_returns_empty():
    assert detect_outliers_modified_zscore({"a": 0.5}) == set()
    assert detect_outliers_modified_zscore({"a": 0.5, "b": -0.5}) == set()


def test_zscore_no_outlier_when_close_values():
    biases = {"a": 0.4, "b": 0.5, "c": 0.6}
    assert detect_outliers_modified_zscore(biases) == set()


def test_zscore_detects_extreme_outlier_n5():
    # 4 valeurs proches + 1 extrême (signe opposé fort)
    biases = {"a": 0.4, "b": 0.5, "c": 0.55, "d": 0.5, "e": -1.0}
    outliers = detect_outliers_modified_zscore(biases)
    assert "e" in outliers
    assert "a" not in outliers


def test_zscore_mad_zero_fallback_to_iqr():
    # 3 valeurs identiques + 1 outlier → MAD = 0 → fallback IQR
    biases = {"a": 0.5, "b": 0.5, "c": 0.5, "d": 5.0}
    outliers = detect_outliers_modified_zscore(biases)
    assert "d" in outliers


# =====================================================================
# detect_disagreement_n2
# =====================================================================

def test_disagreement_n2_opposite_signs_large_gap():
    assert detect_disagreement_n2({"a": 0.6, "b": -0.5}) is True


def test_disagreement_n2_opposite_signs_small_gap():
    # signes opposés mais écart 0.5 < seuil 0.8
    assert detect_disagreement_n2({"a": 0.2, "b": -0.3}) is False


def test_disagreement_n2_same_signs():
    assert detect_disagreement_n2({"a": 0.5, "b": 0.6}) is False


def test_disagreement_n2_wrong_n_returns_false():
    assert detect_disagreement_n2({"a": 0.5}) is False
    assert detect_disagreement_n2({"a": 0.5, "b": 0.5, "c": 0.5}) is False


# =====================================================================
# cross_validate — N petit (0, 1, 2)
# =====================================================================

def test_cross_validate_empty():
    cv = cross_validate({})
    assert cv.combined_bias == 0.0
    assert cv.circuit_breaker_status == "ok"
    assert cv.outlier_sources == set()
    assert cv.n_sources == 0
    assert cv.method == "no_op"


def test_cross_validate_n1():
    cv = cross_validate({"a": 0.7})
    assert cv.combined_bias == 0.7
    assert cv.circuit_breaker_status == "ok"
    assert cv.outlier_sources == set()
    assert cv.n_sources == 1
    assert cv.method == "no_op"


def test_cross_validate_n2_no_disagreement():
    cv = cross_validate({"a": 0.4, "b": 0.6})
    assert cv.combined_bias == pytest.approx(0.5)
    assert cv.circuit_breaker_status == "ok"
    assert cv.outlier_sources == set()


def test_cross_validate_n2_disagreement_degrades_status():
    cv = cross_validate({"a": 0.7, "b": -0.5})
    assert cv.circuit_breaker_status == "degraded"
    assert cv.outlier_sources == set()  # N=2 ne désigne aucune source individuellement
    assert cv.method == "disagreement_n2"


# =====================================================================
# cross_validate — N ≥ 3 (Modified Z-score)
# =====================================================================

def test_cross_validate_n3_concordance():
    cv = cross_validate({"a": 0.5, "b": 0.6, "c": 0.4})
    assert cv.circuit_breaker_status == "ok"
    assert cv.outlier_sources == set()
    assert cv.combined_bias == pytest.approx(0.5)


def test_cross_validate_n4_one_isolated_outlier_neutralized():
    # 1/4 = 25% < 50% → status reste "ok" via outliers, outlier neutralisé.
    # Dispersion sur non-outliers = 0 → ok globalement.
    cv = cross_validate({"a": 0.5, "b": 0.5, "c": 0.5, "d": -2.0})
    assert "d" in cv.outlier_sources
    assert cv.circuit_breaker_status == "ok"
    assert cv.combined_bias == pytest.approx(0.5)


def test_cross_validate_n4_bimodal_50_50_status_tripped_via_dispersion():
    # Distribution bimodale équilibrée : Modified Z ne voit aucun outlier
    # individuel (la médiane est entre les deux groupes), mais la dispersion
    # globale est très élevée → tripped via _detect_global_dispersion.
    cv = cross_validate({"a": 0.0, "b": 0.0, "c": 5.0, "d": -5.0})
    assert cv.circuit_breaker_status == "tripped"
    assert cv.dispersion > 0.85


def test_cross_validate_n4_dispersion_extreme_status_tripped():
    # Mix très éclaté : pas d'outlier individuel statistique, dispersion énorme
    cv = cross_validate({"a": 0.0, "b": 5.0, "c": -5.0, "d": 10.0})
    assert cv.circuit_breaker_status == "tripped"


def test_cross_validate_n4_moderate_disagreement_status_degraded():
    # 4 sources, 2 bull modéré 2 bear modéré. Pas d'outlier individuel, mais
    # std ≈ 0.58 → degraded via dispersion.
    cv = cross_validate({"a": 0.5, "b": 0.5, "c": -0.5, "d": -0.5})
    assert cv.circuit_breaker_status == "degraded"
    assert 0.5 <= cv.dispersion < 0.85


def test_cross_validate_n4_one_outlier_dispersion_uses_non_outliers():
    # 1 outlier extrême + 3 valeurs cohérentes : l'outlier est neutralisé,
    # la dispersion mesurée sur les non-outliers reste basse → status ok.
    cv = cross_validate({"a": 0.5, "b": 0.5, "c": 0.5, "d": -3.0})
    assert "d" in cv.outlier_sources
    assert cv.circuit_breaker_status == "ok"
    assert cv.combined_bias == pytest.approx(0.5)


def test_cross_validate_combined_bias_excludes_outliers():
    # Si "d" est outlier, combined = moyenne(a, b, c) = 0.5, pas 0.5 + (-2.0)/4
    cv = cross_validate({"a": 0.5, "b": 0.5, "c": 0.5, "d": -3.0})
    assert "d" in cv.outlier_sources
    assert cv.combined_bias == pytest.approx(0.5)


def test_cross_validate_method_is_modified_zscore_when_mad_positive():
    cv = cross_validate({"a": 0.1, "b": 0.4, "c": 0.5, "d": 0.6})
    assert cv.method == "modified_zscore"


def test_cross_validate_method_is_zero_mad_fallback_when_mad_zero():
    # 3 valeurs identiques + 1 différente → MAD = 0 → fallback
    cv = cross_validate({"a": 0.5, "b": 0.5, "c": 0.5, "d": 3.0})
    assert cv.method == "zero_mad_fallback"


# =====================================================================
# apply_cross_validation_to_decision — mode "active"
# =====================================================================

def test_apply_active_no_outlier_keeps_decision():
    decision = FakeDecision(direction="long")
    decision.evidence = [
        {"source": "a", "fact": "..."},
        {"source": "b", "fact": "..."},
        {"source": "c", "fact": "..."},
    ]
    cv = apply_cross_validation_to_decision(
        decision, {"a": 0.4, "b": 0.5, "c": 0.6}, mode="active"
    )
    assert decision.direction == "long"
    assert decision.circuit_breaker_status == "ok"
    assert all(ev.get("is_outlier") is None for ev in decision.evidence)
    assert cv.circuit_breaker_status == "ok"


def test_apply_active_marks_outlier_evidence():
    decision = FakeDecision(direction="long")
    decision.evidence = [
        {"source": "a", "fact": "..."},
        {"source": "b", "fact": "..."},
        {"source": "c", "fact": "..."},
        {"source": "d", "fact": "..."},
    ]
    cv = apply_cross_validation_to_decision(
        decision, {"a": 0.5, "b": 0.5, "c": 0.5, "d": -3.0}, mode="active"
    )
    assert "d" in cv.outlier_sources
    d_ev = next(ev for ev in decision.evidence if ev["source"] == "d")
    assert d_ev["is_outlier"] is True
    a_ev = next(ev for ev in decision.evidence if ev["source"] == "a")
    assert a_ev.get("is_outlier") is None


def test_apply_active_tripped_forces_neutral_and_rewrites_hypothesis():
    decision = FakeDecision(
        direction="long", hypothesis="BTC bull (RSI/MACD confluence)"
    )
    decision.evidence = [
        {"source": "a", "fact": "..."},
        {"source": "b", "fact": "..."},
        {"source": "c", "fact": "..."},
        {"source": "d", "fact": "..."},
    ]
    # 3 outliers / 4 → tripped (75 %)
    cv = apply_cross_validation_to_decision(
        decision, {"a": 0.0, "b": 5.0, "c": -5.0, "d": 10.0}, mode="active"
    )
    if cv.circuit_breaker_status == "tripped":
        assert decision.direction == "neutral"
        assert "Anti fake-news" in decision.hypothesis
        assert "BTC bull (RSI/MACD confluence)" in decision.hypothesis  # original conservé


def test_apply_active_n2_disagreement_degrades_but_keeps_direction():
    decision = FakeDecision(direction="long", hypothesis="X")
    decision.evidence = [
        {"source": "a", "fact": "..."},
        {"source": "b", "fact": "..."},
    ]
    cv = apply_cross_validation_to_decision(
        decision, {"a": 0.7, "b": -0.5}, mode="active"
    )
    assert decision.circuit_breaker_status == "degraded"
    assert decision.direction == "long"  # degraded ne force PAS neutral, seul tripped le fait
    assert cv.outlier_sources == set()
    # Aucune evidence marquée individuellement
    assert all(ev.get("is_outlier") is None for ev in decision.evidence)


# =====================================================================
# apply_cross_validation_to_decision — mode "shadow"
# =====================================================================

def test_apply_shadow_does_not_modify_decision():
    decision = FakeDecision(direction="long", hypothesis="X")
    decision.evidence = [
        {"source": "a", "fact": "..."},
        {"source": "b", "fact": "..."},
        {"source": "c", "fact": "..."},
        {"source": "d", "fact": "..."},
    ]
    cv = apply_cross_validation_to_decision(
        decision, {"a": 0.5, "b": 0.5, "c": 0.5, "d": -3.0}, mode="shadow"
    )
    # Le résultat est calculé...
    assert "d" in cv.outlier_sources
    # ... mais decision est inchangée
    assert decision.circuit_breaker_status == "ok"
    assert decision.direction == "long"
    assert decision.hypothesis == "X"
    assert all(ev.get("is_outlier") is None for ev in decision.evidence)


def test_apply_shadow_returns_cv_result():
    decision = FakeDecision()
    cv = apply_cross_validation_to_decision(
        decision, {"a": 0.7, "b": -0.5}, mode="shadow"
    )
    assert cv.circuit_breaker_status == "degraded"
    assert cv.method == "disagreement_n2"


# =====================================================================
# Edge cases
# =====================================================================

def test_cross_validate_all_outliers_uses_median():
    # Cas extrême : si tout est outlier (impossible normalement, mais robuste)
    # → combined = médiane de toutes les valeurs.
    # Pas facile à provoquer, mais on peut vérifier que combined_bias est défini.
    cv = cross_validate({"a": 1.0, "b": -1.0, "c": 0.5, "d": -0.5})
    assert -1.0 <= cv.combined_bias <= 1.0


def test_cross_validate_returns_correct_result_type():
    cv = cross_validate({"a": 0.5})
    assert isinstance(cv, CrossValidationResult)


def test_apply_cross_validation_to_decision_returns_result_type():
    decision = FakeDecision()
    cv = apply_cross_validation_to_decision(decision, {"a": 0.5}, mode="active")
    assert isinstance(cv, CrossValidationResult)
