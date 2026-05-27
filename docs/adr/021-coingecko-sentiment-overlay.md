# ADR-021 — Overlay sentiment CoinGecko (candidat 4e overlay BTC, SHADOW)

**Date** : 2026-05-27
**Statut** : ACCEPTÉ (overlay en SHADOW, désactivé par défaut)
**Implémenté dans** : Paquet 41

---

## Contexte

Depuis le déploiement HP, **Reddit est IP-banni** au niveau réseau (Bug 11,
CLAUDE.md section 9 + Paquet 27). Conséquence : BTC swing tourne avec **3/4
overlays sentiment** (Fear & Greed + CryptoCompare + Google News, sans Reddit).
Quand le FG diverge contrarian des news (cas typique en marché bear), il est
flaggé outlier par l'anti fake-news (ADR-011) → il reste 2 sources alignées +
1 outlier → dispersion structurelle → **veracity capée à 0.85-0.89, jamais
≥ 0.90** sur BTC swing (Garde-fou 2-bis transitoire 0.85, section 5).

Une demande d'unban Reddit est en cours (asynchrone, délai inconnu). En
attendant, on cherche à **restaurer un 4e overlay sentiment BTC** pour rétablir
la capacité de la veracity à atteindre ≥ 0.90 quand les sources concordent.

