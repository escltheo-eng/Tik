"""Verrous croisés polling ↔ surveillance des sources (audit 2026-07-02, constat M-1).

Deux garde-fous nés du Bug 15 (CryptoCompare : polling horaire → 12 h pour tenir le
quota gratuit 100 req/mois, sans resynchroniser `source_health`) :

1. `SOURCE_SPECS.max_age_s` doit rester ≥ 3× l'intervalle de polling réel — c'est la
   désynchronisation (spec à 3 h vs polling 12 h) qui aurait produit une fausse alerte
   critique quasi permanente sur `/metrics/source_health` dès le retour du quota,
   effet « cry wolf » masquant les vraies pannes.
2. Les intervalles anti-quota eux-mêmes sont des invariants opérationnels : les
   baisser ré-introduit l'explosion de quota du Bug 15.

Ces tests croisent le registre `INGESTER_INTERVALS_S` (aggregator/polling.py, source
unique de vérité consommée par run_ingesters.py) avec `SOURCE_SPECS`
(metrics/source_health.py) : toute future désynchronisation casse la CI au lieu de
casser la prod.
"""

from __future__ import annotations

from tik_core.aggregator.polling import INGESTER_INTERVALS_S
from tik_core.metrics.source_health import SOURCE_SPECS

_H = 3600

# Sources surveillées dont le polling est connu : le croisement automatique repose sur
# l'égalité des noms (SourceSpec.name == clé du dict). Ce set fige la couverture
# minimale attendue — si quelqu'un renomme une clé d'un côté, le croisement ne doit
# pas se réduire silencieusement.
EXPECTED_CROSS_CHECKED = {
    "fear_greed",
    "cryptocompare_news",
    "google_news_btc",
    "google_news_gold",
    "gdelt_gold",
    "reddit_btc",
    "coingecko_btc",
    "polymarket_btc",
    "polymarket_gold",
    "binance_derivatives_btc",
    "btc_etf_flows",
    "price_gold",
}


class TestRegistrySanity:
    def test_intervals_are_positive_ints(self):
        for name, interval in INGESTER_INTERVALS_S.items():
            assert isinstance(interval, int) and interval > 0, (
                f"{name} : intervalle invalide ({interval!r})"
            )

    def test_expected_names_present_on_both_sides(self):
        spec_names = {s.name for s in SOURCE_SPECS}
        missing_in_specs = EXPECTED_CROSS_CHECKED - spec_names
        missing_in_intervals = EXPECTED_CROSS_CHECKED - set(INGESTER_INTERVALS_S)
        assert not missing_in_specs, (
            f"sources attendues absentes de SOURCE_SPECS : {sorted(missing_in_specs)}"
        )
        assert not missing_in_intervals, (
            f"sources attendues absentes de INGESTER_INTERVALS_S : "
            f"{sorted(missing_in_intervals)} — clé renommée ? le croisement "
            "max_age_s vs polling ne les protège plus"
        )

    def test_price_btc_has_no_polling_interval(self):
        # Flux WS Binance continu : pas de polling, donc pas d'entrée dans le dict
        # (sa fraîcheur est surveillée via max_age_s=10 min dans SOURCE_SPECS).
        assert "price_btc" not in INGESTER_INTERVALS_S


class TestMaxAgeVsPollingInterval:
    def test_max_age_at_least_3x_polling_interval(self):
        """Règle 3× : tolérer ≥ 2 cycles manqués avant d'alerter (pas de faux positif).

        C'est exactement le trou qui a laissé passer le constat M-1 de l'audit
        2026-07-02 : le Bug 15 a porté le polling CryptoCompare de 1 h à 12 h sans
        que `max_age_s` (3 h) ne suive → « stale » ~75 % du temps en fonctionnement
        NOMINAL. Tout futur changement d'intervalle sans resynchronisation de
        `source_health` doit échouer ici.
        """
        cross_checked = [s for s in SOURCE_SPECS if s.name in INGESTER_INTERVALS_S]
        assert {s.name for s in cross_checked} >= EXPECTED_CROSS_CHECKED
        for spec in cross_checked:
            interval = INGESTER_INTERVALS_S[spec.name]
            assert spec.max_age_s >= 3 * interval, (
                f"{spec.name} : max_age_s={spec.max_age_s}s < 3× le polling réel "
                f"({interval}s) → fausse alerte stale en fonctionnement nominal "
                "(cf. audit 2026-07-02 M-1). Resynchroniser source_health.py avec "
                "aggregator/polling.py."
            )


class TestAntiQuotaInvariants:
    """Les intervalles anti-quota sont des invariants opérationnels, pas du réglage.

    Référence : Bug 15 (2026-06-11) — le free tier CryptoCompare est tombé à
    100 req/mois (rebrand CoinDesk) et le polling horaire (~720 req/mois) condamnait
    le quota chaque mois, privant BTC swing de son 3e overlay pendant des semaines.
    """

    def test_cryptocompare_interval_respects_free_tier_quota(self):
        assert INGESTER_INTERVALS_S["cryptocompare_news"] >= 8 * _H, (
            "Bug 15 : le free tier CryptoCompare est limité à 100 req/mois. "
            "Un polling < 8 h explose le quota (1 h ≈ 720 req/mois = 7× la limite) "
            "et prive BTC swing de son overlay news jusqu'au reset mensuel. "
            "Ne PAS baisser cet intervalle sans vérifier le quota réel "
            "(GET min-api.cryptocompare.com/stats/rate/limit)."
        )

    def test_gdelt_interval_respects_rate_limit(self):
        assert INGESTER_INTERVALS_S["gdelt_gold"] >= 2 * _H, (
            "Bug 15 (même famille de problème) : GDELT free rate-limite l'IP "
            "(429 ~75 % du temps, mesuré 2026-06-11). Le polling a été porté à 2 h "
            "en mitigation (couplé au TTL Redis 6 h) — ne pas re-matraquer l'API."
        )
