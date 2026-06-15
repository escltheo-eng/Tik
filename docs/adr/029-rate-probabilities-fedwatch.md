# ADR-029 — Probabilités de taux Fed par réunion (CME FedWatch, CONTEXTE)

**Date** : 2026-06-15
**Statut** : ACCEPTÉ (contexte read-only, non-enrôlé sur le `combined_bias`)
**Implémenté dans** :
- `core/src/tik_core/aggregator/rate_probabilities_ingester.py` (ingester + calcul pur)
- `core/src/tik_core/aggregator/_pyfedwatch_compat.py` (shim deps cassées)
- `core/src/tik_core/api/macro.py` (`GET /macro/rate_probabilities` + cockpit)
- `core/src/tik_core/storage/schemas.py` (`RateProbabilitiesOut`, `RateMeetingOut`)
- `dashboard/components/dashboard/rate-probabilities-card.tsx` (+ hook `useRateProbabilities`)

**Déclencheur** : Phase 2 de la refonte macro (cf. ADR-028). Reproduire le
« flagship » de centralbank.watch (probas hausse/maintien/baisse par réunion FOMC)
choisi par la trader, via la lib **pyfedwatch** (maths CME éprouvée) + données
gratuites.

---

## Décision

Calculer les **probabilités de mouvement de taux Fed par réunion FOMC** (méthodo
CME FedWatch) à partir de données 100 % gratuites :
- **futures Fed Funds (ZQ)** par échéance via Yahoo Finance (même source que
  l'ingester Yahoo existant) ;
- **range de taux cible + taux effectif** via FRED (`DFEDTARL`/`DFEDTARU`/`DFF`,
  clé de Tik) ;
- **dates FOMC** via le calendrier de Tik (+ dates passées d'ancrage).

`RateProbabilitiesIngester` (couche 4, polling 6 h) publie `tik.macro.rate_probabilities` :
par réunion → probabilités par range de taux + agrégats hold/hike/cut + range le
plus probable. Exposé via `GET /macro/rate_probabilities` (+ intégré au cockpit) et
une carte dashboard « Anticipations taux Fed ».

## Garde-fous (NON négociables)

- **CONTEXTE STRICT** : ne touche JAMAIS `combined_bias`/veracity/direction. C'est
  l'anticipation du marché (pricée dans les futures), affichée comme contexte — pas
  un signal Tik. NO-GO directionnel intact.
- **Pas d'affirmation maison** : la maths vient de CME (via pyfedwatch), les données
  de sources primaires datées. On n'invente aucune lecture.

## Intégration de pyfedwatch (le point délicat)

pyfedwatch 1.2.0 (Apache-2.0) **ne s'importe pas** tel quel dans la stack Tik :

| Problème | Résolution |
|---|---|
| Dépendance épinglée `pandas_datareader==0.10.0` **casse à l'import** contre pandas≥2.2 (`deprecate_kwarg`) | Installé `--no-deps` + **stub `sys.modules`** dans `_pyfedwatch_compat` (jamais appelé : on fournit `user_func` + `watch_rate_range`). |
| `matplotlib` (plot, non utilisé) lourd | Stub `sys.modules` (jamais chargé). |
| `__init__` importe `datareader.py` qui importe `requests` + `bs4` au niveau module | Installés pour de vrai (légers, standard) — pas de stub global pour des libs communes. |
| `generate_hike_info` tente un fetch FRED via pandas_datareader | On passe `watch_rate_range=(DFEDTARL, DFEDTARU)` explicitement (FRED direct). |
| Contrat d'**ancrage** = mois sans-FOMC précédent, souvent **expiré** → Yahoo 404 | **Synthèse** du prix au taux effectif courant (`DFF`) sur tout le mois (un mois sans FOMC = taux constant). Uniquement pour les mois PASSÉS — jamais un mois futur (cela fabriquerait un faux « no change »). |
| Tik ne stocke que les dates FOMC **futures** (Bug 14) | `PAST_FOMC_DATES` (dates passées de l'année) ajoutées pour l'ancrage. ⚠️ à MAJ chaque année comme `macro_calendar_data`. |
| Contrats lointains parfois absents de Yahoo | `num_upcoming` **adaptatif** (6→2) jusqu'à ce que le calcul aboutisse. |

Le shim est entièrement isolé dans `_pyfedwatch_compat` ; les stubs ne visent que
des libs **Tik-exclusives** (pandas_datareader, matplotlib) → aucun effet de bord.

## Alternatives écartées

- **API CME FedWatch payante** : viole « pas de budget API payant sans validation ». ❌
- **Reproduire la maths en pur Python** : la trader a préféré la maths CME éprouvée
  (pondération mi-mois = source de bugs subtils). On la garde, via pyfedwatch. ❌
- **Vendoring des fichiers pyfedwatch** : envisagé (Apache-2.0 le permet) mais
  l'install `--no-deps` + shim est plus simple à mettre à jour (lib versionnée). ⏸

## Validation (2026-06-15)

- Recette validée empiriquement AVANT build (probas sensées, somme = 1).
- Chemin de prod réel (`_compute_blob_sync`) testé live : 6 réunions, range 3.50-3.75,
  marché pricant des **hausses** vers fin 2026 (cohérent régime « expansion » ADR-028 +
  courbe ZQ montante).
- 12 tests purs (parse symbole, hold/hike/cut, transformation DataFrame) +
  non-régression suite complète (1588 verts ; 1 échec WS d'intégration **préexistant**
  et sans lien — timeout Redis pubsub, fichier intouché, 0 réf macro).
- Endpoints live 200, ingester publie `rate_probabilities.published meetings=6`.
- Typecheck dashboard exit 0.

## Limites connues (transparence)

1. **Ancrage synthétique** au taux courant pour le mois expiré : exact tant que ce
   mois n'a pas eu de réunion (vrai par construction) ; approximation EFFR vs cible.
2. **`PAST_FOMC_DATES` à maintenir** annuellement (comme les dates BC de Bug 14).
3. **Dépendance à Yahoo** pour les contrats ZQ (pas d'API officielle gratuite
   « toutes échéances ») — robustifié par le fallback + `num_upcoming` adaptatif.
4. **Aucune valeur prédictive propre démontrée** : c'est l'anticipation du marché,
   du contexte — pas un edge Tik.
5. **Rendu dashboard non vérifié en runtime** (Metro/ngrok) : typecheck OK +
   endpoints testés, rendu visuel à confirmer en Expo Go.
