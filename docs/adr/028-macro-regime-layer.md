# ADR-028 — Couche Macro Regime (liquidité & régime objectifs, CONTEXTE)

**Date** : 2026-06-15
**Statut** : ACCEPTÉ (contexte read-only, non-enrôlé sur le `combined_bias`)
**Implémenté dans** :
- `core/src/tik_core/aggregator/macro_regime_ingester.py` (ingester + calcul pur)
- `core/src/tik_core/api/macro.py` (endpoints `/macro/regime` + `/macro/cockpit`)
- `core/src/tik_core/storage/schemas.py` (`MacroRegimeOut`, `MacroCockpitOut`)
- `dashboard/components/dashboard/macro-regime-card.tsx` (+ hook `useMacroRegime`)

**Déclencheur** : demande utilisatrice de « la meilleure analyse macro possible »
+ recherche sur centralbank.watch et novex.trading (2026-06-15). Aucun des deux
n'a d'API → on ne les branche pas ; on reproduit leur *menu de données* via les
sources primaires gratuites (FRED), et on surface l'existant déjà collecté.

---

## Contexte

État macro de Tik avant cet ADR :
- **Calendrier** macro live (FOMC/ECB/BoJ/BoE + releases FRED) — *quand* il se passe
  quelque chose, pas *où en est* la macro.
- **7 séries FRED** brutes (`DGS10`, `DGS2`, `DTWEXBGS`, `CPIAUCSL`, `M2SL`,
  `FEDFUNDS`, `UNRATE`) collectées, mais **jamais affichées en cockpit** (servent
  juste à l'overlay DXY GOLD, désactivé).
- **Familles non-sentiment déjà en shadow** (Polymarket, dérivés Binance, ETF) avec
  chacune leur endpoint + carte.
- La **« Lecture macro »** (couche éducative qui *expliquait* la macro) a été
  **supprimée le 2026-05-30** : 2 affirmations fausses sur 4 (BoJ YCC, ECB vs Fed).
  Leçon : ne jamais réimporter des *verdicts* macro tiers non auditables.

Le manque réel : **un cockpit de chiffres macro objectifs**, en particulier le
**Fed Net Liquidity** (`WALCL − TGA − RRP`), driver macro structurel reconnu du BTC
et **famille non-sentiment** — exactement ce que CLAUDE.md §8 désigne comme la
direction où l'edge peut vivre (« l'edge, s'il existe, vit dans des familles
DIFFÉRENTES du sentiment »).

centralbank.watch / novex.trading : voir analyse complète dans la mémoire
`macro-data-sources-2026-06-15`. Aucun n'a d'API → pas d'intégration directe
(scraping fragile + zone grise ToS + risque factuel « Lecture macro »). On garde
leur *menu de données* comme cahier des charges.

## Décision

Ajouter une couche **Macro Regime** de chiffres macro **objectifs et datés**,
calculés depuis FRED (gratuit), publiés en CONTEXTE strict :

1. **`MacroRegimeIngester`** (couche 4, polling 6 h) calcule et publie
   `tik.macro.regime` :
   - **Fed Net Liquidity** hebdo (`WALCL/1000 − TGA/1000 − RRP`, en milliards)
     + Δ4 sem, Δ13 sem, z-score 52 sem, label de régime
     (`expansion`/`contraction`/`neutral`).
   - **Indicateurs** dernière valeur datée : proba récession 12 m (`RECPROUSM156N`,
     probit NY Fed), taux réel 10Y (`DFII10`), inflation anticipée (`T10YIE`),
     pente `2s10s` (`T10Y2Y`) et `3m10y` (`T10Y3M`), conditions financières
     (`NFCI`, Chicago Fed), taux nominal 10Y (`DGS10`).
2. **`GET /api/v1/macro/regime`** : le blob ci-dessus.
3. **`GET /api/v1/macro/cockpit`** : agrégateur 1-appel (inspiré du
   « Direction Overview » de novex) = régime macro + snapshots shadow déjà
   collectés (Fear&Greed, dérivés/DMX, ETF, COT or, Polymarket) + prochain event
   macro. Pratique pour un futur écran consolidé.
4. **Dashboard** : carte « Régime macro » (onglet Marché, après le calendrier).

## Garde-fous (NON négociables)

- **CONTEXTE STRICT** : ne touche JAMAIS `combined_bias`, veracity, direction.
  Aucun overlay branché, aucun toggle directionnel. Le NO-GO directionnel du
  2026-05-27 est intact.
- **Zéro affirmation** (anti-« Lecture macro ») : on affiche des **séries FRED
  officielles datées**, on n'explique/n'interprète pas au-delà d'une note de
  contexte clairement marquée « historique, pas une prédiction ».
