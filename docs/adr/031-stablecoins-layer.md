# ADR-031 — Masse de stablecoins (liquidité crypto-native, CONTEXTE)

**Date** : 2026-06-21
**Statut** : ACCEPTÉ (contexte read-only, non-enrôlé sur le `combined_bias`)
**Implémenté dans** :
- `core/src/tik_core/aggregator/stablecoins_ingester.py` (ingester + fonctions pures
  `parse_chart_series` / `compute_stablecoin_regime` / `parse_breakdown`)
- `core/src/tik_core/storage/schemas.py` (`StablecoinBreakdownOut`, `StablecoinsOut`)
- `core/src/tik_core/api/macro.py` (endpoint `GET /api/v1/macro/stablecoins`)
- `core/src/tik_core/scripts/run_ingesters.py` (enregistrement, polling 6 h)
- `dashboard/components/cosmic/cosmic-stablecoins-card.tsx` (+ type `Stablecoins`,
  hook `useStablecoins`, carte sur la page `/macro-cosmique`)

**Déclencheur** : choix trader (2026-06-21) — 3e famille macro de contexte du backlog
(cf. mémoire `macro-backlog-next-families`), après le régime de risque (ADR-030).

---

## Contexte

Tik a la liquidité des banques centrales (ADR-028) et le stress de marché (ADR-030).
Il manquait la **liquidité crypto-native** : la masse totale de stablecoins (USDT,
USDC, …) = le cash en USD parqué sur les rails on-chain, prêt à être déployé (la
« poudre sèche »). C'est une famille **NON-sentiment**, différente du sentiment
retardé ET de la macro TradFi.

**Source** : DefiLlama Stablecoins API (`https://stablecoins.llama.fi`), **gratuite,
sans clé**. Joignabilité VPS vérifiée 2026-06-21 (HTTP 200, ~114 ms).
- `/stablecoincharts/all` → série quotidienne (3127 points) du total
  `totalCirculatingUSD.peggedUSD` → niveau + tendance.
- `/stablecoins` → répartition par stablecoin (382 actifs ; USDT ~59 %, USDC ~24 %).

---

## Décision

**Nouvel ingester** `StablecoinsIngester` (source ≠ FRED → ingester dédié, comme
ADR-029) qui publie `tik.macro.stablecoins`, exposé par un endpoint dédié
`/macro/stablecoins`. Calcul (pur) :
- `total_busd` / `total_tusd` (niveau, milliards / trillions USD)
- `delta_7d_busd`, `delta_30d_busd`, `pct_30d` (variations)
- `trend` ∈ {expansion, contraction, neutral, unknown} : seuil ±0,5 % sur 30 j
  (transparent mais arbitraire — la masse bouge lentement)
- `zscore_90d` (position vs moyenne 90 j)
- `breakdown` : top 5 stablecoins (symbole, capitalisation, part %)

Mesure live au déploiement : **313,4 Md$**, trend **contraction** (−7,36 Md$/30 j,
−2,35 %, z90 −1,39), USDT 59 % / USDC 24 %.

Dashboard : carte cosmique « Stablecoins » (jauge z-score + total + Δ + barres de
répartition) sur la page `/macro-cosmique`.

---

## CONTEXTE STRICT (identique ADR-028/030)

- Ne touche **jamais** `combined_bias`, `veracity`, `direction` (NO-GO intact).
- Aucun overlay branché, aucun toggle. Affichage de chiffres datés, **pas une
  prédiction** (la liquidité ne prédit pas le BTC — mesuré 2026-06-19).
- Si une mesure shadow ≥ 2 semaines démontrait une valeur **prédictive indépendante**
  des sources actuelles (IC vs rendements forward, gain apparié vs Always SHORT,
  fenêtres non chevauchantes), un overlay `_enrich_with_stablecoins` pourrait être
  proposé dans un ADR dédié — JAMAIS avant mesure (règle Axe #1).

---

## Tests & validation

- `core/tests/test_stablecoins.py` : 13 tests (parse_chart_series, compute_stablecoin_
  regime expansion/contraction/neutral/unknown/empty, parse_breakdown, schéma) — verts
  (tik_test).
- DefiLlama vérifié en live (read-only). Runtime : ingester publie (données réelles,
  21 ingesters au total) ; core sérialise via `StablecoinsOut`. Dashboard
  tsc/eslint/bundle iOS verts.

## Limites connues

1. **Pas de pouvoir prédictif** prouvé — c'est du contexte (cohérent NO-GO).
2. Le seuil ±0,5 %/30 j du label `trend` est **transparent mais arbitraire** (pas
   calibré sur un edge — il n'y en a pas à calibrer).
3. **Accès sans clé non garanti** contractuellement (peut se fermer un jour) —
   `source_health` (clé `tik.macro.stablecoins`) le détecterait (stale/missing).
4. Le total agrège tous les stablecoins **USD-pegged** (les non-USD comptent 0 en
   `peggedUSD`) — choix volontaire (la « poudre sèche » pertinente pour le BTC est en
   USD).
