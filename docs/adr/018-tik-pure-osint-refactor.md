# ADR-018 — Refactor architectural Tik vers OSINT pur

**Date** : 2026-05-07
**Statut** : ✅ ACCEPTÉ — implémenté Session refactor du 2026-05-07
**Implémentation** : Sessions 1 + 2 + 3 livrées le 2026-05-07 (891 tests verts, 0 régression)

---

## Contexte

Audit méthodique conduit le 2026-05-06 et 2026-05-07 sous la consigne
*"doute constant et méthodique, sans complaisance"*. L'audit a révélé
plusieurs incohérences architecturales que les sessions précédentes
n'avaient pas identifiées :

### Constat #1 — Tik n'est pas une plateforme OSINT pure (contrairement au branding)

CLAUDE.md section 1 décrit Tik comme *"plateforme OSINT modulaire"*.
**La réalité du code est différente** : Tik est un **système hybride** où :

- Le **cerveau principal de décision** est l'analyse technique
  (RSI/MACD/EMA dans `swing_engine.py:162-291` et `flash_engine.py`)
- Les **overlays OSINT** (sentiment news, macro fondamental, géopolitique)
  ne **modulent que la veracity**, pas la direction
- La **direction** (long/short/neutral) et la **confidence** sont dérivées
  uniquement de RSI/MACD/EMA via `_score_indicators()`

### Constat #2 — Duplication conceptuelle avec Zeta + MT5

- **Zeta** (`cranial_bot/turbo_v2.py`, ~5211 lignes) fait déjà l'analyse
  technique pour ses stratégies H1 Adaptive et Weekend Scalp
- **MT5/ActivTrades** affiche RSI/MACD/EMA en natif sur l'écran de la
  trader manuelle
- Tik fait donc l'analyse technique **trois fois** (Tik + Zeta + MT5),
  mais seulement Zeta a un moteur calibré et MT5 a l'affichage natif

### Constat #3 — Sémantique trompeuse de la "confidence"

Audit code (`swing_engine.py:242-250`) : la `confidence` n'a pas la même
signification selon le cas :

- Cas `long`/`short` : `confidence = score gagnant` (bull_score ou bear_score)
- Cas `neutral` : `confidence = abs(bull_score - bear_score)` (écart, microscopique)

Pour l'utilisatrice : un signal `neutral conf 5%` est interprété comme
*"Tik est faiblement convaincu"* alors que la signification réelle est
*"bull et bear se tirent la bourre, écart minime"*. **Sémantique inversée
par rapport à l'intuition**.

### Constat #4 — Tik n'excelle pas dans l'analyse technique

Mesures factuelles 2026-05-07 :

- Tik scoring core : 3024 lignes
- Zeta `turbo_v2.py` : 5211 lignes (uniquement le moteur principal)
- Tik utilise des seuils binaires (RSI > 70, MACD cross, etc.) avec
  **14 magic numbers non calibrés empiriquement** (cf. audit
  Paquet 17 P5 fin 2026-05-06)
- Hit rate Tik backtest 156 signaux : **22 % global** (vs Random 33 %)
  — *Tik fait pire que Random sur la mesure agrégée*
