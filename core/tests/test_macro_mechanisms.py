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


def test_all_calendar_event_codes_have_fiche():
    """Garde-fou : tous les event_codes émis par le calendrier (FRED Releases +
    statiques Phase B1/B2 FOMC/ECB/BoJ/BoE) DOIVENT avoir une fiche curée,
    sinon le chevron expand côté dashboard n'apparaît pas (régression UX
    découverte 2026-05-29 : RETAIL_SALES, INITIAL_CLAIMS, ECB_GC sans
    chevron). Si tu ajoutes un nouvel event au calendrier, ajoute aussi sa
    fiche ici, ou accepte explicitement le fallback GENERIC.
    """
    expected = {
        # FRED Releases (cf. macro_calendar_data.FRED_RELEASES)
        "NFP",
        "CPI",
        "PPI",
        "GDP",
        "RETAIL_SALES",
        "INDUSTRIAL_PRODUCTION",
        "INITIAL_CLAIMS",
        # Statiques Phase B1 + B2 (cf. macro_calendar_data static dates)
        "FOMC_MEETING",
        "ECB_GOVERNING_COUNCIL",
        "BOJ_MPM",
        "BOE_MPC",
    }
    missing = expected - set(MECHANISMS.keys())
    assert not missing, f"event_codes du calendrier sans fiche curée : {missing}"


def test_get_mechanism_known():
    assert get_mechanism("CPI").event_code == "CPI"


def test_get_mechanism_fallback_to_generic():
    assert get_mechanism("EVENT_INCONNU") is GENERIC_MECHANISM


def test_generic_has_caveat():
    assert "régime" in GENERIC_MECHANISM.regime_caveat.lower() or "TENDANCES" in (
        GENERIC_MECHANISM.regime_caveat
    )
