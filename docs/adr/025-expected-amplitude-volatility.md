# ADR-025 — Amplitude attendue (volatilité réalisée) par signal, non directionnelle

**Statut** : Accepté — livré 2026-06-06
**Contexte trading** : aide à la décision pour le trading manuel BTC (Garde-fou 2-bis, sizing 1 %).

## Contexte

La trader demande, pour chaque signal, « de combien de % ou de points ça va
monter ou descendre, pour savoir si je le prends », et des horizons (timeframes)
plus précis.

Deux contraintes du projet encadrent cette demande :

1. **Aucun edge directionnel mesuré** (go/no-go 2026-05-27 = NO-GO directionnel).
   Tik est colinéaire à la tendance ; il ne prédit pas le *sens* de façon
   fiable. Annoncer « ça va monter de +X% » serait inventer une certitude que
   les données démentent.
2. **Axe stratégique #1** : ne pas peaufiner le « vernis de certitude » de l'UX
   tant que l'edge n'est pas prouvé.

Distinction-clé (confirmée par la littérature — volatility clustering / random
walk) : le **signe** d'un rendement est ~imprévisible, mais son **amplitude**
(volatilité) est statistiquement persistante donc *honnêtement estimable*.
Sources : Bouchaud et al., « The Random Walk behind Volatility Clustering »
(arXiv 1612.09344) ; ATR-based sizing (Wilder 1978).

## Décision

Ajouter à chaque signal une **amplitude attendue** = volatilité réalisée
typique sur l'horizon, **sans aucune affirmation sur le sens**.

- **Calcul** : `indicators.median_abs_return_pct(close, n_bars)` = médiane des
  `|variations|` sur `n_bars` barres, en % du prix. Médiane (pas moyenne) pour
  la robustesse aux queues épaisses crypto.
- **Fenêtres** (`n_bars`) alignées sur les horizons existants :
  - Swing BTC : bougies 4h → ~5 j = **30 barres**
  - Swing GOLD : bougies 1h → ~5 j ouvrés ≈ **120 barres**
  - Flash BTC : bougies 1m → ~1 h = **60 barres**
- **Transport** : posée dans `decision.advisory["expected_amplitude_pct"]` +
  `decision.advisory["ref_price"]` (prix de clôture à l'émission, pour la
  conversion en points). Champs ajoutés au schéma `Advisory`.
  **Pas de migration DB** — `advisory` est déjà une colonne JSON (évite tout
  risque sur l'hypertable Timescale, cf. bugs 1 et 9).
- **Affichage** :
  - Carte : `ampl ±X%` (scan rapide).
  - Détail : bloc « Amplitude attendue (volatilité) » → `±X% (≈ ±Y pts) sur ~Nj/h`
    + mention explicite *« Volatilité typique sur l'horizon — ce n'est PAS une
    prévision du sens »* (anti-vernis).
  - Horizons étiquetés précisément partout : `flash · ~1h`, `swing · ~5-7j`.
- **Points calibrés MT5** : `points.ts` BTC passe de 1,00 $ → **0,01 $** (Digits 2,
  tick 0,01, ActivTrades, fourni par la trader). GOLD inchangé (0,01, convention
  XAUUSD non confirmée broker). ⚠ Conséquence : tous les comptages de points BTC
  (y compris le track record) sont ×100 — c'est la valeur réelle du broker.

Poids **0** sur la décision : comme l'ATR (ADR-018), l'amplitude est du contexte,
elle ne touche ni direction, ni confidence, ni veracity.

## Alternatives écartées

| Option | Pour | Contre | Verdict |
|---|---|---|---|
| **A. Cible directionnelle chiffrée** (entry/stop/target présentés comme objectif) | Concret pour décider | Vernis de certitude sur une direction sans edge mesuré | ❌ Rejeté (viole Axe #1) |
| **B. Niveaux stop/cible ATR (1,5-2× / 2-3× ATR)** | Standard, utile au sizing | Risque d'être lu comme « Tik dit que ça atteindra ce prix » | ⏳ Différé (réévaluable, bien étiqueté) |
| **C. Colonne DB `expected_amplitude_pct`** | Champ first-class | Migration Alembic sur hypertable Timescale (lourde, risquée) | ❌ Rejeté → `advisory` JSON |
| **D. Amplitude = volatilité dans `advisory`** | Honnête, zéro migration, réversible | Nombres de points gros (×100) | ✅ **Retenu** |

## Conséquences & limites connues

- L'amplitude **ne dit rien du sens** — c'est volontaire. Elle **ne corrige pas**
  l'absence d'edge directionnel ; elle aide à juger si un mouvement vaut le
  spread/risque.
- C'est une **médiane** : ~la moitié du temps le mouvement réel dépasse la valeur
  affichée. Ce n'est pas un plafond.
- **Points GOLD non confirmés** sur le broker (à valider avec les specs MT5 Or).
- **BTC points ×100** vs avant (track record inclus) — attendu, pas un bug.
- Calibration empirique 2026-06-06 (réelle, BTC ~60 961 $) : swing ≈ 2,83 % (5j),
  flash ≈ 0,17 % (1h) — ordres de grandeur réalistes.

## Validation

- Suite pytest : **1507 verts** sur `tik_test` (dont 10 tests ADR-025).
- Ruff (config réelle) : clean. TypeScript dashboard : 0 erreur.
- Déploiement : prend effet après rebuild/restart du scheduler (émet les
  nouveaux signaux) et du core (sert les nouveaux champs). Les signaux antérieurs
  n'ont pas le champ → affichage « — » (rétro-compatible).
