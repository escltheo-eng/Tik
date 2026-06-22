# ADR-032 — Corrélations cross-asset (co-mouvement BTC, CONTEXTE)

**Date** : 2026-06-22
**Statut** : ACCEPTÉ (contexte read-only, non-enrôlé sur le `combined_bias`)
**Implémenté dans** :
- `core/src/tik_core/aggregator/cross_asset_ingester.py` (ingester + fonctions pures
  `parse_chart` / `aligned_returns` / `pearson` / `compute_cross_asset`)
- `core/src/tik_core/storage/schemas.py` (`CrossAssetCorrOut`, `CrossAssetOut`)
- `core/src/tik_core/api/macro.py` (endpoint `GET /api/v1/macro/cross_asset`)
- `core/src/tik_core/scripts/run_ingesters.py` (enregistrement, polling 6 h)
- `dashboard/components/cosmic/cosmic-cross-asset-card.tsx` (+ type `CrossAsset`,
  hook `useCrossAsset`, carte sur la page `/macro-cosmique`)

**Déclencheur** : choix trader (2026-06-22) — **4e et dernière** famille macro de
contexte du backlog (cf. mémoire `macro-backlog-next-families`), après stablecoins
(ADR-031).

---

## Contexte

Il manquait une lecture : **avec quoi le BTC co-bouge en ce moment ?** Se négocie-t-il
comme un actif risqué (suit les actions), comme l'or (refuge), ou de façon autonome ?
C'est une question de **régime de corrélation**, utile au contexte. Source : cours
journaliers **Yahoo Finance** (gratuit ; le même endpoint que le `YahooPoller` GOLD).

Symboles (joignabilité VPS vérifiée 2026-06-22, HTTP 200) : `BTC-USD` (base), `^GSPC`
(S&P 500), `^IXIC` (Nasdaq), `GC=F` (or), `DX-Y.NYB` (dollar / DXY).

---

## Décision

**Nouvel ingester** `CrossAssetIngester` (Yahoo, série journalière 3 mois) qui publie
`tik.macro.cross_asset`, exposé par un endpoint dédié `/macro/cross_asset`. Calcul (pur) :
- Corrélation de **Pearson des rendements journaliers** BTC ↔ chaque actif, sur ~30 j
  ouvrés (`corr_recent`) et sur toute la fenêtre (`corr_full`).
- Label `behavior` ∈ {risk_asset, digital_gold, decoupled, mixed} : la corrélation
  positive la plus forte (seuil 0,25, transparent mais arbitraire) décide.

⭐ **Piège résolu — l'ALIGNEMENT des dates** : le BTC cote 7 j/7 (~93 points/3 mois),
les actifs TradFi seulement en semaine (~63). `aligned_returns` échantillonne les deux
séries sur leurs **dates communes** AVANT de calculer rendements et corrélation (le
mouvement BTC du week-end est absorbé dans le rendement vendredi→lundi, comme pour
l'actif). Sans cet alignement, la corrélation serait fausse.

Mesure live au déploiement : behavior **risk_asset** — corr Nasdaq 0,58, S&P 0,55, Or
0,40, DXY −0,34 (BTC se négocie comme un actif risqué, inverse au dollar).

Dashboard : carte cosmique « Corrélations » (label + barres divergentes −1→+1 par
actif, couleur neutre car le signe ≠ « bien/mal »).

---

## CONTEXTE STRICT (identique ADR-028/030/031)

- Ne touche **jamais** `combined_bias`, `veracity`, `direction` (NO-GO intact).
- ⚠️ Une **corrélation n'est NI une prédiction NI une causalité** : elle décrit un
  co-mouvement RÉCENT qui peut s'inverser. Aucun overlay, aucun toggle. Affichage
  descriptif daté, pas un signal.
- Enrôlement futur seulement après mesure shadow ≥ 2 semaines (ADR dédié) — JAMAIS
  avant (règle Axe #1).

---

## Tests & validation

- `core/tests/test_cross_asset.py` : 14 tests (parse_chart, ALIGNEMENT dates,
  pearson dont variance nulle → None, labels behavior, schéma) — verts (tik_test).
- Yahoo vérifié en live (5 symboles, read-only). Runtime : ingester publie (données
  réelles, **22 ingesters**) ; core sérialise via `CrossAssetOut`. Dashboard
  tsc/eslint/bundle iOS verts.

## Limites connues

1. **Pas de pouvoir prédictif** prouvé — corrélation = co-mouvement, pas causalité.
2. Le seuil 0,25 du label `behavior` est **transparent mais arbitraire**.
3. Corrélation **instable** sur 30 points (un choc isolé la déplace) — d'où l'affichage
   `corr_recent` ET `corr_full` pour relativiser.
4. **Accès Yahoo sans clé non garanti** (peut se fermer / throttle) — l'ingester repli
   sur `{}` par symbole en cas d'échec (best-effort, le blob reste partiel).
