# ADR-004 — Architecture multi-overlay pour la cross-validation des signaux

- **Statut** : Accepté
- **Date** : 2026-04-29

## Contexte

Le moteur swing de Tik produit pour chaque entity (BTC, GOLD) une décision
basée sur des indicateurs techniques (RSI, EMA, MACD). Cette décision a une
**veracity** entre 0 et 1 qui exprime la fiabilité du signal.

Initialement, la veracity était **figée à 0.85**. Pour la rendre dynamique,
on a introduit la notion d'**overlay** : une source de sentiment ou de
macro-données qui « enrichit » la décision technique en :
- ajoutant une evidence (preuve avec score de crédibilité)
- ajoutant un trigger (indicateur pondéré dans la décision)
- ajustant la veracity selon la concordance avec la direction technique

Le premier overlay (Fear & Greed Index pour BTC) implémentait cette logique
avec une fonction `_apply_fear_greed_overlay` qui **calculait et SET la
veracity directement** sur la décision.

**Problème quand on a voulu ajouter une 2e source de sentiment** (CryptoCompare
news pour BTC) : si on enchaîne deux overlays qui SET tous les deux la veracity,
**le second écrase le premier**. Pas de combinaison possible. Le code devenait
non-déterministe selon l'ordre d'application.

Une décision architecturale s'imposait : comment **composer plusieurs sources**
de sentiment/macro sur une même entity ?

## Décision

**Pattern « multi-overlay » avec composition par moyenne des biais.**

Chaque source de sentiment / macro est exposée par un helper
`_enrich_with_<source>(decision, data) -> float | None` qui :

1. Ajoute son **evidence** dans `decision.evidence`
2. Ajoute son **trigger** dans `decision.triggers`
3. Calcule son **bias** (entre -1 et +1) selon la sémantique de la source
   (contrarian pour FG/DXY, trend-following pour news)
