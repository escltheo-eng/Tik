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

**Statut** : ✅ **COLLECTE SHADOW LIVE depuis 2026-06-03 (ADR-024, Paquet 52)**.
Ingester `btc_etf_flows_ingester.py` + `measure_btc_etf_flows.py` + `SourceSpec`
santé livrés. **Aucun overlay branché** (shadow strict, comme ADR-023 dérivés) :
zéro ligne dans les moteurs, signaux inchangés. Source tranchée au codage (cf.
verdict ci-dessous) = **SoSoValue openapi v2 `us-btc-spot`, sans clé** (Farside
reste 403, CoinGlass payant). 300 j de backfill immédiat. Mesure ~2026-06-17
(≥ 2 sem) AVANT tout enrôlement directionnel. NO-GO directionnel inchangé.

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
| **CoinGlass** ETF | API **clé obligatoire**, **AUCUN free tier** (vérifié 2026-05-27) | 🔴 min **29 $/mois** (HOBBYIST) | quotidien | Moyenne-haute | ❌ Payant → **exclu par défaut** (§7 no-budget) |
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
   DefiLlama. ~~ni CoinGlass free tier~~ (**MAJ 2026-05-27 : CoinGlass n'a
   AUCUN free tier, cf. V1.4 corrigé** → exclu sans budget). → **principale =
   SoSoValue** (JSON interne, à vérifier au moment du codage), **vérification
   croisée = Farside (scrape) + CoinShares (hebdo)**. Farside reste cantonné
   au recoupement, jamais pilier.
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

### V1.4 — CoinGlass (OI, funding, liquidations BTC) — 🔴 GELÉ (payant, pas de free tier)

**Statut** : ~~couche structurée OSINT, overlay swing BTC~~ → **GELÉ par défaut**
(violation §7 no-budget). À réactiver uniquement si budget payant validé.

**Justification structurelle (inchangée)** : détection baleines indirecte via
positionnement dérivés (OI agrégé, funding rates extrêmes, liquidations
massives).

**⚠️ Vérification empirique 2026-05-27 (curl VPS + page pricing) — la prémisse
« free tier » du backlog était FAUSSE (mea culpa)** :
- `curl` sans clé sur tous les endpoints (`open-api-v4`, `open-api-v3`,
  `open-api.coinglass.com/public/v2/open_interest` et `/funding`) →
  **`"API key missing"`** systématique. Aucun accès anonyme.
- Page pricing (coinglass.com/pricing) : **AUCUN plan gratuit**. 5 tiers
  payants : HOBBYIST **29 $/mois** (80+ endpoints, 30 req/min) · STARTUP
  79 $ · STANDARD 299 $ · PROFESSIONAL 699 $ · ENTERPRISE custom. Le
  découpage par tier des métriques (OI/funding/liq) **n'est pas détaillé**
  sur la page (sans objet puisque payant de toute façon).
- **Donc l'ancienne ligne « Free tier : OI agrégé… Bon. » est invalidée.**

**Plan d'action (révisé)** :
1. **Par défaut : NE PAS coder** (pas de budget validé, cf. CLAUDE.md §7).
2. Si la trader valide un jour un budget (≥ 29 $/mois) ET qu'un edge dérivés
   est plausible → **auditer le contenu exact du tier HOBBYIST** (les 80+
   endpoints incluent-ils OI/funding/liquidations BTC agrégés ?) avant de payer.
3. Sinon → reporter indéfiniment.

**Effort estimé** : n/a tant que gelé.

**Non bloquant pour V1.5** : la séquence Vague 1 saute V1.4 par défaut.

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

**À coder APRÈS V1.4** (mesure 2 semaines V1.4 d'abord — **mais V1.4 est gelé
par défaut**, cf. ci-dessus, donc en pratique V1.5 vient après V1.3).

---

### V1.6 (candidat) — Surprise macro gratuite (FRED proxy + ForexFactory)

**Statut** : candidat **identifié et vérifié 2026-05-27**, **collecte shadow
démarrée** (ForexFactory), **non enrôlé**. PAS un overlay directionnel
(NO-GO go/no-go 27/05) — angle = **enrichir le calendrier macro existant**
(ADR-017/020) avec la magnitude de surprise, comme couche de **contexte**.

**Vérification empirique 2026-05-27 (curl VPS, read-only)** :

