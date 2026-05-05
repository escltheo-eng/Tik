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

## 9. Troisième exemple — La 2e source pour GOLD : CFTC COT (Managed Money)

Ajouté le 2026-04-30. **Le but de cet ajout, au-delà de l'utilité métier, était de tester en grandeur réelle que le pattern multi-overlay marche bien quand on enchaîne plusieurs sources sur la même entity.** Spoiler : oui, et l'ajout n'a coûté qu'un nouvel ingester + un helper + 5 lignes dans la fonction d'analyse GOLD.

### C'est quoi le rapport CFTC COT ?

Le **CFTC COT** (Commitments of Traders) est un rapport hebdomadaire publié **chaque vendredi par la Commodity Futures Trading Commission**, l'autorité américaine qui régule les marchés de matières premières. Il révèle **qui détient quoi** sur les marchés de futures — pas le grand public, mais les **gros acteurs** (banques, hedge funds, producteurs, exportateurs).

Pour l'or, le rapport publie chaque semaine combien de contrats sont :
- détenus en **achat (long)** par chaque catégorie d'acteur
- détenus en **vente (short)** par chaque catégorie d'acteur

Les catégories sont notamment : producteurs/négociants, swap dealers, **Managed Money** (= hedge funds, fonds spéculatifs, CTAs), autres.

C'est gratuit, public, sans clé API. Tik récupère les données via l'endpoint Socrata officiel : `https://publicreporting.cftc.gov/resource/72hh-3qpy.json`.

### Pourquoi spécifiquement « Managed Money » ?

Parce que les Managed Money sont la catégorie qui parie le plus activement sur la **direction du prix** (les producteurs et utilisateurs industriels eux couvrent leurs activités physiques, ils ne font pas vraiment de paris directionnels). Si tu veux savoir « qu'est-ce que la smart money pense de l'or ? », tu regardes les Managed Money.

### La métrique : `mm_net_pct`

Tik calcule chaque semaine :

```
mm_net_pct = (longs MM - shorts MM) / (longs MM + shorts MM)
```

Cette valeur va de -1 (tous shorts) à +1 (tous longs). Exemple récent du 2026-04-21 :

```
Longs Managed Money  : 123 681 contrats
Shorts Managed Money :  30 705 contrats
mm_net_pct           : (123681 - 30705) / (123681 + 30705) = +0.60
```

Donc 60 % de plus de longs que de shorts. La smart money est **fortement haussière** sur l'or.

### Logique contrarian (encore !)

Comme pour le Fear & Greed et le DXY, Tik applique une **lecture contrarian** au COT, mais le raisonnement est légèrement différent. Au lieu de regarder une foule anonyme (Fear & Greed), on regarde des **professionnels qui ont parié leur capital** :

- **Si les Managed Money sont massivement net long** (ex : `mm_net_pct ≥ +0.7`), ça veut dire que **tout le monde au sommet est sur la même ligne**. Quand une foule de pros est unanime, c'est souvent **le moment où ils vont commencer à sortir** (prendre leurs bénéfices). Donc Tik émet un **bias bear sur GOLD**.
- **Si les Managed Money sont massivement net short** (ex : `mm_net_pct ≤ -0.7`), même raisonnement inversé : ils ont déjà parié à la baisse, le retournement à la hausse est probable. Bias **bull sur GOLD**.
- **Entre les deux**, pas d'avis fort.

| `mm_net_pct` | Zone | Bias contrarian sur GOLD |
|---|---|---|
| ≥ +0.7 | `mm_extreme_long` (foule très longue) | **Bear** (vendre) |
| +0.4 à +0.7 | `mm_net_long` | Bear léger |
| -0.4 à +0.4 | `mm_balanced` | Pas d'avis |
| -0.7 à -0.4 | `mm_net_short` | Bull léger (acheter) |
| ≤ -0.7 | `mm_extreme_short` (foule très shorte) | **Bull** (acheter) |

### La donnée n'est PAS temps réel

Important à comprendre : le COT est une **donnée hebdomadaire avec un lag de 3-4 jours** :
- Mardi : les positions sont enregistrées
- Vendredi 15:30 (ET) : le rapport est publié

Donc Tik récupère un instantané qui a 3-4 jours de retard. C'est **une vue de fond, pas un signal de réaction rapide**. C'est pour ça que le score de crédibilité de cette source est de **0.80** (un peu en dessous du DXY à 0.85, qui est mis à jour plus fréquemment).

### Que se passe-t-il pour GOLD maintenant ?

Avant le 2026-04-30, GOLD avait **1 seule source de cross-validation** (DXY). Maintenant, il en a **2** : DXY + COT.

Le mécanisme s'enchaîne automatiquement :

1. Tik calcule le **bias DXY** (par exemple `+0.5` = bull GOLD)
2. Tik calcule le **bias COT** (par exemple `-1.0` = bear GOLD, foule très longue à fuir)
3. Tik fait la **moyenne des deux biais** : `(0.5 + (-1.0)) / 2 = -0.25` → contradiction nette
4. Avec une moyenne proche de 0, la veracity reste à **0.85** (la valeur de base) — *« les sources se contredisent, pas d'avis tranché »*

Et si les deux sources s'accordent :

1. Bias DXY = `+1.0` (dollar en chute → bull GOLD)
2. Bias COT = `+1.0` (Managed Money très shorts → contrarian bull GOLD)
3. Moyenne = `+1.0`
4. Si direction technique = LONG → **veracity = 0.95** (forte concordance)

C'est exactement la même mécanique que pour BTC, juste avec d'autres sources. **Le pattern fonctionne pour n'importe quelle entity du moment qu'on lui ajoute un helper qui retourne un bias entre -1 et +1.**

### Limite assumée

