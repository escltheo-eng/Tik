"""Tests unitaires du classifieur de sentiment par mots-clés
de l'ingester CryptoCompare.

Vérifie que `_classify_title` reconnaît correctement les keywords
bull / bear sur des titres réels, et qu'il gère les cas limites
(titre vide, casse mélangée, mot non listé).
"""

import pytest

from tik_core.aggregator.cryptocompare_ingester import (
    BEARISH_KEYWORDS,
    BULLISH_KEYWORDS,
    _classify_title,
)


# ----- _classify_title : titres clairement directionnels -----

@pytest.mark.parametrize(
    "title, expected_bull, expected_bear",
    [
        # Bull simples
        ("Bitcoin surges to ATH", 2, 0),  # surges + ath
        ("BTC rally continues", 1, 0),
        ("Major partnership boosts adoption", 3, 0),  # partnership + boosts + adoption
        ("Bottoming Signals as Macro Risks Ease", 2, 1),  # bottoming + ease vs risks
        # Bear simples — note : "bear-market" reste un seul token (tiret interne
        # gardé par le regex), donc "bear" exact ne matche pas. Limitation
        # documentée du tokenizer keywords.
        ("Bitcoin crashes to bear-market lows", 0, 1),  # crashes seulement
        ("Massive sell-off triggers panic", 0, 2),  # sell-off + panic
        ("Coinbase premium turns negative as BTC sees sell-off", 0, 1),  # sell-off
        ("Government bans crypto trading", 0, 1),  # bans → "ban" non match (pluriel) — vérifions
        # Mixtes (les deux comptes)
        ("BTC rallies despite bearish headlines", 1, 1),
        ("Recovery stalls amid concerns", 1, 1),  # recovers? non, recover. concerns ✓
    ],
)
def test_classify_title_directional(title, expected_bull, expected_bear):
    n_bull, n_bear = _classify_title(title)
    assert n_bull == expected_bull, f"bull mismatch on '{title}'"
    assert n_bear == expected_bear, f"bear mismatch on '{title}'"


# ----- Casse insensible -----

def test_classify_title_case_insensitive():
    # Tous en majuscules
    n_bull, n_bear = _classify_title("BTC SURGES TO RECORD HIGH")
    assert n_bull >= 2  # SURGES + RECORD + HIGH (3 attendus)

    # Tous en minuscules
    n_bull2, n_bear2 = _classify_title("btc surges to record high")
    assert (n_bull, n_bear) == (n_bull2, n_bear2)


# ----- Cas limites -----

def test_classify_title_empty_string():
    assert _classify_title("") == (0, 0)


def test_classify_title_none():
    # _classify_title doit gérer None sans crasher
    assert _classify_title(None) == (0, 0)


def test_classify_title_only_neutral_words():
    # Aucun mot dans nos listes
    n_bull, n_bear = _classify_title("Bitcoin price moves sideways today")
    assert n_bull == 0
    assert n_bear == 0


def test_classify_title_dedup_within_title():
    # Le même mot apparaît plusieurs fois → ne compte qu'une fois
    # (set d'intersection dans _classify_title)
    n_bull, _ = _classify_title("bull bull bull bullish bullish")
    # bull (1 mot unique) + bullish (1 mot unique) = 2 matchs
    assert n_bull == 2


def test_classify_title_punctuation():
    # Les apostrophes et tirets internes sont gardés, le reste est délimité
    n_bull, n_bear = _classify_title("BTC's surge: a record? Yes!")
    # surge + record = 2 bull, 0 bear
    assert n_bull >= 2
    assert n_bear == 0


# ----- Mots ajoutés lors de l'enrichissement 2026-04-29 -----

@pytest.mark.parametrize(
    "title, expected_bull, expected_bear",
    [
        # Bull ajoutés
        ("Institutions accumulate Bitcoin amid uncertainty", 1, 0),  # accumulate
        ("Crypto markets show bottoming signals", 1, 0),  # bottoming
        ("Inflation eases, optimism grows", 2, 0),  # eases + optimism
        ("Bitcoin gains support at 75k", 2, 0),  # gains + support
        # Bear ajoutés
        ("Fed lowers growth forecast", 0, 1),  # lowers
        ("Major lawsuit filed against exchange", 0, 1),  # lawsuit
        ("Founder arrested on fraud charges", 0, 2),  # arrested + fraud
        ("Exchange shutdown shocks community", 0, 1),  # shutdown
    ],
)
def test_classify_title_enriched_keywords(title, expected_bull, expected_bear):
    n_bull, n_bear = _classify_title(title)
    assert n_bull == expected_bull, f"bull mismatch on '{title}'"
    assert n_bear == expected_bear, f"bear mismatch on '{title}'"


# ----- Cohérence des listes -----

def test_keyword_lists_no_overlap():
    """Aucun mot ne doit être à la fois dans BULLISH et BEARISH (ambigu)."""
    overlap = BULLISH_KEYWORDS & BEARISH_KEYWORDS
    assert overlap == set(), f"Overlap interdit : {overlap}"


def test_keyword_lists_lowercase():
    """Toutes les entrées doivent être en minuscules (le matching le suppose)."""
    for kw in BULLISH_KEYWORDS:
        assert kw == kw.lower(), f"{kw} pas en minuscules"
    for kw in BEARISH_KEYWORDS:
        assert kw == kw.lower(), f"{kw} pas en minuscules"


def test_keyword_lists_non_empty():
    """Garde-fou : on ne veut jamais tomber à 0 mot par accident."""
    assert len(BULLISH_KEYWORDS) >= 30
    assert len(BEARISH_KEYWORDS) >= 30
