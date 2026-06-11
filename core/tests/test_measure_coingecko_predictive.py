"""Tests purs pour `measure_coingecko_predictive` (fonctions sans IO réseau/Redis).

`btc_daily_closes` et `main` font de l'IO → non testés ici (validés en runtime
contre les vraies données le 2026-06-11). On couvre les deux fonctions pures :
`forward_pairs` (alignement + rendement forward) et `interpret` (sens de l'IC).
"""

from datetime import date

import pytest

from tik_core.scripts.measure_coingecko_predictive import forward_pairs, interpret


def test_forward_pairs_rendement_forward_1j():
    cg = {date(2026, 6, 1): 60.0, date(2026, 6, 2): 70.0}
    closes = {date(2026, 6, 1): 100.0, date(2026, 6, 2): 110.0, date(2026, 6, 3): 121.0}
    pairs = forward_pairs(cg, closes, 1)
    assert len(pairs) == 2
    assert pairs[0][0] == 60.0
    assert pairs[0][1] == pytest.approx(0.10)  # 110/100 - 1
    assert pairs[1][0] == 70.0
    assert pairs[1][1] == pytest.approx(0.10)  # 121/110 - 1


def test_forward_pairs_horizon_2j():
    cg = {date(2026, 6, 1): 60.0}
    closes = {date(2026, 6, 1): 100.0, date(2026, 6, 2): 110.0, date(2026, 6, 3): 130.0}
    pairs = forward_pairs(cg, closes, 2)
    assert pairs == [(60.0, pytest.approx(0.30))]  # 130/100 - 1


def test_forward_pairs_skip_si_pas_de_close_forward():
    # Pas de close à d+1 → jour exclu.
    assert forward_pairs({date(2026, 6, 1): 60.0}, {date(2026, 6, 1): 100.0}, 1) == []


def test_forward_pairs_skip_si_base_nulle_ou_absente():
    # Base à 0 → division impossible → exclu.
    assert forward_pairs(
        {date(2026, 6, 1): 60.0}, {date(2026, 6, 1): 0.0, date(2026, 6, 2): 110.0}, 1
    ) == []
    # up_pct présent mais close du jour absente → exclu.
    assert forward_pairs({date(2026, 6, 1): 60.0}, {date(2026, 6, 2): 110.0}, 1) == []


def test_interpret_zero_pas_de_pouvoir():
    assert "pas de pouvoir" in interpret(0.0)
    assert "pas de pouvoir" in interpret(-0.10)  # sous le seuil 0.15
    assert "pas de pouvoir" in interpret(0.14)


def test_interpret_signe():
    assert "trend-following" in interpret(0.30)  # IC>0 → foule haussière précède hausse
    assert "contrarian" in interpret(-0.30)  # IC<0 → foule haussière précède baisse


def test_interpret_none():
    assert interpret(None) == "n/a (trop peu de points)"
