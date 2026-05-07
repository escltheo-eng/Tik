# Backtest empirique paliers sources numériques (P2)

**Date du run** : 2026-05-07T14:27:55.027356+00:00
**Période** : 365 jours (depuis 2025-05-07)
**Horizons mesurés** : 24h, 120h, 720h
**Seuils directionnalité** : 24h=0.5 % / 5j=1.0 % / 30j=2.0 %

## Résumé

| Source | Asset | Direction | n total | IC max (|.|) | Cas extrême max hit rate |
|---|---|---|---|---|---|
| **fear_greed** | BTC | contrarian | 364 | 0.1005 (720h) | 46.9% (720h) |
| **gdelt_tone** | GOLD | contrarian | 0 | - | - |
| **dxy** | GOLD | contrarian | 242 | 0.2345 (120h) | 25.0% (720h) |
| **cftc_cot** | GOLD | contrarian | 51 | 0.4274 (720h) | 20.0% (24h) |

## Recommandations chiffrées

- ⚠ **fear_greed @ 24h** : IC = -0.0133 (|IC| < 0.1) → source non significative à cet horizon.
- 🔴 **fear_greed @ 24h** : paliers extrêmes hit rate = 40.0% (n=140, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes).
- ⚠ **fear_greed @ 120h** : IC = -0.0464 (|IC| < 0.1) → source non significative à cet horizon.
- 🔴 **fear_greed @ 120h** : paliers extrêmes hit rate = 44.3% (n=140, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes).
- ⚠ **gdelt_tone** : aucun point évaluable, vérifier la source de données.
- 🔴 **dxy @ 24h** : IC Spearman = +0.0703 (signe opposé à `negative` attendu pour `contrarian`). Sémantique de l'overlay à reconsidérer.
- ⚠ **dxy @ 24h** : IC = +0.0703 (|IC| < 0.1) → source non significative à cet horizon.
- 🔴 **dxy @ 24h** : paliers extrêmes hit rate = 23.8% (n=21, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes).
- 🔴 **dxy @ 120h** : IC Spearman = +0.2345 (signe opposé à `negative` attendu pour `contrarian`). Sémantique de l'overlay à reconsidérer.
- ✅ **dxy @ 120h** : IC = +0.2345 (|IC| ≥ 0.2) → signal **fort**, garder le mapping actuel.
- 🔴 **dxy @ 120h** : paliers extrêmes hit rate = 18.8% (n=16, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes).
- 🔴 **dxy @ 720h** : IC Spearman = +0.0165 (signe opposé à `negative` attendu pour `contrarian`). Sémantique de l'overlay à reconsidérer.
- ⚠ **dxy @ 720h** : IC = +0.0165 (|IC| < 0.1) → source non significative à cet horizon.
- 🔴 **dxy @ 720h** : paliers extrêmes hit rate = 25.0% (n=12, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes).
- ✅ **dxy @ 720h**, palier `dxy_down` (bias=±0.5) : hit rate = 64.3% (n=56) → **palier moyen utile**.
- ⚠ **cftc_cot @ 24h** : IC = -0.0603 (|IC| < 0.1) → source non significative à cet horizon.
- 🔴 **cftc_cot @ 24h** : paliers extrêmes hit rate = 20.0% (n=10, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes).
- 🔴 **cftc_cot @ 720h** : IC Spearman = +0.4274 (signe opposé à `negative` attendu pour `contrarian`). Sémantique de l'overlay à reconsidérer.
- ✅ **cftc_cot @ 720h** : IC = +0.4274 (|IC| ≥ 0.2) → signal **fort**, garder le mapping actuel.
- 🔴 **cftc_cot @ 720h** : paliers extrêmes hit rate = 0.0% (n=10, < 45 %) → **paliers à élargir** (seuils extrêmes trop laxistes).

## Détail par source × horizon

### fear_greed (asset=BTC, direction=contrarian)

**n total** : 364

#### Horizon 24h