Les seuils contrarian (`±0.4`, `±0.7`) sont **absolus**. Or les Managed Money sont **structurellement net long sur GOLD** (souvent 60-80 % en moyenne historique sur plusieurs années). Donc Tik pourrait ne jamais déclencher le bias bull (il faudrait que les MM passent net short, ce qui est rare). À surveiller dans 3-6 semaines : si les biais COT sont systématiquement à `-0.5` ou `-1.0`, on recalibrera en **z-score 52 semaines** (= "où en sont les MM par rapport à leur propre normale historique ?") plutôt qu'en seuils absolus.

Une routine planifiée a déjà été créée pour faire cette analyse automatiquement le 2026-05-21.

---

## 10. Le framework « paranoïa contrôlée »

Une règle de fer dans Tik : **chaque signal doit toujours contenir au moins 2 contre-scénarios.** Tik se demande systématiquement *« qu'est-ce qui pourrait me faire avoir tort ? »*.

C'est ce qui distingue Tik d'un simple bot naïf qui crierait *« ACHÈTE ! »* sans jamais douter de lui-même.

### Exemple de contre-scénarios pour un signal swing :

1. **`macro_shock`** (probabilité 15 %) : *« Un événement macro majeur (krach, annonce de la Fed, conflit géopolitique) pourrait inverser brutalement la tendance. Mitigation : surveiller le DXY et les taux 10 ans. »*

2. **`indicator_whipsaw`** (probabilité 20 %) : *« Les indicateurs techniques pourraient donner un faux signal sur courte période. Mitigation : confirmer la direction sur la tendance journalière (1 jour). »*

Tik livre ces contre-scénarios **avec chaque signal**. Le bot consommateur (Zeta, Totem, ou un humain) sait exactement à quoi s'attendre et quoi surveiller pour invalider la décision.

---

## 11. La hiérarchie des sources (« scores de crédibilité »)

Toutes les sources ne se valent pas. Tik leur attribue un **score de crédibilité** entre 0 et 1, qui pèse sur la confiance globale du signal :

| Source | Score | Justification |
|---|---|---|
| Binance (cours BTC) | **0.90** | Flux marché direct, données temps réel non altérées |
| FRED (données macro US, dont DXY) | **0.85** | Source officielle de la Réserve Fédérale, fiabilité gouvernementale |
| Yahoo Finance (cours GOLD) | **0.80** | Agrégateur grand public avec délai 15 min, fiable mais moins direct |
| CFTC COT (positioning Managed Money) | **0.80** | Source officielle US gov, mais hebdomadaire avec lag 3-4 jours |
| CryptoCompare news (CoinDesk Data) | **0.70** | Signal direct mais textuel, sentiment dérivé via mots-clés sur titres |
| Fear & Greed Index | **0.65** | Sentiment indirect, agrégat d'agrégats, plus interprétatif |

Plus une source est **directe et neutre**, plus son score est élevé. Une source qui interprète déjà des données (comme un indice de sentiment) a un score plus modéré.

**Note : depuis la livraison de l'anti fake-news (cf. section suivante), ces scores ne sont plus figés**. Ils sont **ajustés automatiquement** chaque nuit selon la performance réelle de chaque source mesurée sur les signaux Tik des 30 derniers jours. Une source qui prédit mal voit son score baisser ; une source qui prédit bien voit le sien remonter (mais plus lentement — paranoïa contrôlée).

---

## 12. Anti fake-news : surveiller que les sources ne se contredisent pas trop

C'est l'évolution la plus structurante depuis la livraison initiale du Core. Deux mécanismes complémentaires.

### A. La cross-validation au moment de l'émission du signal

Imagine que Tik prépare un signal *long* sur BTC, et qu'au moment de combiner les biais des 4 sources sentiment, on observe :

- Fear & Greed dit **bull** (+0.5)
- CryptoCompare dit **bull** (+0.5)
- Google News dit **bull** (+0.5)
- Reddit dit **bear extrême** (-0.95)

Reddit est en désaccord total avec les 3 autres. Sans rien faire, Tik calculait juste la moyenne (≈ +0.14) et émettait le signal avec une veracity adoucie. Mais **Reddit ressort très clairement comme aberrant**. Et c'est précisément le genre de cas qui pourrait être une fake news, un brigading, ou un bug d'ingester.

Tik fait désormais deux choses :

1. **Détection statistique** des sources aberrantes via une méthode académique (Modified Z-score d'Iglewicz-Hoaglin, 1993) qui isole une valeur très éloignée de la médiane des autres. Sur l'exemple : Reddit est marqué `is_outlier: true` dans l'evidence, son biais est neutralisé dans la moyenne combinée (Tik n'utilise plus Reddit pour cette décision).

2. **Détection de dispersion globale** quand toutes les sources s'éclatent à 50/50 (ex: 2 disent bull, 2 disent bear avec la même intensité). Aucune source individuelle n'est aberrante mais c'est exactement le cas dangereux d'un désaccord majeur. Tik mesure la dispersion par écart-type, et si elle dépasse un seuil, le signal est marqué comme dégradé.

### Le `circuit_breaker_status` du signal

Chaque signal Tik porte désormais un drapeau :

- `"ok"` : sources concordantes, signal fiable
- `"degraded"` : disagreement notable, le signal est émis mais avec un drapeau visible côté dashboard et bot
- `"tripped"` : disagreement majeur, **direction forcée à `neutral`** et l'hypothèse est préfixée *"Anti fake-news : X/Y sources ont été marquées comme outliers — direction forcée à neutral"*. Le signal est émis pour traçabilité, mais il dit clairement *"je ne sais pas ce qu'il se passe"* plutôt que d'inventer une direction.

