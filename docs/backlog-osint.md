# Backlog couches OSINT structurées — décision 2026-05-17

## Pourquoi ce fichier existe

Tik est une plateforme OSINT modulaire conçue comme cerveau analytique
en amont de Zeta + Totem + bots futurs (cf. CLAUDE.md sections 1 et 3).
Le SDK Python Paquet 2 existe pour servir ces consommateurs. Tik doit
être plus complet et structuré qu'un simple outil de trading manuel :
il doit produire des **couches stables exploitables programmatiquement
par des bots**.

Ce fichier existe pour **trois raisons distinctes** :

1. **CLAUDE.md fait déjà ~263 KB** (largement au-dessus du seuil de
   confort 218 KB documenté dans le prompt initial). Ajouter encore
   200+ lignes de backlog OSINT directement dedans alourdit son
   chargement automatique pour toute future session Claude.

2. **Séparation des préoccupations** : CLAUDE.md documente l'**état
   actuel** du projet (Paquets livrés, ADRs acceptés, bugs résolus,
   garde-fous opérationnels). Ce fichier documente une **stratégie de
   roadmap** sous condition (Vagues 1/2/3 à activer selon mesures
   empiriques). Les deux ont des cycles de mise à jour différents :
   CLAUDE.md évolue à chaque livraison, ce fichier évolue à chaque
   point de réévaluation (J+44, J+90, etc.).

3. **Sécurisation gestion couches futures** : ce backlog liste
   explicitement ce qui est REFUSÉ (Arkham, Mempool Space,
   Blockchain.com Explorer en doublon de Whale Alert ; miners flows ;
   etc.). Cela protège contre les ajouts impulsifs en future session
   qui ne respecteraient pas le principe directeur "pas d'ajout sans
   manque mesuré".

**Date de création** : 2026-05-17 (J+17 sur J+44 du trading manuel
post-ADR-018).

**Date de réévaluation prévue** : 2026-06-30 (J+44 du trading manuel
décalé au 2026-05-24). Réévaluation post-J+90 prévue ~2026-08-22.

---

## Engagements méthodologiques actifs

Ces principes encadrent **toute** future décision d'ajout/retrait des
couches OSINT listées dans ce backlog. Ils ne sont pas négociables sans
mise à jour explicite de ce fichier.

### Principe directeur "pas d'ajout sans manque mesuré"