- **IC Spearman** : -0.0133 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 40.0% (n=140 sur 140 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| extreme_fear | +1.0 | 136 | 136 | 40.4% | +0.0681 |
| extreme_greed | -1.0 | 4 | 4 | 25.0% | +0.2332 |
| fear | +0.5 | 71 | 71 | 39.4% | -0.2480 |
| greed | -0.5 | 101 | 101 | 37.6% | -0.0878 |
| neutral | +0.0 | 52 | 0 | neutral | +0.0045 |

#### Horizon 120h

- **IC Spearman** : -0.0464 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 44.3% (n=140 sur 140 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| extreme_fear | +1.0 | 136 | 136 | 44.1% | -0.2143 |
| extreme_greed | -1.0 | 4 | 4 | 50.0% | -1.8317 |
| fear | +0.5 | 70 | 70 | 41.4% | -0.5018 |
| greed | -0.5 | 101 | 101 | 36.6% | -0.1428 |
| neutral | +0.0 | 49 | 0 | neutral | -0.1121 |

#### Horizon 720h

- **IC Spearman** : -0.1005 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 46.9% (n=130 sur 130 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| extreme_fear | +1.0 | 126 | 126 | 46.0% | -0.0642 |
| extreme_greed | -1.0 | 4 | 4 | 75.0% | -3.1530 |
| fear | +0.5 | 57 | 57 | 15.8% | -11.0878 |
| greed | -0.5 | 101 | 101 | 35.6% | +0.0721 |
| neutral | +0.0 | 47 | 0 | neutral | -2.2007 |

### gdelt_tone (asset=GOLD, direction=contrarian)

Aucun point évaluable.

### dxy (asset=GOLD, direction=contrarian)

**n total** : 242

#### Horizon 24h

- **IC Spearman** : +0.0703 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 23.8% (n=21 sur 21 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| dxy_down | +0.5 | 74 | 74 | 24.3% | -0.0129 |
| dxy_stable | +0.0 | 89 | 0 | neutral | +0.1504 |
| dxy_strong_down | +1.0 | 11 | 11 | 27.3% | -0.4369 |
| dxy_strong_up | -1.0 | 10 | 10 | 20.0% | +0.4196 |
| dxy_up | -0.5 | 57 | 57 | 19.3% | +0.0946 |

#### Horizon 120h

- **IC Spearman** : +0.2345 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 18.8% (n=16 sur 16 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| dxy_down | +0.5 | 55 | 55 | 25.4% | -0.1430 |
| dxy_stable | +0.0 | 72 | 0 | neutral | +0.9197 |
| dxy_strong_down | +1.0 | 9 | 9 | 33.3% | -2.5055 |
| dxy_strong_up | -1.0 | 7 | 7 | 0.0% | +1.7780 |
| dxy_up | -0.5 | 45 | 45 | 15.6% | +0.9642 |

#### Horizon 720h

- **IC Spearman** : +0.0165 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 25.0% (n=12 sur 12 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| dxy_down | +0.5 | 56 | 56 | 64.3% | +4.1150 |
| dxy_stable | +0.0 | 66 | 0 | neutral | +3.5685 |
| dxy_strong_down | +1.0 | 5 | 5 | 20.0% | +0.2889 |
| dxy_strong_up | -1.0 | 7 | 7 | 28.6% | +0.3326 |
| dxy_up | -0.5 | 43 | 43 | 16.3% | +3.1697 |

### cftc_cot (asset=GOLD, direction=contrarian)

**n total** : 51

#### Horizon 24h

- **IC Spearman** : -0.0603 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 20.0% (n=10 sur 10 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| mm_extreme_long | -1.0 | 10 | 10 | 20.0% | +0.5889 |
| mm_net_long | -0.5 | 41 | 41 | 21.9% | +0.3420 |

#### Horizon 120h

- **IC Spearman** : n/a (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = n/a (n=0 sur 0 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| mm_net_long | -0.5 | 1 | 1 | 0.0% | -0.5885 |

#### Horizon 720h

- **IC Spearman** : +0.4274 (attendu : negative)
- **Cas extrêmes (|bias|=1.0)** : hit rate = 0.0% (n=10 sur 10 extrêmes)

**Hit rate par palier** :

| Palier | bias | n | n_evaluable | hit_rate | delta_avg_pct |
|---|---|---|---|---|---|
| mm_extreme_long | -1.0 | 10 | 10 | 0.0% | +7.5176 |
| mm_net_long | -0.5 | 38 | 38 | 15.8% | +2.2573 |


---

## Limites assumées

- **Période 12m strongly bullish (2025-2026)** : régime haussier crypto + or. Reco issues ne couvriront pas un régime bear (à reproduire dans 6-12 mois).
- **COT hebdomadaire** = ~52 points/12m. IC Spearman bruité, à interpréter prudemment.
- **Direction contrarian assumée pour les 4 sources** : le drapeau `🔴 IC sign opposé` signale une remise en question potentielle de la sémantique.
- **Pas de prise en compte régime de marché** (bull/bear/range). Calibration globale sur 12m.