C'est ce drapeau qui réveille le hook `on_fake_news_detected` côté SDK (le code SDK qui écoutait ce signal était déjà prêt depuis la version 0.2.0, il dormait juste en attente).

### B. Le scoring source dynamique

Les scores de crédibilité du tableau ci-dessus (section 11) sont des **points de départ raisonnables**, pas des vérités. Tik les ajuste désormais automatiquement chaque nuit (03:00 UTC) selon la performance réelle de chaque source.

Le mécanisme :

1. Tik regarde les signaux des **30 derniers jours**
2. Pour chaque signal, il regarde si la prédiction (long/short/neutral) a été correcte par rapport au mouvement de prix réel à 5 jours
3. Il agrège par source : Reddit a-t-il contribué à des signaux gagnants ou perdants ?
4. Si une source a un **hit rate < 40 %** sur au moins 30 signaux, son score est **divisé par 1.2** (pénalité)
5. Si elle a un **hit rate > 70 %** sur au moins 30 signaux, son score est **multiplié par 1.1** (récompense)
6. Entre 40 % et 70 %, le score reste inchangé

**Pourquoi pénaliser plus rapidement qu'on récompense ?** Philosophie « paranoïa contrôlée ». Une mauvaise source peut faire perdre de l'argent dès qu'elle est sur-pondérée. Une bonne source qui a juste eu de la chance pendant 30 jours peut décevoir ensuite. Donc on pénalise vite, on récompense lentement.

**Bornes de sécurité** : aucun score ne descend sous 0.30 (on garde toujours un peu de poids — une source temporairement maladroite peut redevenir bonne) ni ne monte au-dessus de 0.95 (on évite la sur-confiance qui masquerait une dérive future).

### Mode actif vs mode shadow

Une variable d'environnement `TIK_ANTIFAKENEWS_MODE` permet de basculer :

- `active` (défaut) : la cross-validation modifie réellement les signaux émis (drapeau, evidence outlier, force neutral si tripped)
- `shadow` : la cross-validation est juste calculée et logguée, mais le signal est émis comme avant

Si jamais l'algorithme avait un bug, on peut basculer en `shadow` sans redéployer le code (juste `docker compose restart` du scheduler avec la nouvelle variable d'env). Filet de sécurité.

### Audit dans le temps

Une nouvelle table `source_credibility_history` enregistre chaque ajustement (1 ligne par source par nuit). Permet de répondre à *« pourquoi le score de Reddit a-t-il chuté il y a 2 mois ? »* — on retrouve le hit rate du moment et le nombre de signaux qui ont conduit à la décision.

---

## 13. Comment Tik rédige ses hypothèses (depuis 2026-05-03)

Avant cette date, l'hypothèse affichée en haut du signal était une simple phrase générée mécaniquement :

> *« Swing long on BTC based on EMA/RSI/MACD confluence (bull=0.65, bear=0.18) »*

C'était utile mais sec. Toute la richesse du signal (les sources qui convergent ou divergent, les contre-scénarios, le statut anti fake-news, le niveau à surveiller) restait cachée dans les sections du dessous.

Depuis le 2026-05-03, **Tik utilise le même modèle d'IA local que pour le sentiment news** (`llama3.2:3b` qui tourne sur ton Mac via Ollama, sans rien envoyer à internet) pour **rédiger une synthèse contextuelle** en 6 sections fixes :

