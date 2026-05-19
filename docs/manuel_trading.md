# Manuel du trader manuel Tik — J+14

> **Pour qui** : toi, débutante. Tu n'as jamais tradé en vrai. Tu démarres
> avec Tik comme aide à la décision le **2026-05-24** (lundi).
>
> **Par qui** : Claude, dans le double rôle de (1) développeur Tik qui
> connaît le pipeline OSINT par cœur et (2) coach trader qui doit te
> protéger contre les pièges classiques des premiers mois.
>
> **Comment le lire** : sections 0 à 7 dans l'ordre, **avant** le 24 mai.
> Imprime la section 2 (décision tree) et l'annexe B (règles strictes)
> pour les avoir sous les yeux pendant tes premières sessions.
>
> **Mise à jour** : 2026-05-19, J-5 du trading manuel. Tout chiffre cité
> vient de mesures documentées dans CLAUDE.md (pas d'invention).

---

## ⚠ Avant-propos — la lucidité d'abord

**Tik n'a pas d'edge démontré au global.**

Les chiffres mesurés sur les 30 jours précédents (cf. CLAUDE.md
Garde-fou 2-bis, section 5) :

- **22 % hit rate BTC swing 5j vs Random 33 %** sur 156 signaux
- **31.1 % hit rate global vs Random 33.2 %** sur 1316 signaux (audit
  Paquet 27 d'hier)

Concrètement : **Tik bat le hasard sur certains sous-segments seulement**.
Pas sur l'ensemble. Le trading manuel sert à **valider empiriquement**
les sous-segments où Tik a peut-être un edge, pas à "suivre les signaux
parce que Tik est intelligent".

Les sous-segments où on a un signal positif mesuré :

- **SHORT BTC** : 63.1 % hit rate, +0.72 % gain moyen sur 263 signaux 1j
- **Veracity ≥ 0.95 swing** : 67 % hit rate vs 24 % global

Les sous-segments où Tik est **pire que le hasard** :

- **GOLD** : 4.8 % hit rate vs Random 34 % vs Always SHORT 81 %
- **Flash BTC à veracity 0.90+** : 13-16 % hit rate (insight inversé
  contre-intuitif Paquet 10)

**Implication trader débutant** : tu vas faire des trades qui perdent.
Pas parce que tu fais mal, pas parce que Tik est cassé — c'est statistique.
Ton job pendant les 2 premières semaines est de **survivre** (sizing 1 %)
et de **mesurer empiriquement** si TU arrives à reproduire le hit rate
mesuré sur SHORT BTC veracity ≥ 0.85.

Si ça marche → on ajuste à la hausse. Si ça marche pas → on retourne
au plan dessin (refonte pipeline OSINT, etc.). C'est de la science
appliquée, pas de la magie.

---

## 0. Pré-requis — à faire AVANT le 24 mai

### 0.1 Capital et broker

- [ ] **Définis ton capital total de trading** : un montant que tu acceptes
  de perdre intégralement sans que ça change ta vie. Ne **jamais** mettre
  dans Tik plus que ce que tu peux perdre.
- [ ] **Ouvre un compte broker** qui propose BTC en CFD ou futures
  (recommandation Tik : MT5 + ActivTrades, cohérent avec Zeta — ou tout
  broker régulé qui propose BTC long ET short, levier max 1:10 pour
  débutant, **pas 1:100**)
- [ ] **Fais 2-3 trades en mode démo** sur la plateforme broker dans la
  semaine qui reste : place un buy, place un sell, place un stop loss,
  place un take profit. Sans Tik, juste pour apprendre les **clics**.
- [ ] **Note tes paramètres broker** : taille minimum d'un lot, frais
  par trade, spread BTC moyen, swap overnight (= ce que tu paies pour
  garder une position ouverte la nuit)

### 0.2 Outils de suivi

- [ ] **Journal de trading** : crée un fichier (Google Sheets ou Excel)
  avec ces colonnes :
  - Date émission signal Tik
  - Signal ID (`TIK-SWING-BTC-...`)
  - Entity / Horizon / Direction
  - Veracity / Confidence (Conviction OSINT)
  - Hypothèse (résumé en 1 phrase)
  - Anti fake-news (ok/degraded)
  - Décidé d'entrer ? (oui/non/pourquoi)
  - **Si entré** : prix entrée, stop loss, take profit, position size €
  - **Si fermé** : prix sortie, P&L €, raison sortie
  - **Outcome Tik** (selon Watchlist auto-resolution)
  - **Leçon** (1 phrase)
- [ ] **Watchlist Tik côté Expo Go** : à chaque signal que tu décides
  de trader, tape ★ Suivre dans le détail signal. L'auto-resolution
  Paquet 28 te dira correct/raté après 5j sans que tu aies à recalculer.

### 0.3 Setup technique

- [ ] **Tik core opérationnel côté HP** (vérifié hier soir par toi,
  111 events macro à venir, fix track record flash déployé)
- [ ] **Expo Go iPhone** charge le dashboard sans erreur (login OK, signaux
  apparaissent dans l'onglet Signals)
- [ ] **Notifications push activées** sur iPhone pour Expo Go (sinon
  tu rateras les signaux temps réel)
- [ ] **Macro events visibles** sur Home : tu dois voir au moins NFP
  2026-06-05 et CPI dans la liste

### 0.4 État mental

- [ ] **Tu acceptes que tu vas perdre de l'argent** sur tes premiers
  trades. Le but à 1 mois n'est PAS d'être profitable, c'est de **valider
  le process** : as-tu suivi les règles ? as-tu mesuré ? as-tu appris ?
- [ ] **Tu acceptes de ne PAS trader** des jours où aucun signal ne
  passe le filtre (veracity ≥ 0.85, SHORT BTC, pas dans ±4h d'event
  HIGH). Le **meilleur trade est souvent celui qu'on ne prend pas**.
- [ ] **Tu acceptes de t'arrêter** après 3 pertes consécutives dans
  la journée (cf. règles annexe B). Pas de revenge trading.

---

## 1. Rituel quotidien — chaque matin avant la session

À faire à l'heure où tu peux te concentrer 30-60 min (matin, midi, ou
soir — pas multitâche). **Ne pas trader dans le métro / en marchant /
en faisant autre chose.**

### Étape 1 — Vérifier l'état système Tik (2 min)

Ouvre Expo Go iPhone → Onglet **Système** :

- [ ] État du core = `healthy` (sinon, message côté HP pour rebooter)
- [ ] Version dashboard = `0.5.13` ou supérieure (Paquet 28+ actif)

### Étape 2 — Vérifier le calendrier macro (3 min)

Onglet **Marché** → carte **Calendrier macro** :

- [ ] Y a-t-il un event **HIGH** dans les **±4 heures** ? FOMC, NFP, CPI,
  ECB, BoJ, BoE
  - **Si OUI** → **STOP trading aujourd'hui**, ou divise ton sizing
    par 2 (= 0.5 % au lieu de 1 %) si vraiment tu veux jouer
  - Si NON → continue
- [ ] Note l'event HIGH le plus proche dans ton journal (pour anticiper
  les jours suivants)

**Pourquoi ±4h ?** Cf. CLAUDE.md ADR-017 + Garde-fou 2-bis : les
publications FOMC/NFP/CPI provoquent des spikes de 1-3 % qui invalident
les signaux techniques pré-publication. Beaucoup de débutants se sont
fait stop-out sur un FOMC qu'ils n'avaient pas vu venir.

### Étape 3 — Lire les Top headlines BTC (5 min)

Onglet **Marché** → carte **Top headlines aujourd'hui** → sélecteur BTC :

- [ ] Lis les 5-10 titres affichés
- [ ] Identifie la **narrative dominante** : "BTC monte parce que…",
  "BTC baisse parce que…", ou "marché incertain en attente de…"
- [ ] Note si tu vois des sources **rouges** (bear) qui dominent → cohérent
  avec un signal SHORT à venir

**Le but** : avoir le contexte narratif AVANT de regarder les signaux.
Tu jugeras mieux si un signal SHORT BTC tombe sur un narrative bull
(= méfiance, peut-être un piège) ou sur un narrative bear (= cohérent).

### Étape 4 — Regarder les Signals récents (10 min)

Onglet **Signals** :

- [ ] Filtre **horizon = swing** (priorité, pas flash en première semaine)
- [ ] Filtre **entity = BTC** (PAS GOLD, cf. Garde-fou 2-bis)
- [ ] Liste les signaux récents (24h max) dans ton journal

Pour chaque signal apparemment intéressant, ouvre-le et passe à la
section 2 (décision tree).

### Étape 5 — Calibration mentale (2 min)

Avant de cliquer "trader" sur un signal :

- [ ] Tu as combien de trades ouverts actuellement ? Max 3 simultanés
  les 2 premières semaines.
- [ ] Tu es dans quel état émotionnel ? Si tu viens de perdre 3 trades
  d'affilée, **STOP la session, reprends demain**.
- [ ] Tu peux suivre ce trade pendant 5 jours sans paniquer ? Sinon
  prends un horizon plus court ou réduis le sizing.

---

## 2. Décision tree — dois-je trader CE signal ?

> **Imprime cette page** et garde-la à côté de ton ordi.

Pour chaque signal que tu envisages, **passe par toutes les questions
dans l'ordre**. Une seule réponse "NON" = tu ne trades pas.

```
┌─────────────────────────────────────────────────────────────────┐
│ SIGNAL TIK — DOIS-JE LE TRADER ?                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ Q1. Entity = BTC ?                                              │
│     OUI → continue                                              │
│     NON (= GOLD) → STOP, ne PAS trader (Garde-fou 2-bis)        │
│                                                                 │
│ Q2. Horizon = swing ?                                           │
│     OUI → continue                                              │
│     NON (= flash) → STOP les 2 premières semaines, trop bruité  │
│     NON (= macro) → impossible, macro non implémenté            │
│                                                                 │
│ Q3. Veracity ≥ 0.85 ?                                           │
│     OUI → continue (seuil transitoire Reddit IP-banni)          │
│     NON → STOP, signal pas assez cross-validé                   │
│                                                                 │
│ Q4. Direction = SHORT ?                                         │
│     OUI → ★ priorité (63 % hit mesuré, +0.72 % gain moyen)     │
│     NON (= LONG) → autorisé MAIS veracity ≥ 0.90 obligatoire    │
│     NON (= NEUTRAL) → STOP, pas de pari directionnel possible   │
│                                                                 │
│ Q5. Anti fake-news status ?                                     │
│     ok → continue normalement                                   │
│     degraded → continue MAIS sizing divisé par 2 (= 0.5 %)      │
│     tripped → STOP, direction forcée neutral par Tik            │
│                                                                 │
│ Q6. Calendrier macro : event HIGH dans ±4h ?                    │
│     NON → continue                                              │
│     OUI → STOP, ou sizing /2 si vraiment nécessaire             │
│                                                                 │
│ Q7. Triggers cohérents avec direction ?                         │
│     Pour SHORT BTC : RSI > 70 (overbought) bearish + MACD       │
│     croisé baissier + EMA20 < EMA50                             │
│     OUI tous cohérents → continue, conviction renforcée         │
│     Partiels → continue mais sizing 0.5 % au lieu de 1 %        │
│     Aucun cohérent → STOP, signal contradictoire interne        │
│                                                                 │
│ Q8. Tu as moins de 3 trades ouverts ?                           │
│     OUI → continue                                              │
│     NON → STOP, attends qu'un trade se ferme                    │
│                                                                 │
│ Q9. Tu as fait moins de 3 trades perdants aujourd'hui ?         │
│     OUI → continue                                              │
│     NON → STOP, ferme le dashboard, reviens demain              │
│                                                                 │
│ → SI TOUTES RÉPONSES = OUI : passe à la section 3 (sizing)      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Cas particuliers à connaître

- **Signal flash BTC** : non listé dans la décision tree car déconseillé
  pour débutant les 2 premières semaines (insight Paquet 10 : pattern
  inversé à veracity 0.90+ = 13-16 % hit). À rouvrir post-J+15 si tu te
  sens prête.
- **Veracity entre 0.85 et 0.90 BTC swing** : c'est le seuil **transitoire**
  pendant l'IP-ban Reddit. Quand Reddit reviendra, le seuil reviendra à
  0.90. Tant que Reddit est banni, tu opères à 3 overlays au lieu de 4
  donc l'incertitude est structurellement plus haute.
- **Hypothèse contextuelle LLM** : le texte de 6 sections affiché dans
  le détail signal est généré par un LLM 3B (Ollama). C'est de **l'aide
  à la décision**, pas de la vérité absolue. Si ta lecture des evidence
  brutes contredit le texte LLM → fais confiance à ton jugement.

---

## 3. Sizing de position — 1 % du capital par trade

### Formule de base

```
Position size (€)    = (Capital × Risque par trade %)  / Distance stop loss %
                     = (Capital × 0.01)                / (|Stop - Entry| / Entry)
```

### Exemple concret

Capital = **1 000 €** (mets ton vrai chiffre)
Risque max par trade = 1 % = **10 €**
Tu shortes BTC à **100 000 $**, stop loss à **102 000 $** (= +2 % au-dessus)
Distance stop = 2 %

```
Position size = 10 € / 0.02 = 500 € de notionnel
```

→ Tu shortes pour 500 € de BTC. Si BTC monte à 102 000 (stop touché),
tu perds 500 × 2 % = 10 € = 1 % de ton capital. ✓

### Tableau de référence (cas typiques BTC)

| Capital | Risque 1 % | Stop loss à 1 % | Stop loss à 2 % | Stop loss à 3 % |
|---|---|---|---|---|
| **500 €** | 5 € | 500 € | 250 € | 167 € |
| **1 000 €** | 10 € | 1 000 € | 500 € | 333 € |
| **2 000 €** | 20 € | 2 000 € | 1 000 € | 667 € |
| **5 000 €** | 50 € | 5 000 € | 2 500 € | 1 667 € |
| **10 000 €** | 100 € | 10 000 € | 5 000 € | 3 333 € |

### Où placer ton stop loss ?

**Méthode mécanique pour débutant** (à respecter à la lettre) :

- **SHORT BTC swing** : stop loss à **+2 %** au-dessus du prix d'entrée
- **LONG BTC swing** : stop loss à **-2 %** en dessous du prix d'entrée

C'est arbitraire mais cohérent avec la volatilité moyenne BTC 1-5 j
(~3-5 % de range). Plus large = trade trop "tolérant" qui dure des jours
sans bouger. Plus serré = stop out sur le bruit normal.

**Méthode avancée** (semaine 3+, si tu veux affiner) : stop sous le
plus bas/haut récent visible sur le graphique 4h des 24 dernières heures.

### Où placer ton take profit ?

**Risk-Reward ratio minimum 1.5** :

```
Take profit  =  Entry  ±  (Stop loss distance × 1.5)
```

Pour notre SHORT BTC à 100 000 $ avec stop à 102 000 (2 %) :

```
Take profit = 100 000 - (2 000 × 1.5) = 97 000 $  (= -3 % du prix d'entrée)
```

→ Si TP atteint avant SL : tu gagnes **1.5 %** de ton capital (= 15 €
sur 1 000 €), 1.5× ton risque. Si SL atteint avant TP : tu perds 1 %.

**Au hit rate 33 %** (Random), tu serais perdante :
- 33 % × +1.5 % = +0.495 %
- 67 % × -1 % = -0.67 %
- Net = -0.175 % par trade en moyenne

**Au hit rate 50 %** (cible Tik SHORT BTC veracity ≥ 0.85) :
- 50 % × +1.5 % = +0.75 %
- 50 % × -1 % = -0.5 %
- Net = +0.25 % par trade en moyenne ✓ (rentable)

**À 63 % (mesuré sur 263 signaux SHORT BTC 1j horizon)** :
- 63 % × +1.5 % = +0.945 %
- 37 % × -1 % = -0.37 %
- Net = +0.575 % par trade ✓✓

**Donc** : il te faut **>40 % de hit rate** pour être rentable au
RR 1.5. C'est exactement pour ça qu'on filtre veracity ≥ 0.85 et qu'on
priorise SHORT BTC.

---

## 4. Placement de l'ordre côté broker

### Étape par étape (MT5 / ActivTrades ou broker similaire)

1. **Ouvre la plateforme broker**
2. **Cherche le symbole** : `BTCUSD` ou `BTC/USD` selon broker
3. **Décide entry type** :
   - **Market order** (instantané au prix actuel) : recommandé pour BTC
     swing (la latence saisie ordre ne change pas grand-chose sur 5j)
   - **Limit order** (attendre un prix précis) : utile si tu veux entrer
     à un niveau spécifique mentionné dans le signal Tik
4. **Calcule la taille** via la formule section 3
5. **Place le stop loss** dans le ticket d'ordre — case "Stop Loss"
6. **Place le take profit** dans le ticket d'ordre — case "Take Profit"
7. **Vérifie 2 fois** :
   - Direction (Buy = LONG, Sell = SHORT) cohérente avec Tik ?
   - Taille en euros = environ ce que la formule t'a donné ?
   - Stop et TP du bon côté du prix d'entrée ?
8. **Click "Place order"**
9. **Note immédiatement dans ton journal** : ID broker, prix entrée
   exact, heure, screenshot du ticket

### Pièges classiques débutant à éviter

- ❌ **Oublier le stop loss** : NEVER. Un trade sans stop = ta ruine
  potentielle si BTC fait -20 % en 1h (déjà arrivé en 2024 sur des news).
- ❌ **Sizing au pifomètre** : tu te dis "1 BTC ça coûte 100k$, je vais
  prendre 0.01 BTC = 1000$" sans calcul → tu prends un sizing
  potentiellement 10× supérieur à ton 1 %.
- ❌ **Trader le mauvais sens** : Tik dit SHORT et tu cliques Buy par
  réflexe → vérifie 2× la direction.
- ❌ **Lever 1:100 ou 1:500** : pour débutant, levier max 1:10. Tu peux
  toujours utiliser ton capital comme garantie, le levier multiplie
  juste ta perte potentielle si stop sauté par un spike.

---

## 5. Suivi du trade — après l'entrée

### Immédiatement après le clic

- [ ] **Marque le signal en Watchlist Tik** (★ Suivre dans détail signal)
- [ ] **Screenshot du ticket** broker (preuve)
- [ ] **Note dans journal** : prix entrée exact, heure, stop, TP

### Pendant la vie du trade (1h à 5 jours pour swing)

- [ ] **Ne touche PAS au trade** sauf si SL ou TP touché
- [ ] **Ne regarde PAS le P&L toutes les 5 min** — c'est de l'auto-torture
  émotionnelle pour zéro valeur ajoutée. Check 1× le matin et 1× le soir.
- [ ] **Ne bouge PAS le stop loss vers le bas** (sur SHORT) ou vers le
  haut (sur LONG) "pour donner de l'air" — c'est ce qui cause les ruines.
- [ ] **Tu peux bouger le stop dans le BON SENS** (= sécuriser des
  gains) si le trade va vite dans ton sens : c'est le **trailing stop**.
  À éviter en première semaine, on garde le SL fixe pour valider le RR.

### Conditions de sortie acceptables

| Condition | Action |
|---|---|
| **TP atteint automatiquement** | Le broker ferme, tu encaisses gain |
| **SL atteint automatiquement** | Le broker ferme, tu encaisses perte |
| **5 jours écoulés sans toucher SL/TP** | Tu fermes manuellement au prix actuel (= time stop, cohérent horizon swing 5j) |
| **Event macro HIGH imprévu à <4h** (ex. annonce surprise BCE) | Tu fermes manuellement avant l'event |
| **Tik émet un signal OPPOSÉ veracity ≥ 0.90** sur la même entity/horizon | Tu peux fermer manuellement (mais documente la décision) |

### Conditions de sortie NON acceptables

- ❌ "J'ai peur" → tu fermes pour rien
- ❌ "C'est en perte de 0.5 %" → c'est dans la marge normale du trade
- ❌ "Je veux le profit maintenant" → tu coupes ton gain (alors que TP
  pas encore atteint)
- ❌ "Twitter dit que BTC va à 200k" → tu ignores les sources non Tik

---

## 6. Post-trade — feedback et apprentissage

Dans les 24h qui suivent la fermeture d'un trade :

### Côté Tik

1. Ouvre l'onglet **Watchlist** dans Expo Go
2. Trouve ton signal résolu (badge `Confirmé` ou `Infirmé` ou `Sans verdict`)
3. **Si l'outcome Tik diverge de ton trade réel** (rare mais possible) :
   tape sur le badge → choisis manuellement le verdict qui correspond
   à TON résultat réel. Le POST /feedback alimentera la recalibration
   source credibility.
4. Note dans ton journal le ratio TP/SL Tik vs ton ratio réel (peut
   différer si tu as fermé manuellement avant)

### Côté journal de trading

Remplis ces 4 colonnes que tu avais préparées :

- **Prix de sortie réel**
- **P&L réel en €** (et en % de capital)
- **Raison sortie** (TP/SL/time-stop/event-macro/manuel-autre)
- **Leçon en 1 phrase** : qu'est-ce que tu changerais ?

### Revue hebdomadaire (chaque dimanche soir)

Compte sur tes trades de la semaine :

- Nombre de trades total
- Hit rate perso (trades gagnants / trades fermés avec verdict)
- Hit rate Tik officiel pour la même fenêtre (carte Watchlist
  PersonalHitRateCard)
- P&L total semaine
- Drawdown max intraday (pire moment de la semaine)

**Métriques à surveiller à 1 mois** :

- Si **hit rate perso > hit rate Tik** : tu as ajouté de la valeur
  par ton filtrage humain → continue.
- Si **hit rate perso < hit rate Tik** : tu fais peut-être de
  l'overtrading ou tu trades les mauvais sous-segments → revoir
  la décision tree section 2.
- Si **P&L négatif** au bout d'1 mois : retour planche à dessin.
  Pas de tilt, c'est le résultat d'une mesure honnête.

---

## 7. Plan de progression — semaine par semaine

### Semaine 1 (24-30 mai) — VALIDATION DU PROCESS

- Max **1 trade par jour** (même si 3 signaux passent les filtres)
- Sizing strict 1 % capital
- Seulement **SHORT BTC swing** veracity ≥ 0.85
- Objectif : prouver que tu peux suivre la décision tree à la lettre
- Indicateur de succès : **0 trade pris sans avoir passé toutes les
  questions Q1-Q9**. P&L est secondaire cette semaine.

### Semaine 2 (31 mai - 6 juin) — PREMIÈRES MESURES

- Max **2 trades par jour**
- Sizing toujours 1 %
- Ajout possible : **LONG BTC swing** veracity ≥ 0.90
- Objectif : avoir 10-15 trades fermés → premier hit rate perso mesurable
- Attention : **NFP le vendredi 5 juin** = STOP trading ±4h autour

### Semaine 3 (7-13 juin) — AJUSTEMENT

- Selon mesure semaine 2 :
  - Si hit rate perso ≥ 50 % : on continue le process, sizing peut
    monter à 1.5 % si tu veux (pas obligé)
  - Si hit rate perso 33-50 % : on continue à 1 %, on identifie ce qui
    coince
  - Si hit rate perso < 33 % : on revoit le process, peut-être retour
    sizing 0.5 % le temps de corriger
- Recalibration source credibility ADR-011 reprend autour du 18 juin
  → on aura des SOURCE_SCORES ajustés empiriquement

### Semaine 4+ (14 juin et après) — STABILISATION

- Évaluation cumulée 1 mois
- Décision : maintenir / augmenter sizing / arrêter / pivoter
- Si Reddit unban arrivé : retour seuil veracity ≥ 0.90 strict
- Si Reddit toujours banni : décision sur Option C (source alternative
  Hacker News, cf. backlog #10)

---

## Annexe A — Glossaire trader débutant

| Terme | Définition simple |
|---|---|
| **LONG** | Tu paries que le prix VA MONTER. Tu achètes maintenant pour revendre plus cher plus tard. |
| **SHORT** | Tu paries que le prix VA BAISSER. Tu vends maintenant pour racheter moins cher plus tard. |
| **Stop loss (SL)** | Ordre automatique qui ferme ton trade si le prix va trop contre toi. **Obligatoire**, jamais négociable. |
| **Take profit (TP)** | Ordre automatique qui ferme ton trade si tu atteins ton objectif de gain. |
| **Position size** | Combien d'argent tu engages dans CE trade. Calculé selon la formule section 3. |
| **Leverage** | Multiplicateur de ta position. 1:10 = tu trades 10× ta mise. **Risque démultiplié pareil**. Max 1:10 pour débutant. |
| **Spread** | Différence entre prix d'achat et prix de vente. Coût caché de chaque trade (~0.05-0.2 % sur BTC). |
| **Swap overnight** | Coût/gain de garder une position ouverte la nuit. Sur BTC short = souvent négatif (tu paies). |
| **Drawdown** | Pire perte temporaire de ton capital total. Si tu pars de 1000 € et tu descends à 800 € avant de remonter, ton drawdown est 20 %. |
| **Hit rate** | % de tes trades gagnants sur tes trades fermés. Tu vises >40 % pour être rentable au RR 1.5. |
| **Risk-Reward ratio (RR)** | Ratio gain potentiel / perte potentielle. RR 1.5 = tu gagnes 1.5× ce que tu risques sur chaque trade gagnant. |
| **Veracity (Tik)** | Score Tik 0-1 de cross-validation des sources OSINT. Plus c'est haut, plus les sources d'accord entre elles. |
| **Conviction OSINT (Tik)** | Magnitude du combined_bias OSINT. = ce qu'on appelait "confidence" avant ADR-018. |
| **Anti fake-news (Tik)** | Statut `ok` / `degraded` / `tripped` indiquant si les sources sont cohérentes (ok) ou divergent (degraded/tripped). |

---

## Annexe B — Règles strictes (à imprimer)

> Imprime cette page et colle-la **au-dessus de ton écran broker**.

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│         RÈGLES STRICTES — TRADER MANUEL TIK J+14                │
│                                                                 │
│   1. JAMAIS de trade sans stop loss                             │
│   2. JAMAIS plus de 1 % du capital par trade                    │
│   3. JAMAIS de GOLD avec Tik (hit rate 4.8 % mesuré)            │
│   4. JAMAIS de trade dans ±4h d'event macro HIGH                │
│   5. JAMAIS de trade si veracity < 0.85 sur swing BTC           │
│   6. JAMAIS de trade si déjà 3 pertes dans la journée           │
│   7. JAMAIS bouger le stop loss vers le mauvais sens            │
│   8. JAMAIS plus de 3 trades ouverts en simultané               │
│   9. JAMAIS de trade émotionnel "pour me refaire"               │
│  10. JAMAIS de signal flash en première semaine                 │
│                                                                 │
│  TOUJOURS suivre la décision tree (section 2)                   │
│  TOUJOURS journaliser le trade (entrée + sortie + leçon)        │
│  TOUJOURS marquer dans Watchlist Tik ★ Suivre                   │
│  TOUJOURS faire la revue hebdomadaire dimanche soir             │
│                                                                 │
│  PRIORITÉ : SHORT BTC swing veracity ≥ 0.85, RR 1.5             │
│  SIZING : 1 % capital max, 0.5 % si anti-fake-news degraded     │
│  HORIZON : 5 jours max (= time stop swing)                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Annexe C — Erreurs courantes débutant à éviter

1. **L'overtrading** : prendre 10 signaux par jour parce que Tik en
   émet 50. Filtre, filtre, filtre. La majorité des signaux Tik ne
   passent PAS tes critères, c'est normal.

2. **Le revenge trading** : tu viens de perdre, tu veux te refaire
   immédiatement, tu prends un signal médiocre. STOP, fermes le
   dashboard, reprends demain.

3. **L'illusion de contrôle** : "BTC va remonter, je sens", "Je vais
   désactiver le stop juste cette fois". Tu sens RIEN. Le marché ne
   sait pas que tu existes. Ton edge potentiel vient des règles, pas
   de ton intuition de débutante.

4. **L'ancrage au prix d'entrée** : "BTC est à -1 % de mon entrée, je
   vais attendre que ça remonte à break-even pour fermer". Le prix
   d'entrée ne signifie rien pour le marché. Seuls comptent SL et TP.

5. **Le sur-leverage** : "1:10 c'est lent, je vais passer à 1:100 pour
   ce trade clé". Cf. règle stricte #2. La distance stop ne dépend pas
   du levier, mais la perte en € si saute, oui.

6. **Le copy-paste sans comprendre** : "Tik dit SHORT, je shorte, je
   ne regarde pas pourquoi". Lis l'hypothèse contextuelle LLM. Lis les
   evidence. Lis les counter-scenarios. Si tu ne peux pas expliquer le
   signal en 2 phrases, ne le trades pas.

7. **L'isolation** : trader seul sans en parler à personne. Au moins 1
   personne dans ton entourage doit savoir ce que tu fais (montant
   risqué, broker utilisé, où voir tes positions en cas de problème).

8. **Le manque de pause** : trader 7 jours sur 7 = burn-out garanti.
   2-3 jours par semaine de "trading off" obligatoires.

---

## Annexe D — Cas particuliers

### Tik est down (core unhealthy)

- Tu n'as PLUS de signaux fiables → **STOP trading**, n'ouvre aucun
  nouveau trade tant que core pas réparé
- Tu gardes tes positions ouvertes (SL/TP côté broker restent actifs)
- Message à Claude pour diagnostic + remise en route

### Marché en flash crash (BTC -10 % en 1h)

- Si tu as un SHORT ouvert : laisse courir, TP probablement bientôt
- Si tu as un LONG ouvert : SL te sortira normalement. Si SL saute
  (slippage = SL exécuté à un prix pire que prévu), perte > 1 %. C'est
  rare mais possible sur événements extrêmes.
- N'ouvre PAS de nouveau trade pendant le flash, attends que la
  volatilité retombe (1-3h)

### Tu as fait une grosse erreur (mauvais sens, mauvais sizing)

- Constate la position que tu as réellement prise
- Ferme immédiatement au marché (perte de spread, c'est OK)
- Note dans ton journal : "erreur d'exécution, +/- X €, leçon : double
  vérification ticket avant click"
- Pas de revenge trade, journée terminée

### Reddit revient pendant ta semaine de trading

- Tu retournes au seuil veracity ≥ 0.90 strict (au lieu de 0.85
  transitoire) après 7 jours de runtime stable post-réintégration
  (cf. Garde-fou 2-bis critère retour)
- Plus de signaux à veracity 0.90+ = ton filtre devient plus
  sélectif = moins de trades pris mais avec edge potentiel plus haut

### Tu veux abandonner après 2 semaines de pertes

- Lis l'avant-propos. Le hit rate global est 22-31 %. **C'est attendu**.
- Compte tes trades : as-tu pris **moins de 15-20 trades** ? Échantillon
  trop petit pour conclure quoi que ce soit. Continue, mais sizing 0.5 %
  jusqu'à 30 trades cumulés.
- Au-delà de 30 trades cumulés avec hit rate <33 % et P&L négatif :
  on retourne au plan dessin. C'est de la science, pas de la honte.

---

## Sources et références dans Tik

Toutes les références chiffrées de ce manuel viennent de mesures
documentées dans CLAUDE.md :

- **Garde-fou 2-bis** (section 5) : sizing 1 %, veracity ≥ 0.85,
  pas GOLD, priorité SHORT BTC
- **ADR-017** (`docs/adr/017-macro-events-calendar.md`) : ±4h autour
  events HIGH
- **ADR-018** : Tik OSINT pur, sémantique uniforme `confidence`
- **Paquet 10 Phase A.2-bis** : pattern flash 0.90+ inversé contre-intuitif
- **Paquet 27 audit pré-J+14** : SHORT BTC 63 % hit, GOLD 4.8 % hit
- **Paquet 28 Phase C Session 2** : auto-resolution Watchlist + hit
  rate perso

Si tu vois un chiffre dans ce manuel qui te paraît bizarre, demande
toujours : "d'où vient ce chiffre côté Tik ?". S'il n'est pas
mesuré, on ne l'utilise pas.

---

## Avant ton premier trade le 24 mai — checklist finale J-1 (23 mai)

- [ ] Capital défini et déposé sur le broker
- [ ] 3 trades démo réussis cette semaine
- [ ] Journal de trading prêt (fichier ouvert, colonnes définies)
- [ ] Watchlist Tik vide (clear depuis Expo Go) → départ propre
- [ ] Règles strictes annexe B imprimées et collées au mur
- [ ] Décision tree section 2 imprimée et à portée de main
- [ ] Tu as briefé 1 proche sur ce que tu fais
- [ ] Tu as fixé un horaire de session (ex. 9h-10h ou 18h-19h, pas
  toute la journée)
- [ ] Tu as fixé une condition d'arrêt mensuelle (ex. -10 % capital
  cumulé = stop 30 jours)
- [ ] Tu as relu l'avant-propos une dernière fois ✓

**Bonne chance lundi matin. Reviens me voir en fin de semaine 1 pour
debriefer.**
