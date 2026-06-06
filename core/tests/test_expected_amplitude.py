"""Tests de l'amplitude attendue (volatilité) — ADR-025.

L'amplitude attendue = volatilité réalisée typique sur l'horizon
(`indicators.median_abs_return_pct`), exposée via `advisory.expected_amplitude_pct`
+ `advisory.ref_price`. C'est du CONTEXTE de volatilité (« de combien ça bouge »),
PAS une prévision du sens : Tik n'a aucun edge directionnel mesuré (go/no-go
2026-05-27). Ces tests verrouillent :

1. le calcul du helper (médiane des |variations| sur N barres) ;
2. le fait que les deux champs `advisory` traversent bien la sérialisation
   `SignalOut` (sinon Pydantic les droppe silencieusement — le bug qu'on évite
   en les déclarant dans le schéma `Advisory`).
"""

import json

import pandas as pd

from tik_core.scoring.indicators import median_abs_return_pct
from tik_core.storage.schemas import Advisory, SignalOut

# =====================================================================
# median_abs_return_pct — calcul pur
# =====================================================================


def test_amplitude_constant_growth_1bar():
    # +10% à chaque pas → médiane des |variations| 1-barre = 10.0%
    close = pd.Series([100.0, 110.0, 121.0])
    assert median_abs_return_pct(close, 1) == 10.0


def test_amplitude_2bars_single_window():
    # pct_change(2) sur 3 points → une seule fenêtre (121/100 - 1 = 21%)
    close = pd.Series([100.0, 110.0, 121.0])
    assert median_abs_return_pct(close, 2) == 21.0


def test_amplitude_takes_absolute_value_on_down_moves():
    # Baisses de 10% → l'amplitude est positive (|variation|), pas le signe
    close = pd.Series([100.0, 90.0, 81.0])
    assert median_abs_return_pct(close, 1) == 10.0


def test_amplitude_median_is_robust_to_outlier():
    # 1%, 1%, 50% → médiane = 1.0% (la moyenne aurait été ~17%)
    close = pd.Series([100.0, 101.0, 102.01, 153.015])
    assert median_abs_return_pct(close, 1) == 1.0


def test_amplitude_none_when_not_enough_bars():
    assert median_abs_return_pct(pd.Series([100.0, 110.0]), 2) is None


def test_amplitude_none_on_empty_series():
    assert median_abs_return_pct(pd.Series([], dtype=float), 1) is None


# =====================================================================
# Sérialisation SignalOut.advisory — les champs ADR-025 doivent survivre
# =====================================================================


def test_advisory_amplitude_fields_default_none():
    adv = Advisory()
    assert adv.expected_amplitude_pct is None
    assert adv.ref_price is None


def test_signal_out_exposes_amplitude_from_advisory_dict():
    """Un dict advisory (comme produit par les moteurs) doit ressortir en JSON
    avec expected_amplitude_pct + ref_price — sinon Pydantic les droppe."""
    sig = SignalOut(
        id="TIK-SWING-BTC-X",
        timestamp="2026-06-06T10:00:00Z",
        entity_id="BTC",
        horizon="swing",
        direction="long",
        confidence=0.5,
        veracity=0.85,
        advisory={"expected_amplitude_pct": 2.34, "ref_price": 60000.0},
    )
    payload = json.loads(sig.model_dump_json())
    assert payload["advisory"]["expected_amplitude_pct"] == 2.34
    assert payload["advisory"]["ref_price"] == 60000.0


def test_signal_out_amplitude_absent_stays_none():
    sig = SignalOut(
        id="TIK-FLASH-BTC-X",
        timestamp="2026-06-06T10:00:00Z",
        entity_id="BTC",
        horizon="flash",
        direction="neutral",
        confidence=0.0,
        veracity=0.85,
    )
    payload = json.loads(sig.model_dump_json())
    assert payload["advisory"]["expected_amplitude_pct"] is None
    assert payload["advisory"]["ref_price"] is None
