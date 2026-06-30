# CLAUDE.md — Contexte projet Tik

> **Ce fichier est lu automatiquement par toute instance Claude qui ouvre ce projet.**
> Si tu es une instance Claude lisant ceci pour la première fois : **lis-le entièrement avant de répondre à la moindre question**. Il contient l'historique, les décisions, les règles et l'état d'avancement du projet.

---

## 0. Identification de l'utilisateur

L'utilisateur principal du projet **n'a jamais codé de sa vie** avant de démarrer Tik. Il a appris à utiliser Git, Docker, le terminal, et VS Code en quelques jours pour les besoins du projet.

**Implications pour toute instance Claude qui interagit avec lui** :

- **Explique tout en français** et avec un vocabulaire accessible (pas de jargon non défini)
- **Ne suppose jamais qu'il connaît un concept technique** (variables, types, scopes, async, hypertable, foreign key, etc.) — explique brièvement quand tu l'utilises
- **Donne les commandes complètes** à copier-coller, jamais juste "tape la commande habituelle"
- **Indique précisément où il est** (quel dossier, quelle app, quel onglet) avant chaque instruction
- **Découpe les tâches en étapes courtes** (1 → 2 → 3) plutôt que de tout balancer d'un bloc
- **Vérifie son état actuel** avant d'avancer (lui demander où il en est, s'il a bien compris, s'il voit ce que tu décris)
- **Sois patient avec les erreurs** — il copie-colle ce que tu lui donnes, donc une faute d'indentation ou un fichier mal placé vient probablement de toi
- **Pour les corrections de fichiers Python**, fournis-lui le **fichier complet à remplacer** plutôt qu'un diff partiel — il n'a pas le réflexe d'identifier les indentations correctes
- **Quand il te colle un message d'erreur**, ne suppose pas qu'il l'a lu/compris — analyse-le toi-même et explique ce qui se passe en français simple
- **Ne lui propose pas d'installer des outils complexes** (Homebrew, Xcode Command Line Tools) sauf nécessité absolue — préfère les solutions natives macOS ou les contournements

---

## 1. Vision du projet Tik

**Tik n'est PAS un acronyme.** C'est un nom propre.

**Tik est une plateforme OSINT modulaire** (Open Source INTelligence) qui :
- Agrège des données multi-sources (marché, macro, news, on-chain, sentiment, prédictif)
- Score la crédibilité des sources et détecte les fake news
- Produit des signaux pondérés sur 3 horizons en parallèle (flash, swing, macro)
- Historise tout pour analyse et recalibrage continu
- S'expose via une API + WebSocket pour des bots clients

**Périmètre actuel (MVP)** : trading BTC + Gold uniquement.
**Périmètre futur** : domain-agnostic — sport betting, politique, météo-finance, tout système décisionnel ayant besoin d'OSINT + scoring.

---

## 2. Architecture en 3 couches

```
┌────────────────────────────────────────────┐
│  COUCHE 1 — CORE ENGINE (FastAPI central)  │
│  Source de vérité unique, un déploiement    │
└────────────────────────────────────────────┘
              ▲ HTTP + WebSocket
              │
┌────────────────────────────────────────────┐
│  COUCHE 2 — SDK Python (tik-sdk)            │
│  Package pip-installable, cache local,      │
│  fallback offline, hooks événementiels      │
└────────────────────────────────────────────┘
       ▲              ▲              ▲
       │              │              │
   ZETA bot       TOTEM bot     Bot futur
       │              │              │
┌────────────────────────────────────────────┐
│  COUCHE 3 — CONFIG YAML (par bot)           │
│  Adaptation sans redéploiement, hot-reload │
└────────────────────────────────────────────┘
```

L'**abstraction "Entity"** est ce qui permet la modularité multi-domaines : BTC, GOLD, mais aussi un match NBA, une élection, etc. — tous deviennent des "entities observables" avec leurs sources, horizons, et scoreurs.

---

## 3. Écosystème Zeta + Totem

**Zeta** (déjà en production) :
- Bot de trading déterministe Python FastAPI
- Trade BTC + Gold via MT5/ActivTrades, leverage 1:1000
- 29 routes API, 22 services, ~1192 lignes dans `api/main.py`
- Moteur principal : `cranial_bot/turbo_v2.py` (5211 lignes)
- Stratégies actives : H1 Adaptive (BTC + GOLD) + Weekend Scalp (BTC seul)
- **Guard pipeline V01-V15** dans `cranial_bot/micro_live_guard.py` (15 checks bloquants)
- `balance_service.py` = source de vérité financière (Decimal, invariant check)
- `kill_switch_service.py` = stop quotidien à 15% de drawdown

**Totem** (existant, archi séparée) :
- IA de trading autonome (ML/autonome)
- Stack propre, API propre
- À détailler ultérieurement

**Tik** (en construction) :
- Cerveau analytique OSINT en amont des deux bots
- Ne passe **JAMAIS** d'ordre lui-même
- Envoie à Zeta : signaux décisionnels (direction + confidence + veracity + contre-scénarios)
- Envoie à Totem : vecteurs de features ML enrichis

---

## 4. Décisions architecturales (ADR)

### ADR-001 — Authentification pluggable

L'auth est implémentée via une **interface abstraite `AuthProvider`** + un `AuthContext` neutre. Aujourd'hui : `ApiKeyProvider`. Demain (si l'utilisateur en a besoin) : `OAuth2Provider` à ajouter sans toucher au code métier des endpoints. Variable d'env : `TIK_AUTH_PROVIDER=api_key|oauth2`.

### ADR-002 — Monorepo

Structure unique `Tik/` avec sous-dossiers `core/`, `sdk/` (à venir), `dashboard/` (à venir), `docs/`. Solo dev, commits transverses fréquents → pas de polyrepo.

### ADR-003 — Intégration Zeta SANS bypass V01-V15

**Règle absolue** : tout signal Tik consommé par Zeta passe **intégralement** par le guard V01-V15 et le `risk_engine.py` existants. Tik est une **source d'edge additionnelle** pour `turbo_v2.py`, pas un canal d'exécution privilégié.

- Tik ne crée jamais d'ordre MT5 directement
- Un signal Tik **modifie** la `confidence` d'un signal Zeta interne, ne le **remplace** pas
- `risk_engine.py` calcule la taille, pas Tik (les `suggested_entry/stop/target` sont indicatifs)
- `kill_switch_service.py` est la **seule** voie pour Tik de freezer Zeta
- Un nouveau check **V16 optionnel** pourra être ajouté : "véracité globale Tik > seuil"

### ADR-004 — Architecture multi-overlay pour la cross-validation

Pattern **`_enrich_with_<source>(decision, data) -> bias | None`** dans `swing_engine.py` :

- Chaque source de sentiment / macro retourne un bias dans `[-1, +1]` (contrarian pour FG/DXY, trend-following pour news), n'altère **jamais directement la veracity**
- La fonction d'analyse principale (`analyze_swing_btc`, `analyze_swing_gold`) collecte tous les biais valides et calcule la veracity finale via `_veracity_from_concordance(direction_technique, moyenne_des_biais)`
- Sources contradictoires se neutralisent (moyenne tend vers 0 → veracity = 0.85)
- **Ajouter une source = 4 lignes dans `analyze_swing_xxx` + un nouveau helper**
- Moyenne arithmétique non pondérée (à réviser plus tard avec données de backtest)
- Implémentations actuelles : `_enrich_with_fear_greed` (BTC), `_enrich_with_cryptocompare` (BTC), `_enrich_with_dxy` (GOLD)

### ADR-005 — Flash engine (horizon minutes-heures sur BTC)

Nouveau fichier `core/src/tik_core/scoring/flash_engine.py`, séparé du swing, suivant le **même pattern multi-overlay** (ADR-004) mais adapté au court terme :

- **Source** : klines REST Binance interval 1m, 240 dernières bougies (4h glissante). Pas de modification de l'ingester WS existant.
- **Check fraîcheur** : avant chaque cycle, vérifie que `tik.last_price.BTC` (cache du flux WS) a moins de 60 s. Si stale → skip avec log warning.
- **Indicateurs** : EMA 9/21, RSI 14 (seuils 75/25), MACD 12/26/9, ATR 14, momentum 15m. Seuil de directionnalité 0.10 (vs 0.08 swing, plus strict pour limiter les whipsaws).
- **Overlays initiaux (2)** :
  - `_enrich_with_orderbook` : Order Book Imbalance top 20 niveaux via `GET /api/v3/depth` (trend-following).
  - `_enrich_with_aggression` : ratio buyer/seller taker sur les 1000 dernières aggTrades via `GET /api/v3/aggTrades` (trend-following).
- **Émission conditionnelle** : signal persisté + publié uniquement aux **transitions de direction** ou par **heartbeat 30 min**. Direction précédente stockée dans Redis sous `tik.flash.last_direction.BTC` (TTL 24h). Limite le volume DB (~10-50 signaux/jour estimés vs 288 en émission systématique).
- **Veracity dynamique** : mêmes paliers que swing (0.70 ↔ 0.95) via `_veracity_from_concordance`.
- **Pas de flash GOLD** : Yahoo a 15 min de délai, incompatible avec l'horizon flash.

Risques opérationnels rappelés dans l'ADR : Garde-fou 1 (mode shadow 3 mois) **strictement applicable** au flash ; ADR-003 (pas de bypass V01-V15) **inchangé** ; un futur débounce/throttle côté SDK sera nécessaire pour ne pas submerger `turbo_v2.py` de signaux flash quand on cablera Zeta — à documenter dans un futur ADR au moment de l'intégration.

### ADR-006 — NLP via Ollama pour le sentiment news (CryptoCompare)

Remplacement de l'analyse par mots-clés du ingester CryptoCompare par un **LLM local via Ollama** (par défaut `llama3.2:3b`, ~2 GB, hébergé sur le Mac de l'utilisateur en dehors de Docker), avec un **pattern Strategy** :

- Nouveau fichier `core/src/tik_core/aggregator/news_classifier.py` : interface abstraite `NewsClassifier` + `KeywordClassifier` (code historique migré) + `OllamaClassifier`. Sélection par variable d'env `TIK_NEWS_CLASSIFIER=ollama|keywords` (défaut ollama).
- Le `CryptoCompareIngester` reçoit son classifier au constructeur (DI), même esprit que ADR-001 (auth pluggable).
- **Fallback automatique** : `OllamaClassifier` possède un `KeywordClassifier` interne. Si Ollama plante sur un titre → fallback keywords pour ce titre. Si 3 erreurs successives dans le même batch → circuit breaker batch-level, on bascule keywords pour le reste du batch ; retentative au cycle suivant.
- **Au démarrage** : factory `build_news_classifier` ping `GET /api/tags` sur Ollama. Si OK + modèle listé → `OllamaClassifier`. Sinon → `KeywordClassifier` + log warning.
- **Traçabilité backtest** : chaque payload Redis porte `method: "ollama:llama3.2:3b"` ou `method: "keywords"`. Le backtest pourra à terme comparer le hit rate par méthode.
- **Pas de modification du score de crédibilité** `cryptocompare_news` (toujours 0.70 dans `SOURCE_SCORES`) : on attend la mesure quantitative via dataset golden avant de biaiser la veracity.

Risques rappelés : Garde-fou 1 (mode shadow 3 mois) **strictement applicable** ; ADR-003 (pas de bypass V01-V15) **inchangé** ; dépendance externe au Mac hôte (à reconsidérer au déploiement cloud) ; latence ~1 s/titre (acceptable au cycle horaire actuel).

---

## 5. Garde-fous opérationnels (validés par l'utilisateur)

### Garde-fou 1 — Mode SHADOW obligatoire (3 mois minimum)

Tik tourne en parallèle de Zeta sans jamais influencer ses trades. La connexion Zeta ne fait que **lire** (status, positions, PnL). Tik observe, produit des signaux, les loggue. Aucune influence sur les trades réels avant 3 mois minimum d'observation et d'analyse.

### Garde-fou 2 — Budget de test limité (Zeta automatisé)

Quand on passera de shadow à actif, démarrage avec un compte Zeta de test séparé contenant **au maximum 5% du capital**. Pendant 1 mois minimum.

### Garde-fou 2-bis — Sizing trading manuel J+14 (validé 2026-05-06)

**Le Garde-fou 2 (5%) ne s'applique PAS au trading manuel humain.** Pour le trading manuel qui démarre le 2026-05-14 (J+14), sizing différent et plus conservateur :