1. **Verdict + qualité** — direction, asset, confidence, veracity
2. **Lecture technique** — quels indicateurs convergent
3. **Lecture sentiment cross-validée** — chaque source nommée avec son biais
4. **Statut anti fake-news** — quelles sources sont flaggées (s'il y en a)
5. **Risque principal** — le contre-scénario le plus probable + sa mitigation
6. **À surveiller** — niveau ou événement qui invaliderait la thèse

**Exemple de sortie** (signal flash BTC short observé le 2026-05-03 à 21:34) :

> *Verdict and quality: Short BTC with confidence 0.55 and veracity 0.95.*
>
> *Technical reading: The EMA cross trigger is confirmed by the RSI bearish trigger, while the MACD below signal line reinforces this trend. The orderbook imbalance and trade aggression indicators also point to a strong sell signal.*
>
> *Sentiment cross-validation: Binance_klines_1m credibility 0.90 confirms the RSI14=40.4 level, while binance_orderbook credibility 0.85 supports the OBI=-0.73 top-20 levels. Binance_aggtrades credibility 0.85 reinforces the taker buy_ratio=0.32.*
>
> *Anti fake-news status: All sources are flagged as 'ok'.*
>
> *Main risk: The most probable counter-scenario is a micro-whipsaw with probability 0.30, which can be mitigated by confirming direction on multiple timeframes (1h confluence).*
>
> *Watch: Monitor the key level of OBI=-0.73 for potential price movements.*

Le LLM cite les sources nommément avec leur score de crédibilité, restitue le contre-scénario avec sa probabilité, et nomme le niveau à surveiller. **Plus besoin de lire 5 cartes pour comprendre pourquoi Tik recommande cette direction.**

### Le filet de sécurité — mode `shadow` par défaut

Comme pour l'anti fake-news (cf. ADR-011), il y a deux niveaux de sécurité :

- **Mode `shadow` (par défaut)** : le LLM s'exécute, mais sa sortie est **stockée à part** dans un champ secondaire (`Signal.advisory.llm_hypothesis_candidate`). Le champ `Signal.hypothesis` qu'affichent l'app et l'API garde le texte template historique. C'est l'occasion de comparer pendant quelques jours, sans risque qu'un LLM qui « hallucinerait » ne donne une fausse info dans le dashboard.
- **Mode `active`** : la sortie LLM **remplace** le texte template. L'ancien template est conservé dans `Signal.advisory.template_hypothesis` pour audit. Bascule via la variable d'env `TIK_LLM_HYPOTHESIS_MODE=active` + restart du scheduler.

Si Ollama plante (Mac éteint, app fermée, etc.) ou met trop de temps à répondre (>30 sec), Tik revient automatiquement sur le texte template — **aucun signal n'est jamais perdu**. Le statut « circuit breaker batch-level » garantit que 3 erreurs successives basculent tout le batch en template, avec retour automatique au cycle suivant.

### Pourquoi en anglais ?

Toutes les sources de news que Tik consomme sont filtrées sur `lang=EN`, et les `evidence`/`triggers`/`counter_scenarios` sont en anglais. Faire l'hypothèse en français aurait créé un mélange de langues incohérent dans un même signal, et le LLM 3B est moins précis en français qu'en anglais sur le jargon trading. La traduction française complète du signal (tous les champs textuels d'un coup) est prévue dans une prochaine itération via un paramètre `?lang=fr` côté API.

---

## 14. Pourquoi tous les timestamps Tik portent un Z

### Le bug d'affichage qui a tout déclenché

Le 2026-05-04, l'utilisatrice a remarqué que tous les libellés « il y a X minutes » affichés par le dashboard étaient **systématiquement en avance de 2 heures** (en CEST, c'est-à-dire en France au printemps/été). Un signal émis il y a 5 minutes affichait « il y a 2 h 5 min ». Comme si le scheduler de Tik avait pris 2 heures de retard. Mais en vérifiant les logs du core, les signaux étaient bien émis aux fréquences attendues. **Pas un bug Tik, mais un bug d'affichage.**

### La cause : l'horloge sans étiquette

Le core émettait ses timestamps via une fonction Python qui retourne un instant sans dire dans quel fuseau horaire il est exprimé (techniquement : un *datetime naïf*). Concrètement, Tik écrivait `"2026-05-04T11:32:14"` sans préciser que c'était de l'UTC.

Côté dashboard, JavaScript reçoit cette chaîne et — en l'absence d'étiquette de fuseau — l'**interprète comme heure locale**. Donc Tik dit « 11:32 UTC » mais le dashboard comprend « 11:32 Paris CEST » = 09:32 UTC. D'où le décalage de 2 heures.

C'est un piège classique : **le même chiffre 11:32 ne veut pas dire la même chose** selon qu'il est étiqueté UTC ou local. Sans étiquette, c'est une ambiguïté qui finit toujours par mordre.

### Le fix en deux temps

**Temps 1 — côté dashboard (le 2026-05-04 matin)** : un petit utilitaire `parseUtcIso` qui ajoute la lettre `Z` (UTC explicite) si elle manque dans la chaîne. Bug résolu en 30 minutes pour l'utilisatrice. Mais ce filet ne couvre que le dashboard — le SDK Python et le futur connecteur Zeta liraient toujours des timestamps ambigus.

**Temps 2 — côté backend (cet ADR-013, le 2026-05-04 après-midi)** : Tik émet désormais **tous ses timestamps en UTC explicite**, marqué d'un `Z` final. Le format ressemble maintenant à `"2026-05-04T11:32:14Z"`. Quel que soit le consommateur (dashboard, SDK, futur bot), le timestamp est sans ambiguïté.

### Concrètement, qu'est-ce qui change

Pour l'utilisatrice : **rien à ses yeux** — le dashboard affichait déjà la bonne heure depuis le matin grâce au filet `parseUtcIso`. Mais en interne, Tik est désormais cohérent partout : un signal créé à 11:32 UTC dans le scheduler arrive à 11:32 UTC dans la base de données, ressort à 11:32 UTC du WebSocket, et apparaît à 13:32 dans le dashboard parisien (heure d'été). **Pas un seul intermédiaire ne peut plus se tromper de fuseau.**

Pour les futures connexions :

- Le **SDK Python** lira automatiquement des datetimes en UTC explicite (Pydantic reconnaît le `Z` natif)
- Le **futur connecteur Zeta** héritera du même format
- Si on ajoute demain un nouveau type de consommateur (notification push, Slack bot, MQTT), il bénéficiera lui aussi de la convention « tout est en `Z` »

### Pourquoi pas de migration de la base de données

La base de données Tik (PostgreSQL avec hypertable TimescaleDB) stocke les datetimes dans un format qui n'enregistre pas le fuseau (TIMESTAMP WITHOUT TIME ZONE). On aurait pu la migrer vers TIMESTAMPTZ pour stocker explicitement le fuseau, mais ça aurait nécessité une migration sur les partitions Timescale existantes — risqué et coûteux. À la place, on a choisi de **traiter le fuseau au moment de la sortie** : la couche Pydantic (qui sérialise en JSON) ajoute systématiquement le `Z`, même quand la valeur lue depuis la base est sans étiquette. C'est une convention claire (« la base est sémantiquement UTC ») sans toucher au schéma.

Si demain on a besoin d'analyser la base en SQL brut depuis un autre outil (BI, Grafana SQL direct), il faudra savoir que le fuseau est UTC implicite. À ce moment-là, on documentera ou on migrera. Pas avant.

### Ce que cela apprend sur Tik

C'est un de ces bugs « invisibles tant qu'on ne regarde pas, et qui mordent à un moment imprévisible ». Il aurait pu rester caché pendant des mois — l'utilisatrice n'avait jamais comparé l'heure du dashboard avec un `date -u` au terminal jusqu'à ce qu'une carte Stats LLM ait l'air de mentir sur l'âge du dernier signal.

La leçon technique : **toute chaîne de date qui voyage entre systèmes doit porter son fuseau**. Un datetime sans tzinfo est une bombe à retardement.

---

## 15. La couche contextuelle : carte Top headlines (2026-05-05)

Jusqu'ici, Tik produisait deux choses pour son utilisateur final :

