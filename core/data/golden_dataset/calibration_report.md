# Rapport de calibration — golden dataset Tik

*Généré le 2026-05-02T15:03:48.214865+00:00*

- **Items totaux** : 100 (50 BTC + 50 GOLD)
- **Items annotés à la main** : 100
- **Items avec prediction Ollama** : 100
- **Horizons évalués** : 1h, 6h, 24h, 5d
- **Seuil de succès delta** : ±0.5%

## 1. Distribution des verdicts

| Verdict | Humain | Ollama | Keywords |
|---|---:|---:|---:|
| **bull** | 27 (27%) | 38 (38%) | 23 (23%) |
| **bear** | 17 (17%) | 39 (39%) | 12 (12%) |
| **neutral** | 56 (56%) | 23 (23%) | 65 (65%) |
| **n/a** | 0 (0%) | 0 (0%) | 0 (0%) |

## 2. Concordance humain ↔ classifier

- **Accuracy Humain ↔ Ollama** :  58.0%
- **Accuracy Humain ↔ Keywords** :  63.0%
- **Accuracy Ollama ↔ Keywords** :  49.0%

### Confusion matrix Humain (référence) ↔ Ollama (prediction)

Lecture : ligne = ce qu'Ollama a prédit, colonne = ce que l'humain a annoté.
Diagonale = accord. Hors-diagonale = divergence.

| Ollama \ Humain | bull | bear | neutral | n/a |
|---|---|---|---|---|
| **bull** | 20 | 0 | 18 | 0 |
| **bear** | 5 | 17 | 17 | 0 |
| **neutral** | 2 | 0 | 21 | 0 |
| **n/a** | 0 | 0 | 0 | 0 |

## 3. Calibration vs marché réel

*La vérité de référence objective. Compare chaque predictor au mouvement réel du prix.*

### Horizon 1h

| Predictor | n correct / n | hit rate |
|---|---|---:|
| **human** | 56 / 100 |  56.0% |
| **ollama** | 23 / 100 |  23.0% |
| **keywords** | 65 / 100 |  65.0% |

**Baselines** (pour comparaison) :

| Baseline | n correct / n | hit rate |
|---|---|---:|
| random | 34.2 / 100 |  34.2% |
| always_bull | 0 / 100 |   0.0% |
| always_bear | 0 / 100 |   0.0% |
| always_neutral | 100 / 100 | 100.0% |

### Horizon 6h

| Predictor | n correct / n | hit rate |
|---|---|---:|
| **human** | 56 / 100 |  56.0% |
| **ollama** | 23 / 100 |  23.0% |
| **keywords** | 65 / 100 |  65.0% |

**Baselines** (pour comparaison) :

| Baseline | n correct / n | hit rate |
|---|---|---:|
| random | 34.2 / 100 |  34.2% |
| always_bull | 0 / 100 |   0.0% |
| always_bear | 0 / 100 |   0.0% |
| always_neutral | 100 / 100 | 100.0% |

### Horizon 24h

| Predictor | n correct / n | hit rate |
|---|---|---:|
| human | n/a | n/a |
| ollama | n/a | n/a |
| keywords | n/a | n/a |

**Baselines** (pour comparaison) :

| Baseline | n correct / n | hit rate |
|---|---|---:|

### Horizon 5d

| Predictor | n correct / n | hit rate |
|---|---|---:|
| human | n/a | n/a |
| ollama | n/a | n/a |
| keywords | n/a | n/a |

**Baselines** (pour comparaison) :

| Baseline | n correct / n | hit rate |
|---|---|---:|

## 4. Performance par source

*Pour chaque source d'items, hit rate par predictor sur l'horizon principal.*

### Horizon de référence : 5d

| Source | n total | hit human | hit ollama | hit keywords |
|---|---:|---:|---:|---:|
| **cryptocompare** | 17 | n/a | n/a | n/a |
| **google_news** | 67 | n/a | n/a | n/a |
| **reddit** | 16 | n/a | n/a | n/a |

## 5. Pistes d'ajustement

Cette section est un **brouillon machine-générée**. À relire à la main avant tout ajustement structurel de Tik.

1. Si l'accuracy **Humain ↔ Ollama** est faible (<60%), c'est un signal fort que le LLM ne capte pas la sémantique financière comme un humain. À ce stade, ne pas survaloriser Ollama dans `SOURCE_SCORES`.
2. Si une source a un hit rate vs marché **significativement supérieur** à la moyenne (delta > 10 points), augmenter son entrée dans `SOURCE_SCORES`.
3. Si Tik (humain ou Ollama) **bat le baseline 'always X' le plus performant** sur la fenêtre testée, c'est qu'on apporte un edge réel. Sinon, on est dans le bruit.
4. Limites assumées : échantillon de ~100 items, période courte, pas de coûts de transaction. À élargir en Session 5+ avec plus d'items et plusieurs cycles de marché.