**Vérification de joignabilité depuis le VPS (mesurée 2026-05-27, engagement
#10 « mesurer plutôt que spéculer »)** — Reddit était bloqué au niveau réseau,
donc on ne fait plus confiance à une source sans l'avoir testée depuis le VPS :

| Candidat | HTTP | Verdict |
|---|---|---|
| Hacker News (Algolia) | 200 | Joignable **mais quasi vide** : 0 story BTC avec > 15 points sur 7 jours → injecterait du bruit/vide. **Écarté.** |
| StockTwits API | 403 | Bloqué/restreint. **Écarté.** |
| Bluesky recherche publique | 403 | Bloqué / auth requise. **Écarté.** |
| **CoinGecko** `/coins/bitcoin` | 200 | **Joignable**, sans clé. `sentiment_votes_up_percentage` exploitable. **Retenu.** |

Le créneau « sentiment **retail textuel** » de Reddit n'a donc **pas** de
remplaçant gratuit et joignable de qualité. CoinGecko fournit un signal
**numérique** (vote communautaire up/down %), pas du texte — c'est un substitut
*différent*, pas un clone de Reddit.

## Décisions

### D1 — Source = CoinGecko community sentiment (`sentiment_votes_up_percentage`)

Seul candidat libre, joignable et exploitable mesuré. Endpoint public sans clé
`GET /api/v3/coins/bitcoin?community_data=true`. Un appel/heure (sous les limites
du free tier). Coexiste avec Reddit : à son retour, BTC aurait 5 overlays — la
cross-validation ADR-011 s'adapte à N quelconque. CoinGecko ne serait retiré que
si la **mesure** prouve sa redondance (cf. caveat D4).

### D2 — Overlay en SHADOW, désactivé par défaut (toggle env)

Le pipeline (ADR-018) émet des signaux que l'utilisatrice consulte pour trader
**en ce moment** (NO-GO directionnel 2026-05-27, Tik = outil de contexte). On ne
branche pas un signal non mesuré dans le `combined_bias` live. Donc :

- L'**ingester** `CoinGeckoSentimentIngester` collecte dans Redis
  (`tik.sentiment.coingecko.btc` + historique cappé `tik.coingecko.btc.history`,
  HISTORY_MAX=2000 ≈ 83 j) dès maintenant.
- L'**overlay** `_enrich_with_coingecko` dans `swing_engine` est gaté par
  `settings.coingecko_overlay_enabled` (défaut **False**, env
  `TIK_COINGECKO_OVERLAY_ENABLED`). Tant qu'il est OFF, la clé Redis n'entre
  PAS dans le `combined_bias`/direction/veracity — log
  `swing.btc.coingecko_skipped_overlay_disabled`.

Pattern identique au toggle DXY/COT (ADR-018 amendement P2) : code conservé,
réversible sans redéploiement.

### D3 — Mapping contrarian PROVISOIRE (calqué sur Fear & Greed)

`_compute_coingecko_bias(up_pct)` : foule très haussière (up_pct élevé) →
contrarian bear ; foule capitulante (up_pct faible) → contrarian bull. 5 paliers
symétriques (≤30 → +1.0, ≤45 → +0.5, <55 → 0.0, <70 → −0.5, ≥70 → −1.0).
L'hypothèse contrarian est **à valider en shadow** — elle pourrait être
trend-following. Comme l'overlay est OFF, ce mapping n'affecte aucun signal ; il
ne servira qu'au moment de l'activation.

### D4 — Caveat à mesurer avant activation : corrélation Fear & Greed

CoinGecko up-vote % et Fear & Greed sont **deux jauges retail crudes** → risque
de forte corrélation. Si CoinGecko ne fait que recopier le FG, il n'ajoute
**aucune information indépendante** (ADR-004 veut des angles diversifiés) et
gonflerait artificiellement la concordance (donc la veracity) sans valeur réelle.
La phase shadow (~1 semaine d'historique) sert exactement à mesurer cette
divergence **avant** d'activer le toggle. Le score `coingecko_sentiment = 0.60`
(provisoire) reflète sa nature retail crude.

## Conséquences

**Positives** :
- Restaure un 4e overlay BTC candidat sans dépendre du retour de Reddit.
- Zéro impact sur les signaux émis tant que le toggle est OFF (sûr pendant le
  trading manuel actif).
- Accumule un historique mesurable → décision d'activation data-driven.
- Coexiste avec Reddit (pas un remplacement destructif).

**Négatives / limites** :
- CoinGecko est un **nombre**, pas du sentiment retail textuel → ne restaure pas
  l'angle exact de Reddit.
- Possible redondance avec FG (à mesurer, D4).
- NO-GO directionnel (2026-05-27) : « + de sources ≠ + d'edge ». Cet overlay ne
  prétend pas créer un edge ; il restaure une capacité de cross-validation.
- Mapping contrarian non validé (provisoire).
- Le scheduler doit être redémarré pour charger le code overlay ; tant que le
  toggle reste OFF, l'ancien et le nouveau code émettent des signaux identiques,
  donc le restart n'est requis qu'au moment de l'activation.

## Risques opérationnels rappelés

- **Garde-fou 1** (Tik shadow vs Zeta 3 mois) **inchangé**.
- **Garde-fou 2-bis transitoire** (veracity ≥ 0.85 BTC swing tant que Reddit
  IP-banni) **inchangé** tant que l'overlay est OFF. Si l'overlay est activé et
  qu'il restaure durablement la veracity ≥ 0.90, le critère de retour au seuil
  0.90 strict (section 5) devra être **réévalué** (le 4e overlay serait CoinGecko,
  pas Reddit — à documenter à ce moment-là).
- **ADR-003** (pas de bypass V01-V15) **inchangé** — Tik ne crée aucun ordre.
- **ADR-004** (multi-overlay) **respecté** — nouvel overlay via le pattern
  `_enrich_with_<source>` + une ligne (gatée) dans `analyze_swing_btc`.
- **ADR-011** (anti fake-news) **inchangé** — quand activé, le bias CoinGecko
  passera par la cross-validation comme les autres.
- **ADR-018** (Tik OSINT pur) **inchangé**.

## Mémoire pour instances Claude futures

- **NE PAS** activer le toggle `TIK_COINGECKO_OVERLAY_ENABLED=true` sans avoir
  mesuré la divergence CoinGecko vs Fear & Greed sur ≥ 1 semaine d'historique
  (`tik.coingecko.btc.history`). Si redondant → ne pas activer (voire retirer
  l'ingester de `run_ingesters.py`).
- **NE PAS** cristalliser le mapping contrarian sans mesure (IC Spearman / hit /
  gain vs marché).
- Activer = flip env `TIK_COINGECKO_OVERLAY_ENABLED=true` + restart scheduler
  (`redeploy.sh`). Désactiver = repasser à false + restart.
- CoinGecko et Reddit **coexistent** ; ne pas retirer l'un parce que l'autre
  revient — décision basée sur la mesure de valeur indépendante.
