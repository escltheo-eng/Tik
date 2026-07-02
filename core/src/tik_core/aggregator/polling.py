"""Intervalles de polling des ingesters — source unique de vérité (audit 2026-07-02, T2).

Historiquement, chaque intervalle était un littéral dans `scripts/run_ingesters.py`, et
`metrics/source_health.py` dupliquait implicitement ces valeurs dans ses `max_age_s`.
Les deux ont divergé : le Bug 15 (2026-06-11) a fait passer CryptoCompare d'un polling
horaire à 12 h pour tenir le quota gratuit (100 req/mois), sans resynchroniser le
moniteur resté à `max_age_s=3h` → fausse alerte critique quasi permanente dès le
retour du quota (constat M-1 de l'audit 2026-07-02).

Ce module centralise donc les intervalles pour que :
- `run_ingesters.py` les consomme (plus aucun littéral local à désynchroniser) ;
- `source_health.py` puisse être croisé en test avec ces valeurs
  (règle `max_age_s ≥ 3× l'intervalle`, cf. `tests/test_polling_intervals.py`) ;
- les intervalles anti-quota soient verrouillés comme invariants opérationnels.

⚠ Certains intervalles sont des INVARIANTS ANTI-QUOTA (Bug 15), pas des réglages
de confort :
- `cryptocompare_news` : 12 h = 2 req/jour ≈ 60 req/mois < plafond gratuit 100/mois
  (l'ancien polling horaire ≈ 720 req/mois condamnait le quota chaque mois) ;
- `gdelt_gold` : 2 h — GDELT free rate-limite (429 ~75 % du temps, mesuré 2026-06-11).
Les baisser ré-introduit le Bug 15 ; le verrou vit dans `tests/test_polling_intervals.py`.

Convention de nommage : quand la source est surveillée par
`metrics/source_health.py`, la clé du dict reprend EXACTEMENT le `SourceSpec.name`
correspondant (c'est ce qui permet le croisement automatique en test). Les
ingesters non surveillés (calendriers, macro…) ont une clé libre.

Absents volontairement du dict :
- `price_btc` : flux WebSocket Binance continu, pas de polling ;
- breaking news : gaté par toggle, intervalle propre dans `breaking_news_ingester.py`
  (INTERVAL_S) et hors périmètre `source_health`.
"""

from __future__ import annotations

_H = 3600

# Source unique de vérité des intervalles de polling (secondes), consommée par
# run_ingesters.py. Toute modification ici doit passer les verrous de
# tests/test_polling_intervals.py (règle 3× de source_health + anti-quota Bug 15).
INGESTER_INTERVALS_S: dict[str, int] = {
    # --- Flux prix ---
    "price_gold": 60,  # YahooPoller GC=F (upstream délai 15 min, cf. source_health)
    # --- Overlays sentiment / news (noms = SourceSpec.name) ---
    "fear_greed": _H,
    # INVARIANT ANTI-QUOTA (Bug 15) : 12 h = ~60 req/mois < plafond gratuit 100/mois.
    "cryptocompare_news": 12 * _H,
    "google_news_btc": 30 * 60,
    "google_news_gold": 30 * 60,
    "reddit_btc": 30 * 60,  # IP-ban en cours (Bug 11) mais l'ingester tourne
    # INVARIANT ANTI-QUOTA : GDELT free rate-limite (429 ~75 %, mitigation 2026-06-11).
    "gdelt_gold": 2 * _H,
    # --- Shadows (collectés, non branchés aux moteurs) ---
    "coingecko_btc": _H,
    "polymarket_btc": _H,
    "polymarket_gold": _H,
    "binance_derivatives_btc": _H,
    "btc_etf_flows": 6 * _H,
    "tradingview_ta": 30 * 60,
    # --- Macro / calendriers (non surveillés par source_health) ---
    "fred_macro": _H,
    "macro_regime": 6 * _H,
    "rate_probabilities": 6 * _H,
    "cftc_cot": 24 * _H,
    "fred_calendar": 24 * _H,
    "macro_static": 24 * _H,
}