1. **Des signaux décisionnels** (« BTC long, confiance 65 %, fiabilité 90 % ») → ce qui dit *quoi faire*
2. **Des hypothèses expliquées en clair** dans chaque signal → ce qui dit *pourquoi*

Mais il manquait une troisième brique : **le contexte narratif brut**. Si tu lis un signal Tik et que tu te demandes « OK, et qu'est-ce qui se dit dans le marché en ce moment, exactement ? », tu devais ouvrir Twitter, CoinDesk, Reuters, Yahoo Finance en parallèle pour comprendre la narrative en cours. C'est exactement le boulot d'un analyste pro qui consulte son terminal Bloomberg le matin avant de trader.

### Ce que fait la carte « Top headlines »

Sur l'écran Home du dashboard, juste sous la carte « Stats LLM », il y a maintenant un panneau **Top headlines** avec :

- **Un sélecteur BTC / GOLD** (c'est toi qui choisis l'actif)
- **5 titres bruts** issus des dernières 24 h, classifiés bull / bear / neutral
- **La source de chaque titre** affichée en clair (Google News · Yahoo Finance, CryptoCompare · CoinDesk, Reddit · r/Bitcoin, etc.)
- **L'âge du titre** (« il y a 12 min », « il y a 3 h »)
- Un **tap sur un titre** → ouvre l'article original dans Safari natif
- Un **bouton « Voir tous »** qui navigue vers une vue plein écran avec jusqu'à 25 titres

Tout ça est gratuit (les sources existaient déjà — on ne fait que les exposer brut au lieu de les agréger uniquement en score). Aucune nouvelle API payante, aucun nouveau process serveur.

### D'où viennent ces titres ?

Tik a déjà 3 ingesters news qui tournent toutes les 30 minutes en arrière-plan pour alimenter le scoring de sentiment des signaux :

- **Google News RSS** (sources mainstream pro : Reuters, Bloomberg, FT, Yahoo Finance, FXStreet, CoinDesk pour BTC ; KITCO, Mining.com, Fortune, Morningstar pour GOLD)
- **CryptoCompare** (CoinDesk Data, ~50 articles éditoriaux crypto par cycle)
- **Reddit** (r/Bitcoin et r/CryptoMarkets, posts filtrés ≥ 5 upvotes, pas de stickied modos, pas de NSFW)

La carte va simplement lire **les mêmes données** que Tik utilise déjà pour calculer les signaux, et te les montre brutes au lieu de seulement te montrer leur agrégat numérique.

### Comment Tik trie les titres affichés

Par défaut, Tik trie par **crédibilité × récence**. Concrètement :

- Chaque source a un **score de crédibilité** (Google News 0.70, CryptoCompare 0.70, Reddit 0.65 — cf. section 11)
- Plus le titre est récent, plus il pèse (« décroissance exponentielle » avec une demi-vie de 12 heures : un titre de la journée pèse encore beaucoup, un titre vieux de 24 h pèse environ 10 % de sa valeur initiale)
- Les deux se multiplient → un titre Reuters d'il y a 1 h passe devant un titre Reddit d'il y a 6 h, mais un titre Reddit d'il y a 30 min peut passer devant un titre Reuters d'il y a 18 h.

C'est le même principe qu'un fil d'actualité de pro : *qualité de la source × fraîcheur*.

### Et la dédup multi-source ?

Si le même article est relayé sur Google News *et* sur CryptoCompare (ce qui arrive souvent : un article CoinDesk apparaît dans les deux flux), Tik n'affichera **pas le même titre deux fois**. Le titre normalisé (mis en minuscules, espaces nettoyés) sert de clé de dédup — la première version dans le tri gagne.

Cela a nécessité un **petit nettoyage côté Google News** : Google News a la mauvaise habitude de coller ` - Reuters` à la fin de chaque titre (genre *« Bitcoin reclaims 80K - Reuters »*), même quand la balise XML `<source>` contient déjà *« Reuters »*. Sans nettoyage, le même article relayé via Google News (avec suffix) vs CryptoCompare (sans suffix) aurait deux titres strictement différents et la dédup serait défaite. Un helper `_strip_publisher_suffix` retire ce suffix proprement avant classification.

### Ce que la carte filtre déjà (et ce qu'elle ne filtre pas)

**La carte hérite déjà** des filtres en amont :

| Filtre | Origine |
|---|---|
| ✅ Sources curées (mainstream pro, pas de bruit Twitter brut, pas de WSB) | ADR-008 / ADR-009 / ADR-006 |
| ✅ Classification de sentiment (bull / bear / neutral) | Même classifier Ollama llama3.2:3b qui alimente les signaux |
| ✅ Crédibilité par source affichée | `SOURCE_SCORES` dynamique, ADR-011 |
| ✅ Filtres anti-brigading Reddit (score ≥ 5, no-stickied, no-NSFW) | ADR-009 |

**Ce que la carte ne fait pas** (par choix structurel) :

| Filtre absent | Pourquoi |
|---|---|
| ❌ Cross-validation Modified Z-score (anti fake-news ADR-011) | Conçu pour comparer des **biais agrégés multi-source** (« Google News dit +0.3, Reddit dit −0.9 → outlier »). Inapplicable à un titre isolé qui n'a pas de « biais agrégé ». |
| ❌ Filtrage des titres dissonants | Pattern OSINT pro classique : tu veux voir **toutes** les sources curées, y compris dissonantes. Filtrer une dissonance peut masquer une info précieuse (cas Roubini en 2007 sur les subprimes). C'est à toi, l'humain, d'arbitrer entre concordance et dissonance. |

### Comment l'utiliser intelligemment

**Workflow recommandé avant chaque trade manuel** (~3 minutes) :

