# Constat officiel — Backtest flash BTC (2026-07-02)

> **Verdict : le flash BTC n'a PAS de fiabilité directionnelle.** Il fait moins
> bien que le hasard et **significativement pire que la simple tendance**
> (test apparié p=0,000 vs Always SHORT ET vs Always LONG). Le NO-GO
> directionnel officiel du 2026-05-27 (mesuré sur le swing) **s'étend au flash**.
>
> **Toute session future qui croit « découvrir » un edge flash doit relire ce
> document et re-mesurer AVANT d'affirmer quoi que ce soit.**

---

## 1. Contexte

- Déclencheur : observation utilisatrice du 2026-07-01 — *« j'ai des flash sur
  BTC en dehors de short, je souhaiterais vérifier la fiabilité »* (des flash
  `long`/`neutral` apparaissaient alors que le marché est bear).
- Le `backtest.py` standard évalue en **jours** — inadapté au flash qui vit en
  **minutes-heures**. Un script dédié a été écrit :
  `core/src/tik_core/scripts/backtest_flash.py` (klines Binance 1m paginées,
  index de prix dichotomique, mêmes baselines + test apparié que le backtest
  standard, cf. mémoires `measurement-rigor-controls` /
  `measurement-overlapping-returns`).

## 2. Protocole

| Paramètre | Valeur |
|---|---|
| Signaux | TOUS les flash BTC en base (`horizon='flash'`, `entity_id='BTC'`) |
| Évalués | **9160** (sur 9166 en base ; les plus récents que l'horizon sont exclus) |
| Horizon | **60 minutes** (t0 → t0+60 min, prix close klines 1m Binance) |
| Seuil directionnel | ±0,1 % (long réussit si Δ > +0,1 %, short si Δ < −0,1 %, neutral si |Δ| < 0,1 %) |
| Baselines | Always LONG / SHORT / NEUTRAL, Random, + **test apparié de gain** vs les 2 tendances |
| Reproductibilité | Run exécuté **2 fois** (2026-07-01 et 2026-07-02) → **chiffres identiques** |

Commande :

```bash
docker exec tik-core python -m tik_core.scripts.backtest_flash --horizon-minutes 60 --threshold 0.1
```

## 3. Résultats mesurés

### Global

| Stratégie | Hit rate | Gain moyen |
|---|---|---|
| **Tik flash** | **33,0 %** | **−0,120 %** |
| Random | 33,4 % | — |
| Always LONG | ~ | −0,021 % |
| **Always SHORT** | **39,4 %** | **+0,021 %** |

### Par direction

| Direction | N | Hit rate | Gain moyen | Lecture |
|---|---|---|---|---|
| short | ~2900 | 39,6 % | ≈ tendance | **Recopie Always SHORT — zéro info ajoutée** |
| long | ~2700 | 35,2 % | négatif | Pas fiable |
| neutral | **3556** | **26,0 %** | **−0,311 %** | **Le pire ET le plus gros bucket** |

### Test apparié (le vrai juge — cf. `measurement-rigor-controls`)

| Comparaison | Δgain moyen | p | Verdict |
|---|---|---|---|
| Tik vs Always SHORT | **−0,142 %** | **0,000** | **SIGNIFICATIVEMENT PIRE** |
| Tik vs Always LONG | **−0,099 %** | **0,000** | **SIGNIFICATIVEMENT PIRE** |

Tik flash est significativement pire que la tendance **dans les deux sens** :
il ne se contente pas de manquer d'edge, ses changements de direction
détruisent de la valeur par rapport à ne rien décider du tout.

## 4. Pourquoi (mécanisme, pas spéculation)

Le flash tire sa direction du `combined_bias` de 2 overlays microstructure
(orderbook imbalance + aggression taker, ADR-005), seuil 0,30. Ces mesures
sont du **présent instantané** (qui achète/vend MAINTENANT), pas du prédictif
à 60 min. Résultat mesuré cohérent : les `short` collent à la tendance
(colinéarité, comme le swing), les `neutral` échouent car BTC bouge de plus de
±0,1 % en 60 min la plupart du temps, les `long` sont des rebonds
microstructure qui ne tiennent pas l'heure.

## 5. Décisions actées

1. **Le flash reste du CONTEXTE microstructure, pas un signal.** Un flash
   `long`/`neutral` n'est **pas** un signal d'achat. NO-GO directionnel étendu
   au flash. (Répercuté dans `CLAUDE.md` § 8 « La vérité empirique ».)
2. **Interdit de re-tuner le seuil 0,30** (ou le ±0,1 % du backtest) pour
   « améliorer » le hit rate : c'est de l'overfitting sur le passé, ça gonfle
   le chiffre sans créer de fiabilité (Axe #1 — pas de vernis de certitude).
3. Le script `backtest_flash.py` est l'outil de référence pour toute
   re-mesure flash (re-mesurer AVANT toute affirmation d'edge flash).

## 6. Limites connues (honnêtes)

1. **Fenêtres chevauchantes** : les flash rapprochés partagent leurs 60 min →
   observations non indépendantes → le p=0,000 est optimiste. Mais l'écart
   (−6,4 points de hit vs Always SHORT sur 9160 signaux) est trop large pour
   être un artefact du chevauchement.
2. **Un seul régime de marché** : période mesurée ≈ bear (mai-juillet 2026).
   Non testé en bull / range.
3. **Un seul horizon mesuré** : 60 min. Les horizons 15 min et 240 min ne sont
   PAS mesurés à ce jour (option ouverte, faible espérance — un edge qui
   n'apparaîtrait qu'à un horizon précis sentirait l'overfitting).
4. **Pas de coûts de transaction / slippage** — ils ne feraient qu'empirer le
   résultat Tik.
