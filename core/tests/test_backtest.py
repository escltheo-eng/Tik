"""Tests unitaires des helpers de scoring du script de backtest.

Vérifie la logique de classification "succès / échec" et de calcul du
gain réel selon la direction prédite et le delta observé.
"""

import pytest

from tik_core.scripts.backtest import _gain_for, _success_for


# ----- _gain_for -----

@pytest.mark.parametrize(
    "direction, delta_pct, expected_gain",
    [
        # LONG : on profite directement du delta
        ("long", 2.0, 2.0),       # marché monte → gain = delta
        ("long", -1.5, -1.5),     # marché baisse → perte
        ("long", 0.0, 0.0),       # stable → 0
        # SHORT : on profite de l'inverse du delta
        ("short", 2.0, -2.0),     # marché monte → on perd notre short
        ("short", -1.5, 1.5),     # marché baisse → on gagne sur le short
        ("short", 0.0, 0.0),
        # NEUTRAL : "réussi" si stable, donc gain = -|delta|
        ("neutral", 2.0, -2.0),   # gros mouvement → loupé
        ("neutral", -1.5, -1.5),  # ditto en baisse
        ("neutral", 0.0, 0.0),    # marché stable → "réussi"
    ],
)
def test_gain_for(direction, delta_pct, expected_gain):
    assert _gain_for(direction, delta_pct) == expected_gain


# ----- _success_for -----

@pytest.mark.parametrize(
    "direction, delta_pct, threshold, expected_success",
    [
        # LONG : succès si delta > threshold
        ("long", 2.0, 0.5, True),
        ("long", 0.6, 0.5, True),
        ("long", 0.5, 0.5, False),  # strictement supérieur
        ("long", 0.3, 0.5, False),
        ("long", -1.0, 0.5, False),
        # SHORT : succès si delta < -threshold
        ("short", -2.0, 0.5, True),
        ("short", -0.6, 0.5, True),
        ("short", -0.5, 0.5, False),
        ("short", -0.3, 0.5, False),
        ("short", 1.0, 0.5, False),
        # NEUTRAL : succès si |delta| < threshold
        ("neutral", 0.3, 0.5, True),
        ("neutral", -0.3, 0.5, True),
        ("neutral", 0.0, 0.5, True),
        ("neutral", 0.5, 0.5, False),  # |0.5| < 0.5 = False
        ("neutral", 1.0, 0.5, False),
        ("neutral", -1.0, 0.5, False),
        # Threshold custom
        ("long", 0.2, 0.1, True),
        ("long", 0.05, 0.1, False),
    ],
)
def test_success_for(direction, delta_pct, threshold, expected_success):
    assert _success_for(direction, delta_pct, threshold) is expected_success