| Source | Gratuit sans clé payante ? | Données | Verdict |
|---|---|---|---|
| **FRED** (`PAYEMS`, `CPIAUCSL`, `PCEPILFE`…) | ✅ clé FRED gratuite (déjà en `.env`) | **actuel** + précédent. Pas de consensus. Actual historique, non périssable (re-vérifié 27/05 : PAYEMS/CPIAUCSL répondent) | **fournit l'`actual`** du montage surprise |
| **ForexFactory** (`nfs.faireconomy.media/ff_calendar_thisweek.json`) | ✅ aucune clé, HTTP 200, JSON propre ~13 KB | `forecast` (**vrai consensus**) + `previous` + `impact`/title/country/date. **PAS de champ `actual`** (corrigé 27/05). 96 events/sem, 51 avec forecast, inclut US | **fournit le `consensus`** (périssable, rolling-week) |
| Trading Economics `guest:guest` | 🔴 compte invité **supprimé** (HTTP 410) | n/a | mort |

> **⚠ CORRECTION 2026-05-27 (vérifiée curl VPS, read-only — mea culpa).** La
> version précédente de ce tableau affirmait que ForexFactory porte un champ
> `actual` → « vraie surprise = actual − forecast ». **C'est FAUX** : le feed
> `thisweek` (seul à répondre 200 ; lastweek/nextweek/thismonth = 404) n'expose
> que `title/country/date/impact/forecast/previous`, **jamais `actual`** (32/32
> events passés constatés à `actual` absent, sur 5 snapshots ET sur le feed live).
> La surprise n'est donc PAS calculable depuis ForexFactory seul.
>
> **Montage correct (complémentarité)** : `surprise = actual_FRED − forecast_FF`.
> - FF apporte le **consensus** (`forecast`), introuvable dans FRED, et
>   **périssable** (rolling-week) → c'est ce que l'archiveur shadow préserve.
> - FRED apporte l'**actual** (historique, non périssable, récupérable à la
>   mesure) — avec conversion d'unités par type d'event (PAYEMS niveau→variation
>   mensuelle, CPI/PCE indice→% m/m, GDP→% annualisé q/q, taux→niveau).
>   **Couverture US uniquement** (les events non-US du feed n'ont pas d'actual FRED).
> - **1ʳᵉ validation possible** : Core PCE Price Index m/m (F=0,3 %) + Prelim GDP
>   q/q (F=2,0 %), tous deux **release 2026-05-28** → leur consensus est archivé
>   dès maintenant, l'actual FRED suivra → premier point de surprise US mesurable.

**Pourquoi archiver ForexFactory DÈS MAINTENANT (shadow)** : le feed est
**rolling-week** (semaine glissante seulement) → impossible de récupérer
l'historique a posteriori. Pour pouvoir backtester la surprise plus tard
(IC Spearman surprise ↔ delta prix futur), il faut **accumuler les snapshots
dans le temps**. D'où le script standalone livré 2026-05-27 :
`core/src/tik_core/scripts/archive_forexfactory.py` (collecte vers
`core/data/forexfactory_archive/snapshots.jsonl`, **NON wiré dans
`run_ingesters.py`**, **zéro impact `combined_bias`**). **Cron DÉJÀ ACTIF** côté
VPS (crontab root, toutes les 2 h, dedup) pour préserver le `forecast`
(consensus) au fil de la semaine + ses révisions. (Pas pour capter un `actual` :
ce feed n'en a pas — cf. correction ci-dessus ; l'actual viendra de FRED à la
mesure.)

**Limites connues** :
1. **Le feed n'a pas d'`actual`** (corrigé 27/05) → la surprise exige un join
   FRED par type d'event, avec conversion d'unités (le morceau de complexité réel,
   géré dans `measure_forexfactory_surprise.py` livré 28/05, à valider event par
   event au fil des releases).
2. Feed **non officiel** (mirror faireconomy de ForexFactory) → peut casser ;
   prévoir un fallback si 403/timeout persistants.
3. Fuseau horaire du champ `date` : format observé `2026-05-28T08:30:00-04:00`
   (offset explicite -04:00 = ET) → `datetime.fromisoformat` le parse en aware,
   pas de piège Bug 8 tant qu'on garde l'aware (ne PAS stripper la tz). À
   re-confirmer à l'inter-saison DST.
4. **Sparse** : quelques events HIGH US/semaine → couche rare par nature.
5. Join US-only : les events non-US du feed (AUD/NZD/GBP/EUR/JPY/CAD/CHF/CNY)
   n'ont pas d'`actual` FRED → surprise calculable seulement pour les events US
   mappés (NFP, CPI, Core CPI, PCE, GDP, retail sales…).

