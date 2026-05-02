# Glossaire FR-EN — Jargon news financières (BTC + GOLD)

Ce glossaire est destiné à l'annotation manuelle du dataset golden Tik.

**Comment l'utiliser** : ouvre ce fichier dans VS Code à côté de ton terminal d'annotation. Quand un titre contient un terme que tu ne connais pas, viens chercher ici.

**Légende colonne "Tendance"** :
- 🟢 = signal **bull** typique (le marché monte)
- 🔴 = signal **bear** typique (le marché descend)
- ⚪ = signal **contextuel** (peut aller dans les deux sens selon le contexte du titre)

> ⚠️ **Attention** : la colonne Tendance est un **point de départ**, pas une règle absolue. Toujours lire le titre en entier avant de décider. Une "rate cut" annoncée peut être bullish (relance) ou bearish (panique récession) selon le contexte.

---

## 1. Crypto / Bitcoin (~ 25 termes)

| EN | FR | Tendance | Note rapide |
|---|---|---|---|
| **ETF** | Fonds négocié en bourse (sur BTC) | 🟢 si "approval"/"inflows" | Quand un ETF Bitcoin reçoit des "inflows" (= entrées d'argent), c'est bull. Quand il y a des "outflows", c'est bear. |
| **Spot ETF** | ETF au comptant (vs ETF futures) | 🟢 | Les Spot ETF achètent vraiment du BTC physique → demande directe |
| **Halving** | Halving (réduction de moitié de la récompense des mineurs) | 🟢 long terme | Événement tous les 4 ans qui réduit l'offre. Historiquement bull à 6-18 mois. |
| **ATH** | All-Time High = plus haut historique | 🟢 | Briser un ATH = bull psychologique fort |
| **Hashrate** | Puissance de calcul totale du réseau Bitcoin | 🟢 si "record" | Hashrate qui monte = sécurité du réseau ↑, signe de confiance des mineurs |
| **HODL** | "Hold On for Dear Life" = garder à long terme | ⚪ | Sentiment communautaire, pas une indication claire bull/bear |
| **FUD** | Fear, Uncertainty, Doubt = peur/incertitude/doute | 🔴 | Quand des médias "spread FUD" sur Bitcoin → bear |
| **Whale** | Baleine = gros détenteur de BTC | ⚪ | Whales qui accumulent = 🟢, whales qui dump = 🔴 |
| **Mining capitulation** | Capitulation des mineurs | 🔴 court terme, 🟢 moyen terme | Mineurs qui vendent en panique → fond du marché souvent |
| **Liquidation** | Liquidation forcée (positions à effet de levier) | 🔴 si volume énorme | "Long liquidations" = 🔴, "short squeeze" = 🟢 |
| **Long squeeze** | Liquidation massive de positions longues | 🔴 | Les acheteurs forcés de vendre |
| **Short squeeze** | Liquidation massive de positions short | 🟢 | Les vendeurs à découvert forcés de racheter |
| **Mempool** | File d'attente des transactions BTC non confirmées | ⚪ | Mempool plein = activité on-chain ↑, plutôt 🟢 |
| **On-chain** | Données provenant de la blockchain elle-même | ⚪ | Indicateur qualitatif, dépend de quelle métrique |
| **MVRV ratio** | Market Value to Realized Value ratio | ⚪ | MVRV élevé (>3) = surchauffe 🔴, MVRV bas (<1) = sous-évalué 🟢 |
| **Stablecoin inflows** | Entrées de stablecoins (USDC, USDT) sur les exchanges | 🟢 | Des stables sur les exchanges = du cash prêt à acheter du BTC |
| **DeFi** | Decentralized Finance | ⚪ | Pas directement BTC, mais croissance DeFi = bull général crypto |
| **Staking** | Mise en jeu (verrouillage de tokens pour rendement) | 🟢 si "increase" | Plus de staking = moins d'offre liquide |
| **Custody** | Garde / conservation institutionnelle | 🟢 si "launch" | Nouveaux services custody = institutionnels arrivent |
| **Rugpull** | Arnaque où l'équipe se barre avec les fonds | 🔴 | Toujours bear (mauvaise pub crypto) |
| **Hack / Exploit** | Piratage | 🔴 | Toujours bear court terme |
| **Pump** | Pump = montée rapide artificielle | ⚪ | "Pump and dump" = 🔴, "organic pump" = 🟢 |
| **Dump** | Vente massive | 🔴 | Quand des whales "dump" du BTC, c'est bear |
| **Outflows from exchanges** | Sorties de BTC des exchanges (vers cold wallets) | 🟢 | Les gens retirent leur BTC pour HODL = baisse de l'offre liquide |
| **Inflows to exchanges** | Entrées de BTC sur les exchanges | 🔴 | Les gens préparent à vendre = pression vendeur |
| **Halt** | Suspension (de trading sur un exchange) | 🔴 | Mauvais signe technique |

---

## 2. Or / Métaux précieux (~ 15 termes)

| EN | FR | Tendance | Note rapide |
|---|---|---|---|
| **Safe haven** | Valeur refuge | 🟢 | Quand des news parlent de "safe haven demand", c'est bull pour l'or |
| **Flight to quality** | Fuite vers la qualité | 🟢 | Investisseurs qui se réfugient dans l'or = bull |
| **DXY / Dollar Index** | Indice du dollar US | 🔴 si DXY ↑ pour l'or | DXY qui monte = dollar fort = or qui baisse (corrélation négative classique) |
| **Strong dollar** | Dollar fort | 🔴 | Or et dollar sont anti-corrélés |
| **Weak dollar** | Dollar faible | 🟢 | Bon pour l'or |
| **Real yields** | Rendements réels (= taux nominaux - inflation) | 🔴 si réels ↑ | Real yields qui montent = or qui baisse |
| **TIPS** | Treasury Inflation-Protected Securities | ⚪ | Indicateur des real yields, à comprendre via DXY/yields |
| **Central bank gold reserves** | Réserves d'or des banques centrales | 🟢 si "increase" | Les BC qui accumulent = bull structurel |
| **COT report** | Commitment of Traders (CFTC) | ⚪ | Positionnement des grands acteurs, neutre par défaut |
| **Managed Money** | Catégorie "fonds spéculatifs" du COT | ⚪ | Position courte → contrarian 🟢 (cf. ADR Tik) |
| **Mining production** | Production minière d'or | ⚪ | Hausse de prod = offre ↑ → 🔴 mais effet long terme |
| **KITCO / Mining.com / FXEmpire** | Sites éditoriaux or | n/a | Publishers fréquents dans le flux GOLD |
| **Gold/silver ratio** | Ratio or/argent | ⚪ | >80 = or surévalué vs argent, <40 = sous-évalué |
| **Bullion** | Lingots / barres de métal physique | ⚪ | Synonyme générique d'or physique |
| **Tonnes / metric tons** | Tonnes (unité de mesure) | ⚪ | Unité standard, ne donne pas de direction |

---

## 3. Macro / Banque centrale (~ 18 termes)

| EN | FR | Tendance pour BTC | Tendance pour GOLD | Note rapide |
|---|---|---|---|---|
| **Fed / FOMC** | Réserve Fédérale US / Comité de politique monétaire | ⚪ | ⚪ | Selon que la décision est dovish ou hawkish |
| **Hawkish** | Faucon = restrictif (taux ↑) | 🔴 | 🔴 | Mauvais pour les actifs risqués ET pour l'or |
| **Dovish** | Colombe = accommodant (taux ↓) | 🟢 | 🟢 | Bon pour le risque ET pour l'or |
| **Rate hike** | Hausse de taux | 🔴 | 🔴 | Hausse = restrictif = bear assets risqués + bear or |
| **Rate cut** | Baisse de taux | 🟢 | 🟢 | Baisse = accommodant = bull crypto + bull or |
| **Easing / Quantitative Easing (QE)** | Assouplissement / création monétaire | 🟢 | 🟢 | QE = + de liquidité = bull crypto + bull or |
| **Tightening / QT** | Resserrement / destruction monétaire | 🔴 | 🔴 | QT = - de liquidité = bear |
| **Inflation cools / eases** | Inflation ralentit | 🟢 | ⚪ | Cool inflation = Fed peut être dovish = bull crypto. Pour l'or c'est mixte (l'or aime l'inflation). |
| **Inflation surges / hot CPI** | Inflation s'accélère | 🟢 long terme or | 🔴 court terme crypto, 🟢 long terme | Hot CPI = Fed hawkish = bear court terme. Mais l'or comme hedge inflation = 🟢 long terme |
| **CPI** | Consumer Price Index = indice des prix à la conso | ⚪ | ⚪ | Le chiffre lui-même est neutre, c'est la **comparaison aux attentes** qui compte |
| **PPI** | Producer Price Index = inflation côté producteurs | ⚪ | ⚪ | Idem CPI |
| **Soft landing** | Atterrissage en douceur | 🟢 | ⚪ | Bon scénario économique |
| **Recession** | Récession | 🔴 court terme | 🟢 | Crypto = risk asset → bear. Or = safe haven → bull |
| **Stagflation** | Inflation + stagnation économique | ⚪ | 🟢 | L'or adore la stagflation |
| **Yield curve inversion** | Inversion de la courbe des taux | 🔴 | ⚪ | Signal de récession à venir |
| **Bps / basis points** | Points de base (1 bps = 0.01%) | ⚪ | ⚪ | Unité, pas de direction. "50 bps hike" = +0.5% |
| **Fed pivot** | Pivot Fed (passage hawkish → dovish) | 🟢 | 🟢 | "Fed pivot rumor" = bull général |
| **Tapering** | Tapering = réduction du QE | 🔴 | 🔴 | Tapering = moins de liquidité |

---

## 3 bis. Verbes économiques fréquents

| EN | FR | Tendance | Note rapide |
|---|---|---|---|
| **Surge / soar / skyrocket** | Bondir / s'envoler | 🟢 | Forte hausse |
| **Rally / advance / climb** | Rallier / progresser / grimper | 🟢 | Hausse |
| **Rebound / recover** | Rebondir / récupérer | 🟢 | Reprise après baisse |
| **Plunge / crash / collapse** | Plonger / crasher / s'effondrer | 🔴 | Forte baisse |
| **Tumble / slump / slide / slip** | Chuter / glisser | 🔴 | Baisse |
| **Drop / fall / decline** | Baisser / décliner | 🔴 | Baisse modérée |
| **Edge higher / inch up** | Grimper légèrement | 🟢 (faible) | Petite hausse |
| **Edge lower / inch down** | Descendre légèrement | 🔴 (faible) | Petite baisse |
| **Stalls / stagnates / consolidates** | Stagne / consolide | ⚪ | Pas de direction → 🟢 si on attend une cassure haute, mais souvent neutre |
| **Hits / breaks / smashes record** | Bat un record | 🟢 | Souvent bull |
| **Erases gains** | Efface les gains | 🔴 | Annulation de la hausse précédente |

---

## 4. Régulation / Juridique (~ 10 termes)

| EN | FR | Tendance | Note rapide |
|---|---|---|---|
| **SEC** | Securities and Exchange Commission (gendarme bourse US) | ⚪ | Selon action : "SEC approves" 🟢, "SEC sues" 🔴 |
| **CFTC** | Commodity Futures Trading Commission | ⚪ | Idem |
| **Lawsuit / sues** | Poursuite judiciaire | 🔴 | Toujours bear court terme |
| **Settlement** | Accord à l'amiable (fin de poursuite) | 🟢 | Élimine une incertitude juridique |
| **Ban / banned** | Interdiction | 🔴 | "China bans crypto" = bear très fort |
| **Crackdown** | Répression / sévir | 🔴 | Action régulatoire hostile |
| **Approval / approves** | Approbation | 🟢 | "ETF approval" = très bull |
| **Delisted** | Retiré de la cote | 🔴 | Mauvais pour le token concerné |
| **Sanctions** | Sanctions internationales | 🟢 pour or, ⚪ pour BTC | Sanctions = tensions géopolitiques = safe haven 🟢 or |
| **Indictment / charges** | Mise en accusation | 🔴 | Toujours bear |

---

## 5. Indicateurs techniques (rare dans les titres mais ça arrive)

| EN | FR | Tendance | Note rapide |
|---|---|---|---|
| **Support level** | Niveau de support | ⚪ | "Holds support" = 🟢, "breaks support" = 🔴 |
| **Resistance level** | Niveau de résistance | ⚪ | "Breaks resistance" = 🟢, "rejected at resistance" = 🔴 |
| **Breakout** | Cassure haussière | 🟢 | Sortie par le haut |
| **Breakdown** | Cassure baissière | 🔴 | Sortie par le bas |
| **Higher low / lower high** | Plus bas plus haut / plus haut plus bas | 🟢 / 🔴 | Higher low = tendance haussière, lower high = baissière |
| **Bull flag / bear flag** | Drapeau haussier / baissier | 🟢 / 🔴 | Pattern technique |
| **Death cross** | Croisement de la mort | 🔴 | MA50 passe sous MA200 |
| **Golden cross** | Croisement doré | 🟢 | MA50 passe au-dessus MA200 |
| **Oversold / overbought** | Survendu / suracheté | 🟢 / 🔴 | RSI < 30 = oversold (rebond probable), RSI > 70 = overbought (correction probable) |

---

## Cas spéciaux à reconnaître

### Le titre tronqué Google News

Google News colle souvent " - Publisher" à la fin du titre. Exemple :
> "Bitcoin holds firm above $80,000 - Reuters"

→ ignore le "- Reuters", le titre est "Bitcoin holds firm above $80,000" → 🟢 (bull faible).

### Le titre mixte (deux signaux contradictoires)

> "Bitcoin surges 5% but analysts warn of imminent correction"

→ surge = 🟢 mais "warn of correction" = 🔴 → **neutral** (les deux s'annulent).

### Le titre hors-sujet

Tu vois ça dans les news Bitcoin parfois :
> "Ethereum upgrade Pectra goes live, ETH gains 8%"

→ ça parle d'ETH, pas de BTC → **neutral pour BTC**.

### Le titre "ironique" Reddit

> "Just bought my first satoshi with my last paycheck, wish me luck"

→ post Reddit individuel, pas une analyse → **neutral** par défaut. (Sauf si la communauté Reddit a massivement upvoté → mais on regarde juste le texte ici.)

---

## Règle d'or à garder en tête

> **Dans le doute → neutral.** La rigueur statistique > l'envie de "trouver une direction" partout.

Un dataset avec 40% de neutral honnêtes vaut largement mieux qu'un dataset avec 5 erreurs de bull/bear par incompréhension du jargon.

---

*Glossaire généré pour Tik Paquet 4 Session 4 (calibration). Mis à jour : 2026-05-01.*