1. **État du core** (10 sec) → Connecté ?
2. **Veracity globale** (10 sec) → > 0.70 ?
3. **Top headlines BTC ou GOLD** (30 sec) :
   - **4-5 titres concordants** (tous bull ou tous bear) sur sources mainstream → narrative claire, contexte favorable
   - **3 bull / 2 bear sur sources crédibles** → marché incertain, attente recommandée
   - **Discordance forte mainstream vs Reddit** → arbitrage à toi (mainstream = institutionnel, Reddit = retail)
4. **Lecture du signal Tik** (1 min) → direction + confidence + veracity + hypothèse contextuelle
5. **Confrontation** signal ↔ narrative (30 sec) :
   - Concordance → confiance accrue, tu peux trade au sizing prévu
   - Discordance modérée → réduire sizing
   - Discordance forte → skip ce trade
6. **Vérification finale** : tap sur 1-2 titres pour lire les articles complets

Total : 3 minutes de prep avant entrée. C'est le standard d'un analyste pro avant une décision.

### Ce que la carte n'est PAS

- **Pas un signal Tik** : la carte montre des inputs bruts, pas une décision algorithmique. Elle n'a pas de `confidence`, pas de `veracity`, pas de `counter_scenarios`. Ces concepts s'appliquent aux signaux décisionnels.
- **Pas une synthèse LLM** : aucun risque d'hallucination — chaque ligne est un titre réel publié par une vraie source, avec son URL cliquable. Choix conscient pour le trading manuel J+10 (cf. ADR-012 décision 3 : « hypothèse hallucinée serait pire que template »).
- **Pas pour Zeta** : Zeta est un bot trading déterministe qui consomme des **décisions** (signaux Tik) via le SDK. Pas des titres bruts. Les titres sont déjà incorporés en amont via le calcul du score net Google News / CryptoCompare / Reddit qui finit dans `evidence` du signal.
- **Potentiellement pour Totem** (bot ML, à venir) : Totem pourrait consommer les titres bruts comme features supplémentaires (encoder via embeddings BERT, agréger en vecteur, alimenter un modèle XGBoost). C'est l'archi des hedge funds quantitatifs. Hors scope J+10 mais l'endpoint le permet.

### Pourquoi c'est conforme aux standards OSINT pro

Les outils pro qui inspirent Tik (Recorded Future, Bloomberg Terminal, Refinitiv Eikon, Palantir Foundry) appliquent **tous** ce pattern :

- **Multi-source** : on agrège plusieurs flux indépendants
- **Sentiment classifié** : on étiquette chaque titre par un NLP (custom chez Recorded Future, Tik utilise Ollama 3B local)
- **Crédibilité affichée** : chaque source a un score visible
- **Citation explicite des sources** : tu peux toujours cliquer pour lire l'article original
- **Pas de synthèse LLM par défaut** (ou alors avec très haute exigence sur la traçabilité, comme Anduril Lattice)

Différence vs eux : Tik est **gratuit, hostable localement, et combine cette couche contextuelle avec un pipeline de signaux décisionnels et une cross-validation anti fake-news (ADR-011) qu'aucun de ces outils n'a dans un même produit**. Volume plus modeste (~75 titres/24h vs des milliers chez Bloomberg), mais le mécanisme est aligné.

### Limite documentée à connaître

Le LLM 3B utilisé pour classifier le sentiment **n'était pas 100 % déterministe** sur les titres ambigus. À deux cycles d'écart (30 min), un même titre légèrement borderline (genre *« Bitcoin holds support »*) pouvait basculer entre bull et neutral. Le score net agrégé restait stable à ±5 % mais les classifications individuelles changeaient.

**Cette limite a été résolue le 2026-05-05** par un cache Redis (cf. section 16 ci-dessous, Lacune C).

---

## 16. Améliorations OSINT pro Phase 1.1 (2026-05-05)

Après la livraison de la carte « Top headlines » (section 15), trois lacunes vs le standard OSINT pro (Bloomberg, Recorded Future, Refinitiv) ont été identifiées et livrées en bloc avant de continuer le plan trading manuel J+10. Tik passe d'un MVP OSINT à une plateforme OSINT pro robuste sur les axes **audit historique + sentiment stable + transparence anti fake-news**.

### Lacune G — Anti fake-news visible dashboard

**Avant** : quand Tik flagait un signal en `circuit_breaker_status: degraded` ou `tripped` (cross-validation ADR-011 a détecté que les sources se contredisaient fortement), le badge affiché côté dashboard était cryptique :

- Sur le détail signal : un bandeau rouge avec le texte « Circuit breaker : degraded » en franglais
- Sur la liste Signals : une pastille rouge « CB » indifférenciée

Tu voyais qu'il y avait quelque chose d'anormal mais sans comprendre quoi ni quoi en faire.

**Après** : un composant unifié `AntiFakeNewsBadge` qui distingue clairement :

- 🟧 **`degraded`** (orange) : drapeau de prudence. Le signal est émis avec direction inchangée, mais à interpréter avec prudence. Texte affiché : *« Anti fake-news : sources en désaccord — au moins 2 sources de sentiment divergent fortement sur ce signal. »*
- 🟥 **`tripped`** (rouge) : bloquant. La direction a été forcée à `neutral` par sécurité, et le signal original est conservé dans l'hypothèse pour audit. Texte affiché : *« Anti fake-news : bloqué — outliers détectés ou désaccord critique. »*

Le badge est visible aux **deux endroits** (mode compact dans la liste Signals, mode complet dans le détail signal), ce qui permet de repérer un signal flagué d'un coup d'œil sans devoir l'ouvrir.

### Lacune C — Sentiment stable via cache Redis