- Hit rate Tik veracity ≥ 0.95 : 67 % (le **filtre OSINT** sauve la
  performance, pas l'analyse technique)

Tik a un **avantage technique clair en OSINT** (Modified Z-score
Iglewicz-Hoaglin anti fake-news ADR-011, recalibration daily des sources,
LLM hypothesis local ADR-012, multi-overlay cross-validé ADR-004) **mais
pas en analyse technique**.

---

## Décisions structurantes

### 1. Refactor Tik vers une plateforme OSINT pure (pas hybride)

**Décision** : retirer la couche analyse technique du moteur de décision
Tik. La direction et la conviction du signal seront dérivées uniquement
des **overlays OSINT cross-validés**.

**Pour** :

- Concentration des ressources sur la **vraie valeur ajoutée** Tik (OSINT
  + anti fake-news + LLM hypothesis), où Tik a un avantage différencié
- Élimination de la duplication avec Zeta et MT5
- Positionnement clair B2B (si stratégie commerciale) ou perso
  (*"plateforme OSINT crypto/finance cross-validée local-first"*)
- Cohérence interne : Tik OSINT ↔ Zeta technique ↔ Totem ML, chacun son
  rôle

**Contre** :

- Tik moins consommable seul (besoin MT5 ou Zeta pour avoir une direction
  technique)
- Refactor non-trivial (~500-700 lignes core + ~200-300 lignes dashboard)
- L'utilisatrice doit s'adapter (signal Tik change de format)

**Verdict** : Pour. Le bénéfice long terme de la spécialisation l'emporte
sur l'inconvénient court terme de la dépendance MT5/Zeta.

### 2. Direction du signal dérivée du `combined_bias` OSINT

**Décision** : la direction (`long`/`short`/`neutral`) est calculée à
partir du biais combiné des sources OSINT (déjà calculé par
`apply_cross_validation_to_decision`), avec des seuils symétriques :

- `combined_bias > +seuil` → `long`
- `combined_bias < -seuil` → `short`
- `-seuil ≤ combined_bias ≤ +seuil` → `neutral`

**Seuil candidat** : `±0.30` (à calibrer empiriquement).

### 3. Renommer `confidence` → `osint_conviction`

**Décision** : la métrique principale du signal devient
`osint_conviction` ∈ [0, 1] = `abs(combined_bias)`. Magnitude du biais
OSINT cross-validé.

**Sémantique uniforme** :
- `osint_conviction = 0.85` signifie *"forte conviction directionnelle
  OSINT"*
- `osint_conviction = 0.10` signifie *"faible conviction, marché OSINT
  équilibré"*
- Plus jamais de double sens entre direction et neutral

### 4. Conservation des modules OSINT existants

**Conservés intégralement** :

- Multi-overlay sentiment (ADR-004, ADR-008, ADR-009, ADR-010)
- Anti fake-news Modified Z-score (ADR-011)
- LLM hypothesis generator (ADR-012)
- Recalibration daily des SOURCE_SCORES
- Calendrier macro (ADR-017)
- Track record signal (Paquet 12, 17)

### 5. Module `indicators.py` conservé pour usage futur

**Décision** : `core/src/tik_core/scoring/indicators.py` (RSI, EMA, MACD,
ATR, Bollinger Bands) reste dans le repo. Plus utilisé dans les engines,
mais peut servir :

- Au **dashboard** (affichage indicateurs techniques pour la trader si
  elle veut les voir dans Tik)
- À une **future intégration** (cross-feature pour Totem ML, etc.)
- En cas de **revert** si la décision est mauvaise

### 6. Suppression de la couche analyse technique du moteur

**Modifications concrètes** :

| Fichier | Ce qui change |
|---|---|
| `swing_engine.py` | Suppression `_score_indicators()` lignes 151-291 (~140 lignes). Direction calculée à partir du `combined_bias` après cross-validation |
| `flash_engine.py` | Idem — suppression de la logique de score basée sur RSI/MACD/EMA |
| `signal_track_record.py` | Conservation (mesure le track record, pas la décision) |
| `metrics/hit_rate.py` | Conservation |
| `storage/schemas.py` | `confidence` → `osint_conviction` dans `SignalOut` |
| `dashboard/app/signal/[id].tsx` | Hero card : afficher `osint_conviction` au lieu de `confidence` |

---

## 4 hypothèses à vérifier avant exécution

Le refactor n'est pas une décision technique pure — c'est une décision
**produit** qui dépend de la stratégie. Avant de l'exécuter, vérifier :

1. **Stratégie business B2B** : l'utilisatrice envisage-t-elle de vendre
   Tik à des clients institutionnels ? Si oui, le positionnement OSINT
   pur est un argument vendeur. Si non, le refactor reste pertinent mais
   moins critique.

2. **Hit rate Zeta réel** : à demander à l'associé. Si Zeta technique
   tourne déjà à 50 %+ hit rate, le couplage Tik OSINT × Zeta technique
   devient encore plus pertinent. Si Zeta tourne à 25 %, il faut
   reconsidérer.

3. **Proportion signaux Tik veracity ≥ 0.95** : à mesurer en DB
   (`SELECT COUNT(*) FROM signals WHERE veracity >= 0.95 AND timestamp >
   now() - interval '30 days'`). Si > 25 % des signaux passent ce filtre,
   Tik est exploitable. Si < 10 %, problème de calibration des seuils.

4. **Fréquence trading manuel envisagée** : si > 5 trades/semaine, on a
   30-50 trades en 6-10 semaines = signal statistique clair pour décider.
   Si < 2 trades/semaine, il faut 25+ semaines pour valider, et la
   décision empirique est repoussée.

---

## Conditions d'activation

Le refactor s'active **uniquement si** TOUS les critères ci-dessous sont
remplis :

- ✅ Trading manuel J+14 démarré et stable (≥ 1 semaine de trading
  effectif post-2026-05-14)
- ✅ Réponses obtenues sur les 4 hypothèses ci-dessus
- ✅ Hit rate Tik hybride mesuré empiriquement avec ≥ 30 trades manuels
  réels
- ✅ Stratégie d'intégration MT5 + Tik validée (tu te sens à l'aise de
  combiner mentalement)