Applicable aux Vagues 2 et 3 (pas à la Vague 1 dont la justification
structurelle est documentée ci-dessous). Une instance Claude future
qui voudrait coder une source Vague 2/3 doit d'abord prouver
empiriquement (chiffres à l'appui) que son absence a fait rater des
trades mesurables dans le journal de trading manuel.

### Engagements 13bis (CLAUDE.md section 13bis)

1. Lire le code AVANT d'affirmer
2. Distinguer vision (CLAUDE.md / ce backlog) vs réalité (code)
3. Se challenger quand la formulation suggère une réalité fragile
4. Ne JAMAIS inventer de chiffres
5. Vérifier hypothèses avant verdict
6. Mea culpa déclaratif quand erreur découverte
7. Re-questionnement sérieux si question reposée
8. Mentionner 3-4 limites connues à chaque livraison
9. Format pour/contre/verdict pour décisions techniques
10. Mesurer plutôt que spéculer quand données accessibles
11. Ne pas cumuler spécialisation marketing et implémentation hybride

### Discipline opérationnelle Vague 1

- **Une source à la fois**, pas en parallèle
- **2 semaines de mesure** après chaque ajout AVANT la suivante
- **Whale Alert avec seuils stricts** (≥ 10 M USD) pour éviter le bruit
- **Documenter les hypothèses causales** pour chaque source
  (pourquoi elle DOIT améliorer un signal Tik, avec arguments testables)

### Métriques de mesure rigoureuses (engagement audit 2026-05-17)

Quand on évalue si une source produit "des signaux exploitables", on
mesure obligatoirement :

- **IC Spearman** entre la nouvelle source et `delta_pct` futur (méthodo
  Paquet 19 P2 backtest sources numériques)
- **Hit rate par palier de bias** sur 6-12 mois historique
- **Stabilité cycle-à-cycle** (variance des sorties, comme cache
  sentiment Lacune C Paquet 9)
- **Coverage** : % de cycles où la source produit un signal non-neutre

Sans ces 4 métriques chiffrées, "2 semaines de mesure" reste de
l'observation subjective.

---

## VAGUE 1 — À CODER POST-J+14 (justification structurelle)

**Garde-fou timing** : recommandation explicite NE RIEN coder avant le
trading manuel J+14 (décalé au 2026-05-24). Stabilité du runtime >
nouveautés. Tik doit rester sur l'infra connue pendant que la
trader manuelle se familiarise avec BTC + GOLD existants.

> **MAJ 2026-05-24 — garde-fou calendaire LEVÉ + règle unique SHADOW vs ENRÔLEMENT.**
> On est le 2026-05-24 → le blocage calendaire ci-dessus a expiré. Pour éviter
> que des sessions se contredisent (cf. incohérence créée le 2026-05-23 : le
> Paquet 35 avait posé un « pas avant le 27/05 » non réconcilié avec ce
> garde-fou), **la règle unique est** :
> - **SHADOW** (construire l'ingester + collecter en DB/Redis, **sans** le brancher
>   sur le `combined_bias` des engines) : **autorisé dès maintenant**. Zéro impact
>   sur les signaux, sur le go/no-go du 27/05, sur le trading. Construit l'historique
>   nécessaire pour tester la source plus tard. Vérifié en code (2026-05-23) : les
>   engines lisent des **clés Redis explicites** → une nouvelle clé n'est jamais
>   ramassée tant qu'aucun `_enrich_with_<source>` n'est câblé.
> - **ENRÔLEMENT** (brancher la source sur la **direction** des signaux) :
>   **seulement après** (a) le go/no-go du 27/05 (Tik a-t-il un edge directionnel ?),
>   (b) mesure de la valeur prédictive propre de la source sur ~2 semaines
>   (IC Spearman / hit rate / **gain** via `paired_gain_significance`), et idéalement
>   (c) observation sur un **régime de marché mixte** (pas qu'un baissier).
>   Rappel (Paquet 33/35) : Tik n'a **aucun edge directionnel démontré** à ce jour
>   → enrôler un input dans un moteur directionnel non validé est prématuré.
> - **En NO-GO directionnel** : une source peut quand même servir comme **carte de
>   contexte** dashboard (ex. Polymarket, Whale Alert), pas comme overlay du bias.

Les 5 éléments suivants sont à coder **dans cet ordre** (séquentiel
strict, une source à la fois, mesure 2 semaines entre chaque).

### V1.1 — Silver (XAG/USD) en **entité tradable indépendante**

**Statut** : à coder en Vague 1, premier élément si la trader veut
diversifier vers les métaux. **Distinction critique vs prompt initial
ChatGPT** : Silver est PRODUIT INDÉPENDANT tradable, PAS overlay
contextuel GOLD.

**Justification structurelle** : (a) métal précieux corrélé GOLD avec
décalage temporel exploitable, (b) volatilité 2-3× supérieure à GOLD
(opportunités trades plus fréquentes), (c) infra Tik 80 % réutilisable
côté BTC/GOLD existants.

**Stack technique attendu** :
- Ingester prix : Yahoo Finance `SI=F` (futures) ou `XAGUSD=X` (spot).
  Polling identique à GOLD (60s).
- Overlays disponibles : Google News (query "silver price"), GDELT
  (mapping à recalibrer car silver n'a pas la même sémantique safe
  haven que gold), COT silver (CFTC publie aussi), possiblement
  r/Silverbugs (Reddit) si volume suffisant.
- Engine swing : adaptation de `analyze_swing_gold` (mêmes seuils
  directionnalité initialement, à recalibrer post-J+30).
- Track record + hit rate : extension automatique via dispatch horizon
  (déjà supporté Paquet 17).
- Dashboard : ajouter `SILVER` à `ENTITY_FILTERS` des écrans Signals,
  Watchlist, KPIs Home. Ajouter à `HORIZON_SPECS_BY_SIGNAL_HORIZON` si
  flash silver pertinent (à valider — Yahoo a 15 min de délai comme
  GOLD donc pas de flash silver, cohérent ADR-005).

**Effort estimé** : ~4-6 h backend + ~1-2 h dashboard.

**Hypothèses causales à valider** :
1. Le Gold/Silver Ratio mesuré comme metric Tik secondaire (pas overlay)
   peut produire des signaux de retour à la moyenne lors d'extrêmes
2. Le COT silver montre-t-il des positionnements directionnels distincts
   du COT gold (corrélation, pas identité) ?
3. Les news "silver" sont-elles dominées par les mêmes publishers que
   "gold" (Mining.com, KITCO, FXEmpire) ou diversifiées (Silver Institute,
   etc.) ?

**Marqueurs de réussite à 2 semaines** : IC Spearman ≥ 0.10 sur 6 mois
historique × au moins un overlay, hit rate signaux directionnels swing
silver > 35 % (vs 33 % random), coverage ≥ 30 % des cycles.

---

### V1.2 — WGC + SPDR GLD ETF flows Gold

**Statut** : couche structurée OSINT, intégrée comme overlay swing GOLD
(pas entité indépendante).

**Justification structurelle** : (a) Tik a perdu ses 2 overlays GOLD
(DXY + COT désactivés Paquet 19 amendement P2 par calibration empirique
inversée), GOLD émet quasi exclusivement neutral aujourd'hui ; (b)
demande institutionnelle ETF est l'angle dominant gold post-2024
(SPDR GLD a ~70 G USD AUM, WGC publie monthly + weekly flows
gratuitement) ; (c) data free, API stables (WGC publie en JSON
téléchargeable).

**Stack technique attendu** :
- Ingester `wgc_etf_flows_ingester.py` : polling daily (les flows ETF
  ne changent pas en intra-day), fetch WGC monthly + SPDR GLD daily.
- Overlay `_enrich_with_gold_etf_flows` dans `analyze_swing_gold` :
  inflow ETF persistant → bull GOLD ; outflow → bear GOLD.
- Calibration mapping seuils : à mesurer post-déploiement sur 6 mois
  historique (la mémoire WGC remonte à 2003).

**Effort estimé** : ~3-5 h backend.

**Hypothèses causales à valider** :
1. Le delta hebdomadaire AUM SPDR GLD anticipe-t-il les mouvements gold
   sur 5-30 jours (IC Spearman significatif) ?
2. Le mapping trend-following (inflow = bull) tient-il aux extrêmes ?
3. Coverage suffisante (~52 mesures hebdo/an pour SPDR + ~12 mensuelles
   pour WGC) pour produire des signaux Tik ?

---

### V1.3 — Flux ETF spot BTC (arbitrage de source)

**Statut** : couche structurée OSINT, overlay swing BTC. **À coder APRÈS
V1.2** (mesure 2 semaines V1.2 d'abord), et **après le go/no-go du 27/05**
(cf. règle SHADOW vs ENRÔLEMENT en tête de Vague 1). Aucun code écrit à
ce jour.

**Justification structurelle** : (a) ETF BTC US ont >50 G USD AUM
post-janvier 2024, dominant institutionnel mesurable ; (b) le détail
quotidien par fonds est publié gratuitement par plusieurs agrégateurs ;
(c) signal fortement actionable (inflow persistant net = thèse
institutionnelle haussière).

#### Arbitrage de source — analyse pour/contre (MAJ 2026-05-24, vérifiée)

> **Contexte de cette MAJ.** Question utilisatrice : documenter
> « DefiLlama en source principale (API propre) + Farside en vérification
> croisée ». **Vérification empirique faite avant de figer (engagements
> 13bis #5 et #10)** → la prémisse « DefiLlama = API propre *gratuite* »
> est **fausse**. **Mea culpa** : l'API *générale* DefiLlama est gratuite,
> mais l'endpoint flux ETF (`/etfs/flows`, `/etfs/snapshot`) est **Pro à
> 300 $/mois** (source : api-docs.defillama.com, section Pro-Only).

| Source | Accès | Coût | Cadence | Fiabilité | Rôle proposé |
|---|---|---|---|---|---|
| **DefiLlama** `/etfs/flows` | API REST propre **documentée** | 🔴 Pro **300 $/mois** | quotidien | Haute (API officielle) | Principale **SEULEMENT si** budget payant validé |
| **SoSoValue** | Dashboard web (JSON interne **non documenté**, à confirmer) | Gratuit | quotidien temps réel | Moyenne (endpoint non officiel, peut casser) | Candidat principal **gratuit** (à vérifier au codage) |
| **CoinGlass** ETF | API free tier (scope exact **à revérifier**, cf. V1.4) | Gratuit (free) / 29 $+ pro | quotidien | Moyenne-haute | Candidat principal **gratuit** alternatif |
| **Farside** | Scrape HTML, **bloque les bots (403 vérifié 2026-05-24)** | Gratuit | quotidien (soir US) | 🔴 Faible (fragile + anti-bot) | **Vérification croisée uniquement** |
| **CoinShares** | Blog/PDF hebdo, **pas d'API/JSON** | Gratuit | hebdomadaire | Haute (institutionnel) mais lent | Vérification croisée lente / fallback |

**Arguments POUR « DefiLlama principale + Farside cross-val »** :
- DefiLlama est la **seule** API REST propre et documentée du lot → robuste,
  pas de scraping, format JSON stable, maintenance faible.
- Architecture saine en principe : une source fiable décide, une 2ᵉ source
  indépendante valide (cohérent ADR-004 cross-validation + ADR-011).

**Arguments CONTRE (qui l'emportent par défaut)** :
- **Coût 300 $/mois** = violation directe de la règle « pas de budget API
  payant tant que l'utilisatrice n'a pas validé » (CLAUDE.md §7). Pour un
  seul overlay parmi ~10, le ROI doit être démontré AVANT de payer.
- **Farside est un mauvais candidat même en cross-val** : il bloque
  activement les bots (403). Le scrape est fragile et instable (rappel
  Reddit IP-ban Bug 11). Il vaut comme 3ᵉ recoupement, pas comme pilier.
- Aucune **API propre gratuite** n'existe pour ces flux → la « source
  principale » gratuite sera de toute façon un dashboard à JSON interne
  (SoSoValue / CoinGlass), pas une vraie API documentée.

**VERDICT (révisé 2026-05-24)** :
1. **Par défaut (sans budget)** : la source principale ne peut PAS être
   DefiLlama. → **principale = SoSoValue *ou* CoinGlass free tier** (JSON
   interne, à arbitrer au moment du codage après vérification réelle de
   l'endpoint), **vérification croisée = Farside (scrape) + CoinShares
   (hebdo)**. Farside reste cantonné au recoupement, jamais pilier.
2. **Conditionnel** : si un jour un **budget 300 $/mois est explicitement
   validé** par l'utilisatrice ET qu'un edge ETF-flows est mesuré (IC
   Spearman ≥ 0.10 sur 6-12 mois) → **DefiLlama devient la source
   principale propre**, les autres passent en cross-validation. C'est
   l'architecture idéale, mais payante donc gelée par défaut.
3. **Choix principale gratuite SoSoValue vs CoinGlass tranché au codage**
   (même prudence que V1.4 : « auditer exactement ce que le free tier
   expose au moment du codage »). Marqueur : endpoint JSON joignable +
   stable sur 1 semaine d'observation avant de le déclarer principale.

**Plan B obligatoire dans le code** (inchangé, renforcé) :
- Alerte si 3 cycles consécutifs sans data sur la source principale →
  bascule automatique sur la 1ʳᵉ source de cross-val disponible + log
  error + push.
- Jamais dépendre d'une source unique (le 403 Farside prouve qu'une
  source peut disparaître du jour au lendemain).

**Stack technique attendu** :
- Ingester `btc_etf_flows_ingester.py` : source principale (SoSoValue /
  CoinGlass) + fallbacks (Farside scrape, CoinShares hebdo) intégrés,
  polling daily (les flows ne changent pas en intra-day).
- Overlay `_enrich_with_btc_etf_flows` dans `analyze_swing_btc`
  (trend-following : inflow net persistant → bull BTC ; outflow → bear).
- Calibration mapping seuils sur 6-12 mois historique avant activation
  comme overlay (si IC Spearman < 0.05 → garder en evidence dashboard
  seulement, pas d'impact direction — même règle que V1.5 Whale Alert).

**Effort estimé** : ~4-6 h backend (dont fallbacks + monitoring), +
~1-2 h calibration historique avant enrôlement directionnel.

---

### V1.4 — CoinGlass free tier (OI, funding, liquidations BTC)

**Statut** : couche structurée OSINT, overlay swing BTC.

**Justification structurelle** : détection baleines indirecte via
positionnement dérivés (OI agrégé, funding rates extrêmes, liquidations
massives).

**Vérification rigoureuse OBLIGATOIRE avant code** : CoinGlass free tier
expose-t-il vraiment les métriques utiles ? Aux dernières infos publiques
(à revérifier au moment du codage) :
- Free tier : OI agrégé multi-exchanges, funding agrégé. **Bon.**
- Pro tier 29 $/mois : OI par exchange, funding par paire, données
  granulaires. **Risque coût caché si on veut ces données fines.**

**Plan d'action** :
1. Auditer exactement ce que le free tier expose au moment du codage
2. Si insuffisant → reporter à Vague 3 (avec ROI freemium démontré)
3. Si suffisant → coder l'ingester + overlay

**Effort estimé** : ~3-5 h (si free tier suffisant).

**À coder APRÈS V1.3** (mesure 2 semaines V1.3 d'abord).

---

### V1.5 — Whale Alert BTC free tier

**Statut** : couche structurée OSINT, overlay swing BTC.

**Justification structurelle** : détection baleines directe (transferts
on-chain > seuil USD).

**Risques structurels documentés** :
1. Les vraies baleines institutionnelles utilisent OTC desks (Coinbase
   Prime, Genesis, Cumberland, B2C2) → **pas visibles on-chain**
2. Whale Alert capte essentiellement les rebalancing inter-exchange
   (rarement représentatif d'un trader directionnel)
3. Signal/bruit difficile à calibrer sans dataset golden

**Plan d'action** :
- Seuil strict ≥ 10 M USD (engagement prompt initial)
- Filtre direction : wallet → exchange = pression vendeuse ; exchange
  → wallet = accumulation (mais souvent rebalancing exchange, pas trader)
- **Calibration sur 6-12 mois historique obligatoire avant intégration
  overlay** — si IC Spearman < 0.05, ne pas activer comme overlay,
  garder en source d'evidence uniquement (visible dans dashboard mais
  pas impact signal direction)

**Effort estimé** : ~3-5 h dev + 1-2 h calibration.

**À coder APRÈS V1.4** (mesure 2 semaines V1.4 d'abord, sauf décision
de skip V1.4 si free tier CoinGlass insuffisant).

---

## VAGUE 2 — POST-J+44 (uniquement si manques mesurés)

Date d'activation : pas avant 2026-06-30 (J+44 du trading manuel
décalé). Codage **conditionné à manques récurrents documentés dans le
journal de trading**.

| Source | Condition de codage |
|---|---|
| Détection d'anomalies sur flux Vague 1 | Si Vague 1 codée et baseline accumulée ≥ 4 semaines |
| Régime marché (risk-on/risk-off, classifieur FRED) | Si bots futurs (Zeta/Totem) en demandent un classifieur structuré |
| Stress systémique (MOVE index, TED spread, crédit) | Si périodes bear/range observées rendent Vague 1 insuffisante |
| Géopolitique (réactivation GDELT calibrée) | Si régime change vs périodes 2025-2026 calibrées Paquet 19 P2 |
| Détection comportementale (euphorie/panique narrative) | Si signaux narratif Ollama existants insuffisants pour capter les renversements |

**Pour chaque source, à fournir au moment de l'activation** :
- 3 exemples de trades manqués documentés dans le journal qui auraient
  été pris correctement si cette source avait existé
- Métrique de coverage attendue
- Plan B si source indisponible (similaire fallback Farside V1.3)

---

## VAGUE 3 — POST-J+90 (uniquement si edge mesurable)

Date d'activation : pas avant ~2026-08-22 (J+90 du trading manuel
décalé). Codage **conditionné à un edge mesurable des Vagues 1+2** sur
journal de trading.

| Source | Condition |
|---|---|
| Glassnode Pro / CryptoQuant Pro (30-50 $/mois) | Si ROI freemium démontré (delta hit rate ≥ 5 points) justifie l'investissement |
| Corrélation dynamique multi-actifs | Si complexité statistique justifiée par bots futurs Zeta/Totem |
| Platinum (XPT/USD), Palladium (XPD/USD) | Si Silver V1.1 démontre sa valeur en cross-asset |
| **EUR/USD comme entité tradable** | Réservé. Activable plus tôt si trader change d'avis (cf. message utilisatrice 2026-05-17). Mesure d'avant : divergence DXY/EUR-USD a-t-elle fait rater des trades Gold ? |
| ETH comme entité tradable | Réservé. À reconsidérer si la trader veut diversifier post-J+90 |

**Mes 4 limites rappelées** (cf. engagements 13bis) :
1. Le coût payant 30-50 $/mois doit être justifié par un edge mesurable,
   pas par "ça pourrait être utile"
2. EUR/USD réintroduit la logique forex différente de crypto/métaux —
   architecture pipeline OSINT actuel pas testée sur cette classe
3. ETH ajout massif côté infra mais reuse 90 % du code BTC = bon ratio
4. Platinum/Palladium illiquides, info OSINT limitée — coût/bénéfice
   incertain hors cycle économique chinois fort

---

## REFUSÉ INDÉFINIMENT (sauf justification nouvelle documentée)

- **Arkham + Mempool Space + Blockchain.com Explorer** en plus de
  Whale Alert (V1.5) → doublons fonctionnels
- **Miners flows** → pertinence faible documentée par la communauté
  crypto post-2022 (hash rate ne corrèle plus prix BTC depuis l'ère
  ETF)
- **13F institutionnels (SEC EDGAR) comme overlay BTC/GOLD** (analyse
  utilisatrice 2026-05-25) → (a) **horizon incompatible** : publiés 45 à
  135 j après le trimestre, granularité trimestrielle, alors que Tik
  trade flash (1h) et swing (5j) ; (b) **scope incompatible** : actions
  US long-only, pas BTC/Gold — lien seulement indirect via les ETF
  (IBIT/GLD) ; (c) **dominé par les flux ETF quotidiens déjà planifiés**
  (V1.2 WGC/SPDR GLD + V1.3 ETF BTC) qui donnent la même info "argent
  institutionnel" en journalier, pas trimestriel-en-retard ; (d) **alpha
  digéré** : le 13F est l'événement le plus lu de Wall Street, l'edge
  d'une stratégie de copie est mince-à-nul après le délai de publication
  (consensus académique, non mesuré pour Tik). *Réactivation possible
  uniquement comme overlay MACRO de contexte (poids faible), et seulement
  après que l'engine macro existe ET un edge soit mesuré — on en est
  loin.*
- **Leaderboards de "bons traders" / copy-trading** (eToro popular
  investors, Myfxbook, Collective2, finfluencers) comme source (analyse
  utilisatrice 2026-05-25) → (a) **biais du survivant** : "bon score"
  passé ≠ pouvoir prédictif, les classements sont dominés par des chanceux
  à forte variance ; (b) **gameable/adversarial** : classements manipulés,
  vendeurs de signaux incités à pumper ; (c) **pas de vérité-terrain
  vérifiable** → impossible de scorer une crédibilité honnête (viole le
  principe OSINT preuve+source+crédibilité de Tik, section 6 paranoïa
  contrôlée) ; (d) **réflexivité/circularité** : ces traders suivent
  eux-mêmes news/sentiment → ce serait une copie bruitée et en retard de
  signaux que Tik ingère déjà (pas indépendant) ; (e) **légal/ToS** :
  scraping souvent interdit, parfois payant. La seule variante défendable
  (smart money on-chain crypto) est déjà couverte/refusée : Arkham =
  doublon Whale Alert (V1.5), Nansen "smart money" = payant.

> **Point transversal (paranoïa contrôlée).** Ces deux idées partagent
> l'angle mort récurrent du projet : croire que *plus de sources = plus
> d'edge*. C'est faux (ADR-018 : empiler des sources tend à converger vers
> neutre/bruit). Le vrai problème de Tik n'est pas un manque de sources
> mais l'**absence d'edge directionnel démontré** (colinéaire à la
> tendance, perd vs Always SHORT — cf. go/no-go 27/05). Aucune des deux
> sources ne corrige ça ; elles l'enterrent sous du volume. Si l'envie
> "suivre l'argent intelligent" persiste, la **seule** piste saine est les
> **flux ETF quotidiens** (V1.2/V1.3), en shadow, après le go/no-go, une
> source à la fois.

Une instance Claude future qui voudrait réactiver l'un de ces refus
doit d'abord fournir un argumentaire écrit chiffré ET valider l'ajout
de la justification dans ce fichier.

---

## Checklist réévaluation J+44 (2026-06-30)

À remplir à la date de réévaluation par la session Claude qui pilote
cette revue.

```
Vague 1 — état :
[ ] Combien de sources codées : ___ / 5
[ ] Lesquelles : _________________
[ ] Depuis quand chacune (date première mesure) : _________________

Pour chaque source codée — produit-elle des signaux exploitables ?
[ ] V1.1 Silver : IC Spearman = ___ , hit rate = ___ %, coverage = ___ %
[ ] V1.2 WGC GLD : IC Spearman = ___ , hit rate = ___ %, coverage = ___ %
[ ] V1.3 Farside BTC : IC Spearman = ___ , hit rate = ___ %, coverage = ___ %
[ ] V1.4 CoinGlass : IC Spearman = ___ , hit rate = ___ %, coverage = ___ %
[ ] V1.5 Whale Alert : IC Spearman = ___ , hit rate = ___ %, coverage = ___ %

Trading journal accumulé :
[ ] Nombre de trades documentés depuis J+14 : ___
[ ] Hit rate trader manuelle (signaux suivis) : ___ %
[ ] Manques récurrents identifiés (3 max) : _________________

Vague 2 — décision conditionnelle :
[ ] Détection d'anomalies : manque récurrent confirmé ? oui / non
[ ] Régime marché : bot futur en a-t-il demandé ? oui / non
[ ] Stress systémique : période bear/range observée ? oui / non
[ ] GDELT réactivation : régime de marché a-t-il changé ? oui / non
[ ] Comportemental : signaux narratif insuffisants ? oui / non

→ Coder en Vague 2 UNIQUEMENT les sources dont le manque est mesuré.
→ Documenter chaque décision (coder ou skip) avec 3 lignes
  d'argumentaire dans CLAUDE.md.
```

---

## Historique des modifications

- **2026-05-17** : création du fichier suite à demande utilisatrice
  post-audit UX. Vague 1 cadrée (Silver en entité tradable, EUR/USD
  reporté Vague 3 ou réactivable si demande utilisatrice). Engagements
  méthodologiques rappelés. Date réévaluation J+44 fixée.
- **2026-05-24** : V1.3 (flux ETF BTC) — section « Arbitrage de source »
  ajoutée (tableau pour/contre 5 sources) suite à vérification empirique.
  **Découverte** : l'API REST propre de DefiLlama (`/etfs/flows`) est
  Pro/payante (300 $/mois), pas gratuite → exclue par défaut (règle
  no-budget §7). Mea culpa d'une session précédente qui l'avait annoncée
  gratuite. **Verdict** : par défaut, principale = dashboard à JSON interne
  gratuit (SoSoValue ou CoinGlass free tier, arbitré au codage), Farside =
  vérification croisée seulement (403 anti-bot vérifié, fragile),
  CoinShares = fallback hebdo. DefiLlama-principale réservée au cas où un
  budget 300 $/mois serait validé. **Aucun code écrit** (enrôlement gaté
  post go/no-go 27/05 + après V1.2). Origine : analyse des MCP « smart
  money » d'un lien tiers (Polygon/Unusual Whales/SEC EDGAR/Alpaca/Tradier,
  tous rejetés pour TIK) qui a relancé la question des flux ETF BTC.
- **2026-05-25** : ajout au REFUSÉ INDÉFINIMENT de deux sources évaluées à
  la demande de l'utilisatrice (analyse pour/contre/verdict) — **13F
  institutionnels** (horizon/scope incompatibles + dominés par les flux
  ETF quotidiens V1.2/V1.3 + alpha digéré) et **leaderboards de "bons
  traders"** (biais du survivant + gameable + pas de vérité-terrain + ToS
  + réflexivité). Verdict : non pour Tik. Point transversal rappelé :
  aucune ne corrige l'absence d'edge directionnel ; "plus de sources ≠
  plus d'edge" (ADR-018). Si "smart money" souhaité → passer par les flux
  ETF (V1.2/V1.3), en shadow, après le go/no-go du 27/05, une à la fois.
  Aucun code écrit.