- **Pas d'enrôlement sans mesure** : si un jour on veut un overlay
  `_enrich_with_net_liquidity`, il passera par le protocole habituel — shadow
  ≥ 2 semaines + mesure (IC / hit rate / gain apparié **vs Always SHORT**, pas
  Random) **avant** toute influence sur un signal (Axe #1, comme
  Polymarket/dérivés/ETF). Cet ADR ne fait PAS cela.
- **Axe #1** : pas de « vernis de certitude ». La carte affiche des chiffres, pas
  des % de conviction.

## Pièges techniques résolus (Phase 0, vérifiés en live FRED le 2026-06-15)

| Piège | Résolution |
|---|---|
| **Unités** : `WALCL`/`WTREGEN` en MILLIONS $, `RRPONTSYD` en MILLIARDS $ | Normalisation : `WALCL/1000 − TGA/1000 − RRP`. Oubli = erreur ×1000. Test dédié `TestNetLiquidityUnitsGotcha`. |
| **Cadence** : WALCL/TGA hebdo (mercredi), RRP quotidien | Net liquidity = **hebdo**, alignée sur les mercredis WALCL (standard des graphes publics). |
| **Récession** : `RECPROUSM156N` mensuel, ~2 mois de retard | Affiché tel quel avec sa date (indicateur lent par nature). |
| Sanity check | 6725,4 − 828,1 − 0,5 ≈ **5896,8 Md$ (~5,90 T$)** = ordre de grandeur public correct. |

## Alternatives écartées

- **Brancher/scraper centralbank.watch ou novex.trading** : pas d'API ; scraping
  fragile + ToS + risque factuel. ❌
- **CME FedWatch API payante** : viole « pas de budget API payant sans validation ».
  La proba taux Fed sera reproduite gratuitement via `pyfedwatch` en Phase 2
  (futur, non couvert ici). ⏸
- **Recréer une couche d'explication macro narrative** : c'est précisément ce qui a
  été supprimé le 2026-05-30. ❌

## Limites connues (transparence)

1. **Net liquidity = hebdo** (pas intra-day). Pour du quotidien il faudrait le TGA
   journalier via l'API Treasury Fiscal Data — non fait (suffisant pour du contexte).
2. **RRP manquant un mercredi** → traité comme 0 (rare ; RRP ≈ 0,5 Md$ en 2026,
   négligeable). Best-effort assumé.
3. **Aucune valeur prédictive démontrée** à ce stade — c'est du contexte, pas un edge.
4. **Rendu dashboard non vérifié en runtime** au moment de l'écriture (Metro/ngrok) :
   typecheck TS OK + endpoints testés 200, mais rendu visuel à confirmer en Expo Go.

---

## Amendement 2026-06-15 — Liquidité globale (Fed + ECB + BoJ)

Extension de la couche (même ingester `MacroRegimeIngester`, même blob `tik.macro.regime`)
à la **liquidité mondiale des banques centrales** — driver macro structurel n°1 du BTC
(« global liquidity → risk assets »), choisi par la trader comme prochaine brique macro.

- **Agrégat** = `WALCL` (Fed, M$) + `ECBASSETSW` (ECB, M€) + `JPNASSETS` (BoJ, « 100 M¥ »),
  **converti en USD** via FRED `DEXUSEU` (USD/€) et `DEXJPUS` (¥/$). Série hebdo (alignée
  WALCL), régime calculé par le même `_regime_core` (factorisé : `compute_regime` pour le
  net liquidity, `compute_global_regime` pour le global → clés distinctes, zéro régression).
- **Exposé** dans `MacroRegimeOut.global_liquidity` (`GET /macro/regime` + cockpit) +
  carte dashboard **« Liquidité mondiale »** (Fed/ECB/BoJ en barre empilée).
- **Pièges d'unités résolus** (Phase 0 live 2026-06-15) : ECB en M€ (× USD/€), **BoJ en
  « 100 M¥ »** (× 100 puis ÷ ¥/$). Sanity = **17,95 T$** (Fed 6,73 + ECB 7,08 + BoJ 4,15),
  ordre de grandeur public correct (~18 T$). Test `TestGlobalLiquidityUnitsGotcha`.
- **Cadences mixtes** alignées via `_value_on_or_before` : ECB hebdo (≤ 10 j), BoJ mensuel
  (report ≤ 40 j), FX quotidien (≤ 7 j).
- **CONTEXTE STRICT inchangé** : ne touche jamais combined_bias/veracity/direction.
- Validé : 6 tests dédiés + suite complète 1594 verts (1 échec WS d'intégration
  préexistant, sans lien). Déployé par simple restart (pur Python, pas de rebuild).
- Limite : net liquidity vs global liquidity peuvent diverger (US réexpand pendant que
  ECB/BoJ se contractent) — c'est une **nuance** affichée, pas une incohérence.