---

## Plan de migration (3 sessions étalées)

### Session 1 — Refonte modèle de signal core (~4h)

- `swing_engine.py` : suppression `_score_indicators()`, nouvelle logique
  direction = `derive_direction_from_bias(combined_bias, threshold=0.30)`
- `flash_engine.py` : idem
- `storage/schemas.py` : renommage `confidence` → `osint_conviction`
- Adaptation des tests pytest existants (~30-50 tests à mettre à jour)
- Garde un fallback temporaire pour rétrocompat des signaux historiques
  en DB (lecture des anciens signaux avec `confidence` legacy)

### Session 2 — Adaptation dashboard (~3h)

- `dashboard/app/signal/[id].tsx` : hero card refondue, affichage
  `osint_conviction` à la place de `confidence`
- `dashboard/src/api/types.ts` : type Signal mis à jour
- Liste signaux : tri/filtre par `osint_conviction` au lieu de
  `confidence`
- Cartes Home : adaptations cosmétiques

### Session 3 — Documentation + tests + bascule (~2h)

- ADR-018 passe de RÉSERVÉ → ACCEPTÉ
- CLAUDE.md mise à jour (Paquet 18)
- Tests pytest tous verts
- Sync worktree → repo principal
- Premier cycle runtime validé (mode shadow 1 semaine avant production
  réelle)

**Total** : ~9h dev + 1 semaine de validation runtime mode shadow.

---

## Conséquences

### Positives

- **Spécialisation claire** : Tik = OSINT pur, Zeta = exécution technique,
  Totem = ML prédictif. Chaque app excelle dans sa discipline.
- **Élimination duplication** Zeta/MT5 sur l'analyse technique
- **Sémantique uniforme** de `osint_conviction` (plus de double sens)
- **Différenciation produit** vs concurrents (Recorded Future, Bloomberg,
  Dataminr) sur le segment OSINT crypto/finance local-first cross-validé
- **Coverage tests préservé** : ~834 tests verts maintenus

### Négatives

- **Tik moins autonome** : besoin MT5 ou Zeta pour avoir une direction
  technique complémentaire
- **Refactor non-trivial** : 9h dev + 1 semaine validation = effort
  modéré sur 2-3 semaines calendaires
- **Re-apprentissage UX** pour la trader manuelle
- **Risque de mauvais calibrage du seuil ±0.30** : à valider
  empiriquement, avec révision possible post-J+30

---

## Garde-fous opérationnels rappelés

- Garde-fou 1 (Tik shadow vs Zeta 3 mois) **inchangé** — refactor
  intervient sur la logique interne Tik, pas sur l'intégration Zeta
- ADR-003 (pas de bypass V01-V15) **inchangé** — Tik ne crée jamais
  d'ordre, ni avant ni après refactor
- ADR-004 (multi-overlay) **renforcé** — le multi-overlay devient le
  cerveau principal, plus seulement un overlay
- ADR-011 (anti fake-news) **inchangé** — la cross-validation reste
  appliquée
- ADR-012 (LLM hypothesis) **inchangé** — la génération LLM reste sur le
  signal final post-cross-validation