4. **Retourne le bias** au lieu de SET la veracity
5. Retourne `None` si les données sont invalides (et n'enrichit rien)

La fonction d'analyse principale (`analyze_swing_btc`, `analyze_swing_gold`)
**collecte tous les biais valides** dans une liste, calcule leur **moyenne
arithmétique**, et applique
`_veracity_from_concordance(direction_technique, moyenne_biais)` pour
calculer la veracity finale.

Pseudo-code :

```python
async def analyze_swing_xxx(...) -> SwingDecision:
    decision = _score_indicators(df)  # techniques d'abord

    bias_signals: list[float] = []
    for helper in [_enrich_with_source1, _enrich_with_source2, ...]:
        bias = helper(decision, ...)
        if bias is not None:
            bias_signals.append(bias)

    if bias_signals:
        combined_bias = sum(bias_signals) / len(bias_signals)
        decision.veracity = _veracity_from_concordance(
            decision.direction, combined_bias
        )

    return decision
```

## Règles d'intégration

1. **Un helper retourne un bias dans `[-1, +1]`**, jamais la veracity.
2. **Le sens du bias suit la sémantique de la source** :
   - **Contrarian** (FG, DXY) : sentiment extrême → bias inverse (peur extrême → bull)
   - **Trend-following** (news, on-chain) : sentiment direct → bias direct (news bullish → bull)
3. **L'evidence doit contenir** `source` (clé de `SOURCE_SCORES`), `score`
   (lu depuis `SOURCE_SCORES`), `fact` (chaîne lisible).
4. **Le trigger doit contenir** `type`, `value` (chaîne lisible avec contexte),
   `weight` (typiquement 0.10 pour overlay sentiment/macro).
5. **Si une source manque de données** (Redis vide, API down, données
   insuffisantes), retourner `None` et ne rien enrichir. Le caller skip.
6. **La fonction `_score_indicators` reste responsable de la décision
   technique pure** (long/short/neutral, confidence). Les overlays ne
   modifient ni la direction ni la confidence — uniquement evidence,
   triggers et veracity.
7. **Pas de pondération différenciée par source** dans la moyenne :
   moyenne arithmétique simple. À réviser plus tard quand on aura assez
   de données de backtest pour mesurer la valeur ajoutée par source.

## Conséquences

**Positives**

- **Ajouter une nouvelle source coûte 4 lignes** dans `analyze_swing_xxx`,
  plus le nouveau helper. Pas de refactor de la logique existante.
- **Aucun risque d'override silencieux** de la veracity : un seul endroit
  (la fonction d'analyse) la calcule, à partir de toutes les sources.
- **Code symétrique** entre BTC et GOLD (tous deux suivent ce pattern).
- **Veracity 0.85 préservée** quand aucune source n'a d'avis fort : la
  moyenne tend vers 0, et `_veracity_from_concordance(direction, 0) = 0.85`.
- **Sources contradictoires se neutralisent** : si une source dit bull et
  une autre dit bear avec la même intensité, la moyenne tombe à 0 et la
  veracity reste à 0.85 — Tik signale alors « pas d'info nette du sentiment ».

**Négatives**

- **Moyenne arithmétique non pondérée** : si une source à `SOURCE_SCORES`
  élevé (ex : `fred_dtwexbgs` = 0.85) et une à `SOURCE_SCORES` faible
  (ex : `alternative_me_fng` = 0.65) ont des avis opposés, leur poids dans
  la moyenne est identique. Une source moins fiable peut donc neutraliser
  une source plus fiable.
- **Pas de seuil minimum de sources** : avec 1 seule source, le bias unique
  pèse autant qu'une moyenne de 3 sources. Pas grave en pratique car
  `_veracity_from_concordance` plafonne à 0.95, mais sémantiquement moins
  robuste.
- **Pas de gestion explicite de la dépendance entre sources** : si deux
  sources mesurent la même chose (ex : deux fournisseurs de news qui
  reprennent les mêmes dépêches), leur bias compte deux fois.

## Implémentation actuelle (au 2026-04-29)

| Helper | Entity | Sémantique | Source de données |
|---|---|---|---|
| `_enrich_with_fear_greed` | BTC | Contrarian | Redis `tik.sentiment.fear_greed` |
| `_enrich_with_cryptocompare` | BTC | Trend-following | Redis `tik.sentiment.cryptocompare.btc` |
| `_enrich_with_dxy` | GOLD | Contrarian (corrélation négative GOLD/DXY) | Fetch direct FRED API |

Tous trois suivent le contrat : retournent `float | None`, n'altèrent pas
la veracity directement.

La fonction utilitaire `_veracity_from_concordance(direction, bias) -> float`
applique le mapping suivant :

| Concordance (`dir_score × bias`) | Veracity |
|---|---|
| `≥ +0.9` (forte concordance) | 0.95 |
| `≥ +0.4` (concordance légère) | 0.90 |
| `> -0.4` et `< +0.4` (neutralité) | 0.85 |
| `> -0.9` (divergence légère) | 0.78 |
| `≤ -0.9` (forte divergence) | 0.70 |

## Alternatives rejetées

- **Override séquentiel** (chaque overlay SET la veracity, le dernier
  gagne) : non-déterministe selon ordre d'application, perd l'information
  des sources précédentes. Première implémentation, abandonnée à l'ajout
  de la 2e source.
- **Pondération par `SOURCE_SCORES`** dans la moyenne :
  `combined = Σ(bias_i × score_i) / Σ(score_i)`. Plus rigoureux en théorie,
  mais sur-engineering tant qu'on n'a pas de données de backtest qui montrent
  l'effet réel de chaque source. À reconsidérer après plusieurs semaines
  de signaux + backtests.
- **`max` des veracitys si concordance, `min` si divergence** : moins
  lisible, plus complexe, et ne s'étend pas naturellement à 3+ sources.
- **Réseau de neurones / modèle ML** sur la combinaison des biais :
  prématuré, on n'a pas encore l'historique de feedback PnL nécessaire
  pour entraîner.

## Évolutions futures envisagées

- **Pondération par score de crédibilité** une fois qu'on aura mesuré la
  valeur ajoutée de chaque source via backtest (mois 2-3 d'exploitation).
- **Seuil minimum de sources concordantes** pour booster la veracity
  au-dessus de 0.90 (ex : exiger 2 sources sur 3 d'accord).
- **Détection de redondance** entre sources de news (CryptoCompare,
  CryptoPanic ressuscité, futures sources Reddit / Twitter) pour éviter
  le double comptage.
- **Modèle ML léger** (régression logistique) sur les biais individuels
  pour prédire le hit rate, une fois qu'on aura suffisamment de feedback PnL.