**Avant** : à chaque cycle ingester (toutes les 30 min), Tik re-classifiait tous les titres via Ollama. Comme le LLM 3B n'est pas 100 % déterministe sur les cas ambigus, **un même titre pouvait basculer entre bull/neutral/bear entre deux cycles**. UX confusante (« comment ça se fait alors que c'est les mêmes articles ? »).

**Après** : un cache Redis indexé par hash du titre (SHA-256 normalisé tronqué à 16 caractères, clé `tik.sentiment.cache.{model}.{asset}.{hash}`, TTL 7 jours). Comportement :

1. Avant chaque appel Ollama, Tik vérifie si ce titre a déjà été classifié dans les 7 derniers jours
2. Si oui → retourne directement le verdict cached **sans appeler le LLM**
3. Si non → appelle Ollama, parse le verdict, et stocke le label canonique (BULLISH/BEARISH/NEUTRAL) dans Redis

**Bénéfices** :
- **Stabilité totale** : un titre vu hier garde son sentiment original aujourd'hui
- **Économie Ollama** : ~80 % des titres réapparaissent à chaque cycle de polling, donc ~80 % d'appels LLM économisés
- **Best-effort sur les erreurs Redis** : si Redis plante, on retombe sur l'ancien comportement (re-classification systématique) au lieu de bloquer le pipeline

**Subtilité** : la clé inclut le **modèle Ollama** et l'**asset** (Bitcoin vs Gold). Si on change de modèle (passage 3B → 7B) ou si le même titre est classifié pour un autre asset, le cache est invalidé naturellement — pas de mélange.

### Lacune A — Persistance DB des titres pour audit historique

**Avant** : les titres OSINT étaient stockés uniquement dans Redis avec un TTL de 2 heures. Une fois expirés, ils étaient perdus définitivement. Pas d'audit possible (« le 4 mai à 22 h, qu'est-ce qui se disait sur BTC ? »), pas de retro-analyse, pas de feature data pour Totem ML.

**C'est précisément ce qui sépare un MVP OSINT d'une plateforme OSINT pro** : Bloomberg garde 10+ ans de news, Recorded Future maintient des archives interrogeables. Tik ne pouvait pas converger vers ce standard sans persistance long terme.

**Après** : nouvelle table SQL `headlines` qui stocke chaque titre brut en parallèle de Redis. À chaque cycle ingester, après avoir publié l'agrégat dans Redis, l'ingester insère les 25 titres bruts en base avec leur métadonnées complètes (source, sentiment, crédibilité, URL, dates, hash unique).

**Nouveau endpoint** `GET /api/v1/headlines/history/{entity_id}` qui permet la **retro-analyse jusqu'à 30 jours** (vs 24 h max côté Redis live) :

- Filtres : `since_hours` (1-720), `limit` (1-500), `source` (optionnel)
- Tri DESC par date d'ingestion
- Format identique à l'endpoint live + un `id` UUID stable pour référence future

**Cas d'usage débloqués** :
- Audit forensic : comprendre rétrospectivement quel narratif circulait à un instant T
- Mesure de qualité du classifier sur le temps long (corrélation sentiment/marché)
- Recalibration `SOURCE_SCORES` (ADR-011) sur la base du contenu réel et pas juste des signaux dérivés
- Feature data pour Totem ML (à venir post-J+30)
- Convergence vers le standard OSINT pro

**Best-effort sur les erreurs DB** : si Postgres est down ou en contention, l'écriture des titres est skippée silencieusement. L'ingester continue son cycle. Le seul effet est qu'on perd les titres du cycle (récupérables au cycle suivant si Redis n'a pas expiré).

### Convergence mesurable vers le standard OSINT pro

| Axe | Avant Phase 1.1 | Après Phase 1.1 | Bloomberg/Recorded Future |
|---|---|---|---|
| Audit historique des titres | ❌ TTL 2h Redis seul | ✅ DB SQL, retro-analyse 30j | ✅ 10+ ans |
| Stabilité du sentiment | ❌ LLM 3B non-déterministe | ✅ Cache Redis 7j par hash titre | ✅ NLP propriétaire |
| Transparence anti fake-news | ⚠️ Badge cryptique « CB » | ✅ Badge clair degraded/tripped + explication | ✅ Tags catégoriels |
| Volume de sources | ⚠️ ~75 titres/24h | ⚠️ Inchangé | ✅ Milliers/jour |

Tik converge sur 3 axes sur 4. Le volume reste un écart structurel (APIs payantes Bloomberg/Reuters), mais les 3 axes critiques pour un trading manuel sérieux sont au standard pro.

### Pourquoi avoir fait Phase 1.1 AVANT Phase A.2 (hit rate live)

Pour faire passer Tik d'un MVP à une plateforme OSINT pro robuste **avant** que l'utilisatrice trade manuellement avec son capital. Les 3 lacunes scorées (A 9/10 + G 8/10 + C 7/10) sont les fondations qu'on aurait regrettées de ne pas avoir au moment de prendre une vraie décision basée sur Tik.

Décalage planning : les ~6-7h de Phase 1.1 décalent Phase A.2 (hit rate) d'environ 1 jour. Tradeoff jugé positif : meilleur de trader avec un Tik solide qu'avec un Tik à la dernière mode mais bancal.

---

## 17. Pour résumer

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
- **Architecture extensible** : ajouter une nouvelle source = 1 helper + quelques lignes, pas un refactor

---

## 18. État actuel et pistes futures

### Ce qui marche aujourd'hui

