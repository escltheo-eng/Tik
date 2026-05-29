"""Tests structurels du contenu éducatif curé (macro_mechanisms).

On ne juge pas la « vérité » du contenu (consensus macro, hors scope test) ;
on verrouille la STRUCTURE + la présence systématique du caveat régime
(garde-fou anti-mythe « X monte donc Y chute »).
"""

from tik_core.aggregator.macro_mechanisms import (
    GENERIC_MECHANISM,
    MECHANISMS,
    MacroMechanism,
    get_mechanism,
)


def test_all_mechanisms_well_formed():
    for code, mech in MECHANISMS.items():
        assert isinstance(mech, MacroMechanism)
        assert mech.event_code == code
        assert mech.one_liner.strip()
        assert mech.mechanism.strip()
        assert len(mech.assets_in_play) >= 2
        # Garde-fou : chaque fiche DOIT rappeler la régime-dépendance.
        low = mech.regime_caveat.lower()
        assert "tendances" in low or "régime" in low


def test_core_events_present():
    for code in ("CPI", "NFP", "FOMC_MEETING", "PPI", "GDP"):
        assert code in MECHANISMS


def test_get_mechanism_known():
    assert get_mechanism("CPI").event_code == "CPI"


def test_get_mechanism_fallback_to_generic():
    assert get_mechanism("EVENT_INCONNU") is GENERIC_MECHANISM


def test_generic_has_caveat():
    assert "régime" in GENERIC_MECHANISM.regime_caveat.lower() or "TENDANCES" in (
        GENERIC_MECHANISM.regime_caveat
    )
