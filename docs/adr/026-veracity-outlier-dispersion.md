# ADR-026 — Veracity, dispersion et outliers : incohérence diagnostiquée, recalibration différée

**Statut** : Diagnostic accepté — décision « corriger la doc + différer le changement runtime » (2026-06-10). **Aucun changement de comportement runtime livré.**
**Contexte trading** : la trader observe que BTC swing est « quasiment que du short » avec une veracity bloquée à **0.70**. Audit demandé sous consigne « doute méthodique, zéro complaisance, trianguler, tracer toutes les anomalies ».

## Contexte

Mesure du 2026-06-10 (DB prod, 7-14 j) sur BTC swing :

- direction : **399 short / 270 neutral / 6 long** → quasi-100 % short/neutral ;
- veracity : **tous les shorts à exactement 0.700** (plancher), depuis le 2026-05-27 (~14 j).

### Pourquoi quasiment que du short — NORMAL

Tik est OSINT pur (ADR-018) : la direction vient du `combined_bias` des sources
de sentiment, pas de la technique. Le flux de news est massivement baissier
(ex. CryptoCompare 35 bear / 12 bull ; Google News 33 / 14). Les news dominent
→ short. C'est le « **Tik colinéaire à la tendance baissière** » du go/no-go du
2026-05-27. Comportement attendu, pas un bug.

### Pourquoi veracity = 0.70 — diagnostic mesuré (pas spéculé)

La veracity vient de `_veracity_from_dispersion(cv.dispersion)`
(`swing_engine.py:900`), où `cv.dispersion` est l'écart-type des biais des
sources. Biais réels d'un short typique, reconstruits puis **vérifiés en
exécutant `cross_validate`** :

| Source | score brut | biais | rôle |
|---|---|---|---|
| Fear & Greed = 9 (peur extrême) | — | **+1.0** (contrarian long, saturé) | outlier, **exclu** du combined_bias |
| CryptoCompare = −0.49 | strong_bearish | **−1.0** | valide |
| Google News = −0.40 | strong_bearish | **−1.0** | valide |

`cross_validate({+1, −1, −1})` retourne : `combined_bias=−1.0` (FG exclu),
`circuit_breaker_status="ok"`, **`dispersion=1.1547`** → `_veracity_from_dispersion`
→ **0.70**. Si on excluait l'outlier de la dispersion : `valid=[−1,−1]`,
pstdev=0.0 → veracity **0.95**.

### Triangulation (3 axes, cohérents)

- **Flash BTC** (overlays orderbook/agression, **sans FG**) : veracity shorts
  0.85-0.95 → sain. Confirme que la cause est l'overlay FG.
- **GOLD swing** (sans opposition FG) : veracity shorts **0.89**… mais hit rate
  GOLD mesuré **4.8 %** → **preuve directe que veracity ≠ edge**.
- **Historique** : 0.700 quasi tous les jours depuis le 2026-05-27 → régime de
  peur extrême persistant, pas un accident ponctuel.