- **Démarrage : 1% du capital par trade**, pas 5%. Raison : le 5% est calibré pour Zeta automatisé qui passera par le guard V01-V15 + risk_engine + kill_switch ; en manuel il n'y a que le jugement de l'utilisatrice qui filtre. **De plus, le backtest 2026-05-05 a mesuré Tik à 22% hit BTC swing 5j vs Random 33% sur 156 signaux** — pas d'edge démontré à ce stade. Sizing 1% pendant 2 semaines minimum, montée progressive seulement après une **période profitable mesurable**.
- **Filtre veracity ≥ 0.85 sur swing TRANSITOIRE (au lieu de 0.90)** — amendement 2026-05-18 (cf. Paquet 27) : tant que **Reddit IP-bannie sur l'IP HP 204.168.220.47** (cf. Bug 11 section 9), Tik tourne avec **3/4 overlays sentiment BTC** (FG + CryptoCompare + Google News, sans Reddit). Conséquence : BTC swing veracity capée structurellement à 0.85-0.89 quand FG diverge contrarian des news (cas typique marché bear actuel) — mesure 9h post-fix N=2 : **0 % des 36 signaux BTC swing ne passent ≥ 0.90**. Donc le seuil 0.85 reste discriminant (rejette les signaux ≤ 0.79). **Critère retour au 0.90 strict** : (1) Reddit reconnecté ET (2) 7 jours stables post-réintégration ET (3) ≥ 30 signaux BTC swing à veracity ≥ 0.90 mesurés. **⚠ Amendement 2026-06-10 (audit veracity, cf. ADR-026)** : la mesure « 0.85-0.89 » datait du 2026-05-18 (FG modéré). Depuis ~le 2026-05-27, **FG est en peur extrême (≈9)** → son biais contrarian sature à **+1.0** face aux news strong-bearish (**−1.0**) → dispersion des sources maximale → **la veracity des shorts BTC swing est au plancher 0.70** (mesuré : 0.700 quasi tous les jours sur 14 j), PAS 0.85. **Conséquence concrète : le filtre ≥ 0.85 rejette actuellement TOUS les shorts BTC swing** — il tient la trader hors de BTC swing, ce qui est cohérent avec le NO-GO. La veracity 0.70 n'est PAS un bug à « remonter » : GOLD affiche 0.89 de veracity pour 4.8 % de hit → **veracity ≠ edge** (Axe #1). Détail + décision « différer/mesurer » dans ADR-026. **⚠ Amendement 2026-06-14 (audit fiabilité pipeline) — le régime a CHANGÉ depuis le 11/06** : CryptoCompare a décroché net (Bug 15, quota 265/100, à 0 depuis le 11/06) → BTC swing tourne désormais à **2/4 overlays** (FG + Google News seulement), PAS 3/4. Conséquence **mesurée sur 48h (192 signaux BTC swing)** : la direction atteignable a basculé de *short* vers *long* — **113 long / 79 neutral / 0 short**. Les long passent tous le filtre (veracity moy. 0.853), les neutral sont tous rejetés (0.780). Mécanisme vérifié sur un signal réel : FG=18 (peur extrême) → biais contrarian **+1 (long)** ; Google News +0.02 (neutre) → biais ≈ 0 ; CryptoCompare + Reddit absents → moyenne positive → **LONG**, sources pas en désaccord franc → veracity 0.85. **Donc deux affirmations ci-dessus sont périmées** : (a) « 3/4 overlays » → en réalité **2/4** depuis le 11/06 ; (b) « le filtre ≥ 0.85 rejette TOUS les shorts » → il n'y a **plus aucun short** à rejeter, le filtre laisse maintenant passer des **LONG** « FG achète-la-peur » sur 2 sources. ⚠ **Pour la trader** : la guidance « observer les SHORT ≥ 0.85 » (puce suivante) est **inapplicable en l'état** (0 short produit) ; ce qui passe le filtre = des LONG à veracity à peine 0.85 issus d'**une seule source dominante (FG)** — NE PAS les lire comme un signal d'achat (NO-GO directionnel intact). Réversible auto au retour de CryptoCompare (~reset quota 1er juillet).
- **NE PAS trader GOLD avec Tik à J+14** — amendement 2026-05-18 (cf. Paquet 27) : backtest 1j sur 83 signaux GOLD mesure **hit rate Tik 4.8 % vs Random 34.1 % vs Always SHORT 80.7 %** sur fenêtre 5j HP. Distribution direction GOLD = 60 long + 20 neutral + 3 short alors que marché GOLD baisse soutenue (Always SHORT à 80 % de hit). **Tik n'a pas d'edge directionnel GOLD** depuis l'amendement ADR-018 P2 (DXY+COT désactivés, GOLD a perdu 2 overlays directionnels sur 4). Pour trader GOLD à J+14, s'appuyer sur MT5 / analyse technique externe / jugement, **pas sur Tik**. À ré-évaluer post-période bear (cf. critère réactivation DXY/COT amendement ADR-018 P2 ET backlog #9 GDELT GOLD).
- **Observer prioritairement signaux SHORT BTC à haute veracity** — insight mesuré 2026-05-18 (cf. Paquet 27) : sur 263 signaux SHORT BTC backtestés 1j horizon, **hit rate 63.1 % vs gain moyen +0.72 % par signal**. C'est l'edge directionnel le plus crédible mesuré sur Tik à ce jour, mais **à valider post-fix bug N=2 stable (≥ 9-10 j de runtime ≥ 2026-05-27)**. Pas cristallisé comme règle stricte : si la trader voit un SHORT BTC veracity ≥ 0.85 (transitoire) avec triggers cohérents (RSI bearish, EMA20<EMA50, MACD négatif), c'est un setup à favoriser sur les LONG ou NEUTRAL. **⚠ CAVEAT 2026-05-20 (Paquet 33)** : le « 63 % » a été mesuré sur des **données pré-fix contaminées** (CryptoCompare manquant → cross-validation N=2 buggée — un swing 5j sur ces données donne 0,9 % de hit), donc **ne pas le présenter comme un edge fiable**. À ce jour, **aucun filtre n'a de valeur prédictive robuste démontrée** : le filtre AFN `ok` vs `degraded` semblait prometteur (37,8 % vs 19,6 % @6h) mais sous scrutin paranoïaque il est inconclusif (marginal après correction multiple-testing, redondant avec veracity ≥ 0,85, et l'avantage s'inverse sur le gain à 24h — cf. Paquet 33 Découverte n°4). Tout reste **à mesurer proprement le 2026-05-27** (swing 5j post-fix). Sizing 1 % d'autant plus justifié. **⚠ 2026-06-14 — cette puce est temporairement caduque** : depuis le 11/06 (perte de CryptoCompare, Bug 15), Tik ne produit **plus aucun SHORT BTC swing** (mesuré 48h : 0 short / 113 long / 79 neutral). Il n'y a donc rien à « observer en priorité » côté short tant que CryptoCompare n'est pas revenue. Cf. amendement 2026-06-14 puce précédente.
- **Discipline calendrier macro** (Lacune B Phase B1, ADR-017) : ne pas rentrer en swing dans les ±4h autour d'un event HIGH (FOMC, NFP, CPI). Si tu dois absolument trader autour d'un event, sizing divisé par 2 (0.5%). **Fenêtre J+14 → J+25 = 12 jours macro-calmes** confirmée runtime 2026-05-18 (premier event HIGH = NFP 2026-06-05).

**Toute instance Claude qui propose de lever ces garde-fous (1, 2, 2-bis) doit alerter l'utilisatrice explicitement et lui rappeler ces règles.**

---

## 6. Framework "paranoïa contrôlée"

Importé de la philosophie Zeta. Chaque signal Tik livre **systématiquement** :

1. Une **hypothèse** principale (le pourquoi du signal)
2. **Au moins 2 contre-scénarios** qui invalideraient le signal, avec leur probabilité estimée et leur "mitigation" (quoi surveiller)
3. **Des preuves** (evidence) avec source et score de crédibilité
4. **Des triggers** techniques avec leur poids dans la décision

C'est ce qui distingue Tik d'un bot naïf. À respecter dans toute évolution.

---

## 7. Stack technique

**Core engine** :
- Python 3.11 + FastAPI + Uvicorn
- PostgreSQL 16 + TimescaleDB (hypertable sur `signals`)
- Redis 7 (pub/sub + cache)
- SQLAlchemy 2 async + Alembic
- Pydantic 2
- structlog (logging)
- APScheduler (jobs périodiques)

**Hébergement actuel** : Mac local de l'utilisateur via Docker Desktop.

**APIs externes utilisées** (toutes freemium) :
- Binance WebSocket (BTC, gratuit illimité)
- Yahoo Finance (Gold, gratuit avec délai 15min OK)
- FRED API (macro, gratuit illimité, clé requise)
- Source futures : CoinGecko, CryptoPanic, Polymarket, Reddit, etc.

**Pas de budget API payant** (Polygon, Bloomberg, Kaiko) tant que l'utilisateur n'a pas validé.

---

## 8. État actuel (résumé)

> **L'historique détaillé des ~50 « Paquets » de développement (2026-04 → 2026-06) est archivé dans [`HISTORIQUE.md`](HISTORIQUE.md)** — il n'est plus chargé automatiquement à chaque session, pour alléger le contexte. Y aller pour le détail d'une livraison passée, d'un ADR, ou d'un bug résolu. Cette section ne garde que l'état courant durable.

### Ce qui tourne en production (VPS Hetzner `tik-server-1`, Docker)

- **Core FastAPI** : moteurs swing BTC/GOLD + flash BTC, **OSINT pur** (ADR-018 — la direction vient du `combined_bias` OSINT cross-validé ; les indicateurs techniques RSI/MACD/EMA sont calculés mais à **poids 0**, informatifs seulement). ~14 ingesters (Binance, Yahoo, FRED, **Macro Regime (ADR-028 net liquidity + ADR-030 régime de risque VIX/crédit)**, **Rate Probabilities (ADR-029, proba taux Fed FedWatch)**, Fear&Greed, CryptoCompare, Google News, Reddit, GDELT, CFTC COT, CoinGecko, Polymarket, **Stablecoins (ADR-031, DefiLlama, poudre sèche crypto)**, **Cross-asset (ADR-032, corrélations BTC↔actions/or/dollar Yahoo)**, calendriers macro FRED + multi-banques centrales). Anti-fake-news ADR-011 actif. Hypothèse LLM Ollama (swing uniquement, flash = template).
- **Dashboard Expo** (v0.5.x) : cockpit iPhone via Expo Go (Metro en tunnel ngrok sur le VPS), accès direct `IP:8200` + clé API.
- **Notifications Telegram** (Paquet 50) : briefing 3×/jour (06/13/20 UTC) + alertes choc prix BTC / macro imminent + récap on-demand via Claude.
- **Breaking-news alerting** (ADR-027, 2026-06-14) : ingester quasi temps réel (RSS BBC/Al Jazeera/Cointelegraph + Google News ciblé) qui capte les annonces **non programmées** pouvant bouger le BTC (Trump/géopol, Fed/taux, tarifs/sanctions, régulation crypto) → **alerte Telegram** (avec explication du mécanisme ↓/↑ par catégorie) **+ carte dashboard** « 🚨 Breaking » (onglet Marché). C'est de l'**alerting/contexte, PAS un overlay directionnel** (ne touche jamais le `combined_bias`, NO-GO inchangé). Toggle `TIK_BREAKING_NEWS_ENABLED` (ON en prod depuis le 2026-06-14). Déclenché par la perte trader sur l'accord Trump/Iran du 14/06.
- **Couche Macro Regime** (ADR-028, 2026-06-15) : chiffres macro **objectifs et datés** calculés depuis FRED (gratuit) — **Fed Net Liquidity** hebdo (`WALCL−TGA−RRP`) + **Liquidité mondiale** (Fed+ECB+BoJ convertis USD, carte dédiée) + label régime (expansion/contraction/neutral) + proba récession 12 m (NY Fed), taux réel 10Y, breakeven, pente courbe (2s10s/3m10y), conditions financières (NFCI). Endpoints `GET /api/v1/macro/regime` + `GET /api/v1/macro/cockpit` (agrégateur 1-appel : régime + snapshots shadow Polymarket/dérivés/ETF/COT + prochain event), **carte dashboard « Régime macro »** (onglet Marché). **CONTEXTE STRICT** : famille NON-sentiment, ne touche jamais `combined_bias`/veracity/direction (NO-GO inchangé), **zéro affirmation** (anti-« Lecture macro » supprimée le 30/05). Né de la recherche sur centralbank.watch/novex.trading (aucun n'a d'API → on reproduit leur menu via FRED). Détail + verdict sources : `docs/adr/028-macro-regime-layer.md` + mémoire `macro-regime-layer-adr028`.
- **Probabilités de taux Fed** (ADR-029, 2026-06-15) : le « flagship » de centralbank.watch reproduit gratuitement — proba **hausse/maintien/baisse par réunion FOMC** (méthodo CME FedWatch via la lib `pyfedwatch`), à partir des futures Fed Funds (ZQ) Yahoo + range FRED + dates FOMC Tik. Endpoint `GET /api/v1/macro/rate_probabilities` (+ dans le cockpit), **carte dashboard « Anticipations taux Fed »**. **CONTEXTE STRICT** : anticipation du marché, ne touche jamais `combined_bias`/veracity/direction. Intégration pyfedwatch délicate (deps cassées `pandas_datareader`/matplotlib → shim `_pyfedwatch_compat` + install `--no-deps` ; ancrage contrat expiré synthétisé ; `PAST_FOMC_DATES` à MAJ/an). Détail : `docs/adr/029-rate-probabilities-fedwatch.md` + mémoire `rate-probabilities-fedwatch-adr029`.
- **Régime de risque** (ADR-030, 2026-06-21) : thermomètre du stress de marché — **VIX** (`VIXCLS`) + **spreads de crédit** High Yield (`BAMLH0A0HYM2`) & Investment Grade (`BAMLC0A0CM`), depuis FRED (gratuit). Label `risk_state` (risk_on/neutral/risk_off) fondé sur le **rang centile sur 1 an** du VIX + HY (≥0.70 = stress, ≤0.30 = calme). **Pas de nouvel ingester/endpoint** : section `risk_regime` ajoutée au blob `tik.macro.regime` (DRY, l'ingester poll déjà FRED) → exposée via `/macro/regime` + `/macro/cockpit`, **carte dashboard « Régime de risque »** (page Macro cosmique). **CONTEXTE STRICT** : ne touche jamais `combined_bias`/veracity/direction (le macro ne prédit pas le BTC, mesuré 2026-06-19). Détail : `docs/adr/030-risk-regime-layer.md` + mémoire `risk-regime-layer-adr030`.
- **Masse de stablecoins** (ADR-031, 2026-06-21) : liquidité **crypto-native** — la « poudre sèche » (cash USD parqué sur les rails on-chain : USDT, USDC…), via **DefiLlama** (gratuit, sans clé). Niveau total (~313 Md$) + tendance `trend` (expansion/contraction/neutral, seuil ±0,5 %/30j) + z-score 90j + répartition top 5 (USDT 59 %, USDC 24 %). **Nouvel ingester** (source ≠ FRED) `tik.macro.stablecoins` → endpoint dédié `GET /api/v1/macro/stablecoins`, **carte dashboard « Stablecoins »** (page Macro cosmique). **CONTEXTE STRICT** : famille NON-sentiment, ne touche jamais `combined_bias`/veracity/direction (la liquidité ne prédit pas le BTC, mesuré 2026-06-19). 3e des familles macro de contexte. Détail : `docs/adr/031-stablecoins-layer.md` + mémoire `stablecoins-layer-adr031`.
- **Corrélations cross-asset** (ADR-032, 2026-06-22) : avec quoi le BTC **co-bouge** — actions (`^GSPC`/`^IXIC`), or (`GC=F`), dollar (`DX-Y.NYB`), via **Yahoo** (gratuit). Corrélation de Pearson des **rendements journaliers alignés** (BTC cote 7j/7, TradFi en semaine → alignement sur dates communes, piège résolu) sur ~30j + label `behavior` (risk_asset/digital_gold/decoupled/mixed). **Nouvel ingester** `tik.macro.cross_asset` → endpoint dédié `GET /api/v1/macro/cross_asset`, **carte dashboard « Corrélations »** (barres divergentes −1→+1, page Macro cosmique). **CONTEXTE STRICT** : une corrélation n'est NI prédiction NI causalité, ne touche jamais `combined_bias`/veracity/direction. 4e/dernière famille macro de contexte. Détail : `docs/adr/032-cross-asset-correlations.md` + mémoire `cross-asset-correlations-adr032`.
- **SDK Python (`sdk/`) : 🧊 GELÉ** (cf. [ADR-022](docs/adr/022-gel-couche-zeta-sdk.md)) — la couche Zeta n'est pas câblée et le trading est 100 % manuel. On n'y code **plus rien** jusqu'à un besoin réel. Code conservé intact (réversible, gel = zéro coût tant qu'on n'y touche pas).

### La vérité empirique (à ne jamais maquiller)

- **Go/no-go officiel 2026-05-27 = NO-GO directionnel.** Mesuré rigoureusement (fenêtres non chevauchantes, test apparié vs Always SHORT, pas Random) : Tik n'ajoute **pas d'alpha** au-dessus de la meilleure baseline de tendance — il est **colinéaire au trend** baissier. **Aucun edge de prédiction démontré.** Cf. mémoires `tik-empirical-state-2026-05-23`, `measurement-overlapping-returns`, `measurement-rigor-controls`.
- Conséquence assumée : **Tik = outil de contexte + discipline + alerting**, PAS un générateur de signaux directionnels fiables. Sizing 1 % (Garde-fou 2-bis), « observer ≠ parier ».
- **L'edge, s'il existe, vit dans des familles de données DIFFÉRENTES du sentiment.** Toutes les sources actuelles sont du *sentiment retardé* (Fear&Greed, news, Reddit, CoinGecko) — en moyenner davantage ne crée pas d'edge, ça le dilue. Familles à explorer, **gratuites** : (1) **marchés prédictifs** (Polymarket — argent en jeu, déjà en shadow), (2) **positionnement dérivés** Binance funding rate / open interest / liquidations (jamais codé, backlog `454416a`), (3) **flux on-chain / ETF** (Whale Alert, Farside). Ajout via le pattern overlay ADR-004 (`_enrich_with_<source>`). **Règle : mesurer chaque nouvelle source en shadow ≥ 2 semaines (IC / hit rate / gain apparié vs Always SHORT) AVANT tout enrôlement sur le `combined_bias`.**

### Shadows en cours (collectés en Redis, NON branchés aux moteurs)

- **Polymarket** BTC + GOLD (`tik.sentiment.polymarket.*`) — mesure prévue ~2026-06-10 (`measure_polymarket.py`).
- **CoinGecko sentiment** (toggle `TIK_COINGECKO_OVERLAY_ENABLED=False`) — candidat 4e overlay BTC suite ban Reddit, à mesurer vs Fear&Greed (risque de redondance).
- **Dérivés Binance BTC** (`tik.deriv.binance.*`, ADR-023) — funding / OI / long-short retail+top, 1re famille **non-sentiment**, mesure ~2026-06-17 (`measure_btc_derivatives.py`).
- **Flux ETF spot BTC** (`tik.etf.btc*`, ADR-024) — inflow/outflow net quotidien + détail par fonds via SoSoValue (sans clé), 2e famille **non-sentiment**, 300 j de backfill, mesure ~2026-06-17 (`measure_btc_etf_flows.py`).
- **Fusion macro+micro — couche « micro » ML (ADR-033, repo `btc-research-lab`)** : réunion de Tik (macro/OSINT) avec le labo quant `btc-research-lab` (micro : prédiction BTC ML/micro-structure), chemin **F2→F1**. Côté Tik : endpoint `POST /api/v1/signals/ingest` qui force `horizon="micro"` + `circuit_breaker_status="degraded"` (**SHADOW strict** — n'influence AUCUN moteur OSINT, NO-GO inchangé) + horizon `micro` filtrable + filtre « Micro » dans l'app (Signals). Côté labo : conteneur `micro` headless (`docker-compose.micro.yml`, DuckDB persisté) + pont `tik_bridge.py` (POST vers Tik, **toggle `TIK_MICRO_ENABLED` OFF par défaut**). **✅ ACTIVÉ EN PROD le 2026-06-24** : conteneur `micro` lancé sur le VPS (`/opt/btc-research-lab`, `docker compose -f docker-compose.micro.yml up -d --build`, `.env` avec `TIK_MICRO_ENABLED=1` + clé API `micro-bridge` scope `write:signals`), pont actif → **vrais signaux micro qui arrivent (modèles chauds), mesure shadow DÉMARRÉE**. Bug du pont fixé le même jour (`tik_bridge.py` appelait `dashboard.store` au lieu de `dashboard.get_store()`). **Fix UI livré** : un micro étant TOUJOURS `circuit_breaker_status=degraded` by-design, il ne doit PAS être affiché comme anti-fake-news « sources en désaccord » ni déclencher d'alerte « Fake news » → exclu via `horizon==='micro'` dans `stream.ts` + `cosmic-signal-row.tsx` + `signal-cosmique/[id].tsx` (PR escltheo #8 = `700d4c5a` ; commit prod Lolasiku `5c4927d`). Audit E2E + navigation complet réalisé le 2026-06-24 (front↔back sain ; liste de ~17 points NON bloquants restants : veracity micro = vernis Axe #1, micro jamais auto-résolu en watchlist + track-record 400, login défaut `localhost` trompeur sur mobile, pas de déconnexion auto sur clé 401, routes orphelines `bots`/`modal`/`signal/[id]`, etc.). Règle : **mesure shadow ≥ 2 semaines vs baselines AVANT tout enrôlement** → futur **ADR-034** (verdict edge). Détail : `docs/adr/033-fusion-macro-micro-backend-unique.md` + `btc-research-lab/FUSION.md`.

### Dates / état opérationnel

- **2026-06-30 — VERDICT « chasse à l'edge » (pré-ADR-034) : 3 familles non-sentiment mesurées rigoureusement → 3 ⚪.** Mesures shadow durcies (balayage multi-horizon + bande de bruit |IC| corrigée Bonferroni + test du *mécanisme* extrême + N **non chevauchant/indépendant** honnête) lancées sur le VPS : **(1) Dérivés Binance** (`measure_btc_derivatives.py`, 588 snap/24 j) → ⚪ ; seul fil vivant = L/S-ratio contrarian (6/6 Δ négatifs, *direction* prédite, mais |t| max 1,45 < 2,64 → **non significatif, sous-puissant**) → re-mesurer ~mi-août. `Spearman(L/S retail, L/S top)=0,988` → hypothèse « smart money diverge du retail » **MORTE**. **(2) Flux ETF** (`measure_btc_etf_flows.py`, 300 j backfill) → ⚪ **plus net** : tous IC dans le bruit + **mécanisme momentum flat** (quintile haut d'inflow ne bat pas le reste, Δ≈0) → l'effet n'est pas là (échantillon pourtant correct). **(3) Polymarket** (`measure_polymarket.py`, 37 events indépendants) → ⚪ et même **anti-prédictif** (hit 47,2 %, gain −0,105 % en suivant le signe ; signal médiane-implicite/spot faible par nature : marchés « above on date » intraday). **Conséquence (règle Axe #1 : reframe si Polymarket ET dérivés non concluants → les deux le sont) : le reframe honnête est DÉCLENCHÉ.** Conclusion assumée : **pas d'edge de prédiction démontré dans les familles gratuites accessibles → Tik EST un outil de NON-PERTE / contexte / discipline / alerting**, pas un générateur de signaux directionnels. **Seul thread encore ouvert** : le **micro ML** (ADR-033), qui mûrit en shadow (mesurable ~mi-juillet) → vrai **ADR-034** quand mesuré. Les 3 scripts de mesure sont sur `refonte-cosmique` (lecture seule, n'enrôlent rien). **À NE PAS refaire l'erreur** : ⚪ ≠ « plus de données = edge » ; sauf le fil dérivés (à re-mesurer), accumuler ne créera pas un edge absent.
- **2026-06-30 — Edge de NON-PERTE renforcé + déployé (front).** Le « frein de discipline » du cockpit (macro ±4h seul) est devenu un **feu de sécurité consolidé** 🟢/🟠/🔴 (`src/safety/trade-safety.ts`, helper pur testé) qui fusionne : macro ±4h · **2 pertes d'affilée → 🔴 STOP** (règle perso trader) · risk-off (VIX/crédit) · breaking < 2h · **exposition empilée** (≥2 positions même actif+sens). Expose un **`sizingFactor`** (0/0.5/1) = la **prise** sur laquelle un futur signal de prédiction se branchera (prédiction = direction, non-perte = droit de trader + taille ; philosophie guard V01-V15 de Zeta en manuel). Mesure annexe : **PAXG (Binance) suit GC=F à r=0,975** (1h) → flash GOLD techniquement possible via PAXG mais **non prioritaire** (proxy crypto + overlays seraient crypto + GOLD non tradé). **NB session** : GitHub MCP a clignoté → derniers scripts poussés en **direct sur `refonte-cosmique`** (pas via PR).
- **2026-06-30 — Reframe UX honnête TERMINÉE (suite directe du VERDICT ⚪×3) — déployé front (`refonte-cosmique` commit `d2785db`).** L'essentiel du reframe était déjà en place (cockpit mené par le **feu de non-perte** 🟢/🟠/🔴, tuiles/cartes « conv/accord » + disclaimers « contexte, pas un ordre · aucun edge prouvé »). Restait **le dernier vernis de certitude** : nulle part on ne disait **explicitement** que `conviction%` et `veracity%` **ne sont PAS une probabilité de gain**. Ajouté noir sur blanc aux **3 endroits qui comptent** : (1) **`glossary.ts`** — définitions canoniques (surfacées dans **tous** les tooltips InfoTooltip + l'écran glossaire `config.tsx`) : `veracity` renommée « **Accord des sources** », les 2 entrées (veracity + conviction) ouvrent sur « ⚠ pas une proba de gain » + rappel **mesuré** (GOLD 0,89 veracity / 4,8 % hit → **veracity ≠ edge** ; sentiment colinéaire au trend, NO-GO). (2) **`cosmic-signal-card.tsx`** — caption « **concordance des sources, PAS une proba de gain** » sous la grille conv/accord. (3) **`index.tsx`** (cockpit) — disclaimer des tuiles précisé idem. Levier : éditer le glossaire propage à **toutes** les surfaces tooltip d'un coup. **Choix de discipline** : `veracity-gauge.tsx` (« Veracity globale ») laissé tel quel = **dead code** (jamais importé) → le renommer ne sert aucune surface live (Axe #1). Front-only → hot-reload Metro. **Vérif en boucle (consigne trader) → 1 résidu corrigé** (`refonte-cosmique` commit `1dbc07c`) : la carte de sécurité du cockpit listait encore « Veracity dernier swing BTC X% » avec un **✓ vert** quand ≥ 85 % → re-suggérait « accord haut = feu vert pour trader », pile la confusion qu'on tue. Corrigé : les **critères** ne contiennent plus QUE le droit de trader (non-perte : macro/pertes/risk-off/breaking + sizing) ; la veracity passe en **ligne de contexte neutre** (« Accord des sources … — concordance, pas un feu vert »). Le glossaire (édité ici) **propage automatiquement** à toutes les surfaces tooltip vivantes (onglet Signals légende `conv·accord`, écran glossaire `config.tsx`) — vérifié. **Reste à faire** (inchangé) : micro ML ~mi-juillet → ADR-034 ; re-mesure dérivés L/S ~mi-août ; recalibrage `cross_validator` post-régime.
- **2026-06-30 — Vulnérabilités de dépendances creusées + critique/high réglés (front, `refonte-cosmique` commit `f8b9f6d`).** `npm audit` (lockfile dashboard) = **22 vulns (1 critique, 2 high, 18 moderate, 1 low)**, **toutes transitives & dev/build-tooling** (bundler Metro, Expo CLI, ngrok, xcode…). Mesure clé : **`npm audit fix` non-breaking ne change RIEN** — les versions vulnérables sont épinglées par l'arbre **Expo SDK 54**, seul `--force` vers **Expo 57** (migration majeure risquée, NON faite) les bougerait. **Fix chirurgical sans toucher Expo** : bloc `overrides` sur les 3 feuilles réparables → **shell-quote 1.9.0** (tue le **critique**, injection), **ws 8.21.0** + **undici ^6.27.0** (tuent les **2 high**, DoS du serveur de dev ; undici gardé sur la ligne v6 qu'attend React Native). **Mesuré : 22→20, critique 1→0, high 2→0, aucun bump Expo forcé.** Les **19 moderate** restants = dev-tooling de l'arbre Expo → à régler par une future montée de SDK, **pas un risque réel** (app perso, outils de build, surface d'attaque ≈ nulle). **Côté Python (core)** : `python-jose` (candidat high classique) **n'est importé NULLE PART** (réservé au futur OAuth2Provider ADR-001) → **non exploitable** ; pas de `pip-audit` dans le sandbox → mesure précise à lancer **sur le VPS** (`pip-audit` sur l'env réel) si besoin. **Déploiement du fix npm** : nécessite `npm install` + restart Metro sur le VPS (le `git checkout` du lockfile seul ne suffit pas — node_modules doit être régénéré ; le restart change l'URL ngrok → re-scanner le QR). **Réversible** : `git checkout` des 2 fichiers + `npm install`. **Non vérifié runtime** (pas de node_modules ici) : à tester que l'app charge après `npm install`.
- **2026-06-26 — Audit fiabilité + 1er lot de réparations déployé en prod (`Lolasiku` commit `0a193e5`, pytest 168 verts sur le périmètre touché).** (1) **Vague 2 UI** (« Contrat des 4 états » étendu à toutes les cartes cosmiques) + **âges en temps réel** (actus, marchés prédictifs, hit-rate `computed_at`, agenda « dans X », cartes macro « il y a X ») + défaut login `204.168.220.47:8200`. (2) **2 fixes backend fiabilité/honnêteté** : *publish Redis best-effort* dans `publisher.py` (un hoquet Redis ne fait plus rollback → perte du signal DB) ; *anti-fausse-confiance* sur `hit_rate_by_veracity` (flag `thin_sample` par bucket < 10 + `sample_warning` enrichi — un bucket « 100 % sur 2 signaux » est désormais signalé). (3) **Audit complet** : [`docs/audit-fiabilite-2026-06-26.md`](docs/audit-fiabilite-2026-06-26.md) — cartographie émission→suivi→affichage, tous les fails par composant, plan priorisé. **4 « fails » de l'audit invalidés à la lecture du code** (donc NON « réparés », pour ne pas coder du vent) : `antifakenews_mode` est déjà un `Literal` Pydantic (typo = crash démarrage, pas désactivation muette) ; le scheduler enveloppe déjà chaque job en `try/except` (pas de crash sur outage API, juste cycle perdu en silence) ; le micro ne spammait PAS de 400 toutes les 5 min (l'auto-résolution le skippe déjà, absent de `REFERENCE_HOURS_BY_HORIZON`) ; la page détail avalait déjà l'erreur 400.
- **2026-06-26 (suite) — 2e lot de réparations déployé en prod (`Lolasiku` commit `b7e1145`, pytest 135 verts).** (1) **Bannière « ⚠ BTC swing dégradé — N/4 sources actives »** en tête du cockpit (`cosmic-overlays-banner.tsx`, 100 % front dérivé de `useSourceHealth`) : rend VISIBLE la dégradation silencieuse (actuellement 2/4 : Reddit + CryptoCompare HS), s'auto-masque à 4/4. (2) **`n_too_young`** sur le hit-rate (back additif + carte) : distingue « signal trop jeune pour être mesuré » de « prix manquant » (`n_skipped`), `n_evaluated` bas enfin explicable. (3) **Micro track-record explicite** : la page détail d'un signal micro affiche « ✋ Micro — mesure shadow (ADR-033), Tik ne suit pas le prix » au lieu d'un vide silencieux, et skippe l'appel 400. **Donc les 3 « réparations restantes » notées au 1er lot sont FAITES.** **Vraies tâches restantes (besoin de données LIVE, pas de code)** : recalibrer les seuils de dispersion `cross_validator` **post-régime** (quand FG sort de la peur extrême) ; mesurer les shadows non-sentiment (Polymarket/dérivés/ETF/micro) ≥ 2 sem vs Always-SHORT → **ADR-034** (seule voie vers un edge). Détail complet : [`docs/audit-fiabilite-2026-06-26.md`](docs/audit-fiabilite-2026-06-26.md).
- **Trading manuel démarré 2026-05-24** — BTC uniquement (pas GOLD : hit rate Tik GOLD mesuré ~4.8 % vs Always SHORT 81 %, cf. Garde-fou 2-bis). Premier event macro HIGH post-démarrage = NFP 2026-06-05.
- **Reddit IP-banni** (Bug 11) **ET CryptoCompare hors quota** (Bug 15, à 0 depuis le 11/06) → BTC swing tourne à **2/4 overlays sentiment** (FG + Google News seulement), pas 3/4. Conséquence mesurée 2026-06-14 (48h) : la direction atteignable a basculé *short → long* (113 long / 79 neutral / **0 short**), les LONG « FG achète-la-peur » passant le filtre ≥ 0.85 (moy. 0.853). Seuil transitoire **0.85** maintenu (Garde-fou 2-bis) mais **ne plus lire ces LONG comme un achat** (NO-GO intact). Réversible auto au retour de CryptoCompare (~1er juillet) puis de Reddit.
- Recalibration `source_credibility` ADR-011 active depuis ~22/05 sur données propres (post-fix Bug N=2) — impact **cosmétique** : alimente uniquement l'affichage `evidence[].score`, jamais direction/conviction/veracity (post-ADR-018).
- Suite pytest core : ~1395 tests verts (contre `tik_test`, **jamais la prod** — cf. mémoire `pytest-run-safely-tik-test`).
- **Accès & déploiement VPS (établi 2026-06-24 — IMPORTANT, à ne pas oublier)** :
  1. **Accès SSH par clé** : `ssh root@204.168.220.47` (clé publique du « gros PC » Windows de l'utilisatrice dans `/root/.ssh/authorized_keys`). Vrai terminal avec **copier-coller** → fini la console web Hetzner (clavier QWERTY/caps qui mélange `:`→`;`, `_`→`-`, `@`→`2`, `>`→`.`, `|`→`\`). Pas de mot de passe (login root = clé only ; un prompt mot de passe = on était déjà connecté ou mauvais point de départ). L'associé reste joignable via la console web Hetzner.
  2. **La deploy key du VPS est en lecture+ÉCRITURE** sur `Lolasiku-prog/Tik` → **on peut déployer DIRECTEMENT depuis le VPS sans l'associé** : éditer dans `/opt/tik` puis `git add` + `git commit` + `git push origin refonte-cosmique` (= le dépôt de PROD que le VPS lit). Vérifié 2026-06-24 (commit `5c4927d` poussé ainsi). C'est désormais le chemin de déploiement le plus simple.
  3. **Dashboard Expo/Metro tourne en tmux** (session `metro`, lancée par `cd /opt/tik/dashboard && npx expo start --tunnel`) → **permanent**, survit au PC éteint. Le tunnel ngrok est **anonyme** (`…exp.direct`, change à chaque restart → re-scanner le QR). Revoir le QR / logs : `tmux attach -t metro` (ressortir SANS couper : **Ctrl+B puis D** ; ne PAS faire Ctrl+C qui tue Metro). App iPhone (Expo Go) → se connecter au core via **`http://204.168.220.47:8200`** (PAS `localhost` qui = le téléphone) + clé API de **lecture** (`read:signals…`, pas la clé `micro-bridge` write-only).
  4. **Conteneur `micro`** : `/opt/btc-research-lab`, lancé via `docker compose -f docker-compose.micro.yml` (séparé du compose Tik `/opt/tik/core`). `restart: unless-stopped` → survit aux reboots. Logs : `cd /opt/btc-research-lab && docker compose -f docker-compose.micro.yml logs -f micro`.
  5. **Topologie 2 comptes GitHub** : **`escltheo-eng`** = compte de l'utilisatrice / **dev** (mes commits + PR ; c'est ce que lit le sandbox Claude `/home/user/Tik`) ; **`Lolasiku-prog`** = compte de l'associé / **PROD** (ce que le VPS clone/pull/push pour Tik ET pour btc-research-lab). Les deux NE sont PAS auto-synchronisés → une même correction peut exister en **2 commits** (un par compte, même contenu) ; réconciliation triviale à la prochaine synchro associé. `btc-research-lab` (escltheo) cloné sur le VPS via passage **temporaire en public** du dépôt (pas de deploy key pour lui).

