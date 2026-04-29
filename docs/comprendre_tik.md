# Comment Tik analyse les marchés — guide pour les non-initiés

> Ce document est écrit pour quelqu'un qui n'a **aucune connaissance** en trading, en data science, ou en programmation. Si à un moment tu te perds, dis-le-moi : c'est que j'ai mal expliqué.

---

## 1. C'est quoi Tik, en une phrase ?

**Tik est un cerveau artificiel qui regarde plein de sources d'information sur les marchés financiers, croise ces informations entre elles, et émet des avis (« signaux ») pour aider à prendre des décisions de trading.**

Tik **ne passe jamais d'ordre lui-même**. Il dit juste : *« voilà ce que je pense de la situation, voilà mon niveau de confiance, et voilà ce qui pourrait me faire changer d'avis. »* C'est ensuite à un autre programme (par exemple le bot Zeta) ou à un humain de décider quoi faire.

---

## 2. C'est quoi un « signal » ?

Imagine la météo. Le matin, ton appli te dit :

> *« Demain à 14h : pluie probable à 70 %. Si le vent tourne au nord, ça pourrait basculer en orage. »*

Tu as :

- **Une prédiction** (« il va pleuvoir »)
- **Un niveau de confiance** (70 %)
- **Un contre-scénario** (« si le vent tourne au nord, ça change tout »)

Un signal Tik fonctionne **exactement pareil**, mais pour les marchés :

> *« BTC dans les 3 prochains jours : achat probable à 55 %. Si le sentiment du marché vire à l'euphorie, je perds confiance. »*

Tu as :

- **Une prédiction** (« acheter »)
- **Un niveau de confiance** (la `confidence`, ici 0.55)
- **Un niveau de fiabilité** (la `veracity`, on y revient)
- **Des contre-scénarios** (les conditions qui invalideraient le signal)
- **Des preuves** (les indicateurs sur lesquels Tik se base)

---

## 3. Les trois échelles de temps de Tik (« horizons »)

Tik analyse les marchés sur **trois échelles de temps** en parallèle, comme un médecin qui prendrait à la fois ta température, ton bilan sanguin annuel, et ton historique sur 10 ans :

| Horizon | Durée | À quoi ça sert |
|---|---|---|
| **Flash** | Minutes à quelques heures | Réagir vite à un événement (pas encore implémenté) |
| **Swing** | Quelques jours à 2 semaines | C'est notre niveau actuel pour BTC et GOLD |
| **Macro** | Plusieurs semaines à plusieurs mois | Vue d'ensemble, tendances de fond (partiellement implémenté) |

---

## 4. C'est quoi un « GOLD swing » alors ?

C'est une **analyse à horizon de quelques jours à 2 semaines** sur le cours de l'or (« GOLD »).

**Concrètement, toutes les 30 minutes, Tik fait ceci pour l'or :**