**Cause racine** : en régime de **peur extrême**, FG sature à +1.0 (contrarian)
et s'oppose frontalement aux news strong-bearish (−1.0). Comme la veracity inclut
cet outlier dans sa dispersion (alors que la direction et le circuit breaker
l'excluent), la dispersion est maximale → plancher 0.70.

## Anomalies tracées (sources)

| ID | Anomalie | Source | Nature |
|---|---|---|---|
| **A1** | La veracity inclut l'outlier dans la dispersion, alors que `combined_bias` et `circuit_breaker_status` l'excluent → `circuit=ok` ET `veracity=0.70` sur le même signal | `cross_validator.py:271` consommé par `swing_engine.py:900` / `flash_engine.py` ; exclusion direction `:244-245` ; statut `:256-260` | Incohérence de design (le docstring de `_veracity_from_dispersion` la dit intentionnelle — « alignement de TOUTES les sources » — mais elle est incohérente avec le reste du pipeline) |
| **A4** | Avec exactement 2 sources valides (Reddit IP-banni), le check de dispersion du circuit breaker est sauté (`len(valid) >= 3`) → circuit structurellement `ok` | `cross_validator.py:260` | Anomalie de couverture |
| **A5** | Estimateur incohérent entre branches : `pstdev` (population) pour N=2, `stdev` (échantillon) pour N≥3 | `cross_validator.py:221` vs `:271` | Bug de calibration (décale les paliers selon N) |
| **A7** | Bucketing grossier des biais (−1 / −0.5 / 0 / +0.5 / +1) : FG=9 et FG=20 → tous deux +1 ; news −0.40 et −0.95 → tous deux −1. Amplifie la dispersion apparente | `swing_engine.py:356-364, 598-606, 654-672` | Limite de design |
| **A6** | `confidence=1.0` (conviction max) coexiste avec `veracity=0.70` (confiance basse) | by design (axes différents) | Tension UX |
| **A2** | CLAUDE.md annonçait « veracity capée à 0.85-0.89 » ; réalité = plancher 0.70 depuis 14 j | CLAUDE.md §5 + Bug 11 | **Bug doc** — corrigé dans ce lot |

## Options évaluées

### Option A — Cohérent « confiant » : exclure FG de la veracity → shorts ~0.95
- **Pour** : cohérent avec `circuit=ok` ; supprime l'incohérence A1.
- **Contre** : (1) ⚠️ **fabrique de la fausse confiance** — GOLD prouve qu'une
  veracity 0.89 coexiste avec 4.8 % de hit ; (2) viole l'**Axe stratégique #1**
  (« ne pas peaufiner le vernis de certitude tant que l'edge n'est pas prouvé ») ;
  (3) ferait passer les shorts le filtre ≥ 0.85 → la trader trade des signaux
  sans edge démontré (NO-GO).

### Option B — Cohérent « prudent » : faire passer le circuit breaker à `degraded`
- **Pour** : le désaccord FG pénalise les deux champs, honnête, garde la discipline.
- **Contre** : **rayon de blast large** — `circuit_breaker_status` est consommé par
  10 modules (`publisher`, `hypothesis_generator`, `metrics`, dashboard, SDK…).
  Changer 399 shorts de `ok` à `degraded` ripple dans le texte d'hypothèse LLM,
  les métriques, l'affichage. Risque élevé pour un gain cosmétique. Consommateurs
  de `degraded` non audités en détail.

### Option C — Découpler veracity / « tradable »
- **Pour** : intellectuellement le plus honnête (veracity = accord des sources
  valides ; la discipline de trading repose explicitement sur autre chose).
- **Contre** : nécessite de repenser le Garde-fou 2-bis ; même risque de vernis
  de certitude que A sur l'affichage.

### Option retenue — « Corriger la doc + différer la recalibration » (Lot 0 + 1)
- **Pour** : (1) corrige le seul élément **factuellement faux** (A2) sans risque ;
  (2) ne fabrique aucune fausse confiance (respecte Axe #1 + preuve GOLD) ;
  (3) ne touche pas le circuit breaker (pas de blast radius) ; (4) **diffère** la
  décision sémantique jusqu'à avoir **mesuré la distribution réelle de
  `cv.dispersion`** (méthode B.1) — au lieu de tuner à l'aveugle.
- **Contre** : l'incohérence A1/A4/A5/A7 reste en place (mais tracée, sans impact
  edge). La trader continue de n'avoir aucun short BTC swing « tradable » sous son
  filtre ≥ 0.85 — ce qui est **cohérent avec le NO-GO** (ne pas trader la direction).

## Décision

1. **Corriger la doc** (A2) : CLAUDE.md §5 + Bug 11 amendés (mécanisme FG extrême,
   plancher 0.70, conséquence sur le filtre ≥ 0.85). ✅ fait.
2. **Clarifier le commentaire** `cross_validator.py:270` (A1 + A5 documentés à la
   source). ✅ fait.
3. **Ne PAS changer** la veracity ni le circuit breaker en runtime maintenant.
4. **Pré-requis avant toute recalibration (Lot futur)** : instrumenter
   `cv.dispersion` + biais par source par cycle (comme B.1), collecter ~2 semaines,
   puis trancher A5 (estimateur unique) et la sémantique include/exclude outlier
   dans un ADR-026-bis, et recalibrer `_veracity_from_dispersion` sur la
   distribution réelle. **Conditionné** à une utilité edge (Axe #1).

## Conséquences

- La veracity reste un indicateur d'**accord des sources**, pas d'edge. À ne pas
  présenter comme un gage de fiabilité (cf. Axe #1).
- Pour la trader : sous le filtre ≥ 0.85, **aucun short BTC swing n'est tradable
  en régime de peur extrême** — comportement assumé, aligné NO-GO. Le contexte
  (direction + désaccord FG/news) reste lisible dans l'evidence.

## Ce qui reste à mesurer / limites (non vérifié)

- Distribution réelle de `cv.dispersion` sur tous les signaux (non stockée → Lot 2).
  Les paliers `_veracity_from_dispersion` ne sont donc **pas** validés empiriquement.
- Impact exact de A5 (pstdev vs stdev) sur les cas **neutral** (spreads moyens).
- Comportement des consommateurs de `circuit_breaker_status="degraded"` (audit non fait).
- B.1 re-mesuré sur 28 j (DB) vs 16 j (logs) : non refait.

## Références

- ADR-018 (Tik OSINT pur) ; CLAUDE.md §5 Garde-fou 2-bis, Bug 11 ; go/no-go 2026-05-27.
- `cross_validator.py` (cross_validate, dispersion), `swing_engine.py` /
  `flash_engine.py` (`_veracity_from_dispersion`).