### Couches non implémentées / backlog

- Engine macro (semaines-mois) ; flash GOLD (bloqué par le délai Yahoo 15 min).
- **Familles edge non-sentiment en shadow** (codées, NON enrôlées) : dérivés Binance (ADR-023), flux ETF spot BTC (ADR-024) — enrôlement seulement après mesure ≥ 2 sem concluante. Restantes non codées : on-chain (Whale Alert V1.5), ETF GOLD (V1.2).
- Traduction FR des signaux (ADR-014 réservé), refonte UX complète (prévue en fin de dev, sur demande).
- Roadmap OSINT conditionnelle : [`docs/backlog-osint.md`](docs/backlog-osint.md). Backlog général : [`docs/backlog.md`](docs/backlog.md).
- Hébergement / distribution de l'app : exposé fait, **décision en attente** ([`docs/hosting-and-app-options.md`](docs/hosting-and-app-options.md) + mémoire `hosting-app-distribution-decision`).

### Axe stratégique #1

Tant que le trading manuel est la priorité : **toute décision technique se juge au filtre « contribue-t-elle à un edge mesurable, OU à la qualité contexte / discipline / fiabilité ? »**. Ne **pas** peaufiner le « vernis de certitude » de l'UX (conviction %, veracity affichées comme des gages de fiabilité) tant que l'edge n'est pas prouvé. Le reframe UX honnête n'est déclenché que si Polymarket **et** les dérivés s'avèrent non concluants.