1. **Récupère les cours** : il télécharge les 60 derniers jours de cotation de l'or via Yahoo Finance (gratuit)
2. **Calcule trois indicateurs techniques classiques** sur ces cours :
   - **RSI** (Relative Strength Index) : mesure si le marché est « surchauffé » (trop d'acheteurs récents) ou « lessivé » (panique des vendeurs)
   - **EMA** (Exponential Moving Average) : moyenne du prix lissée sur 20 jours et sur 50 jours, pour détecter une tendance haussière ou baissière
   - **MACD** (Moving Average Convergence Divergence) : détecte les changements de momentum (accélération à la hausse ou à la baisse)
3. **Combine ces trois indicateurs** avec une logique de pondération
4. **Décide une direction** : `long` (acheter), `short` (vendre à découvert), ou `neutral` (rester en dehors du marché)
5. **Émet un signal** avec un niveau de confiance et de fiabilité

**Pour BTC c'est pareil**, sauf que :
- La source de cours est Binance (pas Yahoo)
- L'analyse tourne toutes les 15 minutes (pas 30) car le marché crypto est ouvert 24/7

---

## 5. Le problème de « regarder une seule source »

Imagine que tu doives décider si tu pars en vacances. Tu demandes à **un seul** ami : *« il fera beau ? »*

- S'il répond *« oui »*, tu pars.
- Mais s'il s'est trompé, tu te tapes une semaine sous la pluie.

Maintenant imagine que tu demandes à **trois amis indépendants** :

- Si les trois disent *« oui »* → tu peux y aller en confiance
- Si deux disent *« oui »* et un dit *« non »* → tu y vas, mais avec un parapluie
- Si les trois disent *« non, ça va être horrible »* → tu restes
- Si un dit *« oui canicule »* et un autre dit *« non tempête »* → c'est la cacophonie, prudence absolue

C'est exactement le principe de la **cross-validation** dans Tik. **Plus on a de sources qui se confirment mutuellement, plus on a confiance dans le signal.**

---

## 6. La fiabilité dynamique (« veracity »)

Tik attribue à chaque signal un **score de fiabilité** appelé `veracity`, entre 0 et 1 :

| Veracity | Signification |
|---|---|
| **0.95** | Très forte concordance entre les sources — signal très fiable |
| **0.90** | Concordance légère — signal fiable |
| **0.85** | Pas d'avis tranché — signal de base |
| **0.78** | Divergence légère — méfiance |
| **0.70** | Forte divergence entre sources — signal contradictoire, **prudence absolue** |

**Le mot magique : la veracity est dynamique.** Elle bouge en fonction de ce que les sources disent ENTRE ELLES, pas juste de ce qu'elles disent individuellement.

---

## 7. Premier exemple concret : BTC + Fear & Greed Index

C'est ce qu'on a déjà mis en place.

### C'est quoi le Fear & Greed Index ?

C'est un **indicateur de sentiment** publié quotidiennement par alternative.me. Il agrège plein de signaux (volatilité, volume, dominance BTC, recherches Google, sondages…) et produit un score de 0 à 100 :

- **0 à 25 = Extreme Fear** : tout le monde a peur, panique sur le marché
- **26 à 45 = Fear** : ambiance pessimiste
- **46 à 55 = Neutral** : ambiance calme
- **56 à 74 = Greed** : ambiance optimiste
- **75 à 100 = Extreme Greed** : euphorie générale

### Comment Tik s'en sert (logique « contrarian »)

L'intuition contre-intuitive du trading : **quand tout le monde a peur, c'est souvent le moment d'acheter. Quand tout le monde est euphorique, c'est souvent le moment de vendre.**

Tik applique cette règle :

| Sentiment du marché | Bias contrarian |
|---|---|
| Extreme Fear (panique) | **Acheter** (bull) |
| Fear | Acheter légèrement |
| Neutral | Pas d'avis |
| Greed | Vendre légèrement |
| Extreme Greed (euphorie) | **Vendre** (bear) |

### Le moment de la cross-validation

Quand Tik émet un signal sur BTC, il regarde **les indicateurs techniques** ET **le sentiment** :

**Cas 1 — Concordance forte (veracity = 0.95)** :
- Indicateurs techniques disent : *« BTC va monter »*
- Fear & Greed dit : *« Extreme Fear, panique »*
- → Les deux sources concordent (achat technique + opportunité contrarian de panique)
- → **Tik est très confiant**, veracity = 0.95

**Cas 2 — Divergence forte (veracity = 0.70)** :
- Indicateurs techniques disent : *« BTC va monter »*
- Fear & Greed dit : *« Extreme Greed, euphorie »*
- → Les deux sources divergent (achat technique mais marché survolté)
- → **Tik baisse fortement sa confiance**, veracity = 0.70 — *« attention, signal contradictoire »*

**Cas 3 — Pas d'avis fort (veracity = 0.85)** :
- Indicateurs techniques disent : *« neutre »* (pas de tendance claire)
- Fear & Greed dit n'importe quoi
- → Tik ne peut rien confirmer ni infirmer
- → veracity = 0.85 (la valeur de base)

---

## 8. Deuxième exemple — L'extension : GOLD + DXY

C'est ce qu'on vient d'implémenter. Le principe est exactement le même que pour BTC + Fear & Greed, mais avec une autre paire de sources.

### C'est quoi le DXY ?

Le **DXY** (Dollar Index) mesure la **force du dollar américain** par rapport à un panier d'autres grandes devises (euro, yen, livre sterling…). Quand le DXY monte, ça veut dire que le dollar se renforce. Quand il baisse, le dollar s'affaiblit.

On utilise une variante officielle publiée par la Réserve Fédérale américaine appelée **DTWEXBGS** (« Trade Weighted U.S. Dollar Index : Broad »). C'est gratuit, fiable, mis à jour quotidiennement.

### Pourquoi GOLD et DXY sont liés ?

Parce que l'or est **coté en dollars dans le monde entier**. Donc :

- **Si le dollar se renforce** (DXY ↑), l'or coûte mécaniquement plus cher pour les acheteurs étrangers → ils en achètent moins → le **prix de l'or baisse**
- **Si le dollar s'affaiblit** (DXY ↓), l'or devient relativement moins cher → demande qui augmente → le **prix de l'or monte**

C'est la **corrélation négative** classique GOLD/DXY. Pas absolue, mais très souvent vérifiée.

### Comment Tik va s'en servir

Toutes les 30 minutes, en plus de son analyse technique habituelle de l'or, Tik va :

1. **Récupérer la valeur du DXY** sur les 10 derniers jours via FRED (la Réserve Fédérale)
2. **Calculer la variation sur 5 jours ouvrés** (= 1 semaine)
3. **Appliquer la logique contrarian inversée** :

| Variation DXY sur 5 jours | Signification | Bias sur l'or |
|---|---|---|
| ≥ +1.0 % | Dollar en forte hausse | Bear sur or (vendre) |
| +0.3 % à +1.0 % | Dollar en hausse | Bear léger |
| -0.3 % à +0.3 % | Dollar stable | Pas d'avis |
| -1.0 % à -0.3 % | Dollar en baisse | Bull léger (acheter) |
| ≤ -1.0 % | Dollar en forte baisse | Bull sur or (acheter) |

### Exemple concret

Imaginons les valeurs DXY suivantes :

```
J-7 (lundi dernier)  : 117.50
J (aujourd'hui)      : 119.20
Variation 5 jours    : (119.20 - 117.50) / 117.50 × 100 = +1.45 %
```

Le dollar a pris **+1.45 %** en une semaine, c'est une **forte hausse**.

Maintenant, imaginons que les indicateurs techniques de l'or disent :

- EMA 20 < EMA 50 : tendance baissière
- RSI bas : faiblesse
- MACD négatif : momentum baissier
- → **Direction technique : SHORT** (vendre l'or)

**Cross-validation** :
- Direction technique = SHORT (l'or va baisser)
- DXY = forte hausse → bias bear sur l'or (l'or va baisser)
- → **Forte concordance** : les deux disent "l'or va baisser"
- → **Veracity = 0.95** (signal très fiable)

Tik émet alors le signal suivant :

```
GOLD swing — short
confidence : 0.55
veracity : 0.95   ← veracity dynamique, boostée par concordance
hypothesis : "Swing short on GOLD based on EMA/RSI/MACD confluence"
evidence :
  - source: yahoo_finance, fact: "RSI=32, EMA20<EMA50, MACD négatif"
  - source: fred_dtwexbgs, fact: "DXY=119.20 (var 5j +1.45%)"
triggers :
  - ema_cross : EMA20 < EMA50
  - rsi : RSI bearish
  - macd : MACD below signal
  - dxy_correlation : DXY dxy_strong_up → contrarian bear GOLD
counter_scenarios :
  - macro_shock (15%) : "Surveiller un crash boursier soudain"
  - indicator_whipsaw (20%) : "Confirmer sur tendance journalière"
```

**Tu remarques quoi d'important ?**
- Il y a maintenant **2 sources** au lieu d'une seule (Yahoo Finance + FRED DXY)
- La veracity n'est plus figée à 0.85 mais **calculée dynamiquement** (0.95 dans ce cas)
- On peut **expliquer** au lecteur pourquoi Tik est si confiant : *« parce que la technique ET la macro vont dans le même sens »*

---

## 9. Le framework « paranoïa contrôlée »

Une règle de fer dans Tik : **chaque signal doit toujours contenir au moins 2 contre-scénarios.** Tik se demande systématiquement *« qu'est-ce qui pourrait me faire avoir tort ? »*.

C'est ce qui distingue Tik d'un simple bot naïf qui crierait *« ACHÈTE ! »* sans jamais douter de lui-même.

### Exemple de contre-scénarios pour un signal swing :

1. **`macro_shock`** (probabilité 15 %) : *« Un événement macro majeur (krach, annonce de la Fed, conflit géopolitique) pourrait inverser brutalement la tendance. Mitigation : surveiller le DXY et les taux 10 ans. »*

2. **`indicator_whipsaw`** (probabilité 20 %) : *« Les indicateurs techniques pourraient donner un faux signal sur courte période. Mitigation : confirmer la direction sur la tendance journalière (1 jour). »*

Tik livre ces contre-scénarios **avec chaque signal**. Le bot consommateur (Zeta, Totem, ou un humain) sait exactement à quoi s'attendre et quoi surveiller pour invalider la décision.

---

## 10. La hiérarchie des sources (« scores de crédibilité »)

Toutes les sources ne se valent pas. Tik leur attribue un **score de crédibilité** entre 0 et 1, qui pèse sur la confiance globale du signal :

| Source | Score | Justification |
|---|---|---|
| Binance (cours BTC) | **0.90** | Flux marché direct, données temps réel non altérées |
| FRED (données macro US, dont DXY) | **0.85** | Source officielle de la Réserve Fédérale, fiabilité gouvernementale |
| Yahoo Finance (cours GOLD) | **0.80** | Agrégateur grand public avec délai 15 min, fiable mais moins direct |
| CryptoCompare news (CoinDesk Data) | **0.70** | Signal direct mais textuel, sentiment dérivé via mots-clés sur titres |
| Fear & Greed Index | **0.65** | Sentiment indirect, agrégat d'agrégats, plus interprétatif |

Plus une source est **directe et neutre**, plus son score est élevé. Une source qui interprète déjà des données (comme un indice de sentiment) a un score plus modéré.

---

## 11. Pour résumer

### Ce que Tik fait pour chaque signal

1. **Collecte** des données depuis plusieurs sources indépendantes
2. **Analyse** chaque source individuellement (techniques, sentiment, macro)
3. **Croise** les conclusions : est-ce que les sources sont d'accord ?
4. **Ajuste** son niveau de fiabilité en fonction de la concordance/divergence
5. **Émet** un signal avec :
   - Une direction (acheter / vendre / neutre)
   - Un niveau de confiance technique
   - Un niveau de fiabilité dynamique
   - Une hypothèse expliquée en clair
   - Des contre-scénarios pour rester humble
   - La traçabilité complète des preuves

### Ce qui rend Tik différent

- **Multi-sources** : pas d'avis basé sur une seule donnée
- **Cross-validation** : confronte systématiquement les sources
- **Veracity dynamique** : la fiabilité bouge en fonction de la cohérence des sources
- **Paranoïa contrôlée** : Tik admet toujours qu'il peut avoir tort
- **Transparence totale** : chaque signal expose ses preuves et ses doutes

---

## 12. État actuel et pistes futures

### Ce qui marche aujourd'hui

- ✅ Analyse swing pour **BTC** (toutes les 15 min) avec **3 sources** : **Binance** (cours) + **Fear & Greed Index** (sentiment crypto contrarian) + **CryptoCompare news** (sentiment textuel trend-following)
- ✅ Analyse swing pour **GOLD** (toutes les 30 min) avec **2 sources** : **Yahoo Finance** (cours) + **FRED DXY** (macro)
- ✅ **Veracity dynamique** pour les deux actifs (entre 0.70 et 0.95) selon la concordance entre sources. Pour BTC, la veracity est calculée sur la **moyenne des biais sentiment** (architecture multi-overlay extensible)
- ✅ Framework « paranoïa contrôlée » respecté : chaque signal contient hypothèse, contre-scénarios, evidence et triggers
- ✅ Authentification API (clé Bearer), Swagger interactif, healthchecks Docker propres

**Les deux actifs sont cross-validés multi-sources** avec veracity dynamique. Le pattern d'overlay est un composant réutilisable : ajouter une 4e source pour BTC (ou une 3e pour GOLD) = quelques lignes de code.

### Pistes futures (par ordre de priorité)

- **Backtest** : faire jouer les signaux passés contre les cours historiques pour mesurer si l'edge est réel
- **NLP avancé** : remplacer l'analyse par mots-clés (CryptoCompare) par un vrai modèle (FinBERT, ou un LLM local via Ollama) pour mieux gérer la négation, le contexte, le sarcasme
- **SDK Python** (`tik-sdk`) : package pip-installable pour brancher les bots clients (Zeta, Totem) sur Tik
- **Dashboard Expo mobile** : visualisation temps réel des signaux sur smartphone
- **Engines flash et macro** : étendre les horizons d'analyse (minutes pour flash, semaines pour macro)
- **Sources additionnelles** : Reddit (r/CryptoCurrency), Polymarket (marchés prédictifs), on-chain metrics (Glassnode), CFTC COT report pour GOLD
- **Module anti-fake-news** : cross-validation entre sources de news pour détecter les rumeurs/manipulations

---

## Glossaire des termes clés

- **Signal** : un avis émis par Tik à un instant donné sur un actif
- **Horizon** : la durée sur laquelle un signal est valide (flash / swing / macro)
- **Direction** : le sens du signal (long = acheter, short = vendre, neutral = ne rien faire)
- **Confidence** : le niveau de conviction technique du signal, entre 0 et 1
- **Veracity** : le niveau de fiabilité du signal, calculé via la cross-validation, entre 0 et 1
- **Evidence** : les preuves factuelles (chiffres, indicateurs, valeurs) sur lesquelles le signal se base
- **Triggers** : les éléments déclencheurs de la décision avec leur poids
- **Counter-scenarios** : les scénarios alternatifs qui pourraient invalider le signal
- **Source** : un fournisseur de données externe (Binance, Yahoo, FRED, etc.)
- **Cross-validation** : la confrontation de plusieurs sources pour évaluer la fiabilité
- **Bias contrarian** : la logique « faire l'inverse de la foule » (acheter quand tout le monde panique, vendre quand tout le monde est euphorique)
- **RSI / EMA / MACD** : trois indicateurs techniques classiques utilisés en analyse boursière
- **DXY / DTWEXBGS** : un indice mesurant la force du dollar US

---

*Document rédigé le 2026-04-28, mis à jour le 2026-04-29 (ajout 3e source CryptoCompare pour BTC). Pour expliquer Tik à toute personne curieuse, sans prérequis technique.*