**Instrument de mesure livré 2026-05-28** : `core/src/tik_core/scripts/
measure_forexfactory_surprise.py` (lecture seule, calqué sur `measure_polymarket.py`).
Joint le consensus archivé (FF) aux actuals FRED → `surprise = actual − forecast`
par event US, puis mesure IC Spearman / hit de signe / gain sur BTC à 1 h / 6 h /
24 h. Helpers déterministes testés (`core/tests/test_measure_forexfactory_surprise.py`,
47 tests : parsing consensus, mapping titre→FRED, période de référence
mensuelle/trimestrielle, conversions d'unités vérifiées contre valeurs FRED réelles).
Mapping US (`US_EVENT_MAP`) : Core/PCE, CPI/Core CPI (m/m + y/y), NFP, Unemployment
Rate, Avg Hourly Earnings, Retail Sales, PPI, Personal Income/Spending, GDP q/q —
**series_id tous vérifiés actifs**. Garde-fou `actual` PENDING : si FRED n'a pas
encore publié la période de référence, on NE fabrique PAS de surprise (pas de faux
positif à partir du mois précédent).

> **Validation runtime 2026-05-28** : Prelim GDP q/q → `actual=2.000` (FRED Q1)
> vs forecast 2,0 % → `surprise=+0,000` (pipeline end-to-end validé). Core PCE /
> Personal Income / Spending → `PENDING` (FRED n'a pas encore avril). 0 paire mûre
> (events release du jour, horizon prix non écoulé) → verdict « non concluant,
> attendu au démarrage ». **1ʳᵉ surprise US réellement mesurable** dès que FRED
> publie les actuals d'avril (Core PCE attendu fin mai/début juin). Lancer :
> `docker exec tik-core python -m tik_core.scripts.measure_forexfactory_surprise`.

**Pré-enrôlement** : comme toute source, **après** mesure ≥ 2 sem de la valeur
prédictive propre (IC / hit / gain via `paired_gain_significance`) + régime
mixte + ADR. Et **seulement** comme couche de contexte tant que le go/no-go
directionnel reste NO-GO.

---

### V1.7 (candidat) — Dérivés BTC : funding rate + open interest (Binance Futures gratuit)

**Statut** : candidat **identifié et vérifié 2026-06-01** (curl VPS read-only),
**aucun code écrit**, **non collecté**. Origine : analyse d'une liste « edge OSINT »
proposée par ChatGPT à l'utilisatrice (points « contrarian score », « douleur
maximale / short squeeze », « dérivés CoinGlass/Coinalyze »). C'est le **seul
candidat de cette liste à la fois neuf, gratuit, pertinent BTC et “argent
réellement engagé”** (comme Polymarket — pas du sentiment éditorial).

**Vérification empirique 2026-06-01 (curl VPS, read-only) — la prémisse
« dérivés = payant » (CoinGlass V1.4, Coinalyze) ne tient PAS pour funding + OI** :

| Source | Accès sans clé ? | Données | Verdict |
|---|---|---|---|
| **Binance Futures** `fapi/v1/premiumIndex` | ✅ **HTTP 200, aucune clé** | `lastFundingRate` (funding actuel) + mark/index price | **funding gratuit** |
| **Binance Futures** `fapi/v1/openInterest` | ✅ **HTTP 200, aucune clé** | open interest BTCUSDT perp | **OI gratuit** |
| **Binance Futures** `fapi/v1/fundingRate` (historique) | ✅ public documenté | historique funding (backtest IC sur 6-12 mois possible) | **calibration possible** |
| Coinalyze `v1/funding-rate` | 🔴 **HTTP 401** « Invalid/Missing API key » | n/a | clé obligatoire → exclu anonyme |
| CoinGlass | 🔴 aucun free tier (cf. V1.4) | n/a | gelé payant |

> **Note importante** : Binance Futures donne **funding + OI** gratuitement, mais
> **PAS** les liquidations agrégées multi-exchange (heatmaps de liquidité), qui
> restent payantes (CoinGlass). Le `forceOrders` Binance exige une clé et ne
> couvre qu'un exchange. Donc V1.7 = funding + OI seulement, pas le module complet
> « market structure / liquidation heatmap » de la liste ChatGPT.

**Justification structurelle** : (a) **même fournisseur déjà intégré** (Tik utilise
déjà Binance spot pour klines/orderbook/aggTrades) → coût d'intégration faible ;
(b) signal de **positionnement réel des traders à effet de levier**, indépendant de
nos overlays news/sentiment → vraie diversification d'angle (pas un doublon
éditorial) ; (c) angle **contrarian crédible** : funding fortement positif + OI
euphorique = excès de longs à effet de levier = risque de squeeze baissier (et
inversement). C'est le mécanisme « douleur maximale » de la liste ChatGPT.