---
## 9. Bugs connus et résolus

16 bugs identifiés depuis le démarrage du projet — 15 résolus + 1 actuel mitigé en attente d'un fix asynchrone (les 3 premiers pendant le déploiement initial du Paquet 1, les 3 suivants pendant les évolutions post-livraison du 2026-04-28, le 7e découvert le 2026-05-03 lors de la mise en service du dashboard sur iPhone, le 8e découvert le 2026-05-04 lors de la livraison Stats LLM card et résolu en deux temps : fix dashboard `parseUtcIso` le matin puis fix backend ADR-013 / Paquet 7 l'après-midi ; le 9e régression asyncpg DB du Paquet 7 fixé runtime le 2026-05-04 ; le 10e WebSocket coroutine zombie identifié et fixé le 2026-05-17 soir lors de l'audit santé runtime pré-trading Paquet 26 ; le 11e Reddit IP-ban full sur IP HP découvert lors de l'audit pré-J+14 Paquet 27 du 2026-05-18, mitigé par Option A doc-only en attente unban Reddit asynchrone ; le 12e cache track record qui figeait l'affichage des favoris flash en « tout sablier », découvert et fixé le 2026-05-26 via les questions de l'utilisatrice, Paquet 38 ; le 13e mapping FRED release_id faux (RETAIL_SALES=H.10 FX Rates, INITIAL_CLAIMS=G.19 Consumer Credit) découvert et fixé le 2026-05-31 lors de l'audit A3, Paquet 45 ; le 14e dates banques centrales fausses (FOMC = ~calendrier BoE, faux FOMC nov, octobre manquant ; BoE/BoJ décalées) découvert et fixé le 2026-06-07 lors de la validation A.4 ; le 15e CryptoCompare free tier tombé à 100 req/mois (rebrand CoinDesk) faisant exploser le quota par polling horaire — BTC swing privé de son 3e overlay → souvent neutral, découvert + fixé le 2026-06-11 en investiguant l'observation trader « BTC beaucoup de neutral depuis hier » ; le 16e WebSocket en reconnexion boucle toutes les ~5s — régression redis-py 8.0 où `pubsub.listen()` lève `TimeoutError` sur read idle, non capté par le handler — découvert + fixé le 2026-06-15 en investiguant l'échec du test d'intégration WS) :

### Bug 1 — Hypertable TimescaleDB avec primary key incompatible

**Symptôme** : `cannot create a unique index without the column "timestamp" (used in partitioning)`
**Cause** : la table `signals` est une hypertable Timescale partitionnée par `timestamp`, mais la primary key initiale n'incluait pas `timestamp`.
**Fix** : dans `core/migrations/versions/20260420_0000_0001_initial.py`, modifier la table `signals` pour avoir `primary_key=False` sur `id`, ajouter `nullable=False`, et ajouter `sa.PrimaryKeyConstraint("id", "timestamp")`.

### Bug 2 — Foreign key composite manquante dans `feedbacks`

**Symptôme** : `there is no unique constraint matching given keys for referenced table "signals"`
**Cause** : conséquence du Bug 1 : la primary key de `signals` étant maintenant `(id, timestamp)`, la foreign key de `feedbacks` doit référencer les deux colonnes.
**Fix** : dans la même migration, ajouter `sa.Column("signal_timestamp", sa.DateTime(), nullable=False)` à la table `feedbacks` et changer la `ForeignKeyConstraint` pour `(["signal_id", "signal_timestamp"], ["signals.id", "signals.timestamp"], ondelete="CASCADE")`. Côté modèle Python (`core/src/tik_core/storage/models.py`), ajouter le champ `signal_timestamp` au modèle `Feedback`.

### Bug 3 — Type UUID vs VARCHAR incompatible

**Symptôme** : `operator does not exist: character varying = uuid`
**Cause** : dans les modèles `ApiKey` et `Feedback`, la colonne `id` était déclarée `UUID(as_uuid=False)` côté SQLAlchemy mais générée comme `String(36)` dans la migration.
**Fix** : dans `core/src/tik_core/storage/models.py`, remplacer `UUID(as_uuid=False)` par `String(36)` dans les deux modèles. Retirer l'import `from sqlalchemy.dialects.postgresql import UUID` qui n'est plus utilisé.

### Bug 4 — Source mal labelisée pour les signaux GOLD

