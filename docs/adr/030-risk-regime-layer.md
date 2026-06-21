# ADR-030 — Régime de risque (VIX + spreads de crédit, CONTEXTE)

**Date** : 2026-06-21
**Statut** : ACCEPTÉ (contexte read-only, non-enrôlé sur le `combined_bias`)
**Implémenté dans** :
- `core/src/tik_core/aggregator/macro_regime_ingester.py` (section `risk_regime` +
  fonctions pures `_series_metrics` / `compute_risk_regime`)
- `core/src/tik_core/storage/schemas.py` (`RiskSeriesOut`, `RiskRegimeOut`, champ
  `risk_regime` dans `MacroRegimeOut`)
- `core/src/tik_core/api/macro.py` (exposé via `/macro/regime` + `/macro/cockpit` —
  aucun nouvel endpoint, la section voyage dans le blob régime existant)
- `dashboard/components/cosmic/cosmic-risk-regime-card.tsx` (+ type `RiskRegime`,
  carte ajoutée sur la page `/macro-cosmique`)

**Déclencheur** : choix trader (2026-06-21) parmi les familles macro restantes du
backlog (cf. mémoire `macro-backlog-next-families`). Le « régime de risque » est la
première des trois familles de contexte restantes (les deux autres : corrélations
cross-asset, stablecoins).

---

## Contexte

La couche Macro Regime (ADR-028) expose la **liquidité** (Fed net + mondiale) et des
indicateurs FRED (récession, taux réels, courbe, NFCI). Il manquait un thermomètre
direct du **stress de marché** : volatilité actions + tension du crédit corporate.
Ce sont des séries FRED gratuites, quotidiennes, objectives et datées — exactement la
même nature que l'existant (NON-sentiment, CONTEXTE strict).

**Garde-fou empirique rappelé** : le macro **ne prédit pas** le prix BTC/GOLD
(mesuré le 2026-06-19, `measure_macro_predictive.py` : IC liquidité/taux → BTC = bruit
de niveau / mauvais signe / artefact de régime haussier). Donc cette couche est, comme
ADR-028, **du contexte/discipline, jamais un signal directionnel**.

---

## Décision

Ajouter une section **`risk_regime`** au blob `tik.macro.regime` (PAS de nouvel
ingester ni endpoint — DRY : l'ingester `MacroRegimeIngester` poll déjà FRED). Trois
séries :

| FRED ID | Sens | Unité |
|---|---|---|
| `VIXCLS` | VIX — volatilité implicite du S&P 500 (« indice de la peur ») | points |
| `BAMLH0A0HYM2` | ICE BofA US **High Yield** OAS — spread haut rendement | % pts |
| `BAMLC0A0CM` | ICE BofA US **Investment Grade** OAS — spread corporate IG | % pts |

**Vérifiées en live le 2026-06-21** (API FRED, lecture seule) : VIX 18.44, HY 2.63 %,
IG 0.74 % (cohérent : HY > IG car le haut-rendement est plus risqué), ~795 obs (> la
fenêtre de 252 j).

### Calcul (pur, honnête)

Pour chaque série : dernière valeur + date, variation ~1 mois (20 j ouvrés), et surtout
le **rang centile** sur ~1 an (`pct_rank_1y` ∈ [0,1] = fraction des points ≤ dernier).
Le centile est préféré au seul z-score car le VIX et les spreads sont **asymétriques**
(bornés à gauche, longues queues à droite) → un centile dit honnêtement « où on est par
rapport à la dernière année ». Le z-score est aussi exposé en détail.

**Label `risk_state`** fondé sur la moyenne des centiles du **VIX et du HY** (les deux
jauges de stress les plus directes ; l'IG est exposé en détail mais hors label) :
- ≥ 0.70 → `risk_off` (stress élevé : volatilité/crédit tendus vs l'année)
- ≤ 0.30 → `risk_on` (marché calme)
- sinon → `neutral` ; `unknown` si historique trop court.

Mesure live au déploiement : VIX centile 0.70, HY centile 0.00 → moyenne **0.35 →
neutral** (VIX modérément haut MAIS crédit très détendu → signaux mitigés, label
honnête).

---

## CONTEXTE STRICT (identique ADR-028/029)

- Ne touche **jamais** `combined_bias`, `veracity`, `direction` (NO-GO intact).
- Aucun overlay branché, aucun toggle d'enrôlement. C'est de l'affichage de chiffres
  FRED datés, **pas une prédiction**. On n'affirme rien (anti-« Lecture macro » du
  2026-05-30).
- Si un jour une mesure shadow ≥ 2 semaines démontrait un edge (IC / gain apparié vs
  Always SHORT, fenêtres non chevauchantes), un overlay `_enrich_with_risk_regime`
  pourrait être **proposé dans un ADR dédié** — JAMAIS avant mesure (règle Axe #1,
  protocole Polymarket/dérivés/ETF).

---

## Tests & validation

- `core/tests/test_macro_regime.py` : 15 tests ajoutés (`_series_metrics`,
  `compute_risk_regime` risk_on/off/neutral/unknown/empty, exclusion IG du label,
  schémas) → **35 verts** au total (tik_test).
- Séries FRED vérifiées en live (read-only).
- Runtime : ingester publie `risk_regime` dans Redis (données réelles) ; le conteneur
  core (schéma rechargé) sérialise `risk_regime` via `MacroRegimeOut` (même chemin que
  l'endpoint). Dashboard tsc/eslint/bundle iOS verts.

## Limites connues

1. **Pas de pouvoir prédictif** prouvé (et probablement aucun, cf. mesure 2026-06-19) —
   c'est du contexte, point.
2. Le seuil 0.70/0.30 sur le centile est un **choix transparent mais arbitraire** (pas
   calibré sur un edge — il n'y en a pas à calibrer).
3. Le label ignore l'IG (volontaire : VIX + HY suffisent et l'IG bouge peu) — exposé en
   détail seulement.
4. Données quotidiennes FRED avec ~1 j de retard (publication J+1) — acceptable pour du
   contexte hebdo/quotidien, **inadapté à un usage intraday**.