**Stack technique attendu** :
- Ingester `binance_derivatives_ingester.py` : polling court (funding évolue en
  continu, OI bouge intra-day — à calibrer, ~5-15 min). Stocke funding + OI dans
  Redis (clé explicite, NON ramassée par les engines tant qu'aucun
  `_enrich_with_*` n'est câblé — cohérent règle SHADOW).
- Overlay futur (si enrôlé) : `_enrich_with_derivatives` dans `analyze_swing_btc`
  (contrarian sur extrêmes : funding/OI extrêmes → bias inverse au positionnement
  de la foule). **Mapping à calibrer empiriquement** sur historique `fundingRate`
  6-12 mois (méthodo Paquet 19 P2 : IC Spearman + hit rate par palier).
- Pas de version GOLD (Binance Futures = crypto uniquement ; Gold n'a pas de
  funding/OI équivalent gratuit).

**Effort estimé** : ~3-5 h backend (ingester + Redis + tests), + ~1-2 h
calibration historique avant tout enrôlement directionnel.

**Hypothèses causales à valider** (avant enrôlement) :
1. Le funding extrême (top/bottom décile sur 6-12 mois) anticipe-t-il un
   retournement BTC sur 5-30 j (IC Spearman significatif, signe contrarian) ?
2. L'OI en euphorie (pic vs baseline) combiné à un funding extrême améliore-t-il
   le tri vs funding seul ?
3. Le signal dérivés est-il **indépendant** de nos overlays existants (FG, news)
   ou redondant ? (corrélation des bias — si redondant avec FG contrarian, faible
   apport, cf. risque mesuré pour CoinGecko shadow).

**Marqueurs de réussite à 2 semaines** : IC Spearman ≥ 0.10 sur 6-12 mois
historique, hit rate des cas extrêmes (|bias|=1.0) > 50 %, coverage raisonnable
(funding extrême est rare par nature → couche d'alerte, pas signal permanent).

**File d'attente (discipline “une source à la fois”)** : V1.7 vient **après** la
mesure des 3 shadows déjà en cours — Polymarket (~2026-06-10), CoinGecko
(~2026-06-11), surprise macro ForexFactory. **Aucune collecte ne démarre tant
qu'un shadow en cours n'est pas mesuré.** Et comme toujours : SHADOW d'abord,
ENRÔLEMENT directionnel **seulement après** mesure ≥ 2 sem (IC / hit / gain) +
régime mixte + ADR, et **jamais** tant que le go/no-go directionnel reste NO-GO
(dans ce cas → carte de contexte dashboard, pas overlay du bias).

**Limites connues** :
1. **BTC uniquement** (rien pour Gold) → n'aide pas le trou directionnel GOLD.
2. **Funding extrême ≠ timing** : signale un risque de squeeze, pas le moment exact.
3. **Liquidations agrégées non couvertes** (payant CoinGlass) → pas le module
   « heatmap de liquidité » complet de la liste ChatGPT, seulement funding + OI.
4. **Risque de redondance avec Fear & Greed** (les deux captent l'excès de la
   foule) → à mesurer (corrélation des bias) avant d'enrôler, sinon volume sans edge.

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
- **2026-05-27** : go/no-go officiel J+10 exécuté (`go_no_go_report.sh`,
  N=396 swing BTC mûrs 5j) → **NO-GO directionnel** : Tik perd vs « toujours
  short » sur le gain à tous horizons (Δ −0,50 % à 5j, z=−8,2, p<0,001),
  régime baissier unique (BTC −4,25 %). Tik = outil de **contexte**, pas
  oracle directionnel. **Spikes de vérification sources gratuites (curl VPS)** :
  (a) **correction V1.4** — CoinGlass n'a **AUCUN free tier** (min 29 $/mois,
  `"API key missing"` sans clé) : la prémisse « free tier » du backlog était
  fausse (mea culpa), V1.4 **gelé** par défaut ; (b) **Whale Alert** confirmé
  **payant** (pas de free API : Custom Alerts 29,95 $/mois min $100k, REST
  699 $/mois — cohérent V1.5 paywall) ; (c) **ForexFactory faireconomy**
  validé comme **meilleure source surprise gratuite** (forecast=consensus +
  actual, sans clé) → nouvelle entrée **V1.6 (candidat)** + **archiveur shadow
  livré** (`archive_forexfactory.py`, non wiré) ; (d) FRED surprise-proxy
  validé mais faible (momentum + retardé). **Aucun enrôlement** (gaté
  post-mesure 2 sem + NO-GO actuel). Polymarket (shadow depuis 24/05) reste
  à mesurer EN PREMIER (une source à la fois).
- **2026-05-27 (suite, audit data-quality du shadow ForexFactory)** : audit du
  cron déjà actif + des 5 snapshots accumulés → **découverte : le feed `thisweek`
  n'a AUCUN champ `actual`** (clés réelles = title/country/date/impact/forecast/
  previous ; 32/32 events passés à `actual` absent ; lastweek/nextweek/thismonth
  = 404). La ligne V1.6 (c) du 27/05 ci-dessus disait « forecast=consensus +
  actual » → **FAUX, corrigé** (mea culpa, prémisse jamais vérifiée par les
  sessions précédentes). **Impact** : la collecte reste saine (elle préserve le
  consensus, qui est la partie périssable rolling-week), mais la surprise n'est
  PAS calculable depuis FF seul. **Montage correct figé** : `surprise =
  actual_FRED − forecast_FF` (FRED re-vérifié 27/05 : fournit l'actual historique,
  US-only, conversion d'unités par event). Docstring `archive_forexfactory.py` +
  tableau/limites V1.6 corrigés. **Détecté à J+1,5 de collecte** (vs au 2026-06-10)
  → 2 semaines d'archivage du consensus PAS perdues + futur `measure_forexfactory_
  surprise.py` cadré sur la bonne mécanique. Limite Bug-8 (#2 d'avant) **levée** :
  le champ `date` a un offset explicite `-04:00` → parse aware, pas de piège tant
  qu'on garde la tz. 1ʳᵉ surprise US validable : Core PCE + Prelim GDP (release
  2026-05-28). Aucun code de pipeline touché ; doc/memory seulement.
- **2026-05-28 (instrument de mesure surprise livré)** : nouveau script lecture
  seule `core/src/tik_core/scripts/measure_forexfactory_surprise.py` (calqué sur
  `measure_polymarket.py`) — joint le consensus FF archivé aux actuals FRED
  (`surprise = actual − forecast`, conversion d'unités par event), mesure IC
  Spearman / hit / gain sur BTC à 1 h / 6 h / 24 h, garde-fou `actual` PENDING
  (pas de surprise fabriquée tant que FRED n'a pas publié). `US_EVENT_MAP` :
  Core/PCE, CPI, Core CPI (m/m + y/y), NFP, Unemployment Rate, Avg Hourly Earnings,
  Retail Sales, PPI, Personal Income/Spending, GDP q/q — series_id tous vérifiés
  actifs (curl FRED). **47 tests purs** (parsing, période réf, conversions vs
  valeurs FRED réelles) → suite **1159 → 1206 verts** (tik_test, jamais la prod),
  ruff propre (config repo). **Validé runtime** : Prelim GDP surprise +0,000 (FRED
  Q1=2,0 vs forecast 2,0 %) ; Core PCE/Income/Spending PENDING ; 0 paire mûre
  (events du jour) → « non concluant, attendu ». 1ʳᵉ mesure réelle quand FRED
  publie avril (Core PCE fin mai/début juin) ; mesure ≥ 2 sem avant tout verdict.
  **Zéro impact pipeline / signaux / `combined_bias`** (lecture seule, SHADOW).
  Aucun enrôlement (NO-GO inchangé).
- **2026-06-01 (candidat V1.7 — dérivés Binance funding + OI)** : ajout entrée
  V1.7 suite à analyse d'une liste « edge OSINT » proposée par ChatGPT à
  l'utilisatrice. Tri complet de la liste fait (cf. réponse Claude) : la plupart
  des points sont soit **déjà dans Tik** (OBI/CVD flash, contrarian score =
  cross-validation ADR-004/011), soit **payants/refusés** (Glassnode/Nansen/
  Arkham/CoinGlass/Coinalyze, Twitter), soit **hors-scope BTC-Gold** (GitHub/
  recrutements/projets = pertinent altcoins seulement). **2 points retenus** :
  (1) **dérivés funding + OI** → V1.7, vérifié gratuit chez Binance Futures
  (`premiumIndex` + `openInterest`, HTTP 200 sans clé ; Coinalyze 401, CoinGlass
  payant) → seul candidat neuf/gratuit/BTC/« argent engagé » ; (2) **régimes de
  marché** (savoir QUAND ignorer un signal) → déjà en Vague 2, c'est l'idée qui
  vise notre vraie faiblesse (colinéarité au trend, NO-GO 27/05) plutôt que
  d'empiler du volume. **Aucun code écrit.** V1.7 en file après les 3 shadows en
  cours (Polymarket/CoinGecko/ForexFactory), une source à la fois. Rappel
  transversal : « + de sources ≠ + d'edge » — V1.7 ne corrige PAS l'absence
  d'edge directionnel, il faut le mesurer (IC/hit/gain) avant tout enrôlement.