**Symptôme** : l'evidence des signaux GOLD indiquait `source: binance_klines` alors que GOLD vient de Yahoo Finance. Le score de crédibilité (0.85) était identique pour toutes les sources.
**Cause** : dans `core/src/tik_core/scoring/swing_engine.py`, la fonction `_score_indicators()` hardcodait `"source": "binance_klines"` dans l'evidence — alors qu'elle est appelée pour BTC (Binance) et pour GOLD (Yahoo).
**Fix** : la source est désormais passée via `df.attrs["source"]` (cohérent avec le pattern existant pour `entity_id`). Le score de crédibilité vient du dictionnaire `SOURCE_SCORES` qui dépend de la source réelle. Bug fonctionnel ? Non, c'était juste un label incorrect — les données utilisées étaient bien les bonnes.

### Bug 5 — Bouton "Authorize" manquant dans Swagger

**Symptôme** : pas de bouton "Authorize" dans le Swagger UI à `http://localhost:8200/docs`, donc impossible de tester les endpoints authentifiés directement depuis Swagger.
**Cause** : la sécurité OpenAPI n'était pas déclarée dans la config FastAPI.
**Fix** : dans `core/src/tik_core/main.py`, override de `app.openapi()` pour ajouter un security scheme `bearerAuth` (HTTP/Bearer), appliqué à tous les paths sauf `/api/v1/health` (déclaré public via la constante `PUBLIC_PATHS`).

### Bug 6 — Healthchecks Docker `unhealthy` pour ingesters et scheduler

**Symptôme** : `tik-ingesters` et `tik-scheduler` apparaissent comme `(unhealthy)` dans `docker compose ps`, alors qu'ils tournent bien.
**Cause** : ils héritaient du `HEALTHCHECK` du Dockerfile commun (`curl http://localhost:8200/api/v1/health`), mais n'exposent pas l'API → curl échoue toujours.
**Fix** : override du healthcheck dans `core/docker-compose.yml` pour ces deux services. Test via `python -c "import redis; redis.Redis(host='redis').ping()"` (Python est déjà installé, Redis est nécessaire au fonctionnement). Pas un heartbeat fin du process business mais suffisant pour le MVP.

### Bug 7 — WebSocket auth refusée systématiquement (import statique `_session_maker`)

**Symptôme** : tous les clients WebSocket (dashboard iPhone, dashboard Mac, curl) reçoivent un HTTP 403 sur `/api/v1/ws/signals?api_key=...`. Côté dashboard, l'indicateur reste bloqué sur "Reconnexion…" en boucle. Côté logs Tik core, on observe : `"WebSocket /api/v1/ws/signals?api_key=tik_..." 403` répété à chaque tentative. Aucun signal temps réel ne remonte au dashboard, qui reste en mode "preload REST seul".