---

## Références

- Audit méthodique 2026-05-06 et 2026-05-07 (conversation Claude session
  refactor)
- ADR-004 : architecture multi-overlay (renforcée par ADR-018)
- ADR-011 : anti fake-news (cross-validation Modified Z-score)
- ADR-017 : calendrier macro/géopolitique (préservé)
- Paquet 17 P5 : audit calculs et seuils (a révélé les 14 magic numbers)
- Backlog entry n°6 (compagnon de cet ADR)

---

## Notes d'implémentation (Session refactor du 2026-05-07)

### Fichiers modifiés

**Backend** (3 fichiers) :

- `core/src/tik_core/scoring/swing_engine.py` :
  - Renommé `_score_indicators()` en `_compute_technical_evidence()`
  - Suppression du calcul `bull_score`/`bear_score` et de la décision technique
  - RSI/MACD/EMA toujours calculés et affichés en `evidence`/`triggers` (informatif)
  - Triggers techniques avec `weight: 0.0` pour signaler qu'ils ne pèsent
    pas dans la décision OSINT pure
  - Nouvelle fonction `_derive_osint_decision(decision, combined_bias, threshold=0.30)`
    qui dérive direction + confidence du combined_bias
  - Nouvelle fonction `_veracity_from_dispersion(dispersion)` qui remplace
    `_veracity_from_concordance` au runtime (résout bug #2 audit Paquet 17 :
    veracity neutral n'est plus figée à 0.85)
  - `_veracity_from_concordance` conservée comme legacy pour rétrocompat
    tests existants
  - Alias `_score_indicators = _compute_technical_evidence` pour rétrocompat
  - `analyze_swing_btc` et `analyze_swing_gold` modifiées pour appeler
    `_derive_osint_decision()` et `_veracity_from_dispersion()` après
    cross-validation OSINT

- `core/src/tik_core/scoring/flash_engine.py` :
  - Mêmes changements que swing : `_score_flash_indicators()` →
    `_compute_technical_evidence_flash()`
  - Nouvelle fonction `_derive_osint_decision_flash()` (duplication
    volontaire du swing — à factoriser au prochain ajout d'engine, cohérent
    avec le commentaire `_veracity_from_concordance` ligne 326)
  - Nouvelle fonction `_veracity_from_dispersion()` (idem)
  - `analyze_flash_btc` modifiée

- **Pas de modification** de `storage/models.py`, `storage/schemas.py`,
  ou de migration Alembic. La colonne SQL `confidence` reste, sa
  **signification** seule change (devient `|combined_bias|` au lieu de
  `bull_score`). Les 683 anciens signaux en DB restent lisibles.

**Dashboard** (2 fichiers) :

- `dashboard/app/signal/[id].tsx` : label "Confidence" → "Conviction OSINT"
  avec sous-titre explicatif "magnitude du biais cross-validé".
  Label "Veracity" gardé avec sous-titre "alignement des sources".
  Style `metricSubtitle` ajouté au StyleSheet.

- `dashboard/src/api/types.ts` : commentaire JSDoc enrichi sur le champ
  `Signal.confidence` pour expliquer la nouvelle sémantique ADR-018.
  Le nom du champ reste `confidence` pour rétrocompat avec les signaux
  historiques.

### Tests

- **57 nouveaux tests** ajoutés dans `test_swing_engine.py` et
  `test_flash_engine.py` :
  - `TestDeriveOsintDecision` (swing) : 13 tests paramétrés sur les
    différentes valeurs de combined_bias et threshold
  - `TestVeracityFromDispersion` (swing) : 16 tests des 5 paliers
  - `TestVeracityFromConcordanceLegacy` : 2 tests vérifient que la
    fonction legacy reste fonctionnelle pour rétrocompat
  - `TestSemanticUniformityADR018` : 3 tests vérifient explicitement
    que la sémantique de `confidence` est uniforme (résout bug #1 audit)
  - `TestDeriveOsintDecisionFlash` : 11 tests
  - `TestVeracityFromDispersionFlash` : 10 tests

- **Suite complète** : 834 → **891 tests verts**, 0 régression sur les
  834 tests pré-existants.

### Comportement runtime post-refactor

Les engines `analyze_swing_btc/gold` et `analyze_flash_btc` produisent
maintenant des signaux dont :

- `direction` est dérivée du `combined_bias` OSINT cross-validé (seuil ±0.30)
- `confidence` = `abs(combined_bias)` (sémantique uniforme)
- `veracity` = paliers selon la dispersion des sources OSINT
  (résout le bug `veracity_neutral_figée` identifié dans l'audit)
- Sans overlay OSINT (Redis miss) : direction="neutral", confidence=0
- L'evidence et les triggers techniques (RSI/MACD/EMA) sont toujours
  affichés pour audit, mais avec `weight: 0.0` (signal informatif)

### Bugs résolus par ce refactor

| Bug audit Paquet 17 P5 | Statut |
|---|---|
| #1 — Sémantique double confidence (long/short = score, neutral = écart) | ✅ Résolu |
| #2 — Veracity neutral figée à 0.85 | ✅ Résolu (via dispersion) |
| #3 — Recalibration sources flash mesurée à 5j | 🔵 Non touché (à régler ailleurs) |
| #4 — Attribution hit rate au signal entier | 🔵 Non touché (Phase C Session 2 P7) |
| Confidence plafonnée à 0.55 swing | ✅ Résolu (peut maintenant aller jusqu'à 1.0) |

### Limitations connues post-refactor

1. **Seuil ±0.30 sur combined_bias** : calibration empirique au pifomètre
   (cohérent avec les autres seuils Tik). À réviser post-J+30 selon
   les vrais signaux émis.
2. **Seuils veracity dispersion** (0.2 / 0.4 / 0.6 / 0.8) : pifomètre
   raisonné. Calibration empirique post-J+30.
3. **Tik moins consommable seul** : direction nécessite des sources OSINT
   disponibles. Si Redis est down, Tik produit `direction="neutral"` —
   c'est cohérent avec le rôle OSINT pur mais peut surprendre.
4. **Volume de signaux directionnels** : peut différer post-refactor.
   Mesurer empiriquement après quelques jours de runtime.

### Validation runtime nécessaire post-livraison

- Démarrer Tik core et observer les premiers cycles swing/flash
- Vérifier que les signaux émis ont une direction cohérente avec le
  `combined_bias` calculé
- Mesurer la nouvelle distribution des veracity (devrait être plus
  variée que le 73 % de signaux dans 0.85-0.89 mesurés pre-refactor)
- Vérifier qu'aucun crash en runtime (anciens signaux DB restent lisibles)

### Garde-fous opérationnels confirmés

- Garde-fou 1 (Tik shadow vs Zeta 3 mois) : **inchangé**
- ADR-003 (pas de bypass V01-V15) : **inchangé** — Tik ne crée toujours
  jamais d'ordre
- ADR-004 (multi-overlay) : **renforcé** — devient le cerveau principal
  de décision (pas seulement un overlay)
- ADR-011 (anti fake-news) : **inchangé** — cross-validation toujours
  appliquée
- ADR-012 (LLM hypothesis) : **inchangé** — génération LLM toujours
  appelée post-cross-validation
- Garde-fou 2-bis (sizing 1 % capital, veracity ≥ 0.90 sur swing) :
  **inchangé** — règle stricte trading manuel J+14

---

## Amendement post-livraison — Bascule anticipée 2026-05-07

### Contexte

L'ADR-018 a été livré le **2026-05-07**, soit **7 jours avant** la date
de démarrage du trading manuel J+14 (2026-05-14). Cette livraison est en
divergence assumée avec la section *"Conditions d'activation"* qui
exigeait :

- *"Trading manuel J+14 démarré et stable (≥ 1 semaine de trading
  effectif post-2026-05-14)"*
- *"Hit rate Tik hybride mesuré empiriquement avec ≥ 30 trades manuels
  réels"*
- *"Réponses obtenues sur les 4 hypothèses"* (stratégie B2B, hit rate
  Zeta, proportion signaux veracity ≥ 0.95, fréquence trading)

**Aucune** de ces conditions n'était remplie le 2026-05-07.

### Raison de la bascule anticipée

Décision consciente de l'utilisatrice de **devancer le refactor** plutôt
que de l'attendre post-J+14, pour permettre le démarrage du trading
manuel **directement sur la nouvelle architecture** — sans avoir à
re-apprendre la sémantique de `confidence` en cours de route.

**Trade-off accepté** :

| Pour bascule anticipée | Contre bascule anticipée |
|---|---|
| Une seule sémantique à apprendre (`confidence` = `\|combined_bias\|` uniforme) | Conditions d'activation ADR-018 non vérifiées empiriquement |
| Pas de re-formation UX en cours de trading actif | Risque de découvrir un bug structurel pendant le trading réel |
| 7 jours pré-J+14 disponibles pour validation runtime mode shadow | Mode shadow compressé (initialement prévu 1 semaine post-livraison) |
| Tik et la trader « calibrent » ensemble dès le début | Perte du recul empirique sur l'ancienne version hybride |

**Verdict** : la cohérence d'apprentissage UX a primé sur la rigueur des
conditions d'activation. Décision raisonnée mais à valider runtime.

### Mode shadow compressé

Au lieu d'1 semaine de validation post-livraison comme prévu, on a
**7 jours pré-J+14 + 1 semaine post-J+14** = ~14 jours de validation
runtime. C'est en fait **plus** que ce qui était initialement prévu,
mais coupé par le démarrage du trading réel. Donc la fenêtre
*"observation pure sans risque"* est de 7 jours seulement.

### Hypothèses ADR-018 toujours non vérifiées

Les 4 hypothèses listées en section *"4 hypothèses à vérifier avant
exécution"* restent **toutes non répondues** au 2026-05-07 :

1. Stratégie B2B Tik — pas tranchée
2. Hit rate Zeta réel — non mesuré (associé à interroger)
3. Proportion signaux Tik veracity ≥ 0.95 sur 30 jours — partiellement
   mesurée (3.37 % au moment du refactor, mais sur l'ancienne
   architecture hybride, donc non comparable post-refactor)
4. Fréquence trading manuel — projection seulement (à mesurer post-J+14)

**Critère de bascule empirique défini complémentairement par
l'utilisatrice (2026-05-07)** : si **< 3 signaux directionnels par
semaine sur 2 semaines post-J+14**, alors bascule prévue vers
intégration **Polymarket** (cf. P8 du plan stratégique fiabilité signaux,
CLAUDE.md Paquet 18). Critère binaire mesurable directement en DB.

### Limitations connues post-bascule anticipée

1. **Hypothèses ADR-018 toujours à vérifier** post-J+14, le refactor a
   été exécuté sur la base de la **conviction** qu'elles seraient
   validées plutôt que sur leur **vérification empirique**.
2. **Comparabilité hit rate avant/après** dégradée : le golden dataset
   et les 156 signaux backtest sont sur l'ancienne architecture hybride.
   La comparaison post-refactor nécessitera **une nouvelle accumulation
   empirique** de 30+ jours.
3. **Volume de signaux directionnels post-refactor inconnu** : le seuil
   ±0.30 sur `combined_bias` est calibré au pifomètre. Le critère
   Polymarket *< 3 signaux/semaine* sera l'indicateur empirique de
   recalibration nécessaire.
4. **Trading manuel sur architecture < 2 semaines de runtime** : c'est
   inhabituellement court. Garde-fou 2-bis (sizing 1 %, veracity ≥ 0.90)
   reste **strictement applicable** pour absorber ce risque.

### Mémoire pour instances Claude futures

Si une future session questionne pourquoi l'ADR-018 a été activé sans
respect des conditions originales, **ne pas réécrire l'historique** :
les conditions étaient explicites, la décision de devancer était
consciente, le trade-off est documenté ici. La rigueur méthodologique
exige de **distinguer** :

- *Décision raisonnée d'enfreindre une règle qu'on s'était fixée*
  (ce cas : raison cohérente, conséquences acceptées)
- *Oubli d'une règle qu'on s'était fixée* (qui aurait justifié de
  signaler une erreur)

Cet amendement documente la première catégorie, pas la seconde.