- ✅ Analyse swing pour **BTC** (toutes les 15 min) avec **3 sources** : **Binance** (cours) + **Fear & Greed Index** (sentiment crypto contrarian) + **CryptoCompare news** (sentiment textuel trend-following)
- ✅ Analyse swing pour **GOLD** (toutes les 30 min) avec **3 sources** : **Yahoo Finance** (cours) + **FRED DXY** (macro contrarian) + **CFTC COT Managed Money** (positioning institutionnel contrarian)
- ✅ **Veracity dynamique** pour les deux actifs (entre 0.70 et 0.95) selon la concordance entre sources, calculée via la **moyenne des biais** disponibles (architecture multi-overlay extensible et désormais validée sur les deux entities)
- ✅ **NLP via Ollama** pour le sentiment news CryptoCompare : depuis le 2026-04-30, les titres de news ne sont plus classés par une simple liste de mots-clés mais par un **vrai modèle d'IA local** (`llama3.2:3b`, ~2 GB, qui tourne sur le Mac de l'utilisateur en dehors de Docker). Le modèle gère la **négation** ("Fear has eased" → bull), la **polarité contextuelle** ("Capitulation may be near, smart money accumulating" → bull), et les **expressions multi-mots** ("Bitcoin losing support" → bear). Si l'app Ollama plante, Tik bascule automatiquement sur l'ancienne analyse keywords (mode dégradé) sans rien casser.
- ✅ Framework « paranoïa contrôlée » respecté : chaque signal contient hypothèse, contre-scénarios, evidence et triggers
- ✅ Authentification API (clé Bearer), Swagger interactif, healthchecks Docker propres
- ✅ **Script de backtest** (`docker compose exec core python -m tik_core.scripts.backtest`) qui mesure si Tik bat des stratégies naïves (Random, Always LONG, Always SHORT, Always NEUTRAL). Premier verdict 2026-04-29 : Tik bat Random largement, mais sur cette période bullish BTC, un naïf "toujours long" performait mieux. Conclusion : besoin de plus de données et de périodes variées.

**Les deux actifs sont cross-validés multi-sources** avec veracity dynamique. Le pattern d'overlay est un composant réutilisable : ajouter une 4e source pour BTC (ou une 4e pour GOLD) = 1 nouveau helper + 5 lignes dans la fonction d'analyse, tests inclus.

### Premières leçons du backtest (à raffiner avec plus de données)

- **Sweet spot horizon swing : 5 jours** (vs 3 jours initialement supposés)
- **GOLD est slow-burn** : ses mouvements macro se matérialisent sur 5-7 jours, pas 1-3
- **Le seuil NEUTRAL était trop large** (0.15) : il rangeait des situations directionnelles en "neutral" et ratait des opportunités. Recalibré à **0.08** le 2026-04-29
- **L'edge réel de Tik se mesurera en cas de retournement de tendance** — pas en période trending forte où des trend-followers naïfs suffisent
- **Le vrai test du pattern multi-overlay sur GOLD aura lieu le 2026-05-21** : analyse automatique programmée pour vérifier si les seuils COT contrarian se déclenchent correctement après 3 semaines de collecte (ou s'il faut les recalibrer en z-score 52 semaines, vu que les Managed Money sont structurellement net long sur l'or)

### Pistes futures (par ordre de priorité)

- **Continuer à laisser tourner Tik 4-8 semaines** pour avoir au moins une période de retournement de tendance dans le backtest, et plus de signaux directionnels à veracity dynamique
- **Recalibrer ou non les seuils COT** après l'analyse automatique du 2026-05-21
- **Mesurer le gain réel du NLP Ollama vs keywords** : créer un dataset golden d'une cinquantaine de titres réels annotés à la main (BULLISH / BEARISH / NEUTRAL) et comparer quantitativement les deux méthodes (cf. `docs/backlog.md` § 1.B). Le ingester loggue déjà la méthode utilisée par batch (`method:ollama:llama3.2:3b` ou `method:keywords`), donc le backtest pourra aussi comparer le hit rate par méthode sur les vrais signaux.
- **Enrichir le backtest** : stockage des résultats en DB pour suivi temporel, comparaison veracity-by-bucket plus fine, lancement multi-horizons en une commande
- **SDK Python** (`tik-sdk`) : package pip-installable pour brancher les bots clients (Zeta, Totem) sur Tik
- **Dashboard Expo mobile** : visualisation temps réel des signaux sur smartphone
- **Engines flash et macro** : étendre les horizons d'analyse (minutes pour flash, semaines pour macro)
- **Sources additionnelles** : Reddit (r/CryptoCurrency), Polymarket (marchés prédictifs), on-chain metrics (Glassnode), ETF flows GOLD
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
- **Source** : un fournisseur de données externe (Binance, Yahoo, FRED, CFTC, etc.)
- **Cross-validation** : la confrontation de plusieurs sources pour évaluer la fiabilité
- **Bias contrarian** : la logique « faire l'inverse de la foule » (acheter quand tout le monde panique, vendre quand tout le monde est euphorique)
- **RSI / EMA / MACD** : trois indicateurs techniques classiques utilisés en analyse boursière
- **DXY / DTWEXBGS** : un indice mesurant la force du dollar US
- **CFTC COT** : Commitments of Traders, rapport hebdomadaire publié par le régulateur américain CFTC qui révèle les positions des grands acteurs sur les marchés de futures
- **Managed Money** : catégorie d'acteurs dans le rapport COT — hedge funds, fonds spéculatifs, CTAs (= la « smart money » directionnelle)

---

*Document rédigé le 2026-04-28, mis à jour le 2026-04-29 (ajout 3e source CryptoCompare, premier backtest avec baselines, recalibrage seuil NEUTRAL), puis le 2026-04-30 (ajout 2e source GOLD : CFTC COT Managed Money, validation grandeur réelle du pattern multi-overlay sur GOLD ; remplacement de l'analyse par mots-clés CryptoCompare par un LLM local via Ollama avec fallback keywords automatique). Pour expliquer Tik à toute personne curieuse, sans prérequis technique.*