**Cause** : dans `core/src/tik_core/api/ws.py`, l'import était écrit comme `from tik_core.storage.database import _session_maker`. Cet import lit la **valeur** de la variable globale `_session_maker` au moment de l'import du module (= `None`, parce que le lifespan FastAPI n'a pas encore appelé `init_engine()` à ce moment-là). Cette référence reste `None` pour toujours dans `ws.py`, même quand `init_engine()` met à jour la variable globale dans `database.py`. Conséquence : à chaque connexion WS, le check `if _session_maker is None: await websocket.close(code=1011)` se déclenche → close → 403 HTTP côté client.

Bug invisible côté REST parce que les routes REST utilisent la **fonction** `get_session()` qui résout `_session_maker` dynamiquement à chaque requête (au runtime, après que l'engine soit initialisé). Bug invisible en CI parce que la fixture pytest `db_engine` initialise le session_maker **avant** l'import du module testé.

**Fix** : remplacer `from tik_core.storage.database import _session_maker` par `from tik_core.storage import database`, et accéder dynamiquement à `database._session_maker` au moment de la requête WS (pattern identique à `get_session()`).

**Validation runtime** (2026-05-03) :
- Logs core : `ws.connected client_id=dashboard entity=None horizon=None` ✓
- Indicateur Signals dashboard : "Live" ✓
- Flux temps réel : signaux apparaissent en haut de la liste

**À ajouter en futur** : un test pytest qui démarre l'app FastAPI complète (lifespan inclus) puis tente une connexion WS, pour attraper ce genre de bug en CI plutôt qu'en production. Reporté Session future.

### Bug 8 — Décalage de 2 h sur tous les âges affichés côté dashboard (timezone UTC mal interprétée)

**Symptôme** : sur tous les écrans du dashboard (Home, Signals, Alerts, détail signal, nouvelle carte Stats LLM), tous les libellés "il y a X minutes/heures" sont systématiquement en avance de l'écart UTC ↔ heure locale (2 h en CEST, 1 h en CET). Un signal émis il y a 5 min affiche "il y a 2 h 5 min". Sur le détail signal, "Émis le ..." affiche un timestamp décalé. L'utilisatrice voit "il y a 2 h" alors que le scheduler tourne aux fréquences attendues (flash 5 min, swing 15-30 min).

**Cause** : le core sérialise tous ses timestamps via `datetime.utcnow()` qui retourne un `datetime` **naïf** (sans tzinfo). Pydantic le sérialise en chaîne ISO **sans suffixe `Z`** : par exemple `"2026-05-04T10:38:14.554767"`. Côté dashboard, `new Date("2026-05-04T10:38:14.554767")` interprète selon ECMA-262 cette chaîne comme **heure locale** (pas UTC). Conséquence : un signal émis à 10:38 UTC est traité côté dashboard comme 10:38 Paris CEST = 08:38 UTC. Le delta `Date.now() - parsedDate` est donc systématiquement faussé de l'écart de timezone.

Bug pré-existant depuis le Paquet 3 (commit `5ba28cb` du 2026-05-01) mais resté invisible parce que l'utilisatrice n'avait jamais comparé l'âge affiché avec un `date -u` terminal jusqu'au 2026-05-04 (lors de la livraison Stats LLM card). **Pas un bug Tik** (les signaux sont bien émis en instantané, le scheduler tourne aux fréquences fixes attendues) — uniquement un bug d'affichage côté client.

**Fix côté dashboard uniquement (2026-05-04)** : nouvel utilitaire `dashboard/src/utils/time.ts` avec `parseUtcIso(iso)` qui détecte la présence d'une timezone (`Z`, `+HH:MM`, `-HH:MM`) via regex et ajoute `Z` si absent. `timeAgo` et `formatLocal` réutilisent ce helper. Refactor des 5 fichiers consommateurs (suppression des 4 `timeAgo` dupliqués + 2 `new Date(iso).toLocaleString()` du détail signal + 1 `new Date(iso).getTime()` du filtre `deriveLlmStats` dans `useDashboardKpis`). **Compat forward** : si le backend ajoute un jour la timezone explicite (`Z` ou `+00:00`), `parseUtcIso` la détecte et n'ajoute rien — donc pas de double-encoding.

**Fix backend complémentaire — ✅ LIVRÉ 2026-05-04 (ADR-013, Paquet 7)** : tous les `datetime.utcnow()` du core remplacés par les helpers `now_utc()` (aware, pour création d'objets) et `now_utc_naive()` (naïf, pour comparaisons SQL et défauts colonnes) du nouveau module `core/src/tik_core/utils/time.py`. Sérialisation Pydantic via `field_serializer` + helper `iso_utc` (ajoute `Z` même sur datetime naïf venant de la DB). Périmètre maximal : 17 fichiers source + 19 tests pytest. **Bug 8 désormais résolu à la source** pour TOUS les consommateurs (dashboard, SDK Python, futur Zeta). Le `parseUtcIso` côté dashboard reste comme filet forward-compat. Pas de migration Alembic vers TIMESTAMPTZ (hypertable Timescale, le serializer compense suffisamment). Voir Paquet 7 section 8 et `docs/adr/013-timezone-aware-datetimes.md`.

**Validation runtime fix dashboard** (2026-05-04 matin) :
- Heure UTC terminal : `date -u` → 11:36 UTC ✓
- Heure locale iPhone : 13:35 (CEST = UTC+2) → écart cohérent ✓
- Carte Stats LLM dashboard : "Dernier signal il y a 4 min" sur un signal émis à 11:32 UTC ✓
- Détail signal "Émis le 04/05/2026 13:32:14" pour un signal de timestamp `2026-05-04T11:32:14` ✓

**Validation runtime fix backend** (2026-05-04 après-midi, ADR-013) :
- Pytest 590 tests verts (0 régression vs 561 base + 19 nouveaux tests timezone)
- Tous les datetimes émis par Tik portent désormais le suffixe `Z` (UTC explicite) à la sérialisation JSON
- Cas piège DB validé : un `Signal.timestamp` lu naïf depuis SQLAlchemy ressort avec `Z` via le `field_serializer` Pydantic — bug 8 ne peut plus se reproduire côté backend

### Bug 9 — Asyncpg refuse les datetime aware sur colonnes `TIMESTAMP WITHOUT TIME ZONE` (régression introduite par ADR-013)

**Symptôme découvert le 2026-05-04 fin d'après-midi** lors de la session de bascule LLM hypothesis shadow runtime : depuis le déploiement du Paquet 7 (ADR-013) du matin même, **aucun signal n'arrive en DB**. Les engines tournent normalement, le LLM Ollama produit ses candidates (8 succès observés entre 16:36 et 16:57 UTC, 76-115 mots), puis `INSERT INTO signals` échoue systématiquement avec `asyncpg.exceptions.DataError: invalid input for query argument $2: ... (can't subtract offset-naive and offset-aware datetimes)`. Tous les cycles swing BTC + swing GOLD + flash BTC sont perdus pendant ~4 h sans aucune alerte côté UI (le scheduler logue l'erreur mais ne crashe pas — il continue à tenter des cycles toutes les 5/15/30 min). Côté dashboard, aucun nouveau signal n'apparaît dans la liste Signals après 13:09 UTC alors que les containers sont up et "healthy".

**Cause** : ADR-013 a remplacé tous les `datetime.utcnow()` (naïfs) par `now_utc()` (aware avec `tzinfo=UTC`) dans le code core. Conséquence : `decision.timestamp` (assigné dans les engines `swing_engine.py` / `flash_engine.py`) et `expiry` (calculé dans `publisher.py:48`) sont désormais aware. Mais les colonnes `signals.timestamp` et `signals.expiry` dans Postgres sont restées en `DateTime` sans `timezone=True` → mappées en `TIMESTAMP WITHOUT TIME ZONE` côté SQL. **asyncpg lève `DataError` sur un datetime aware au lieu de stripper silencieusement la tzinfo** comme le commentaire d'`utils/time.py:18` le prétendait *"asyncpg strippe silencieusement la tz d'un aware mais autant garder la cohérence"* — le commentaire est obsolète sur la version actuelle d'asyncpg.

Bug invisible en CI parce que les tests pytest utilisent SQLite (qui accepte aware sans broncher) ou un setup Postgres avec un comportement asyncpg différent. **590 tests pytest verts ne garantissent pas l'absence de régression runtime DB** — leçon retenue.

**Fix (workaround chirurgical)** : strip explicite de la `tzinfo` au moment de l'INSERT dans `publisher.py:_publish_signal`. 2 lignes ajoutées : `timestamp_naive = decision.timestamp.replace(tzinfo=None) if decision.timestamp.tzinfo is not None else decision.timestamp` et `expiry = (now_utc() + EXPIRY_BY_HORIZON[horizon]).replace(tzinfo=None)`. Le `Signal(timestamp=timestamp_naive, expiry=expiry, ...)` reçoit donc des datetimes naïfs compatibles avec les colonnes existantes.

ADR-013 reste valide dans son intention (datetimes aware partout en mémoire + sérialisation Pydantic via `iso_utc` qui ajoute le suffixe `Z`). On corrige juste **la prémisse erronée** sur le comportement asyncpg. Le fix est volontairement chirurgical (1 fichier, 2 lignes) plutôt qu'une refonte des engines (`now_utc()` → `now_utc_naive()` dans 5 sites) ou une migration Alembic vers `TIMESTAMPTZ` (lourde sur hypertable Timescale, explicitement rejetée par ADR-013).

**Validation runtime** (2026-05-04 17:11 UTC, post-restart `docker compose restart scheduler`) :
- `scheduler.hypothesis_generator_ready method=ollama:llama3.2:3b mode=shadow` ✓
- `hypothesis_generator.shadow.candidate length_words=138 method=ollama:llama3.2:3b` (LLM swing BTC) ✓
- `signal.published id=TIK-SWING-BTC-20260504171105-7554b3` ← **la ligne qui était absente toute la matinée** ✓
- Idem swing GOLD (105 mots) + flash BTC (103 mots) — 3 cycles complets en 90 secondes
- **Aucune erreur `scheduler.*.error`** dans les logs depuis le restart

**Suites à donner (dette technique)** :
- ✅ **Commentaire `utils/time.py:18` corrigé (2026-05-05, Paquet 14 polish)** : *"asyncpg strippe silencieusement la tz"* → *"asyncpg lève `DataError` sur un datetime aware passé à une telle colonne"* avec mention bug 9 et workaround `publisher.py`.
- ✅ **ADR-013 amendé (2026-05-05, Paquet 14 polish)** : nouvelle section « Amendement post-livraison — Bug 9 régression DB asyncpg » qui documente la prémisse erronée + le tableau pour/contre/verdict des 3 options de fix (migration TIMESTAMPTZ rejetée, `now_utc_naive` partout rejeté, workaround chirurgical retenu).
- ✅ **Test pytest Postgres bout-en-bout** — **FAIT depuis le Paquet 31**, vérifié runtime 2026-05-24 (5 tests verts contre `tik_test`, `core/tests/test_publisher_timezone_db.py`). Attrape une régression DB-spécifique invisible en SQLite (strip de tzinfo dans `publisher._publish_signal`).

**Ces 9 fixes sont déjà appliqués dans le code actuel** (et poussés sur GitHub).

### Bug 10 — tik-core API hang bloquée par coroutine WebSocket zombie

**Symptôme découvert le 2026-05-17 soir** lors de l'audit santé runtime pré-trading (cf. Paquet 26 section 8) : `docker compose ps` montre `tik-core (unhealthy)` depuis 3h, `curl http://localhost:8200/api/v1/health` timeout après 5s (TCP handshake OK mais aucune réponse HTTP), logs `docker compose logs core --tail 50` spam `[warning] ws.send_failed error='Cannot call "send" once a close message has been sent.'` 5+ fois par cycle de publication signal (toutes les 5-30 min selon horizon). Dashboard iPhone Expo Go ne peut plus appeler l'API → trader ne pourrait pas utiliser Tik pour son trading manuel J+14.

**Cause root** : dans [core/src/tik_core/api/ws.py:106-107](core/src/tik_core/api/ws.py#L106-L107) (avant fix), le bloc `except Exception` interne à la boucle `async for message in pubsub.listen():` attrapait **TOUTES** les exceptions de `await websocket.send_json(...)` incluant `RuntimeError("Cannot call 'send' once a close message has been sent.")` (levée quand le client est déconnecté) — mais **ne sortait PAS de la boucle**. Conséquence : à chaque nouveau signal Tik publié sur Redis pubsub, la coroutine retente `send_json` sur un WebSocket déjà fermé → nouveau warning → boucle infinie. Le `WebSocketDisconnect` externe (ligne 108) ne sauve pas car `RuntimeError` ≠ `WebSocketDisconnect`. Chaque WebSocket zombie consomme une coroutine + une connexion Redis pubsub + un heartbeat task. Multiplié par les déconnexions Expo Go répétées (changement WiFi, swipe down de l'app, etc.), l'event loop async sature progressivement → les requêtes HTTP `/api/v1/health` (et toutes les autres) timeout silencieusement.

Bug invisible en CI parce que `test_ws_lifespan.py` (Paquet 7 fix Bug 7) teste seulement l'établissement de la connexion WS, pas le cycle complet de publication Redis pubsub + déconnexion brutale + assertion non-zombie.

**Fix Option A appliqué dans Paquet 26** : sépare le `try/except` interne en 2 blocs distincts :

```python
try:
    parsed = json.loads(data) if isinstance(data, str) else data
except (json.JSONDecodeError, TypeError) as exc:
    log.warning("ws.payload_invalid", error=str(exc))
    continue   # signal mal formé côté publisher, on passe au suivant
try:
    await websocket.send_json({"type": "signal", "payload": parsed})
except Exception as exc:  # noqa: BLE001
    log.info("ws.client_gone", client_id=key.client_id, error=str(exc))
    break   # client déconnecté, on sort de la boucle → finally cleanup
```

Pourquoi pas Option B (juste ajouter `break` sans séparer les except) : si Tik publiait un signal mal formé en interne, tous les clients WebSocket se déconnecteraient en cascade. Option A distingue **"signal mal formé"** (continue avec le suivant) de **"client parti"** (break, libère ressources). Cohérent paranoia contrôlée.

Pourquoi pas Option C (whitelist `WebSocketDisconnect`, `ConnectionClosed`, `RuntimeError`) : dépend des imports précis du module `websockets` (fragile aux upgrades de lib), et `RuntimeError` trop large (matchera d'autres bugs futurs).

**Validation runtime fix** (2026-05-17 soir post-restart) :
- `docker compose restart core` → API répond `{"status":"ok","version":"0.1.0"}` après 10s warmup ✓
- Fix code permanent à appliquer via `docker compose up -d --build core` (image custom buildée, pas bind-mount) ✓
- Plus de spam `ws.send_failed` dans les logs depuis le déploiement du fix ✓

**Suites à donner (dette technique)** :
- ✅ **Test pytest spécifique Bug 10 — FAIT depuis le Paquet 31**, vérifié runtime 2026-05-24 : `core/tests/test_ws_lifespan.py` couvre app + connexion WS authentifiée + 2 garde-fous « code source » (présence du `break` après `ws.client_gone` + du `continue` sur payload invalide) + 1 test d'intégration (close brutal WS + publication Redis + assertion `/health` rapide). Limite connue : le test d'intégration skippe en CI sans Redis → seuls les garde-fous « code source » tournent en CI (suffisants comme garde-fou principal).
- **Audit Issues #2, #3, #4 du Paquet 26 audit** : LLM hypothesis NOT active sur HP, CryptoCompare BTC swing à 7 %, baseline anomaly CC WRONGTYPE Redis. À arbitrer pré-J+14.
- **Setup HP : tik-core sur 0.0.0.0:8200** (faille hygiène 3 Paquet 15) à traiter post-J+14 (ferme tik-core au LAN maison, garder accès localhost + Tailscale subnet).

### Bug 11 — Reddit IP-ban full sur IP publique HP 204.168.220.47 (découvert 2026-05-18, Paquet 27)

**Symptôme** : depuis le déploiement HP entier (5 jours d'historique en DB), Reddit est **totalement inaccessible** depuis l'infra Tik. Les logs ingesters montrent `reddit.fetch.error 403 Blocked` répété toutes les 30 min sur `r/Bitcoin` ET `r/CryptoMarkets`. Conséquence pipeline : **0 signal sur 1778 contient `reddit_btc` dans l'evidence** = Reddit n'a jamais contribué à un signal HP. Découvert lors de l'audit santé Paquet 27 en croisant les logs avec une requête SQL `evidence::text LIKE '%reddit_btc%'`.

**Confirmation côté utilisatrice** (capture navigateur PC Windows 2026-05-18 19:30) : page d'accueil Reddit affiche "Vous avez été bloqué par la sécurité du réseau" avec le personnage Reddit + bouton "Déposer une demande d'assistance". **L'ensemble du réseau** (serveur HP + PC Windows perso) est bloqué, pas juste l'API.

**Diagnostic complet** (engagement méthodologique #10 mesurer plutôt que spéculer) :

| Test | Endpoint | HTTP | Verdict |
|---|---|---|---|
| 1 | `www.reddit.com/r/Bitcoin/hot.json` avec UA Tik custom | 403 | Bloqué |
| 2 | `www.reddit.com/r/Bitcoin/hot.json` avec UA vide | 403 | Bloqué |
| 3 | `www.reddit.com/r/Bitcoin/hot.json` avec UA Mozilla réel | 403 | Bloqué |
| 4 | `oauth.reddit.com/r/Bitcoin/hot.json` (endpoint OAuth) | 403 | Bloqué |
| 5 | `www.reddit.com/api/v1/access_token` (POST) | 401 | Joignable mais inutile |
| 6 | `old.reddit.com/r/Bitcoin/hot.json` | 403 | Bloqué |
| 7 | `reddit.com/dev/api/` (doc) | 403 | Bloqué |

**Conclusion** : c'est un **ban IP réseau** (pas un ban User-Agent ni un ban compte Reddit). Reddit OAuth officiel est **non viable** car même si on peut obtenir un bearer token via test 5, on ne peut pas l'utiliser car `oauth.reddit.com` est bloqué (test 4).

**Cause** : pas un bug Tik. IP publique partagée `204.168.220.47` (mesurée via `curl https://ifconfig.me`) probablement bannie pour une combinaison de :
- Accumulation polling Tik depuis le déploiement HP (deux subreddits × 30 min cycle = ~96 req/jour, bien sous les 100 QPM unauth de Reddit mais peut déclencher un anti-abuse système)
- Réputation IP datacenter / plage IP / FAI signalée
- Autre device sur le même réseau ayant fait du scraping passé

**Conséquence pipeline structurelle** : Tik tourne avec **3 overlays sentiment au lieu de 4** sur BTC swing (FG + CryptoCompare + Google News, sans Reddit). Quand FG diverge contrarian des news (cas typique marché bear actuel), FG est flaggé outlier ADR-011 → reste 2 sources alignées + 1 outlier → dispersion forte → **veracity capée à 0.85-0.89, jamais ≥ 0.90** sur BTC swing. Mesure audit 9h post-fix bug N=2 confirme : **0/36 signaux BTC swing à veracity ≥ 0.90**. **⚠ Correction 2026-06-10 (ADR-026)** : en régime de **peur extrême** (FG=9, depuis ~27/05), ce n'est pas « capé à 0.85 » mais **au plancher 0.70** — FG sature à +1.0, news à −1.0 → dispersion maximale. Subtilité clé : l'outlier FG est **exclu de la direction ET du circuit breaker** (`combined_bias`, status) mais **reste inclus dans la dispersion qui calcule la veracity** (`cross_validator.py:271`) → d'où `circuit=ok` MAIS `veracity=0.70` sur le même short. Incohérence diagnostiquée et tracée (ADR-026), recalibration **différée** (ne pas gonfler la veracity : Axe #1).

Ce bug était **masqué par le bug N=2** (cf. Paquet 25) qui figait artificiellement veracity = 0.95 sur 99.4 % des signaux pré-fix. Le fix N=2 du 2026-05-17 20:47 UTC a révélé la véracité réelle, et l'audit Paquet 27 l'a quantifiée.

**Fix appliqué — Option A (3 overlays + Garde-fou 2-bis transitoire)** :

Aucune modification de code. Décisions documentées Paquet 27 + Garde-fou 2-bis section 5 amendé :
- Seuil veracity transitoire **0.85 sur BTC swing** (au lieu de 0.90) tant que Reddit IP-banni
- Critère retour à 0.90 strict : Reddit reconnecté ET 7 jours stables post-réintégration ET ≥ 30 signaux BTC swing à veracity ≥ 0.90 mesurés
- Réversible automatiquement quand Reddit revient (aucun code à modifier, juste vérifier `curl` puis re-mesurer)

**Fix asynchrone Option B (demande unban Reddit en cours)** :

Formulaire support officiel `support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=21879292693140` soumis par l'utilisatrice le 2026-05-18 soir avec adresse IP `204.168.220.47`, justification OSINT research non commerciale, et engagement à migrer vers OAuth authentifié dès l'unban. **Délai retour Reddit inconnu (24h → plusieurs semaines)**. Si retour positif : `curl -s -o /dev/null -w "%{http_code}\n" -H "User-Agent: test" https://www.reddit.com/r/Bitcoin/hot.json` retourne 200 → restart ingesters via `docker compose up -d --force-recreate ingesters` → Reddit ré-intégré au pipeline en ~5 min.

**Fix structurel Option C (post-J+14) — non implémenté** :

Si Reddit refuse l'unban ou ne répond jamais, options évaluées dans backlog.md entry #10 : remplacement par Hacker News API (gratuit, JSON, tech+crypto), 4chan /biz/ (bruité), StockTwits API (free tier), X via snscrape (fragile). Effort ~4-5h dev + tests + ADR. Différé post-J+14 car trop risqué de réécrire un ingester sentiment à 5 jours du trading manuel.

**Suites à donner (dette technique)** :
- Surveiller email utilisatrice pour réponse Reddit (gmail `escltheo@gmail.com`)
- Si pas de retour Reddit dans 14 jours post-J+14 → décider Option C source alternative
- Considérer migration Tik vers VPS commercial avec IP propre si Reddit refuse définitivement (effort ~1-2 sessions + coût ~5-10€/mois)
- Le compteur global passe à **11 bugs identifiés** depuis le démarrage projet (10 résolus + 1 actuel Bug 11 mitigé par Option A en attente Option B/C)

### Bug 12 — Cache track record figeant les favoris flash en « tout sablier » (découvert + fixé 2026-05-26, Paquet 38)

**Symptôme** : un signal flash mis en favori restait « tout sablier » (badges `en_attente`) dans sa carte track record même après >1h, et son badge Watchlist restait « En attente ». Un flash non-favori du même âge s'affichait correctement.

**Cause** : `GET /api/v1/metrics/signal_track_record/{id}` mettait le résultat en cache Redis 6h à TTL fixe, **y compris quand les lignes étaient `en_attente`**. Un favori flash ouvert frais (page détail, signal < 1h) figeait le résultat « tout sablier » 6h = 6× la fenêtre flash (1h). L'auto-résolution (poll 5 min) re-tapait ce cache figé → jamais débloquée. Swing peu affecté (cache 6h ≪ fenêtre 5j → auto-correction), d'où l'asymétrie observée. Découvert via les questions de l'utilisatrice sur les favoris flash + triangulation Redis (`TIK-FLASH-BTC-20260526062008` à 82 min, 4 sabliers figés, TTL ~5h restant).

**Fix** : helper `_track_record_cache_ttl` (TTL court tant qu'il reste des `en_attente` = expire après la prochaine échéance, long 6h une fois tout résolu) + bump clé cache `v3→v4` dans `core/src/tik_core/api/metrics.py`. 7 nouveaux tests (`test_track_record_cache_ttl.py`) + suite complète 1136 verte. Vérifié live (clés v4 créées par l'endpoint, flash résolu → TTL ≈6h, signal jadis bloqué recalculé `correct/raté`). Cf. Paquet 38.

- Le compteur global passe à **12 bugs identifiés** (11 résolus + 1 actuel Bug 11 Reddit en attente).

### Bug 13 — Mapping FRED release_id faux : RETAIL_SALES + INITIAL_CLAIMS (découvert + fixé 2026-05-31, Paquet 45)

**Symptôme** : le calendrier macro affichait 3 RETAIL_SALES en juin (06-01/08/15, lundis hebdo) alors que le retail sales US est mensuel. Découvert lors de l'audit du 2026-05-31 (anomalie A3 — 31 events RETAIL_SALES futurs vs 7-9 pour les autres).

**Cause** : 2 release_id FRED faux dans `FRED_RELEASES` (`macro_calendar_data.py`) depuis le Paquet 11, vérifiés contre l'API FRED (`GET /fred/release?release_id=X`) : `RETAIL_SALES` pointait sur **17 = « H.10 Foreign Exchange Rates »** (hebdo lundi → 31 faux events) et `INITIAL_CLAIMS` sur **14 = « G.19 Consumer Credit »** (mensuel). Le vrai Advance Retail Sales = release_id **9**, le vrai weekly claims = **180**. Les 5 autres IDs (NFP=50, CPI=10, PPI=46, GDP=53, IP=13) étaient corrects. Bug invisible jusqu'ici car les deux sont MEDIUM/LOW (pas des HIGH suivis ±4h) et personne n'avait croisé la cadence avec la réalité.

**Fix (Paquet 45, commit 5de2d8a)** : `RETAIL_SALES` 17→9 ; `INITIAL_CLAIMS` retiré de la whitelist (choix utilisatrice — claims hebdo LOW = bruit). Prod nettoyée (37 faux RETAIL_SALES FX + 8 faux INITIAL_CLAIMS supprimés via le `release_id` stocké) + cycle FRED relancé → retail mensuel correct (06-17, 07-16…), comptage 31→7. 118 tests macro verts (tik_test). Diagnostic clé : il fallait passer `include_release_dates_with_no_data=true` (déjà fait par l'ingester) pour voir les dates futures de 9/180 — sans ce flag, on ne voit que le passé (fausse piste écartée).

- Le compteur global passe à **13 bugs identifiés** (12 résolus + 1 actuel Bug 11 Reddit en attente).

### Bug 14 — Dates banques centrales fausses dans le calendrier macro : FOMC/ECB/BoJ/BoE (découvert + fixé 2026-06-07, tâche A.4)

**Symptôme** : lors de l'exécution de la validation A.4 (backlog entry n°7 — « vérifier les dates ECB/BoJ/BoE 2026-2027 contre les sources officielles »), croisement des dates statiques de `macro_calendar_data.py` avec les calendriers officiels (Fed, ECB, BoJ, BoE), chacune vérifiée 2×. La quasi-totalité des dates de banques centrales étaient fausses, y compris des HIGH suivis ±4h en trading manuel.

**Cause** : dates hardcodées (Phase B2, ADR-020) jamais validées contre les sources officielles (le commentaire du fichier le signalait : « À VÉRIFIER avant déploiement runtime »). Détail :
- **FOMC** : les 13 dates étaient en réalité ~le calendrier **BoE** (jeudis) → toutes décalées, avec un **faux FOMC le 2026-11-05** (n'existe pas) et l'**octobre manquant** (vrai 2026-10-28). Vrais statements 2e jour : 06-17, 07-29, 09-16, 10-28, 12-09 (2026) + 8 dates 2027.
- **BoE** : 5/5 dates 2026 fausses (ex. code 06-19 → vrai 06-18 ; code 08-07 → vrai 07-30).
- **BoJ** : 2 dates 2026 fausses (06-17 → vrai **06-16** ; 09-19 → vrai 09-18).
- **ECB** : 2026 correctes, mais 2027 = fausses estimations (remplacées par les 8 dates officielles).

**Fix (2026-06-07)** : `macro_calendar_data.py` réécrit avec les dates officielles vérifiées, **dates à venir uniquement** (les passées restent dans la table d'audit `macro_events`). 44 events statiques (FOMC 13 + ECB 13 + BoJ 5 + BoE 13). **BoJ 2027 volontairement non inclus** : pas encore publié par la BoJ au 2026-06-07 (parution ~mi-année) → à ajouter dès parution. Application prod (même gotcha que Bug 13 — l'upsert ne supprime jamais) : (1) édition fichier (bind-mount), (2) `DELETE` des 36 lignes futures `source IN ('fed_static','ecb_static','boj_static','boe_static')`, (3) `docker restart tik-ingesters` → réinsertion 44, (4) vidage cache Redis `tik.cache.macro_events.*` (TTL 5 min). Vérifié : 0 faux FOMC nov, 59 tests `test_macro_calendar_data.py` verts (tik_test — tests structurels, n'assertent aucune date précise). Impact trader : les 4 events de mi-juin (BCE 11/06, BoJ 16/06, FOMC 17/06, BoE 18/06) sont enfin exacts pour la discipline ±4h.

- Le compteur global passe à **14 bugs identifiés** (13 résolus + 1 actuel Bug 11 Reddit en attente).

### Bug 15 — CryptoCompare free tier 100 req/mois : le polling horaire faisait exploser le quota (découvert + fixé 2026-06-11)

**Symptôme** : la trader observe « GOLD toujours short et BTC beaucoup de neutral depuis hier ». En investiguant, BTC swing s'avère privé de son **3e overlay sentiment** (CryptoCompare) → il ne reste que Fear&Greed (peur extrême → contrarian +1,0) et Google News (baissier −1,0) qui **s'annulent** → direction `neutral` quasi systématique + veracity plancher 0,70. Logs ingester : `cryptocompare.api.error message='You are over your rate limit please upgrade your account!'` toutes les heures depuis 2026-06-10 10:56 UTC (dernier succès 09:56). Clé Redis `tik.sentiment.cryptocompare.BTC` absente ; seulement 61/145 signaux BTC swing 36h contenaient CryptoCompare.

**Cause (mesurée)** : via `GET min-api.cryptocompare.com/stats/rate/limit?api_key=` → `max_calls.month=100`, `calls_made.month=251`. Le **free tier est tombé à 100 req/mois** après le rebrand CoinDesk Data ; le commentaire du code (« ~11k req/mois ») était **périmé**. L'ingester pollait **toutes les heures** (`interval_s=3600`) = ~720 req/mois = **7× la limite**. La clé Redis ayant un TTL de 2h, BTC swing perdait CryptoCompare 2h après le 1er échec. Pas un bug applicatif au sens strict, mais une **hypothèse périmée sur le quota API** baked-in dans le code → condamnait le quota chaque mois.

**Fix (2026-06-11)** : `run_ingesters.py` → `interval_s` 3600 → `8 * 3600` (3/jour ≈ 90 req/mois < 100) ; `cryptocompare_ingester.py` → `REDIS_TTL_S` 2h → 9h (couvre l'intervalle 8h) + docstring corrigée. Bind-mount → `docker restart tik-ingesters`. Vérifié : log `cryptocompare.ingester.started interval_s=28800`, `ingesters.started count=17`, syntaxe OK. **⚠ Ne ramène PAS CryptoCompare ce mois-ci** : on est déjà à 251/100 → reste bloqué jusqu'au **reset du quota** (~1er du mois, date exacte du reset non confirmée). D'ici là BTC swing reste à 2 overlays (neutral), affiché honnêtement (cohérent NO-GO). **Caveat marge** : 8h ≈ 90/mois ne laisse que ~10 appels de marge ; chaque `restart` ingesters déclenche un appel immédiat (+1). Si la marge s'avère trop juste, passer à 12h (≈ 60/mois). Alternative écartée (combler le trou via CoinGecko) : CoinGecko est la **même famille** (vote de foule, comme FG) + non mesuré prédictif → enrôlement prématuré (cf. règle shadow ≥ 2 sem + Axe #1).

- Le compteur global passe à **15 bugs identifiés** (14 résolus + 1 actuel Bug 11 Reddit en attente).

### Bug 16 — WebSocket : reconnexion en boucle toutes les ~5s (régression redis-py 8.0 sur `pubsub.listen()`) (découvert + fixé 2026-06-15)

**Symptôme** : en investiguant l'échec du test d'intégration `test_ws_disconnects_cleanly_and_app_stays_healthy` (le seul rouge de la suite, échouant 3/3 de façon déterministe), découverte que **le flux WS Live du dashboard se reconnecte en boucle**. Logs core : `ws.connected client_id=dashboard-siku` toutes les **~5-6 secondes**, chacune suivie d'un traceback non capté `redis.exceptions.TimeoutError: Timeout reading from redis:6379`. **Mesuré : 48 reconnexions en 30 min.** Les signaux publiés dans les trous de reconnexion étaient manqués (le resync REST de la mémoire `dashboard-ws-signal-staleness-fix` masquait le problème côté UI).

**Cause (mesurée)** : **régression d'upgrade redis-py 8.0**. Le handler `ws_signals` ([core/src/tik_core/api/ws.py](core/src/tik_core/api/ws.py)) bouclait sur `async for message in pubsub.listen()` dans un `try` qui ne capturait QUE `WebSocketDisconnect`. Or, en redis-py 8.0, `pubsub.listen()` lève `redis.exceptions.TimeoutError` après **exactement 5,0 s sans message** (mesuré : `socket_timeout=None` pourtant le read idle timeout à 5s) — alors qu'avant l'upgrade `listen()` bloquait indéfiniment. Comme les signaux Tik arrivent toutes les 5-30 min, chaque connexion WS crashait ~toutes les 5s entre deux signaux → coroutine handler tuée par exception non captée → WS fermée → reconnexion client → re-crash 5s plus tard. Bug invisible en CI (test d'intégration skippé sans Redis) ; révélé sur le VPS où Redis est présent.

**Fix (2026-06-15)** : remplacement du `async for pubsub.listen()` par une boucle `while True` sur `pubsub.get_message(ignore_subscribe_messages=True, timeout=30)` qui **traite l'inactivité comme normale** : `except redis.exceptions.TimeoutError: continue` (read idle = pas une erreur, on continue d'écouter) + `except redis.exceptions.RedisError: break` (vraie panne Redis → sortie propre, le client se reconnecte). **Bonus race** : `psubscribe` déplacé **AVANT** `websocket.accept()` — le client n'est « connecté » qu'une fois l'abonnement actif, donc aucun signal publié dans la fenêtre accept→subscribe n'est perdu (corrige aussi la flakiness du test d'intégration : il reçoit le signal immédiatement au lieu d'attendre 30s un heartbeat). Les garde-fous code-source Bug 10 (`break` après `ws.client_gone`, `continue` après `ws.payload_invalid`) sont préservés.

**Validation runtime** (2026-06-15) : pattern de fix validé en isolé (1 timeout d'inactivité encaissé + signal délivré après) ; **suite complète 1595 verts (0 échec)** dont le test d'intégration qui échouait, en 0,57s ; après restart core, **vraie connexion WS survit 8,0s** (>5s) et reçoit le signal publié après l'inactivité ; logs core post-fix = **0 `TimeoutError`**, plus de churn. Déployé par restart (ws.py bind-monté).

- Le compteur global passe à **16 bugs identifiés** (15 résolus + 1 actuel Bug 11 Reddit en attente).

---

## 10. Bugs non résolus / améliorations à faire

**Aucun bug critique en cours au 2026-05-04 fin d'après-midi.**

Les 2 bugs Alerts identifiés en section 10 le 2026-05-04 matin (Bug A persistance et Bug B timestamp figé) ont été résolus dans la même journée :

- **Bug A — Persistance Alerts (résolu 2026-05-04 après-midi)** : migration vers `@react-native-async-storage/async-storage` dans `dashboard/src/alerts/AlertsContext.tsx`. Hydratation eager au mount + persistance à chaque `setAlerts`. Clé storage `tik.alerts.v1` (suffixe versionné pour migration future). Filet d'exception : si JSON corrompu → log warning + reset `[]`. Cap `MAX_ALERTS=50` inchangé.

- **Bug B — Timestamp figé Alerts (résolu 2026-05-04 après-midi)** : initialement résolu avec un `setInterval(setTick, 30_000)` inline dans `app/(tabs)/alerts.tsx`. Constat post-déploiement que le **même bug existe sur l'écran Signals + Home** (4 fichiers utilisent `timeAgo`). Refacto en hook custom mutualisé `dashboard/src/hooks/use-tick.ts` (~10 lignes, retourne le `tick` pour `FlatList.extraData`). Pattern aligné sur la factorisation `dashboard/src/utils/llm.ts` (helper partagé entre carte détail signal et Stats LLM Home). Refacto de 4 fichiers (alerts, signals, index, stats-llm-card en cascade via parent index).

Pour les évolutions fonctionnelles à venir (carte Top headlines, hit rate live, track record signal, watchlist post-trade — plan trading manuel J+10), voir `docs/backlog.md` entry n°3 et la section 8 — *Couches encore non-implémentées*.

### Observations / tâches en suspens (audit du 2026-06-11)

Surfacées en investiguant le « BTC neutral » (cf. Bug 15). **Non bloquantes, à traiter quand l'occasion se présente** :

- **GDELT (overlay GOLD) rate-limited — investigué + mitigé 2026-06-11** : `gdelt.fetch.error 429` ~75 % du temps (603 erreurs vs 205 succès), GOLD swing perdait GDELT ~37 % du temps (61/97 signaux 48h) → repli sur Google News seul. Throttle GDELT **non mesurable** (pas d'endpoint quota comme CryptoCompare ; IP datacenter possiblement throttée comme Reddit). Mitigation **défensive** (marche que le throttle soit burst ou IP) : polling 30 min → **2h** (`run_ingesters.py`) + TTL Redis 2h → **6h** (`gdelt_ingester.py`) → garde le dernier tone valide malgré les 429, réduit matraquage + trous. Enjeu faible (GOLD non tradé avec Tik, tone souvent neutre) — fait pour la fiabilité/hygiène. Vérifié `interval_s=7200`. À surveiller via `GET /metrics/source_health`.
- **Re-mesure DXY/COT pour GOLD (critère ADR-018 amendement)** : la précondition « drawdown gold ≥ 5 % » est en cours (or ~−6 % du 06-06 au 06-11). Re-mesure propre à lancer **~2026-06-23** (post-J+30, ≥ 2-3 sem de données bear) via `backtest_numeric_sources.py` : si IC DXY @120h redevient **négatif** + hit cas extrêmes ≥ 50 % → réactiver `gold_dxy_cot_overlays_enabled=True`. **Ne PAS réactiver à l'aveugle** (mesurés inversés en régime bull, signe non revalidé). Indice non concluant : COT actuel extreme-long (net +76,5 %) pile quand l'or chute → la lecture contrarian aurait eu raison cette fois.
- **CoinGecko** : mesure divergence vs Fear & Greed lancée le 2026-06-11 (N=16 j) → « apport PARTIEL » (Spearman mouvement 0,467, ni redondant ni clairement indépendant). **Prochaine étape avant tout enrôlement** : mesurer son pouvoir **prédictif propre** (Δup% vs rendement BTC), pas seulement la divergence. Toggle reste OFF.

---

## 11. Workflow de l'utilisateur

L'utilisateur est sur **macOS Tahoe 26.0** (Mac M1 Apple Silicon).

**Outils installés et fonctionnels** :
- **Claude Desktop** (app native macOS) — outil principal de l'utilisatrice pour interagir avec Claude. **Important** : ce n'est pas l'extension Claude Code de VS Code.
- VS Code — éditeur de code, sans extension Claude (l'IA est ailleurs, dans Claude Desktop). Utilisé pour lire/éditer manuellement quand besoin.
- Docker Desktop — fait tourner Tik (5 services : core, ingesters, scheduler, postgres, redis)
- GitHub Desktop — gestion Git visuelle (l'utilisatrice ne maîtrise PAS les commandes Git en ligne de commande)
- Ollama (app native macOS, installée le 2026-04-30 via le .dmg officiel sans Homebrew) avec le modèle `llama3.2:3b` téléchargé localement (~2 GB). Utilisé par le `OllamaClassifier` du ingester CryptoCompare (cf. ADR-006). L'app tourne en service au démarrage, l'icône lama est visible dans la barre de menus Mac. Les conteneurs Docker l'atteignent via `http://host.docker.internal:11434`. **Réutilisable pour tout futur besoin NLP** (module anti-fake-news, génération d'hypothèses, etc.).
- **Expo Go** (app iOS sur iPhone) — installée le 2026-05-03 pour tester le dashboard Tik (Paquet 3) en mode dev. Le téléphone scanne le QR code affiché par `npx expo start` côté Mac et charge l'app Tik via WiFi local. Le dev server Expo (port 8081) doit tourner côté Mac en parallèle de Tik core (port 8200).
- Node.js v24 + npm 11 — installés sur le Mac (probablement via le .pkg officiel nodejs.org). Nécessaires pour `npx expo start` côté dashboard.
- Le repo GitHub Tik est privé

**Outils NON installés** (et qui ont posé problème) :
- Homebrew — abandonné car nécessite Xcode Command Line Tools
- Xcode Command Line Tools — bloqué (la version dispo Apple Developer 26.4.1 exige macOS 26.2)
- jq — abandonné, on utilise `plutil -convert json -r -o - -` à la place pour formater le JSON

**Workflow Git** : passe par GitHub Desktop pour `commit` + `push`, jamais par la ligne de commande.

**Workflow d'installation de paquets** : préférer Docker (déjà installé) plutôt que `brew install`.

**Pour tester l'API depuis le terminal** : l'utilisateur sait taper `curl -H "Authorization: Bearer ..." http://localhost:8200/...` et formater le résultat avec `| plutil -convert json -r -o - -`.

---

## 12. Démarrage rapide pour une nouvelle instance Claude

Si tu es une instance Claude qui prend ce projet en main pour la première fois :

1. **Lis ce fichier en entier**
2. **Lis `core/README.md`** pour les détails techniques du Core
3. **Lis les 3 ADR** dans `docs/adr/` pour comprendre les décisions
4. **Vérifie l'état du Core** en demandant à l'utilisateur de taper :
   ```
   docker compose ps
   curl http://localhost:8200/api/v1/health
   ```
5. **Demande à l'utilisateur ce qu'il veut faire** parmi les options en cours :
   - Continuer le Paquet 2 (SDK)
   - Continuer le Paquet 3 (Dashboard Expo)
   - Corriger les bugs non résolus (section 10)
   - Ajouter une nouvelle source de données
   - Faire un export / analyse des signaux déjà collectés

---

## 13. Règles à respecter (récapitulatif final)

1. **Toujours expliquer en français accessible**, pas de jargon non défini
2. **Toujours respecter le mode shadow 3 mois** avant connexion réelle Tik ↔ Zeta
3. **Toujours respecter le budget test 5%** lors du passage en mode actif
4. **JAMAIS de bypass du guard V01-V15** côté Zeta
5. **Toujours inclure contre-scénarios** dans les signaux (paranoïa contrôlée)
6. **Toujours documenter** dans un nouvel ADR toute décision structurante
7. **Toujours pousser sur GitHub** via GitHub Desktop après modifications
8. **Préférer les solutions sans installation lourde** (utiliser Docker, éviter Homebrew)
9. **Fournir des fichiers complets à remplacer** plutôt que des diffs partiels (l'utilisateur ne maîtrise pas l'indentation Python)
10. **Vérifier l'état avant chaque action** (où en est l'utilisateur, quel terminal, quel dossier)
11. **Synchroniser systématiquement worktree → repo principal** (cf section 14)

---

## 13bis — Engagements méthodologiques actifs (depuis 2026-05-07)

Section ajoutée suite à un **audit méthodique** mené les 2026-05-06 et
2026-05-07 sous consigne utilisatrice *"doute constant et méthodique,
sans complaisance"*. L'audit a révélé plusieurs errements répétés
d'instances Claude précédentes, notamment :

- Affirmer Tik = "plateforme OSINT" sans avoir vérifié que le code réel
  est en fait hybride (analyse technique + OSINT)
- Inventer des chiffres business (hit rate Zeta, lignes de code Tik) sans
  les vérifier en données réelles
- Sous-estimer la taille réelle de Tik (3.4k lignes annoncées vs 14k
  lignes vérifiées)
- Présenter avec excès de confiance des verdicts qui s'avèrent fragiles
  quand challengés

**Engagements à respecter dans toute future session de discussion
stratégique** :

1. **Lire le code AVANT d'affirmer**, pas la doc seulement.
   La doc (CLAUDE.md, ADRs) est la **vision** du projet, pas
   nécessairement la **réalité du code**. Les deux peuvent diverger.

2. **Distinguer vision (CLAUDE.md) vs réalité (code)** systématiquement.
   Quand l'utilisatrice ou la doc présente Tik d'une certaine manière,
   challenger : *est-ce que le code reflète vraiment ça ?*

3. **Te challenger** quand la formulation utilisatrice suggère une
   réalité que le code ne tient pas. Ne pas accepter passivement les
   prémisses des questions.

4. **Ne PAS inventer de chiffres** (hit rate Zeta, lignes de code Tik,
   estimations marché, etc.) sans les vérifier. Préférer
   *"je ne sais pas, à mesurer"* que de fabriquer des fourchettes
   plausibles. Apprendre de la session 2026-05-07.

5. **Vérifier les hypothèses avant verdict**. Pas de *"refactor
   obligatoire"* sans ≥ 2 vérifications factuelles préalables.

6. **Réviser explicitement** mes affirmations quand je découvre que je
   me suis trompé. **Mea culpa déclaratif**, pas implicite.

7. **Re-questionnement sérieux** quand l'utilisatrice repose la même
   question deux fois ou plus. C'est un signal que la réponse
   précédente était insatisfaisante. Aller plus loin dans le doute
   au lieu de répéter la même chose en plus long.

8. **Mentionner explicitement 3-4 limites connues** à chaque livraison
   de code ou de recommandation.

9. **Format pour/contre/verdict** pour décisions techniques (déjà
   inscrit dans la mémoire feedback).

10. **Mesurer plutôt que spéculer** quand les données sont accessibles
    (DB Tik, lignes de code via `wc -l`, fichiers du repo via Read).
    Spéculer est de la complaisance déguisée en argument quantitatif.

11. **Ne pas cumuler "spécialisation marketing" et "implémentation
    hybride"**. Si Tik est annoncé OSINT pur mais fait de l'analyse
    technique, c'est un **bug de positionnement** qu'il faut signaler,
    pas masquer.

**Mécanisme** : à relire au début de chaque session impliquant des
décisions stratégiques ou architecturales. Mention explicite dans la
réponse *"j'ai relu les engagements méthodologiques actifs"* avant
d'aborder le sujet stratégique.

**Lien direct vers les artefacts produits par cette session** :

- `docs/adr/018-tik-pure-osint-refactor.md` — décision architecturale
  réservée pour activation post-J+14
- `docs/backlog.md` entry n°6 — companion de l'ADR-018

---

## 13ter — Méthode récurrente PAR SESSION (depuis 2026-06-24)

Issue de l'audit exhaustif des états « indisponible » du dashboard (cf.
`docs/audit-etats-indisponibles-2026-06-24.md`) : ~80 messages « indisponible »
recensés, dont l'écrasante majorité vient du **même manque de discipline UI**
(erreurs avalées en silence, dumps techniques bruts, confusion vide/panne/auth).
**Un seul levier règle ~80 % des symptômes.** À appliquer/vérifier **à chaque
session** touchant l'UI ou un flux de données :

### A. Le « Contrat des 4 états » (règle UI obligatoire)
Tout élément qui affiche une donnée doit distinguer **4 états jamais confondus**,
+ un 5ᵉ si pertinent :
1. **Chargement** (spinner/skeleton).
2. **Erreur** → **message FR métier** (« Serveur injoignable », « Clé sans les
   droits / expirée »), **JAMAIS** un dump technique brut (`401 Forbidden {…}`,
   `timeout (10000ms) on …`). Idéal : helper `humanizeError()` / composant partagé
   `<UnavailableState kind=…/>`.
3. **Vide AVEC sa cause** — et **distinguer** « pas encore publié (ingester) » de
   « pas d'auth/scope » : **ne JAMAIS accuser l'ingester quand c'est la clé** (cf. le
   piège « clé absente → 7 cartes macro disent à tort *pas d'ingester* »).
4. **Donnée**.
5. **By-design** (✋) → libellé **explicite et pédagogique** (« Source désactivée
   *ADR-018* », « Micro — mesure shadow », « 🌙 marché GOLD fermé »). On **clarifie**,
   on ne masque pas (Axe #1 : l'honnêteté n'est pas un bug).

**Interdits** : avaler une erreur en `catch → []`/`null` sans la surfacer ; afficher
`err.message` brut ; coupler plusieurs cartes sur un seul `error`/`loading` (1 panne =
N cartes rouges) — chaque carte évalue **son** sous-champ.

### B. La passe « honnêteté & santé » (par session données/UI)
- Vérifier l'état des **known-issues** (sources critiques Reddit/CryptoCompare,
  ingesters macro, micro shadow) et **MAJ CLAUDE.md** si l'état a changé.
- Tout nouvel écran/carte respecte le Contrat des 4 états **avant** d'être livré.

### C. Auto-documentation (standing, demandé 2026-06-24)
**Consigner automatiquement** dans CLAUDE.md (§8 / bugs / cette section) toute info
**durable** importante — décision, accès, fix, état des sources, méthode — **sans
attendre qu'on le demande**. La doc est la mémoire du projet entre les sessions.

---

## 14. Workflow worktree Claude Code — IMPORTANT

Claude Code peut travailler dans un **worktree Git** isolé situé dans `.claude/worktrees/<nom>/`. C'est une copie temporaire du projet où l'instance Claude fait ses modifications, **séparée du repo principal** que GitHub Desktop voit (`/Users/siku/Documents/Tik/`).

**Conséquence importante** : tant que l'instance Claude n'a pas **copié explicitement** un fichier modifié du worktree vers le repo principal, **GitHub Desktop ne le voit pas** et l'utilisateur ne peut pas le commit/push.

### Règle pour toute instance Claude

**À chaque modification d'un fichier dans le worktree** (via `Edit`, `Write`, ou autre), tu DOIS immédiatement le copier vers le repo principal avec une commande Bash :

```bash
cp /Users/siku/Documents/Tik/.claude/worktrees/<TON_WORKTREE>/<chemin_relatif> /Users/siku/Documents/Tik/<chemin_relatif>
```

**Ne demande JAMAIS à l'utilisateur de faire cette copie manuellement.** Le faire toi-même via le Bash tool est la règle. Sinon l'utilisateur croit que le travail est fait et essaie de push via GitHub Desktop, mais GitHub Desktop ne voit rien — frustration assurée.

### Exception

Si tu créés un fichier dans le repo principal directement (chemin absolu commençant par `/Users/siku/Documents/Tik/` sans `.claude/worktrees/`), tu n'as pas besoin de copier — il est déjà au bon endroit.

### Vérification que tu fais bien

Après une session, l'utilisateur ouvre GitHub Desktop et **doit voir tous les fichiers modifiés** dans la liste des changements. S'il ne voit que des dossiers `.claude/worktrees/` ou « rien à committer » alors qu'on a fait des modifs, c'est que la sync n'a pas été faite. **C'est un bug bloquant**.

### Pattern recommandé pour les modifications en lot

À la fin d'une étape avec plusieurs fichiers touchés, faire un `cp` groupé via une seule commande Bash :

```bash
WORKTREE=/Users/siku/Documents/Tik/.claude/worktrees/<nom>
MAIN=/Users/siku/Documents/Tik
cp "$WORKTREE/path1" "$MAIN/path1"
cp "$WORKTREE/path2" "$MAIN/path2"
# etc.
```

---

*Dernière mise à jour : 2026-06-24 (fusion macro+micro ADR-033 **ACTIVÉE en prod** sur le VPS + fix UI micro `degraded`≠fake-news + audit E2E/navigation + note « Accès & déploiement VPS » dans ## 8). Avant : 2026-06-22 (ADR-032 Corrélations cross-asset Yahoo, CONTEXTE strict — 4e/dernière famille macro de contexte, après ADR-030 régime de risque + ADR-031 stablecoins). Journal détaillé des livraisons (Paquets 1→50) déplacé dans [`HISTORIQUE.md`](HISTORIQUE.md) ; cette section ne garde plus que l'état courant (cf. ## 8).*
*Version Tik : Core MVP + multi-overlay swing/flash OSINT pur (ADR-018) + dashboard Expo + SDK gelé (ADR-022) + notifications Telegram. Détail par composant dans HISTORIQUE.md.*
*Mainteneur : utilisatrice solo + assistant Claude.*
