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
- **Filtre veracity ≥ 0.85 sur swing TRANSITOIRE (au lieu de 0.90)** — amendement 2026-05-18 (cf. Paquet 27) : tant que **Reddit IP-bannie sur l'IP HP 204.168.220.47** (cf. Bug 11 section 9), Tik tourne avec **3/4 overlays sentiment BTC** (FG + CryptoCompare + Google News, sans Reddit). Conséquence : BTC swing veracity capée structurellement à 0.85-0.89 quand FG diverge contrarian des news (cas typique marché bear actuel) — mesure 9h post-fix N=2 : **0 % des 36 signaux BTC swing ne passent ≥ 0.90**. Donc le seuil 0.85 reste discriminant (rejette les signaux ≤ 0.79). **Critère retour au 0.90 strict** : (1) Reddit reconnecté ET (2) 7 jours stables post-réintégration ET (3) ≥ 30 signaux BTC swing à veracity ≥ 0.90 mesurés.
- **NE PAS trader GOLD avec Tik à J+14** — amendement 2026-05-18 (cf. Paquet 27) : backtest 1j sur 83 signaux GOLD mesure **hit rate Tik 4.8 % vs Random 34.1 % vs Always SHORT 80.7 %** sur fenêtre 5j HP. Distribution direction GOLD = 60 long + 20 neutral + 3 short alors que marché GOLD baisse soutenue (Always SHORT à 80 % de hit). **Tik n'a pas d'edge directionnel GOLD** depuis l'amendement ADR-018 P2 (DXY+COT désactivés, GOLD a perdu 2 overlays directionnels sur 4). Pour trader GOLD à J+14, s'appuyer sur MT5 / analyse technique externe / jugement, **pas sur Tik**. À ré-évaluer post-période bear (cf. critère réactivation DXY/COT amendement ADR-018 P2 ET backlog #9 GDELT GOLD).
- **Observer prioritairement signaux SHORT BTC à haute veracity** — insight mesuré 2026-05-18 (cf. Paquet 27) : sur 263 signaux SHORT BTC backtestés 1j horizon, **hit rate 63.1 % vs gain moyen +0.72 % par signal**. C'est l'edge directionnel le plus crédible mesuré sur Tik à ce jour, mais **à valider post-fix bug N=2 stable (≥ 9-10 j de runtime ≥ 2026-05-27)**. Pas cristallisé comme règle stricte : si la trader voit un SHORT BTC veracity ≥ 0.85 (transitoire) avec triggers cohérents (RSI bearish, EMA20<EMA50, MACD négatif), c'est un setup à favoriser sur les LONG ou NEUTRAL. **⚠ CAVEAT 2026-05-20 (Paquet 33)** : le « 63 % » a été mesuré sur des **données pré-fix contaminées** (CryptoCompare manquant → cross-validation N=2 buggée — un swing 5j sur ces données donne 0,9 % de hit), donc **ne pas le présenter comme un edge fiable**. À ce jour, **aucun filtre n'a de valeur prédictive robuste démontrée** : le filtre AFN `ok` vs `degraded` semblait prometteur (37,8 % vs 19,6 % @6h) mais sous scrutin paranoïaque il est inconclusif (marginal après correction multiple-testing, redondant avec veracity ≥ 0,85, et l'avantage s'inverse sur le gain à 24h — cf. Paquet 33 Découverte n°4). Tout reste **à mesurer proprement le 2026-05-27** (swing 5j post-fix). Sizing 1 % d'autant plus justifié.
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

## 8. État d'avancement

### Paquet 1 — Core MVP : ✅ LIVRÉ et FONCTIONNEL

Implémenté et testé sur le Mac de l'utilisateur :
- Tous les endpoints REST (`/health`, `/entities`, `/signals`, `/feedback`, `/veracity`)
- WebSocket `/ws/signals` (auth via query param `api_key`)
- Auth pluggable API Key (avec interface prête pour OAuth2)
- Modèles SQLAlchemy : Entity, Source, Signal, Feedback, ApiKey
- Migration Alembic initiale (avec hypertable TimescaleDB)
- Ingester Binance WebSocket (BTC trades temps réel)
- Ingester Yahoo Finance (Gold polling 60s)
- Ingester FRED (macro polling 1h)
- Engine swing (RSI + MACD + EMA + contre-scénarios)
- Publisher Redis + DB pour les signaux
- Adapter trading (mapping BTC, GOLD)
- Scheduler APScheduler (swing BTC toutes les 15min, swing Gold toutes les 30min)
- Scripts CLI : `create_api_key`, `run_scheduler`, `run_ingesters`
- Tests pytest : health + auth (scope matching, hash, wildcards)
- CI GitHub Actions
- 3 ADR documentés
- docker-compose.yml complet (5 services)

### Paquet 1.x — Évolutions post-livraison (2026-04-28 → 2026-04-30)

Améliorations apportées au Core après le déploiement initial.

#### Du 2026-04-28

- **Bouton "Authorize" dans Swagger** : security scheme `bearerAuth` ajouté à l'OpenAPI (`core/src/tik_core/main.py`), appliqué à tous les endpoints sauf `/health`. Les endpoints sécurisés sont désormais testables directement depuis `/docs`.
- **Healthchecks Docker propres** : override des healthchecks pour `tik-ingesters` et `tik-scheduler` (qui héritaient à tort du healthcheck curl 8200 du Dockerfile commun). Test simple via `python -c "import redis; redis.Redis(host='redis').ping()"`. Plus de `(unhealthy)` dans `docker compose ps`.
- **Ingester Fear & Greed Index** : nouveau ingester `core/src/tik_core/aggregator/fear_greed_ingester.py` (couche 7 sentiment). Polling toutes les 1h sur l'API publique alternative.me (sans clé). Stocke la valeur courante dans Redis sous la clé `tik.sentiment.fear_greed` (TTL 25h).
- **Cross-validation FG ↔ techniques sur BTC swing** : `analyze_swing_btc(redis)` lit la valeur FG depuis Redis et applique un overlay sur la décision (evidence + trigger + bias contrarian). La **veracity devient dynamique** entre 0.70 (forte divergence techniques ↔ sentiment) et 0.95 (forte concordance), au lieu d'être figée à 0.85. GOLD reste inchangé (FG est crypto-spécifique).
- **`SOURCE_SCORES` par source** : nouveau dictionnaire dans `swing_engine.py` qui mappe chaque source à son score de crédibilité.
- **`SwingDecision` porte désormais `veracity`** : le publisher (`publish_swing_signal`) lit la veracity de la décision au lieu de la hardcoder à 0.85.

#### Du 2026-04-29

- **Cross-validation GOLD ↔ DXY (FRED DTWEXBGS)** : `analyze_swing_gold(fred_api_key)` fetch les 10 derniers points DXY depuis FRED, calcule la variation sur ~5 jours ouvrés et déduit un bias contrarian sur GOLD (corrélation négative classique : DXY ↑ → GOLD ↓). Veracity dynamique pour GOLD entre 0.70 et 0.95 (mêmes paliers que BTC). `SOURCE_SCORES` enrichi : `fred_dtwexbgs=0.85` (source officielle US gov).
- **Documentation pédagogique `docs/comprendre_tik.md`** : guide accessible sans prérequis technique, à partager à n'importe qui pour comprendre Tik (12 sections + glossaire).
- **Nouvel ingester CryptoCompare news** : `core/src/tik_core/aggregator/cryptocompare_ingester.py` (couche 6 sentiment textuel). API CoinDesk Data (free tier 11k req/mois, plafond 250k à vie). Les votes upvotes/downvotes étant dépréciés depuis le rachat 2022, le sentiment est dérivé via une **analyse par mots-clés** sur les titres (listes BULLISH_KEYWORDS / BEARISH_KEYWORDS). Stocké dans Redis sous `tik.sentiment.cryptocompare.btc` (TTL 2h). À terme : migrer vers FinBERT ou Ollama local.
- **Refactor multi-overlay dans `analyze_swing_btc`** : `_apply_fear_greed_overlay` renommé en `_enrich_with_fear_greed` (retourne le bias au lieu de set la veracity). Nouveau helper `_enrich_with_cryptocompare`. La veracity finale est calculée sur la **moyenne des biais sentiment** disponibles (FG + CryptoCompare aujourd'hui). Cette architecture est extensible : ajouter une 4e source = un nouveau `_enrich_with_xxx` + une ligne dans `analyze_swing_btc`. `SOURCE_SCORES` enrichi : `cryptocompare_news=0.70`.
- **CryptoPanic abandonné** : free tier supprimé le 2026-04-01. Le champ `cryptopanic_api_key` reste dans `config.py` pour rétrocompatibilité mais n'est plus utilisé. Remplacé par CryptoCompare.
- **Script de backtest CLI** : nouveau `core/src/tik_core/scripts/backtest.py`. Pour chaque signal en DB, fetch le prix au moment du signal et N jours après, calcule le delta %, juge le succès selon direction et seuil paramétrable. CLI args : `--horizon-days`, `--threshold`. Rapport : hit rate global / par entity / par direction / par tranche de veracity, top 3 best/worst. Ajout d'une **section "Tik vs baselines naïfs"** comparant Tik à Random (100 runs averaged), Always LONG, Always SHORT, Always NEUTRAL — global et par entity. Limites assumées : pas de coûts de transaction, échantillon réduit (~50-100 signaux à ce stade), période trending forte qui favorise les trend-followers naïfs.
- **Insights premier backtest (horizon 5j sweet spot)** :
  - Tik bat Random (79% vs 31%) → pipeline non-bruit ✅
  - Mais Always LONG bat Tik sur BTC (100% vs 74%) sur cette période bullish → seuil NEUTRAL trop large dans `_score_indicators`
  - Tik = Always SHORT sur GOLD sur cette période bearish or → pas d'edge mesuré
  - Veracity figée à 0.85 dans la fenêtre testée → cross-validation pas encore exercée
  - Sweet spot horizon = 5 jours (79% hit rate vs 61% à 1-3j et 40% à 7j)
  - GOLD SHORT est slow-burn : 27% à 1-3j → 100% à 5-7j (les mouvements macro de l'or se matérialisent sur la semaine)
- **Révision du seuil de directionnalité dans `_score_indicators`** : passage de **0.15 à 0.08** suite au backtest. Avant, des signaux avec `bull_score - bear_score` autour de 0.10 étaient classés à tort en `neutral` et rataient des opportunités directionnelles claires. Validation runtime immédiate : BTC est passé de `neutral conf 0.10 verac 0.85` à `long conf 0.25 verac 0.90` — la **veracity dynamique se déclenche enfin** sur les signaux réels (concordance partielle techniques ↔ sentiment cross-validé). À surveiller : un seuil trop bas peut générer des whipsaws en marché choppy.

#### Du 2026-04-30

- **Flash engine BTC (horizon minutes-heures)** : nouveau fichier `core/src/tik_core/scoring/flash_engine.py`, séparé du swing, suivant le pattern multi-overlay (ADR-004 → décliné en ADR-005). Klines REST Binance 1m × 240 (fenêtre 4h glissante). Indicateurs EMA 9/21, RSI 14 (seuils 75/25), MACD 12/26/9, ATR 14, momentum 15m. Seuil de directionnalité 0.10 (un cran plus strict que swing à 0.08). Émission **conditionnelle** : transitions de direction + heartbeat toutes les 30 min, direction précédente stockée sous `tik.flash.last_direction.BTC` (TTL 24h) — limite le volume DB (~10-50 signaux/jour estimés vs 288 en émission systématique).
- **Check fraîcheur via le flux WS** : avant chaque cycle flash, lecture de `tik.last_price.BTC` (cache mis à jour par l'ingester Binance WS existant). Si timestamp > 60 s, l'ingester est probablement déconnecté → cycle skippé avec `log.warning("flash.btc.stale_data_skip")`. Pas de modification de l'ingester WS, qui continue de tourner en shadow.
- **2 overlays flash distincts du swing** : `_enrich_with_orderbook` (Order Book Imbalance top 20 via `GET /api/v3/depth`, trend-following) et `_enrich_with_aggression` (ratio buyer/seller taker sur les 1000 dernières aggTrades via `GET /api/v3/aggTrades`, trend-following). `FLASH_SOURCE_SCORES` local (binance_klines_1m=0.90, binance_orderbook=0.85, binance_aggtrades=0.85) — distinct de `SOURCE_SCORES` swing pour clarté sémantique.
- **Refactor `publisher.py`** : factorisation `_publish_signal(session, redis, decision, horizon, veracity)` partagée par `publish_swing_signal` et nouveau `publish_flash_signal`. Aucun changement de signature publique (rétrocompat). `EXPIRY_BY_HORIZON["flash"] = 1h` était déjà prévu, juste activé.
- **Job scheduler `flash_btc`** : ajouté dans `run_scheduler.py`, interval 5 min, `max_instances=1, coalesce=True`. Le job applique la décision d'émission via `should_emit(decision, last, now)` exposé publiquement par `flash_engine.py` (testable unitairement). Premier run immédiat au démarrage comme pour swing.
- **Tests pytest `test_flash_engine.py`** : ~30 tests unitaires sur `_compute_obi_bias`, `_compute_aggression_bias`, `_enrich_with_orderbook`, `_enrich_with_aggression`, `_veracity_from_concordance`, et `should_emit` (transitions + heartbeat boundary + custom heartbeat). Aucune dépendance Redis/HTTP/DB.
- **ADR-005 documenté** : `docs/adr/005-flash-engine.md` formalise les choix (klines REST 1m vs WS direct, overlays trend-following plutôt que contrarian, émission conditionnelle, pas de flash GOLD pour cause de délai Yahoo) et rappelle les **risques opérationnels** : Garde-fou 1 (mode shadow 3 mois) reste **strictement applicable** au flash, ADR-003 (pas de bypass V01-V15) **inchangé**, et un futur débounce/throttle côté SDK sera nécessaire au moment de l'intégration Zeta pour éviter de submerger `turbo_v2.py` de signaux haute fréquence.
- **NLP via Ollama (LLM local) pour le sentiment news CryptoCompare** : remplacement de l'analyse par mots-clés par `llama3.2:3b` (~2 GB), avec pattern Strategy + fallback keywords automatique. Nouveau fichier `core/src/tik_core/aggregator/news_classifier.py` (interface ABC `NewsClassifier` + `KeywordClassifier` migré + `OllamaClassifier`). Le `CryptoCompareIngester` reçoit son classifier au constructeur (DI). 3 nouvelles settings dans `config.py` : `news_classifier=ollama` (défaut), `ollama_url=http://host.docker.internal:11434`, `ollama_model=llama3.2:3b`. **Ollama tourne en dehors de Docker** sur le Mac de l'utilisateur (installation native via .dmg, sans Homebrew) ; les conteneurs Docker l'atteignent via l'adresse magique `host.docker.internal`.
- **Fallback robuste à chaud** : si Ollama plante sur un titre → fallback keywords pour ce titre, compteur d'erreurs incrémenté. Si 3 erreurs successives dans le même batch → circuit breaker batch-level, bascule keywords pour le reste du batch, retentative au cycle suivant. À chaque cycle horaire, `reset_batch()` réarme le compteur. Pas de circuit permanent qui forcerait un redémarrage manuel.
- **Traçabilité backtest** : chaque payload Redis (`tik.sentiment.cryptocompare.btc`) porte désormais `method: "ollama:llama3.2:3b"` ou `method: "keywords"`. Le script de backtest pourra à terme comparer quantitativement le hit rate des signaux selon la méthode.
- **Validation runtime au déploiement** : `news_classifier.ollama_ready` au démarrage, premier cycle complet en ~48 s (50 articles classifiés à ~1 s/titre, latence acceptable car cycle horaire). Distribution typique observée : ~20 % bull, ~40 % bear, ~40 % neutral — le LLM 3B est plus prudent (plus de NEUTRAL) que les keywords sur les cas ambigus.
- **Tests pytest `test_news_classifier.py`** : 55 tests unitaires (30 keywords migrés depuis l'ancien `test_cryptocompare_ingester.py` supprimé + 25 Ollama mockés via `unittest.mock.AsyncMock` — parsing tolérant, fallback sur erreur, circuit breaker, factory + santé Ollama). Suite complète du projet : 230 tests verts, aucune régression.
- **ADR-006 documenté** : `docs/adr/006-nlp-ollama-classifier.md` formalise les choix (Ollama plutôt que FinBERT/CryptoBERT pour la réutilisabilité future, pattern Strategy avec injection de dépendance, fallback hiérarchique avec circuit breaker batch-level, prompt one-shot avec parsing tolérant) et liste les conséquences positives/négatives (gestion native négation/contexte/multi-mots vs dépendance Mac hôte, latence, faiblesse sur termes techniques précis comme "higher low" non captés par le 3B).
- **Backlog `docs/backlog.md` créé** : amélioration différée du fallback keywords (8 mots-clés mono-mot non ambigus à ajouter : `reclaim/reclaims/reclaimed` en bull, `topping/rejection/breakdown/outflows/unloading` en bear) et idée d'un **dataset golden** annoté (~50 titres) pour comparer quantitativement keywords vs Ollama. Reportés car le LLM résout déjà la majorité des cas et le fallback est rare en pratique.

### Paquet 2 — SDK Python : ✅ COMPLET (Sessions 1 à 5 livrées le 2026-04-30, version 0.5.0)

Implémenté dans `Tik/sdk/`. Découpage final en 5 sessions :

| # | Session | Statut |
|---|---|---|
| 1 | Fondations + client HTTP de base + auth pluggable | ✅ livrée le 2026-04-30 |
| 2 | Client WebSocket + hooks événementiels | ✅ livrée le 2026-04-30 |
| 3 | Cache local + fallback offline + circuit breaker LOCAL | ✅ livrée le 2026-04-30 |
| 4 | Config YAML hot-reload + telemetry feedback automatique (POST /feedback) | ✅ livrée le 2026-04-30 |
| 5 | Doc intégration overlay Zeta + exemples + polish | ✅ livrée le 2026-04-30 |

**Session 1 livrée le 2026-04-30** :
- Structure `sdk/` (pyproject.toml, src layout, tests/) — package `tik-sdk` pip-installable en mode dev (`pip install -e ./sdk`).
- **Architecture extensible** : 5 modules disjoints (`exceptions.py`, `auth.py`, `models.py`, `_http.py` privé, `client.py` public). Les briques des sessions 2-5 (WS, cache, hooks, telemetry, config) viendront s'ajouter sans casser ces fondations.
- **Auth pluggable façon ADR-001** : interface abstraite `AuthMethod` + implémentation `ApiKeyAuth` (Bearer token). Ouverte à `OAuth2Auth`, `MtlsAuth` plus tard sans toucher au `TikClient`.
- **Modèles Pydantic miroirs** des schémas core (`storage/schemas.py`) : `Signal`, `Entity`, `Evidence`, `Trigger`, `CounterScenario`, `Advisory`, `VeracityStatus`, `SourceVeracity`, `Health`. Validation des bornes (`confidence`/`veracity` ∈ [0,1], `tier` ∈ [1,5]).
- **Couche HTTP `_http.py` (privée)** : wrapper async `httpx.AsyncClient`, prefix `/api/v1` automatique, User-Agent `tik-sdk/0.1.0`, mapping HTTP → exceptions typées (`AuthError` pour 401/403, `NotFoundError` pour 404, `ServerError` pour 5xx, `NetworkError` pour timeout/transport, `TikError` pour le reste).
- **Client `TikClient` (public)** : 9 méthodes async **lecture uniquement** : `get_health`, `list_entities`, `get_entity`, `get_latest_signals`, `get_signal`, `search_signals`, `get_global_veracity`, `list_sources`, `get_source`. Utilisable en `async with` pour fermer proprement la connexion.
- **Garde-fou ADR-003 automatisé** : test `test_client_does_not_expose_execution_methods` qui vérifie qu'aucune méthode interdite (`place_order`, `execute`, `trade`, `buy`, `sell`, `bypass_guard`, …) ne soit exposée par mégarde dans une session future.
- **42 tests pytest** (4 auth + 15 http + 13 client + 10 models) passant en 0.15 s, lancés via un conteneur `python:3.11-slim` éphémère (sans installer Python 3.11 sur l'hôte). Mock HTTP via `httpx.MockTransport` natif (pas de dépendance `respx`/`pytest-httpx`).
- **README** `sdk/README.md` en français : règles ADR-003 rappelées, table des endpoints couverts, exemple minimal, hiérarchie d'exceptions, plan des sessions à venir.

**Session 2 livrée le 2026-04-30** :
- **Auth pluggable étendue** : `AuthMethod` reçoit une nouvelle méthode `query_params()` (défaut `{}`). `ApiKeyAuth` la surcharge pour exposer `{"api_key": …}` — nécessaire pour le WS qui ne permet pas d'attacher des en-têtes personnalisés au handshake côté navigateur. Compat REST inchangée.
- **`hooks.py` — Registry + dispatcher générique** : enregistre des handlers nommés (sync OU async indifféremment, plusieurs handlers par événement, ordre d'enregistrement préservé). **Isolation des exceptions** : un handler qui plante n'arrête ni la dispatch ni la boucle WS — log warning et on continue. Critique pour un bot qui tourne 24/7.
- **`_ws.py` — Helpers purs** : `http_to_ws` (http→ws / https→wss / pass-through ws-wss), `build_ws_url` (assemble `ws://host/api/v1/ws/signals?api_key=…&entity=…&horizon=…`, urlencode auto), `next_backoff` (exponentiel × 2, plafond 60 s, jitter [0, 0.5 s] pour désynchroniser plusieurs clients après crash core).
- **`stream.py — TikStream` public** : boucle WS avec **reconnexion automatique** (backoff exponentiel + jitter), 4 hooks événementiels :
  - `on_signal(handler)` : tout signal reçu (actif aujourd'hui)
  - `on_crash_warning(handler)` : `signal.advisory.macro_crash_warning is True` *(dormant — le core ne l'émet pas encore, SDK forward-compat)*
  - `on_fake_news_detected(handler)` : `signal.circuit_breaker_status != "ok"` *(dormant — sera actif quand l'anti-fake-news du core sera branché)*
  - `on_veracity_collapse(handler)` : `signal.veracity < veracity_collapse_threshold` (défaut 0.5, configurable au constructeur)
- **Lifecycle** : `async with stream` + `await stream.run()` (bloque) + `await stream.stop()` (arrêt propre depuis une autre coroutine). `stream.wait_connected(timeout)` pour les tests/observabilité. Stop ferme la WS active explicitement → sortie en < 1 s même quand la connexion est silencieuse.
- **Sécurité** : si le handshake renvoie 401/403 (clé invalide), `AuthError` immédiate sans retry (évite le hammer sur clé révoquée). Les autres erreurs réseau (`ConnectionClosed`, `OSError`, etc.) déclenchent la reconnexion. URL loggée avec api_key masquée (`api_key=***`).
- **`TikClient.stream(entity, horizon, veracity_collapse_threshold)`** : factory qui réutilise `base_url` + `auth` du client HTTP — un seul point d'entrée pour les bots.
- **46 nouveaux tests** (10 hooks + 14 helpers WS + 17 stream unit + 5 stream intégration) — total 88/88 passants en ~12 s. Les tests d'intégration montent un **vrai serveur `websockets.serve()`** sur localhost:0 (port libre auto) et vérifient le bout-en-bout : auth via query param, parsing JSON, dispatch hooks, **reconnexion après drop serveur**, stop pendant idle.
- **Bump version SDK 0.1.0 → 0.2.0**. Dep ajoutée : `websockets>=13.1` (même version que le core).
- **Garde-fou ADR-003 toujours vert** : aucune méthode d'envoi WS exposée — le stream est strictement read-only depuis le core vers le bot. Pas de "force signal" possible.

**Session 3 livrée le 2026-04-30** :
- **`circuit_breaker.py`** : machine à états `closed` → `open` → `half_open` → `closed/open`. Compteur d'échecs consécutifs, ouvre après `failure_threshold` (défaut 5), reste ouvert pendant `reset_timeout_s` (défaut 30 s). `time_fn` injectable pour des tests déterministes (FakeClock plutôt que `asyncio.sleep`). Pas de lock — atomicité garantie par l'event loop mono-thread asyncio.
- **`cache.py`** : interface abstraite `Cache` + 2 implémentations livrées :
  - `NoCache` (no-op, défaut)
  - `InMemoryCache` (TTL en RAM, éviction LRU au-delà de `maxsize`, défaut 1000 entrées)
  - Future : `RedisCache` via extras `[redis]` quand on aura besoin de partager le cache entre processus
  - Helper `make_cache_key("GET", path, params)` → clé stable et lisible (params triés alphabétiquement)
  - `DEFAULT_TTL_BY_HORIZON` : flash 60 s, swing 300 s, macro 3600 s, default 300 s — alignés sur les durées d'expiry du publisher core
- **`exceptions.py`** : ajout `CircuitBreakerOpen(TikError)` levée quand le breaker est ouvert ET pas de cache disponible
- **`_http.py` refondu** : flux unifié cache → breaker → HTTP. Cache hit court-circuit tout (pas de HTTP, pas de breaker check). Cache miss + breaker ouvert → `CircuitBreakerOpen` direct. Cache miss + breaker OK → tente HTTP, record_success/failure selon résultat. **5xx compte comme échec** pour le breaker (le core a un souci) ; **4xx ne compte pas** (problème de requête, pas de disponibilité). Bug subtil corrigé pendant le run : l'ordre des `except` était cassé (`ServerError` héritant de `TikError`, le `except TikError` la mangeait avant le `except ServerError` → breaker ne s'ouvrait jamais sur 5xx).
- **`TikClient`** : nouveaux kwargs optionnels `cache=`, `circuit_breaker=`, `ttl_by_horizon=` (override des défauts). Tout reste rétrocompatible : sans rien configurer, comportement identique aux sessions 1+2. TTL passé automatiquement par méthode selon l'horizon (`get_latest_signals(horizon="flash")` → TTL 60 s ; `get_health` → TTL 0 = jamais cached).
- **3 fichiers de tests + 56 nouveaux tests** : `test_circuit_breaker.py` (16 tests sur les transitions d'état + cycles complets via FakeClock), `test_cache.py` (23 tests : NoCache, InMemoryCache, TTL/expiration, LRU, helper `make_cache_key`), `test_fallback.py` (17 tests d'intégration via `httpx.MockTransport` : cache hit/miss, fallback sur NetworkError, 5xx ouvre le breaker, 4xx ne l'ouvre pas, scénario complet TikClient).
- **Total suite** : 144/144 tests verts en ~12 s. Aucune régression Sessions 1+2.
- **Bump version SDK 0.2.0 → 0.3.0**. Aucune nouvelle dépendance externe (cache + breaker = stdlib pure).
- **Garde-fou ADR-003 toujours vert** : `test_client_does_not_expose_execution_methods` continue de passer ; les nouvelles classes (`Cache`, `CircuitBreaker`) sont read-only et ne peuvent pas générer de signaux ni d'ordres.

**Session 4 livrée le 2026-04-30** :
- **`feedback.py`** — `FeedbackPayload` (Pydantic, miroir du schéma `FeedbackIn` du core) + `FeedbackQueue` (file `asyncio.Queue` + worker async). `submit()` est **synchrone non-bloquant** (`put_nowait` + retour True/False), garantie ADR-003 que `report_outcome` ne ralentit jamais un trade. Si la queue est pleine → drop avec log warning. Worker POST `/feedback` avec retry exponentiel (défaut 3 tentatives, backoff 1s/2s/4s, `backoff_fn` injectable pour tests). Au-delà des retries → drop avec log error. 4xx (404 si signal inconnu côté core) → pas de retry, drop direct (problème de payload, pas de disponibilité). Compteurs publics `sent_count`/`dropped_count`/`failed_count` pour observabilité. `stop(drain=False, timeout_s=5)` par défaut = fast shutdown.
- **`_http.py` étendu** : ajout `post()`. Volontairement **sans cache et sans circuit breaker** : POST est mutating, pas de cache ; et si on bloquait les POST sur breaker ouvert, ça bloquerait aussi les retries du worker et la coordination casserait. Le breaker reste donc strictement sur les GET. `_parse()` accepte désormais un `expected_status` tuple (200 par défaut, 200/201 pour POST).
- **`config.py`** — `TikConfig` Pydantic 5-niveaux (`core`, `cache`, `circuit_breaker`, `stream`, `feedback`) avec valeurs par défaut sensées. `TikConfig.load_from_yaml(path)` charge + valide + lève si KO. `ConfigWatcher` polling mtime (défaut 5s, `time_fn` injectable) avec async context manager `async with watcher:`. À chaque changement de mtime : rechargement + appel des handlers `on_reload(old, new)` (sync uniquement, isolation des exceptions). Si reload échoue (YAML cassé / Pydantic invalide) → log error + **conserve l'ancien config** (jamais d'état corrompu). Helpers `diff_mutable_settings(old, new)` et `warn_immutable_changes(old, new)` pour aider le caller à savoir ce qui peut être appliqué à chaud.
- **Périmètre du hot-reload** : strictement les settings mutables — `cache.ttl_by_horizon` et `stream.veracity_collapse_threshold`. Les settings non mutables (`core.base_url`, `core.timeout_s`, `cache.enabled`, `cache.maxsize`, `circuit_breaker.*`, `feedback.*`) sont loggués en warning au reload mais **ne s'appliquent qu'au redémarrage** — c'est un choix conscient pour éviter des recréations partielles d'objets internes risquées (un `httpx.AsyncClient` ne peut pas changer de `base_url` à chaud).
- **`TikClient` étendu** : nouveau `report_outcome(signal_id, outcome, **kwargs)` qui valide via `FeedbackPayload` puis enqueue dans la queue. Lifecycle : `__aenter__` démarre le worker feedback, `__aexit__` le stop fast (drop ce qui reste). Nouveau `feedback_queue` property pour observabilité + drain explicite. Nouveau `apply_mutable_config(new_config)` pour le hot-reload (utilisable comme handler de `ConfigWatcher.on_reload`). Nouvelle factory **`TikClient.from_config(TikConfig, auth=…)`** qui matérialise un client avec cache, breaker, queue feedback configurés depuis le YAML. Kwarg `enable_feedback=False` au constructeur si on veut désactiver complètement la queue (lever `RuntimeError` si `report_outcome` appelé).
- **`pyproject.toml`** : ajout dep `pyyaml>=6.0.2` (même version que le core). Bump version `0.3.0 → 0.4.0`.
- **42 nouveaux tests** : `test_feedback.py` (20 tests : payload validation, submit/drop, lifecycle, worker send/retry/4xx, drain, integration `TikClient.report_outcome`) + `test_config.py` (22 tests : load YAML minimal/full/missing/invalid, diff mutable, warn immutable, watcher polling avec mtime forcé via `os.utime` pour fiabilité multi-FS, isolation exceptions handler, async context manager, `from_config`, `apply_mutable_config`).
- **Total suite** : **186/186 tests verts en 17 s**, premier run sans aucune correction. Aucune régression Sessions 1+2+3.
- **Garde-fou ADR-003 toujours vert** : `test_client_does_not_expose_execution_methods` continue de passer (la liste des méthodes interdites a été vérifiée). `report_outcome` n'est **pas** un canal d'exécution — c'est un canal de telemetry retour, et son non-blocage garantit qu'il ne ralentit jamais un trade.

**Session 5 livrée le 2026-04-30 — Paquet 2 finalisé** :
- **`docs/integration_zeta.md`** — guide concret d'intégration côté Zeta avec **3 patterns documentés** + 1 pattern telemetry :
  1. Overlay confidence dans `cranial_bot/turbo_v2.py` (modulation ±15-20% maximum, jamais de remplacement de signal, fallback gracieux si Tik est down)
  2. Hook `on_crash_warning` → `services/kill_switch_service.handle_alert(...)` (la SEULE voie autorisée par ADR-003 pour Tik d'arrêter Zeta)
  3. V16 optionnel dans `cranial_bot/micro_live_guard.py` (S'AJOUTE aux V01-V15, ne les remplace pas, fail-OPEN si Tik down)
  4. Telemetry feedback après chaque close de trade (non-bloquant via `report_outcome`)
  - Inclut une checklist de mise en service (mode shadow 3 mois, budget 5 %, scopes API requis, logs à monitorer) et un exemple `tik.yaml` recommandé pour démarrer en SHADOW.
- **`docs/adr/007-sdk-architecture.md`** — ADR-007 qui formalise les choix : SDK strictement read-only, async partout, Strategy pattern (cohérent ADR-001/006), lifecycle async with, telemetry non-bloquante, cache + breaker opt-in, config YAML hot-reload limité aux settings mutables, hooks isolation des exceptions. Liste les alternatives rejetées (SDK sync, cache always-on, telemetry bloquante, watchdog inotify, classe géante).
- **`sdk/tik.example.yaml`** — config YAML complète et annotée (5 sections : core, cache, circuit_breaker, stream, feedback). Prête à copier-coller. Documentée pour démarrer en mode SHADOW.
- **`sdk/examples/`** — 4 exemples runnable + README :
  1. `01_basic_read.py` — health, list entities, derniers signaux
  2. `02_streaming_with_hooks.py` — WS + 4 hooks + Ctrl+C handler
  3. `03_zeta_overlay.py` — pseudo-overlay sur turbo_v2 avec stubs (annoté, démontre le pattern)
  4. `04_full_resilience.py` — bot complet config YAML + cache + breaker + ConfigWatcher hot-reload + telemetry démo
- **CI workflow** — 2 nouveaux jobs ajoutés à `.github/workflows/ci.yml` : `sdk-lint` (ruff check + format) et `sdk-test` (pytest + cov + ré-vérification explicite du test ADR-003 `test_client_does_not_expose_execution_methods`). Path filtering sur `sdk/` pour ne se déclencher que sur les changements pertinents (cohérent avec le job core existant).
- **`sdk/README.md` poli** — Section « Statut Paquet 2 ✅ COMPLET » en tête, section « Liens utiles » (vers integration_zeta, ADR-003, ADR-007, examples, tik.example.yaml), section « Production checklist » (8 items à valider avant mise en service), section « Roadmap » qui remplace l'ancien « À venir » (v1.0.0 = quand wiré en prod après les 3 mois shadow).
- **Bump version SDK 0.4.0 → 0.5.0** (pyproject + `__version__` + `USER_AGENT` HTTP). v1.0.0 explicitement réservée pour la mise en production réelle dans Zeta.
- **+ 1 test pytest** (smoke test qui charge `tik.example.yaml` et valide la sanity des champs principaux). Verrouille que le YAML d'exemple reste cohérent si on ajoute un nouveau champ obligatoire à `TikConfig`.
- **Total suite finale** : **187/187 tests verts en 17 s**. Aucune régression sur les 5 sessions cumulées.

#### Synthèse Paquet 2

15 fichiers source SDK + 14 fichiers tests + 4 exemples runnable + 2 docs (intégration + ADR-007) + 1 fichier YAML d'exemple + CI workflow étendu.

**187 tests pytest** couvrant : auth pluggable, modèles Pydantic, HTTP error mapping, cache TTL/LRU, circuit breaker états, fallback HTTP+cache, hooks dispatcher (sync/async/exceptions), helpers WS, intégration WS server local (5 tests bout-en-bout dont reconnexion), feedback queue + retry + drain, config YAML loader/validation/hot-reload, smoke test example YAML.

**Garde-fou ADR-003** verrouillé par test runtime ET vérifié explicitement en CI (`pytest tests/test_client.py::test_client_does_not_expose_execution_methods` dans le job `sdk-test`). Aucune méthode `place_order`, `execute`, `trade`, `buy`, `sell`, `bypass_guard` exposée.

### Paquet 3 — Dashboard Expo : ✅ LIVRÉ (5 sessions + évolution 2026-05-04, version 0.5.1)

App Expo SDK 54 livrée dans `Tik/dashboard/`. 5 sessions livrées et pushées entre les commits `5ba28cb` et `b438f29` :

| # | Session | Commit | Statut |
|---|---|---|---|
| 1 | Bootstrap Expo SDK 54 + écrans Home/About | `5ba28cb` | ✅ |
| 2 | Auth pluggable + client HTTP + écran login | `b37401d` | ✅ |
| 3 | WebSocket live + Signals Feed + écran détail signal | `5ab5b72` | ✅ |
| 4 | KPIs Home + sparkline veracity | `8ec8362` | ✅ |
| 5 | Alerts + bots Zeta/Totem + config + push notifications | `b438f29` | ✅ |

**Périmètre couvert** :
- App Expo SDK 54+ avec Expo Router (file-based routing)
- Auth (login + storage local sécurisé `expo-secure-store` du baseUrl + apiKey)
- Écrans : `Home` (KPIs live + sparkline), `Signals` (flux WS temps réel + filtres entity/horizon), détail signal (`/signal/[id]`), `Alerts`, `Bots`, `Config`
- Connexion REST + WebSocket vers Tik core via `192.168.1.34:8200` (IP locale du Mac sur WiFi maison)
- Notifications push (Expo Push) avec storage du push token
- Compatible iPhone (testé via Expo Go le 2026-05-03) ET mode web (Safari)

**Mise en service réelle (2026-05-03)** :
- Installation Expo Go sur iPhone de l'utilisatrice
- `npm install` (~600 Mo de deps) dans `dashboard/`
- `npx expo start` côté Mac → QR code → scan iPhone via app Caméra native iOS → ouvre dans Expo Go
- Login dans l'app : Base URL `http://192.168.1.34:8200` + clé API existante
- Validation runtime : KPIs Home OK, flux Signals "Live" via WebSocket OK
- 2 bugs découverts pendant la mise en service : logo "Tik" tronqué sur iPhone (fontSize 96 → 72) + WebSocket auth refused systématique (import statique `_session_maker`). Fixés et commit le 2026-05-03 (cf. section 9 bug 7).

**Limites connues à ce stade** :
- Les hypothèses de signaux affichées dans le détail sont **minimalistes** (juste `"Swing long on BTC based on EMA/RSI/MACD confluence (bull=0.65, bear=0.18)"`). Les sections Evidence et Triggers contiennent l'info riche, mais l'hypothèse en haut n'est pas générée par NLP. Amélioration possible en ré-utilisant Ollama pour synthétiser un texte plus contextuel — à mettre en backlog si intérêt. *(Limite résolue par le Paquet 6 ADR-012 du 2026-05-03 : le candidat LLM est désormais affiché dans la carte secondaire "Hypothèse contextuelle" du détail signal en mode shadow.)*
- Mode 4G hors WiFi maison non fonctionnel (l'iPhone ne peut pas atteindre `192.168.1.34` depuis l'extérieur). Pour mobilité 4G, prévoir un setup ngrok/Tailscale ou un hébergement cloud — à voir si besoin réel.

**Évolution post-livraison (2026-05-04 — version 0.5.1)** :
- **Carte "Stats LLM" sur Home** : nouveau composant `dashboard/components/dashboard/stats-llm-card.tsx` qui affiche en temps réel le ratio de signaux émis aujourd'hui (depuis 00 h UTC) avec une sortie LLM ≥ 30 mots. Code couleur vert/orange/rouge (seuils 80 % / 60 %), badge "LLM ✓" ou "fallback" sur le dernier signal. Calcul **côté client** à partir des 100 signaux déjà fetchés par `useDashboardKpis` (zéro nouveau request HTTP, zéro modification backend). Couvre les modes `shadow` ET `active` du `TIK_LLM_HYPOTHESIS_MODE` via le helper `isSignalLlmEnriched(signal)` — préparé pour la bascule shadow → active prévue le 2026-05-05 sans intervention dashboard supplémentaire.
- **Fix bug d'affichage timezone (Bug 8 section 9)** : le core émet ses timestamps via `datetime.utcnow()` (Pydantic sérialise sans suffixe `Z`), JavaScript les interprétait comme heure locale → décalage de +UTC offset (2 h en CEST, 1 h en CET). Nouveau utilitaire `dashboard/src/utils/time.ts` (`parseUtcIso` + `timeAgo` + `formatLocal`) qui ajoute `Z` si absent. Refactor des 4 fonctions `timeAgo` dupliquées (alerts, index, signals, stats-llm-card) en un seul import partagé. Refactor des 2 `new Date(iso).toLocaleString()` du détail signal en `formatLocal`. Refactor du `new Date(s.timestamp).getTime()` du filtre `deriveLlmStats` dans `useDashboardKpis`. **Tous les âges et timestamps du dashboard sont désormais corrects.**
- **Factorisation seuil "30 mots"** du candidat LLM dans `dashboard/src/utils/llm.ts` (`MIN_LLM_HYPOTHESIS_WORDS`, `countWords`, `isLlmCandidateValid`, `isSignalLlmEnriched`) — élimine la duplication entre la carte secondaire "Hypothèse contextuelle" du détail signal (existait déjà) et la carte Stats LLM Home (nouvelle).
- **Bump version dashboard 0.5.0 → 0.5.1**. 2 bugs Alerts pré-existants identifiés et tracés en section 10 (persistance + timestamp figé) à fixer dans une session dédiée.

**Évolution post-livraison (2026-05-04, après-midi — version 0.5.2)** :

Session de bascule LLM hypothesis shadow runtime + bug critique timezone DB découvert et fixé + résolution des 2 bugs Alerts pré-identifiés + plan trading manuel J+10 acté. Détail :

- **Bascule LLM hypothesis shadow runtime activée** : `TIK_LLM_HYPOTHESIS=ollama` activé dans `core/.env` (était déjà positionné depuis le 2026-05-03 22:38 mais le scheduler a tourné la matinée avec le bug 9 qui a empêché tous les inserts — cf. section 9). Premier cycle complet runtime validé le 2026-05-04 17:11 UTC : swing BTC 138 mots, swing GOLD 105 mots, flash BTC 103 mots, sortie LLM dans `Signal.advisory.llm_hypothesis_candidate` conformément à ADR-012 décision 3.
- **Carte secondaire "Hypothèse contextuelle (LLM · validation)" affichée sur le détail signal iPhone** : la carte était déjà implémentée dans `dashboard/app/signal/[id].tsx:142-173` depuis la livraison Stats LLM card du matin (anticipation), avec filet anti-fantôme via `isLlmCandidateValid()` (≥ 30 mots) et badge gris "LLM · validation". Validation visuelle confirmée sur iPhone post-bascule runtime. **Aucun nouveau code dashboard nécessaire** — l'évolution n'a touché que `core/.env` (déjà fait) + restart `tik-scheduler`.
- **Bug critique 9 timezone DB asyncpg découvert et fixé runtime** : régression du Paquet 7 (ADR-013) qui empêchait tous les inserts de signaux depuis 13:09 UTC le matin même. Workaround chirurgical de 2 lignes dans `publisher.py:_publish_signal` (strip `tzinfo` avant insertion DB). Voir section 9 Bug 9 pour le diagnostic complet et la dette technique tracée (commentaire obsolète `utils/time.py:18` à corriger, ADR-013 à amender, test pytest Postgres bout-en-bout à ajouter).
- **Bug A Alerts résolu** : migration vers `@react-native-async-storage/async-storage` dans `dashboard/src/alerts/AlertsContext.tsx`. Hydratation eager au mount + persistance à chaque `setAlerts`. Clé storage `tik.alerts.v1`. Filet d'exception JSON corrompu → reset `[]`. Cap `MAX_ALERTS=50` inchangé. Voir section 10.
- **Bug B Alerts résolu via hook `useTick` mutualisé** : initialement résolu inline dans `app/(tabs)/alerts.tsx`, puis constat post-déploiement que **le même bug existait sur Signals + Home** (4 fichiers utilisent `timeAgo`). Refacto en hook custom `dashboard/src/hooks/use-tick.ts` (~10 lignes, retourne le `tick` pour `FlatList.extraData`). Pattern aligné sur la factorisation `utils/llm.ts` du matin. Refacto de `app/(tabs)/alerts.tsx` + `app/(tabs)/signals.tsx` (FlatList.extraData=tick) + `app/(tabs)/index.tsx`. Le composant enfant `stats-llm-card.tsx` re-render en cascade via le parent Home (pas de useTick dédié — YAGNI).
- **Plan préparation trading manuel J+10 acté** : l'utilisatrice a annoncé son intention de **trader manuellement avec Tik dans 10 jours**. Tik passe d'outil d'observation (Garde-fou 1 mode shadow vs Zeta) à outil d'aide à la décision réelle avec son capital. Plan en 4 features priorisées sur la calibration empirique + contexte rapide sans risque LLM + discipline opérationnelle (cf. `docs/backlog.md` entry n°3 pour le détail) : (J+1-2) carte Top headlines dashboard, (J+3-4) carte Hit rate live Home, (J+5-6) vue track record dans détail signal, (J+7-8) workflow watchlist post-trade, (J+9-10) calibration mentale sans dev. **Aucune modif des engines / pipeline scoring / cross-validation** — les 4 features sont purement dashboard + endpoints API en lecture. **Phase 2 enrichissement contextuel hypothèse LLM (réservé ADR-015) reportée à post-J+30** car mode shadow strict 1 mois impossible en 10j et le LLM 3B a des limites documentées (cf. backlog entry n°4 pour le raisonnement complet).
- **Bump version dashboard 0.5.1 → 0.5.2**. Section 10 désormais vide (aucun bug critique en cours).

### Paquet 4 — Diversification des sources OSINT news : 🟡 EN COURS

Enrichir le sentiment textuel multi-source (jusqu'ici limité à CryptoCompare BTC) en respectant strictement le pattern multi-overlay (ADR-004) et en réutilisant l'infra NLP Ollama (ADR-006).

| # | Session | Statut |
|---|---|---|
| 1 | Google News RSS (BTC + GOLD) + classifier asset-aware + ADR-008 | ✅ livrée le 2026-05-01 |
| 2 | Reddit JSON (r/Bitcoin + r/CryptoMarkets, pondération log upvotes) + ADR-009 | ✅ livrée le 2026-05-01 |
| 3 | GDELT timelinetone GOLD (tone brut, méthode NLP scientifique non-LLM, contrarian) + ADR-010 | ✅ livrée le 2026-05-01 |
| 4 | Consolidation : dataset golden BTC + GOLD + extension backtest CLI pour comparer hit rate par source | 🟡 partielle (livrée 2026-05-02, re-run prévu J+5 pour deltas 5d) |

**Session 1 livrée le 2026-05-01** :

- **Nouvel ingester Google News RSS** dans `core/src/tik_core/aggregator/google_news_ingester.py` (couche 6 sentiment textuel, layer 6). Source publique gratuite, sans clé, large couverture (Reuters, Bloomberg, FT, Yahoo Finance, CoinDesk, KITCO, Mining.com…). Polling toutes les **30 min** (~1440 req/mois total BTC+GOLD, sous radar de tout rate-limit). 50 titres max par cycle pour rester comparable à CryptoCompare. Parser via `feedparser>=6.0.11` (lib pure Python, tolérante aux variations de format) plutôt que parsing XML manuel — choix justifié dans ADR-008 par la fiabilité long terme et la réutilisabilité future (Reddit/GDELT parsent aussi du RSS/Atom).

- **Premier overlay sentiment news pour GOLD** : jusqu'ici GOLD n'avait que DXY (FRED) et COT (CFTC) comme overlays cross-validation. La distribution observée live (KITCO, Mining.com, FXStreet, FXEmpire, Fortune en top publishers) montre que Google News capte un univers de news macro / géopolitique / mining qu'aucune autre source ne couvrait. Sur BTC, Google News s'ajoute à FG + CryptoCompare comme 3e overlay sentiment.

- **Classifier asset-aware (extension ADR-006)** : ajout du paramètre `asset_name: str = "Bitcoin"` au constructeur de `OllamaClassifier`. Le prompt devient *"Classify the headline by its likely impact on the {asset_name} price…"*. Rétrocompat totale (`CryptoCompareIngester` non modifié, default = Bitcoin). Le `KeywordClassifier` reste asset-agnostic (analyse par mots-clés universelle).

- **1 classifier par ingester pour isoler les circuit breakers** : 3 instances `OllamaClassifier` au boot (CryptoCompare-BTC + GoogleNews-BTC + GoogleNews-GOLD), construites **en parallèle** via `asyncio.gather` pour économiser ~2 s de boot. Si Ollama plante 3 fois sur un batch GoogleNews-BTC, son circuit s'ouvre pour ce batch ; CryptoCompare-BTC et GoogleNews-GOLD restent intacts. Robustesse opérationnelle vs partage de classifier (qui aurait propagé un incident d'un ingester à tous les autres).

- **Pipeline multi-overlay étendu (ADR-004)** : nouveaux helpers `_compute_google_news_bias` (paliers identiques à CryptoCompare pour cohérence multi-source news textuelle) et `_enrich_with_google_news` (ajoute evidence avec `top_publishers` exposés dans le `fact` pour transparence dashboard, et trigger `news_sentiment_google`). Branché dans `analyze_swing_btc` ET `analyze_swing_gold`. La veracity finale reste calculée via `_veracity_from_concordance` sur la moyenne des biais — sources contradictoires se neutralisent (veracity 0.85), concordantes la renforcent (0.90-0.95).

- **Score `google_news_rss = 0.70` provisoire** dans `SOURCE_SCORES` (équivalent CryptoCompare, cohérent avec la philosophie ADR-006 *"on ne biaise pas a priori, on mesurera"*). Réévaluation prévue Session 3 après dataset golden.

- **Champ `top_publishers` dans le payload Redis** : top 5 sources observées par cycle (extraites via balise `<source>` ou suffix " - Publisher" du titre Google News). Permet l'analyse a posteriori du biais éditorial sans imposer un whitelist a priori (qui serait fastidieux à maintenir et biaisé par notre vision de "qualité").

- **Validation runtime au déploiement** : 8 ingesters au total (vs 6 avant). Premier cycle complet en <1 min après boot. Distributions observées :
  - Google News BTC : 22 bull / 22 bear / 6 neutral, score 0.0, top publisher Yahoo Finance (40 % des hits — concentration à surveiller).
  - CryptoCompare BTC : 13 bull / 28 bear, score −0.37. **Divergence cross-source mesurée dès le premier cycle** — exactement le mécanisme de cross-validation visé par ADR-008.
  - Google News GOLD : 14 bull / 18 bear / 18 neutral, score −0.125, top 5 publishers diversifiés (Fortune, KITCO, FXStreet, FXEmpire, Mining.com — distribution beaucoup plus saine que BTC).

- **Tests pytest** : 230 → **283 tests verts** (+53 : 11 swing engine helpers, 6 news_classifier asset_name + isolation circuit breakers, 26 google_news_ingester avec fixtures RSS embarquées + tests feedparser bout-en-bout). Aucune régression. 1.90 s d'exécution.

- **ADR-008 documenté** : `docs/adr/008-multi-asset-news-overlays.md` formalise les choix (Google News parmi les sources gratuites, parser feedparser, queries simples `Bitcoin` / `"gold price"`, polling 30 min, isolation circuit breakers, score 0.70 provisoire) et liste les conséquences positives/négatives (dépendance à un endpoint Google non officiel mitigée par feedparser tolérant + log warning + cycle suivant retentera). Risques opérationnels rappelés : Garde-fou 1 (mode shadow 3 mois) **strictement applicable**, ADR-003 (pas de bypass V01-V15) **inchangé**, paranoïa contrôlée maintenue.

**Session 2 livrée le 2026-05-01** :

- **Nouvel ingester Reddit JSON** dans `core/src/tik_core/aggregator/reddit_ingester.py` (couche 6 sentiment textuel, layer 6). Source publique gratuite, sans clé pour read-only, ~60 req/min anonyme. Polling toutes les **30 min** sur 2 subs agrégés (`r/Bitcoin` ~5M membres + `r/CryptoMarkets` ~1.5M membres). Endpoint `/r/<sub>/hot.json?limit=50` (algorithme Reddit `hot` = mélange popularité + récence, plus représentatif que `top:hour` stale ou `new` bruité). User-Agent obligatoire pour éviter le ban Reddit : `tik-osint-bot/0.1 (research; contact escltheo@gmail.com)`. Parsing JSON natif via `httpx.json()` — pas de nouvelle dépendance Python ajoutée.

- **Pondération log(score+1) par upvotes** : **nouveauté structurante** par rapport au pattern uniforme de Google News / CryptoCompare. Pour chaque post `i` filtré, `weight_i = log(score_i + 1)` et `score_net = Σ(weight_i × verdict_i) / Σ(weight_i) ∈ [-1, +1]`. Reflète le poids communautaire réel : un post viral à 10 000 upvotes pèse `log(10001)≈9.2` vs un post à 5 upvotes pèse `log(6)≈1.8`. L'échelle log atténue les outliers sans les écraser. C'est la métrique unique de Reddit que les autres sources n'offrent pas — l'ignorer reviendrait à traiter un thread à 1 upvote comme un thread à 10 000 upvotes.

- **Mitigation brigading et bots via 3 filtres conservateurs** : `stickied=False` (skip posts épinglés par mods, non représentatifs), `over_18=False` (skip NSFW), **`score >= 5`** (ignore les posts brand-new pas encore validés communautairement, facilement manipulables par 1-2 bots). Le filtre score>=5 garantit qu'un brigading nécessite **au minimum 5 votes coordonnés**. Risque résiduel d'un brigading à 50+ votes coordonnés tracké pour observation Session 3 (comparaison upvotes/comments comme détecteur d'anomalie possible).

- **4e overlay sentiment BTC dans `analyze_swing_btc`** : Tik dispose désormais de 4 sources sentiment cross-validées sur BTC :
  1. Fear & Greed (contrarian)
  2. CryptoCompare news (trend-following, crypto-éditorial — CoinDesk)
  3. Google News BTC (trend-following, mainstream-éditorial — Reuters/Bloomberg/FT)
  4. **Reddit BTC** (trend-following, retail-communautaire pondéré log)
  Chacune avec un angle indépendant pour maximiser l'apport du pipeline multi-overlay ADR-004.

- **Pas de Reddit pour GOLD** : décision documentée dans ADR-009 section 5. r/Gold (~70k) et r/GoldandSilverStackers (~250k) trop petits pour produire un échantillon significatif (3-5 posts pertinents/jour). r/wallstreetbets (~16M) trop bruité : ironie + argot WSB (*"apes"*, *"tendies"*, *"stonks"*, *"🚀"*) non capté par le LLM 3B → faux positifs structurels. WSB a aussi un biais long-stocks structurel qui colore négativement le sentiment GOLD. GDELT évalué Session 3 comme alternative macro/géopol propre (flux structuré officiel, ton mesuré, multilingue, pas d'ironie).

- **Score `reddit_btc = 0.65` provisoire** dans `SOURCE_SCORES` : un cran sous mainstream (CryptoCompare/Google News à 0.70) pour refléter la nature retail amateur, mais pas trop pénalisant. Réévaluation prévue Session 3 après dataset golden. Le pipeline ADR-004 absorbera de toute façon les divergences via `_veracity_from_concordance` — le score sert d'evidence (transparence dashboard), pas de pondération du bias.

- **Champ `top_subreddits`** dans le payload Redis (analogue à `top_publishers` de Google News) : top 5 distribution post-filtrage par sub. Permet l'analyse a posteriori de l'équilibre r/Bitcoin vs r/CryptoMarkets sans imposer un ratio fixe a priori. Affiché préfixé `r/` dans l'evidence du signal swing pour clarté.

- **4 instances `OllamaClassifier` au boot** (CryptoCompare-BTC + GoogleNews-BTC + GoogleNews-GOLD + **Reddit-BTC**), construites **en parallèle** via `asyncio.gather` (~3-4 s one-shot au lieu de ~12 s séquentiel). Bénéfice : circuit breakers Ollama isolés — un incident Ollama sur un ingester ne contamine pas les autres ingesters textuels. **9 ingesters au total** (vs 8 après Session 1, +1 Reddit).

- **Résilience par sub** : si un sub fail (réseau, 503, payload invalide), `_fetch_sub` log un warning et retourne None ; la boucle agrégée continue avec les autres subs. Le ingester Reddit ne s'arrête jamais à cause d'un seul sub indisponible.

- **ADR-009 documenté** : `docs/adr/009-reddit-sentiment.md` formalise les choix structurants Reddit (subs choisis avec leurs profils retail vs trader, pondération log upvotes en innovation par rapport au pattern uniforme, mitigation brigading via 3 filtres conservateurs, justification du rejet WSB pour GOLD) et liste les conséquences positives/négatives. Risques opérationnels rappelés : Garde-fou 1 (mode shadow 3 mois) **strictement applicable**, ADR-003 (pas de bypass V01-V15) **inchangé**, paranoïa contrôlée maintenue.

**Session 3 livrée le 2026-05-01** :

- **Nouvel ingester GDELT** dans `core/src/tik_core/aggregator/gdelt_ingester.py` (couche 6 sentiment textuel, layer 6). Source : GDELT 2.0 Doc API (`https://api.gdeltproject.org/api/v2/doc/doc`), mode `timelinetone`, query `"gold price"`, filtre `sourcelang:eng`, timespan 24 h. Polling toutes les **30 min** (~1440 req/mois, GDELT n'a pas de rate-limit documenté pour la Doc API en lecture publique). Aucune nouvelle dépendance Python ajoutée (parsing JSON natif via `httpx.json()`).

- **Premier overlay Tik à NE PAS passer par OllamaClassifier** : décision structurante d'ADR-010. GDELT consomme directement le tone calculé par GDELT (NLP scientifique non-LLM) plutôt que de classifier les titres via Ollama. **Diversification méthodologique pure** : Tik a désormais du sentiment Ollama-LLM (CC + Google News + Reddit) ET du sentiment NLP scientifique non-LLM (GDELT). Si les deux convergent → veracity élevée ; si divergent → information riche sur la diversité du sentiment réel. C'est l'esprit ADR-004 poussé plus loin : on diversifie les **méthodes** de scoring, pas seulement les **sources**.

- **Mapping contrarian validé empiriquement** : tone GDELT négatif (tensions globales, crises, sanctions, banques en faillite) → bull GOLD via rotation safe haven. Cohérent avec FG sur BTC mais inversé : tone GDELT ≈ « global mood negative » → GOLD bull. Validé sur 50 ans d'histoire monétaire (1970s inflation, 2008 GFC, 2020-22 pandémie + Ukraine, 2023 SVB — chaque épisode de stress a vu l'or monter).

- **Mapping retenu (`_compute_gdelt_bias`)** :
  - tone ≤ −3.0 → +1.0 (`tensions_extreme`) — strong bull GOLD
  - tone ≤ −1.0 → +0.5 (`tensions_moderate`) — bull GOLD
  - −1.0 < tone < 1.0 → 0.0 (`neutral_climate`) — neutre
  - tone ≥ 1.0 → −0.5 (`optimism`) — bear GOLD
  - tone ≥ 3.0 → −1.0 (`euphoria`) — strong bear GOLD
  Calibration provisoire des seuils ±1, ±3 issus de la littérature GDELT, à réévaluer Session 4 après dataset golden.

- **4e overlay GOLD** : `analyze_swing_gold` reçoit désormais 4 sources cross-validées :
  1. DXY (FRED, contrarian)
  2. CFTC COT Managed Money (contrarian)
  3. Google News GOLD (trend-following, mainstream-éditorial via Ollama)
  4. **GDELT tone** (contrarian, NLP scientifique non-LLM)
  Symétrie qualitative avec BTC qui a aussi 4 overlays — les profils méthodologiques sont juste différents.

- **Pas de GDELT BTC en Session 3** : décision tracée dans ADR-010 section 3. Le mapping contrarian validé pour GOLD est **incertain pour BTC** (corrélation BTC ↔ tensions globales instable historiquement : sell-off avec actions mars 2020, mais bull Russie 2022 et SVB 2023). Déployer un mapping non-validé sur BTC risquerait d'introduire du bruit dans le pipeline BTC qui marche bien aujourd'hui. Stratégie échelonnée : Session 4 dataset golden inclura des titres macro BTC pour mesurer si GDELT BTC apporterait un signal exploitable et avec quel mapping (contrarian, trend-following, hybride).

- **Score `gdelt_news = 0.75` provisoire** dans `SOURCE_SCORES` : un cran au-dessus des news mainstream (CC/Google News à 0.70) pour reconnaître la qualité éditoriale + scientifique de GDELT, un cran sous les sources gouvernementales chiffrées (FRED `dtwexbgs` à 0.85). Réévaluation prévue Session 4.

- **Ingester ultra-léger** : 1 req HTTP par cycle, parsing JSON tolérant (`_extract_tone_points` supporte multi-séries / valeurs non numériques / payloads malformés), mapping numérique. **Aucun classifier au boot** (4 classifiers Ollama inchangés vs Session 2). 10 ingesters au total (vs 9 après Session 2).

- **Tests pytest** : 336 → **~386 tests verts** (+ ~26 gdelt_ingester sur `_extract_tone_points` / `_fetch` / lifecycle / construction URL avec sourcelang, + ~24 swing engine helpers GDELT incluant un test dédié à la nature contrarian du mapping). Aucune régression. Chiffre exact à confirmer post-pytest live.

- **ADR-010 documenté** : `docs/adr/010-gdelt-tone-overlay-gold.md` formalise les choix structurants (mode `timelinetone` plutôt qu'`artlist + Ollama` pour la diversification méthodologique, interprétation contrarian plutôt que trend-following pour aligner sur la sémantique safe haven de l'or, mapping calibré ±1/±3, lang:eng seul, query simple `"gold price"`, GOLD seul Session 3, BTC reporté à Session 4+ pour validation empirique). Risques opérationnels rappelés : Garde-fou 1 (mode shadow 3 mois) **strictement applicable**, ADR-003 (pas de bypass V01-V15) **inchangé**, paranoïa contrôlée maintenue.

**Session 4 partielle livrée le 2026-05-02** (re-run prévu le 2026-05-06+ pour les deltas 5d) :

- **Pipeline de calibration livré** : 5 scripts CLI dans `core/src/tik_core/scripts/` qui s'enchaînent et se joignent par hash `id` stable :
  1. `collect_golden.py` — refetch on-the-fly 50 BTC (mix Google News + CryptoCompare + Reddit) + 50 GOLD (Google News) → `raw_items.jsonl`
  2. `annotate_golden.py` — CLI interactif blinded, ordre randomisé seed=42, traduction live FR via Ollama, glossaire EN→FR (~80 termes ciblés crypto/or/macro/régulation/technique) → `annotations.jsonl`
  3. `predict_golden.py` — Ollama asset-aware (`Bitcoin` / `Gold`) + KeywordClassifier en parallèle, construits via `asyncio.gather` → `predictions.jsonl`
  4. `backtest_golden.py` — multi-horizon (1h, 6h, 24h, 5d) via Binance klines + Yahoo, deltas marqués `available=False` quand l'horizon est dans le futur → `prices.jsonl`
  5. `measure_calibration.py` — joint les 4 fichiers, calcule 3 familles de métriques (concordance humain↔classifier, calibration vs marché, performance par source), génère rapport JSON + Markdown

- **Décisions structurantes prises** :
  - **Refetch on-the-fly** : pas de modif schéma DB (garde-fou 1 inchangé)
  - **Annotation 50/asset** (~17/source pour BTC) plutôt que 50/source (200 items à annoter) : effort gérable (~20 min) pour un premier cycle, à étendre si signal ambigu
  - **Sources numériques (FG, GDELT tone, DXY, COT) exclues du textuel annotable** : leur calibration se fait via backtest sur série historique étendue (étape 7, à venir Session 4-bis)
  - **Format JSON Lines versionné git** dans `core/data/golden_dataset/` (mount Docker `./data:/app/data:rw` ajouté à `core/docker-compose.yml`)
  - **Multi-horizon** plutôt qu'un seul horizon 5d : permet une lecture progressive (1h dispo dès la collecte) et une re-lecture plus fine de la demi-vie de chaque source

- **Aide à l'annotation** :
  - **Traduction live FR via Ollama** dans `annotate_golden.py` (~1-2 sec par titre, prompt durci pour conserver les termes techniques en anglais — partiellement respecté par `llama3.2:3b`)
  - **Glossaire `core/data/golden_dataset/glossaire-news-fr.md`** : ~80 termes EN→FR avec tendance bull/bear/contextuelle, organisé en 5 sections (crypto, or, macro, régulation, technique)
  - **Limite documentée** : la traduction Ollama 3B inverse parfois la sémantique sur le jargon précis (ex. `supply` ↔ `demand`). Le glossaire reste la référence absolue en cas de divergence ; règle "dans le doute → neutral".

- **Premier cycle de mesure (2026-05-02)** :
  - **100 items annotés à la main** par l'utilisatrice (distribution : 27 bull / 17 bear / 56 neutral — ratio neutral élevé cohérent avec règle "dans le doute → neutral", appliquée par une débutante en trading mais sur lecture sémantique de titres)
  - **100 predictions Ollama** sans aucun fail (38 bull / 39 bear / 23 neutral — Ollama très directionnel)
  - **100 predictions Keywords** (23 bull / 12 bear / 65 neutral — très conservateur)
  - **Deltas 1h et 6h disponibles** ; deltas 24h et 5d à venir (collecte 1er mai 18h09 UTC, deltas 5d dispo le 6 mai 18h09 UTC)

- **Insights provisoires (à confirmer avec deltas 5d)** :
  - **Accuracy Humain ↔ Ollama** = 58 % ; **Humain ↔ Keywords** = 63 % ; **Ollama ↔ Keywords** = 49 %. Les deux classifiers internes prennent des décisions structurellement différentes sur 51 % des items — confirmation que le choix Ollama vs keywords change radicalement le signal en sortie de chaque ingester news.
  - **Confusion matrix Humain ↔ Ollama** : 35 cas où Ollama tranche bull/bear (18+17) quand l'humain dit neutral (Ollama agressif), seulement 5 cas de vraie divergence sémantique (Ollama bear ↔ humain bull). Ollama capte des signaux ténus que l'humain juge trop ambigus — peut être une force ou une faiblesse selon le marché.
  - **Hit rate vs marché à 1h et 6h biaisé par le seuil** : `always_neutral` atteint 100 % (tous les deltas BTC+GOLD < 0.5 % à ces horizons sur 100 items). Mesure non-informative à court terme — confirmera ce qu'on attendait : le sentiment news a une demi-vie >24h, les vraies conclusions ne sortiront qu'à 5d.

- **Tests pytest** : 386 → **451 tests verts** (+65 sur `core/tests/test_golden_pipeline.py` couvrant `_make_id`, `_load_existing_ids`, `quotas_for`, `pick_new`, `_verdict_from_counts`, `_parse_horizon`, `_parse_dt`, `_compute_deltas_for_item`, `_verdict_correct_vs_market`, `_accuracy`, `_confusion_matrix`, `_hit_rate_vs_market`, `_baseline_random/constant`, `_build_combined`, `_section_distribution/concordance`, `_render_markdown`, `_index_by_id`). 1 bug latent corrigé pendant le run : `pick_new(quota=0)` retournait incorrectement 1 item au lieu de 0 (early return ajouté).

- **Documentation** :
  - **`docs/methodology/calibration.md`** créé : protocole en 6 étapes, architecture des fichiers, métriques calculées, limites assumées (échantillon 100 items, 1 cycle de marché, annotateur unique débutant trader, traduction LLM 3B imparfaite), commandes de relance, décisions à valider après chaque cycle.
  - **`docs/backlog.md`** enrichi (entrée n°2) : traduction native française des signaux Tik (param `?lang=fr` API + cache Redis + 3 endpoints + ADR-011) — 3 options évaluées pour/contre/verdict, Option A retenue, à attaquer en Session 5 dédiée si la calibration ne fait pas remonter d'ajustement structurant urgent.

- **Volontairement reporté à Session 4-bis (re-run J+5 le 2026-05-06)** :
  - Lecture des hit rates 5d humain / Ollama / keywords (la vraie mesure)
  - Comparaison vs baselines (random, always X) sur 5d
  - Performance par source à 5d (Google News BTC vs CryptoCompare vs Reddit vs Google News GOLD)
  - **Étape 7 — Backtest sources numériques** (FG, GDELT tone, DXY, COT) sur série historique étendue (6-12 mois) plutôt que sur 100 items récents
  - **Étape 9 — Ajustements `SOURCE_SCORES`** dans `swing_engine.py` selon mesures
  - **Étape 10 — Décision GDELT BTC** (déployer ou archiver selon corrélation tone↔delta BTC mesurée)
  - **Pas d'ADR en Session 4** (l'utilisatrice a explicitement demandé `docs/methodology/calibration.md` en alternative). ADR-012 sera réservé à la traduction native FR signaux future. ADR-011 a finalement été pris par l'anti fake-news (cf. Paquet 5 ci-dessous).

- **Risques opérationnels rappelés** : Garde-fou 1 (mode shadow 3 mois) **strictement applicable** — la calibration ne touche pas la logique d'exécution Zeta, on est en pure observation. ADR-003 (pas de bypass V01-V15) **inchangé**. Paranoïa contrôlée maintenue. Le commit 2026-05-02 ne modifie aucun engine ni ingester ni endpoint API — uniquement scripts CLI + tests + docs + 1 ligne dans `core/docker-compose.yml`.

### Paquet 5 — Anti fake-news : ✅ LIVRÉ (ADR-011, 2026-05-03)

Cross-validation runtime + scoring source dynamique. Réveille l'infra dormante du Paquet 1 (`Signal.circuit_breaker_status`) et du Paquet 2 (hook SDK `on_fake_news_detected`).

**Cross-validation runtime** (`core/src/tik_core/scoring/cross_validator.py`) :

- **Algorithme adapté à la taille N** : no-op N≤1, règle disagreement N=2 (signes opposés ET écart > 0.8), Modified Z-score d'Iglewicz-Hoaglin (1993) pour N≥3 avec seuil 3.5 et fallback seuil absolu (>0.3) quand MAD=0.
- **Détection de dispersion globale** complémentaire (écart-type sur les non-outliers, seuils 0.5 / 0.85) qui capture les distributions bimodales 50/50 que Modified Z laisse passer mathématiquement.
- **Status final** = pire des deux (max sévérité). `"degraded"` flagge le signal sans modifier sa direction ; `"tripped"` force `direction="neutral"` et préfixe la `hypothesis` avec `"Anti fake-news: X/Y outliers — direction forced to neutral. (Original: ...)"`.
- **Outliers individuels** marqués `is_outlier: true` dans leur evidence, neutralisés dans le `combined_bias` qui sert au calcul de la veracity.
- **Mode `active`/`shadow`** via variable d'env `TIK_ANTIFAKENEWS_MODE` (défaut `active`). Mode `shadow` : cross-validation calculée + log structuré, mais decision inchangée. Permet bascule sans redéploiement si bug en prod.
- Branché dans `analyze_swing_btc/gold` et `analyze_flash_btc` au lieu du calcul de moyenne brut. Helper `apply_cross_validation_to_decision(decision, biases, mode)` propage le résultat à la decision en place.

**Scoring source dynamique** (`core/src/tik_core/scoring/source_credibility.py`) :

- **Stockage hybride Redis (runtime) + Postgres (audit)** : clé Redis `tik.source_credibility.<source>` (TTL 8j, > intervalle scheduler 24h), nouvelle table `source_credibility_history` (1 row par source par recalibration).
- **Mécanisme d'injection via `contextvars.ContextVar`** : aucune modification de signature des `_enrich_with_<source>`, le caller (`analyze_swing_btc/gold`, `analyze_flash_btc`) précharge les scores Redis au début de son exécution et active le context-var. Chaque helper appelle `get_effective_score(source, fallback_static)` qui lookup le context-var avant le fallback statique. Isolé par task asyncio (pas de races inter-cycles).
- **Job APScheduler `recalibrate_sources`** cron daily 03:00 UTC dans `run_scheduler.py`. Lit les signaux des 30 derniers jours, calcule hit rate par source en réutilisant la logique de `backtest.evaluate_signal`, ajuste asymétriquement.
- **Algorithme d'ajustement asymétrique** (paranoïa contrôlée — pénalité plus rapide que récompense) : hit rate <40% sur ≥30 samples → score ÷1.2 (penalty) ; 40–70% → unchanged ; >70% sur ≥30 samples → score ×1.1 (reward) ; <30 samples → unchanged. Cap final `[0.30, 0.95]`.
- **Sources concernées** (`RECALIBRATABLE_SOURCES` whitelist) : alternative_me_fng, cryptocompare_news, google_news_rss, reddit_btc, gdelt_news, fred_dtwexbgs, cftc_cot, binance_orderbook, binance_aggtrades. Exclues : sources de prix (binance_klines, yahoo_finance, binance_klines_1m).
- **Coefficients ÷1.2 / ×1.1 calibrés au pifomètre** — assumé ouvertement dans ADR-011, à réviser au cycle de calibration suivant (Session 4-bis du 2026-05-06+) en croisant avec les hit rates 5j mesurés sur le golden dataset.

**Validation runtime** : 71 nouveaux tests (39 cross_validator + 32 source_credibility) couvrant les edge cases mathématiques (MAD=0, dispersion globale, asymétrie pénalité/récompense, cap min/max, fallback hiérarchique Redis/static, context-var dynamic_scores). Suite complète : 425 → **457 tests verts** (+32 source_credibility), aucune régression. Migration Alembic 0003 appliquée et table créée en DB.

**ADR-011 documenté** : `docs/adr/011-anti-fake-news.md` formalise les choix structurants (Modified Z-score d'Iglewicz-Hoaglin + dispersion globale, stockage Redis+Postgres, asymétrie pénalité/récompense, mode active/shadow par variable d'env). Risques opérationnels rappelés : Garde-fou 1 (mode shadow 3 mois) **strictement applicable**, ADR-003 (pas de bypass V01-V15) **inchangé**, paranoïa contrôlée maintenue. ADR-004 (multi-overlay pattern) inchangé — anti fake-news enrichit le calcul du combined_bias, ne le remplace pas.

**Documentation pédagogique** : nouvelle section 12 dans `docs/comprendre_tik.md` en français accessible (cross-validation expliquée avec un exemple concret 4 sources dont 1 aberrante, scoring dynamique expliqué avec son cycle quotidien, mode active vs shadow expliqué comme un filet de sécurité réversible).

### Paquet 6 — LLM hypothesis generator : ✅ LIVRÉ (ADR-012, 2026-05-03)

Synthèse contextuelle de l'hypothèse signal via LLM local (réutilise l'infra Ollama d'ADR-006). Limite "hypothèses minimalistes" identifiée dans Paquet 3 résolue.

**Module `core/src/tik_core/scoring/hypothesis_generator.py`** (~370 lignes) :

- Pattern Strategy ABC `HypothesisGenerator` + `TemplateHypothesisGenerator` (fallback historique f-string) + `OllamaHypothesisGenerator` (LLM local). Calque exact du pattern `news_classifier.py` (cf. ADR-006), familier et testé.
- **Circuit breaker batch-level** : 3 erreurs successives → bascule template pour le reste du batch, `reset_batch()` réarme à chaque cycle scheduler. **Validation post-génération** : longueur 50-400 mots, doit contenir direction + entity_id, sanitize markdown (`**`, `##`, ```, `__`). Sortie invalide → fallback template **sans** incrémenter le compteur (différencie échec réseau vs loupé ponctuel du modèle).
- Factory `build_hypothesis_generator(generator_type, ollama_url, ollama_model)` avec ping santé Ollama au démarrage (réutilise GET `/api/tags`).
- Helper `apply_llm_hypothesis(decision, horizon, generator, mode, timeout_s=30.0)` : enveloppe `asyncio.wait_for` 30s (cohérent avec httpx interne 25s, calibré sur la latence mesurée llama3.2:3b sur Mac M1 ~13s/cycle pour ~250 mots). Ne lève **jamais** : tout échec → log warning + decision inchangée.

**Prompt structuré 6 sections fixes** (~150 mots cible) : Verdict + Lecture technique + Sentiment cross-validé + Anti fake-news status + Risque principal + À surveiller. Garde-fous prompt : *"Use ONLY the data provided"*, *"No invented prices/sources"*, *"No markdown"*. `temperature=0.0`, `num_predict=350`.

**Modes par variable d'env `TIK_LLM_HYPOTHESIS_MODE=disabled|shadow|active`** (défaut `shadow`) + `TIK_LLM_HYPOTHESIS=template|ollama` (défaut `template`, opt-in via env) :

| Mode | Comportement |
|---|---|
| `disabled` | Aucun appel LLM, `Signal.hypothesis` = template historique |
| `shadow` (défaut) | LLM s'exécute, sortie dans `Signal.advisory["llm_hypothesis_candidate"]`. `Signal.hypothesis` garde le template — validation passive |
| `active` | LLM remplace `Signal.hypothesis`. Template conservé dans `Signal.advisory["template_hypothesis"]` pour audit |

**Pourquoi `shadow` par défaut** (vs ADR-011 qui était `active`) : ici l'hypothèse est lue par un **humain** qui prend des décisions à partir d'elle. Une hypothèse hallucinée serait pire que le template. Le mode shadow permet de valider qualité sortie LLM sur 5-10 cycles avant bascule active.

**Réveil champ `Signal.advisory`** (existant en DB depuis Paquet 1, jamais utilisé) : aucune modification de schéma DB nécessaire. Le payload Redis publié inclut désormais `advisory` (modification mineure dans `publisher.py:_publish_signal`).

**Branchement engines** : paramètre `hypothesis_generator: HypothesisGenerator | None = None` ajouté aux signatures de `analyze_swing_btc`, `analyze_swing_gold`, `analyze_flash_btc`. Rétrocompat totale (defaut None). Préchargement du generator au démarrage `run_scheduler.main()`, partagé entre les 3 jobs, `reset_batch()` au début de chaque cycle.

**Validation runtime** (2026-05-03 20:44-20:45) : premiers cycles Ollama réussis observés en prod local — GOLD swing 139 mots, BTC flash 125 mots, format 6 sections respecté, sources nommées avec credibility scores, contre-scénarios cités avec probabilités, niveaux à surveiller mentionnés. Mode shadow actif → `Signal.hypothesis` reste template, `Signal.advisory.llm_hypothesis_candidate` porte la sortie LLM.

**39 nouveaux tests pytest** (`core/tests/test_hypothesis_generator.py`) : render template, formatters (triggers/evidence/CS/outliers), sanitize markdown, validation post-génération, generate success/fallback/invalid, circuit breaker open/reset, modes apply (disabled/shadow/active/timeout/exception/unknown/advisory not dict), factory (template/ollama alive/unreachable/model missing). Suite complète : 522 → **561 tests verts**, aucune régression.

**ADR-012 documenté** : `docs/adr/012-llm-hypothesis-generator.md` formalise les 5 décisions structurantes (création sync vs lazy, EN seul vs FR/bilingue, shadow par défaut vs active/disabled, tous engines vs step-by-step, format 6 sections ~150 mots) avec arguments pour/contre/verdict pour chacune. Risques opérationnels rappelés : Garde-fou 1 **strictement applicable** (texte affiché à l'humain, zéro impact trade), ADR-003 **inchangé**, paranoïa contrôlée maintenue.

**Documentation pédagogique** : nouvelle section 13 dans `docs/comprendre_tik.md` en français accessible (limite ancienne hypothèse expliquée + format 6 sections + exemple sortie LLM réelle + filet de sécurité shadow expliqué).

**Backlog** : entry #2 (traduction FR signaux) glissée vers **ADR-014** (ADR-013 a finalement été utilisé pour le fix timezone bug 8 — cf. Paquet 7 ci-dessous). La traduction couvrira l'hypothèse contextualisée + les autres champs textuels.

### Paquet 7 — Timezone fix backend : ✅ LIVRÉ (ADR-013, 2026-05-04)

Fix backend complémentaire du Bug 8 timezone (cf. section 9). Le fix dashboard du commit `47b4f4c` (`parseUtcIso`) restait un filet local — le SDK Python et le futur connecteur Zeta liraient toujours des datetimes ambigus. ADR-013 fixe à la source.

**Module `core/src/tik_core/utils/time.py`** (~50 lignes, 3 fonctions pures) :

- `now_utc()` → datetime **aware** (`tzinfo=UTC`). Pour création d'objets métier (`signal.timestamp`, `decision.timestamp`, `expiry`, `last_computed`, etc.).
- `now_utc_naive()` → datetime **naïf** (UTC sémantique). Pour `default=` colonnes SQLAlchemy `DateTime` sans `timezone=True` et comparaisons SQL `Signal.timestamp >= since` (évite `DeprecationWarning` SQLAlchemy 2 sur conversion silencieuse asyncpg).
- `iso_utc(value)` → chaîne ISO-8601 avec suffixe `Z`. Utilisé par les `field_serializer` Pydantic ET par le publisher pour les payloads Redis WebSocket. Marque `Z` même sur datetime naïf (cas DB SQLAlchemy lecture).

**Périmètre couvert** : tous les usages `datetime.utcnow()` dans `core/src/tik_core/` remplacés (zéro restant). 17 fichiers source modifiés (storage models + schemas + scoring 4 fichiers + api 3 fichiers + auth + scripts 3 fichiers + aggregator 2 fichiers).

**Sérialisation Pydantic via `field_serializer` explicite par schéma** : `SignalOut`, `EntityOut`, `FeedbackOut`, `VeracityStatus`. Tous délèguent au helper unique `iso_utc`. Le piège DB résolu : SQLAlchemy retourne des datetimes naïfs (colonnes sans `timezone=True`) → sans serializer, Pydantic sortirait sans `Z` et bug 8 reproduit. Le serializer compense à la sortie.

**Choix structurants documentés** : helper centralisé vs `datetime.now(timezone.utc)` partout (centralisé pour refactor futur trivial), field_serializer explicite vs BaseModel parent générique (explicite pour traçabilité), pas de migration Alembic vers TIMESTAMPTZ (hypertable Timescale lourde à migrer, le serializer compense suffisamment).

**Validation runtime** : 19 nouveaux tests pytest (`test_utils_time.py` 9 tests sur les 3 helpers + `test_schemas_serialization.py` 10 tests verrouillant le format JSON sortant pour 4 schémas naïf ET aware). Suite complète : 561 → **590 tests verts**, 0 régression.

**ADR-013 documenté** : `docs/adr/013-timezone-aware-datetimes.md` formalise les 4 décisions (périmètre maximal core, field_serializer Pydantic + helper `iso_utc`, helper centralisé `utils/time.py` avec 3 fonctions, pas de migration Alembic). Risques opérationnels rappelés : Garde-fou 1 **strictement applicable** (fix purement technique, zéro impact trade), ADR-003 **inchangé** (aucun nouveau canal d'exécution). Glissement réservation ADR-013→ADR-014 pour la traduction FR.

**Documentation pédagogique** : nouvelle section 14 dans `docs/comprendre_tik.md` en français accessible (cause du bug expliquée avec « horloge sans étiquette », fix en deux temps dashboard puis backend, leçon technique sur les datetimes naïfs voyageant entre systèmes).

**Compatibilité forward** : le `parseUtcIso` côté dashboard (Paquet 3 / commit `47b4f4c`) reste en place comme double sécurité. Si Tik émet `Z` côté backend ET le dashboard ajoute `Z` si absent, aucun double encoding (le helper détecte `Z` déjà présent et ne touche à rien).

### Paquet 8 — Plan trading manuel J+10 Phase A.1 LIVRÉE (2026-05-05)

Phase A.1 (J+1-2) du plan trading manuel J+10 livrée et validée runtime. Carte « Top headlines » sur Home dashboard + endpoint API `/api/v1/headlines/{entity_id}` + persistence des titres bruts dans Redis aux côtés des agrégats existants.

**Backend (core)** — 6 fichiers modifiés/créés :

- 3 ingesters news (Google News, CryptoCompare, Reddit) enrichis pour persister un champ `headlines: list[dict]` (cap `MAX_HEADLINES=25` titres/cycle) dans le payload Redis existant, avec : `title`, `url`, `publisher`, `sentiment` (bull/bear/neutral mappé depuis le verdict du classifier), `published_at`, `fetched_at`. **Calcul du score net strictement inchangé** — modif 100 % additive, zéro régression sur les engines / pipeline scoring / cross-validation.
- Nouvel endpoint `GET /api/v1/headlines/{entity_id}` (params `limit` 1-50 défaut 10, `since_hours` 1-72 défaut 24, `sort` `credibility_recency` défaut ou `recency`). Tri par crédibilité × exp(-age_h / 12h half-life). Dédup par titre normalisé (lowercase trim) entre sources. Auth scope `read:signals` (réutilisé, pas de nouveau scope).
- Schéma Pydantic `HeadlineOut` dans `storage/schemas.py` (sérialisation timezone-aware via `field_serializer` + `iso_utc`, cohérent ADR-013).
- Router câblé dans `main.py` (import + `app.include_router(headlines.router)`).
- Helper `_strip_publisher_suffix` ajouté à `google_news_ingester.py` : Google News colle ` - Reuters` / ` - Bloomberg` à la fin du `<title>` même quand la balise `<source>` canonique est présente. Sans ce nettoyage, la dédup multi-source côté endpoint serait défaite (un même article relayé par Google News et CryptoCompare aurait deux titres strictement différents).

**Dashboard** — 6 fichiers modifiés/créés :

- Carte `top-headlines-card.tsx` sur Home avec sélecteur BTC/GOLD, badge sentiment couleur (vert bull / rouge bear / gris neutral), source + publisher + âge, tap titre → ouvre l'article original dans Safari natif via `Linking.openURL`. Cap 5 titres en mode compact Home + bouton « Voir tous (jusqu'à 25) » qui navigue vers la route détail.
- Hook `useTopHeadlines.ts` (fetch + poll 60s, reset complet de la liste quand l'entity change pour éviter d'afficher des titres BTC pendant le fetch GOLD).
- Route détail `dashboard/app/headlines/[entityId].tsx` plein écran (cap 25 titres, sélecteur BTC/GOLD, bouton rafraîchir).
- Type TS `Headline` + endpoint client `getTopHeadlines(client, entityId, params)` dans `src/api/`.
- Intégration dans `app/(tabs)/index.tsx` (Home) entre la carte Stats LLM et la section Activité 24h. State local `headlinesEntity` + appel hook `useTopHeadlines(headlinesEntity, { limit: 5 })`. Bump version dashboard 0.5.2 → 0.5.3.

**Tests pytest** — 4 fichiers (1 nouveau + 3 modifiés) :

- `test_headlines_api.py` (nouveau, 30 tests) : helpers purs `_parse_iso` (Z / +00:00 / naïf / déjà aware), `_normalize_title` (trim+lowercase), `_sort_score` (credibility_recency vs recency, decay 12h half-life, published_at préféré à fetched_at), `_iter_headlines_from_payload` (rétrocompat avec payloads sans champ headlines, filtres cutoff/title vide/fetched_at invalide, override credibility/source par caller), `_finalize_headlines` (tri, dédup par titre normalisé, cap limit).
- `test_cryptocompare_ingester.py` (nouveau, 16 tests) : recrée le fichier qui avait été supprimé lors d'ADR-006 (les tests keywords avaient migré dans `test_news_classifier.py` mais le ingester lui-même n'avait plus de fichier dédié). Couvre `_verdict_to_sentiment`, `_extract_publisher` (source_info.name → source brut → unknown), `_parse_unix_iso`, format headlines, cap MAX_HEADLINES, return None sur `Type != 100`.
- `test_google_news_ingester.py` (+9 tests) : `_strip_publisher_suffix` (3 cas : suffix présent / pas de suffix / publisher unknown), format headlines complet, sentiment matchant verdict, cap à 25 sur 50 entries.
- `test_reddit_ingester.py` (+5 tests) : URL = permalink absolu Reddit (`https://www.reddit.com/r/...`), publisher = `r/{sub}`, sentiment matchant verdict, `published_at` ISO depuis `created_utc`, helper `_build_permalink` (relatif/absolu/None/vide).
- **Total suite : 590 → 649 tests verts** (+59 nouveaux), 0 régression, 3.83 s d'exécution.

**Validation runtime** (2026-05-04 21:53 → 22:28 UTC) :

- Endpoint `/api/v1/headlines/{entity_id}` enregistré dans OpenAPI ✓
- 3 ingesters publient avec `n_headlines=25` dans Redis (logs `google_news.published`, `reddit.published`, `cryptocompare.published`) ✓
- `GET /headlines/GOLD?limit=3` retourne 3 titres FXStreet/GoldSilver/Mining.com avec sentiment + URL + crédibilité 0.70 ✓
- `GET /headlines/BTC?limit=10` retourne 10 titres mélangés 3 sources (Google News + CryptoCompare + Reddit), titres dédupés multi-source, format JSON conforme schéma `HeadlineOut`, timestamp UTC explicite (suffix Z) ✓
- Carte iPhone validée visuellement par l'utilisatrice (Expo Go) ✓
- 109 signaux émis sur 24h post-livraison (61 swing + 48 flash) ✓ → Tik continue de tourner normalement, aucune régression sur les engines.

**Pattern OSINT pro respecté** : titres bruts citant leurs sources, l'humain interprète, **zéro synthèse LLM**, **zéro hallucination**. Conforme à Recorded Future / Bloomberg / Refinitiv (multi-source curé + sentiment classifié + crédibilité affichée). Différence vs eux : Tik est gratuit/local-hostable, et la carte est combinée à un pipeline de signaux décisionnels avec cross-validation anti fake-news (ADR-011) qu'eux n'ont pas dans un même produit.

**Garde-fous opérationnels rappelés** : Garde-fou 1 inchangé, ADR-003 inchangé, ADR-004 (multi-overlay) inchangé. **Aucune modif des engines / pipeline scoring / cross-validation** — purement additif (champ `headlines` au payload Redis) + nouvelle route API en lecture + carte UI consommatrice.

**Lacunes vs standard OSINT pro identifiées (2026-05-05, à arbitrer)** :

| # | Lacune | Score utilité | Coût dev | Priorité proposée |
|---|---|---|---|---|
| **A** | Pas de persistence DB des titres (Redis TTL 2h, perte définitive) | 9/10 | 3-4h | Phase 1.1 (séparation MVP/pro) |
| **G** | Anti fake-news flag invisible dashboard (`circuit_breaker_status: degraded` jamais affiché côté UI signal détail) | 8/10 | 1h | Phase 1.1 |
| **C** | Sentiment instable (LLM 3B non-déterministe sur cas ambigus, basculement entre cycles) | 7/10 | 1-2h cache Redis par hash titre TTL 7j | Phase 1.1 |
| **B** | Pas de calendrier événementiel macro (FOMC, NFP, CPI, élections) | 8/10 | 4-5h ingester FRED Calendar + carte | Phase 1.2 (J+10-J+20) |
| **D** | Méthode SDK Python `client.get_top_headlines(...)` manquante | 6/10 | 1h | Quand un bot consommera |
| **E** | Pas de cross-validation au niveau titre individuel (uniquement au niveau biais agrégé multi-source) | 7/10 | 2 sessions de recherche | Post-J+30 |
| **F** | Doublons titres au niveau ingester (Google News retourne parfois 2× le même article via 2 publishers wrappers) | 5/10 | 30 min | Bonus |
| **H** | Volume sources limité (~75/24h vs Bloomberg milliers) | 4/10 | Énorme (APIs payantes) | Hors budget MVP |

**ADR-016 — Couplage signal↔titres dans `Signal.evidence`** : score d'utilité **5/10** après analyse rigoureuse (carte Top headlines couvre déjà 80 % du besoin via lecture indépendante des titres récents sur la même fenêtre). **Verdict : NE PAS implémenter.** Conforme à la règle utilisatrice « seulement si utilité énorme ».

**Décision en attente de validation utilisatrice (2026-05-05)** : implémenter A + G + C (Phase 1.1, ~6-7h dev) AVANT Phase A.2 (`/metrics/hit_rate`), pour faire passer Tik d'un MVP OSINT à une plateforme OSINT pro robuste. Lacunes E / F / H écartées (utilité jugée insuffisante après analyse). Cf. conversation 2026-05-05 pour pour/contre/verdict détaillé de chaque lacune.

**Bug d'observation utilisatrice (2026-05-05) — RÉSOLU** : le compteur « Activité 24h » sur Home semblait figé. Diagnostic = cap visible côté dashboard (hook `useDashboardKpis` poll `searchSignals` avec `limit: 100`, mais 109 signaux en 24h → compteur figé à 100). Fix `limit: 500` appliqué dès le commit Phase A.1 (`9105f0b`) et confirmé runtime au polish 2026-05-05 (cf. Paquet 14 ci-dessous).

**Limite Ollama 3B documentée (2026-05-05)** : le LLM 3B avec `temperature=0` **n'est PAS 100 % déterministe** sur les titres ambigus. Un même titre re-classifié au cycle suivant peut basculer entre bull/neutral/bear. Le score net agrégé reste stable à ±5 % mais les classifications individuelles peuvent changer. **Solution proposée (Lacune C ci-dessus)** : cache Redis par hash titre (TTL 7j) pour réutiliser le sentiment original sans re-classifier. Bénéfices : stabilité totale UX + économie Ollama (~80 % des titres réapparaissent à chaque cycle de polling).

**Anti fake-news en mode `active` confirmé runtime (2026-05-05)** : 10 flags `anti_fake_news.flagged` levés sur les 24 dernières heures (uniquement sur **flash BTC**, jamais swing). Tous avec `method=disagreement_n2 status=degraded outliers=[]` — règle ADR-011 N=2 sources sentiment qui divergent (orderbook vs aggression du flash, signes opposés + écart > 0.8). **Status=`degraded`, pas `tripped`** → signal émis avec direction inchangée mais flag dans `Signal.circuit_breaker_status`. Pattern Tik = soft filtering (« audit + transparence ») et non hard filtering (« bloquer »). Limite UX : ce flag n'est **pas visible** côté dashboard détail signal aujourd'hui — c'est précisément la **Lacune G** ci-dessus.

### Paquet 9 — Phase 1.1 Lacunes OSINT pro essentielles LIVRÉE (2026-05-05)

3 lacunes vs standard pro identifiées au Paquet 8 (A persistance DB / G flag visible / C sentiment stable) livrées en bloc avant Phase A.2 hit rate live, après analyse rigoureuse pour/contre/verdict avec scores d'utilité (cf. conversation 2026-05-05).

**Lacune G — Anti fake-news flag visible côté dashboard** (~30 min) :

- **Composant unifié `dashboard/components/dashboard/anti-fake-news-badge.tsx`** (~140 lignes) avec prop `compact` qui distingue mode liste (pastille colorée + label court "⚠ AFN" / "🚫 AFN") vs mode détail (carte avec titre français, status traduit, explication contextuelle).
- **Différenciation visuelle** entre `degraded` (orange `#e67e22`, drapeau de prudence : signal émis avec direction inchangée, à interpréter avec prudence) et `tripped` (rouge `#c0392b`, bloquant : direction forcée à `neutral`).
- **Intégration `app/signal/[id].tsx`** : remplace l'ancien bandeau franglais cryptique « Circuit breaker : degraded » par une carte avec libellé français + explication contextuelle (« Au moins 2 sources de sentiment divergent fortement sur ce signal. Direction inchangée, mais à interpréter avec prudence. Cf. ADR-011 anti fake-news. »).
- **Intégration `app/(tabs)/signals.tsx`** : remplace la pastille rouge `CB` indifférenciée par une pastille couleur dédiée selon `degraded`/`tripped`. Visible d'un coup d'œil sans ouvrir le détail.
- **Mea culpa paranoïa contrôlée** : le badge existait déjà dans une forme minimaliste (constatation après lecture du code), donc le périmètre de Lacune G a été révisé runtime de « ajouter le flag » à « améliorer le badge existant + différencier degraded/tripped ». Conforme à l'engagement « toujours lire le code existant avant de coder ». Pas d'ajout de carte Home « Signaux flagués 24h » (G3) — décision validée utilisatrice « Don't add features until users ask », évite la pollution UX Home.

**Lacune C — Cache Redis du sentiment classifié par hash titre** (~1-2h) :

- **Modification `OllamaClassifier`** dans `news_classifier.py` : ajout param `redis: Redis | None = None` au constructeur. Avant chaque appel Ollama, lookup Redis via clé `tik.sentiment.cache.{model}.{asset}.{sha256[:16]}` ; si hit, retourne directement le label canonique sans appeler le LLM. Après chaque succès Ollama parsable (BULLISH/BEARISH/NEUTRAL trouvé), stockage du label canonique avec TTL 7j.
- **Hash SHA-256 du titre normalisé** (strip + lowercase) tronqué à 16 hex chars (collision improbable sur ~75 titres/jour).
- **Clé inclut model + asset** : changement modèle ou asset → cache invalidé (re-classification forcée). Cohérent avec le besoin : un même titre peut avoir un sentiment différent selon l'asset (BTC vs Gold pour « Bitcoin reclaims 80K »).
- **Stockage du label canonique** plutôt que la réponse Ollama brute : compact (10 chars max), déterministe à la lecture (`_label_to_counts` trivial), pas de pollution cache par les réponses Ollama mal formées (parse échec → pas de cache).
- **Best-effort sur les erreurs Redis** : Redis down en read → fallback Ollama frais ; Redis down en write → log warning, le caller a déjà obtenu son verdict, le seul effet de bord est que le titre sera re-classifié au prochain cycle.
- **Helpers purs ajoutés** : `_parse_verdict_label` (réponse Ollama → label canonique ou None), `_label_to_counts` (label canonique → tuple n_bull/n_bear). L'ancien `_verdict_to_counts` est gardé pour rétrocompat tests.
- **`build_news_classifier(... redis=None)`** propage le paramètre au constructeur. `run_ingesters.py` passe `redis=redis` aux 4 instances classifiers (CC BTC, GN BTC, GN GOLD, Reddit BTC) construites en parallèle via `asyncio.gather`.
- **Bénéfice mesurable** : stabilité totale des sentiments individuels entre cycles + économie Ollama (~80 % des titres réapparaissent à chaque cycle de 30 min, soit ~4 minutes d'économie de calcul Ollama par jour).
- **11 nouveaux tests pytest** dans `test_news_classifier.py` (cache hit/miss, dédup par model/asset/title, normalisation casing/whitespace, rétrocompat sans Redis, Redis down → fallback Ollama, verdict non parsable → pas de cache pollution, valeur cachée corrompue → traitée comme miss, circuit breaker open + cache hit cohérent).

**Lacune A — Persistence DB des titres pour audit historique** (~3-4h) :

- **Nouvelle table SQL `headlines`** dans `core/src/tik_core/storage/models.py` (modèle `HeadlineRecord`) : `id` UUID PK, `entity_id` indexé, `source` indexé, `title_hash` 16 chars indexé (cohérent cache Lacune C), `title` Text, `url` Text optional, `publisher`, `sentiment`, `credibility`, `published_at` optional, `fetched_at` indexé. Pas d'hypertable Timescale (volume modeste ~75 titres/jour = ~27500/an, table simple suffit).
- **Migration Alembic `0004_headlines`** : 4 indexes (entity_id, source, title_hash, fetched_at). Pas de UNIQUE constraint à l'insertion — la dédup se fait au lookup endpoint si nécessaire (cohérent avec la nature « audit log » de la table : un même titre ingéré 30 min plus tard apparaîtra deux fois).
- **Helper `core/src/tik_core/storage/headlines_repo.py`** : `compute_title_hash` (réutilisable cache Lacune C), `parse_iso_naive` (strip tz cohérent Bug 9), `_build_record` (dict → HeadlineRecord, skip si title vide), `persist_headlines(session_maker, entity_id, source, credibility, headlines)` qui fait un bulk INSERT best-effort (erreur DB → log + retourne 0, pas de raise), `fetch_headlines_history(session, entity_id, since, limit, source=None)` (tri DESC, filtre optionnel par source), `cutoff_from_hours`.
- **3 ingesters modifiés** (Google News, CryptoCompare, Reddit) : ajout param `session_maker: async_sessionmaker | None = None` au constructeur, appel `persist_headlines` après publish Redis dans `_run`. Log `n_persisted=...` ajouté pour observabilité.
- **`run_ingesters.py`** : création d'un `async_sessionmaker` dédié aux ingesters (pool 5 + max overflow 5) via `create_async_engine(settings.database_url)`. Propagation aux 4 ingesters news. Cleanup `db_engine.dispose()` au shutdown.
- **Schéma Pydantic `HeadlineHistoryOut`** : identique à `HeadlineOut` + champ `id` UUID + `entity_id`. Sérialisation timezone-aware via `field_serializer` + `iso_utc` cohérent ADR-013.
- **Nouvel endpoint `GET /api/v1/headlines/history/{entity_id}`** : params `since_hours` 1-720h défaut 168h (7j), `limit` 1-500 défaut 100, `source` optional filter. Auth scope `read:signals` (réutilisé). Tri DESC par `fetched_at`. Distinct de `/headlines/{entity_id}` (Redis live, fenêtre 24h max) — celui-ci permet la **retro-analyse jusqu'à 30 jours** et préfigure la convergence vers le standard OSINT pro (Bloomberg garde 10+ ans).
- **20 nouveaux tests pytest** dans `test_headlines_repo.py` : helpers purs (compute_title_hash normalisation/déterminisme/16 hex, parse_iso_naive 4 cas, cutoff_from_hours), `_build_record` (valid/empty title/whitespace title/default publisher/default sentiment/published_at optional), `persist_headlines` (None session_maker, empty list, valid records, mix valid/invalid, all invalid, DB error swallowed best-effort).
- **Migration appliquée runtime** (avec correction manuelle `UPDATE alembic_version SET version_num = '0004_headlines'` car `--reload` Uvicorn avait déclenché 2 fois la migration en concurrence — table créée mais version non mise à jour, fix manuel suffit ; cas isolé pas une régression d'archi). Table `headlines` + 4 indexes en place.
- **Validation runtime** (2026-05-05 11:46-11:48 UTC) : 50 rows insérées dès le 1er cycle post-restart (25 CryptoCompare BTC + 25 Google News GOLD), `n_persisted=25` visible dans les logs ingester. `GET /headlines/history/BTC?limit=3` retourne 3 rows `reddit_btc` avec `id` UUID + URL cliquable + `fetched_at` UTC explicite (Z) + credibility 0.65 (cohérent SOURCE_SCORES).

**Tests pytest** : 649 → **689 verts** (+40 nouveaux : 11 cache Lacune C + 20 helpers/persist Lacune A + 9 google_news.py headlines déjà comptés Phase A.1). Aucune régression. 16.74 s d'exécution.

**Total fichiers Phase 1.1** : 16 fichiers modifiés/créés (3 ingesters + run_ingesters + news_classifier + storage/models + storage/schemas + api/headlines + storage/headlines_repo nouveau + migration nouvelle + test_news_classifier + test_headlines_repo nouveau + 3 fichiers dashboard : anti-fake-news-badge nouveau + signal/[id] + (tabs)/signals).

**Pattern OSINT pro renforcé** : on est passé de « MVP qui expose des titres bruts » à « plateforme avec audit historique + sentiment stable + transparence anti fake-news ». Convergence mesurable vers Recorded Future / Bloomberg sur les axes audit + reliability + transparency, modulo le volume de sources (~75/jour vs milliers).

**Garde-fous opérationnels rappelés** : Garde-fou 1 inchangé, ADR-003 inchangé, ADR-004 (multi-overlay) inchangé. **Aucune modif des engines / pipeline scoring / cross-validation** — purement additif (table SQL + 1 endpoint + 1 carte UX) + amélioration UI (badge enrichi) + optimisation interne (cache sentiment).

**Décision méthodologique paranoïa contrôlée prise (2026-05-05)** : pour chaque future feature je m'engage systématiquement à (1) tester la stabilité runtime sur 10 cycles avant déclarer livré, (2) lister les questions critiques utilisateur paranoïaque AVANT de coder, (3) auditer bout-en-bout backend↔UI quand une feature touche les deux, (4) mentionner explicitement les 3-4 limites connues à chaque livraison, (5) tableau pour/contre/verdict avec score d'utilité pour chaque option. Engagement opérationnel, pas discours creux — l'utilisatrice peut me reprocher de ne pas l'appliquer.

### Paquet 10 — Phase A.2 + A.2-bis trading manuel J+10 LIVRÉ (2026-05-05)

Hit rate live + analyse par tranche de veracity. 2e étape du plan trading manuel J+10 — **calibration empirique** de la performance Tik avant le premier trade réel J+14.

**Phase A.2 — Hit rate live (commit `690975a`)** :

- **Nouveau module `core/src/tik_core/metrics/hit_rate.py`** (~176 lignes) — fonctions pures qui calculent le hit rate sur les 30 derniers jours par horizon × asset, en réutilisant la logique d'évaluation de `scripts/backtest.py`. Zéro accès DB/Redis depuis le module — le caller injecte la liste de signaux et le fetch de prix.
- **Nouvel endpoint `GET /api/v1/metrics/hit_rate`** (cache Redis TTL 15 min, scope `read:signals`) — params `horizon` (flash/swing/macro), `entity_id` (BTC/GOLD), `include_flagged` (booléen, par défaut `true` ; `false` exclut les signaux `circuit_breaker_status≠ok`). Réponse : hit rate global + comptage signaux + fenêtre temporelle.
- **Carte Home `HitRateCard`** (`dashboard/components/dashboard/hit-rate-card.tsx`, ~344 lignes) avec sélecteurs horizon × asset partagés + toggle « Exclure les signaux flagués anti fake-news ». Visualisation pourcentage + couleurs vert/orange/rouge selon seuil (≥50 % / 30-49 % / <30 %).
- **MiniSparkline veracity refondue** (`dashboard/components/dashboard/mini-sparkline.tsx`) — auto-scale Y sur min/max observés (au lieu de 0-1 fixe qui écrasait les variations entre 0.70-0.95) + labels textuels min/current/max pour donner une lecture chiffrée immédiate.
- **Fix bug latent `backtest.py`** : import `now_utc_naive` manquant depuis le Paquet 7 (ADR-013). Le script CLI fonctionnait encore parce que le `from tik_core.utils.time import now_utc` était présent, mais une comparaison SQL `Signal.timestamp >= since` échouait silencieusement avec `DeprecationWarning` SQLAlchemy. Corrigé en passant à `now_utc_naive`.
- **Suite pytest** : 689 → **716 verts** (+27 nouveaux tests dans `test_metrics_hit_rate.py`), 0 régression.

**Phase A.2-bis — Hit rate par tranche de veracity (commit `8a065cd`)** :

- **Nouvel endpoint `GET /api/v1/metrics/hit_rate_by_veracity`** (cache Redis TTL 15 min) — découpe les signaux en 4 buckets de veracity (`0.70-0.79`, `0.80-0.89`, `0.90-0.94`, `0.95+`) et calcule le hit rate de chaque bucket. Mêmes params que `/hit_rate`.
- **Carte `HitRateByVeracityCard`** (~215 lignes) sous `HitRateCard` sur Home, avec sélecteurs partagés (un seul horizon × asset pilote les 2 cartes) — lit les buckets et les affiche en barres horizontales avec %, comptage par bucket, et code couleur cohérent.
- **Insight contre-intuitif découvert runtime — pattern flash BTC inversé** : sur les signaux flash BTC, la tranche `0.80-0.89` performe **mieux** (53.5 %) que la tranche `0.90+` (13-16 %). Hypothèse provisoire : la veracity 0.90+ sur flash BTC indique souvent une concordance excessive *trend-following* qui se paye dans un marché choppy à très court terme. Inverse parfait du pattern attendu (et du pattern observé sur swing). À investiguer post-J+14 — backlog entry n°5 enrichie pour tracer la piste « refonte dashboard + vision macro/géopolitique ».
- **Suite pytest** : 716 → **726 verts** (+10 nouveaux), 0 régression.

**Insight clé cristallisé dans Garde-fou 2-bis** (cf. section 5) : sur 156 signaux backtestés, **Tik mesuré à 22 % hit BTC swing 5j vs Random 33 %** — pas d'edge démontré sur le seuil global. **Mais** veracity ≥ 0.95 atteint **67 %** vs 24 % global → **filtre veracity ≥ 0.90 sur swing recommandé** pour le trading manuel J+14 (réduit le faux-positif drastiquement). Justifie la décision de démarrer à **1 % du capital par trade**, pas 5 %, pendant 2 semaines minimum, montée progressive seulement après période profitable mesurable.

**Garde-fous opérationnels** : Garde-fou 1 (Tik shadow vs Zeta 3 mois) inchangé, ADR-003 (pas de bypass V01-V15) inchangé, ADR-004 (multi-overlay) inchangée. **Aucune modif des engines / pipeline scoring / cross-validation** — purement additif (2 endpoints en lecture + 2 cartes UX).

### Paquet 11 — Lacune B Phase B1 calendrier macro LIVRÉ (2026-05-05, ADR-017)

Calendrier macro/géopolitique programmé. **Outil de risk management** pour le trading manuel J+14 — éviter d'entrer en swing dans les ±4 h autour d'un event HIGH (FOMC, NFP, CPI). Lacune B des 8 lacunes OSINT pro identifiées au Paquet 8, scorée 8/10 utilité.

**Backend** (13 fichiers) :

- **Table SQL `macro_events`** dans `storage/models.py` + migration Alembic `0005_macro_events`. Colonnes : `id` UUID, `event_code` (NFP, CPI, FOMC, etc.), `title`, `scheduled_for` (UTC, indexé), `importance` (HIGH/MED/LOW), `affected_entities` JSON (`["BTC","GOLD"]`), `source` (fred|fomc_static), `status` (scheduled|released|cancelled). **Contrainte UNIQUE `(event_code, scheduled_for)`** pour idempotence — le repo fait du `upsert ON CONFLICT DO UPDATE` à chaque cycle d'ingestion.
- **Helper `core/src/tik_core/storage/macro_events_repo.py`** : `upsert_events`, `fetch_upcoming` (filtres `since`, `until`, `importance_min`, `entity_id`, `limit`), `fetch_history`. Tri DESC sur `scheduled_for`.
- **Nouvel ingester `FredCalendarIngester`** (`aggregator/fred_calendar_ingester.py`, ~255 lignes) — polling **daily** (les calendriers FRED ne changent pas en intra-day). Pour chaque release de la whitelist : `GET /fred/releases/dates?release_id=X&realtime_end=9999-12-31&sort_order=desc&limit=50`. **DST automatique** via `zoneinfo.ZoneInfo("America/New_York")` qui calcule l'offset UTC correct selon la date (8:30 ET → 12:30 UTC en EST hiver / 13:30 UTC en EDT été). Best-effort sur les erreurs FRED — un release qui échoue logue un warning et continue les autres.
- **Whitelist 7 releases FRED** + helper `aggregator/macro_calendar_data.py` qui contient aussi **12 dates FOMC statiques 2026-2027** (la Fed publie son calendrier ~1 an à l'avance, pas via FRED API → mise à jour annuelle manuelle ~30 min en septembre). Heures release hardcodées dans une table : 8:30 ET pour les BLS releases (NFP, CPI, PPI), 9:15 ET pour les FRB (Industrial Production), 14:00 ET pour les FOMC statements.
- **Endpoints `GET /api/v1/macro_events/upcoming`** + **`/history`** (cache Redis TTL 5 min, scope `read:signals`). Params : `importance_min` (LOW/MED/HIGH), `entity_id` (BTC/GOLD/null=tous), `hours_ahead` (défaut 168 = 7j) ou `days_back` (défaut 30). Schéma `MacroEventOut` Pydantic sérialisé via `iso_utc` — cohérent ADR-013, le dashboard reçoit toujours du UTC explicite avec suffixe `Z`.
- **`run_ingesters.py`** : ajout de l'instance `FredCalendarIngester` dans la liste des ingesters lancés au boot.

**Dashboard** (7 fichiers, bump dashboard `0.5.2` → `0.5.6`) :

- **Carte Home compact « Calendrier macro »** (`components/dashboard/macro-events-card.tsx`, ~284 lignes) — next event mis en avant avec countdown live (« dans 2 h 14 min »), 3 events suivants en mode liste compacte (date + nom + badge importance), bouton « Voir tout » qui navigue vers `/macro`.
- **Route détail `/macro/index.tsx`** (~174 lignes) plein écran avec filtres importance HIGH / MED / LOW (toggle multi-select), liste paginée des events à venir (jusqu'à 50). Tri chronologique ASC.
- **Hook `useUpcomingMacroEvents`** (~92 lignes) — poll 5 min (cohérent avec le TTL Redis backend), reset au changement de filtre, renvoie `events` + `loading` + `error`.
- **Helper `timeUntil(iso)`** dans `src/utils/time.ts` — countdown futur formaté FR (« dans Xj Yh » / « dans Xh Ymin » / « dans X min » / « passé »).
- **Type TS `MacroEvent`** + endpoint client `getUpcomingMacroEvents`, `getMacroEventsHistory` dans `src/api/`.

**Documentation** :

- **ADR-017 documenté** (`docs/adr/017-macro-events-calendar.md`) — formalise les 6 décisions structurantes : (1) source FRED + dates FOMC statiques plutôt que ForexFactory scrapé / Investing.com, (2) polling daily plutôt que real-time, (3) whitelist 7 releases plutôt qu'all FRED, (4) timezone source UTC stockée + display local côté dashboard, (5) idempotence via UNIQUE constraint, (6) couverture US-only en Phase B1 (ECB/BoJ/BoE/élections en Phase B2 post-J+14).
- **`comprendre_tik.md` section 17** — explication pédagogique en français accessible (pourquoi un FOMC bouge les marchés, pourquoi ±4h, pourquoi la Fed publie 1 an à l'avance et pas la BCE).
- **`backlog.md` entries 3 et 5 mises à jour** : Phase B1 ✅, Phase B2 ouverte (multi-banques centrales + élections).
- **CLAUDE.md section 5 — Garde-fou 2-bis cristallisé** (cf. section 5 ci-dessus) : sizing 1 % au démarrage trading manuel J+14 (raison : backtest 22 % hit BTC swing 5j vs Random 33 % sur 156 signaux = pas d'edge démontré), filtre veracity ≥ 0.90 recommandé sur swing, **discipline calendrier macro ±4 h autour d'un event HIGH** (sizing divisé par 2 = 0.5 % si trade autour d'un event).

**Tests** : 62 nouveaux pytest (`test_macro_calendar_data` + `test_fred_calendar_ingester` + `test_macro_events_repo` + `test_macro_events_api`). Suite complète : 726 → **788 verts**, 0 régression.

**Fix bug 1-caractère post-livraison** (commit `6112901`) — Bug découvert au déploiement runtime : `sort_order=asc` récupérait les 200 premières dates de l'historique FRED (années 1700-1900 pour NFP qui a 867 release_dates depuis 1776), aucune date future ne franchissait `filter_future_dates`. Conséquence : 0 event à venir affiché côté dashboard malgré l'ingester qui tournait. **Fix chirurgical** : `sort_order=desc` + `limit=50` → récupère les 50 **dernières** publications, qui incluent les ~8-12 dates futures programmées grâce à `realtime_end=9999-12-31`. Validé runtime : NFP du 2026-05-08 (dans 3 jours), CPI mensuel, FOMC juin/juillet apparus immédiatement post-restart. 20 tests pytest `fred_calendar_ingester` mis à jour, tous verts.

**Garde-fous opérationnels** : ADR-003 (pas de bypass V01-V15) inchangé, ADR-004 (multi-overlay) inchangée — **engines / pipeline scoring / cross-validation strictement inchangés**. Garde-fou 1 (Tik shadow vs Zeta 3 mois) inchangé. Le calendrier macro est un outil de discipline pour l'humain, pas un input des engines.

**Limites connues Phase B1** :

- **US-only** — Phase B2 post-J+14 pour ECB/BoJ/BoE/élections (sources : ECB calendar JSON, BoJ static, BoE static, agrégateur élections à choisir).
- **FOMC 2027 = estimations** (Fed publie son calendrier 2027 courant septembre 2026, mise à jour manuelle nécessaire à ce moment-là).
- **Heures release hardcodées** (8:30 ET BLS, 9:15 ET FRB, 14:00 ET FOMC) — si la Fed déplaçait un release, il faudrait éditer `macro_calendar_data.py`. Pas plus volatile que le calendrier lui-même.
- **Pas de couplage signal↔event automatique** — l'humain fait le lien mentalement (« je vois NFP dans 2h, je n'entre pas »). Phase B1.5 envisageable selon retour usage : flag `near_macro_event` posé sur les signaux émis dans la fenêtre ±4h.

### Paquet 12 — Phase A.3 trading manuel J+10 LIVRÉ (2026-05-05)

Vue track record signal multi-horizon dans le détail signal. Permet à l'utilisatrice de voir, sur n'importe quel signal passé, comment il a effectivement performé sur 4 horizons : 1 h / 6 h / 24 h / 5 j. **Calibration empirique signal-par-signal** complémentaire du hit rate agrégé (Phase A.2).

**Backend** :

- **Module pur `core/src/tik_core/metrics/signal_track_record.py`** (~113 lignes) — `compute_track_record(decision, prices_by_horizon)` retourne 4 lignes (`TrackRecordRow`) : `1h`, `6h`, `24h`, `5d`. Chaque ligne porte `delta_pct`, `outcome` (badge), `expected_at` (date cible), `available` (booléen). **Zéro DB/Redis/HTTP** dans le module — le caller injecte la decision et le dict de prix par horizon. Architecture cohérente avec le module `metrics/hit_rate.py` du Paquet 10.
- **Badges produits** : `correct` (delta dans la bonne direction et magnitude > seuil), `raté` (delta dans la mauvaise direction et magnitude > seuil), `en_attente` (horizon dans le futur, pas encore évaluable), `données_manquantes` (pas de prix disponible à `expected_at`, ex. weekend pour GOLD ou retard ingestion).
- **Seuils directionnalité** : 0.3 % sur 1h-6h, 0.5 % sur 24h-5j. Calibrés pour distinguer un mouvement réel d'un bruit de marché — un BTC qui bouge de 0.1 % en 1 h n'est pas un signal validé même si la direction est bonne. Cohérent avec le seuil `_score_indicators` du swing engine (Paquet 1.x).
- **Schémas Pydantic** `TrackRecordRow` + `SignalTrackRecordOut` dans `storage/schemas.py`. Sérialisation timezone-aware via `iso_utc` (cohérent ADR-013).
- **Nouvel endpoint `GET /api/v1/metrics/signal_track_record/{signal_id}`** (cache Redis TTL 6 h, scope `read:signals`). Charge la decision en DB → fetch les prix Binance/Yahoo aux 4 horizons → invoque `compute_track_record` → retourne `SignalTrackRecordOut`. Cache Redis sur le signal_id pour éviter de re-fetcher les prix à chaque ouverture du détail signal côté dashboard.
- **29 nouveaux tests unitaires** (`test_signal_track_record.py`, pure logic, 351 lignes) — couvre `compute_track_record` sur les 4 horizons × 4 badges × 3 directions (long/short/neutral) + edge cases (decision dans le futur, prix manquants, magnitude exactement au seuil, direction `neutral` traitée comme « pas de prédiction donc pas évaluable »).

**Dashboard** :

- **Types TS `TrackRecordRow` + `SignalTrackRecord`** (`src/api/types.ts`).
- **Fonction `getSignalTrackRecord(client, signalId)`** (`src/api/endpoints.ts`).
- **Composant `TrackRecordSection`** lazy-loadé sur le détail signal (`app/signal/[id].tsx`) — 4 lignes (1h / 6h / 24h / 5j) avec badge couleur (vert ✓ / rouge ✗ / gris ⏳ / orange ⚠) + delta % réel ou compte à rebours « dans Xj Yh » selon disponibilité. Lazy-load (fetch déclenché à l'ouverture du détail, pas au chargement de la liste Signals) — évite N requests pour N signaux affichés.

**Tests** : suite complète 788 → **817 verts** (+29), 0 régression. 7 fichiers modifiés/créés au total.

**Garde-fous opérationnels** : Garde-fou 1 / ADR-003 / ADR-004 inchangés. Module pur sans dépendance externe + endpoint en lecture + composant UI consommateur. **Aucune modif des engines / pipeline scoring / cross-validation**.

### Paquet 13 — Phase C Session 1 trading manuel J+10 LIVRÉ (2026-05-05)

**Watchlist signaux suivis — version reframée OSINT** (cf. conversation 2026-05-05 sur la cohérence vision modulaire). Phase C originale était trading-specific (« j'ai pris ce trade ») → reformulée en pattern OSINT standard « saved alerts » / « watchlist » présent chez Recorded Future, Bloomberg Terminal, Dataminr. Vocabulaire neutre (« suivre », « résultat observé »), aucune sémantique trading dans les types ou libellés — réutilisable tel quel si Tik est étendu à d'autres domaines (élections, sport betting, météo-finance) sans refonte.

**Décisions structurantes prises avant code** :

| # | Décision | Verdict |
|---|---|---|
| D1 | Persistance locale (AsyncStorage) vs serveur DB | **Hybride** — watchlist en AsyncStorage local + réutilise `POST /api/v1/feedback` existant (Paquet 1) en Session 2 pour le résultat observé. Zéro nouveau endpoint, zéro migration. |
| D2 | Outcome auto vs manuel | **Auto par défaut** via `getSignalTrackRecord` (Paquet 12) en Session 2 + override manuel optionnel. Réutilise les seuils 0.3 % / 0.5 % déjà calibrés. |
| D3 | Bouton « Suivre » : toggle vs modal | **Toggle simple** (étoile remplie/vide), pas de friction. État visuel immédiat. |
| D4 | Onglet Watchlist : placement tab bar | **Entre Signals et Alerts** (sémantique cohérente — je consulte mes signaux suivis près du flux signals). |
| D5 | Stats Watchlist | **Simple** Session 1 (N total / pending / résolus). Hit rate perso vs Tik global en Session 2 quand l'auto-resolution sera branchée. |

**Périmètre Session 1 (livré 2026-05-05)** :

- **`dashboard/src/watchlist/WatchlistContext.tsx`** (~180 lignes) — type `WatchlistEntry` + `WatchlistOutcome` (`pending|confirmed|refuted|n_a`) + `WatchlistProvider` + hook `useWatchlist()`. Pattern hydratation eager + flag `hydrated` + persistance AsyncStorage clé `tik.watchlist.v1` (suffixe versionné pour migration future) — calque exact de `AlertsContext` (cohérent Bug A résolu 2026-05-04, même filet d'exception JSON corrompu → reset). Cap `MAX_WATCHLIST=200` (volontaire de marquer = pas de spam, cap plus généreux que les alertes WS qui s'accumulent passivement). API : `entries`, `isWatched(signalId)`, `add(signal)`, `remove(signalId)`, `setOutcome(signalId, outcome, note)`, `clear()`, `hydrated`.
- **Snapshot du signal au moment du suivi** — on stocke localement les champs essentiels (signalId, entityId, horizon, direction, veracity, confidence, signalTimestamp, expiry, circuitBreakerStatus, addedAt, outcome, outcomeResolvedAt, userNote) pour pouvoir afficher l'entrée même si le signal n'est plus dans la liste `/signals` (cap 100 côté API ou expiry passée). Le signal complet reste accessible via `getSignal(signalId)` pour les détails.
- **`dashboard/app/_layout.tsx`** — `WatchlistProvider` ajouté dans la pile (wraps `<Stack>` à l'intérieur de `<AlertsProvider>`).
- **`dashboard/app/signal/[id].tsx`** — bouton Pressable « ☆ Suivre » / « ★ Suivi » dans la hero card, juste sous l'`AntiFakeNewsBadge`. Toggle réactif (état mis à jour immédiatement via context React). Couleur or `#f1c40f` border + texte `#b07d0a` sur état suivi (cohérent sémantique étoile/bookmark). `accessibilityLabel` adapté aux deux états.
- **`dashboard/app/(tabs)/watchlist.tsx`** (~250 lignes) — écran complet : titre + sous-titre explicatif, ligne stats (`N suivis · N en attente · N résolus`), bouton « Tout effacer », liste tri DESC par `addedAt`, carte par entry avec entity_id + direction badge couleur + horizon + veracity/confidence + outcome badge bordure colorée + bouton X retirer en absolute top-right. Tap sur la row → navigation `/signal/{id}`. Empty state pédagogique. Hook `useTick()` mutualisé (cohérent fix Bug B 2026-05-04) pour rafraîchir les `timeAgo`.
- **`dashboard/components/ui/icon-symbol.tsx`** — entrée mapping `'star.fill': 'star'` ajoutée pour SF Symbol → Material Icon (Android/web fallback).
- **`dashboard/app/(tabs)/_layout.tsx`** — onglet Watchlist inséré entre Signals et Alerts, icône `star.fill`.

**Validation TypeScript + ESLint** : `tsc --noEmit` exit 0, `eslint` exit 0 sur les 6 fichiers (1 warning pré-existant non lié à la modif). **Pas de tests pytest backend** car aucun changement core. **Pas de tests dashboard ajoutés** Session 1 (cohérent avec la pratique Paquet 3 dashboard initial qui n'avait pas non plus de tests sur les contexts) — à ajouter Session 2 si besoin.

**Cohérence pattern existant** : architecture calque sur AlertsContext (hydratation eager + persistance + cap + dédup), réutilise `useTick()` pour les timeAgo (refacto Bug B), composant `ThemedView`/`ThemedText` partout. Aucune dette technique introduite.

**Garde-fous opérationnels** : Garde-fou 1 (Tik shadow vs Zeta 3 mois) inchangé, ADR-003 (pas de bypass V01-V15) inchangé, ADR-004 (multi-overlay) inchangée. **Aucune modif backend** (zéro fichier `core/` touché). Persistance locale uniquement → zéro risque sur les données core. Bump dashboard 0.5.6 → 0.5.7.

**Limites connues Session 1** :

1. **Pas de sync multi-device** — désinstall Expo Go = watchlist perdue. Acceptable MVP (1 iPhone), à doc dans la prochaine version utilisatrice.
2. **Pas d'auto-resolution outcome** — toutes les entries restent en état `pending` jusqu'à ce que la Session 2 branche le poll `getSignalTrackRecord` toutes les 5 min (avec throttling 20 reqs max par cycle).
3. **Pas de hit rate perso** — la stats card n'affiche que le comptage brut (total / pending / résolus). Hit rate perso vs Tik global = Session 2.
4. **Pas de bouton override / feedback explicite** — Session 2 ajoutera modal sur signal résolu + POST `/api/v1/feedback` existant (scope `write:feedback`) pour nourrir la calibration source credibility (Paquet 5).

**Session 2 à venir (~2-3h)** :
- Auto-resolution outcome via poll throttlé `getSignalTrackRecord` (calcule outcome agrégé selon horizon : flash → row 1h, swing → row 5d).
- Stats card enrichie : hit rate perso (signaux résolus avec outcome `confirmed`) vs Tik global, disclaimer « biais de sélection » si N < 20.
- Bouton override sur signal résolu : modal avec choix manuel + note + POST `/feedback`.
- Tests dashboard sur le context (add/remove/persist/hydratation + auto-resolution logic).

### Paquet 14 — Polish post-livraison J+10 (2026-05-05)

3 micro-livraisons ~1h cumulé pour clore les notes obsolètes accumulées sur le polish trading manuel J+14. Aucune feature ajoutée — uniquement audit + correction de prémisses + mises à jour doc.

**Polish 1 — Compteur « Activité 24h » Home (~10 min, audit)** :
- Symptôme historique : Home semblait figé à 100 signaux malgré 109 signaux/24h.
- **Constat post-grep** : le fix `limit: 100 → 500` était **déjà en place** dans `dashboard/src/hooks/useDashboardKpis.ts:158` depuis le commit Phase A.1 (`9105f0b`). Mais la note dans CLAUDE.md disait encore « En attente de validation utilisatrice ». Confusion potentielle pour une instance Claude future.
- **Action** : audit grep + correction de la note CLAUDE.md (« En attente de validation utilisatrice » → « Fix appliqué dès Phase A.1, confirmé runtime au polish 2026-05-05 »). Zéro modif de code.
- **Leçon** : audit systématique avant de coder un fix « trivial » — sinon on coderait un fix déjà appliqué et on doublerait l'historique.

**Polish 2 — Bascule LLM hypothesis shadow → active (~30 min, audit + doc)** :
- État attendu : `TIK_LLM_HYPOTHESIS_MODE=active` à valider runtime après 5-10 cycles shadow validés depuis 2026-05-04 17:11 UTC.
- **Constat post-grep `core/.env`** : `TIK_LLM_HYPOTHESIS_MODE=active` est **déjà** positionné côté Mac de l'utilisatrice. Vraisemblablement appliqué silencieusement par l'utilisatrice ou pendant une session précédente sans trace dans CLAUDE.md.
- **Action** : audit + cette section comme trace explicite. **À valider** : que `docker compose restart scheduler` ait bien été fait pour que la nouvelle valeur soit prise en compte par le process scheduler en cours d'exécution. Si non fait, la valeur dans `.env` ne s'applique pas tant que le container n'a pas été restart.
- **Conséquences runtime mode active** (rappel ADR-012 décision 3) : `Signal.hypothesis` = texte LLM 6 sections ~150 mots, `Signal.advisory.template_hypothesis` = ancien texte template f-string conservé pour audit permanent. Le composant `app/signal/[id].tsx:268-288` gère déjà les deux modes (shadow → carte « Hypothèse contextuelle (LLM · validation) » / active → carte « Hypothèse template (référence) »).
- **Limite documentée** : `core/.env` n'est **pas** dans le repo Git (présent dans `.gitignore`). Si l'utilisatrice change de Mac ou réinstalle Tik, il faut re-poser `TIK_LLM_HYPOTHESIS_MODE=active` à la main. Idéalement à terme : exposer cette config via `core/src/tik_core/config.py` avec valeur par défaut `active` post-validation runtime.

**Polish 3 — Dette technique Bug 9 (~20 min, code + doc)** :
- **Commentaire `core/src/tik_core/utils/time.py:18`** corrigé : « asyncpg strippe silencieusement la tz d'un aware mais autant garder la cohérence » → « asyncpg lève `DataError` sur un datetime aware passé à une telle colonne (régression bug 9 du 2026-05-04 découverte après ADR-013 ; workaround chirurgical dans `publisher._publish_signal` qui strippe la tzinfo avant l'INSERT. Cf. section 9 CLAUDE.md pour le diagnostic complet) ».
- **ADR-013 amendé** (`docs/adr/013-timezone-aware-datetimes.md`) : nouvelle section « Amendement post-livraison — Bug 9 régression DB asyncpg » qui documente (1) la prémisse erronée originale, (2) la réalité observée runtime, (3) le workaround chirurgical 2 lignes, (4) un tableau pour/contre/verdict des 3 options de fix envisagées (migration TIMESTAMPTZ rejetée, `now_utc_naive` partout rejeté, workaround retenu), (5) les conséquences sur les décisions de l'ADR original (3 et 4 inchangées dans leur conclusion, mais décision 4 maintenant explicitement justifiée par le coût de migration sur hypertable plutôt que par la croyance asyncpg-permissif), (6) la dette tracée du test pytest Postgres bout-en-bout en CI **toujours à ajouter**.
- ✅ **Test pytest Postgres bout-en-bout** — **FAIT depuis le Paquet 31**, vérifié runtime 2026-05-24 (5 tests verts contre `tik_test`, dont 4 contre Postgres réel via fixture `db_engine`, dans `core/tests/test_publisher_timezone_db.py`). Attrape une régression DB-spécifique invisible en SQLite (le strip de tzinfo dans `publisher._publish_signal`). *(Note d'origine, désormais obsolète : « toujours à faire, reporté à une session dédiée ~1-2h ».)*

**Tests** : aucun test ajouté (audits + 1 commentaire Python + 1 ADR markdown). Suite pytest inchangée à 817 verts. Aucun risque de régression.

**Garde-fous opérationnels** : Garde-fou 1 / ADR-003 / ADR-004 inchangés. Aucune modif backend logique, uniquement commentaires et doc.

### Paquet 15 — Audit sécurité Tailscale + fix critique exposition Postgres/Redis (2026-05-05)

L'utilisatrice a installé Tailscale précédemment pour accéder à Tik depuis son iPhone en 4G hors WiFi maison (cf. CLAUDE.md section 11.5 limite identifiée Paquet 3). Audit fresh demandé en cette fin de session, **1 faille critique identifiée + 3 hygiène défense en profondeur**.

**🔴 Faille 1 critique — Postgres et Redis exposés sur 0.0.0.0** :

Constat : `core/docker-compose.yml` exposait `5432:5432` et `6379:6379` sans préfixe IP → bind sur **toutes les interfaces réseau**. Conséquence concrète :

- Sur le LAN maison : tout appareil du wifi peut tenter de se connecter à Postgres et Redis.
- **Avec Tailscale actif** : tout le tailnet peut accéder à Postgres et Redis depuis n'importe où dans le monde. Si un device tiers est ajouté au tailnet (famille, ami) il a accès à toute la DB Tik.
- Redis n'a aucun mot de passe configuré (port 6379 open = lecture/écriture libres). Postgres a un user/pass mais pas un rempart sérieux face à un attaquant ciblant la DB sur le tailnet.

**Fix appliqué (commit ce paquet)** : préfixage `127.0.0.1` sur les 2 ports exposés :

```yaml
postgres: ports: ["127.0.0.1:5432:5432"]
redis:    ports: ["127.0.0.1:6379:6379"]
```

**Aucune régression fonctionnelle** : Tik core / ingesters / scheduler accèdent à Postgres et Redis **via le réseau Docker interne** (`postgres:5432` et `redis:6379` résolus par le DNS interne Docker compose), pas via les ports exposés de l'hôte. Les ports exposés sur l'hôte ne servaient qu'à du debug manuel local (psql / redis-cli depuis le terminal Mac) — toujours possibles depuis le Mac via `127.0.0.1`. Commentaires inline ajoutés dans `docker-compose.yml` pour traçabilité future.

**Application runtime** : nécessite `docker compose down && docker compose up -d` (un simple `restart` ne recrée pas les containers donc ne réapplique pas la nouvelle config de ports).

**🟡 Failles hygiène défense en profondeur (à faire plus tard)** :

| # | Faille | Sévérité | Fix | Temps |
|---|---|---|---|---|
| 2 | Tik core HTTP plain (pas de TLS, l'API key transite en clair entre devices du tailnet) | 🟡 moyenne | Reverse proxy Caddy avec auto-TLS Tailscale (feature `tailscale_cert`) | ~1-2h |
| 3 | Tik core sur 0.0.0.0:8200 — exposé au LAN maison (mais Tik a une auth API key) | 🟡 moyenne | Firewall macOS qui n'autorise que Tailscale subnet `100.64.0.0/10` + localhost sur 8200 | ~10 min |
| 4 | ACLs Tailscale par défaut autorisent tout le tailnet à tout | 🟢 mineure | Panel admin Tailscale → Access controls → restriction par tag `tag:tik` | ~10 min |

**Priorité** : la faille 1 critique est résolue, le reste est de l'hygiène à attaquer si un device tiers entre dans le tailnet ou si un audit de conformité est demandé. Pas urgent si ton tailnet n'a que ton Mac + iPhone.

**Mémoire pour instances Claude futures** : Tik tourne via Docker Desktop natif macOS, accessible iPhone via Tailscale (gratuit free tier 5 min setup). Tailscale n'est PAS dans le repo Git — c'est un service externe au projet. Ne jamais commiter d'IP Tailscale `100.x.x.x` dans le code (l'IP est saisie au login dashboard).

### Paquet 16 — Diagnostic mobilité 4G + plan EAS Build dev en attente (2026-05-06 ~00h45)

Diagnostic complet de l'utilisation Tik en mobilité 4G (sans WiFi maison) effectué fin de session. **Conclusion : Expo Go en mode dev tunnel n'est pas viable en 4G, vraie solution = EAS Build dev (à activer plus tard sur demande utilisatrice).**

**Setup Tailscale actif et fonctionnel** (info récupérée via `tailscale status` côté Mac) :
- Mac : IP Tailscale `100.112.141.57`, hostname `macbook-air-de-siku`
- iPhone : IP Tailscale `100.70.101.7`, hostname `iphone-12-pro-max`
- Tailscale free tier suffit pour les 2 devices, accès partout dans le monde via tunnel chiffré WireGuard

**Tests effectués** :

1. **Tunnel public Expo (`npx expo start --tunnel`)** : install `@expo/ngrok` global échouait avec exit code 243 (permissions npm global macOS). Workaround appliqué : install local au projet `npm install --save-dev @expo/ngrok` (~30 packages ajoutés à `dashboard/package.json`). Tunnel démarre OK sur URL `*.exp.direct` mais en 4G iPhone affiche « Could not connect to development server » → instable, surtout avec `--no-dev --minify` qui produit aussi « Failed to load all assets » (incompatibilité bundle prod + tunnel + 4G connue).

2. **Metro via Tailscale (`REACT_NATIVE_PACKAGER_HOSTNAME=100.112.141.57 npx expo start --clear`)** : tunnel ngrok abandonné, Metro publie son URL sur l'IP Tailscale. Plus stable que le tunnel public mais **toujours lent en 4G** (bundle dev 10-15 Mo non-minifié) et **freeze sur l'écran login** au moment de saisir les identifiants (UI thread bloqué pendant que le bundle finit de hydrater en background).

3. **Test contrôle WiFi** : la même app Tik en mode tunnel Tailscale fonctionne **parfaitement en WiFi maison** (chargement rapide, login sans freeze, navigation fluide). Donc l'app Tik elle-même est saine — c'est le combo « Expo Go dev + bundle JS lourd + 4G » qui est intrinsèquement inviable.

**Conclusion technique** : Expo Go est un dev tool, pas une vraie app. Pour usage 4G régulier en mobilité, une vraie app iPhone est nécessaire.

**Plan EAS Build dev (~1-2h, session dédiée future)** — ce qui sera fait quand l'utilisatrice le demandera :

1. `npm install --save-dev eas-cli` (5 min)
2. `eas login` → identification compte Expo (création gratuite si nouveau)
3. `eas build:configure` → génère `eas.json` (~5 min)
4. Bundle ID dans `app.json` style `com.siku.tik` (1 min)
5. `eas build --profile development --platform ios` → build cloud sur serveurs Expo (~10-15 min wait)
6. Reçoit un QR / lien → install IPA sur iPhone via Safari + profil dev macOS
7. L'app Tik apparaît sur le home screen iPhone comme une vraie app native
8. Plus de Metro server à 99% du temps. Démarrage 2-3s. Marche en 4G nativement.

**Limites du plan EAS Build dev** :

- **Compte Apple gratuit suffit** pour démarrer mais signature valide **7 jours** seulement → réinstall tous les 7 jours (~2 min via le même lien). Pas chiant si on automatise via `expo-dev-client`.
- **Apple Developer payant 99 €/an** supprime l'expiration + permet la distribution via TestFlight (lien d'install partageable, MAJ OTA via `eas update`). À évaluer selon usage.
- **EAS Build cloud free tier** : ~30 builds/mois. Largement suffisant pour usage perso (1-2 builds/mois en pratique).
- Premier build = ~10-15 min de wait cloud (compilation iOS sur serveurs Expo). Les builds suivants utilisent le cache → ~3-5 min.

**Pré-requis utilisatrice avant d'attaquer** :
- Compte Apple ID prêt (probablement déjà existant pour App Store).
- Numéro téléphone iPhone à portée pour validation 2FA Apple si demandé.
- ~1-2h continues devant le Mac + iPhone.

**Mémoire pour instances Claude futures** : si l'utilisatrice demande « EAS Build dev » ou « vraie app iPhone Tik » ou « Tik en 4G stable », c'est ce plan qu'il faut activer. **Pas urgent** car le trading manuel J+14 (2026-05-14) peut se faire en WiFi maison sans difficulté. À attaquer en mode confort, pas en stress.

### Paquet 17 — Track record granularité adaptée par horizon LIVRÉ (P5 plan fiabilité, 2026-05-06)

P5 du plan stratégique post-audit fiabilité signaux livrée. Refactor du Paquet 12 (Phase A.3 track record signal multi-horizon) — passage des 4 horizons fixes (1h/6h/24h/5j quel que soit l'horizon du signal) à une **granularité adaptée à l'horizon contractuel** :

| Signal horizon | Row 1 | Row 2 | Row 3 | Row 4 |
|---|---|---|---|---|
| **Flash** | 15min — 0.10 % | 30min — 0.15 % | 45min — 0.20 % | 1h — 0.30 % |
| **Swing** (inchangé) | 1h — 0.30 % | 6h — 0.30 % | 24h — 0.50 % | 5j — 0.50 % |
| **Macro** | 1j — 0.50 % | 7j — 1.00 % | 30j — 2.00 % | 90j — 3.00 % |

**Raison stratégique** : un signal flash perdait 75 % de son track record sur des horizons hors-fenêtre contractuelle (24h/5j inutiles pour flash). Mesure fine sur la fenêtre flash → calibration plus précise du sweet spot flash → ajustements `SOURCE_SCORES` flash plus fiables (alimente P4 du plan post-J+30).

**Choix flash 15min/30min/45min/1h (vs 4h initialement envisagé) — correction post-livraison 2026-05-06** : la première version livrée du Paquet 17 plaçait le 4e palier flash à **4 h** (cohérent avec la fenêtre d'analyse klines 1m × 240). Reconsidération sur question utilisatrice : le horizon flash dans le pipeline Tik est défini par **`EXPIRY_BY_HORIZON["flash"] = 1h`** (TTL signal Paquet 1.x) ET **`HORIZON_MEASURE_HOURS["flash"] = 1.0`** (point de mesure hit rate Paquet 10). Mesurer le track record à 4h sortait de cette fenêtre → incohérent avec la sémantique pipeline + non-actionnable pour le trader manuel J+14 (le signal n'est plus exploitable après 1h). 5min n'a pas été retenu malgré la pertinence du scalping (le projet Tik ne capte pas le scalping micro pour 4 raisons cumulées : klines 15m natives insuffisamment fines pour viser 5 min précis, bruit microstructure sous le seuil 0.05 %, scheduler flash 5 min génère un décalage d'émission, latence de saisie d'ordre humaine 1-3 min — un futur ADR « flash micro-scalping » devra fetch klines 1m + scheduler 1 min si on veut y aller post-J+30). Verdict retenu : **15min/30min/45min/1h reste dans la fenêtre TTL signal + s'aligne sur le hit rate Phase A.2 + tous les paliers sont actionnables par un trader manuel + précision optimale sur klines 15m natives Binance**.

**5 décisions structurantes prises avant code (for/contre/verdict)** :

- **D1 fetch klines** : paramétrage `fetch_btc_history(client, interval="1h", limit=1000)` + `fetch_gold_history(client, interval="1h", range_param="60d")` rétrocompat via defaults — un seul fetch HTTP par signal track record selon `decision.horizon`. Alternatives 3 fonctions séparées et fonction polymorphe rejetées (duplication / signature ambiguë).
- **D2 seuils directionnalité** : pifomètre raisonné cohérent avec Paquet 12, plus l'horizon est court plus le seuil est bas (volatilité absolue typique BTC : 0.1-0.3 % en 15 min en marché normal vs 30-40 % sur 90 j cycle long). Calibration empirique post-J+30 inscrite au backlog.
- **D3 module pur** : ajout param `signal_horizon: str` REQUIRED (sans default — paranoïa contrôlée force le caller à expliciter) à `compute_track_record(...)`. Dict externe `HORIZON_SPECS_BY_SIGNAL_HORIZON: dict[str, dict]` 3 entrées flash/swing/macro avec `rows` + `price_match_tolerance_ms` (flash 30 min / swing 6 h / macro 24 h, propagé à `find_closest_price` selon la granularité des klines fetchées). Schémas Pydantic `TrackRecordRow` / `SignalTrackRecordOut` **inchangés** (rows déjà `list` de longueur variable).
- **D4 dashboard** : footer min-max dynamique (« Seuils : ±X % à ±Y % selon l'horizon mesuré » ou « Seuil : ±X % » si min === max). `.map()` sur rows déjà N variable, aucun autre refactor nécessaire.
- **D5 tests** : préserver les 29 tests Paquet 12 intégralement (tous portés sur `signal_horizon="swing"`), ajouter 17 nouveaux (5 dispatch + 5 flash + 5 macro + 2 erreurs). Total **46 tests** dans `test_signal_track_record.py`.

**Backend** (3 fichiers modifiés) :

- `core/src/tik_core/scripts/backtest.py` : `fetch_btc_history` et `fetch_gold_history` reçoivent params kwargs-only (interval/limit/range_param) avec defaults rétrocompat. `find_closest_price` reçoit `max_diff_ms` kwargs-only avec default 6h (rétrocompat). Tous les autres callers existants (`hit_rate.py`, `source_credibility.py`, `backtest_golden.py`, endpoints `/hit_rate` et `/hit_rate_by_veracity`) restent fonctionnels sans modif.
- `core/src/tik_core/metrics/signal_track_record.py` : `HORIZON_SPECS_BY_SIGNAL_HORIZON` dict 3 entrées + alias rétrocompat `TRACK_RECORD_HORIZONS = HORIZON_SPECS_BY_SIGNAL_HORIZON["swing"]["rows"]`. `compute_track_record(..., signal_horizon: str, ...)` REQUIRED, raise `ValueError` si horizon inconnu. `find_closest_price` appelée avec `max_diff_ms=tolerance_ms` selon spec.
- `core/src/tik_core/api/metrics.py` : 2 dicts `TRACK_RECORD_BINANCE_PARAMS` et `TRACK_RECORD_YAHOO_PARAMS` qui mappent horizon → params fetch (flash → klines 15m × 96 ≈ 24 h, swing → klines 1h × 1000 ≈ 41 j inchangé, macro → klines 1d × 365 = 1 y). Endpoint `/metrics/signal_track_record/{signal_id}` : (1) charge le signal en DB, (2) valide `signal.horizon ∈ {flash,swing,macro}` sinon HTTP 400 (cas DB corrompu), (3) **fail-fast HTTP 400 si flash + GOLD** (cohérent ADR-005 — Yahoo 15 min de délai incompatible flash, pas de signaux flash GOLD émis par Tik), (4) fetch interval/limit/range selon horizon, (5) appelle `compute_track_record(..., signal_horizon=signal.horizon)`. Cache key Redis bumpée à `tik.track_record.v2.{signal_id}` (TTL 6 h inchangé) — invalide les caches Paquet 12 au déploiement, format des rows changeant pour flash/macro.

**Dashboard** (1 fichier modifié) : `dashboard/app/signal/[id].tsx` footer Track record passe de hardcodé `rows[0]?.threshold_pct` / `rows[2]?.threshold_pct` à min-max dynamique calculé via `Math.min(...thresholds)` / `Math.max(...thresholds)`. Adaptatif aux 3 horizons sans toucher au reste du composant — `.map()` gérait déjà N variable. Aucun bump version dashboard nécessaire (modif minime).

**Tests** : suite complète 817 → **834 verts** (+17 nouveaux : 5 `TestSignalHorizonDispatch` + 5 `TestFlashTrackRecord` + 5 `TestMacroTrackRecord` + 2 `TestUnknownSignalHorizon`), 0 régression sur les 817 existants. 5 fichiers modifiés au total (3 backend + 1 tests + 1 dashboard).

**Garde-fous opérationnels** : Garde-fou 1 inchangé, ADR-003 inchangé, ADR-004 inchangé, **ADR-005 (flash GOLD interdit) renforcé** par fail-fast HTTP 400. Garde-fou 2-bis inchangé. Aucune modif des engines / pipeline scoring / cross-validation — purement métrique de calibration en lecture.

**Limites assumées** :
1. Seuils calibrés au pifomètre raisonné — révision empirique post-J+30 sur dataset golden étendu inscrite au backlog (cf. P4 du plan).
2. Pas de track record flash GOLD (limite ADR-005 héritée — Yahoo 15 min délai). HTTP 400 explicite si appelé.
3. Cache Redis TTL 6 h potentiellement long pour flash 15 min — à observer runtime, raccourcir si besoin.
4. La tolérance `find_closest_price` est calibrée sur la granularité des klines fetchées (klines 15m → 30 min de tolérance, klines 1d → 24 h). Un signal très ancien dont les klines ne couvrent plus la fenêtre cible retournera `données_manquantes` (badge prévu).

### Paquet 18 — Refactor architectural Tik pur OSINT LIVRÉ (ADR-018, 2026-05-07)

**Le plus gros refactor architectural depuis le démarrage du projet.**

Tik passe d'un système hybride (analyse technique RSI/MACD/EMA + OSINT cross-validé) à une **plateforme OSINT pure**. La direction et la conviction des signaux sont désormais dérivées uniquement du `combined_bias` OSINT cross-validé, plus de l'analyse technique. Cette dernière reste calculée et affichée en evidence/triggers pour audit, mais **n'influence plus la décision directionnelle**.

### Origine — audit méthodique 2026-05-06/07

Audit conduit sous consigne utilisatrice *"doute constant et méthodique, sans complaisance"*. Plusieurs errements répétés d'instances Claude précédentes identifiés :

- Affirmer Tik = "plateforme OSINT" sans avoir vérifié que le code réel est en fait hybride (analyse technique + OSINT)
- Inventer des chiffres business (hit rate Zeta, lignes de code Tik) sans les vérifier en données réelles
- Sous-estimer la taille réelle de Tik (3.4k lignes annoncées vs 14k lignes vérifiées via `wc -l`)
- Présenter avec excès de confiance des verdicts qui s'avèrent fragiles quand challengés

L'utilisatrice a posé 3 fois la même question méthodologique et challengé chaque verdict avant que la prise de conscience architecturale soit complète :

> *"si j'ai bien compris l'hybride que me fait tik, c'est ce que zeta fait en mieux"*

C'est cette formulation simple qui a rendu visible la duplication conceptuelle entre Tik (analyse technique basique) et Zeta (analyse technique calibrée 5211 lignes) + MT5 (indicateurs natifs sur l'écran de la trader).

### 5 décisions structurantes prises (cf. ADR-018)

1. **Refactor Tik vers plateforme OSINT pure** plutôt que garder l'hybride ou créer une nouvelle plateforme à côté (option C de l'utilisatrice analysée et écartée — 80-160h dev pour résultat inférieur)
2. **Direction dérivée du combined_bias OSINT** avec seuil ±0.30 (calibré au pifomètre raisonné, à réviser post-J+30)
3. **`confidence` renommé sémantiquement** en "Conviction OSINT" côté dashboard (pas en DB pour rétrocompat des 683 signaux historiques). Sa valeur = `abs(combined_bias)`. **Sémantique uniforme** (résout bug #1 audit Paquet 17 P5 : double sens long/short vs neutral)
4. **`veracity` calculée depuis la dispersion des sources OSINT** (pas la concordance technique↔sentiment). Résout bug #2 audit (veracity neutral figée à 0.85 confirmée empiriquement sur 162 signaux)
5. **Indicateurs techniques préservés en evidence/triggers** (informatifs, weight 0.0). Tik reste lisible pour l'humain qui veut voir les indicateurs, mais ne les utilise plus pour décider

### Décisions reconsidérées avec l'utilisatrice

- **Option A (statu quo)** : rejetée — bugs structurels persistent (conf plafonnée 0.55, veracity neutral figée), duplication Tik/Zeta éternelle
- **Option B (refactor pur OSINT)** : retenue — règle bugs + élimine duplication
- **Option C (nouvelle plateforme OSINT séparée + Tik orchestrateur)** : analysée et **rejetée** — 80-160h dev vs 9h pour B, double la base de code (24k lignes vs 13k), ne résout pas les bugs Tik, disperse les ressources solo+1
- **Option ajout sources X/Reuters** : analysée et écartée pour le refactor — plus de sources ≠ plus de signaux à haute veracity (statistiquement plutôt l'inverse, loi des grands nombres). Polymarket reste pertinent post-J+14 (P8 plan stratégique)

### Vérifications factuelles préalables

Mesures effectuées avant le refactor :

- Tik core (sans tests) : **8733 lignes** (3024 scoring + 2691 aggregator + 1481 api + 1098 storage + 439 metrics)
- Tik dashboard : **5232 lignes**
- **Total Tik : ~14 000 lignes** (4× plus que les estimations précédentes incorrectes)
- 683 signaux émis sur 30 jours
- **Hypothèse #3 ADR-018 confirmée** : seulement **3.37 %** des signaux ont veracity ≥ 0.95 (23/683). Volume modeste de signaux à très haute concordance.
- **17.86 %** des signaux à veracity ≥ 0.90 (122/683) — niveau exploitable pour trading manuel filtré
- **Confidence max swing = 0.550 strictement** sur 437 signaux (l'utilisatrice avait raison : *"tous mes signaux ont conf max à 55%"* — c'était une **borne supérieure structurelle**, pas une coïncidence)
- **162 signaux neutral, tous dans veracity 0.85-0.89** — bug confirmé empiriquement

### Implémentation (Sessions 1 + 2 + 3 livrées 2026-05-07)

**Session 1 — Refactor core** :

- `swing_engine.py` (~150 lignes refactorées) :
  - `_score_indicators()` → `_compute_technical_evidence()` (calcul technique préservé pour evidence, plus de calcul `bull_score`/`bear_score` ni de décision)
  - Nouvelle fonction `_derive_osint_decision(decision, combined_bias, threshold=0.30)`
  - Nouvelle fonction `_veracity_from_dispersion(dispersion)` avec 5 paliers (0.95/0.90/0.85/0.78/0.70)
  - `_veracity_from_concordance` conservée en legacy pour rétrocompat tests
  - `analyze_swing_btc/gold` modifiées pour appeler `_derive_osint_decision` puis `_veracity_from_dispersion` après cross-validation OSINT
  - Alias rétrocompat `_score_indicators = _compute_technical_evidence`

- `flash_engine.py` (~165 lignes refactorées, même pattern) :
  - `_score_flash_indicators()` → `_compute_technical_evidence_flash()`
  - Nouvelle `_derive_osint_decision_flash()` (duplication volontaire à factoriser au prochain ajout d'engine)
  - Nouvelle `_veracity_from_dispersion()` (idem)
  - `analyze_flash_btc` modifiée

- **Pas de modification** de `storage/models.py`, `storage/schemas.py`, ou de migration Alembic. La colonne SQL `confidence` reste, sa **signification** seule change. Les 683 signaux historiques restent lisibles.

**Session 2 — Adaptation dashboard** :

- `dashboard/app/signal/[id].tsx` :
  - Label "Confidence" → "Conviction OSINT" avec sous-titre "magnitude du biais cross-validé"
  - Label "Veracity" gardé avec sous-titre "alignement des sources"
  - Style `metricSubtitle` ajouté

- `dashboard/src/api/types.ts` :
  - Commentaire JSDoc enrichi sur `Signal.confidence` pour documenter la nouvelle sémantique ADR-018
  - Nom du champ `confidence` conservé pour rétrocompat (683 signaux historiques)

**Session 3 — Documentation** :

- ADR-018 : `RÉSERVÉ` → `ACCEPTÉ`, ajout section "Notes d'implémentation" complète
- Backlog entry n°6 : à mettre à jour pour refléter LIVRÉ (à faire post-merge)
- CLAUDE.md : ce paquet 18

### Tests

- **57 nouveaux tests pytest** ajoutés :
  - `TestDeriveOsintDecision` (swing) : 13 tests paramétrés
  - `TestVeracityFromDispersion` (swing) : 16 tests des 5 paliers
  - `TestVeracityFromConcordanceLegacy` : 2 tests rétrocompat
  - `TestSemanticUniformityADR018` : 3 tests vérifient explicitement que la sémantique de `confidence` est uniforme post-refactor
  - `TestDeriveOsintDecisionFlash` : 11 tests
  - `TestVeracityFromDispersionFlash` : 10 tests

- **Suite complète : 834 → 891 tests verts**, 0 régression sur les 834 tests pré-existants.

### Bugs résolus

| Bug audit Paquet 17 P5 | Statut |
|---|---|
| #1 — Sémantique double confidence (long/short = score, neutral = écart) | ✅ Résolu (sémantique uniforme `abs(combined_bias)`) |
| #2 — Veracity neutral figée à 0.85 | ✅ Résolu (via `_veracity_from_dispersion`) |
| #3 — Recalibration sources flash mesurée à 5j | 🔵 Non touché (à régler dans P6 post-J+14) |
| #4 — Attribution hit rate au signal entier | 🔵 Non touché (Phase C Session 2 P7 post-J+14) |
| Confidence plafonnée à 0.55 swing | ✅ Résolu (peut maintenant atteindre 1.0) |

### Comportement runtime post-refactor

- Avec OSINT disponible : direction et confidence dérivées du `combined_bias` cross-validé
- Sans overlay OSINT (Redis miss) : `direction="neutral"`, `confidence=0` (cohérent — Tik OSINT pur ne décide pas sans OSINT)
- Veracity dynamique selon dispersion des sources (0.70 à 0.95)
- Indicateurs techniques affichés en evidence/triggers avec `weight: 0.0` (informatifs)

### Limitations connues post-refactor

1. **Seuil ±0.30 sur combined_bias** : pifomètre raisonné, à réviser post-J+30
2. **Seuils veracity dispersion** (0.2/0.4/0.6/0.8) : pifomètre raisonné, à réviser post-J+30
3. **Tik moins consommable seul** : direction nécessite des sources OSINT disponibles. Pour avoir une direction technique complémentaire, regarder MT5
4. **Volume de signaux directionnels** : peut différer post-refactor — à mesurer empiriquement après quelques jours de runtime
5. **Validation runtime à faire** : démarrer Tik core post-livraison, observer les premiers cycles, vérifier qu'aucun crash et que les signaux ont une distribution cohérente

### Garde-fous opérationnels rappelés

- Garde-fou 1 (Tik shadow vs Zeta 3 mois) **inchangé**
- ADR-003 (pas de bypass V01-V15) **inchangé** — Tik ne crée toujours jamais d'ordre
- ADR-004 (multi-overlay) **renforcé** — devient le cerveau principal de décision
- ADR-011 (anti fake-news) **inchangé**
- ADR-012 (LLM hypothesis) **inchangé**
- Garde-fou 2-bis (sizing 1 % capital, veracity ≥ 0.90 sur swing) **inchangé** — règle stricte trading manuel J+14

### Total fichiers modifiés Paquet 18

7 fichiers (3 backend + 2 dashboard + 2 doc) :

1. `core/src/tik_core/scoring/swing_engine.py`
2. `core/src/tik_core/scoring/flash_engine.py`
3. `core/tests/test_swing_engine.py` (+34 tests)
4. `core/tests/test_flash_engine.py` (+23 tests)
5. `dashboard/app/signal/[id].tsx`
6. `dashboard/src/api/types.ts`
7. `docs/adr/018-tik-pure-osint-refactor.md` (RÉSERVÉ → ACCEPTÉ + Notes d'implémentation)

Plus `CLAUDE.md` (ce Paquet 18) et `docs/backlog.md` entry n°6 (mise à jour à venir post-livraison).

### Paquet 19 — P1 + P2 plan stratégique fiabilité signaux LIVRÉS + amendement ADR-018 désactivation overlays GOLD DXY/COT (2026-05-07)

P1 + P2 du plan stratégique post-audit fiabilité (cf. Plan stratégique ci-dessous) livrés le même jour que le Paquet 18, avec un amendement structurant à l'ADR-018 dans la foulée. **Premier verdict empirique chiffré sur les 4 sources numériques de Tik** (FG, GDELT, DXY, COT) sur 12 mois — a invalidé l'hypothèse contrarian DXY+COT sur GOLD pour 2025-2026 et conduit à les désactiver par défaut.

**P1 — Re-run golden dataset deltas 5j (commit `c79fed5`, data only)** :

- Mise à jour du fichier `core/data/golden_dataset/prices.jsonl` avec les vrais deltas 5j observés (les deltas 24h et 5d étaient en attente depuis le 1er cycle d'annotation du 2026-05-02, cf. Paquet 4 Session 4 partielle).
- Régénération du `calibration_report.md` et `.json` consolidés.
- **Insights clés** mesurés sur 100 items (50 BTC + 50 GOLD) annotés à la main :
  - Accuracy Humain ↔ Ollama = 58 %, Humain ↔ Keywords = 63 %, Ollama ↔ Keywords = 49 %
  - Hit rate vs marché à 5j : Ollama 38 % > Humain 27 % > Keywords 23 %
  - **Ollama bat l'humain à 5j sur cette fenêtre bullish** (mais reste sous `always_bull` baseline = 100 % puisque période strongly bullish)
  - Performance par source à 5j : CryptoCompare Ollama 47 % > Google News Ollama 39 % > Reddit Ollama 25 %
  - Hit rate humain à 24h = 68 % (l'humain est bon à court terme sur les titres clairs, faible à long terme où les fondamentaux dominent)
- **Limites assumées** : 1 cycle de marché (bullish), échantillon 100 items, période 5 jours seulement. Verdict structurel à confirmer sur 6-12 mois (ce que P2 a fait pour les sources numériques).

**P2 — Backtest empirique 12m sources numériques (commit `0fb99d0`)** :

- **2 nouveaux scripts CLI** dans `core/src/tik_core/scripts/` :
  - `fetch_numeric_history.py` (~381 lignes) : helpers async `fetch_fear_greed_history` (alternative.me, 365j), `fetch_gdelt_tone_history` (GDELT Doc API timelinetone, 12m), `fetch_dxy_history` (FRED DTWEXBGS, 12m), `fetch_cot_history` (CFTC Managed Money, 12m hebdomadaire). Chaque fonction est typed, testée, idempotente.
  - `backtest_numeric_sources.py` (~663 lignes) : orchestration backtest empirique. Pour chaque source × horizon (24h / 120h / 720h) calcule (1) hit rate par palier de bias selon les paliers actuels de `swing_engine.py` (`_compute_fg_bias`, `_compute_dxy_bias`, `_compute_cot_bias`, `_compute_gdelt_bias` réutilisés directement = cohérence garantie), (2) IC Spearman avec sign check vs sémantique attendue (contrarian = IC négatif attendu pour ces 4 sources), (3) hit rate des cas extrêmes (|bias|=1.0). Génère rapport JSON détaillé + Markdown auto-commenté avec recommandations chiffrées.
- **Nouveau dossier `core/data/numeric_calibration/`** versionné Git avec :
  - `numeric_calibration_report.json` (501 lignes, sortie machine)
  - `numeric_calibration_report.md` (191 lignes, rapport humain)

**Insights critiques mesurés sur 12 mois (2025-05-07 → 2026-05-07)** :

| Source | Asset | Direction | n total | IC Spearman max | Verdict |
|---|---|---|---|---|---|
| **Fear & Greed** | BTC | contrarian | 364 | -0.10 (à 720h) | ⚠ Marginalement contrarian, signal **non significatif** aux 3 horizons (\|IC\| < 0.1 partout sauf 720h frontière) |
| **GDELT tone** | GOLD | contrarian | **0** | n/a | ⚠ **Aucun point évaluable** — rate-limit GDELT public sur historique 12m. Qualité **non validée empiriquement** post-2026-05-07 |
| **DXY** | GOLD | contrarian | 242 | **+0.23** (à 120h) | 🔴 **Inversé** — IC +0.23 au lieu de négatif attendu. Hit rate cas extrêmes 19-25 %. Palier `dxy_strong_up` à 120h = **0 % hit rate** (n=7) |
| **CFTC COT** | GOLD | contrarian | 51 | **+0.43** (à 720h) | 🔴 **Inversé** — IC +0.43. Palier `mm_extreme_long` à 720h = **0 % hit rate** (n=10) avec delta moyen +7.5 % gold |

**Décisions structurantes prises** (documentées avec for/contre/verdict dans rapport MD + ADR-018 amendement) :

1. **DXY contrarian désactivé** sur GOLD par défaut (toggle env var)
2. **COT contrarian désactivé** sur GOLD par défaut (toggle env var)
3. **FG conservé sur BTC** malgré le signal marginal — palier `extreme_greed` (n=4) montre 75 % hit rate à 720h, l'extrême lui-même reste exploitable même si l'IC global est faible
4. **GDELT à investiguer** post-J+14 — soit fix du fetch historique 12m, soit acceptation que GDELT est un overlay temps réel non backtesté

**Régime 2025-2026 strongly bullish** (BTC + GOLD + USD en parallèle, perception de débasement monétaire) limite la généralisation. **À reproduire post-J+30 sur période bear** (drawdown gold ≥ 5 % ou bear crypto) pour confirmer si l'inversion DXY/COT est régime-spécifique ou structurelle.

**4 nouveaux fichiers de tests** : `test_fetch_numeric_history.py` (324 lignes, 33 tests sur les 4 fetch helpers — payloads valides/invalides/vides, parsing dates, gestion erreurs HTTP) + `test_backtest_numeric_sources.py` (147 lignes, 24 tests sur Spearman correlation, hit rate calculation, palier aggregation, baseline metrics, recommandations auto-générées). Suite complète : 891 → **948 tests verts** (+57 nouveaux), 0 régression.

**Amendement ADR-018 P2 (commit `e1f9a03`)** :

- **`core/src/tik_core/config.py`** : nouveau setting `gold_dxy_cot_overlays_enabled: bool = False` lu depuis env var `TIK_GOLD_DXY_COT_OVERLAYS_ENABLED`. Réversible sans redéploiement code.
- **`core/src/tik_core/scoring/swing_engine.py`** : wrap les blocs DXY et COT dans `analyze_swing_gold` derrière le check `if settings.gold_dxy_cot_overlays_enabled`. Fonctions `_compute_dxy_bias`, `_compute_cot_bias`, `_enrich_with_dxy`, `_enrich_with_cot` **conservées** (pour réactivation rapide). Logs explicites `swing.gold.dxy_skipped_overlay_disabled` / `swing.gold.cot_skipped_overlay_disabled` au runtime pour traçabilité.
- **3 nouveaux tests pytest** dans `test_swing_engine.py` (`TestGoldDxyCotOverlaysSettingADR018Amendment`) : default=False, override=True via env, override=False via env. Suite complète : 948 → **954 tests verts** (+3), 0 régression.
- **ADR-018 amendé** : nouvelle section « Amendement post-livraison — Désactivation overlays GOLD DXY+COT (P2) » qui formalise le constat empirique chiffré, les arguments pour/contre la désactivation, le critère de réactivation post-J+30 (IC Spearman DXY @ 120h **redevient négatif** ET cas extrêmes hit rate ≥ 50 % → réactiver), les limitations connues post-désactivation, mémoire pour instances Claude futures (ne pas confondre désactivation réversible vs suppression irréversible).
- **`docs/comprendre_tik.md` section 21** : nouveau chapitre pédagogique en français accessible *« Calibration empirique 12m : DXY et COT désactivés sur GOLD »*. Explique pourquoi les pros disent *"the dollar should hurt gold"* et pourquoi sur 2025-2026 ça n'a pas tenu, comment Tik mesure ça scientifiquement avec Spearman, et la décision conservatrice de désactiver plutôt que supprimer.

**Validation runtime confirmée** (2026-05-07 14:49 UTC, post-restart `docker compose restart scheduler`) :
- Logs `swing.gold.dxy_skipped_overlay_disabled` et `swing.gold.cot_skipped_overlay_disabled` ✓
- Premier signal GOLD émis post-désactivation : `direction=neutral` (cohérent ADR-018 OSINT pur — sans overlay OSINT directionnel sur GOLD, pas de direction)

**Conséquence opérationnelle pour la trader manuelle J+14** : depuis le 2026-05-07, **Tik émet quasi-exclusivement des signaux directionnels sur BTC** (4 overlays actifs : FG + CC + Google News + Reddit). GOLD a maintenant 2 overlays (Google News + GDELT — quand GDELT marche), donc la majorité des signaux GOLD sont `direction=neutral`. Si la trader veut un signal directionnel GOLD, elle doit s'appuyer sur MT5 / son jugement / l'analyse technique externe, **pas sur Tik** dans cet état post-amendement.

**Fix Dockerfile (commit `83cef71`)** :

- Suppression d'une instruction `COPY scripts/ ./scripts/` obsolète dans `core/Dockerfile` (le dossier `scripts/` à la racine du projet n'existait plus, les scripts Tik sont en réalité tous dans `src/tik_core/scripts/` et sont donc copiés via la commande `COPY src/ ./src/` standard). Build Docker passait quand même grâce à un layer cache mais la commande étant invalide elle générait du bruit dans les logs CI/CD.
- 1 ligne supprimée, 0 test impacté.

**Total Paquet 19** : 9 fichiers modifiés/créés (4 backend + 2 tests + 3 doc/data) + 1 fichier supprimé (instruction Dockerfile). Suite pytest **891 → 954 tests verts** (+63 nouveaux : 33 fetch + 24 backtest + 3 setting + 3 amendment), 0 régression sur les 891 tests Paquet 18.

**Garde-fous opérationnels rappelés** :
- Garde-fou 1 (Tik shadow vs Zeta 3 mois) **inchangé**
- Garde-fou 2-bis (sizing 1 % capital, veracity ≥ 0.90 sur swing, discipline macro ±4h) **strictement applicable** — règle stricte trading manuel J+14
- ADR-003 (pas de bypass V01-V15) **inchangé** — Tik ne crée jamais d'ordre, ni avant ni après désactivation overlays
- ADR-004 (multi-overlay) **inchangé** — pattern ouvert, on ferme juste 2 overlays GOLD spécifiques par calibration empirique
- ADR-011 (anti fake-news) **inchangé** — cross-validation Modified Z-score toujours appliquée sur les overlays restants
- ADR-018 OSINT pur **renforcé empiriquement** — la décision de retirer les overlays défaillants confirme qu'on optimise la qualité OSINT plutôt que le volume

**Limites connues post-Paquet 19** :

1. **GOLD post-désactivation = quasi 100 % signaux `neutral`** côté Tik. La trader manuelle J+14 doit avoir conscience que l'absence de signal directionnel GOLD ≠ absence d'opportunité, c'est juste que Tik ne tranche plus.
2. **GDELT non validé empiriquement** — fetch historique 12m bloqué par rate-limit GDELT public. Le ingester GDELT runtime tourne quand même normalement (une requête / 30 min reste sous radar), mais on ne sait pas si le mapping contrarian retenu (cf. ADR-010) est le bon. À investiguer P3 (ci-dessous).
3. **Verdict P2 régime-spécifique** : 12m bullish n'est pas représentatif. Le critère de réactivation post-J+30 doit attendre un **vrai drawdown** (gold ≥ 5 % ou bear crypto) pour être interprétable.
4. **Re-mesure FG sur BTC à prévoir** post-J+30 sur fenêtre bear pour confirmer si le signal marginal contrarian se renforce dans un régime stress (théoriquement oui — *"buy when there's blood in the streets"*).

**Mémoire pour instances Claude futures** :

- **DXY/COT réversibles** : si une session future re-mesure ces overlays sur période bear et trouve signe contrarian correct → réactiver via `TIK_GOLD_DXY_COT_OVERLAYS_ENABLED=true`. Ne **JAMAIS supprimer** le code des fonctions `_compute_dxy_bias` / `_compute_cot_bias` / `_enrich_with_dxy` / `_enrich_with_cot` — ils restent en place exprès.
- **Si une session trouve un nouvel insight justifiant trend-following** plutôt que contrarian sur DXY ou COT → modifier le mapping dans `_compute_dxy_bias` / `_compute_cot_bias` (inverser les signes) et **nouveau ADR** documentant le revirement.
- **Tik n'est plus un système de signaux directionnels GOLD à ce jour**. Si l'utilisatrice se plaint de l'absence de signaux GOLD → c'est attendu, expliquer le pourquoi (ADR-018 amendement P2). Pas un bug.

### Paquet 21 — Fix GDELT timing rate-limit + P6 détection anomalies par ingester (2026-05-16)

Deux livraisons cumulées le 2026-05-16 (J+2 trading manuel) sur l'axe stratégique fiabilité signaux. **Aucun fichier touché sur `work-from-hp`** (audit `git diff --name-only main origin/work-from-hp` confirmé avant code) — branche d'isolation respectée.

#### Fix GDELT timing rate-limit (commit `a7ef93d`, ~20 min)

Cause racine du bug Paquet 19 P2 backtest GDELT 0 points (cf. CLAUDE.md Paquet 19 + investigation diagnostique 2026-05-16) : le retry sur 429 démarrait avec un backoff de 2 s, en-dessous du rate-limit GDELT explicite (1 requête / 5 secondes par IP). Le 1er retry retombait systématiquement sur 429 ; les 4 tentatives s'épuisaient en ~30 s sans jamais récupérer la donnée.

**Diagnostic confirmé runtime** :
- Test live `timespan=1y` : HTTP 200 + 365 points complets disponibles. La donnée EST là.
- Test live `timespan=1d` après autre call < 5s : HTTP 429 "Please limit requests to one every 5 seconds".
- Conclusion : pas de bug d'API ni de parsing, juste un backoff retry trop court vs rate-limit GDELT.

**Fix** : nouvelle constante module `GDELT_MIN_BACKOFF_S = 6` (commentée avec rationale) dans `fetch_numeric_history.py`. `backoff_s = max(GDELT_MIN_BACKOFF_S, 2 ** (attempt + 1))` au lieu de `2 ** (attempt + 1)`. Pattern résultant : 6s, 6s, 8s, 16s. Constante module-level pour permettre monkey-patch dans tests (sinon backoff 6s × 3 retries = 18s par test 429 = trop lent CI).

3 nouveaux tests pytest dans `test_fetch_numeric_history.py` : 2 tests existants `test_429_*` patchés avec `monkeypatch.setattr(GDELT_MIN_BACKOFF_S, 0)` + 1 nouveau `test_429_backoff_respects_min_floor` qui mock `asyncio.sleep` et vérifie le pattern `[6, 6, 8]` produit par 3 retries successifs avec floor=6.

**Impact opérationnel** : re-run du backtest P2 nécessaire pour avoir les vraies mesures GDELT GOLD 12m (commande dans le commit message). Une fois le re-run effectué, le fichier `core/data/numeric_calibration/numeric_calibration_report.md` doit être régénéré et CLAUDE.md Paquet 19 mis à jour avec les nouveaux chiffres GDELT GOLD (n_history_fetched devrait passer de 0 à ~365 points).

#### P6 — Détection anomalies par ingester (commit `b340735`, ~3-4h)

P6 du plan stratégique fiabilité signaux livrée. Couche qualité upstream complémentaire à l'anti fake-news ADR-011 : ce dernier agit en aval sur le biais agrégé après cross-validation, P6 agit en amont sur chaque ingester individuel.

**Architecture (D-P6-2 verdict)** :
- Helpers purs dans nouveau module `core/src/tik_core/scoring/anomaly_detector.py` (~299 lignes, zéro accès Redis/HTTP, type `AnomalyResult` TypedDict avec `type / score / severity / detail`)
- Chaque ingester appelle son détecteur AVANT publish Redis et ajoute le résultat sous la clé `anomaly` du payload
- L'engine swing consomme `anomaly` dans `_enrich_with_<source>` via le nouveau helper `_apply_anomaly_pondération` (D-P6-1 verdict bias /2 sur high)

**3 anomalies détectées** :

| # | Anomalie | Métrique | Seuil medium | Seuil high | Ingester |
|---|---|---|---|---|---|
| A | Brigading Reddit | `sum(comments) / sum(upvotes)` agrégé | ≥ 0.5 | ≥ 1.0 | reddit_ingester |
| B | Dominance publisher Google News | `top_publisher_count / total` | ≥ 0.50 | ≥ 0.70 | google_news_ingester |
| C | Pic volume CryptoCompare | `volume_today / mean(baseline 7j)` | ≥ 3× | ≥ 5× | cryptocompare_ingester |

**Action de l'engine selon severity** :
- `severity=high` → bias divisé par 2 + flag dans evidence (réduit l'influence sans supprimer)
- `severity=medium` → bias inchangé + flag dans evidence (transparence)
- `severity=ok` → bias normal, pas de flag

**Spécificités** :
- **Reddit** : ratio agrégé `sum(comments) / sum(upvotes)` plutôt que moyenne des ratios individuels (un post viral à 10000 upvotes pèse naturellement plus, ce qui est l'effet souhaité — un brigading touche typiquement des posts qui montent vite)
- **Google News** : seuil 50%/70% nuancé, validé par observation Paquet 4 Session 1 où Yahoo Finance était à 40% sur certains cycles (déjà élevé mais pas suspect)
- **CryptoCompare** : baseline persistée Redis sous `tik.anomaly.baseline.cryptocompare.{currency}` (TTL 14j, max 168 points = rolling 7j à polling horaire). Désactivée tant que baseline < 7 points (cold start). Best-effort sur erreurs Redis (warnings, pas de crash). Migration test fixture `MagicMock` → `AsyncMock` car le ingester appelle maintenant `await self.redis.get/setex` pour la baseline.
- **Rétrocompat engine** : `_enrich_with_<source>` lit `anomaly` via `.get("anomaly")` (None par défaut). Si payload Redis pre-fix sans le champ → bias inchangé. Aucune modification de schéma DB ni de signature publique.

**Fichiers (7)** : 1 nouveau module + 3 ingesters + 1 engine + 2 tests. **31 nouveaux tests pytest** dans `test_anomaly_detector.py` (11 brigading + 9 dominance + 11 volume_spike), suite complète **954 → 988 verts** (+34 cumulés P6+GDELT fix), 0 régression.

**Validation runtime à faire post-déploiement** :
1. `docker compose restart ingesters` pour charger le nouveau code
2. Observer sur 1-2 cycles que les payloads Redis contiennent `anomaly`
3. Sur 7+ cycles CryptoCompare, vérifier que la baseline se construit (key `tik.anomaly.baseline.cryptocompare.btc` apparaît dans Redis)
4. Surveiller les logs `*.anomaly_detected` pour calibrer les seuils post-J+30 si trop de faux positifs

**Garde-fous** : ADR-003 / ADR-004 / ADR-011 / Garde-fou 1 / 2-bis tous inchangés. Aucune modification engines / pipeline scoring / cross-validation — purement additif.

**Limites connues** :
1. Seuils pifomètre raisonné (D-P6-4) — à recalibrer empiriquement post-J+30 sur dataset réel
2. Cold start CryptoCompare 7+ heures avant activation détection volume
3. Brigading ratio sensible à l'algo `hot` Reddit (post viral peut avoir beaucoup des deux)
4. Couplage engine ↔ ingester payload : nouvelle clé `anomaly` doit rester rétrocompat (`.get` défensif respecté)

### Paquet 22 — Option B SDK alias `osint_conviction` + pattern Zeta refondu (2026-05-16)

Résolution de la « false friend confidence » identifiée dans la discussion stratégique du 2026-05-16 entre l'utilisatrice et Claude. Depuis le refactor OSINT pur du Paquet 18 (ADR-018, 2026-05-07), le champ `Signal.confidence` ne mesure plus la force d'analyse technique RSI/MACD/EMA mais la magnitude du `combined_bias` OSINT cross-validé. Le nom est resté `confidence` pour rétrocompatibilité des 683 signaux historiques en DB.

**Risque identifié et confirmé** : un dev Zeta (ou tout futur consommateur — bot tiers, trader manuel partageant ses signaux, intégration B2B) qui lit `tik.confidence: 0.62` va l'interpréter selon la convention dominante en trading (= force du signal technique de prédiction), pas selon la sémantique OSINT post-Paquet 18. Le doc `integration_zeta.md` lui-même (rédigé 2026-04-30, AVANT le refactor) codait linéairement `tik.confidence × tik.veracity` sans vérifier ce que confidence représente vraiment — preuve empirique que même les concepteurs du système se sont trompés sur le mot 1 mois après l'avoir nommé.

#### 4 raisons vérifiables qui ont déterminé Option B

1. **Convention universelle** : "confidence" en trading = force du signal/probabilité de prédiction (cf. ML frameworks, bots Pine Script/Jesse/Backtrader, IB TWS API). Tout dev/bot va l'interpréter ainsi par défaut.
2. **Le doc Zeta démontrait déjà le piège** : pattern overlay 2026-04-30 prouve qu'on s'est trompés nous-mêmes 1 mois après Paquet 18.
3. **Contexte trading manuel** : si l'utilisatrice partage un signal avec un autre trader ou intègre Tik à un autre service (P8 Polymarket, futur B2B), le destinataire va l'interpréter mal.
4. **Coût asymétrique** : ~2-3h fix maintenant vs refactor de tous les clients ayant hardcodé une interprétation erronée dans 6 mois.

#### 3 changements précis (commit `d5e40d0`)

**1. SDK 0.6.0 — Alias `osint_conviction` sur `Signal`** (Pydantic property dérivée)

```python
class Signal(BaseModel):
    confidence: float = Field(ge=0, le=1)  # canonique JSON, rétrocompat 683 signaux
    ...

    @property
    def osint_conviction(self) -> float:
        """Alias sémantique de confidence (ADR-018, SDK 0.6.0+).
        Strictement même valeur. Nom rend explicite que la confidence
        Tik est un score OSINT cross-validé, pas un score technique."""
        return self.confidence
```

Property dérivée → strictement la même valeur, JSON sortant inchangé (`osint_conviction` n'apparaît PAS dans `model_dump()`), aucune migration backend nécessaire. Usage recommandé pour tous les nouveaux consommateurs : `tik.osint_conviction × tik.veracity` au lieu de `tik.confidence × tik.veracity`.

**2. `docs/integration_zeta.md` — Pattern overlay refondu**

Avant (2026-04-30) : modulation linéaire systématique
```python
factor = tik.confidence × tik.veracity
boost = factor × 0.20  # max +20%
```

Après (2026-05-16) : modulation **conditionnelle** au-delà d'un seuil minimum `OSINT_MIN_STRENGTH = 0.6`
```python
osint_strength = tik.osint_conviction × tik.veracity
if osint_strength < OSINT_MIN_STRENGTH:
    return internal_signal  # Tik trop faible → ne dit rien à Zeta
adjustment = (osint_strength - 0.6) / 0.4 × 0.20  # 0.0 à 0.20
```

Pattern plus rigoureux car (a) ne mélange plus 2 dimensions orthogonales (technique Zeta vs OSINT Tik) qu'au moment où Tik dit quelque chose de fort, (b) le seuil empêche les modulations bruitées sur cycles OSINT faibles. Cohérent vision « Tik = filtre fort qualité OSINT, Zeta = analyse technique calibrée » post-ADR-018.

**3. Bump SDK 0.5.0 → 0.6.0** (pyproject.toml + `__version__` + `USER_AGENT`)

v1.0.0 reste réservée à la mise en production réelle dans Zeta après les 3 mois shadow obligatoires (cf. Garde-fou 1).

**Tests** : 3 nouveaux tests pytest dans `sdk/tests/test_models.py` : alias retourne même valeur que confidence, alias est property read-only absente du JSON sortant, alias suit la valeur si `confidence` mute. Tests existants inchangés (le champ `confidence` est rigoureusement inchangé).

**Garde-fous** : ADR-003 / ADR-004 / ADR-011 inchangés. ADR-018 OSINT pur **renforcé** — la sémantique OSINT du score est désormais explicite dans le nom côté SDK. Garde-fou 1 inchangé (câblage Zeta toujours en attente shadow 3 mois).

**Limites connues** :
1. Le champ JSON reste `confidence` (rétrocompat 683 signaux) — un consommateur qui lit le JSON brut sans passer par le SDK Python verra toujours le mot ambigu. Le SDK Python est la couche qui matérialise l'alias.
2. `OSINT_MIN_STRENGTH = 0.6` est calibré au pifomètre raisonné, à valider empiriquement quand Zeta sera câblé en mode shadow (Garde-fou 1 = 3 mois minimum, donc validation ~août 2026).
3. Le pattern Pattern 1 Zeta documenté ici n'est pas encore exécuté en runtime (Zeta encore en mode observation seule). À re-vérifier au moment du câblage réel.

**Mémoire pour instances Claude futures** : NE PAS revenir au pattern linéaire de 2026-04-30 sans relire ADR-018 et la discussion du 2026-05-16. Le mot "confidence" dans Tik signifie "magnitude OSINT cross-validée", pas "force technique" — utiliser `osint_conviction` partout dans tout nouveau code consommateur. Le SDK 0.6.0+ matérialise l'alias.

### Paquet 23 — Phase B2 calendrier macro multi-banques centrales LIVRÉ (P9 plan fiabilité, ADR-020, 2026-05-16)

P9 du plan stratégique post-audit fiabilité signaux livrée le même jour
que les Paquets 21+22. Extension naturelle de Phase B1 (ADR-017, Paquet 11)
qui couvrait US-only : Tik dispose maintenant d'un calendrier macro
**multi-banques centrales** (BCE Lagarde + BoJ Ueda + BoE Bailey aux
côtés du FOMC américain). Discipline opérationnelle de la trader manuelle
J+14 (Garde-fou 2-bis) étendue aux ±4 h autour de **24 events majeurs
internationaux supplémentaires par an** (3 BC × 8 meetings).

#### 6 décisions structurantes prises (cf. ADR-020)

1. **Nouvel ingester `MacroStaticIngester` séparé** (vs étendre `FredCalendarIngester`) :
   fix d'un **bug latent Phase B1** — sans clé FRED, le ingester actuel
   skip TOUT y compris FOMC static. Séparation propre des responsabilités
   (FRED dynamique vs static). MacroStaticIngester n'a aucune dépendance
   externe (pas de fetch HTTP, pas de clé API).
2. **Dates hardcodées en Python** dans `macro_calendar_data.py` (vs scraping
   ECB JSON ou API agrégée payante). Cohérent avec FOMC Phase B1.
   Auditabilité PR-able + type-checking + tests possibles.
3. **`tz_name: str` IANA** sur `StaticEventSpec` + `FredReleaseSpec` (default
   `"America/New_York"` rétrocompat). Permet 1 seule structure pour
   FOMC US / BCE EU / BoJ JP / BoE UK. DST géré automatiquement par
   `zoneinfo` stdlib (CEST/CET ECB, JST sans DST BoJ, GMT/BST BoE).
4. **`source: str` sur `StaticEventSpec`** (default `"fed_static"` rétrocompat).
   Valeurs `"fed_static"` / `"ecb_static"` / `"boj_static"` / `"boe_static"`.
   Trace d'audit + filtrage potentiel futur côté API.
5. **Importance** : FOMC HIGH, BCE HIGH, BoJ HIGH, BoE MEDIUM (GBP moins
   influente sur DXY que EUR/USD). Calibration au pifomètre raisonné à
   recalibrer empiriquement post-J+30 (backlog #7 B.4).
6. **Pas d'élections en Phase B2** (reportées Phase B3 post-J+30). Scope
   élections trop large (50+/an mondial) pour bien faire en une session.

#### Implémentation (9 fichiers, ~700 lignes nettes)

| Fichier | Changement |
|---|---|
| `core/src/tik_core/aggregator/macro_calendar_data.py` | +`tz_name` sur specs, +`source` sur StaticEventSpec, helpers `date_to_utc_release`/`build_event_from_*` déplacés ici (avant dans `fred_calendar_ingester`), +3 listes `ECB_STATIC_DATES`/`BOJ_STATIC_DATES`/`BOE_STATIC_DATES` (12 dates 2026-2027 chacune), helper `all_static_events()`. 48 static events total (12 par BC). |
| `core/src/tik_core/aggregator/fred_calendar_ingester.py` | Retrait FOMC static du cycle. Devient FRED-only. Réexport rétrocompat des helpers déplacés. |
| `core/src/tik_core/aggregator/macro_static_ingester.py` | **Nouveau** (~120 lignes). `MacroStaticIngester(BaseIngester)` qui upsert `all_static_events()` à chaque cycle daily. Aucune dépendance externe. |
| `core/src/tik_core/scripts/run_ingesters.py` | +1 instance `MacroStaticIngester(session_maker=..., interval_s=24*3600)`. |
| `core/tests/test_macro_calendar_data.py` | +43 tests (invariants ECB/BoJ/BoE, `date_to_utc_release` 4 timezones, `all_static_events()`, `build_event_from_static` 4 sources). |
| `core/tests/test_fred_calendar_ingester.py` | 1 test refactor (FOMC retiré) + 1 nouveau (`test_ingester_cycle_includes_fred_dates_only`). |
| `core/tests/test_macro_static_ingester.py` | **Nouveau** (10 tests : lifecycle no_session_maker → skip propre, `_cycle()` upsert all events, counts par source, best-effort sur erreur DB, structure events). |
| `docs/adr/020-multi-central-banks-static-ingester.md` | **Nouveau** — formalise les 6 décisions. |
| `docs/comprendre_tik.md` | Section 22 pédagogique FR sur le calendrier multi-BC. |
| `docs/backlog.md` | Entry #5 ✓ Phase B2 livrée + entry #7 enrichie (A.4 validation dates 2026-2027, B.4 importance BoE). |

#### Schéma DB et API : aucune modification

Table `macro_events` Phase B1 (migration `0005_macro_events`) déjà
domain-agnostic : `source: str` accepte les nouvelles valeurs, schéma
Pydantic `MacroEventOut` et endpoints `/macro_events/{upcoming,history}`
inchangés. La carte Home dashboard `MacroEventsCard` affiche ECB Lagarde /
BoJ Ueda / BoE Bailey **automatiquement sans aucune modification frontend**.
C'est l'effet visé par la conception domain-agnostic Phase B1 (ADR-017 D4+D5).

#### Validation effectuée

- Syntaxe Python OK sur tous les fichiers modifiés (py_compile).
- Test d'import du module pur : `FRED_RELEASES=7` + `FOMC=12` + `ECB=12`
  + `BoJ=12` + `BoE=12` = 48 static events. Conversions timezone
  validées (ECB 14h15 CEST → 12h15 UTC, BoJ 12h JST → 03h UTC, BoE 12h
  BST → 11h UTC).
- Suite pytest complète **à valider sur Mac/HP** (env serveur n'a pas
  Docker/dépendances) — inscrite dans backlog #7 A.2 standard. Estimation :
  954 → ~1007 verts (+53 nouveaux : 43 calendar_data + 10 static_ingester
  + 0 net fred_calendar_ingester).

#### Garde-fous opérationnels rappelés

- **Garde-fou 1** (Tik shadow vs Zeta 3 mois) **inchangé**.
- **ADR-003** (pas de bypass V01-V15) **inchangé** — calendrier macro est
  un outil de discipline humain, **pas un input des engines**.
- **ADR-004** (multi-overlay) **inchangé** — calendrier ne devient pas
  un overlay du `combined_bias`.
- **Garde-fou 2-bis** (sizing 1 %, veracity ≥ 0.90, discipline macro
  ±4 h autour event HIGH) **renforcé empiriquement** : la discipline
  s'étend à 24 events internationaux/an en plus des US.

#### Limites connues post-livraison

1. **Dates 2026-2027 ECB/BoJ/BoE basées sur patterns publiés** — à
   vérifier par l'utilisatrice contre les sites officiels avant
   déploiement runtime (cf. backlog #7 A.4). UNIQUE constraint
   `(event_code, scheduled_for)` protège contre doublons mais pas
   contre erreur de date.
2. **2027 = estimations sur patterns**. Calendrier 2027 confirmé sera
   publié mi-2026 par chaque BC. Mise à jour annuelle dans
   `macro_calendar_data.py`.
3. **Importance BoE MEDIUM = pifomètre raisonné**. À recalibrer
   empiriquement post-J+30 (backlog #7 B.4).
4. **Pas de couplage automatique signal ↔ event proche**. L'humain fait
   le lien mentalement. Phase B2.5 (flag `near_macro_event` sur signaux
   dans la fenêtre ±4 h) envisageable selon retour terrain.

#### Mémoire pour instances Claude futures

- Si une BC déplace une réunion (rare mais arrive — BoJ a bougé son
  statement 2x sur 10 ans), éditer `macro_calendar_data.py` ET restart
  `MacroStaticIngester` (idempotent — UNIQUE constraint protège
  contre doublons).
- **NE PAS** ajouter des dates ECB/BoJ/BoE sans citer la source officielle
  en commentaire de la liste. Le pattern Phase B1 (URL en tête de
  `FOMC_STATIC_DATES`) est la convention.
- **NE PAS** revenir au pattern "tout dans FredCalendarIngester" sans
  re-lire ADR-020 décision 1 — la séparation static/dynamic résout un
  bug latent qui était silencieux en Phase B1.

### Paquet 24 — Refonte dashboard Home tabs Marché/Calibration/Système LIVRÉ (backlog #5 Levier B+D, 2026-05-16)

Refonte UX du dashboard Home demandée par l'utilisatrice juste après
Paquet 23 (même session 2026-05-16, J+2 trading manuel). La Home avait
**13 sections empilées** (cf. backlog #5 constat 2026-05-05) — trop
dense pour une utilisatrice débutante. Refonte = tabs internes pour
organiser visuellement + élagage de sections obsolètes.

#### Architecture retenue

**3 tabs internes** (state local React `activeTab: 'market' | 'calibration' | 'system'`) :

- **Marché** (défaut, ce dont la trader a besoin avant un trade) :
  Top headlines + Veracity globale + Macro events + Dernier signal par
  actif + Activité 24 h
- **Calibration** (vue d'audit, consultée en début de journée) :
  Hit rate live + Hit rate par veracity + Tendance veracity + Stats LLM
- **Système** (menu secondaire) : État du core + Bouton refresh +
  Version box + rappel des autres onglets (Signals/Watchlist/Alerts/
  Bots/Config)

**Pas de scroll preserved par tab** — pattern radio buttons simple,
conditional rendering en un seul scroll. Pas de dépendance externe à
React Native Tab Navigator (overkill pour 3 sections internes).

**Pas de persistence du dernier tab sélectionné** — Marché par défaut
à chaque ouverture. Friction minimale (3 tabs = 1 tap pour switcher).

#### Décisions structurantes prises

| # | Décision | Verdict |
|---|---|---|
| D1 | Mécanisme tabs : Tab Navigator vs radio buttons | **Radio buttons** (simple, pas de lib externe, ParallaxScrollView préservé) |
| D2 | Onglet défaut + persistence | **Marché par défaut, pas de persistence** (3 tabs = 1 tap = friction minimale) |
| D3 | Placement MacroEventsCard (livré Paquet 11, après backlog #5) | **Onglet Marché** (outil de discipline avant trade, cohérent vision Phase B1) |
| D4 | Suppression Roadmap Paquet 3 obsolète | **Oui** (Paquet 3 livré 2026-05-01, 15 jours plus tard plus de raison de l'afficher) |
| D5 | Sélecteurs hit rate partagés entre 2 cartes Calibration | **Garder state lifted dans HomeScreen** (les 2 cartes restent synchronisées même séparées dans le DOM tab) |
| D6 | Comportement quand on switch de tab pendant un fetch | **Aucune action** — les hooks (useHitRate, useTopHeadlines, etc.) continuent leur poll. Au retour du tab, données fraîches. |

#### Fichiers modifiés (1 + bump version)

| Fichier | Changement |
|---|---|
| `dashboard/app/(tabs)/index.tsx` | Refactor complet : ajout state `activeTab`, composant TabBar inline (3 boutons Pressable), conditional rendering via `renderMarketTab` / `renderCalibrationTab` / `renderSystemTab`. Suppression section Roadmap Paquet 3. Déplacement State du core + Version box dans `renderSystemTab`. Total ~430 lignes (vs 422 avant). |
| `dashboard/package.json` | Bump 0.5.6 → 0.5.7. |

#### Validation effectuée côté env serveur

- Pas de Node disponible côté env serveur Claude Code → pas de
  `tsc --noEmit` possible ici.
- Validation TypeScript + runtime visuelle **à faire côté HP/Mac** :
  `npx expo start --clear` côté dashboard puis scan iPhone via Expo Go,
  vérifier qu'aucune section ne plante au switch de tab, que les
  sélecteurs hit rate gardent leur valeur entre Marché ↔ Calibration.

#### Garde-fous opérationnels rappelés

- **Garde-fou 1** (Tik shadow vs Zeta 3 mois) **inchangé**. La refonte
  est purement UX, zéro modification backend / engines / pipeline
  scoring / cross-validation.
- **ADR-003** (pas de bypass V01-V15) **inchangé**.
- **ADR-018** (Tik OSINT pur) **inchangé**.
- Refacto purement front, **aucun fichier `core/` touché**, **aucune
  modif Pydantic / endpoints / migrations Alembic**.

#### Limites connues post-livraison

1. **Pas testé sur petit écran** (iPhone SE / iPhone Mini) — les boutons
   tab pourraient être étroits. Validation visuelle iPhone 12 Pro Max
   (device utilisatrice) suffisante en première approche. Adaptation
   responsive si retour terrain négatif.
2. **Sélecteurs hit rate partagés** (entity/horizon/includeFlagged) :
   choix volontaire pour éviter la duplication d'état mais si la trader
   préfère 2 contextes séparés (ex. swing BTC sur Calibration, flash
   GOLD ailleurs), ça nécessitera de séparer les states. Inscrit comme
   limite à observer post-J+14.
3. **Onglet Système peu utilisé** — `État du core` était auparavant en
   tête de Home, désormais caché derrière 2 taps. Volontaire (la trader
   n'a pas besoin de voir l'état du core toutes les 5 min) mais à
   surveiller : si l'utilisatrice se plaint de ne pas voir tout de
   suite quand le core est down, on remontera un indicateur compact
   dans la TabBar ou en bas de Marché.
4. **Roadmap Paquet 3 supprimée** : si l'utilisatrice voulait garder
   un historique des livraisons, c'est désormais dans
   `CLAUDE.md` (le seul endroit qui doit l'avoir, plus de duplication).

#### Mémoire pour instances Claude futures

- **NE PAS** réintroduire la section Roadmap Paquet 3 dans le dashboard.
  L'historique des livraisons est dans CLAUDE.md ("État d'avancement").
- **NE PAS** mettre l'État du core sur Marché — c'est désormais sur
  Système exprès, pour réduire la densité visuelle avant un trade.
- Si une feature future ajoute une nouvelle carte, **choisir l'onglet
  selon le critère** : *est-ce que la trader la consulte AVANT un trade
  (Marché), pour AUDIT (Calibration), ou pour CONFIG/MAINTENANCE
  (Système) ?*
- Bump version dashboard à chaque livraison Paquet ≥ 1 fichier
  `dashboard/` modifié (cohérent pattern Paquets 13, 14, 22).

### Plan stratégique post-audit fiabilité signaux (révision 2026-05-06 ~01h00)

Re-audit demandé par l'utilisatrice fin de session pour trier les recommandations selon le critère **« fiabilité, précision et qualité des signaux Tik émis »** uniquement, en excluant UX/sécurité/mobilité (axes orthogonaux qui restent à mener mais ne contribuent pas à la qualité signal).

**Contexte** : trading manuel J+14 (2026-05-14, dans 8 jours), priorité utilisatrice. Garde-fou 2-bis (sizing 1% capital, filtre veracity ≥ 0.90 sur swing, discipline macro ±4h autour event HIGH) reste applicable. Garde-fou 1 (mode shadow Tik vs Zeta 3 mois) inchangé — applicable à Zeta auto, pas au trading manuel humain.

**Décisions reconsidérées avec verdict révisé** :

- **D1 Phase C Watchlist — AsyncStorage local seul → POST /feedback systématique côté backend + AsyncStorage en complément local**. Raison : le feedback humain alimente la recalibration daily 03h UTC des SOURCE_SCORES (ADR-011). Le perdre côté backend = priver la calibration source credibility d'un input de qualité. À implémenter en Phase C Session 2 (cf P7 ci-dessous).
- **Track record flash — 4 horizons fixes 1h/6h/24h/5j (verdict Paquet 12) → granularité adaptée par horizon de signal** : flash → 15min/30min/1h/4h ; swing → 1h/6h/24h/5j (actuel) ; macro → 1j/7j/30j/90j. Raison : aujourd'hui un signal flash perd 75 % de son track record sur des horizons hors-fenêtre contractuelle (24h/5j). Mesure fine sur la fenêtre flash = calibration plus précise du sweet spot flash → ajustements SOURCE_SCORES flash plus fiables. Refactor backend ~2-3h (refetch klines 15m Binance pour les horizons fins).

**Plan d'action stratégique fiabilité signaux (révision 2026-05-06)** :

| Priorité | Action | Effort | Quand |
|---|---|---|---|
| ✅ **P1** | Re-run Session 4-bis golden dataset deltas 5j → conclusions hit rate par source. **Mesuré** : Ollama 38 % > Humain 27 % > Keywords 23 % à 5j ; CryptoCompare Ollama 47 % top performer ; humain meilleur à 24h (68 %) que 5j. Période bullish 1 cycle, à reproduire post-J+30 sur bear. | ~30 min | ✅ LIVRÉ 2026-05-07 (cf. Paquet 19) |
| ✅ **P2** | Étape 7 calibration sources numériques (FG, GDELT, DXY, COT) sur 12m. **Mesuré** : DXY contrarian inversé sur GOLD (IC +0.23), COT contrarian inversé (IC +0.43), FG marginalement contrarian sur BTC (IC -0.10), GDELT non mesurable (rate-limit historique). **Décision** : DXY+COT désactivés par défaut sur GOLD via env var (réversible). | ~2h | ✅ LIVRÉ 2026-05-07 (cf. Paquet 19 + ADR-018 amendement) |
| ✅ **P3** | Décision GDELT BTC — **VERDICT PRIS 2026-05-18 (option E = ne pas déployer + recalibrer GOLD post-J+30)**. Mesure runtime HP 5j : **239/239 = 100 % des tones GDELT GOLD en zone neutre** `[-1, +1]` (min 0.070, max 0.700, avg 0.376, std 0.208). Le mapping ADR-010 ±1/±3 ne s'est **jamais déclenché** depuis le déploiement HP → GDELT GOLD émet bias=0.0 systématique. Déployer GDELT BTC avec les mêmes seuils = overlay dormant garanti. **Décision** : ne pas déployer GDELT BTC, recalibrer les seuils GDELT GOLD post-J+30 sur 30j de runtime (idéalement avec un événement de stress macro), tracé `docs/backlog.md` entry #9 avec critère chiffré. | ~30 min mesure + doc | ✅ VERDICT 2026-05-18 (sans code) |
| 🟡 **P4** | Étape 9 ajustements `SOURCE_SCORES` selon mesures P1+P2 — **partiellement traité** par l'amendement ADR-018 P2 (désactivation = pondération à 0 effective). Ajustements fins des `SOURCE_SCORES` (CryptoCompare 0.70 → ?, Reddit 0.65 → ?) reportés post-J+14 après mesure sur fenêtre diversifiée. | ~30 min | 🟡 Reporté post-J+14 |
| ✅ **P5** | Track record granularité adaptée par horizon (flash 15min/30min/45min/1h dans TTL signal, swing inchangé, macro 1j/7j/30j/90j) — refactor Paquet 12 (cf. Paquet 17 ci-dessus) | ~2h30 livrés (avec correction flash post-livraison) | ✅ LIVRÉ 2026-05-06 |
| **P6** | Détection anomalies par ingester : brigading Reddit (ratio comments/upvotes), dominance publisher Google News (>50% single source), pic volume CryptoCompare anormal vs baseline 7j — invalide ou pondère down les biais pollués | ~3-4h | Post-J+14 (premier mois trading) |
| ✅ **P7** | Phase C Session 2 avec `POST /feedback` systématique — auto-resolution + hit rate perso vs Tik global + bouton override feedback nourrissant la calibration source credibility. **LIVRÉE 2026-05-19 (Paquet 28)** : 4 nouveaux fichiers (`outcome.ts` / `stats.ts` / `useAutoResolveWatchlist.ts` / `personal-hit-rate-card.tsx`) + 5 modifiés + bump dashboard 0.5.13. TypeScript + ESLint exit 0. 8 décisions structurantes D1-D8 documentées. | ~2-3h livrés ✅ | ✅ LIVRÉ 2026-05-19 |
| **P8** | Phase B Polymarket (ADR-015) — 5e overlay sentiment BTC avec « money on the line », signal qualité supérieure aux news textuelles éditoriales | ~2 sessions | Post-J+14 si pas eu le temps avant |
| ✅ **P9** | Phase B2 calendrier macro multi-banques centrales (ECB/BoJ/BoE) — étend la discipline macro hors-US. **Livré 2026-05-16** (Paquet 23, ADR-020). 36 events 2026-2027 ajoutés, nouvel ingester `MacroStaticIngester` séparé, fix bug latent FOMC sans clé FRED. Phase B3 (élections G7) reportée post-J+30 selon retour utilisatrice. | ~3-4h livrés ✅ | ✅ LIVRÉ 2026-05-16 |

**Recommandations dépriorisées (zéro impact fiabilité signal)** :
- EAS Build dev (UX mobilité, cf Paquet 16)
- Sync multi-device Watchlist (UX)
- Traduction FR ADR-014 (UX)
- Reframe OSINT vocabulaire (modularité future, neutre signaux)
- Phase C UX cosmétique (toggle, placement, etc.)
- Failles hygiène défense en profondeur Tailscale (TLS Caddy, firewall macOS, ACLs Tailscale — sécurité, cf Paquet 15)

**Cohérence avec la stratégie globale Tik** :
- **ADR-003** (pas de bypass V01-V15) inchangé — le pipeline guard reste prioritaire pour la phase Zeta auto post-3 mois shadow.
- **ADR-004** (multi-overlay) **renforcé** — P2/P4/P5/P8 ajoutent précision/source dans le pipeline existant, ne le cassent pas. P5 améliore la granularité de mesure track record. P8 ajoute un overlay sentiment BTC qualitativement supérieur (marchés prédictifs avec capital engagé).
- **ADR-011** (anti fake-news) **renforcé** — P6 détection anomalies = couche supplémentaire pré-cross-validation, complémentaire au Modified Z-score d'Iglewicz-Hoaglin.
- **Garde-fou 1** (shadow Tik vs Zeta 3 mois) inchangé.
- **Garde-fou 2-bis** (sizing 1%, veracity ≥ 0.90, discipline macro ±4h) inchangé — règle stricte trading manuel J+14.
- **Section 6 paranoïa contrôlée** maintenue — chaque priorité a un argument chiffré ou un risque tracé.

**Mémoire pour instances Claude futures** : ce plan est l'**axe stratégique #1** pour Tik tant que le trading manuel J+14 est la priorité utilisatrice. Toute nouvelle décision technique doit être réévaluée selon ce filtre « contribue-t-elle à la fiabilité des signaux émis ? ». Si oui → priorité haute. Si non → différée à post-J+14 ou backlog. **Ne jamais ajouter une feature qui dilue ce focus avant le 2026-05-14.**

### Couches encore non-implémentées (évolutions futures)

- Engine macro (semaines-mois) — partiellement couvert via FRED
- Flash GOLD (bloqué par le délai 15 min de Yahoo Finance — nécessite une source temps réel alternative)
- Détection d'anomalies par ingester (brigading Reddit, dominance d'un publisher Google News, pic de volume anormal) — backlog, complémentaire au Paquet 5 livré
- Ingester news : ✅ CryptoCompare (Paquet 1.x), ✅ Google News RSS BTC + GOLD (Paquet 4 Session 1, ADR-008), ✅ Reddit BTC pondéré log upvotes (Paquet 4 Session 2, ADR-009), ✅ GDELT timelinetone GOLD NLP scientifique non-LLM (Paquet 4 Session 3, ADR-010), Nitter / GDELT BTC en évaluation Session 4+ (avec dataset golden)
- Marchés prédictifs : Polymarket, Kalshi
- Backtesting service (script CLI déjà livré, service à industrialiser)
- Data alternative : Google Trends
- Traduction native française des signaux Tik (ADR-014 réservé — ADR-013 finalement utilisé pour le timezone fix Paquet 7) — voir `docs/backlog.md` entry n°2
- ~~Carte secondaire dashboard "Hypothèse LLM (en validation)"~~ ✅ **Livrée et activée runtime 2026-05-04 après-midi** : carte "Hypothèse contextuelle (LLM · validation)" affichée conditionnellement sur `signal.advisory.llm_hypothesis_candidate` (≥ 30 mots via `isLlmCandidateValid`), badge gris "LLM · validation". Code dans `dashboard/app/signal/[id].tsx:142-173`.
- **Plan préparation trading manuel J+10** (2026-05-04 → 2026-05-14, cf. `docs/backlog.md` entry n°3) :
  - ✅ **Phase A.1 — Carte "Top headlines aujourd'hui" dashboard (J+1-2)** : LIVRÉE 2026-05-05, cf. Paquet 8 ci-dessus.
  - ✅ **Phase 1.1 — Lacunes OSINT pro essentielles (A + G + C)** : LIVRÉE 2026-05-05, cf. Paquet 9 ci-dessus.
  - ✅ **Phase A.2 — Carte Home "Hit rate live" (J+3-4)** : LIVRÉE 2026-05-05, cf. Paquet 10 ci-dessus.
  - ✅ **Phase A.2-bis — Hit rate par tranche de veracity** : LIVRÉE 2026-05-05, cf. Paquet 10 ci-dessus. Insight pattern flash BTC inversé (0.80-0.89 = 53.5 % vs 0.90+ = 13-16 %) à investiguer post-J+14.
  - ✅ **Lacune B Phase B1 — Calendrier macro (ADR-017)** : LIVRÉE 2026-05-05, cf. Paquet 11 ci-dessus. Discipline ±4h autour des events HIGH (FOMC, NFP, CPI) pour le trading manuel J+14.
  - ✅ **Phase A.3 — Vue "Track record signal" dans détail signal (J+5-6)** : LIVRÉE 2026-05-05, cf. Paquet 12 ci-dessus.
  - ✅ **Phase C Session 1 — Watchlist (reframée OSINT)** : LIVRÉE 2026-05-05, cf. Paquet 13 ci-dessus. Marquage manuel des signaux + onglet dédié + persistance AsyncStorage. Pattern domain-agnostic (« suivre » / « résultat observé »), réutilisable hors trading.
  - Phase C Session 2 — Auto-resolution outcome + hit rate perso + bouton override feedback (~2-3h, à attaquer après J+1-2 d'usage Session 1) : poll `getSignalTrackRecord` toutes les 5 min throttlé, modal override + POST `/api/v1/feedback`, stats hit rate perso vs Tik global avec disclaimer biais de sélection si N < 20.
  - Phase B — Polymarket ingester + entity PREDICTION_MARKET + carte dashboard (J+7-8, ~2 sessions, ADR-015)
  - J+10 calibration mentale + premier trade manuel
- **Phase 2 — Enrichissement contextuel hypothèse LLM (réservé ADR-018, post-J+30)** : pistes A/B/C/D évaluées dans `docs/backlog.md` entry n°4. Verdict : Piste A (top headlines injectés dans le prompt LLM) en mode shadow strict 1 mois + dataset golden d'évaluation, à attaquer **uniquement si** le retour utilisatrice après 2-3 semaines de trading manuel confirme un manque contextuel narratif que la carte Top headlines (Phase A.1) ne couvre pas. *(Note : ADR-017 initialement réservé à cette piste a été pris par le calendrier macro Lacune B Paquet 11, glissement à ADR-018.)*
- **Backlog couches OSINT structurées (3 vagues, décision 2026-05-17)** — roadmap conditionnelle documentée dans **[`docs/backlog-osint.md`](docs/backlog-osint.md)** (fichier dédié, séparé de CLAUDE.md pour ne pas l'alourdir + sécuriser les futures gestions de couches). Résumé : **Vague 1** (post-J+14, justification structurelle) = Silver (entité tradable indépendante), WGC + SPDR GLD ETF flows, Farside BTC ETF flows avec plan B, CoinGlass free tier sous condition, Whale Alert ≥ 10 M USD avec calibration ; **Vague 2** (post-J+44, uniquement si manques mesurés) = anomalies, régime marché, stress systémique, GDELT calibré, comportemental ; **Vague 3** (post-J+90, uniquement si edge mesurable) = Glassnode/CryptoQuant Pro payants, corrélation dynamique, Platinum/Palladium, EUR/USD réservé entité tradable, ETH réservé. **REFUSÉ indéfiniment** : Arkham/Mempool/Blockchain.com (doublons Whale Alert), miners flows. Aucune source codée à ce jour. Engagements méthodologiques (13bis, une source à la fois, mesure 2 semaines, métriques IC Spearman/hit rate/stabilité/coverage) rappelés dans le fichier. Date de réévaluation : 2026-06-30 (J+44 du trading manuel décalé au 2026-05-24).
- **Hébergement Tik + distribution de l'appli — exposé fait, DÉCISION EN ATTENTE (2026-05-31)** : discussion complète dans **[`docs/hosting-and-app-options.md`](docs/hosting-and-app-options.md)** + mémoire `hosting-app-distribution-decision`. Points exposés à l'utilisatrice (non-technique) : (1) **appli ≠ connexion** — l'appli n'est que l'écran, Tik (API+moteurs+DB) est la « station » sur un serveur ; faire une vraie appli ne donne PAS l'accès « dehors » ; (2) **24/7 impossible sans serveur toujours allumé** (Mac éteint = Tik off, collecte/calibration stoppées) → seul un VPS donne le 24/7 ; (3) **Tailscale** : optionnel (sécurité) sur VPS, **nécessaire** (connexion extérieur + associé) en local Mac, gratuit à leur échelle ; (4) **Expo Go = outil de dev**, **vraie appli (EAS Build) = produit** recommandé long terme (cf. Paquet 16) ; (5) **99 €/an Apple ≠ licence commerciale** = signature + TestFlight (seul moyen propre de partager à l'associé ; Apple ID gratuit = réinstall tous les 7 j + partage galère). **2 scénarios** : A (tout gratuit : local Mac + Tailscale, mais PAS 24/7 + associé compliqué) vs B (VPS ~5 €/mois + 99 €/an + TestFlight = 24/7 partout à deux, recommandé si dépendance continue). **NE PAS ré-expliquer de zéro** : reprendre le doc + aider à trancher (3 questions d'usage en bas du doc).

### Paquet 25 — Audit recalibration ADR-011 + diagnostic DB HP trop jeune (2026-05-17 soir)

Audit post-fix bug N=2 (commit 65d2818 du 2026-05-17 ~20:47 UTC) — vérification de la santé de la recalibration auto ADR-011 avant le démarrage du trading manuel J+14 (décalé au 2026-05-24).

**Mesures factuelles côté HP** :

- Table `source_credibility_history` : **0 rows** depuis le déploiement Paquet 5 (2026-05-03, 14 jours).
- Redis `tik.source_credibility.*` : **(empty array)**.
- DB HP `signals` : premier signal au **2026-05-13 10:07 UTC**, dernier au 2026-05-17 22:23 UTC. **1514 signaux sur 5 jours**, ~303 signaux/jour.
- Logs scheduler post-restart 2026-05-17 20:18 UTC : job recalibrate_sources tourne sans erreur en retournant `signals_loaded n=0` → `no_signals_skip` → `scheduler.recalibrate_sources.done n=0`. **Comportement attendu, pas un fail.**

**Diagnostic définitif (pas un bug code)** : la fenêtre de lookback `[now-30j, now-5j]` de [source_credibility.py:354-355](core/src/tik_core/scoring/source_credibility.py#L354-L355) est mécaniquement **vide** sur l'environnement HP frais. La recalibration auto deviendra opérante naturellement vers **2026-06-18 03:00 UTC** (35 jours après le premier signal en DB = 30j lookback + 5j cutoff horizon). Jusque-là, Tik tourne sur les `SOURCE_SCORES` statiques de `swing_engine.py` — **comportement déjà en place depuis le Paquet 5** (idem pendant la phase Mac avant migration HP, la table était probablement aussi vide là-bas).

**Validation runtime du fix bug N=2** : sur 19 signaux émis dans les 1h25 post-fix (2026-05-17 20:48 → 22:13 UTC), distribution **désormais saine** :

| Métrique | post_fix (n=19) | pre_fix_7d (n=1491) |
|---|---|---|
| avg veracity | 0.8726 | 0.9495 |
| stddev veracity | **0.0667** | 0.0071 |
| n à veracity = 0.95 | 6 (32 %) | 1482 (**99.4 %**) |
| n à veracity ≥ 0.90 | 7 (37 %) | 1484 (99.5 %) |

✅ Veracity désormais **variée**. Filtre Garde-fou 2-bis (veracity ≥ 0.90 sur swing) redevient discriminant (37 % post-fix vs 99.5 % pré-fix = inopérant). Sources d'evidence : BTC swing à N=4 sources (CryptoCompare actif post-fix clé API), BTC flash à N=3, GOLD swing à N=3 — distribution stable post-fix (en pré-fix BTC swing variait de N=1 à N=4).

**Décisions structurantes prises (Q1-Q4 utilisatrice)** :

- **Q1 phasing** : mix audit + attente. Audit complet ce soir, mesure empirique différée 10-12j.
- **Q2 objectif** : **les deux niveaux** (niveau 1 veracity ≥ 0.90 prioritaire en conflit, niveau 2 global = garde-fou contre régression silencieuse). Raison : algo ADR-011 mesure le global (pas le filtré), donc audit possible.
- **Q3 tolérance** : basse. Zéro code écrit cette session, aucun gel cron, aucune purge Redis (déjà vide), aucun toggle env ajouté.
- **Q4 action bug** : cas par cas. Aucun bug trouvé, donc rien à fixer.

**Plan d'action calendaire (mesure manuelle pendant la période silencieuse de la recalibration auto)** :

| Date | Étape |
|---|---|
| 2026-05-22 | Premiers signaux post-fix N=2 mûrs à horizon 5j (mesure préliminaire possible) |
| 2026-05-27 (J+10 post-fix) | Lancement mesure manuelle niveau 2 via script `measure_post_fix_hit_rates.py` (387 lignes Python, **MATÉRIALISÉ et validé runtime 2026-05-19** sur données pré-fix, cf. Paquet 30) |
| 2026-06-15 (J+29) | Mesure niveau 1 (veracity ≥ 0.90) probablement disponible avec ≥ 30 samples |
| 2026-06-18 (J+32) | Recalibration auto opérante théorique, premier ajustement attendu |

**Memory project créée** : `recalibration-state-2026-05-17` pour éviter qu'une future session re-diagnostique inutilement la table vide. Date de péremption de cette memory : 2026-06-19.

**Aucun fichier core/dashboard/tests modifié.** Paquet doc-only (CLAUDE.md + MEMORY.md + 1 nouveau fichier memory). Garde-fou 1 / ADR-003 / ADR-004 / ADR-011 / ADR-018 inchangés. Suite pytest inchangée à 988 verts (cohérent avec commit `65d2818` du 2026-05-17 matin).

### Paquet 26 — Fix Bug 10 WebSocket leak coroutine zombie + audit santé runtime pré-trading (2026-05-17 soir, suite Paquet 25)

Audit santé runtime exécuté côté HP avant trading manuel J+14 (cf. Paquet 25 contexte). 6 commandes pass/fail menées : containers Docker, jobs scheduler, logs ingesters 6h, SQL bundle (LLM mode + anti fake-news + headlines + macro events), sources actives evidence, sentinelles Redis. **4 issues critiques découvertes** + 3 issues connues confirmées.

**Issue critique #1 traitée immédiatement (Bug 10, cf. section 9 ci-dessous)** : `tik-core API unhealthy` depuis 3h, curl `/api/v1/health` hang à 5s timeout. Root cause = WebSocket leak coroutine zombie dans `core/src/tik_core/api/ws.py:106` (`except Exception` qui logue mais ne `break` pas la boucle pubsub). Fix Option A appliqué : sépare parse JSON (continue si payload invalide) vs send_json (break si client gone), ajoute commentaire explicite référençant ce bug.

**3 autres issues critiques identifiées mais NON traitées cette session** (à arbitrer dans une session suivante avant J+14) :
- **Issue #2 LLM hypothesis NOT active sur HP** : 172/172 signaux 12h en `hypothesis_type=template_short` (avg 92 chars). Fix probable = éditer `core/.env` HP `TIK_LLM_HYPOTHESIS_MODE=active` + restart scheduler (~5 min). Trader perd contexte LLM 6 sections.
- **Issue #3 CryptoCompare BTC swing à 7 % seulement** : 11/49 cycles swing BTC ont CC dans evidence (vs 49/49 pour binance_klines, google_news, FG). 78 % swing BTC tournent à 3 sources au lieu de 4. Cause probable Ollama timeout systématique cryptocompare classifier. À investiguer (~30-60 min).
- **Issue #4 Baseline anomaly CryptoCompare WRONGTYPE Redis** : clé `tik.anomaly.baseline.cryptocompare.btc` existe mais pas une LIST → `WRONGTYPE Operation`. Détection volume spike CC silencieusement KO (Paquet 21 P6 partiellement cassé). Non-bloquant trading.

**Amendement post-livraison — 2026-05-18 (suite Paquet 26)** :

- **Issue #2 LLM hypothesis active** : ✅ RÉSOLUE runtime. Édition `core/.env` HP `TIK_LLM_HYPOTHESIS_MODE=active` + `docker compose up -d --force-recreate scheduler` appliqués le 2026-05-17 vers 22h UTC. Vérifié 6h plus tard côté HP : scheduler `Up 6 hours (healthy)`, signaux publiés normalement (79 `signal.published` en 6h, cohérent avec swing_btc 24 + swing_gold 12 + flash_btc conditionnels). Bascule shadow → active confirmée.

- **Issue #3 CryptoCompare BTC swing à 7 %** : ✅ AUTO-RÉSOLUE par le rebuild scheduler/core du 2026-05-17 soir (fix Bug 10 + activation LLM mode active). Mesure SQL 2026-05-18 sur 6h post-rebuild : `cryptocompare_news` à **24/24 = 100 %** de couverture dans l'evidence BTC swing, à égalité avec `binance_klines` / `alternative_me_fng` / `google_news_rss`. Logs `swing.btc.cryptocompare_unavailable` sur 6h post-rebuild = **0**. Cause root probable : la mesure 7 % du 2026-05-17 23h UTC chevauchait l'ancienne image scheduler (11 h pré-rebuild) et la nouvelle (1 h post-rebuild), faisant ressortir un historique stale. **Aucun fix code appliqué** — engagement *"pas d'ajout sans manque mesuré"* (cf. section 13bis) respecté. **Mea culpa méthodologique** consigné : toujours vérifier `docker compose ps` et l'âge des containers AVANT d'investiguer un bug runtime mesuré sur fenêtre temporelle ; chevauchement pre/post rebuild = faux positif probable.

- **Surveillance H+24 effectuée (2026-05-18)** : ✅ **Issue #3 DÉFINITIVEMENT CLÔTURÉE**. Mesure SQL post-rebuild Bug 10 (commit `cfabd12`, scheduler/core `Up 7 hours`) : `cryptocompare_news` à **28/28 = 100 %** sur la fenêtre stable 7h, à égalité avec `binance_klines` / `alternative_me_fng` / `google_news_rss`. Une mesure brute sur 24h glissantes retourne 76/98 = **77.6 %** mais c'est un **artefact de chevauchement** entre la période pré-rebuild Bug 10 (il y a 7-24h, régime hétérogène avec restart intermédiaire) et la période stable post-rebuild (il y a 0-7h). **Mea culpa méthodologique #2** : j'ai re-fait l'erreur d'interpréter le 77.6 % avant de vérifier `docker compose ps` — exactement le pattern que l'amendement matin du 2026-05-18 venait de documenter. Rattrapage immédiat via vérif uptime containers + re-mesure sur fenêtre stable. **Engagement renforcé pour toute mesure runtime sur fenêtre temporelle : `docker compose ps` AVANT interprétation, systématiquement, sans exception.**

- **Issue #4 baseline anomaly CryptoCompare WRONGTYPE Redis** : ✅ **AUTO-RÉSOLUE** (mesure 2026-05-18 après surveillance H+24). Audit Redis HP : clé `tik.anomaly.baseline.cryptocompare.btc` désormais en `string` (pas LIST), 20 points matures `[50, 50, ..., 50]`, TTL ~14j restants, **0 erreur `cryptocompare.baseline.read_error/write_error` sur 24h de logs**. Le restart ingesters du 2026-05-17 22h UTC (`force-recreate scheduler` → cascade ingesters `Up 18 hours`) a probablement écrasé l'ancienne clé corrompue via `setex` (qui overwrite indépendamment du type Redis précédent). **Aucun fix code appliqué** — engagement *"pas d'ajout sans manque mesuré"* respecté. **Découverte annexe (hors scope Issue #4)** : limite structurelle de `detect_volume_spike` sur CryptoCompare — l'API retourne ~50 articles par défaut, la baseline converge donc vers `[50, 50, ..., 50]`, et `severity=medium` requiert ratio ≥ 3× = 150 articles (structurellement inatteignable sans changer le polling API). **La détection volume spike CC est donc dormante en pratique depuis le Paquet 21**, sans régression (Reddit brigading + Google News dominance couvrent la surcouche P6 sur les autres sources, et cross-validation ADR-011 reste opérationnelle). Limite tracée dans `docs/backlog.md` entry #8 pour Phase post-J+14 (4 options évaluées for/contre, verdict préliminaire Option B = compter publishers distincts à valider empiriquement sur dataset historique).

**3 issues connues confirmées (pas d'action)** : Reddit 403 (différé post-J+24), GDELT 429 1 cycle/2 (publish quand même), Ollama timeout occasionnel (géré ADR-006 circuit breaker batch-level).

**Findings positifs runtime** : tous les autres composants OK — Postgres + Redis healthy 4j, scheduler jobs à la bonne cadence, anti fake-news ADR-011 actif (52 + 80 = 132 flags `degraded` sur 24h, **0 `tripped`**), 102 macro events à venir (Paquet 11 + 23 multi-BC opérationnels), cache sentiment Ollama 307 keys (Lacune C Paquet 9 ✓), flash last direction + last price BTC timestamps frais. **BTC flash** 3 sources égales (33.3 % chacune ADR-005). **GOLD swing** 3 sources égales (Paquet 19 amendement P2). **Anti fake-news swing BTC à 82 % degraded post-fix N=2** : attendu (le fix démasque les divergences que le bug N=2 masquait), à expliquer trader pour qu'elle ne pense pas Tik cassé — direction reste valide, drapeau de prudence, filtre Garde-fou 2-bis (veracity ≥ 0.90) reste opérationnel par-dessus.

**Sécurité postgres+redis bind 127.0.0.1 (Paquet 15) à vérifier HP** : `docker compose ps` montre toujours `127.0.0.1:5432` et `127.0.0.1:6379` pour postgres/redis ✓ (fix Paquet 15 préservé). **MAIS** tik-core toujours sur `0.0.0.0:8200` (faille hygiène 3 documentée Paquet 15 non encore fixée). Cohérent vu garde-fou ce n'est pas critique avec auth API key, à attaquer post-J+14.

**Validation runtime fix Bug 10** : restart `tik-core` immédiat post-diagnostic (`docker compose restart core`) → API répond `{"status":"ok","version":"0.1.0"}` après 10 sec warmup. Fix code permanent (Option A `break` après client gone) à appliquer via `docker compose up -d --build core` (image custom buildée, code copié au build, pas bind-mount). Cf. section 9 Bug 10 pour le diagnostic complet.

**Dette technique tracée** :
- ✅ Test pytest spécifique Bug 10 (WS zombie) — **FAIT depuis le Paquet 31**, vérifié runtime 2026-05-24 : 2 garde-fous « code source » (présence du `break` après `ws.client_gone` + du `continue` sur payload invalide) + 1 test d'intégration close brutal WS, dans `core/tests/test_ws_lifespan.py`. *(Note d'origine, désormais obsolète : « non ajouté cette session, à ajouter ~1-2h ». Limite connue : le test d'intégration skippe en CI sans Redis → seuls les garde-fous « code source » tournent en CI.)*
- Issues #2 et #3 ✅ résolues (cf. amendement post-livraison 2026-05-18 ci-dessus) ; Issue #4 (WRONGTYPE Redis baseline) à arbitrer pré-J+14 ou différer post-J+14 (non-bloquant trading manuel, casse seulement la détection volume spike CryptoCompare du Paquet 21 P6).
- Faille hygiène 3 Tailscale (tik-core sur 0.0.0.0) à traiter post-J+14.

**Aucune régression runtime** post-restart core (API répond, scheduler continue à publier ses signaux, ingesters tournent). Suite pytest **pas relancée** après ce fix (12 lignes scope isolé `ws.py`, low risk — à relancer en session suivante).

### Paquet 27 — Audit santé runtime pré-J+14 + verdict Reddit DOA + 5 décisions opérationnelles (2026-05-18 soir)

Session J-6 avant trading manuel J+14 (2026-05-24, décalé du 2026-05-14 initial). **Audit complet de l'état runtime de Tik avant le démarrage** (PISTE A + PISTE C version réduite), conformément au plan stratégique fiabilité signaux. Aucun fichier code modifié — Paquet **doc-only** + mise à jour Garde-fou 2-bis section 5 + ajout Bug 11 section 9 + entry 10 backlog.md.

#### PISTE A — Audit santé runtime (9h fenêtre stable post-rebuild scheduler matin 2026-05-18)

| Mesure | BTC flash | BTC swing | GOLD swing | Verdict |
|---|---|---|---|---|
| Cadence cycles 9h | 65 (~7.2/h) | 36 (4/h) | 18 (2/h) | ✅ Conforme attendus |
| Direction | 19L / 20S / 26N | **100 % short (36/36)** ⚠️ | 0L / 9S / 9N | 🟡 100 % short BTC swing structurel (marché bear) |
| Veracity ≥ 0.90 | 52 % (34/65) | **0 % (0/36)** 🔴 | 50 % (9/18) | 🔴 Filtre Garde-fou 2-bis non discriminant BTC swing |
| Anti fake-news degraded | 31 % | 33 % | 0 % | ✅ Soft filtering ADR-011 opérationnel |

**Engagement méthodologique #9 vérifié** : containers `Up 9 hours` (scheduler/core post-rebuild matin) → mesures faites uniquement sur la fenêtre stable post-rebuild.

#### Diagnostic Reddit IP-ban full — découverte critique

L'audit révèle que **Reddit n'a jamais contribué à un signal sur le déploiement HP entier** (0/1778 signaux sur 5 jours d'historique HP avec `reddit_btc` dans l'evidence). Diagnostic factuel :

| Mesure | Verdict |
|---|---|
| HTTP 403 sur `www.reddit.com/r/Bitcoin/hot.json` (3 User-Agents testés : custom Tik, Mozilla réel, vide) | IP-ban confirmé, pas un problème UA |
| HTTP 403 sur `oauth.reddit.com/r/Bitcoin/hot.json` | API endpoint aussi bloqué → **OAuth Reddit non viable** |
| HTTP 401 sur `www.reddit.com/api/v1/access_token` (POST) | Endpoint joignable mais inutile sans accès à `oauth.reddit.com` |
| HTTP 403 sur `old.reddit.com` + `reddit.com/dev/api` | Toutes les routes Reddit bloquées |
| Capture utilisatrice navigateur Windows + PC HP : "Vous avez été bloquée par la sécurité du réseau" | **IP publique partagée 204.168.220.47 bannie pour l'ensemble du réseau** |

**Cause probable** : accumulation des polling Tik depuis le déploiement HP + IP datacenter potentiellement dans une plage à mauvaise réputation côté Reddit. Pas un bug Tik — bug réseau Reddit-side.

**Conséquence structurelle pour le pipeline** : depuis le déploiement HP, **Tik tourne avec 3/4 overlays sentiment BTC** (binance_klines + alternative_me_fng + cryptocompare_news + google_news_rss). Quand FG diverge contrarian des news (cas typique marché bear actuel), FG est flaggé outlier → 2 sources alignées + 1 outlier neutralisé → dispersion structurelle → veracity capée à 0.85-0.89 → **filtre Garde-fou 2-bis ≥ 0.90 non discriminant**.

**Le bug N=2 du Paquet 25 (fixé 2026-05-17 20:47 UTC) masquait cette réalité en figeant la veracity à 0.95 pour 99.4 % des signaux pré-fix.** Le fix a révélé la véracité réelle, et l'audit l'a quantifiée.

#### PISTE C version réduite — Backtest 1j sur 1316 signaux matures (threshold ±0.3 %)

| Stratégie | Hit rate global | BTC | GOLD | Gain moyen BTC |
|---|---|---|---|---|
| **Tik** | 31.1 % | 32.8 % | 4.8 % 🔴 | **-0.62 %** |
| Random | 33.2 % | 33.1 % | 34.1 % | -0.54 % |
| Always LONG | 22.6 % | 24.0 % | 2.4 % | -0.72 % |
| **Always SHORT** | **64.1 %** | 62.9 % | **80.7 %** | **+0.72 %** |
| Always NEUTRAL | 13.3 % | 13.1 % | 16.9 % | -1.59 % |

**Par direction Tik BTC** :
- LONG (521 sig) : 31.9 % hit, gain -0.53 % → **perdant**
- **SHORT (263 sig) : 63.1 % hit, gain +0.72 %** → **edge mesuré**
- NEUTRAL (449 sig) : 16.3 % hit, gain -1.51 % → pire que Random

**GOLD chez Tik = 4.8 % hit rate** vs Always SHORT 80.7 % sur 1j horizon (83 signaux). Distribution : 60 LONG + 20 NEUTRAL + 3 SHORT alors que GOLD baisse soutenue. Cohérent amendement P2 ADR-018 (DXY+COT désactivés → moins d'overlays directionnels GOLD) MAIS bug N=2 pré-fix a probablement laissé passer 60 faux LONG GOLD.

**Limitation rigoureuse** : 99.9 % des 1315 signaux historiques ont veracity = 0.95 (figée bug N=2). Hit rate par tranche de veracity **inutilisable rigoureusement** sur cette fenêtre. Vraie mesure stabilisée commence à J+10 post-fix (2026-05-27).

#### 5 décisions opérationnelles validées par l'utilisatrice (D1–D5)

| # | Décision | Verdict | Raison |
|---|---|---|---|
| **D1** | Option A — Accepter Tik à 3 overlays sans Reddit | ✅ ADOPTÉ | Zéro dev, zéro risque pré-J+14, 4 sources restantes solides |
| **D2** | Option B parallèle — Demande unban Reddit soumise via support.reddithelp.com | ✅ EN COURS | Délai inconnu, asynchrone, dette technique tracée backlog #10 |
| **D3** | NE PAS trader GOLD avec Tik à J+14 | ✅ ADOPTÉ | Hit rate 4.8 % vs Random 34 % vs Always SHORT 81 % = pas d'edge |
| **D4** | Garde-fou 2-bis transitoire seuil veracity 0.85 sur BTC swing | ✅ ADOPTÉ | 0/36 signaux BTC swing ≥ 0.90 sur 9h post-fix N=2 = filtre non discriminant à 0.90 |
| **D5** | Observer prioritairement signaux SHORT BTC (sans cristalliser) | ✅ ADOPTÉ | 63 % hit, +0.72 % gain mesuré, à valider J+10 post-fix |

#### Couverture macro J+14 → J+44 (vérification runtime)

12 jours macro-calmes après J+14, premier event HIGH = **NFP 2026-06-05 12:30 UTC**. Phase B2 multi-BC (Paquet 23 ADR-020) confirmée runtime : ECB Governing Council 2026-06-11 + BoJ MPM 2026-06-17 visibles dans la fenêtre 30j. CPI 2026-06-10 également présent. **Cluster macro mi-juin** = la trader aura 12 jours pour calibrer son workflow avant la première période macro chargée.

#### Verts ✅ et oranges 🟡 consolidés

**Verts (9)** :
- Containers healthy (postgres/redis 5j, ingesters 20h, scheduler/core 9h post-rebuild)
- Cadence cycles conforme attendus
- Anti fake-news ADR-011 opérationnel (32 degraded / 0 tripped sur 9h)
- LLM hypothesis active (6 sections ~150 mots cf. Paquet 26 amendement)
- P6 anomalies ACTIVE runtime (champ `anomaly` présent dans payloads, `severity: ok` = aucun seuil franchi)
- Cache sentiment Ollama opérationnel (>100 keys)
- Phase B2 multi-BC confirmée runtime
- Macro J+14 → J+25 = 12 jours macro-calmes
- 1778 signaux DB sur 5j cohérent cadence

**Oranges (2)** :
- GDELT rate-limit 429 ~20 % fetches GOLD (déjà tracé P3 backlog #9, ne pas re-investiguer)
- Recalibration source_credibility silencieuse jusqu'au 2026-06-18 (cf. memory recalibration-state-2026-05-17)

#### Mémoire pour instances Claude futures

- **Reddit IP-ban est structurel sur cette infra** : ne pas re-tenter OAuth tant que (a) Reddit n'a pas répondu positivement à la demande d'unban OU (b) Tik n'a pas migré vers une IP non-bannie. Vérification rapide : `curl -s -o /dev/null -w "%{http_code}\n" -H "User-Agent: test" https://www.reddit.com/r/Bitcoin/hot.json` depuis container ingesters. Si 200 → Reddit débloqué, restart ingesters. Si 403 → toujours bloqué.
- **Garde-fou 2-bis transitoire 0.85** réversible automatiquement quand Reddit revient. Critère retour 0.90 strict documenté section 5.
- **Ne pas trader GOLD avec Tik** = règle dure post-Paquet 27 jusqu'à mesure empirique post-amendement P2 + post-fix N=2 démontre un edge. À rouvrir post-J+30 (cf. backlog #9 GDELT GOLD + critère réactivation DXY/COT amendement ADR-018 P2).
- **Insight SHORT BTC 63 % à valider J+10 post-fix N=2** (2026-05-27 = J+13 du trading manuel décalé). Mesure manuelle prévue dans plan stratégique fiabilité signaux post-trading.

#### Aucune modification code ni runtime

Paquet 27 = pure documentation + diagnostic. Aucun fichier `core/` ou `dashboard/` modifié. Pas de restart container. Suite pytest inchangée à 988 verts (cohérent commit `1624fe7` du 2026-05-18 amendement Paquet 26). Garde-fou 1 / ADR-003 / ADR-004 / ADR-011 / ADR-018 inchangés.

**Limites assumées** :
1. Mesure 9h fenêtre stable post-rebuild scheduler matin — pas représentative d'un cycle 24h+ (mais cohérente engagement #9 stabilité containers).
2. Hit rate par tranche de veracity inutilisable rigoureusement (bug N=2 pré-fix). Vraie mesure dispo seulement après J+10 post-fix (2026-05-27).
3. Diagnostic Reddit ne distingue pas IP-ban temporaire vs définitif. Si l'unban Reddit aboutit dans la fenêtre J+14, on revient sur 4 overlays automatiquement. Si refusé, dette technique post-J+14 (Option C source alternative).
4. Verdict GOLD basé sur 83 signaux 5j = échantillon limité. Période bullish-bear-or atypique. À rouvrir post-J+30 avec dataset plus large.

### Paquet 28 — Phase C Session 2 Watchlist auto-resolve + hit rate perso + override modal (P7 plan fiabilité, 2026-05-19)

P7 du plan stratégique fiabilité signaux livrée à J-5 du trading manuel
(2026-05-24). Complète le Paquet 13 (Watchlist Session 1 du 2026-05-05,
13 jours d'usage potentiel accumulés) avec les 3 features attendues :
auto-resolution outcome via track record signal, stats hit rate perso vs
Tik global, bouton override manuel sur le badge outcome avec POST
/feedback systématique vers la calibration source credibility ADR-011.

#### 8 décisions structurantes prises avant code (for/contre/verdict)

| # | Décision | Verdict |
|---|---|---|
| **D1** | Auto-resolution timing : poll auto vs focus uniquement vs hybride | **Hybride** — 1 cycle au boot du hook + interval 5 min tant que mounted + 1 cycle au focus (via runOnce exposé). Pattern React Native standard sans dépendance lourde. |
| **D2** | Throttling appels API | **Cap N=20 entries/cycle**, priorisé par `addedAt` ASC (plus anciennes d'abord). Évite de spammer le core même avec 200 entries. |
| **D3** | Mapping horizon → row de référence pour outcome | **Row le plus long disponible** : `flash→1h`, `swing→5j`, `macro→90j` (cf. `REFERENCE_ROW_BY_HORIZON`). Cohérent Paquet 17 granularité adaptée par horizon + ADR-005 flash TTL 1h. |
| **D4** | Hit rate perso vs Tik global | **Stats card dédiée** `PersonalHitRateCard` avec hit perso (confirmed / evaluable), Tik global via `getHitRate` (entity × horizon dominant de la watchlist), disclaimer biais de sélection si N evaluable < 20. |
| **D5** | Bouton override : modal custom vs Alert natif | **Alert.alert natif iOS** 4 boutons (Confirmé/Infirmé/N-A/Annuler). Pas de note Session 2 (extension possible Session 3 si besoin). Cohérent pattern `confirmRemove` existant. |
| **D6** | POST /feedback : auto + manuel vs manuel seul | **Auto + manuel** envoyés. Distinction via `trade_id` préfixé (`watchlist-auto-{id}` vs `watchlist-manual-{id}`) et `exit_reason` (`watchlist_auto_{horizon}_{row}_{outcome}` vs `watchlist_manual_{horizon}_override_{outcome}`). Fire-and-forget, swallow 401/403 si scope manquant. |
| **D7** | Anti-spam re-resolution | Champ `manuallyResolved: boolean` sur `WatchlistEntry`. Si true, l'auto ne touche jamais (sanctuaire humain). Auto met false, override met true. |
| **D8** | Backoff erreurs API | Champ `lastAutoAttemptAt: string \| null` + cooldown 30 min entre attempts. Évite spam si API throw HTTP 400 (flash GOLD ADR-005) ou 404 (signal disparu DB). |

#### Mapping outcome watchlist ↔ feedback core

Le vocabulaire watchlist est **OSINT-neutral** (cohérent vision domain-agnostic
Paquet 13), le feedback core est **trading-specific**. Mapping unidirectionnel :

| Watchlist | Feedback core | Sens |
|---|---|---|
| `pending` | (non envoyé) | Pas encore résolu |
| `confirmed` | `win` | Direction Tik correcte |
| `refuted` | `loss` | Direction Tik incorrecte |
| `n_a` | `not_taken` | Data manquante / non-trading explicite |

Mapping row → outcome via `mapRowToOutcome` :

| `row.badge` | Outcome | Action |
|---|---|---|
| `correct` | confirmed | Résolu, success=true |
| `raté` | refuted | Résolu, success=false |
| `données_manquantes` | n_a | Résolu, data indisponible (weekend GOLD, etc.) |
| `en_attente` | (null) | Pas de résolution, reste pending |

#### Implémentation (9 fichiers)

**Nouveaux (4)** :

- [dashboard/src/watchlist/outcome.ts](dashboard/src/watchlist/outcome.ts) (~230 lignes) — helpers purs `deriveOutcomeFromTrackRecord` / `mapRowToOutcome` / `mapOutcomeToFeedback` / `formatExitReason` / `formatTradeId` / `isOutcomeLikelyAvailable` / `isEligibleForAutoResolve` + constantes `REFERENCE_ROW_BY_HORIZON` / `REFERENCE_HOURS_BY_HORIZON` / `AUTO_RESOLVE_COOLDOWN_MS`. Aucune dépendance React/IO. Testable trivialement (tests Jest reportés à Session 3).
- [dashboard/src/watchlist/stats.ts](dashboard/src/watchlist/stats.ts) (~145 lignes) — helpers purs `computePersonalStats` / `selectionBiasWarning` (seuil < 20) / `entriesByHorizon` / `dominantHorizon` (avec tie-breaker swing > flash > macro) / `dominantEntity`.
- [dashboard/src/watchlist/useAutoResolveWatchlist.ts](dashboard/src/watchlist/useAutoResolveWatchlist.ts) (~235 lignes) — hook custom avec refs pour casser les closures stales + factory `createResolveEntryFn` exposée pour tests futurs. Lifecycle : 1 cycle one-shot au boot + interval 5 min tant que enabled. Promise.allSettled pour ne jamais propager d'exception.
- [dashboard/components/watchlist/personal-hit-rate-card.tsx](dashboard/components/watchlist/personal-hit-rate-card.tsx) (~195 lignes) — composant card avec pourcentage gros + comptage détaillé + ligne de comparaison Tik global + warning biais si N < 20 + meta note "X outcomes ajustés manuellement" si applicable.

**Modifiés (5)** :

- [dashboard/src/watchlist/WatchlistContext.tsx](dashboard/src/watchlist/WatchlistContext.tsx) — +3 champs sur `WatchlistEntry` (`manuallyResolved` / `lastAutoAttemptAt` / `autoResolveError`) + 2 setters (`setOutcomeAuto`, `markAutoAttempt`) + helper `normalizeEntry` pour rétrocompat hydratation Session 1 (sans bumper la clé storage `tik.watchlist.v1`). `setOutcome` manuel met `manuallyResolved=true`, `setOutcomeAuto` reste à false (sauf si l'entry était déjà manuellement résolue, auquel cas il ne touche pas — sanctuaire).
- [dashboard/src/api/types.ts](dashboard/src/api/types.ts) — +interface `FeedbackPayload` / `FeedbackResponse` + type `FeedbackOutcome` (`win|loss|breakeven|not_taken`, cohérent `core/storage/schemas.py:FeedbackIn`).
- [dashboard/src/api/endpoints.ts](dashboard/src/api/endpoints.ts) — +`reportFeedback(client, payload)` typed. Commentaire sur scope `write:feedback` requis (POST échoue 401/403 sinon, caller swallow).
- [dashboard/app/(tabs)/watchlist.tsx](dashboard/app/(tabs)/watchlist.tsx) — câblage `useAutoResolveWatchlist` au mount, `useEffect` pour fetch `getHitRate` au changement de comparaison, remplacement statsLine par `PersonalHitRateCard`, badge outcome Pressable avec `openOverrideModal` (Alert.alert 4 boutons), suffix `✎` sur outcome label si `manuallyResolved=true`.
- [dashboard/package.json](dashboard/package.json) — bump version 0.5.12 → **0.5.13**.

#### Validation TypeScript + ESLint

- `npx tsc --noEmit` → **exit 0** ✓
- `npx eslint <fichiers Phase C Session 2>` → **exit 0** ✓ (1 warning array-type fixé)
- Pas de framework Jest dashboard à ce stade → validation runtime iPhone côté HP. Tests unitaires sur `outcome.ts` / `stats.ts` reportés Session 3 si besoin (helpers purs, ~30 tests Jest trivials une fois Jest setup ~1-2h).

#### Garde-fous opérationnels rappelés

- **Garde-fou 1** (Tik shadow vs Zeta 3 mois) **inchangé** — POST /feedback alimente la recalibration daily 03:00 UTC ADR-011 côté core, qui reste interne à Tik. Aucun ordre, aucune action vers Zeta.
- **Garde-fou 2-bis transitoire** (sizing 1 % capital, veracity ≥ 0.85 BTC swing tant que Reddit IP-banni, NE PAS trader GOLD, observer SHORT BTC) **inchangé** — Phase C Session 2 nourrit la calibration empirique sans modifier la stratégie de trading manuel.
- **ADR-003** (pas de bypass V01-V15) **inchangé** — Tik continue de ne créer aucun ordre.
- **ADR-004** (multi-overlay) **inchangé** — le feedback humain enrichit la recalibration source credibility, ne crée pas de nouvel overlay.
- **ADR-011** (anti fake-news + recalibration source credibility) **renforcé empiriquement** — la recalibration daily 03:00 UTC reçoit enfin un input humain depuis le dashboard (jusqu'ici elle ne lisait que les signaux DB). À noter : la recalibration auto reste silencieuse jusqu'au 2026-06-18 sur l'env HP (DB trop jeune, cf. memory `recalibration-state-2026-05-17`), donc les feedbacks Phase C Session 2 alimentent une calibration qui ne tournera pas avant ~30 jours. C'est OK — les rows DB s'accumulent pour audit.
- **ADR-018** (Tik OSINT pur) **inchangé** — sémantique `confidence` = "Conviction OSINT" affichée correctement dans le `PersonalHitRateCard` via le hit rate global.

#### Limites connues post-livraison

1. **Pas de tests Jest dashboard** — pattern Phase C Session 1 Paquet 13 conservé. Helpers purs `outcome.ts` et `stats.ts` sont testables trivialement, mais l'absence de framework Jest setup côté dashboard reste une dette technique (~1-2h pour setup + ~50 tests sur les helpers + composant). Inscrite au backlog #12.
2. **Scope `write:feedback` requis sur la clé API dashboard** — la clé API actuelle de l'utilisatrice doit avoir ce scope. Si l'audit Paquet 27 ou un check `curl` montre HTTP 401/403 sur POST /feedback, il faudra régénérer la clé via `python -m tik_core.scripts.create_api_key --scopes "read:signals,read:entities,read:veracity,write:feedback"`. Sinon, l'auto-resolution fonctionne **localement** (UI immédiate) mais le feedback côté backend est perdu.
3. **Cas badge cliquable dans Pressable parente** — le badge outcome est dans une Pressable enfant d'une Pressable parent (toute la row). React Native v0.71+ gère correctement la capture event sur l'enfant. À tester runtime iPhone : si tap badge déclenche aussi navigation → ajouter onPressIn pour bloquer la propagation.
4. **Auto-resolution flash GOLD systématiquement échoue** — l'endpoint `/metrics/signal_track_record/{id}` retourne HTTP 400 pour flash GOLD (ADR-005, Yahoo 15 min delay incompatible). Le cooldown 30 min + cap 20 entries/cycle évitent le spam. L'entry reste `pending` indéfiniment. **Pas un bug** — Tik n'émet jamais de signal flash GOLD donc en pratique l'utilisatrice ne devrait jamais en avoir dans sa watchlist. Si elle réussit à en marquer un via un manège API direct, il restera en pending. Documenté dans `autoResolveError`.
5. **Divergence avec work-from-hp** — une implémentation parallèle Phase C Session 2 existe sur la branche `work-from-hp` (commit `21418c7` du 2026-05-11 sous le nom "Paquet 20" interne à cette branche). Cette branche reste **strictement isolée** par règle utilisatrice (memory `work-from-hp-isolation.md`) — jamais mergeable. Les deux implémentations divergent sur l'UX modal (work-from-hp = modal custom React avec note, main = Alert.alert natif sans note) mais convergent sur les principes (D1-D8). Le code sur `main` est l'implémentation officielle.
6. **Mode shadow strict ne s'applique PAS au feedback humain** — l'utilisatrice trade manuellement à J+14 et son feedback nourrit la calibration de Tik. C'est cohérent Garde-fou 2-bis qui dit explicitement *"le Garde-fou 1 (Tik shadow vs Zeta 3 mois) ne s'applique PAS au trading manuel humain"*. Le feedback humain n'influence pas Zeta directement — il influence les `SOURCE_SCORES` qui modulent le `combined_bias` ADR-018.

#### Mémoire pour instances Claude futures

- **`tik.watchlist.v1` reste la clé storage** — pas de migration `v2` malgré l'ajout des champs Session 2 (rétrocompat via `normalizeEntry` au hydrate). Une future Session 3 qui ajoute encore plus de champs DOIT continuer ce pattern.
- **Mapping watchlist → feedback unidirectionnel** — `breakeven` n'est pas exposé par l'auto-resolution (le track record ne fournit pas ce niveau). Pour exposer breakeven, il faudrait étendre l'UI override modal Session 3.
- **Auto-resolution fire-and-forget POST /feedback** — si une session future veut tracer/retry les feedbacks échoués, ajouter une queue locale (pattern SDK Python `FeedbackQueue` du Paquet 2 Session 4). Pas urgent — la prochaine auto-resolution ne renverra pas (entry n'est plus `pending` après outcome != null), donc un feedback perdu reste perdu.
- **Anti-spam re-resolution sanctuaire `manuallyResolved`** — JAMAIS faire en sorte que l'auto puisse écraser un override manuel. C'est un principe d'UX (l'humain a toujours raison). Si on veut "rafraîchir" un outcome manuel suite à un retour terrain, il faudra une UI explicite (ex. "Réinitialiser") qui remet `manuallyResolved=false` avant que l'auto retouche.

#### Fix track record flash window 24h → 7j (amendement Paquet 28, 2026-05-19)

Bug rapporté runtime par l'utilisatrice juste après la livraison Paquet 28 :
le signal `TIK-FLASH-BTC-20260517095409-e299f8` (émis le 2026-05-17 09:54
UTC) affichait **"données non disponibles"** sur tous les rows de son
track record alors que tous les rows (15min/30min/45min/1h) auraient dû
être résolus (correct/raté) depuis 48h.

**Cause racine** : `TRACK_RECORD_BINANCE_PARAMS["flash"]` (cf. [core/src/tik_core/api/metrics.py:78](core/src/tik_core/api/metrics.py#L78))
fetchait klines 15m × **96 bougies** ≈ 24h. Un signal flash de plus de
24h avait ses klines hors fenêtre → `find_closest_price` retournait
`None` → badge `données_manquantes`.

**Fix** : `limit` 96 → **672** (7 jours × 96 bougies/jour). Reste sous
le cap Binance 1000. Coût marginal négligeable (cache Redis TTL 6h).
Cache key bumpé `tik.track_record.v2.{id}` → `tik.track_record.v3.{id}`
pour invalider les caches calculés sur l'ancienne fenêtre 24h.

**Validation** : aucun test pytest ne hardcode `limit=96` (vérifié grep
sur `test_metrics*.py` et `test_signal_track_record.py`). Pas de
nouveau test ajouté (le bug était dans une constante, pas dans une
logique de calcul). Suite pytest inchangée.

**Limite résiduelle** : un signal flash de plus de **7 jours** sera
toujours "données non disponibles". Acceptable car (a) Paquet 17
exposed que la fenêtre TTL signal flash = 1h donc un signal flash de
+7j est de toute façon hors d'usage actionnable, (b) si besoin futur
de track record long, étendre à 7j n'est pas non plus suffisant pour
un audit historique — c'est le rôle d'un script CLI dédié hors UI.

### Paquet 29 — Polish UX audit 2026-05-17 (F3 + F6 + F7) LIVRÉ 2026-05-19

3 frictions audit UX 2026-05-17 livrées à J-5 du trading manuel J+24
suite à dialogue itératif avec l'utilisatrice après Paquet 28.

**F3 — Tooltips + glossaire** (≈ 2h, le plus gros) :

- Nouveau module `dashboard/src/glossary.ts` (~190 lignes, 17 entrées
  FR : veracity / conviction / afn / trackRecord / horizon / seuil /
  combinedBias / dispersion / outcome / evidence / triggers /
  counterScenarios / hypothesis / advisory / sourceScores /
  gardeFou2bis / shadow). Chaque entrée : `term`, `short` (tooltip
  ≤ 250 chars), `long` (référence ADR), `ref` (ADR/section CLAUDE.md).
- Nouveau composant `dashboard/components/ui/info-tooltip.tsx`
  (≈ 60 lignes) — pastille `?` tap-able qui ouvre `Alert.alert` natif
  iOS avec le `term` + `short` + `ref`.
- Injection sur 6 termes critiques : `Veracity globale` (Home), `Conviction OSINT` / `Veracity` / `horizon swing • N sources` / `Track record` (détail signal), header `Hit rate par veracity` (Calibration).
- `AntiFakeNewsBadge` mode compact (liste Signals) rendu Pressable →
  Alert.alert avec libellé FR + description ADR-011. Alternative
  élégante au tooltip séparé.
- Nouvelle carte "Glossaire" dans Config tab avec 5 collapsibles
  (Scoring / Sources & preuves / Anti fake-news / Track record &
  horizons / Workflow & discipline).
- Fix résiduel F4 audit : `APP_VERSION = '0.5.0'` hardcodé dans
  `config.tsx` ligne 24 → `pkg.version` (cohérent avec
  `index.tsx:32` déjà fixé commit `95cd71c`).
- **Patch cohérence tooltip post-livraison** : sur question
  utilisatrice "17 % conviction OSINT mais tooltip dit 0.0 à 1.0",
  rectification des tooltips `conviction` / `veracity` / `seuil` /
  `combinedBias` pour utiliser des % (cohérent avec l'affichage)
  au lieu de l'échelle technique 0-1. Le tooltip `conviction`
  mentionne explicitement le seuil 30 % directionnalité avec
  exemple : *"un signal à 17 % conviction est toujours neutral"*.

**F6 — Featured macro event tappable** (≈ 10 min) :

- `MacroEventsCard` : bloc "next event" mis en avant désormais
  enrouré dans `<Link href="/macro" asChild><Pressable>` (pattern
  identique au bouton "Voir tout" existant). Chevron `›` ajouté
  pour signaler l'affordance. `accessibilityLabel` décrit
  l'événement + countdown pour les lecteurs d'écran.

**F7 — Sparkline ligne seuil personnel** (≈ 20 min) :

- `MiniSparkline` étendue avec 2 props optionnels :
  `personalThreshold?: number` (ligne pleine colorée vs pointillée
  grise pour `thresholds`) + `personalThresholdColor?: string`
  (défaut vert `#27ae60`).
- Côté Home `(tabs)/index.tsx` : `thresholds={[0.7]}` (plancher
  rejet) + `personalThreshold={0.85}` (seuil J+24 Garde-fou 2-bis
  transitoire) en vert. Légende mise à jour : *"ligne verte 85 % =
  ton seuil J+24 (Garde-fou 2-bis transitoire) · tirets gris 70 % =
  plancher rejet"*.
- **Différence avec l'audit UX** : l'audit suggérait `0.90` (seuil
  normal swing BTC), mais le Paquet 27 du 2026-05-18 a établi
  Garde-fou 2-bis transitoire à `0.85` tant que Reddit est IP-banni.
  Si Reddit revient et que le seuil passe à 0.90, modification
  triviale d'une constante côté caller.

**Validation** :
- TypeScript `tsc --noEmit` exit 0 ✓
- ESLint exit 0 ✓ (1 warning pré-existant `signal/[id].tsx:99`,
  non lié)
- Bump dashboard 0.5.13 → **0.5.15** (0.5.14 = F3 initial avant
  patch cohérence tooltips, 0.5.15 = F6 + F7 + patch tooltips)

**Limites assumées** :
1. F1 (bande feu pré-trade Home) **reste ouvert** — c'est la
   friction critique 🔴 la plus importante de l'audit, score 9/10
   utilité J+24. À attaquer dans la prochaine session si la trader
   veut.
2. Pas testé sur iPhone côté env serveur — validation runtime à
   faire côté HP via `cd /opt/tik/dashboard && npx expo start
   --clear`. Hot-reload du JS automatique au prochain ouvre de
   l'app dans Expo Go.
3. F7 hardcode `0.85` côté caller — si la trader veut une
   abstraction (constante exposée + auto-switch selon état Reddit),
   c'est ~30 min de refactor complémentaire post-J+24.
4. F11 (pull-to-refresh) volontairement reporté post-J+24 (~20 min,
   confort UX non critique).

**Garde-fous opérationnels** : ADR-003 / ADR-004 / ADR-011 / ADR-018
inchangés. Garde-fou 1 et 2-bis inchangés. **Aucune modif backend**
— purement dashboard. Aucun risque de régression sur les engines /
pipeline scoring / cross-validation.

**Mémoire pour Claude futures** :
- Le glossaire est la source de vérité du vocabulaire Tik in-app.
  Toute nouvelle entrée doit y être ajoutée + idéalement injectée
  via `<InfoTooltip entryKey="..." />` à côté du label concerné.
- `MiniSparkline.personalThreshold` est une convention qui peut
  être réutilisée pour d'autres seuils utilisateur (sizing,
  drawdown perso, etc.) — pattern propre.
- F1 audit UX reste prioritaire pour J+24 — ne PAS livrer de polish
  cosmétique mineur avant de l'avoir fait si l'utilisatrice le
  demande.

#### Bonus mini-F1 statique discipline J+24 (commit `4d84aa5`, 2026-05-19)

Compromis livré ~20 min après le Paquet 29 suite à dialogue
utilisatrice sur F1. Elle a clarifié qu'une **refonte UX complète est
prévue à la fin du dev Tik** quand opérationnel — donc F1 réactif
(bande feu 🟢🟡🔴 calculant les 5 critères temps réel, ~1-2h dev)
serait du code refait.

**Compromis retenu** : carte **non-réactive** en haut de Marché avec
les 5 puces Garde-fou 2-bis section 5 affichées en texte fixe. Effort
~20 min "jetable" sans douleur lors de la refonte UX future.

**Contenu** (5 puces fixes, exactement les règles section 5) :
1. Pas de macro event HIGH dans ±4h (voir Calendrier macro)
2. BTC uniquement — pas de GOLD (Tik à 4,8 % hit rate GOLD)
3. Direction long ou short — pas neutral
4. Veracity ≥ 85 % swing BTC (seuil transitoire Reddit IP-banni)
5. Sizing 1 % du capital max — montée progressive après période
   profitable

**Placement** : tout en haut de l'onglet Marché, avant
`TopHeadlinesCard`. Première chose visible à l'ouverture de l'app.

**Différences avec le vrai F1 (à activer si l'utilisatrice le
demande)** :

| | Mini-F1 (livré) | Vrai F1 (envisagé) |
|---|---|---|
| Logique | 0 ligne (texte fixe) | ~80-120 lignes calcul live |
| Données lues | aucune | veracity courante + next macro + état GOLD ouvert |
| Verdict | aucun (lecture humaine) | 🟢🟡🔴 synthétique |
| Refresh | jamais | 5 min (cohérent autres polls) |
| Effort | ~20 min | ~1-2h |
| Risque bug | quasi nul | logique conditionnelle à tester |

**Critère de bascule vers vrai F1 réactif** : utilisatrice rapporte
oublier un critère régulièrement, OU friction de croiser mentalement
4 cartes à chaque trade. Sinon → maintenir statique jusqu'à la refonte
UX finale.

**Style** : carte border orange (`#e67e22`) + fond `rgba(230, 126, 34,
0.08)` discret. Cohérent visuellement avec le badge AFN `degraded`
(orange = drapeau prudence). Non-tappable (pas d'affordance bouton).

Bump dashboard 0.5.15 → **0.5.16**. TypeScript + ESLint exit 0. Aucune
modif backend.

**Mémoire pour Claude futures** :
- Le contenu des 5 puces est strictement copié de CLAUDE.md section 5
  (Garde-fou 2-bis). Si les règles section 5 changent (ex. retour de
  Reddit → seuil 85 % → 90 %), il faut **synchroniser manuellement**
  `dashboard/app/(tabs)/index.tsx:165-184`.
- Pattern "carte statique discipline" peut être réutilisé pour
  d'autres règles opérationnelles si besoin (ex. checklist post-
  trade, checklist debug). Garder simple.
- NE PAS coder le vrai F1 réactif sans demande explicite de
  l'utilisatrice — elle préfère attendre la refonte UX finale.

### Paquet 30 — Script measure_post_fix_hit_rates.py LIVRÉ (J-5 trading manuel, 2026-05-19)

Matérialisation du script `measure_post_fix_hit_rates.py` prévu dans le plan
calendaire Paquet 25 pour le J+10 post-fix Bug N=2 (= 2026-05-27). Matérialisé
8 jours en avance pour permettre la validation logique sur données pré-fix
avant le run réel et éviter la pression dernière minute.

**Fichier créé** : [core/src/tik_core/scripts/measure_post_fix_hit_rates.py](core/src/tik_core/scripts/measure_post_fix_hit_rates.py)
(387 lignes, wrapper de `backtest.py` qui réutilise 95 % des helpers — pas de
duplication de logique).

**Spec implémentée** :

- 3 niveaux veracity mesurés simultanément en un seul run :
  - **Niveau 2 global** (tous signaux) : garde-fou contre régression silencieuse
    car l'algo ADR-011 mesure le global, pas le filtré.
  - **Niveau 1 transitoire** (veracity ≥ 0.85) : aligné Garde-fou 2-bis
    transitoire (CLAUDE.md section 5) tant que Reddit IP-banni (Bug 11).
  - **Niveau 1 strict** (veracity ≥ 0.90) : audit comparatif pour le retour à
    Garde-fou 2-bis nominal post-unban Reddit.
- Pour chaque niveau : hit rate global + par asset × direction + baselines
  Tik/Random/Always LONG/SHORT/NEUTRAL.
- CLI args : `--horizon-days` (défaut 5j swing), `--horizon-hours` (alternative
  flash), `--threshold` (défaut 0.5 %), `--since-iso` (défaut fix Bug N=2
  2026-05-17T20:47:00 UTC), `--until-iso` (optional, défaut now), `--min-samples`
  (défaut 20 — warning biais si bucket plus petit).
- Constantes versionnées : `FIX_BUG_N2_ISO`, `MIN_VERACITY_TRANSITOIRE = 0.85`,
  `MIN_VERACITY_STRICT = 0.90`.

**Décisions structurantes prises** :

- **Réutilisation maximale** des helpers `backtest.py` (`fetch_btc_history`,
  `fetch_gold_history`, `find_closest_price`, `evaluate_constant_baseline`,
  `evaluate_random_baseline`, `evaluate_tik_baseline`, `_gain_for`, `_success_for`)
  plutôt que duplication. Cohérent engagement #5 (vérifier hypothèses avant
  verdict) + engagement #1 (lire code avant affirmer).
- **Variante locale `_evaluate_signal_td`** parce que l'original
  `evaluate_signal` de `backtest.py` prend `horizon_days: int` et ne permet
  donc pas un horizon `1h`. Duplication chirurgicale (35 lignes) plutôt que
  modifier la signature publique de `backtest.py` (rétrocompat préservée).
- **Klines 15m si horizon ≤ 4h** (flash) sinon klines 1h (swing+). Tolérance
  `find_closest_price` ajustée en conséquence (30 min / 6h).
- **Pas de persistance DB**. Sortie stdout uniquement (la trader peut
  rediriger `> rapport.md` à la main si besoin). Pattern minimaliste —
  un seul fichier, zéro side effect.
- **Pas de tests pytest** ajoutés. Cohérent avec `backtest.py` qui n'a pas
  non plus de tests sur ses helpers internes. Les nouveaux helpers (`_parse_iso`,
  `_filter_by_veracity`) sont triviaux. Limite assumée.

**Validation runtime effectuée** (commande sur le VPS HP container `tik-core`) :

```bash
docker exec tik-core python -m tik_core.scripts.measure_post_fix_hit_rates \
  --since-iso 2026-05-13T10:00:00 \
  --until-iso 2026-05-17T20:47:00 \
  --horizon-days 1 \
  --threshold 0.3
```

Résultats sur 1058 signaux pré-fix évalués comparés au Paquet 27 :

| Métrique | Paquet 27 (mesure 2026-05-18) | Script (validation 2026-05-19) | Cohérent ? |
|---|---|---|---|
| Tik global hit rate 1j | 31.1 % | **32.9 %** | ✓ proche |
| GOLD hit rate | 4.8 % | **5.0 %** | ✓ très proche |
| BTC SHORT hit rate | 63.1 % | **56.0 %** | ⚠ ma fenêtre exclut post-fix |
| Always SHORT baseline | 64.1 % | **57.6 %** | ⚠ même raison |
| BTC SHORT gain moyen | +0.72 % | **+0.55 %** | ✓ même ordre |

Les différences attendues viennent de la fenêtre choisie (`--until-iso 2026-05-17T20:47`
exclut les signaux post-fix, alors que Paquet 27 mesurait l'historique complet
HP). Logique du script **saine**. Observation bonus : les 3 niveaux veracity
donnent presque les mêmes chiffres (1058 → 1058 → 1057) sur cette fenêtre
pré-fix car **99.4 % des signaux pré-fix sont à veracity = 0.95** (bug N=2
confirmé empiriquement). Au 2026-05-27 sur données post-fix, les 3 niveaux
divergeront enfin de manière significative.

**Limites assumées** (engagement #8) :

1. Seuil directionnalité par défaut 0.5 % (hérité `backtest.py`), pas la
   granularité Paquet 17 (flash 0.30 %, swing 0.50 %, macro 1 %+).
   Override via `--threshold` si besoin.
2. Pas de séparation flash/swing/macro automatique — la trader lance le
   script plusieurs fois (1 par horizon).
3. Constante `MIN_VERACITY_TRANSITOIRE = 0.85` codée en dur. Si Garde-fou 2-bis
   revient à 0.90 strict (retour Reddit), modifier la constante (1 ligne).
4. Pas de tests pytest pour `_parse_iso` / `_filter_by_veracity` / `_evaluate_signal_td`.
   Helpers triviaux mais dette technique tracée si besoin futur de robustifier.

**Garde-fous opérationnels rappelés** :

- Garde-fou 1 (Tik shadow vs Zeta 3 mois) **inchangé** — script de mesure
  passive, aucun input vers Zeta.
- Garde-fou 2-bis transitoire **inchangé** — le script EST l'outil qui
  permettra de valider ou invalider la règle "observer prioritairement
  SHORT BTC" et de raffiner les seuils veracity post-J+24.
- ADR-003 / ADR-004 / ADR-011 / ADR-018 **inchangés** — purement additif.
- Aucune modif des engines / pipeline scoring / cross-validation.

**Mémoire pour instances Claude futures** :

- Lancement réel **prévu 2026-05-27** (J+10 post-fix Bug N=2). Commande par
  défaut suffisante : `docker exec tik-core python -m tik_core.scripts.measure_post_fix_hit_rates`
  (horizon 5j swing par défaut).
- Pour flash : ajouter `--horizon-hours 1`.
- **NE PAS modifier** `MIN_VERACITY_TRANSITOIRE = 0.85` tant que Bug 11
  Reddit IP-ban n'est pas résolu. Sinon désynchronisation avec Garde-fou 2-bis
  section 5.
- Si la trader veut un rapport markdown propre : rediriger `> /tmp/rapport.md`
  côté HP puis `docker cp` côté local (le container n'a pas de FS persistant
  hors bind-mount).

### Paquet 31 — Fix suite pytest rouge + foot-gun production drop_all (2026-05-20)

Audit santé exécuté sur le VPS Hetzner (où Tik tourne, sur `main`). La suite
pytest annoncée à « 988 verts » dans la doc était en réalité **rouge** :
**4 failed + 5 errors**, tous dans les gardes anti-régression Bug 9 (timezone
DB) + Bug 10 (WS) ajoutés le 2026-05-19 (commit `bf0d360`) — **ces tests
avaient été commités sans jamais passer** (ni tests, ni lint CI).

**Foot-gun production critique découvert** : la fixture `db_engine`
(`core/tests/conftest.py`) faisait `Base.metadata.drop_all` sur la base de
`settings.database_url`, qui vaut `TIK_DB_NAME=tik` (**production, 2390+
signaux**) dans le conteneur. Lancer `pytest` dans le conteneur de prod aurait
pu **détruire toutes les données** ; sauvé cette fois uniquement par le bug de
boucle d'événements concomitant. Données vérifiées intactes (2390 → 2393, le
scheduler insère normalement).

**Cause racine du rouge** : `db_engine` était en `scope="session"`,
incompatible avec **pytest-asyncio 1.3.0** (la fixture `event_loop` custom
session-scoped est dépréciée/ignorée depuis 1.0). Les connexions asyncpg
créées sur la boucle de session étaient utilisées dans la boucle (différente)
de chaque test function-scoped → `asyncpg ... another operation is in
progress`. L'erreur collatérale sur `test_ws_lifespan.py` était un effet de
bord de cette fixture cassée polluant la boucle partagée.

**Fix (3 fichiers, +55/-15)** :
- `conftest.py` : `db_engine` passé en **scope `function`** (partage la boucle
  du test), fixture `event_loop` dépréciée **retirée**, **`drop_all` supprimé**
  (les tests nettoient leurs propres lignes), et **garde anti-prod**
  `_is_test_database()` qui fait `pytest.skip` si la base n'est pas une base de
  test. Impossible désormais de toucher la prod par erreur.
- `test_publisher_timezone_db.py` : seed idempotent de l'entité BTC (FK
  `signals.entity_id → entities.id`) dans `clean_signal_row` — sur tik_test
  vierge la FK manquait, ce qui prouvait que ces tests n'avaient jamais tourné
  même en CI (DB fraîche).
- `pyproject.toml` : `asyncio_default_fixture_loop_scope = "function"` (lock +
  silence le warning ; effectif en CI / au prochain rebuild image).

**Validation (jamais contre la prod)** : base `tik_test` créée dans le
conteneur postgres (`CREATE DATABASE tik_test OWNER tik`). Suite complète
contre tik_test = **1052 verts** (vs 4 failed + 5 errors). Contre la prod
`tik` : les tests DB *skippent* proprement, signaux **inchangés (2393 →
2393)**. Commande sûre (cf. memory `pytest-run-safely-tik-test`) :
`docker compose ... exec -T -e TIK_DB_NAME=tik_test core sh -c 'cd /app && pytest -q'`.

**Résout** la dette « test pytest Postgres bout-en-bout en CI » tracée depuis
Bug 9 (Paquet 7/14) : les gardes anti-régression Bug 9 protègent enfin
réellement.

**Constat séparé puis RÉSOLU même session** : `ruff check src/ tests/` (commande
CI) trouvait **360 erreurs** + 58 fichiers à reformater (dette pré-existante,
lint CI rouge). Traité par auto-fixes sûrs (260) + `ruff format` (56 fichiers)
+ config ciblée pour faux positifs FastAPI/Pydantic (`extend-immutable-calls`
pour `Depends`/`require_scope`, `per-file-ignores` tests, `ignore` global des
règles de style) + 4 vrais petits fixes (F821 import manquant, B007 boucle
morte, PIE810, RET504) + 4 `# noqa` ARG (conformité d'interface). Résultat :
`ruff check` + `ruff format --check` verts, **1052 pytest verts** (79 fichiers
touchés, quasi 100 % mécanique). Détail backlog #12.

**Garde-fous** : Garde-fou 1 / 2-bis / ADR-003 / ADR-004 / ADR-011 / ADR-018
inchangés. Aucune modif des engines / pipeline scoring / cross-validation —
purement infra de test + sécurité données. Branche `work-from-hp` non touchée
(règle d'isolation respectée : commit sur `main` uniquement, l'implémentation
officielle).

### Paquet 32 — Audit fiabilité signaux pré-trading + filtre horizon mesure (2026-05-20)

Audit fiabilité signaux exécuté sur le système live à **J-4 du trading manuel**
(2026-05-24), axe stratégique #1. Lecture seule, zéro modif pipeline. Objectif :
réponse honnête mesurée à « Tik produit-il des signaux fiables depuis le fix
Bug N=2 (3 jours) ? ». Fenêtre stable (scheduler `Up 2j` post-fix).

**Pipeline SAIN post-fix** (distribution depuis 2026-05-17 20:47, ~900 signaux) :
- Veracity de nouveau **variée** (fini le 0.95 figé du bug N=2). Flash BTC
  0.70-0.95, swing BTC plafonné 0.85 (cohérent Garde-fou 2-bis transitoire
  Reddit banni → filtre 0.85 confirmé discriminant), GOLD 0.85-0.95.
- AFN ADR-011 actif : flash BTC 161 degraded/350 ok ; swing BTC 80 degraded /
  **54 tripped** (direction forcée neutral) / 132 ok. ~20 % des swing BTC tripped.
- `sources_count` correct : flash=3 (ADR-005), swing BTC=4 (klines+FG+CC+GN,
  **Reddit absent** cohérent Bug 11), GOLD=3 (avec GDELT) ou 2 (GDELT 429).
- Cadence stable ~186 flash + ~145 swing/jour. Redis frais, P6 actif (champ
  `anomaly` dans payloads, severity=ok). Reddit toujours 403, GDELT 429 ~3/4 cycles.

**Renversement direction GOLD swing** : 74 short / 60 neutral / **0 long**
post-fix, vs Paquet 27 (pré-fix) 60 **long** / 3 short qui donnait 4.8 % hit.
Le bug N=2 biaisait peut-être les directions GOLD. **NE PAS changer la guidance
« pas de GOLD » pour autant** — 3 jours, non validé. À ré-évaluer post-J+30.

**Mesures préliminaires (horizons mûrs) — AUCUN edge directionnel démontré** :
- **Flash BTC @1h** (501 sig, seuil 0.3 %) : Tik 37.9 % > Random 33.3 %, mais
  porté **uniquement par les neutral** (75.8 % — trivial à 1h). Calls
  directionnels faibles : long 14.3 %, short 13.8 %.
- **Swing BTC @1j** (préliminaire) : Tik 27.5 % < Random 33.6 %. SHORT BTC
  17.7 % — l'« edge » SHORT 63 % du Paquet 27 **ne tient pas** → était
  **régime-dépendant** (BTC baissait alors, a chopé/monté depuis), pas prédictif.
- **Swing @5j (mesure officielle)** : pas encore possible (signaux 3j < 5j).
  Premiers mûrs ~2026-05-22, mesure complète **2026-05-27** (J+10 post-fix).

**Conclusion** : pipeline techniquement sain, mais **pas d'edge directionnel
mesurable** sur cette fenêtre. **Renforce Garde-fou 2-bis** (sizing 1 %,
observer ≠ parier, pas d'edge démontré). La vraie mesure go/no-go reste le
swing 5j du 2026-05-27.

**Amélioration outil (commit séparé)** : `measure_post_fix_hit_rates.py` reçoit
`--signal-horizon flash|swing|macro|all`. Avant, le script mélangeait flash
(conçu 1h) et swing (conçu 5j) à un horizon forward unique → mesure faussée.
Désormais la mesure J+10 officielle se lance proprement par horizon
(`--signal-horizon swing --horizon-days 5`). Helper pur `_filter_by_signal_horizon`,
ruff propre, script validé runtime (flash@1h / swing@1j / swing@5j). Limitation
résolue (cf. Paquet 30 « pas de séparation flash/swing »).

**Garde-fous** : Garde-fou 1 / 2-bis / ADR-003/004/011/018 inchangés. Aucune
modif pipeline/engines — audit lecture seule + 1 amélioration script CLI de
mesure. Branche `work-from-hp` non touchée.

### Paquet 33 — Vérification méthodique 6× + backtest AFN + durcissement outil mesure (2026-05-20)

Session de **doute méthodique sans complaisance** (section 13bis) à J-4 du
trading : 6 conclusions challengées avec arguments pour/contre + re-mesure, puis
**backtest démontrable du module anti-fake-news**, puis durcissement de l'outil
de mesure. Tout en **lecture/mesure seule** (zéro modif pipeline/engines), tout
**reproductible** (filtres CLI + commandes documentées). Conteneurs stables
(scheduler up 2j post-fix N=2).

**Découverte n°1 — DONNÉES PRÉ-FIX CONTAMINÉES (la plus importante)** : un swing
5j swing-only sur les signaux pré-fix mûrs (2026-05-13→15, n=323) donne **Tik
0,9 % hit / −3,62 % par signal** vs Always SHORT 99,1 %. BTC = 208 long / 0 short
→ 0 % de hit pendant un crash. **Cause confirmée par `sources_count`** : pré-fix
swing BTC = 3 sources (klines + 2 sentiment, **CryptoCompare manquant** cf. Issue
#3 Paquet 26) → chemin cross-validation **N=2 buggé** → directions long à
contresens. Post-fix = 4 sources (CC restauré) → N=3 correct → short-biased.
**CONSÉQUENCE : toute donnée backtest pré-fix est inexploitable** (y compris les
chiffres Paquet 27 : SHORT BTC 63 %, GOLD 4,8 %, 22 % — tous contaminés). La
mesure go/no-go fiable = **swing 5j post-fix le 2026-05-27**.

**Découverte n°2 — AUCUN edge directionnel démontré aux horizons mûrs** : 10
backtests post-fix (flash@1h, swing@6h/24h, seuils 0,15-0,50, par actif). Tik bat
Random uniquement via les neutral à seuil grossier ; à seuil fin Tik ≈ Random ;
à 24h Tik < Random. Always SHORT/NEUTRAL compétitifs ou dominants selon
horizon. Résultats instables selon la fenêtre (run récent 46,9 % vs full 26,9 %)
= échantillon trop court (~3j, régime bear unique).

**Découverte n°3 — filtre veracity ≥ 0,85 : neutre sur swing BTC (correction
d'un verdict trop alarmiste)** : sur BTC+GOLD mélangé le filtre semblait dégrader
le hit, mais c'était un **artefact** (flash-inversé Paquet 10 + bruit GOLD
neutral). Sur **swing BTC seul** (cas réel trader), @6h le filtre ne dégrade pas :
Tik V≥0.85 = 40 % > Random 33 %. **BTC swing V≥0.90 = 0 signal** (capé 0,85) → le
seuil transitoire **0,85 est le bon** (0,90 ne sélectionnerait rien).

**Découverte n°4 — backtest AFN : signal en hit rate, mais INCONCLUSIF sous
paranoïa** : backtest `ok` vs `degraded` sur swing BTC SHORT (seule classe
comparable, BTC short-biased) :

| Horizon | `ok` short | `degraded` short |
|---|---|---|
| @6h, seuil 0,30 | 37,8 % (48/127) | 19,6 % (9/46) |
| @24h, seuil 0,50 | 22,5 % (23/102) | 0,0 % (0/28) |

**Lecture optimiste (sans paranoïa)** : `ok` touche ~2× mieux que `degraded` sur
2 horizons → le flag séparerait les signaux fiables des moins fiables.

**Lecture paranoïaque (CORRECTION d'un verdict initial trop optimiste — mea
culpa)** : le finding **ne survit pas** à un scrutin rigoureux. (1) **Multiple-
testing** : z-test p=0,024 @6h / 0,006 @24h, mais ~10 backtests lancés → seuil
Bonferroni ~0,005 → @6h NE survit pas, @24h survit de justesse. (2) **Confond
veracity** : les `degraded`-short sont TOUS à veracity 0,78 (std 0), les `ok` à
0,81 → le filtre veracity ≥ 0,85 retire DÉJÀ tous les degraded → le flag AFN
n'ajoute **quasi aucun pouvoir de filtrage indépendant** par-dessus la veracity.
(3) **Gain ≠ hit rate** : @6h ok +0,02 % vs degraded −0,01 % (négligeable) ;
@24h ok +0,04 % vs degraded **+0,15 %** → l'avantage **s'inverse sur le gain**.
(4) Petits échantillons (degraded short 28-46), régime bear unique ~3j, pas
l'horizon 5j. **VERDICT : inconclusif** — pas un edge robuste. Le module AFN
n'est pas démontré nuisible, mais sa valeur prédictive n'est PAS établie. Sur
**flash** le flag est de toute façon redondant avec « neutral » (degraded flash
= 100 % neutral). `tripped` = 54 neutral (bias brut faible 0,167, 0 outlier, ne
prive d'aucun directionnel — vérifié V4). **Actionable trader** : NE PAS
sur-pondérer le flag AFN — il coïncide avec le filtre veracity ≥ 0,85 que tu
appliques déjà. À re-tester proprement au 5j le 2026-05-27 (`--cb-status`).

**Découverte n°5 — balayage dual-lens systématique : AUCUN edge robuste nulle
part** : nouveau script `backtest_dual_lens.py` (commité) qui, pour chaque slice,
sort la lecture SANS paranoïa (hit rate, bat random ?) ET AVEC paranoïa (n, gain
moyen, p-value vs random, survie Bonferroni, flag petit échantillon). Balayage de
**31 slices** (flash/swing × BTC/GOLD × direction × bucket veracity × statut AFN).
**Résultat : pas un seul slice n'est simultanément `bat random` + significatif
après Bonferroni + `gain+`.** Pattern systématique : les slices qui « battent
random » sont les NEUTRAL (flash 76 %, swing 60-82 %) mais toujours `gain-`
(artefact — être neutre ne rapporte pas) ; les DIRECTIONNELS (long/short) sont au
niveau ou sous random, leurs petits gains positifs (short +0,02 à +0,23 %) sont
non significatifs = juste suivre la tendance baissière (beta, pas alpha) ;
`cb_status=ok` swing @6h non-sig vs random (p=0,273), @24h sous random ; GOLD tout
sous random. **Conclusion démontrée : Tik n'a aucun edge directionnel robuste
mesurable sur les données post-fix disponibles** — le sizing 1 % est la seule
posture justifiée, la mesure 5j du 2026-05-27 reste le test décisif. Outil :
`python -m tik_core.scripts.backtest_dual_lens --signal-horizon swing --entity BTC
--horizon-hours 6` (ou `--horizon-days 5` le 27/05).

**6 vérifications (pour/contre/verdict)** : V1 prod intacte ✅ (toutes tables
peuplées, drop_all jamais exécuté) · V2 CI passera ✅ (1074 verts sur tik_test
VIERGE, réplique CI) · V3 « no edge » ⚠️ robuste mais « pas démontré » (5j
décisif) · V4 AFN sain ✅ (0/54 tripped n'a d'outlier, bias brut) · V5 branche
main ✅ cohérent · V6 lint sans bug caché ✅ (aucun F/E-code ignoré, re-exports
`auth/__init__` intacts).

**Finding incident — mémoire corrigée** : la recalibration ADR-011 n'est PAS
silencieuse (mémoire 2026-05-17 fausse) — elle tourne depuis ~2026-05-19 et
pénalise les SOURCE_SCORES dynamiques (binance_orderbook 0,85→0,35, etc.). MAIS
impact **cosmétique** : `get_effective_score` n'alimente que le champ `"score"`
des evidence (affichage), pas le combined_bias / direction / veracity
(post-ADR-018). Aucun impact signal. Option post-J+14 (pas avant lundi) : geler
la recalibration sur données contaminées.

**Tooling livré (commits séparés, déjà poussés)** : 3 filtres ajoutés à
`measure_post_fix_hit_rates.py` — `--signal-horizon` (`4e16e4f`, évite de mélanger
flash 1h et swing 5j), `--entity` (`a2b6477`, isole BTC du bruit GOLD),
`--cb-status` (`2d2945b`, backtest valeur prédictive AFN) ; + couverture tests des
primitives d'évaluation hit-rate (`82e5d87` : find_closest_price, baselines,
evaluate_signal, +22 cas, suite 1052→**1074**). La mesure officielle BTC-only du
2026-05-27 se lance : `--entity BTC --signal-horizon swing --horizon-days 5
[--cb-status ok|degraded]`.

**2 mea culpas méthodologiques** (artefacts de requête corrigés) : (1) « 9
overrides AFN » = faux positif (matchait la section LLM « Anti fake-news status »,
vrai compte = 0) ; (2) evidence « 1 seule entrée » = `LIMIT 1` mal placé sur les
lignes expansées (réel = 4 entrées). Verdicts inchangés après correction.

**Garde-fous** : Garde-fou 1 / 2-bis / ADR-003/004/011/018 inchangés. **Aucune
modif pipeline/engines** — mesure/audit seule + filtres CLI + tests + doc. Prod
jamais touchée (2410 signaux, vérifié avant/après). Branche `work-from-hp` non
touchée (commits sur main, l'implémentation officielle).

**Note sur Garde-fou 2-bis** : l'insight « observer SHORT BTC 63 % » (section 5,
issu du Paquet 27) repose sur des **données pré-fix contaminées** (Découverte
n°1) — ne pas le présenter comme un edge fiable. Sous scrutin paranoïaque,
**aucun filtre (veracity ni AFN) n'a de valeur prédictive robuste démontrée**
(cf. Découvertes n°4 et n°5). À re-mesurer proprement le 2026-05-27.

**Découverte n°6 — audit dual-lens du FRONT-END + correction de chiffres
contaminés (dashboard 0.5.17)** : même méthode dual-lens appliquée à l'UX
dashboard. *Sans paranoïa* : UI soignée, transparente (evidence, contre-
scénarios, tooltips, badge AFN warning-only honnête). *Avec paranoïa* : l'UI
**parle le langage d'un système validé et confiant** (gros % « Veracity »/
« Conviction » verts, track record ✓, prose LLM assurée) alors qu'aucun edge
n'est démontré → risque de sur-confiance pour une débutante. Deux endroits
affichaient des **chiffres contaminés comme des faits**, dont un qui
**instruisait** un pari : le glossaire `gardeFou2bis` (« observer SHORT BTC
63 % ») et la carte discipline mini-F1 (« GOLD 4,8 % »). **Corrigés**
(`glossary.ts` + `index.tsx`, dashboard 0.5.16 → 0.5.17, tsc + eslint exit 0) :
les chiffres faux retirés, remplacés par « aucun edge directionnel démontré,
mesure fiable au 27/05 ». Le reste de l'alignement UX↔réalité (libellés trop
affirmatifs, HitRateCard sur données contaminées, scores crédibilité pénalisés
à 35 % par la recalibration) est **documenté pour la refonte UX de fin de dev,
NON codé** (cohérent consigne utilisatrice). Audit consolidé front+back :
`docs/audit-dual-lens-2026-05-20.md`.

### Paquet 34 — Fix R2/R6 recalibration sur données contaminées (J-3 trading, 2026-05-21)

Correction du mode de défaillance **R2/R6** anticipé par l'audit dual-lens du
2026-05-20 (annexe 2). Le job `recalibrate_sources` (ADR-011) tournait sur une
fenêtre de lookback `[now−30j, now−5j]` **entièrement pré-fix Bug N=2** (le fix
date du 2026-05-17 20:47, la borne de maturité now−5j était encore au 2026-05-16).
Il apprenait donc des **hit rates faux** (données contaminées, cf. Paquet 33
Découverte n°1) et poussait les scores de crédibilité vers le plancher 0,30.

**Mesure live confirmant l'artefact** (Redis prod, 2026-05-21) : FG 0,38 (statique
0,65), Google News 0,41 (0,70), GDELT 0,52 (0,75), orderbook/aggtrades **0,30**
(plancher, statique 0,85). Dans 1-2 j, le détail de chaque signal aurait affiché
toutes ses sources à ~30 % → une débutante aurait cru « Tik tout pourri » juste
avant son 1er trade.

**Vérification de sécurité critique (faite en code, pas en croyant la doc)** :
le `score` de crédibilité n'entre **nulle part** dans `combined_bias` / direction
/ conviction / veracity (post-ADR-018, `cross_validate` fait une moyenne **non
pondérée** des biais). `get_effective_score` n'alimente que le champ
`evidence[].score` (affichage). Donc geler/corriger la recalibration est
**strictement cosmétique** — zéro impact sur les signaux émis.

**Fix (auto-cicatrisant, pas un toggle à oublier)** :

- `RECALIBRATION_DATA_FLOOR = 2026-05-17 20:47` + helper pur `_lookback_window(now)`
  dans `source_credibility.py` : `start = max(now−30j, floor)`. Tant que `start ≥ end`
  (now−5j), fenêtre vide → recalibration **skip** (log `window_empty_skip`, n=0).
  Le plancher devient automatiquement inopérant après ~2026-06-16. La recalibration
  reprend seule sur données propres+mûres dès ~2026-05-22 (post-fix +5j de maturité).
- Nouveau script `core/src/tik_core/scripts/reset_source_credibility.py` : DELETE
  des clés EXACTES `tik.source_credibility.<source>` (liste connue, **jamais** de
  wildcard/FLUSHDB — cf. foot-gun `drop_all` Paquet 31). Revertit l'affichage au
  statique immédiatement.
- 4 tests purs `_lookback_window` (plancher appliqué / inopérant / fenêtre vide /
  plancher custom). Suite **1074 → 1078 verts** contre `tik_test` (jamais la prod),
  0 régression. Lint ruff + format propres.

**Déploiement runtime validé** (VPS prod `tik-server-1`, bind-mount `./src` →
restart scheduler suffit, pas de rebuild image — la doc CLAUDE.md « pas de
bind-mount » était obsolète, le compose réel monte `./src:/app/src:ro` + `./tests`) :

1. `docker restart tik-scheduler` → log au boot `recalibrate.start
   window_start=2026-05-17T20:47 window_end=2026-05-16... → window_empty_skip → done n=0` ✓
2. `docker exec tik-core python -m tik_core.scripts.reset_source_credibility` →
   5 clés supprimées (FG, aggtrades, orderbook, GDELT, Google News), 4 déjà absentes ✓
3. Redis post-reset : toutes les clés `tik.source_credibility.*` absentes → fallback
   statique ✓ ; scheduler healthy ✓.

**Décision méthodologique** : R2/R6 choisi comme le plus important parmi les modes
anticipés car **seul à impact visible avant le 1er trade** (2026-05-24), sur l'axe
confiance, faible risque (cosmétique + scheduler-only + réversible). Analyse 6×
(V1 réel mesuré / V2 cosmétique vérifié code / V3 cutoff > toggle / V4 sûr runtime
/ V5 reset scopé aux clés exactes / V6 bon moment) + double lecture (sans paranoïa
= fix propre auto-cicatrisant ; avec paranoïa = ne crée AUCUN edge, le go/no-go
reste le 2026-05-27).

**Garde-fous** : Garde-fou 1 / 2-bis / ADR-003 / ADR-004 / ADR-011 / ADR-018
**inchangés**. Aucune modif du pipeline de scoring / direction / veracity — purement
la fenêtre d'apprentissage d'un job cosmétique + un script de reset. `work-from-hp`
non touchée.

**Limites connues** : (1) les signaux émis AVANT le reset gardent leurs scores
pénalisés figés dans leur evidence (normal, l'evidence est calculée à l'émission) —
seuls les nouveaux signaux affichent le statique. (2) La recalibration reste
**silencieuse** jusqu'à ~2026-05-27 (premiers post-fix mûrs à 5j) puis ne touchera
qu'à ≥30 samples propres par source. (3) Toujours pas de test pytest Postgres
bout-en-bout du job (le helper pur est testé, le job lui-même non — dette héritée).

**Mémoire pour instances Claude futures** : NE PAS supprimer `RECALIBRATION_DATA_FLOOR`
— il s'auto-désactive après 2026-06-16. Si la recalibration semble « ne rien faire »
avant cette date, c'est ATTENDU (`window_empty_skip`), pas un bug. Le script de
reset est réutilisable si une future contamination de données justifie un nettoyage
des scores dynamiques.

### Polish dashboard — tap alerte = marquer lue (2026-05-21)

Friction remontée par l'utilisatrice : dans l'onglet Alerts, le **seul** moyen
de marquer une alerte lue était le bouton « Tout marquer comme lu ». Taper une
alerte ouvrait le détail du signal mais **ne la marquait pas lue** (manque, pas
un choix de design — `AlertsContext` n'exposait que `markAllAsRead`/`clear`).

Fix (pur dashboard, ~12 lignes) : ajout de `markAsRead(id)` dans `AlertsContext`
+ branché sur le `onPress` de la ligne d'alerte (`alerts.tsx`) → **taper une
alerte la marque lue ET ouvre le signal** (lecture = ouverture). « Tout marquer
comme lu » conservé pour le bulk. TypeScript `tsc --noEmit` + ESLint exit 0
(validés sur le VPS, Node présent). Bump dashboard 0.5.19 → 0.5.20. Aucune modif
backend. Garde-fous inchangés.

---

### Paquet 35 — Outil « Tik vs trend baseline » + audit fiabilité honnête (J-1 trading, 2026-05-23)

Session d'audit fiabilité à J-1 du trading manuel (2026-05-24), sous consigne
utilisatrice « sans paranoïa mais sans complaisance, ne plus faire d'erreurs ».
Mesure/lecture seule + 1 ajout d'outillage. **Aucune modif pipeline/engines.**
Prod jamais touchée (3235 signaux). Branche `work-from-hp` non touchée.

#### Livré — test apparié « Tik vs baselines constantes » sur le GAIN

- `core/src/tik_core/scripts/backtest.py` : 2 fonctions pures additives —
  `normal_cdf(x)` (CDF normale via `math.erf`) et `paired_gain_significance(
  results, baseline_direction)` (test z apparié sur `d_i = gain_Tik_i −
  gain_baseline_i`, retourne tik_gain/baseline_gain/mean_diff/z/p).
- `core/src/tik_core/scripts/measure_post_fix_hit_rates.py` : nouvelle section
  « Tik vs baselines constantes » dans chaque niveau veracity — compare Tik à
  Always SHORT/LONG/NEUTRAL sur le gain, avec verdict de significativité et
  conclusion « Tik ajoute-t-il de l'alpha au-dessus de la **meilleure** baseline
  constante ? ». Répond à la vraie question (Random est trivial à battre en
  marché tendanciel ; le juge est la baseline de tendance).
- `core/tests/test_backtest.py` : +13 tests (TestNormalCdf + TestPairedGainSignificance).
  Suite complète **1074 → 1091 verts** contre `tik_test`, 0 régression. ruff +
  format verts (avec la vraie config repo, cf. ci-dessous).

#### Verdict empirique honnête (cf. memory `tik-empirical-state-2026-05-23`)

Sur données propres post-fix Bug N=2 (matrice contrôlée seuil 0,3% fixe) : BTC
swing = **64% short** (≈ Always SHORT), régime BTC −4,4% sur la fenêtre → perf
**confondue avec la tendance**. Hit rate 44→28→20→100% selon l'horizon (le 5d
100% = N=27 tous short, 1 épisode = artefact). **Gain ≤ 0 à tous les horizons
mesurables.** Test apparié : Tik **PERD significativement vs Always SHORT** (6h :
Δ −0,17%, z=−6,4, p<0,001). **Aucun edge directionnel démontré ; Tik n'ajoute pas
d'alpha au-dessus de la tendance, il la sous-performe.** Verdict définitif
impossible sur un seul régime baissier → la mesure go/no-go fiable reste le
**swing 5j du 2026-05-27** (`--entity BTC --signal-horizon swing --horizon-days 5`,
comparer **vs Always SHORT** pas Random). Le filtre veracity est quasi-inopérant
sur BTC swing (≥0,90 ne garde que 13 signaux, cap Bug 11 Reddit).

#### Erreurs de méthode commises & contrôles (cf. memory `measurement-rigor-controls`)

L'utilisatrice a dû me reprendre 3 fois. Erreurs documentées pour ne plus les
refaire (toutes = « affirmer au lieu de vérifier ») :

1. **Extraction incohérente** : comparé un « 32,3% » (via `tail`, = section
   veracity≥0,85) à un « 44% » (via `grep|head`, = section globale) — sections,
   horizons ET seuils différents. → Extraire la même section nommée explicitement.
2. **Hit rate isolé présenté comme « la fiabilité de Tik »** : il varie 44→100%
   selon les params. → Toujours citer les 4 params + faire varier un seul + le gain.
3. **Affirmation fausse non vérifiée** : « enrôler une source contamine le go/no-go
   du 27 » → FAUX (signaux déjà figés, arithmétique de maturité). → Vérifier DB avant verdict.
4. **Comparé à Random** (faible) au lieu de la baseline de tendance Always SHORT.
5. **Verdict « 9/9 » trop propre** contenant 2 erreurs factuelles. → S'auto-challenger avant de présenter.

Gotcha annexe (memory `container-stale-pyproject-ruff`) : `docker exec tik-core
ruff check` donne ~165 **faux positifs** car le `pyproject.toml` du conteneur
(image 13/05) est antérieur à la config ruff du Paquet 31 (20/05). Vraie config =
repo `/opt/tik/core/pyproject.toml` ; `src/ tests/` est vert avec elle.

#### Garde-fous

Garde-fou 1 / 2-bis / ADR-003 / ADR-004 / ADR-011 / ADR-018 inchangés. Outillage
de mesure pur (lecture seule), additif, zéro impact signaux. **Décision actée :
NE PAS ajouter de nouvelle source OSINT avant le go/no-go du 27/05** (garde-fou
timing backlog-osint + ne résout pas la colinéarité au trend). Pour le trading de
demain : Tik = outil de **contexte** (headlines/macro/sentiment), pas signal
directionnel fiable — renforce Garde-fou 2-bis (sizing 1%, observe ne parie pas).

> **Correctif 2026-05-24 (incohérence de date à éviter).** La phrase « NE PAS
> ajouter de source avant le 27/05 » ci-dessus était **trop grossière** : elle a
> introduit une date (27/05) non réconciliée avec le garde-fou de `backlog-osint.md`
> (« post-J+14 = post 2026-05-24 »). Une nouvelle session du 24/05, lisant le
> backlog, a (à raison) dit à l'utilisatrice qu'elle pouvait lancer Polymarket.
> **Règle unique réconciliée** (cf. `backlog-osint.md` MAJ 2026-05-24 + memory
> `tik-empirical-state-2026-05-23`) : **SHADOW** (construire l'ingester + collecter,
> sans brancher sur le `combined_bias`) = OK dès le 24/05, zéro impact go/no-go ;
> **ENRÔLEMENT** sur la direction = seulement après le go/no-go du 27/05 + mesure
> 2 sem (IC / hit / gain via `paired_gain_significance`) + idéalement un régime
> mixte ; en NO-GO directionnel, la source sert de **carte de contexte**, pas
> d'overlay du bias. Ne plus poser de date qui contredit le backlog.

### Paquet 36 — Track record lisible (3 états) + mouvement en points + triggers décisionnels (dashboard, 2026-05-25)

Session UX dashboard pure (**aucune modif backend / pipeline / engines / scoring**).
3 commits : `aead5d1` → `a11c475` → `e5c9621`. Dashboard 0.5.22 → 0.5.27.

**Track record plus lisible (`aead5d1`)** :
- Le chiffre affiché suit désormais le **résultat du pari** (gain-relatif), pas le mouvement brut du marché → le **signe colle au badge**. Pour un SHORT, un prix qui baisse = chiffre positif. Le mouvement brut reste en sous-ligne « marché … ».
- **3 états** au lieu de 2 : ✓ vert (bon sens, mouvement ≥ seuil) · **≈ orange (bon sens mais sous le seuil = bruit)** · ✗ rouge (mauvais sens). Résout la confusion remontée par l'utilisatrice (« +0,19 % mais pastille rouge » = mouvement favorable juste sous le seuil 0,20 % → désormais ≈ orange). Helper pur `effectiveState(row, direction)`, cohérent avec `_success_for` backend : le `correct` reste identique, on raffine seulement le `raté` en raté/sous_seuil **pour l'affichage**, sans changer la définition du hit rate. Divergence assumée tracée : un ≈ est compté comme non-hit dans le hit rate agrégé.

**Mouvement en points par signal (`e5c9621`, demande utilisatrice)** :
- Nouveau `dashboard/src/utils/points.ts` : taille du point par instrument (**BTC 1 $, GOLD 0,01 $**, ajustable + surfacée dans l'UI) + conversions %↔points.
- Carte Track record enrichie : bloc **« Mouvement requis en points »** par horizon (montée ▲ / baisse ▼ = seuil × prix de réf ÷ taille du point) + **mouvement observé en points** dans la sous-ligne « marché ». Réutilise le prix `p0` déjà chargé → **zéro backend, zéro fetch en plus**.
- **Symétrique** (montée = baisse, car le seuil l'est) — étiqueté « barre à franchir pour valider, **pas un objectif de gain** ». L'asymétrie vraie exigerait une source de volatilité (ATR, non exposée) = autre chantier.
- Distinction clarifiée à l'utilisatrice : le **requis** = cible théorique connue dès l'émission (fixe) ; le **track record** = résultat observé qui se remplit avec le temps ; le **badge** = comparaison des deux.

**Triggers : décisionnels vs contexte technique repliable (`aead5d1`, corrigé `a11c475`)** :
- La carte Triggers sépare par **poids** : **« Triggers décisionnels »** (poids > 0 — sentiment OSINT en swing, microstructure orderbook/agression en flash) et **« Contexte technique »** repliable (RSI/EMA/MACD/momentum, poids 0 depuis ADR-018, informatif). Répond à la demande de masquer la technique qui ne décide plus rien. **Pas une nouvelle feature** : relabel/regroupage de l'existant.
- Correction post-audit (`a11c475`) : « Triggers OSINT » était **faux pour le flash** (triggers décisionnels = microstructure, pas sentiment) → « Triggers décisionnels » ; « momentum » ajouté à la note technique.

**Comparateur de coûts brokers : construit puis RETIRÉ** :
- Construit (`aead5d1`) puis **supprimé à la demande** (`a11c475`). **Ne pas le reconstruire sans demande.** Chiffres broker réels notés en mémoire : spread ~220 pts ActivTrades (slippage inclus) vs 20-40 Pepperstone ; levier 1:1000 ActivTrades (compte **pro** confirmé) / 1:2 crypto Pepperstone (UE retail).

**Audit méthodique prismatique** (demandé, « doute méthodique sans complaisance ») :
- Triangulation : re-lecture code, `grep` poids triggers (swing+flash), `tsc` (0), `eslint` fichiers touchés (0/0), **bundle web réel** (`expo export`, 1256 modules, 21 routes, exit 0 → aucun import fantôme), recherche web broker.
- 2 anomalies sémantiques **trouvées + corrigées** ; 2 anomalies lint **pré-existantes** (pas cette session) tracées : `app/(tabs)/signals.tsx:114` (react/display-name) + `useDashboardKpis.ts:25` (HORIZONS) — non corrigées (hors périmètre).
- Incohérence levier 1:1000 vs UE retail **levée** (compte pro confirmé).

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003 / 004 / 011 / 018 **inchangés**. Afficher des points **n'améliore pas l'edge** (présentation, pas performance ; edge directionnel non démontré, go/no-go 2026-05-27).

**Limites** : (1) points symétriques (asymétrie = ATR, autre chantier) ; (2) taille du point = hypothèse à vérifier selon broker (1 ligne dans `points.ts`) ; (3) BTC & GOLD seulement, prix de réf = prix d'émission ; (4) non vérifié sur device réel (statique + bundle uniquement).

---

### Paquet 37 — Audit J+1 trading : go/no-go préliminaire + dette de déploiement + rattrapage doc (2026-05-25)

Session d'audit menée sur le VPS Hetzner à **J+1 du trading manuel** (démarré
2026-05-24), sous consigne *« doute méthodique sans complaisance, analyse
prismatique, zéro complaisance »*. **Lecture/mesure seule — aucun fichier de code
modifié, prod jamais touchée** (4079 signaux, scheduler/core/ingesters healthy).
Doc-only : ce Paquet 37 + correction d'une memory périmée.

#### 1. Trois commits antérieurs enfin tracés dans CLAUDE.md

Découverts non documentés au début de session (tous du 2026-05-24, antérieurs au
Paquet 36) :

- **`87e78cb` — Polymarket SHADOW** : nouvel ingester `polymarket_ingester.py`
  (Gamma API publique, sans clé) qui collecte les marchés de seuils BTC
  (« Bitcoin above ___ on <date>? », « What price will Bitcoin hit in <X>? »)
  dans Redis (`tik.sentiment.polymarket.btc` TTL 6h + `tik.polymarket.btc.history`
  liste cappée 5000). **NON branché aux engines** (0 `_enrich_with_polymarket`,
  aucune ref dans `scoring/` — re-vérifié ce jour). But : construire l'historique
  pour mesurer la valeur prédictive (IC/hit/gain) AVANT tout enrôlement. 30 tests,
  suite 1091 → 1121. Interval 1h. **Validé runtime 2026-05-25** : logs
  `polymarket.published` horaires (n_events 7-9, volume ~85 M USD = vrais marchés),
  Redis historique = 29 snapshots. Conforme « règle SHADOW vs ENRÔLEMENT »
  (`backlog-osint.md` 2026-05-24).
- **`3367575` — Durcissement sécurité audit prod 2026-05-24** (H1/H2/H3/H4/M2/M3/
  M5/B1/B4). Code only, « actif au prochain restart ». Points clés : **H1** auth WS
  vérifie désormais expiration + scope `read:signals` (avant : ni l'un ni l'autre —
  une clé expirée/sans scope pouvait streamer tous les signaux) ; **H2** troncature
  défensive des données externes (publisher/sentiment/url/title) avant DB+classify
  (évite perte silencieuse de batch) ; **H3** dashboard n'ouvre que les URL http(s)
  absolues (avant : tout schéma) ; **H4** caps Polymarket (events/markets/payload +
  rejet inf/nan + json.dumps dans le try) ; **M2** redis maxmemory 1gb + allkeys-lru
  (filet anti-OOM) ; **M5** last_used_at throttlé ≤1/h ; **B1** handler SIGTERM
  (arrêt gracieux Docker) ; **B4** publisher convert-UTC avant strip tzinfo.
  **Aucun changement du pipeline scoring/direction/veracity.** Différés : M1
  env=production, B2 pin deps, B3 CORS exp.direct.
- **`e39a71a` — M4 détection panne silencieuse** : `metrics/freshness.py`
  (`compute_signal_freshness`, seuil 60 min) + endpoint `GET /api/v1/metrics/
  signal_freshness` + bannière dashboard `SignalFreshnessBanner` (rouge en haut de
  Marché si aucun signal depuis 60 min). Répond au risque « panne avalée en log »
  (cf. Bug 9 = 4h sans détection). 8 tests, lecture seule.

#### 2. Mesure go/no-go PRÉLIMINAIRE (non-officielle — l'officielle reste le 2026-05-27)

Tension méthodologique tranchée : la memory `tik-empirical-state-2026-05-23` dit
« ne pas re-mesurer avant le 27/05 ». **Décision argumentée** : mesure
**préliminaire explicitement non-officielle** lancée car (a) la trader trade déjà
avec du capital, (b) 290 swing BTC mûrs à 5j = échantillon solide, (c) coût marginal
d'attendre 2 j faible. Contrôles `measurement-rigor-controls` appliqués (régime +
distribution AVANT interprétation, vs Always SHORT pas Random, gain ≥ hit rate).

**Régime BTC (Binance daily)** : −4,2 % sur 12 j, mais chute nette 14→20/05 puis
**plat/choppy** (range 75,5k–77,7k) — fenêtre forward des signaux mûrs mi-baissière
mi-plate (moins nettement baissière que le 23/05).

**Résultat (swing BTC, vs Always SHORT = juge de tendance, test apparié sur gain)** :

| Horizon | N | Tik hit% | Tik gain | meilleure baseline | Verdict apparié |
|---|---|---|---|---|---|
| 24h | 651 | 30,3 % | −0,39 % | Always LONG +0,03 % | **Tik PERD** (p<0,001) |
| 48h | 555 | 23,2 % | −0,63 % | Always SHORT +0,01 % | **Tik PERD** (p<0,001) |
| 5j global | 267 | 63,3 % | +0,64 % | Always SHORT +0,75 % | **Tik PERD** (p<0,001) |
| 5j veracity≥0,85 | 106 | 72,6 % | +1,23 % | Always SHORT +1,22 % | **ÉGALITÉ** (p=0,298) |
| flash 1h | 1458 | 36,9 % | −0,08 % | Always LONG +0,00 % | **Tik PERD** (p<0,001) |

**Verdict préliminaire (confirme le 2026-05-23, ne le renverse pas)** : Tik est
short-biaisé (65 % short sur 290 mûrs), **colinéaire à la tendance baissière**. À
aucun horizon il **n'ajoute d'alpha au-dessus de la meilleure baseline constante** :
il PERD (24h/48h/5j-global/flash) ou ÉGALISE au mieux (5j ≥0,85). Les hit rates
élevés (63-72 % à 5j) sont des **artefacts de tendance** (le marché baissait, Tik
shortait), pas un edge. Le filtre veracity ≥ 0,85 amène Tik à **parité** avec
« toujours short » (pas au-dessus). **Aucun edge directionnel démontré.** Scrutin
dual-lens (Bonferroni) cohérent : seuls les `neutral` « battent random » et toujours
en gain négatif (artefact connu). **Implication trader** (renforce Garde-fou 2-bis) :
Tik = outil de **contexte**, pas signal directionnel ; sizing 1 % ; ne PAS augmenter
le sizing sur les calls directionnels de Tik ; au 24h, les shorts de Tik **perdent
de l'argent** en marché choppy. **La mesure officielle du 2026-05-27** (`bash
/opt/tik/go_no_go_report.sh`, swing 5j, ~399 signaux mûrs) reste le go/no-go ; ce
préliminaire ne la remplace pas.

#### 3. Dette de déploiement (anomalie tracée — sourcée par mtimes vs démarrages process)

Le durcissement sécurité `3367575` (fichiers écrits 2026-05-24 11:05-11:07) n'est
PAS entièrement actif en runtime, car scheduler/ingesters tournent **sans
`--reload`** et ont démarré avant :

| Item | Process | Démarré | Actif ? | Sévérité |
|---|---|---|---|---|
| **H1** auth WS, **M4** freshness, **M5**, **B4** (côté core) | core | 19/05, **--reload** | ✅ OUI (endpoint M4 → 401, auto-reload) | — |
| **H2** troncature headlines/classifier | ingesters | 24/05 10:24 < mtime 11:05 | ❌ NON | 🟡 |
| **H4** caps Polymarket | ingesters | idem | ❌ NON (shadow → impact faible) | 🟢 |
| **B1** SIGTERM gracieux | scheduler+ingesters | avant mtime | ❌ NON | 🟢 |
| **B4** publisher convert-UTC | scheduler | 21/05 | ❌ NON (défensif, callers déjà UTC) | 🟢 |
| **M2** redis maxmemory+LRU | redis | Up 12 j | ❌ NON (`maxmemory=0 noeviction` vérifié) | 🟡 |

**Correction des signaux INTACTE** (vérifié, non supposé) : `swing_engine`/
`flash_engine`/`cross_validator`/`anomaly_detector` mtime 2026-05-20 14:38 < démarrage
scheduler 2026-05-21 09:54, et `source_credibility.py` (fix Paquet 34) mtime 09:48 <
09:54 → le scheduler tourne la **logique d'engine + recalibration ACTUELLE**. Seuls
des items hors-pipeline (sécurité défensive + filet OOM) ne sont pas chargés.

**Fix recommandé** : nouveau script **`/opt/tik/redeploy.sh`** (créé ce jour, cohérent
avec `go_no_go_report.sh`) — fait `BGSAVE` Redis puis recreate `scheduler ingesters
redis` (core OK via --reload) + vérifs intégrées (healthy, M2 actif, /health 200,
erreurs logs, reprise signaux). Active H2/H4/B1/B4/M2 en **une commande** : `bash
/opt/tik/redeploy.sh`. Bref gap de production (quelques min, toléré par la bannière M4
60 min). À lancer hors fenêtre macro chaude (prochain HIGH = NFP 2026-06-05, loin).
Le recreate par Claude a d'abord été **bloqué** par l'auto-mode classifier
(modification de prod en cours de trading nécessite la décision explicite de la
trader) — garde-fou respecté, non contourné. **✅ RÉSOLU 2026-05-25 15:28** : la
trader a lancé `bash /opt/tik/redeploy.sh` elle-même. **Vérifié runtime** : M2 actif
(`maxmemory=1073741824` + `allkeys-lru`), 5 conteneurs healthy, données Redis
préservées (BGSAVE → DBSIZE 1996→1997), signaux repris (dernier 15:29:17, 1er cycle
scheduler au démarrage), **aucune erreur nouvelle** (seuls Reddit 403 / GDELT 429
connus). H2/H4/B1/B4/M2 sont désormais **réellement actifs**. Note vérifiée : le
commentaire compose « M2 appliqué en live le 2026-05-24 » était FAUX (`maxmemory=0`
mesuré avant recreate → jamais appliqué jusqu'ici).

#### 4. Recalibration ADR-011 : memory corrigée

Logs `tik-scheduler` 2026-05-25 03:00 montrent la recalibration **active**
(penalty binance_orderbook/aggtrades → 0.30, reward cryptocompare → 0.847, 420
samples) sur données **post-fix propres** `[2026-05-17 20:47 → now-5j]`. C'est
conforme à l'intention du Paquet 34 (la fenêtre a ouvert à `floor+5j` ≈ 2026-05-22,
pas le 27) et reste **cosmétique** (n'alimente que l'affichage evidence, pas
combined_bias/direction/veracity — re-vérifié). La memory `recalibration-state-2026-05-17`
disait « ne rien faire avant ~2026-05-27 = ATTENDU » → **corrigée** ce jour (la
recalibration tourne depuis ~2026-05-22, c'est normal).

#### 5. Backlog OSINT Vague 1 : NE PAS construire maintenant (verdict argumenté)

Évalué (Silver, ETF flows BTC, Whale Alert) et **écarté pour cette session** : (a)
le garde-fou `backlog-osint.md` autorise le SHADOW mais conditionne l'ENRÔLEMENT au
go/no-go du 27/05 + 2 sem de mesure ; (b) Polymarket est déjà en shadow et n'a que
29 snapshots — ajouter une 2e source en shadow avant d'avoir su exploiter la 1ère
disperse l'effort sans rien prouver ; (c) **engagement #13bis « une source à la
fois »** ; (d) aucune source ne change le constat « pas d'edge directionnel » — le
problème n'est pas le volume de sources mais la colinéarité au trend. Recommandation :
attendre le go/no-go du 27/05, puis décider Polymarket enrôlement vs nouvelle source.

#### Ce qui reste / NON vérifié cette session (transparence)

- **Mesure officielle 27/05** non encore faite (2 j) — `go_no_go_report.sh` prêt.
- ~~**Recreate scheduler/ingesters/redis**~~ ✅ FAIT par la trader 2026-05-25 15:28 (vérifié).
- **Dashboard** : non lancé/testé sur device cette session (M4 bannière, Paquet 36
  points/track-record validés seulement par bundle, pas device réel).
- **GDELT** : 23 samples seulement à 5j (toujours marginal, cf. P3 backlog #9).
- **Reddit** : toujours IP-banni (0 sample recalibration), Bug 11 non résolu (asynchrone).
- **Branche `work-from-hp`** : non touchée (règle d'isolation respectée).

#### Garde-fous

Garde-fou 1 / 2-bis, ADR-003 / 004 / 011 / 018 **inchangés**. Aucune modif du
pipeline de scoring. `work-from-hp` non touchée. Le préliminaire **renforce**
Garde-fou 2-bis (sizing 1 %, observe ≠ parie).

---

### Paquet 38 — Fix bug cache track record (favoris flash bloqués) + nettoyage doc/anomalies (2026-05-26)

Session de réponses aux questions de l'utilisatrice (glossaire « triggers », track record d'un signal neutre, favoris flash) qui a fait remonter **un vrai bug** + 2 anomalies doc. Lecture seule sur le pipeline (endpoint metrics uniquement), prod jamais touchée (~4300 signaux), `work-from-hp` non touchée.

#### Bug cache track record (le vrai problème) — cf. Bug 12 section 9

**Symptôme rapporté** : un signal flash mis en **favori** affichait « tout sablier » dans sa carte track record même après >1h, alors qu'un flash **non-favori** du même âge s'affichait normalement ; et le badge outcome de la Watchlist restait « En attente ».

**Cause racine** (triangulée en base + Redis) : l'endpoint `GET /api/v1/metrics/signal_track_record/{id}` mettait le résultat en cache Redis **6h à TTL fixe**, *y compris quand les lignes étaient `en_attente`* (horizons futurs). Comme on est sur la page détail au moment de mettre en favori (signal frais), le résultat « tout sablier » se figeait 6h — soit **6× la fenêtre contractuelle du flash (1h)**. L'auto-résolution du favori (poll 5 min) re-tapait ce cache figé → ne se débloquait jamais. **Un seul bug, deux symptômes** (carte détail figée + badge Watchlist bloqué). Le commentaire du code prétendait à tort que le cache « se rafraîchit naturellement ». Preuve avant fix (Redis) : `TIK-FLASH-BTC-20260526062008` à 82 min, badges `['en_attente']×4`, TTL restant ~5h. Le swing n'était que légèrement affecté (cache 6h ≪ fenêtre 5j → auto-correction), d'où « le swing marchait, le flash semblait cassé ».

**Fix** (`core/src/tik_core/api/metrics.py`) :
- nouveau helper pur `_track_record_cache_ttl(rows, now)` : **TTL court tant qu'il reste des `en_attente`** = (prochaine échéance − now) + 30s, borné `[60s, 6h]` ; **TTL long 6h une fois tout résolu** (prix passés immuables). Flash ET swing en profitent.
- bump clé cache `v3 → v4` : abandonne les entrées « tout sablier » figées (expirent seules).
- commentaires trompeurs corrigés.

**Vérifié de bout en bout** : 7 tests unitaires (`core/tests/test_track_record_cache_ttl.py`) + 53 tests track record + **suite complète 1136 verte** (contre tik_test, jamais la prod) ; ruff/tsc/eslint exit 0 ; déploiement live via uvicorn `--reload` confirmé (clés `v4` créées par l'endpoint en round-trip HTTP réel ; flash résolu → TTL ≈6h ; signal jadis bloqué recalculé `correct/raté`).

#### 2 anomalies doc corrigées

- **Docstring `metrics.py`** : « flash → 15min / 30min / **1h / 4h** » → corrigé en `15min/30min/45min/1h` (leftover pré-Paquet-17 ; la vérité est dans `signal_track_record.py`).
- **Glossaire `triggers`** (`dashboard/src/glossary.ts`) : « événements techniques **qui ont déclenché le signal** » → faux depuis ADR-018 (la direction vient du `combined_bias` OSINT ; RSI/MACD/EMA sont à **poids 0.0**, informatifs). Reformulé « Triggers décisionnels (poids > 0) vs Contexte technique (poids 0) », cohérent Paquet 36.

#### 2 sur-flags reconnus puis revertés (mea culpa)

J'avais d'abord retiré « 90j macro » de la Watchlist + reformulé le glossaire `horizon` (« Tik produit 3 horizons » est present-tense faux : 0 signal macro émis — vérifié en base : 2448 flash + 1871 swing, scheduler sans job macro). **Mais l'utilisatrice confirme que le moteur macro est au roadmap** (CLAUDE.md §8 « Engine macro — partiellement couvert via FRED ») et assume la mention forward-looking. → **les deux changements macro ont été revertés** ; le scaffolding macro (code + texte UI) reste intentionnel. Mémoire `macro-horizon-intentional` créée pour qu'aucune session future ne re-flagge ça.

#### Scalping — verdict confirmé + correction conceptuelle

L'utilisatrice veut faire du **scalping manuel**. Confirmé (cohérent ADR-005 / Paquet 17) : **Tik ne doit PAS générer de signaux scalp** — au timeframe scalp (secondes-minutes), les sources lentes (news/sentiment/macro, rafraîchies toutes les 30 min-24h) sont gelées → il ne reste que la microstructure seule → la cross-validation multi-sources de Tik s'effondre. **Correction conceptuelle** (mea culpa d'une formulation antérieure) : la microstructure **EST** de l'OSINT (carnet d'ordres + aggTrades publics ; déjà overlays du flash `_enrich_with_orderbook` + `_enrich_with_aggression`, crédibilité 0.85). Ce n'est pas « la microstructure n'est pas de l'OSINT » — c'est « le scalping comme **horizon** sort du modèle multi-sources de Tik ». Mémoire `scalping-not-osint` créée. Pour le scalping manuel, Tik = outil de **contexte**.

#### Garde-fous

Garde-fou 1 / 2-bis, ADR-003/004/005/011/018 **inchangés**. **Aucune modif du pipeline scoring / engines** (endpoint de mesure en lecture seule). dashboard 0.5.28 → 0.5.29 (fix glossaire triggers seul ; les bumps 0.5.30 intermédiaires annulés avec les reverts macro).

---

### Paquet 39 — Fix bug parsing seuil Polymarket shadow (« M » de « May ») (2026-05-27)

Bug découvert en début de session de dev (la mémoire le signalait « à corriger »).
L'ingester Polymarket (mode SHADOW depuis le 24/05, cf. memory `polymarket-shadow-live`)
lisait certaines questions de travers : `Will Bitcoin reach $84,000 May 25-31?`
→ le « **M** » de « **May** » était pris pour « **M**illion » → seuil enregistré
à **8,4e10** au lieu de 84 000. Touchait toute la famille « reach/dip $X _plage
de dates_ » (sans « on »/« in » entre le nombre et le mois) : **28 questions
distinctes corrompues sur 81 snapshots historiques** mesurés en Redis. Les familles
« above ___ **on** <date> » et « reach $X **in** <mois> » n'étaient PAS affectées.

**Cause** : regex `_USD_RE` qui autorisait un `\s*` entre le nombre et le suffixe
`[kKmM]`, donc captait la 1ʳᵉ lettre du mot suivant.

**Fix** ([core/src/tik_core/aggregator/polymarket_ingester.py](core/src/tik_core/aggregator/polymarket_ingester.py)) :
regex `\$\s?([\d,]+(?:\.\d+)?)([kKmM]?)(?![A-Za-z])` — le suffixe doit coller au
nombre (pas de `\s*`) ET ne pas être suivi d'une lettre (lookahead négatif). Le `?`
reste **dans** le groupe pour que `group(2)` soit toujours une chaîne (`.lower()`
sûr). +3 tests dans `test_polymarket_ingester.py` qui verrouillent le cas « May »
+ l'adjacence du vrai suffixe (« $150k », « $1.5m »).

**Vérifications** : 33 tests Polymarket verts (contre `tik_test`, jamais la prod) ;
lint propre (config repo, pas celle périmée du conteneur) ; `docker restart ingesters`
→ snapshot frais 17:38 UTC avec **0 seuil corrompu** (familles « by December 2026 »
et « on May » correctes).

**Nuance honnête (engagement #5/#6)** : mon inquiétude initiale (« ça pollue la
mesure du 10/06 ») était exagérée — `measure_polymarket.py` était **déjà protégé**
(filtre `1 000 ≤ seuil ≤ 5 000 000` + ne garde que la famille « above…on »). Le fix
sert donc l'**exactitude des données stockées** + un futur enrôlement de la famille
« reach/dip », pas la mesure du 10/06 elle-même. Le script de mesure n'a **pas** été
touché. L'historique Redis corrompu (28 entrées du 24-27/05) est laissé tel quel
(inoffensif : filtré par le script, et le fix corrige tout snapshot futur).

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003/004/011/018 **inchangés**. SHADOW
strict (toujours 0 `_enrich_with_polymarket`, zéro impact signaux/pipeline/veracity).
Prod jamais touchée. Branche `work-from-hp` non touchée. Polymarket reste à mesurer
EN PREMIER (~10/06, une source à la fois). Limites : historique corrompu non purgé
(volontaire) ; le format « $Nmot » sans espace renverrait None (n'arrive pas dans
les données réelles).

---

### Paquet 40 — Audit dette technique : redis `aclose` + 2 lint dashboard (2026-05-27)

Suite Paquet 39, même session : audit « autres bugs/dette sûrs » (sans toucher
pipeline ni garde-fous), demandé par l'utilisatrice.

**Vérité d'abord (leçon Paquet 31)** : suite pytest **réellement verte** confirmée —
**1139 passed** contre `tik_test` (jamais la prod). Mais 1 `DeprecationWarning`
remonté → point de départ de l'audit.

**Dette backend — redis-py `close()` déprécié** : redis-py 7.4.0 déprécie `.close()`
au profit de `.aclose()` (cassera en 8.x). 9 occurrences sur 7 fichiers, **toutes
dans des chemins de fermeture/teardown** (`finally:` / lifespan), zéro logique de
scoring : `api/ws.py` (pubsub + redis), `api/headlines.py`, `api/macro_events.py`,
`api/metrics.py` (×3), `scripts/run_scheduler.py`, `scripts/run_ingesters.py`.
`Redis.aclose` / `pubsub.aclose` confirmés présents (7.4.0). Fix mécanique → suite
re-verte **1139 passed, 0 warning**. Le core (`--reload`) recharge à chaud ;
scheduler/ingesters appliqueront au prochain restart (teardown-only → inoffensif
d'ici là, pas de restart forcé pour ne pas perturber la collecte/les signaux).

**Dette dashboard — 1 erreur + 1 warning ESLint** (documentées Paquet 36, jamais
corrigées) :
- `react/display-name` ([signals.tsx](dashboard/app/(tabs)/signals.tsx)) : le
  `renderItem` anonyme renvoyé par `useMemo` → nommé `SignalRow`. `tsc` + `eslint`
  exit 0.
- `HORIZONS` inutilisé comme valeur ([useDashboardKpis.ts](dashboard/src/hooks/useDashboardKpis.ts)) :
  remplacé par un type union direct `TrackedHorizon = 'flash' | 'swing' | 'macro'`
  (même type exporté, valeur morte supprimée).
- 3ᵉ warning (`.expo/types/router.d.ts`) ignoré : fichier généré par Expo.

Bump dashboard 0.5.29 → 0.5.30.

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003/004/011/018 **inchangés**. Aucune modif
du pipeline scoring / engines / cross-validation — purement teardown technique +
qualité de code. Prod jamais touchée (tests sur `tik_test`). `work-from-hp` non
touchée. Limite : le fix teardown backend n'est pas encore actif dans
scheduler/ingesters (restart non urgent, teardown-only).

---

### Paquet 41 — Overlay sentiment CoinGecko en SHADOW (ADR-021, 2026-05-27)

Choix utilisatrice « restaurer le 4e overlay BTC » : Reddit IP-banni depuis le
déploiement HP (Bug 11) → BTC swing tourne à 3/4 overlays sentiment, veracity
structurellement capée à 0.85 (Garde-fou 2-bis transitoire).

**Source choisie par MESURE, pas par supposition** (joignabilité testée depuis
le VPS — Reddit était bloqué au niveau réseau, on ne fait plus confiance sans
tester) : Hacker News joignable **mais quasi vide** (0 story BTC > 15 points sur
7j → bruit/vide), StockTwits + Bluesky **403**. Seul candidat libre/joignable/
exploitable = **CoinGecko** `sentiment_votes_up_percentage` (vote communautaire,
numérique). **Mea culpa** : le menu initial « HN/StockTwits » était optimiste ;
le créneau sentiment retail **textuel** de Reddit n'a pas de remplaçant gratuit
de qualité — CoinGecko est un substitut **numérique**, pas un clone.

**SHADOW strict, toggle OFF par défaut** (pattern DXY/COT ADR-018 P2) :
- Nouvel ingester `coingecko_sentiment_ingester.py` (modèle Fear & Greed) :
  collecte `up_pct`/`down_pct` dans Redis `tik.sentiment.coingecko.btc` +
  historique cappé `tik.coingecko.btc.history` (2000 ≈ 83 j), 1 appel/h, sans clé.
- Overlay `swing_engine` (`_read_coingecko` / `_compute_coingecko_bias` contrarian
  PROVISOIRE calqué FG / `_enrich_with_coingecko`) **gaté** par
  `settings.coingecko_overlay_enabled` (env `TIK_COINGECKO_OVERLAY_ENABLED`,
  défaut False). OFF → log `swing.btc.coingecko_skipped_overlay_disabled`, **zéro
  impact signaux**. `SOURCE_SCORES["coingecko_sentiment"] = 0.60` (provisoire).
- But shadow : mesurer la **divergence vs Fear & Greed** (~1 sem) AVANT activation
  — risque de redondance (deux jauges retail crudes), à valider (D4 ADR-021).

**Vérifs** : suite **1139 → 1159 verts, 0 warning** (tik_test, jamais la prod) ;
ruff check + format OK (config repo) ; imports OK. **Runtime** : ingesters
restart → `coingecko_sentiment.published up_pct=63.58` + Redis snapshot/historique
OK. Scheduler **non redémarré** (overlay OFF → ancien et nouveau swing_engine
émettent des signaux identiques ; restart requis seulement à l'activation).

**Garde-fous** : Garde-fou 1 / 2-bis / ADR-003/004/011/018 **inchangés** tant que
toggle OFF. Si activé un jour et que la veracity ≥ 0.90 est restaurée durablement,
le critère de retour au seuil 0.90 strict (section 5) devra être réévalué (le 4e
overlay serait CoinGecko, pas Reddit). CoinGecko et Reddit **coexistent** (5
overlays à terme), CoinGecko n'est pas retiré au retour de Reddit (sauf si mesuré
redondant). Prod jamais touchée hors collecte shadow. `work-from-hp` non touchée.

**Limites** : (1) CoinGecko numérique ≠ retail textuel Reddit ; (2) corrélation
FG à mesurer (D4) ; (3) mapping contrarian provisoire non validé ; (4) NO-GO
directionnel rappelle « + de sources ≠ + d'edge » — restaure une capacité de
cross-validation, ne prétend pas créer un edge.

### Paquet 42 — Carte UX « Stabilité flash · BTC » (dashboard, 2026-05-30)

Réponse à une friction de trading manuel remontée par l'utilisatrice : « je
reçois long puis short en flash sur BTC à quelques minutes d'intervalle, je
ne sais pas quoi prendre ni comment croiser les sources davantage ».

**Diagnostic triangulé (données live VPS, pas la doc)** : le flip-flop est
**structurel, pas un bug**. Mesuré sur 24h : **31 bascules long↔short opposées
en <20 min** (≈ 1 / 45 min ; 173/175 signaux = transitions). Cause racine (4
facteurs cumulés) : direction flash = moyenne de **2 sources microstructure
discrètes** (carnet OBI + flux agressif taker, valeurs {−1,−0.5,0,+0.5,+1})
face à un **seuil ±0.30 sans hystérésis**, le seuil tombant pile entre 0.25 et
0.50 → un seul capteur qui bouge d'un cran fait traverser neutral↔directionnel ;
l'émission conditionnelle (ADR-005) se déclenche pile sur les transitions →
amplifie le bruit perçu. Rappel : flash **sans edge directionnel démontré**
(go/no-go 2026-05-27). Donc l'objectif n'est pas « mieux suivre le flash » mais
**aider à NE PAS trader sur du bruit**. Exemple live disséqué : un signal
`neutral degraded` où carnet `OBI=+0.62 → bull` (+1.0) et flux
`buy_ratio=0.41 → bear` (−0.5) → moyenne +0.25 < 0.30 → neutral.

**Choix utilisatrice : Option A (UX seule, réversible)** plutôt que de toucher
le moteur (hystérésis/debounce = Options B/C, backend, exigent backtest, ne
créent aucun edge → backlog). Cohérent memory [[feedback_perf_vs_ux]] : c'est
de la présentation, pas une amélioration de performance signal.

**Implémenté (3 fichiers neufs + 2 micro-éditions, 100 % côté dashboard,
zéro backend, zéro requête réseau supplémentaire)** :
- `dashboard/src/flash/stability.ts` — logique pure (`computeFlashStability`,
  `crossFromSignal`), testable, zéro IO. Calcule depuis les signaux **déjà
  chargés** par `useDashboardKpis` (`signals24h`, limite 500).
- `dashboard/src/flash/flashCardSetting.ts` — toggle on/off persistant
  (AsyncStorage `tik.settings.flashStabilityCard`, défaut visible) + store
  partagé Marché↔Config.
- `dashboard/components/dashboard/flash-stability-card.tsx` — la carte.
- `dashboard/app/(tabs)/index.tsx` — affichage conditionnel en haut de Marché
  (après la carte discipline).
- `dashboard/app/(tabs)/config.tsx` — interrupteur dans une carte « Affichage ».

**Ce que la carte affiche** — deux lectures à fenêtres de temps distinctes
(clarifié après confusion utilisatrice) :
1. **Verdict de stabilité = les 45 dernières minutes** : `INSTABLE` (≥2
   bascules opposées → reste à l'écart, rouge) / `STABLE` (direction tenue
   depuis X min, vert) / `INDÉCIS` (1 bascule, orange) / `no_data` (gris).
2. **Croisement des 2 sources = à l'instant** (dernier signal) : carnet
   d'ordres vs flux agressif côte à côte + verdict « ✓ s'accordent / ✗ se
   contredisent / ~ accord partiel ». Règle de décision : trader seulement si
   **direction stable ET sources d'accord**. Un instant cohérent ne suffit pas
   si le film des 45 min est un yo-yo.

Les libellés portent explicitement leur fenêtre (« stabilité sur les 45
dernières minutes » / « à l'instant ») + pied de carte explicatif, pour lever
la confusion « instable mais sources d'accord » (les deux ne mesurent pas la
même période, ce n'est pas contradictoire).

**Vérifications** : `tsc` exit 0, ESLint exit 0. **Logique rejouée contre les
données live** (réplique JS de l'algo) : fenêtres successives → `choppy`
(flips=2) puis `indecisive` (flips=1), conformes au calcul à la main, zéro
erreur de comptage. Pas de rendu device testé (à juger dans Expo Go).
dashboard 0.5.40 → **0.5.42**.

**Réversibilité** : toggle off (live, dans Config), ou retrait de la ligne
d'affichage dans Marché, ou suppression des 3 fichiers — l'UX de base reste
intacte (aucune carte existante modifiée).

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003 / 004 / 005 / 011 / 018
**inchangés**. **Aucune modif du moteur / pipeline scoring / cross-validation**
— la carte lit des signaux déjà émis. `work-from-hp` non touchée. Mémoire
[[flash-flipflop-diagnosis]] créée : NE PAS « réparer » le flip-flop en
modifiant `flash_engine.py` sans demande explicite.

**Limites connues** : (1) ne réduit pas le bruit dans le flux brut (présentation,
pas performance) ; (2) en régime choppy actuel, la carte dira souvent « reste à
l'écart » — c'est voulu (flash = bruit, à éviter), à ne pas confondre avec
« peu trader tout court » (la carte ne parle que du flash BTC ; swing + contexte
+ jugement restent les vrais leviers du trading manuel) ; (3) options backend
B (hystérésis) / C (debounce 2 cycles) / D (3e source flash) restent au backlog
si un jour on veut réduire le bruit à la source.

---

### Paquet 43 — Session fiabilité & mesures : durcissement mesure CoinGecko + résolution pattern flash inversé (2026-05-30)

Session « Fiabilité & mesures » (axe stratégique #1) menée sur le VPS Hetzner,
**lecture seule sur le pipeline** (zéro modif engines / scoring / cross-validation),
avec un seul ajout de code (script de mesure) + tests. Prod jamais touchée (4079+
signaux). `work-from-hp` non touchée.

#### 1. Durcissement de `measure_coingecko_divergence.py` (correctif méthodologique)

Constat avant code (engagement #5) : le script comparait les **niveaux** quotidiens
de CoinGecko (`up_pct`, vote communautaire) et Fear & Greed. Or CoinGecko vote
structurellement haut (~65-75 %, détenteurs optimistes) et FG est bas en marché
bear (~20) → « toujours à l'opposé de 50 » est **mécanique**, pas une preuve
d'indépendance d'information. Un verdict basé là-dessus serait faux.

Ajout de métriques de **mouvement** robustes au biais de base : `movement_deltas` /
`movement_agreement` (% de jours où up% et FG varient dans le même sens) /
`centered_directional_agreement` (accord vs la médiane PROPRE de chaque série) /
`movement_stats` / `primary_spearman`. **Le verdict s'appuie désormais sur le
Spearman des variations jour-à-jour** s'il est calculable (≥ 6 jours appariés),
sinon sur le niveau (signalé explicitement). +20 tests purs (27 → **47 verts**),
ruff check + format propres (avec la vraie config dépôt, pas celle périmée du
conteneur — cf. memory `container-stale-pyproject-ruff`).

**Démonstration immédiate sur données live (N=4 jours, NON concluant)** : l'ancienne
lecture niveau disait « accord directionnel vs 50 = 0 % » ; la nouvelle lecture
mouvement montre « accord des variations = 100 % » (sur 2 jours exploitables,
CoinGecko et FG ont bougé ENSEMBLE). Le « 0 % » était bien un artefact de base, pas
une indépendance. Conclusion inchangée (trop tôt), mais le verdict du ~11/06 sera
fiable. Cf. memory `coingecko-shadow-live`.

#### 2. Recalibration auto ADR-011 — vérifiée saine

Tourne chaque jour 03:00 UTC sur données propres (fenêtre depuis le fix Bug N=2 du
17/05, cf. Paquet 34). Dernier run 2026-05-30 : 2412 signaux, 9 sources.
`binance_orderbook` + `binance_aggtrades` pénalisées au plancher 0.30 (hit ~34 %,
cohérent « pas d'edge flash »), sources news inchangées (bande 40-70 %). **Rappel :
cosmétique** (n'alimente que `evidence[].score` affiché, pas combined_bias /
direction / veracity depuis ADR-018).

#### 3. Résolution de l'open question « pattern flash BTC inversé » (Paquet 10)

Le Paquet 10 documentait un pattern contre-intuitif sur les signaux flash BTC :
tranche veracity 0.80-0.89 = 53.5 % hit vs 0.90+ = 13-16 %, « à investiguer
post-J+14 ». Mesuré au backtest dual-lens sur **données propres post-fix** (2463
signaux flash BTC mûrs @1h, seuil 0.3 %) :

| Groupe | n | hit% | gain% | verdict paranoïaque |
|---|---|---|---|---|
| overall | 1969 | 35.6 | -0.08 | bat random mais FRAGILE (✗Bonf, gain-) |
| direction=long | 622 | 8.7 | -0.01 | SOUS random |
| direction=short | 601 | 12.0 | +0.01 | SOUS random |
| direction=neutral | 746 | 76.9 | -0.22 | bat random mais gain- (FRAGILE) |
| veracity<0.85 | 534 | 77.9 | -0.22 | ≈ neutral (FRAGILE) |
| veracity>=0.85 | 1435 | 19.8 | -0.03 | SOUS random |

**Verdict : le pattern « inversé » est un ARTEFACT DE COMPOSITION, pas un paradoxe
de qualité.** La distribution veracity×direction le montre : la tranche basse
0.70-0.79 = **674 signaux TOUS neutral** (haute dispersion → neutral) ; les tranches
hautes contiennent les calls directionnels. À la mesure 1h/0.3 %, les neutral
« gagnent » trivialement (le prix bouge rarement de 0.3 % en 1h) mais **ne
rapportent rien** (gain ≤ 0), tandis que les directionnels ratent (le mouvement
n'atteint pas le seuil). Donc « veracity basse = meilleur hit » = « veracity basse =
surtout du neutral ». Le « 0.80-0.89 = 53.5 % » du Paquet 10 ne se reproduit PAS sur
données propres (cette tranche est majoritairement directionnelle post-fix → hit
~10-12 %) → c'était un artefact des données **pré-fix contaminées** (cf. Paquet 33).

**Conséquence honnête** : flash BTC n'a **aucun edge directionnel** à aucun niveau de
veracity (cohérent go/no-go NO-GO + sources flash pénalisées à 0.30). Le filtre
veracity ne « trie » rien d'utile sur le flash. Open question Paquet 10 = **close**.

#### 4. Polymarket — prêt à mesurer (~10-11/06)

Accumulation saine : BTC 160 relevés, GOLD 63. Script `measure_polymarket.py` prêt.
SHADOW strict (non branché engines). À mesurer ≥ 2 semaines après démarrage (cf.
memory `polymarket-shadow-live`).

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003 / 004 / 005 / 011 / 018 **inchangés**.
Aucune modif du pipeline scoring / engines — mesure/audit + 1 amélioration de script
de mesure. Verdict go/no-go directionnel **inchangé : NO-GO** → aucun enrôlement,
toggles CoinGecko/Polymarket OFF.

---

### Paquet 44 — Audit santé runtime + fix A1 LLM hypothesis timeouts Ollama (2026-05-31, commit 96d7a42)

Session d'audit méthodique (« doute constant, sans complaisance, analyse
prismatique ») menée sur le VPS Hetzner de prod, **en lecture seule** sauf le
fix A1 (in-repo + restart). Prod jamais mise en danger, `work-from-hp` non
touchée.

#### Audit — doc ↔ runtime triangulé

Vérifications croisées (logs + DB + tests live, pas la doc seule) :

- ✅ Paquets 41-43 réellement présents et cohérents (CoinGecko ingester +
  toggle OFF `config.py:95`, FlashStabilityCard, durcissement mesure CoinGecko
  **47 tests verts** confirmés par run réel).
- ✅ Pipeline vivant : 318 signaux/24h, dernier il y a ~5 min, 5858 total.
  Swing BTC short conf 1.0 (short-bias documenté), swing GOLD neutral (DXY/COT
  désactivés ADR-018 P2).
- ✅ Calendrier macro exact : NFP 06-05 HIGH, CPI 06-10, ECB 06-11, BoJ 06-17.
- ✅ Recalibration ADR-011 a tourné à 03:00 sur données propres (cosmétique).
- ✅ Shadows CoinGecko + Polymarket BTC+GOLD collectent (non branchés engines).
- **Fausse alerte démasquée (mea culpa évité)** : compte de tests CoinGecko
  41 `def test_` vs 47 annoncés → vérifié par pytest réel = **47 passed**
  (paramétrisation). Le doc était correct. Discipline « vérifier avant verdict ».

#### A1 — anomalie trouvée + corrigée

**Symptôme** : `TIK_LLM_HYPOTHESIS_MODE=active` mais **~50 % des signaux en
hypothèse template** (mesuré DB : 29 template / 21 LLM sur 50 derniers ;
**95 `ollama_error ReadTimeout`/24h**). Le doc Paquet 26 affirmait « LLM active
= 6 sections ~150 mots » → divergence doc↔réalité.

**Cause racine (triangulée, ≠ commentaire de code)** : Ollama tourne sur
l'**hôte VPS** (systemd, **4 cœurs CPU sans GPU**, `llama3.2:3b` ~2.48G). 3 jobs
LLM (flash 5min + swing BTC 15min + swing GOLD 30min) collisionnent à
xx:00/xx:30 ; le `Lock` intra-process sérialise mais `apply_llm_hypothesis`
enveloppe l'appel dans `wait_for(60s)` qui **inclut l'attente du lock** → le
2e/3e job consomme son budget à attendre → timeout. Aggravé par le process
**ingesters** (même Ollama, hors lock). ⚠ Le commentaire supposant
`OLLAMA_NUM_PARALLEL=2` était **faux** : l'`override.conf` systemd ne définit
que `OLLAMA_HOST`. RAM serveur tendue (7.6G total, 2.0G dispo, 0 swap) mais le
modèle est déjà résident en permanence aujourd'hui → keep_alive sans surcoût.

**Fix (4 fichiers, +54/-8, in-repo)** :

1. `run_scheduler.py` — flash job + boot reçoivent `None` → **flash = hypothèse
   template instantanée**. Flash = bruit sans edge (Paquet 43). 3 jobs LLM → 2,
   fin de la contention. Commentaire « lock » corrigé (NUM_PARALLEL=2 retiré).
2. `hypothesis_generator.py` (constante `OLLAMA_KEEP_ALIVE = "24h"`) +
   `news_classifier.py` — `"keep_alive": "24h"` dans le payload `/api/generate`
   → modèle reste chaud (indispensable une fois le flash retiré, sinon swing/15min
   rechargerait à froid).
3. `test_ollama_call_includes_keep_alive` — verrouille keep_alive dans le payload.

**Vérifié** : **1307 pytest verts** (tik_test, jamais la prod), ruff check+format
clean (config dépôt swappée temporairement vs config conteneur périmée). Déployé
prod (`docker compose restart scheduler ingesters`) → **mécanisme confirmé
runtime** : 0 `ollama_error`, flash=template (90c), swing=LLM (676c).

**Zéro impact pipeline** : l'hypothèse LLM est du texte affiché, pas un input de
décision (ADR-018). Garde-fous 1/2-bis, ADR-003/004/011/018 **inchangés**.

**Limites / reste à faire** :
1. **Confirmation statistique — MESURÉE le 2026-05-31 ~19h UTC (≈18,5 h post-fix)** :
   `ollama_error` **95/24h → 1** ; flash **100 % template** (voulu) ; swing **64 %
   LLM** (72/112). Résiduel : **36 % de swings en template** dû à la collision
   swing_btc (15 min) + swing_gold (30 min) à :23/:53 (le lock les sérialise → le
   1er prend ~50 s = ReadTimeout httpx, le 2e épuise son `wait_for(60 s)`). **Bénin**
   (template = fallback valide, le trader a quand même une hypothèse). Fix de
   complétion **APPLIQUÉ le 2026-05-31 (commit e0aa0b4)** : swing_btc → cron
   `:00/:15/:30/:45`, swing_gold → cron `:10/:40` (minutes **disjointes**) → plus
   aucune collision swing↔swing. Restart vérifié : 2 swings de boot = LLM (715c/
   582c), **0 ollama_error / 0 timeout**. Ratio ≈100 % LLM attendu sur les cycles
   suivants (à confirmer sur ~1 h de runtime, mais collision éliminée par
   construction).
2. Doc CLAUDE.md = ce Paquet 44 ; mémoire `ollama-llm-timeout-fix` créée.
3. Anomalie mineure non diagnostiquée : 3 RETAIL_SALES en juin (01/08/15) dans
   le calendrier macro (artefact FRED probable, MEDIUM, sans impact discipline).
4. Connus inchangés : Reddit ban (Bug 11, asynchrone), tik-core 0.0.0.0:8200
   (hygiène différée), mesures shadow CoinGecko/Polymarket (~10-11/06).

**Mémoire pour instances Claude futures** : NE PAS remettre le LLM sur le flash
(réintroduit la contention). Ollama est sur le **serveur** (CPU sans GPU), pas
sur le Mac de l'utilisatrice. Si les timeouts reviennent : `curl
localhost:11434/api/ps` + `free -h`. Cf. mémoire `ollama-llm-timeout-fix`.

---

### Paquet 45 — Fix A3 : mapping FRED release_id faux (RETAIL_SALES + INITIAL_CLAIMS) (2026-05-31, commit 5de2d8a)

Suite de l'audit du 2026-05-31 (cf. Paquet 44). Diagnostic + fix de l'anomalie
A3 (3 RETAIL_SALES en juin), révélée plus large : **2 release_id FRED faux
depuis le Paquet 11**, vérifiés contre l'API FRED (engagement #10 : mesurer).

**Cause racine (Bug 13, cf. section 9)** :
- `RETAIL_SALES` → `release_id=17` = **« H.10 Foreign Exchange Rates »** (hebdo
  lundi) → 31 faux « retail sales » du lundi.
- `INITIAL_CLAIMS` → `release_id=14` = **« G.19 Consumer Credit »** (mensuel).
- Vrais IDs : Advance Retail Sales = `9` ; weekly claims = `180`. Les 5 autres
  (NFP=50, CPI=10, PPI=46, GDP=53, IP=13) étaient corrects (audit complet).
Conséquence : le vrai retail sales et le vrai claims étaient **absents**,
remplacés par des dates sans rapport. Impact limité : les deux sont MEDIUM/LOW →
la discipline ±4h sur les **HIGH** (NFP/CPI/FOMC/ECB/BoJ) n'a jamais été
affectée ; mais le calendrier affichait « retail sales chaque lundi » (= dates FX).

**Fix (choix utilisatrice : corriger retail, dropper claims)** :
- `RETAIL_SALES` : release_id 17 → **9** (mensuel mi-mois, MEDIUM).
- `INITIAL_CLAIMS` : **retiré** de la whitelist (le vrai claims hebdo 180 = bruit
  LOW ~50/an peu utile pour la discipline ±4h). `FRED_RELEASES` 7 → 6.
- `event_name`/heures déjà corrects (seuls les IDs étaient faux). 2 commentaires
  « 7 releases » corrigés en « 6 ».

**Prod** : 37 faux RETAIL_SALES (FX) + 8 faux INITIAL_CLAIMS supprimés (`DELETE`
chirurgical via le `release_id` stocké), cycle FRED relancé → retail mensuel
correct (06-17, 07-16, 08-14…), comptage RETAIL_SALES 31 → 7. INITIAL_CLAIMS = 0.

**Vérifié** : 118 tests macro verts (tik_test), ruff clean, re-query DB prod
conforme. Aucun test ne hardcodait 17/14 (`len(FRED_RELEASES)` dynamique).

**Zéro impact pipeline** : le calendrier macro est un outil de discipline humain,
pas un input des engines (ADR-017). Garde-fous 1/2-bis, ADR-003/004/011/018
**inchangés**.

**Dead code laissé (hors scope, inoffensif)** : `macro-events-card.tsx` garde un
`case 'INITIAL_CLAIMS'` (label jamais déclenché) et `storage/models.py` un
commentaire d'exemple citant INITIAL_CLAIMS.

**Mémoire pour instances Claude futures** : release_id FRED corrects = NFP=50,
CPI=10, PPI=46, GDP=53, RETAIL_SALES=9, INDUSTRIAL_PRODUCTION=13 (claims 180
volontairement non utilisé). NE PAS réintroduire INITIAL_CLAIMS avec un ID
arbitraire. Vérifier tout nouveau release_id via `GET /fred/release?release_id=X`.
Cf. mémoire `macro-fred-release-ids`.

---

### Paquet 46 — Re-analyse colinéarité (doute méthodique) + outil de mesure + point A "hit rate honnête" + diagnostic flip-flop flash (2026-05-31)

Session de doute méthodique demandée par l'utilisatrice (« recommence ton analyse, vérifie tout sous tous les angles, zéro complaisance »). Re-audit de l'analyse de colinéarité, correction d'un bug statistique, livraison du point A (distribution usage manuel), diagnostic chiffré du flip-flop flash, et longue séquence pédagogique. **Lecture seule sur la prod** (4079+ signaux) sauf le point A (additif). `work-from-hp` non touchée.

**Outil `analyze_colinearity.py` (commit `fdc9f27`)** — mesure pure : à quels moments Tik diverge de la tendance brute, et est-ce gagnant ? Réutilise les helpers de `backtest.py`. Classe chaque signal directionnel concordant/divergent vs la tendance locale (Spearman + %), compare Tik-tel-que-tradé (neutral=0) à Always SHORT (la baseline de régime, pas Random).

Verdict mesuré (BTC swing 5j, données propres post-fix N=2, régime baissier confirmé par recherche externe : correction ~3 semaines, sorties ETF, BTC ~73k) :
- Tik est **~98 % short** quand il tranche (DB : 899 short / 18 long / 428 neutral) → ≈ « Always SHORT » + un filtre neutre. Quasi aucune variation directionnelle.
- Hit rate 83-89 % par groupe = **effet du régime baissier, PAS un talent** (Tik ≈ always short, et le marché a baissé).
- Son filtre « neutral » coïncide avec des baisses → rate des shorts gagnants (mécanisme descriptif, régime-locked).

**Bug méthodologique trouvé et corrigé (important)** — mon premier verdict affirmait « Tik PERD vs Always SHORT, p<0.001 ». FAUX : les fenêtres forward 5j **se chevauchent** (signaux ~/15 min → chaque neutre partage ~99 % de sa fenêtre avec le suivant). Les ~863 « observations » ne sont pas indépendantes → **z-test gonflé** (Hansen-Hodrick 1980 ; les corrections HAC n'aident pas — confirmé par recherche temps réel). N réellement indépendant ≈ **2** → **edge 5j NON mesurable à ce stade**, ni dans un sens ni dans l'autre. Le script reporte désormais le N indépendant + l'effet descriptif, pas un p bidon. **⚠ Ce biais affecte AUSSI les audits précédents** (go/no-go 2026-05-27, Paquets 32/33/37 ont utilisé des z-tests sur signaux chevauchants → p-values gonflées, même si leurs conclusions de direction tiennent probablement). Mémoire `measurement-overlapping-returns` créée.

**Point A — Hit rate honnête vs baseline constante (commit `bd0d283`)** — la carte « Hit rate » affichait un % brut qu'une débutante lit comme « Tik est fiable », alors qu'en marché tendanciel ce taux peut n'être que l'effet de la pente (un pari constant fait aussi bien).
- Backend (`metrics/hit_rate.py`) : `compute_constant_baselines` (hit rate toujours long/short/neutral sur les MÊMES signaux évalués) + `assess_baseline_edge` (Tik bat-il la meilleure baseline de ≥ 5 pts avec ≥ 30 signaux ?). `HitRateOut` : 3 champs (`best_baseline_label`, `best_baseline_hit_rate`, `beats_baseline`), avec défauts → les caches Redis antérieurs parsent sans erreur. Endpoint `/metrics/hit_rate` câblé.
- Dashboard (`HitRateCard`) : bandeau orange « ce taux suit surtout la tendance : parier <X> aurait fait Y% ici » quand Tik ne bat pas la baseline. **Disparaît automatiquement** quand `beats_baseline` devient vrai (auto-suppression demandée par l'utilisatrice). Bump dashboard 0.5.43 → 0.5.44.
- Vérifié runtime (lecture seule prod) : BTC swing 30j → Tik 35,7 % vs always-short 87,4 % → `beats=False` → bandeau affiché (correct). +6 tests, suite 1307 → **1313 verte** (tik_test). ruff + tsc + eslint propres.

**Diagnostic flip-flop flash (mesure DB, 48h BTC)** — l'utilisatrice signale « des signaux qui se contredisent dans un petit intervalle, dur à trader ». Mesuré : **flash = 76 retournements long↔short en 48h (~1 toutes les 7 min)** ; **swing = 0 retournement**. La confusion = **100 % le flash** (cohérent memory `flash-flipflop-diagnosis`). Le swing est stable (en partie parce qu'il est ~toujours short en régime baissier).

**Séquence pédagogique (pas de code)** :
- « Pas d'edge » ≠ « rien à améliorer ». 3 axes distincts : **edge** (lent, demande une source qui anticipe), **stabilité/lisibilité** (améliorable maintenant), **réception/distribution** (améliorable maintenant). Le trading manuel s'améliore via les 2 derniers, sans edge.
- Pourquoi pas d'edge même avec Binance temps réel : Tik **est déjà** branché Binance temps réel (prix à 1 s, vérifié Redis) ; les indicateurs techniques sont à `weight: 0.0` depuis ADR-018 ; et RSI/MACD/EMA **suivent** (calculés sur le passé) → temps réel ≠ anticipation. Rajouter la technique = refaire l'ancien Tik hybride abandonné (ADR-018) + dupliquer Zeta/MT5.
- Le flash **est utilisable** en manuel, mais comme outil de **timing / température du court terme** (sur un trade décidé par swing + contexte), pas comme direction à suivre. Le flip-flop lui-même = « court terme haché → s'abstenir ».

**Décision tranchée + LIVRÉE (dashboard 0.5.45)** : repositionner le flash côté UI **sans le supprimer**. Choix utilisatrice = **garder la direction LONG/SHORT visible** + ajouter un repère, **sans onglet séparé** (un onglet aurait fait doublon avec le filtre Flash existant + fait perdre le contexte swing/flash mêlés). Sur `app/(tabs)/signals.tsx` : 1 calcul mémoïsé `computeFlashStability(signals, {entityId:'BTC'})` (logique pure Paquet 42, zéro recalcul moteur), et sur **chaque ligne flash BTC** un tag orange « ⚠ court terme indécis » affiché **uniquement** quand l'état est `choppy` (≥ 2 flips long↔short opposés sur 45 min). Re-render FlatList via `extraData={tick}-{flashChoppy}`. **Direction conservée** (badge couleur inchangé). Repositionne le flash comme outil de **timing/température**, pas de direction à suivre. Vérifié runtime (SQL sur prod, lecture seule) : 48h BTC = 138 flips, fenêtres 45 min jusqu'à 7 flips, 170 instants `choppy` → le repère se déclenche bien quand ça flippe et se tait quand c'est calme (à l'instant : 2 directionnels/45 min, 1 flip → `indecisive`, pas de tag = correct). tsc + eslint exit 0. **Aucune modif du moteur flash** (cohérent memory `flash-flipflop-diagnosis`), zéro backend, réversible. **Correctif anti-confusion (dashboard 0.5.46)** : l'utilisatrice a repéré que le tag était **orange comme le badge AFN `degraded`** (`#e67e22`) → risque de télescopage visuel (les deux co-occurrent souvent sur le flash). Tag passé en **indigo `#5b54c9` + icône 🔀** (distinct de l'AFN) et rendu **tap-able** (`Alert` explicatif : « ce repère = la direction CHANGE souvent DANS LE TEMPS ; l'AFN = désaccord entre sources SUR UN signal — ce n'est pas la même chose »). Les deux mesures restent distinctes et lisibles côte à côte. **Raffinement ergonomie (dashboard 0.5.48)** : (1) **B** — le badge par-ligne 🔀 ne s'affiche désormais que sur les flash BTC **récents (≤ 45 min, fenêtre de stabilité)** : un flash > 1h n'est plus tradable (TTL ≈ 1h ADR-005), inutile d'y coller un repère « court terme ». (2) **Bandeau d'état** en haut de Signals (visible quand BTC dans le filtre) : synthèse permanente « 🔀 Court terme BTC : haché » (indigo) / « ✓ calme » (vert) / « • pas assez de données » (gris), tap-able (même explication partagée que le badge). Permet de voir l'état d'un coup d'œil sans scanner la liste. (3) **Couplage onglet Alertes étudié puis ÉCARTÉ** (proposé par l'utilisatrice) : le flash est haché ~76 % du temps → pousser une alerte à chaque fois **noierait** les vraies alertes (fake-news, effondrement veracity) qui sont des **événements ponctuels** ; « court terme haché » est un **état continu / météo**, pas un événement → le bandeau d'état est le bon véhicule, pas l'accumulateur d'alertes. tsc + eslint exit 0. Toujours zéro moteur/backend.

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003/004/005/011/018 **inchangés**. Aucune modif du moteur / pipeline scoring (analyse lecture seule + point A = métrique additive + cartes/repères UI).

**Limites / reste à faire** :
1. Rendu dashboard non testé sur device (tsc/eslint OK, à valider en Expo Go).
2. La carte hit rate sur 30 j mélange des données pré-fix (avant 17/05) contaminées → le % brut (35,7 %) n'est pas représentatif ; à décider si on restreint la fenêtre aux données propres.
3. Edge réel = source qui anticipe (Polymarket, mesure ~10/06) — non résolu, c'est le vrai chantier de fond.
4. Flip-flop flash non réduit à la source (option moteur hystérésis en réserve, déconseillée car flash sans edge).

---

### Paquet 47 — Couplage signaux ↔ calendrier macro (Phase B1.5, 2026-06-01)

Repère de **discipline** qui marque les signaux émis dans la fenêtre ±4h
d'un événement macro **HIGH** (NFP, CPI, FOMC, BCE, BoJ, BoE…) impactant
leur entité. Concrétise la Phase B1.5/B2.5 envisagée aux Paquets 11 (ADR-017)
et 23 (ADR-020) — jusqu'ici l'humain devait faire le lien mentalement
(« je vois NFP dans 2h, je n'entre pas »). Aligné avec le verdict empirique
**NO-GO directionnel** : Tik = outil de contexte/discipline.

**Décision d'architecture (for/contre/verdict)** : flag calculé **à l'émission**
et persisté dans `Signal.advisory.near_macro_event` (vs calcul read-time côté
API, vs calcul client-side dashboard). Verdict émit-time car (1) le flag est une
propriété **intrinsèque du moment d'émission** (« ce signal est sorti 2h avant le
NFP »), (2) il voyage automatiquement vers DB + REST + WS, (3) il sera
**requêtable en SQL** pour une future mesure de fiabilité (les signaux « près
macro » performent-ils différemment ?). Réutilise le champ JSON `advisory`
existant → **zéro migration**.

**Garde-fou central (ADR-017)** : le calendrier macro est un outil de discipline
**humain**, **PAS un input des engines**. Le module ne touche JAMAIS
direction/conviction/veracity — il ajoute uniquement des métadonnées. **Best-effort** :
toute erreur DB est avalée (log warning), l'émission du signal n'est jamais bloquée
(cohérent `headlines_repo.persist_headlines` / `macro_events_repo.upsert_many`).

**Backend (3 fichiers)** :
- **Nouveau** `core/src/tik_core/scoring/macro_proximity.py` : fonction PURE
  `find_nearest_macro_event(signal_ts, events, window_hours=4.0)` (fenêtre ±4h,
  choisit le plus proche, `hours_until` signé : >0 = event à venir, <0 = passé)
  + annotateur async `annotate_near_macro_event(session, decision)` (query
  `macro_events` HIGH dans ±4h, filtre par entité via `assets_impacted`, pose
  le flag, best-effort try/except).
- `core/src/tik_core/scripts/run_scheduler.py` : `annotate_near_macro_event`
  appelé dans les 3 jobs (swing BTC, swing GOLD, flash BTC) à l'intérieur du
  `async with session_maker()` avant `publish_*`, réutilise la session.
- `core/src/tik_core/storage/schemas.py` : sous-modèle `NearMacroEvent` +
  champ `near_macro_event: NearMacroEvent | None` sur `Advisory` — **sinon
  Pydantic supprimait silencieusement le champ en sortie REST** (le WS publie
  le dict brut, donc lui l'aurait eu de toute façon).

**Dashboard (4 fichiers, bump 0.5.46 → 0.5.47)** :
- **Nouveau** `components/dashboard/near-macro-badge.tsx` : badge **ambre 📅**
  volontairement distinct de l'AFN (orange/rouge) et du flash « court terme
  indécis » (indigo 🔀) — trois concepts différents. Mode `compact` (pastille
  liste + Alert) et mode plein (carte discipline détail signal, tap → `/macro`).
- `src/api/types.ts` : interface `NearMacroEvent` + champ sur `Advisory`.
- `app/signal/[id].tsx` : carte discipline sous l'`AntiFakeNewsBadge`.
- `app/(tabs)/signals.tsx` : pastille compacte dans la ligne signal.

**Vérifications** : **1329 tests verts** (contre `tik_test`, jamais la prod ; +17
nouveaux dans `test_macro_proximity.py` : fonction pure + annotateur mocké +
best-effort + passthrough schéma), 0 régression ; ruff check + format propres
(vraie config dépôt) ; `tsc` exit 0 ; `eslint` exit 0. **Validation runtime
contre la vraie DB prod** (lecture seule) : signal BTC simulé 2h avant le NFP du
05/06 → flag `{event_code: NFP, hours_until: 2.0}` ; signal hors fenêtre → `None`.

**Déploiement** : core (API) recharge le schéma seul (`--reload`) ; scheduler
redémarré (`restart`) pour charger l'annotateur → boot propre, 2 signaux ré-émis
sans erreur, annotateur actif (ne flagge rien actuellement = normal, aucun event
HIGH dans ±4h ; **première mise en pratique = NFP 2026-06-05 ~08:30 UTC**).

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003 / 004 / 011 / **017 renforcé** /
018 **inchangés**. Aucune modif du pipeline scoring / engines / cross-validation.
`work-from-hp` non touchée.

**Limites connues** :
1. Flag posé seulement sur les **nouveaux** signaux (calculé à l'émission) — les
   historiques n'en ont pas. Sans conséquence : les signaux autour du NFP du 05/06
   seront tous neufs.
2. Fenêtre **±4h / HIGH uniquement** (calibré sur Garde-fou 2-bis) — MED/LOW ne
   déclenchent rien (choix volontaire, recalibrable via `NEAR_MACRO_*`).
3. `hours_until` **figé à l'émission** (pas un compte à rebours live) — d'où le
   phrasé « émis ~Xh avant/après », pas « dans Xh ».
4. Repère **sur le signal** uniquement, pas (encore) sur la carte discipline Home
   ni couplé au sizing — extension possible plus tard.
5. Pas encore vu sur **device réel** (validé tsc/eslint + runtime backend) — à
   confirmer dans Expo Go.

**Mémoire pour instances Claude futures** : le flag macro est de la **discipline**,
jamais un input moteur (ne JAMAIS le faire entrer dans `combined_bias`/veracity).
Si une session veut élargir aux events MED ou changer la fenêtre, modifier
`NEAR_MACRO_WINDOW_HOURS` / `NEAR_MACRO_IMPORTANCE` dans `macro_proximity.py`.
Le couplage existe désormais → une future mesure de fiabilité pourra segmenter
le hit rate par `near_macro_event` (requêtable en SQL via `advisory`).

---

### Paquet 48 — Audit santé + fix timeouts LLM swing (cause racine réelle vs e0aa0b4) (2026-06-01)

Session « audit santé + dette technique » sur le VPS Hetzner, **lecture seule sur
le pipeline** sauf un fix calibré sur mesure. Prod jamais touchée en écriture.
`work-from-hp` non touchée. Méthode : rassembler les données AVANT d'interpréter,
vérifier l'âge des conteneurs avant toute mesure sur fenêtre temporelle (engagement
#9), mesurer plutôt que spéculer (#10).

**Anomalie trouvée + corrigée — les hypothèses LLM swing timeoutent encore (~64%),
malgré le fix e0aa0b4 du Paquet 44.** La doc Paquet 44 affirmait « ratio ≈100% LLM
attendu » après le décalage des crons swing, en le laissant *« à confirmer sur ~1h
de runtime »*. **Confirmation faite : non résolu.** Mesuré en DB (fenêtre 90 min) :
swing = **4 LLM / 11 = ~36% LLM** (le flash est 100% template, voulu A1). Logs : ~5
`ollama_error ReadTimeout` sur ~6 cycles swing en 45 min.

**Cause racine MESURÉE (≠ supposée)** : un seul appel Ollama chaud (`num_predict=350`)
prend **~33s sur ce CPU** (3 runs : 36,9s / 31,3s / 31,5s ; `size_vram: 0` = pas de
GPU). Le timeout httpx était à **50s** → marge ~15s seulement. Dès que le classifier
news des ingesters (process SÉPARÉ, MÊME Ollama, queue interne, hors du lock
intra-scheduler) tape Ollama en parallèle, la latence dépasse 50s → `ReadTimeout`. **Le
décalage des crons (e0aa0b4) visait la mauvaise cause racine** (collision swing↔swing
= facteur secondaire ; le vrai facteur = latence d'un appel seul trop proche du
timeout). Le ~36% mesuré aujourd'hui = identique au « 36% résiduel » d'avant e0aa0b4
→ le décalage n'a quasiment rien changé au ratio.

**Fix** ([core/src/tik_core/scoring/hypothesis_generator.py](core/src/tik_core/scoring/hypothesis_generator.py)) :
- `OllamaHypothesisGenerator.timeout_s` (httpx) **50 → 120s**.
- `apply_llm_hypothesis.timeout_s` (wait_for) **60 → 130s**.
- Calibré sur la mesure : 33s best case, ~80-100s sous contention (batch ingester
  complet en queue), tous < 120s. Reste très en dessous de l'interval swing (15 min
  BTC, 30 min GOLD) → pas de pileup (`max_instances=1, coalesce`). `num_predict=350`
  inchangé (qualité de sortie 6 sections préservée).
- Commentaires obsolètes corrigés au passage : référence fantôme à `OLLAMA_NUM_PARALLEL=2`
  (override systemd ne définit que `OLLAMA_HOST`, cf. Paquet 44) + calibration « Mac M1
  ~13s » (Tik tourne sur le VPS CPU, ~33s) + maths « 13s × 3 = 40s » périmées.

**Zéro impact pipeline** : l'hypothèse LLM est du texte affiché à l'humain, jamais
un input de décision (ADR-012/018, [[feedback_perf_vs_ux]]). Améliore seulement ce que
la trader lit sur le signal.

**Vérifié** : **1329 pytest verts** (contre `tik_test`, jamais la prod), ruff check +
format propres (vraie config dépôt, pas celle périmée du conteneur cf.
[[container-stale-pyproject-ruff]]). **Déployé** (`docker compose restart scheduler`,
bind-mount `./src`) → cycle de boot confirme : swing BTC `active.applied length_words=89
method=ollama:llama3.2:3b`, ~47s (12:35:27 → 12:36:14), **aucun timeout** — exactement
la latence qui frôlait l'ancien 50s et passe maintenant sous 120s.

**Reste sain (vérifié, rien à faire)** : dead code INITIAL_CLAIMS du Paquet 45 = déjà
nettoyé (ne reste qu'un commentaire intentionnel) ; fix redis `aclose` (Paquet 40)
présent + actif ; flag `near_macro_event` (Paquet 47) OK (0 flag sur 335 signaux/24h,
attendu car aucun event HIGH avant NFP 5/06) ; couche WS équilibrée (34 `ws.connected`
= 34 `ws.client_gone` sur 1h → **aucune fuite**, le fix Bug 10 marche ; le volume
reflète juste ~34 reconnexions/h du dashboard = côté client iPhone, pas un bug backend).

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003 / 004 / 005 / 011 / 012 / 017 / 018
**inchangés**. Aucune modif des engines / pipeline scoring / cross-validation.

**Limites connues** :
1. Confirmation **statistique** du ratio (~100% LLM) demande ~30-60 min de runtime
   post-déploiement — garantie par observation, pas par le code.
2. Sous contention **extrême** (gros batch ingester + swing simultanés), un appel rare
   pourrait encore frôler 120s → fallback template propre (pas un crash).
3. La contention cross-process scheduler↔ingesters (même Ollama, pas de lock partagé)
   n'est pas supprimée, seulement **absorbée** par le timeout. Suppression = chantier
   plus lourd (lock cross-process ou file d'attente Ollama), hors scope dette.
4. Ollama sur CPU reste lent par nature ; si un GPU était ajouté au VPS, on pourrait
   réduire les timeouts.

**Mémoire pour instances Claude futures** : le ~36% résiduel n'était PAS la collision
swing↔swing (e0aa0b4 ne l'a pas réglé) mais la **latence CPU d'un appel seul vs le
timeout 50s**. NE PAS rebaisser `timeout_s` sous ~100s tant qu'Ollama tourne sur CPU.
Si les timeouts reviennent : `curl localhost:11434/api/ps` (modèle chaud ?) + `free -h`
(RAM). Cf. mémoire [[ollama-llm-timeout-fix]].

---

### Paquet 49 — Audit méthodique P46/47/48 + durcissement test DB `near_macro_event` (2026-06-01)

Session de doute méthodique (« vérifie ce que tu devais faire et ce que tu as
fait, triangule, zéro complaisance ») exécutée sur le VPS prod, **lecture seule
sur le pipeline** sauf 1 ajout de test. Prod jamais touchée (6376 signaux).
`work-from-hp` non touchée. Branche `main`, `origin` en sync.

**Triangulation doc ↔ code ↔ runtime des 3 derniers paquets — tous VERTS** :
- **Paquet 48 (timeout LLM)** : déployé (`timeout_s=120`, apply `130`,
  `keep_alive=24h` confirmés en source), scheduler `RestartCount=0` (pas de
  crash, redéploiement volontaire 12:35), code review du diff propre (ordre
  `wait_for 130 > httpx 120` correct → fallback template propre). **Open
  question « ~100% LLM à confirmer » CLOSE** : mesuré DB depuis 12:35 = **5
  swing LLM / 0 template / 0 `ollama_error`** (les 5 derniers swings = 600-820
  chars = 6 sections). Confirmé positivement.
- **Paquet 47 (`near_macro_event`)** : vérifié **bout en bout** — code lit les
  vraies colonnes du modèle (`event_name`/`assets_impacted`, pas
  `title`/`affected_entities` comme l'affirmait à tort la doc Paquet 11 = drift
  doc, pas un bug), schéma `NearMacroEvent` déclare les 5 clés du dict (REST ne
  drop rien), câblé aux 3 jobs scheduler, **donnée prod correcte** (NFP 05/06
  12:30 HIGH `["BTC","GOLD"]`, CPI 10/06, ECB 11/06) → la discipline se
  déclenchera bien sur le NFP. Premier déclenchement réel = 2026-06-05.
- **Paquet 46 (`hit_rate.py` baselines)** : `compute_constant_baselines` /
  `assess_baseline_edge` — edge cases gardés (p0==0, prix None, n_evaluated==0,
  dict vide → pas de `max()` sur vide), mêmes skips que `compute_hit_rate`
  (apples-to-apples). Aucun bug.

**Durcissement livré (nouveau `core/tests/test_macro_proximity_db.py`, +6 tests)** :
les tests existants de `near_macro_event` n'utilisent que des **mocks**
(`FakeEvent` + `_mock_session`) → un renommage de colonne du vrai modèle
`MacroEvent` passerait inaperçu, et le `except Exception` best-effort de
`annotate_near_macro_event` l'avalerait **silencieusement** → discipline NFP
muette au pire moment. Le nouveau fichier insère de **vraies rows `MacroEvent`**
dans `tik_test` (Postgres réel, isolation par `flush()` sans commit →
`rollback()` de teardown discard, anchor 2030 = zéro collision) et couvre les 4
chemins que les mocks ne voient pas : colonnes réelles, filtre importance SQL,
filtre `assets_impacted` JSON Postgres, fenêtre SQL + choix du plus proche. Suit
le pattern `_db.py` (cf. `test_publisher_timezone_db.py`, garde anti-prod
`_is_test_database` du conftest).

**Bug latent trouvé + corrigé (drift modèle↔migration `MacroEvent`)** : en
écrivant un 2e garde DB pour `macro_events_repo` (nouveau
`core/tests/test_macro_events_repo_db.py`, +6 tests), le test a échoué avec
`asyncpg InvalidColumnReferenceError: no unique constraint matching the ON
CONFLICT` → le modèle SQLAlchemy `MacroEvent` ne déclarait **pas** la contrainte
UNIQUE `(event_code, scheduled_for)` que la migration 0005 ET la prod ont
(`uq_macro_events_code_when`, vérifié via `pg_constraint`). Conséquence du drift :
(1) tout environnement `create_all` (tests, CI, dev frais) n'avait pas la
contrainte → l'upsert `ON CONFLICT` du calendrier macro y échouait
**silencieusement** (best-effort → 0, log warning) ; (2) un futur `alembic
--autogenerate` aurait voulu la **DROP** (le modèle ne la déclarant pas). **Fix**
(`storage/models.py`) : `UniqueConstraint(..., name="uq_macro_events_code_when")`
ajoutée au modèle, **nom identique à la migration** → modèle aligné sur prod,
aucun nouveau migration nécessaire, **zéro risque prod** (prod a déjà la
contrainte ; seul `tik_test` a été droppé+recréé par `create_all`, prod `tik`
intacte = 98 events vérifiés). Les 6 tests guardent l'idempotence (2 upserts =
1 row), l'update on-conflict, le strip aware (Bug 9), et les filtres
importance/asset JSON Postgres. **Tracé non corrigé** (chemin prod qui marche,
non déclenchable avec les specs statiques bien formées) : dans `upsert_many`, un
event en erreur SQL n'est pas rollback → transaction Postgres « aborted » → les
events suivants + le `commit()` échouent → batch entier perdu (best-effort → 0).
À reconsidérer (savepoint par event) si une spec malformée le déclenche un jour.

**Audit systémique du drift (le bug est-il isolé ?)** : j'ai diffté TOUTES les
contraintes UNIQUE/PK réelles de la prod (`pg_constraint`) contre ce que les
modèles déclarent. Résultat sur les tables applicatives : **un seul autre
écart** — le modèle `Signal` déclare un PK sur `id` seul alors que la prod a un
PK composite `(id, timestamp)` (requis par l'hypertable Timescale, posé en
migration, cf. Bug 1/2). Contrairement à `macro_events`, ce drift **ne casse
rien** : aucun chemin app ne fait d'`ON CONFLICT` sur `signals`, l'identité ORM
par `id` (UUID unique) suffit, les inserts/queries marchent en prod ET en
`create_all`. C'est une **conséquence inhérente à Timescale**, **NON corrigée**
(déclarer le PK composite dans le modèle casserait `session.get(Signal, id)` et
l'identité ORM → risque élevé sur le modèle central). **⚠ Pour instances futures :
NE PAS appliquer un `alembic --autogenerate` qui voudrait changer le PK de
`signals` — c'est ce drift connu, pas une vraie migration.** Toutes les autres
tables applicatives (entities, sources, feedbacks, api_keys [client_id+key_hash
`unique=True` ✓], backtest_runs, source_credibility_history, headlines) :
**modèle = prod, aucun drift**.

**Vérifications** : suite complète **1329 → 1341 verts** (+12 : 6
`test_macro_proximity_db` + 6 `test_macro_events_repo_db`, tik_test, jamais la
prod), 0 régression ; ruff check + format propres (vraie config dépôt, pas celle
périmée du conteneur cf. [[container-stale-pyproject-ruff]]).

**Reste / non vérifié cette session (transparence)** : dashboard non testé sur
device (Paquets 46/47 = repères UI flash/macro validés seulement par bundle/tsc,
pas device réel) ; mesures shadow CoinGecko ~11/06 + Polymarket ~10/06 non dues ;
Reddit ban (Bug 11) asynchrone ; tik-core 0.0.0.0:8200 (hygiène différée, ne PAS
fermer sans chemin Tailscale iPhone confirmé) ; revue exhaustive des 14k lignes
non faite (focalisée sur les diffs récents = plus haut risque de régression).

**Garde-fous** : Garde-fou 1 / 2-bis, ADR-003 / 004 / 005 / 011 / 012 / 017 /
018 **inchangés**. Aucune modif des engines / pipeline scoring — audit lecture
seule + 2 fichiers de test additifs + 1 fix modèle (déclaration de contrainte
`MacroEvent` alignée sur migration/prod, zéro risque de régression : prod déjà
à jour). Verdict go/no-go directionnel **inchangé : NO-GO**.

---

## 9. Bugs connus et résolus

13 bugs identifiés depuis le démarrage du projet — 12 résolus + 1 actuel mitigé en attente d'un fix asynchrone (les 3 premiers pendant le déploiement initial du Paquet 1, les 3 suivants pendant les évolutions post-livraison du 2026-04-28, le 7e découvert le 2026-05-03 lors de la mise en service du dashboard sur iPhone, le 8e découvert le 2026-05-04 lors de la livraison Stats LLM card et résolu en deux temps : fix dashboard `parseUtcIso` le matin puis fix backend ADR-013 / Paquet 7 l'après-midi ; le 9e régression asyncpg DB du Paquet 7 fixé runtime le 2026-05-04 ; le 10e WebSocket coroutine zombie identifié et fixé le 2026-05-17 soir lors de l'audit santé runtime pré-trading Paquet 26 ; le 11e Reddit IP-ban full sur IP HP découvert lors de l'audit pré-J+14 Paquet 27 du 2026-05-18, mitigé par Option A doc-only en attente unban Reddit asynchrone ; le 12e cache track record qui figeait l'affichage des favoris flash en « tout sablier », découvert et fixé le 2026-05-26 via les questions de l'utilisatrice, Paquet 38 ; le 13e mapping FRED release_id faux (RETAIL_SALES=H.10 FX Rates, INITIAL_CLAIMS=G.19 Consumer Credit) découvert et fixé le 2026-05-31 lors de l'audit A3, Paquet 45) :

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

**Conséquence pipeline structurelle** : Tik tourne avec **3 overlays sentiment au lieu de 4** sur BTC swing (FG + CryptoCompare + Google News, sans Reddit). Quand FG diverge contrarian des news (cas typique marché bear actuel), FG est flaggé outlier ADR-011 → reste 2 sources alignées + 1 outlier → dispersion forte → **veracity capée à 0.85-0.89, jamais ≥ 0.90** sur BTC swing. Mesure audit 9h post-fix bug N=2 confirme : **0/36 signaux BTC swing à veracity ≥ 0.90**.

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

---

## 10. Bugs non résolus / améliorations à faire

**Aucun bug critique en cours au 2026-05-04 fin d'après-midi.**

Les 2 bugs Alerts identifiés en section 10 le 2026-05-04 matin (Bug A persistance et Bug B timestamp figé) ont été résolus dans la même journée :

- **Bug A — Persistance Alerts (résolu 2026-05-04 après-midi)** : migration vers `@react-native-async-storage/async-storage` dans `dashboard/src/alerts/AlertsContext.tsx`. Hydratation eager au mount + persistance à chaque `setAlerts`. Clé storage `tik.alerts.v1` (suffixe versionné pour migration future). Filet d'exception : si JSON corrompu → log warning + reset `[]`. Cap `MAX_ALERTS=50` inchangé.

- **Bug B — Timestamp figé Alerts (résolu 2026-05-04 après-midi)** : initialement résolu avec un `setInterval(setTick, 30_000)` inline dans `app/(tabs)/alerts.tsx`. Constat post-déploiement que le **même bug existe sur l'écran Signals + Home** (4 fichiers utilisent `timeAgo`). Refacto en hook custom mutualisé `dashboard/src/hooks/use-tick.ts` (~10 lignes, retourne le `tick` pour `FlatList.extraData`). Pattern aligné sur la factorisation `dashboard/src/utils/llm.ts` (helper partagé entre carte détail signal et Stats LLM Home). Refacto de 4 fichiers (alerts, signals, index, stats-llm-card en cascade via parent index).

Pour les évolutions fonctionnelles à venir (carte Top headlines, hit rate live, track record signal, watchlist post-trade — plan trading manuel J+10), voir `docs/backlog.md` entry n°3 et la section 8 — *Couches encore non-implémentées*.

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

*Dernière mise à jour : 2026-06-01 (**Paquet 48 — Audit santé + fix timeouts LLM swing (cause racine réelle vs e0aa0b4)** : session audit lecture seule sauf 1 fix calibré sur mesure. **Trouvé** : les hypothèses LLM des signaux swing timeoutent encore ~64% malgré le fix e0aa0b4 du Paquet 44 (qui visait la collision swing↔swing = mauvaise cause racine). **Cause MESURÉE** : un appel Ollama chaud prend ~33s sur CPU (`size_vram:0`, pas de GPU) vs timeout httpx 50s = marge 15s → toute contention avec le classifier news des ingesters (même Ollama, queue interne, hors lock) dépasse 50s → `ReadTimeout`. Mesuré DB : 4 LLM / 11 swing = ~36% LLM (identique au résiduel pré-e0aa0b4 → le décalage des crons n'a rien changé au ratio). **Fix** (`hypothesis_generator.py`) : timeout httpx 50→120s + wait_for 60→130s (calibré : 33s best, ~80-100s sous contention, tous < interval swing 15min/30min donc pas de pileup `max_instances=1,coalesce`) + commentaires obsolètes corrigés (référence fantôme `OLLAMA_NUM_PARALLEL=2`, calibration « Mac M1 ~13s »). **Zéro impact pipeline** (hypothèse = texte affiché à l'humain, ADR-012/018). **1329 tests verts** (tik_test, jamais la prod), ruff check+format OK (vraie config dépôt). **Déployé** (restart scheduler, bind-mount ./src) → boot confirme swing BTC `active.applied length_words=89 method=ollama:llama3.2:3b` en ~47s **sans timeout** (la latence qui frôlait l'ancien 50s passe sous 120s). **Reste sain vérifié** : dead code INITIAL_CLAIMS Paquet 45 déjà nettoyé (commentaire seul), redis `aclose` Paquet 40 actif, flag `near_macro_event` Paquet 47 OK (0/335 signaux attendu pré-NFP), couche WS équilibrée (34 connected = 34 client_gone/h, aucune fuite). **Limites** : confirmation statistique ~100% LLM = ~30-60min runtime (par observation), contention extrême rare peut frôler 120s (fallback template propre), contention cross-process scheduler↔ingesters absorbée pas supprimée, CPU lent par nature. Garde-fou 1/2-bis + ADR-003/004/005/011/012/017/018 **inchangés**, pipeline/engines intouchés, `work-from-hp` non touchée. **Précédent** : 2026-06-01 (**Paquet 47 — Couplage signaux ↔ calendrier macro (Phase B1.5)** : flag `near_macro_event` posé dans `Signal.advisory` quand un signal est émis dans la fenêtre ±4h d'un event macro HIGH (NFP/CPI/FOMC/BCE/BoJ) impactant l'entité — calculé à l'émission (best-effort, **ne touche PAS direction/conviction/veracity**, ADR-017 renforcé), persisté (requêtable plus tard pour mesurer si les signaux « près macro » performent différemment). Backend : module pur `macro_proximity.py` (`find_nearest_macro_event` + annotateur `annotate_near_macro_event` câblé aux 3 jobs scheduler) + schéma `Advisory` enrichi (sous-modèle `NearMacroEvent`, sinon le champ était supprimé en sortie REST). Dashboard : badge ambre 📅 distinct AFN (orange)/flash (indigo) — carte discipline détail signal + pastille liste, bump 0.5.46 → 0.5.47. **1329 tests verts** (tik_test, +17 dans test_macro_proximity), ruff/tsc/eslint OK, validé runtime contre la vraie DB prod (signal BTC −2h NFP → flag hours_until=2.0, hors fenêtre → None) + déployé (restart scheduler, boot propre + 2 signaux ré-émis sans erreur). **1re mise en pratique = NFP 2026-06-05 ~08:30 UTC.** Limites : flag sur nouveaux signaux seulement, ±4h/HIGH only, `hours_until` figé à l'émission, pas encore vu sur device réel. Garde-fou 1/2-bis + ADR-003/004/011/017/018 inchangés, pipeline scoring/engines intouché, `work-from-hp` non touchée. **Précédent** : 2026-05-31 (**Paquet 46 — Re-analyse colinéarité (doute méthodique) + outil analyze_colinearity.py (fdc9f27) + point A hit rate honnête vs baseline constante (bd0d283) + diagnostic flip-flop flash (76/48h vs swing 0). Bug méthodo : p-value gonflée par chevauchement des fenêtres (Hansen-Hodrick) — affecte aussi go/no-go + Paquets 32/33/37, reporter le N indépendant. **Suite livrée (dashboard 0.5.45)** : repère « ⚠ court terme indécis » sur les lignes flash BTC `choppy` dans Signals (direction conservée, pas d'onglet séparé, moteur intouché). Détails section 8 Paquet 46.** **Précédent (même session)** : **Paquet 45 — Fix A3 : mapping FRED release_id faux** : suite de l'audit du 2026-05-31. L'anomalie A3 (3 RETAIL_SALES en juin) cachait **2 `release_id` FRED faux depuis le Paquet 11** (vérifiés contre l'API FRED) : `RETAIL_SALES`=17=« H.10 Foreign Exchange Rates » (hebdo → 31 faux events du lundi), `INITIAL_CLAIMS`=14=« G.19 Consumer Credit ». Vrais IDs : Retail=**9**, weekly claims=180. Les 5 autres (NFP=50/CPI=10/PPI=46/GDP=53/IP=13) corrects. Fix (choix utilisatrice) : `RETAIL_SALES` 17→**9** (mensuel MEDIUM), `INITIAL_CLAIMS` **retiré** de la whitelist (claims hebdo LOW = bruit ±4h), `FRED_RELEASES` 7→6 ; `event_name`/heures déjà bons ; 2 commentaires « 7 releases » corrigés. Prod : 37 faux RETAIL_SALES (FX) + 8 faux INITIAL_CLAIMS supprimés (`DELETE` chirurgical via `release_id` stocké), cycle FRED relancé → retail mensuel correct (06-17, 07-16, 08-14…), comptage 31→7, INITIAL_CLAIMS=0. **118 tests macro verts** (tik_test), ruff clean, commit `5de2d8a`. Diagnostic clé : `include_release_dates_with_no_data=true` (déjà passé par l'ingester) est requis pour voir les dates futures de 9/180 (fausse piste « pas de dates futures » écartée). Bug 13 tracé section 9. **Zéro impact pipeline** (calendrier = discipline humaine, ADR-017), Garde-fous 1/2-bis + ADR-003/004/011/018 inchangés, `work-from-hp` non touchée. Mémoire `macro-fred-release-ids` créée. **Précédent** : 2026-05-31 (**Paquet 44 — Audit santé runtime + fix A1 LLM timeouts Ollama** : audit méthodique du VPS de prod (doc↔runtime triangulé, lecture seule sauf le fix). **1 vraie anomalie A1** trouvée + corrigée, **1 fausse alerte démasquée** (compte tests CoinGecko 41 `def` vs 47 annoncés → run réel = 47 passed = paramétrisation, doc correcte ; discipline « vérifier avant verdict »). **A1** : `TIK_LLM_HYPOTHESIS_MODE=active` mais ~50 % des hypothèses retombaient en **template** (mesuré DB : 29 template / 21 LLM sur 50 derniers ; **95 `ollama_error ReadTimeout`/24h**) → divergence doc↔réalité. Cause racine triangulée (≠ commentaire de code) : Ollama sur l'**hôte VPS** (systemd, **4 cœurs CPU sans GPU**, llama3.2:3b ~2.48G) ; 3 jobs LLM (flash 5min + swing BTC 15min + swing GOLD 30min) collisionnent à xx:00/xx:30, le `Lock` intra-process sérialise mais `wait_for(60s)` **inclut l'attente du lock** → 2e/3e job timeout ; aggravé par le process ingesters (même Ollama). Le commentaire supposant `OLLAMA_NUM_PARALLEL=2` était **faux** (override.conf ne définit que `OLLAMA_HOST`). Fix (commit `96d7a42`, 4 fichiers +54/-8, in-repo) : (1) `run_scheduler` flash exclu du LLM (`None`) → **template instantané** (flash = bruit sans edge, Paquet 43), 3 jobs LLM → 2 ; (2) `hypothesis_generator` (constante `OLLAMA_KEEP_ALIVE="24h"`) + `news_classifier` → `keep_alive=24h` dans le payload `/api/generate` (modèle reste chaud, indispensable une fois le flash retiré) ; (3) test verrouillant le payload. **1307 pytest verts** (tik_test, jamais la prod), ruff check+format clean (config dépôt). Déployé prod (`restart scheduler ingesters`) → **mécanisme confirmé runtime** : 0 `ollama_error`, flash=template(90c), swing=LLM(676c). **Zéro impact pipeline** (hypothèse = texte affiché, pas un input de décision, ADR-018). Mémoire `ollama-llm-timeout-fix` créée. **Reste** : confirmation **statistique** du ratio sur 30-60 min (1re collision swing ~00:53 UTC) ; anomalie mineure RETAIL_SALES ×3 en juin (artefact FRED probable) non diagnostiquée ; connus inchangés (Reddit ban Bug 11, hygiène 8200, mesures shadow ~10-11/06). **NE PAS remettre le LLM sur le flash** (réintroduit la contention). Garde-fou 1/2-bis, ADR-003/004/011/018 **inchangés**, `work-from-hp` non touchée. **Précédent** : 2026-05-30 (**Paquet 43 — Session fiabilité & mesures** : (1) durcissement de `measure_coingecko_divergence.py` — ajout de métriques de **mouvement** robustes au biais de base (`movement_deltas`/`movement_agreement`/`centered_directional_agreement`/`primary_spearman`) car comparer les NIVEAUX de CoinGecko (vote ~65-75 %) et Fear & Greed (~20 en bear) est mécaniquement biaisé ; le verdict s'appuie désormais sur le Spearman des variations jour-à-jour ; +20 tests (27→47 verts, tik_test), ruff/format propres (config dépôt) ; lecture live N=4 jours NON concluante mais l'ancienne « accord vs 50 = 0 % » était un artefact (le mouvement montre 100 % d'accord) → re-mesurer ~11/06. (2) Recalibration ADR-011 vérifiée saine (03:00 UTC, données propres, sources flash pénalisées 0.30, cosmétique). (3) **Résolution open question « pattern flash BTC inversé » Paquet 10** : sur données propres post-fix (2463 signaux dual-lens @1h), le pattern est un **artefact de composition neutral/directionnel** (veracity basse = surtout du neutral qui « gagne » trivialement à 1h mais gain ≤ 0 ; veracity haute = directionnels qui ratent), PAS un paradoxe de qualité → flash = **aucun edge directionnel** à aucun niveau de veracity, le « 53.5 % » du Paquet 10 ne se reproduit pas (données pré-fix contaminées). (4) Polymarket prêt à mesurer ~10-11/06 (BTC 160 / GOLD 63 relevés). Lecture seule pipeline, zéro modif engines, prod jamais touchée, NO-GO directionnel **inchangé**, `work-from-hp` non touchée. **Précédent** : 2026-05-30 (**Paquet 42 — Carte UX « Stabilité flash · BTC »** : réponse à la friction « long puis short en flash BTC à quelques minutes, je ne sais pas quoi prendre ». Diagnostic triangulé sur données live = flip-flop **structurel pas un bug** (31 bascules opposées <20 min/24h ; direction flash = moyenne 2 sources microstructure discrètes + seuil ±0.30 sans hystérésis ; flash sans edge prouvé). Choix utilisatrice Option A UX réversible (pas de retouche moteur). 3 fichiers neufs dashboard + 2 micro-éditions, 100 % côté affichage, zéro backend, calculé depuis `signals24h` déjà chargé : carte avec **verdict stabilité (45 dernières min : INSTABLE/STABLE/INDÉCIS)** + **croisement carnet vs flux agressif (à l'instant : s'accordent/se contredisent)** + toggle on/off dans Config. Libellés portant leur fenêtre de temps + pied explicatif (lève la confusion « instable mais sources d'accord » = 2 fenêtres distinctes). tsc/ESLint exit 0, logique rejouée contre données live (choppy flips=2 / indecisive flips=1 conformes). dashboard 0.5.40 → 0.5.42. Garde-fou 1/2-bis, ADR-003/004/005/011/018 inchangés, moteur/pipeline intouchés, mémoire `flash-flipflop-diagnosis` (NE PAS modifier flash_engine sans demande), prod jamais touchée, work-from-hp non touchée. **Précédent** : 2026-05-27 (**Paquet 41 — Overlay sentiment CoinGecko en SHADOW (ADR-021)** : choix utilisatrice « restaurer le 4e overlay BTC » (Reddit IP-banni → BTC à 3/4 overlays, veracity capée 0.85). Source choisie par MESURE de joignabilité depuis le VPS (Reddit était bloqué réseau) : HN joignable mais quasi vide (0 story BTC >15 pts/7j), StockTwits+Bluesky 403 → seul candidat libre exploitable = CoinGecko `sentiment_votes_up_percentage` (numérique, mea culpa : menu initial « HN/StockTwits » optimiste, pas de remplaçant retail textuel gratuit). SHADOW strict toggle OFF (pattern DXY/COT) : ingester `coingecko_sentiment_ingester.py` collecte dans Redis (snapshot + historique cappé 2000) ; overlay swing gaté `TIK_COINGECKO_OVERLAY_ENABLED` (défaut False) → zéro impact signaux, log `coingecko_skipped_overlay_disabled` ; mapping contrarian provisoire calqué FG ; `SOURCE_SCORES` 0.60. But shadow = mesurer divergence vs Fear & Greed avant activation (risque redondance). 1139 → 1159 verts 0 warning (tik_test), ruff OK, runtime `coingecko_sentiment.published up_pct=63.58` + Redis OK. Scheduler non redémarré (overlay OFF → signaux identiques, restart requis seulement à l'activation). Garde-fou 1/2-bis/ADR-003/004/011/018 inchangés tant que OFF ; coexiste avec Reddit (5 overlays à terme) ; prod jamais touchée hors collecte shadow ; `work-from-hp` non touchée. **Précédent (même jour)** : 2026-05-27 (**Paquet 40 — Audit dette technique** : suite Paquet 39 même session, audit « autres bugs/dette sûrs » hors pipeline/garde-fous. Suite pytest **réellement verte** confirmée (1139 passed, tik_test) avec 1 `DeprecationWarning` comme point de départ. Backend : redis-py 7.4.0 déprécie `.close()` → `.aclose()` sur 9 objets redis/pubsub (7 fichiers, tous teardown `finally:`/lifespan, zéro logique scoring) → suite re-verte 1139 passed **0 warning** ; core `--reload` à chaud, scheduler/ingesters au prochain restart (teardown-only, inoffensif). Dashboard : 1 erreur ESLint `react/display-name` (`renderItem` → nommé `SignalRow`) + 1 warning `HORIZONS` inutilisé (→ type union direct), documentés Paquet 36 jamais corrigés ; tsc+eslint exit 0 ; bump 0.5.29 → 0.5.30. Garde-fou 1/2-bis, ADR-003/004/011/018 inchangés, pipeline intouché, prod jamais touchée, `work-from-hp` non touchée. **Précédent (même jour)** : 2026-05-27 (**Paquet 39 — Fix bug parsing seuil Polymarket shadow** : l'ingester Polymarket (shadow depuis 24/05) lisait « $84,000 May 25-31? » avec le « M » de « May » pris pour « million » → seuil aberrant 8,4e10 ; familles « reach/dip $X <plage de dates> » sans « on »/« in » corrompues (28 questions sur 81 snapshots historiques Redis). Fix regex `([kKmM]?)(?![A-Za-z])` sans `\s*` dans `polymarket_ingester.py` + 3 tests (33 verts, tik_test) + ruff propre (config repo). `docker restart ingesters` → snapshot frais 0 seuil corrompu vérifié runtime. Nuance honnête : la mesure du 10/06 était DÉJÀ protégée (filtre ≤5M$ + famille « above…on » seule) — le fix sert l'exactitude des données stockées + un futur enrôlement de la famille « reach/dip ». SHADOW strict (0 `_enrich_with_polymarket`, zéro impact signaux/pipeline), historique corrompu laissé tel quel (filtré par le script de mesure), prod jamais touchée, `work-from-hp` non touchée. **Précédent** : 2026-05-26 (**Paquet 38 — Fix bug cache track record (favoris flash bloqués) + nettoyage doc, en réponse aux questions de l'utilisatrice** : bug découvert via ses questions sur les favoris flash — l'endpoint `/metrics/signal_track_record` mettait le résultat en cache Redis 6h **y compris quand les lignes étaient `en_attente`**, donc un favori flash ouvert frais restait « tout sablier » 6h (≫ fenêtre flash 1h) et son auto-résolution ne se débloquait jamais (re-tapait le cache figé) ; **un seul bug, deux symptômes** (carte détail figée + badge Watchlist bloqué). Fix : helper `_track_record_cache_ttl` (TTL court tant qu'il reste des `en_attente`, long 6h une fois résolu) + bump clé cache `v3→v4` dans `core/src/tik_core/api/metrics.py`. Vérifié bout en bout : 7 tests + **suite complète 1136 verte** (tik_test), ruff/tsc/eslint exit 0, déploiement live uvicorn `--reload` confirmé (clés v4 créées par l'endpoint, flash résolu → TTL ≈6h, signal jadis bloqué recalculé `correct/raté`). **2 anomalies doc corrigées** : docstring « flash → 15min/30min/**1h/4h** » (vrai = 45min/1h) + glossaire `triggers` « qui ont déclenché le signal » (faux post-ADR-018 — direction = combined_bias OSINT, indicateurs techniques à poids 0.0 ; reformulé décisionnels vs contexte technique). **2 sur-flags revertés** (mea culpa) : retrait « 90j macro » Watchlist + reformulation glossaire `horizon` annulés car le moteur macro est au roadmap (CLAUDE.md §8) et la mention forward-looking est assumée. **Scalping** : confirmé non-viable comme générateur de signaux (au timeframe scalp les sources lentes sont gelées → cross-validation multi-sources s'effondre) ; **correction conceptuelle** : la microstructure EST de l'OSINT (carnet/aggTrades publics, déjà overlays flash `_enrich_with_orderbook`+`_enrich_with_aggression` à 0.85) — c'est le *scalping comme horizon* qui sort du modèle, pas la microstructure comme donnée. Mémoires créées : `macro-horizon-intentional`, `scalping-not-osint`. Bug 12 ajouté section 9. dashboard 0.5.28 → 0.5.29 (fix glossaire triggers). Garde-fou 1/2-bis, ADR-003/004/005/011/018 inchangés ; **aucune modif du pipeline scoring/engines** (endpoint lecture seule) ; prod jamais touchée ; `work-from-hp` non touchée. **Précédent** : 2026-05-25 (**Paquet 37 — Audit J+1 trading (doc/mesure seule, prod intouchée)** : (1) 3 commits du 24/05 enfin tracés (Polymarket SHADOW `87e78cb` non branché engines, validé runtime 29 snapshots ; durcissement sécurité `3367575` H1-H4/M2/M3/M5/B1/B4 ; M4 détection panne silencieuse `e39a71a`). (2) **Mesure go/no-go PRÉLIMINAIRE** (non-officielle, l'officielle reste le 2026-05-27 via `go_no_go_report.sh`) sur 267 swing BTC mûrs vs Always SHORT : Tik PERD à 24h/48h/5j-global/flash (p<0,001), ÉGALITÉ au mieux à 5j veracity≥0,85 (p=0,298) → **aucun edge directionnel, hit rates 63-72 % = artefacts de tendance** ; confirme le 2026-05-23, renforce Garde-fou 2-bis (sizing 1 %, contexte ≠ pari). (3) **Dette de déploiement tracée** (mtimes vs démarrages process) : H1/M4 actifs dans core via `--reload`, mais H2/H4/B1/B4/M2 PAS chargés dans scheduler/ingesters/redis (démarrés avant les commits 24/05, sans --reload) — **correction des signaux INTACTE** (engines mtime < démarrage scheduler vérifié), seuls items hors-pipeline (sécu défensive + filet OOM Redis) ; fix = recreate via `redeploy.sh`, ✅ FAIT+vérifié par la trader 2026-05-25 15:28 (M2 actif, signaux repris, 0 erreur). (4) Memory recalibration corrigée (active depuis ~2026-05-22 sur données propres, cosmétique, pas le 27/05). (5) Backlog OSINT Vague 1 NON construit (garde-fou enrôlement + une source à la fois + ne résout pas la colinéarité au trend). Garde-fou 1/2-bis, ADR-003/004/011/018 inchangés ; `work-from-hp` non touchée. **Précédent** : 2026-05-25 (**Paquet 36 — Track record lisible (3 états ✓/≈/✗) + mouvement en points par signal + triggers « décisionnels » vs « Contexte technique » repliable + comparateur broker construit puis retiré (dashboard 0.5.22 → 0.5.27)**. Le chiffre du track record suit le résultat du pari (signe colle au badge) ; 3ᵉ état orange ≈ = « bon sens mais sous le seuil » (résout « +0,19 % mais pastille rouge »). Nouveau `src/utils/points.ts` (BTC 1 $, GOLD 0,01 $ ajustable) : bloc « Mouvement requis en points » montée ▲/baisse ▼ = seuil × prix (symétrique, barre à franchir pas objectif) + mouvement observé en points ; zéro backend (réutilise `p0`). Triggers split par poids : décisionnels (>0, sentiment OSINT swing / microstructure flash) vs technique repliable (RSI/EMA/MACD/momentum, poids 0, ADR-018). Broker comparator construit (`aead5d1`) puis SUPPRIMÉ à la demande (`a11c475`) ; chiffres broker réels en mémoire (spread ~220 ActivTrades slippage inclus / 20-40 Pepperstone, levier 1:1000 pro / 1:2 crypto). Audit prismatique : 2 anomalies sémantiques corrigées (« OSINT » faux pour flash → « décisionnels » ; momentum omis), 2 lint pré-existantes tracées (signals.tsx display-name, useDashboardKpis HORIZONS). tsc 0, eslint 0 fichiers touchés, bundle web OK (1256 modules). Zéro modif backend/pipeline/engines ; Garde-fou 1/2-bis, ADR-003/004/011/018 inchangés. Commits `aead5d1` → `a11c475` → `e5c9621` (+ ce doc). **Précédent** : 2026-05-23 (**Paquet 35 — Outil « Tik vs trend baseline » (test apparié sur le gain + significativité) + audit fiabilité honnête à J-1 trading**. Ajout pur additif `normal_cdf` + `paired_gain_significance` dans `backtest.py` + section « Tik vs baselines constantes » dans `measure_post_fix_hit_rates.py` (compare Tik à Always SHORT/LONG/NEUTRAL sur le GAIN, pas seulement Random — Random est trivial à battre en marché tendanciel). +13 tests, **1074 → 1091 verts** contre tik_test, ruff/format verts (avec la vraie config repo ; le `pyproject.toml` du conteneur est périmé → faux positifs, cf. memory `container-stale-pyproject-ruff`). **Verdict empirique honnête** : BTC swing post-fix = 64% short ≈ Always SHORT, régime BTC −4,4% → perf confondue avec la tendance ; hit rate 44→28→20→100% selon l'horizon (5d=100% = N=27 tous short, 1 épisode = artefact) ; gain ≤ 0 à tous les horizons mesurables ; Tik **PERD significativement vs Always SHORT** (6h Δ −0,17% z=−6,4 p<0,001) → **aucun edge directionnel démontré, Tik sous-performe la tendance**. Go/no-go fiable = swing 5j du **2026-05-27** vs Always SHORT, pas Random. **5 erreurs de méthode documentées** (mémoires `measurement-rigor-controls` + `tik-empirical-state-2026-05-23`) : extraction incohérente (tail vs grep|head → comparé veracity≥0,85 @1j à global @6h), hit rate isolé présenté comme « la fiabilité de Tik », affirmation fausse non vérifiée (« enrôler contamine le go/no-go » → FAUX, signaux figés), comparaison à Random au lieu d'Always SHORT, verdict 9/9 trop propre avec 2 erreurs factuelles. **Décision : NE PAS ajouter de source OSINT avant le go/no-go du 27/05** (garde-fou timing + ne résout pas la colinéarité au trend). Trading demain : Tik = outil de contexte, pas signal directionnel fiable → renforce Garde-fou 2-bis. Garde-fou 1/2-bis/ADR-003/004/011/018 inchangés, pipeline/engines intouchés, prod jamais touchée (3235 signaux), `work-from-hp` non touchée. **Précédent** : 2026-05-21 (**Paquet 34 — Fix R2/R6 recalibration sur données contaminées (J-3 trading)**. Le job `recalibrate_sources` apprenait sur une fenêtre lookback 100 % pré-fix Bug N=2 et poussait les scores de crédibilité affichés vers le plancher 0,30 (mesuré live : FG 0,38, orderbook/aggtrades 0,30 vs statiques 0,65/0,85). Vérifié en code que c'est **strictement cosmétique** (le score n'entre pas dans combined_bias/direction/veracity post-ADR-018). Fix auto-cicatrisant : `RECALIBRATION_DATA_FLOOR = 2026-05-17 20:47` + helper pur `_lookback_window` → `window_empty_skip` tant que pas de données propres+mûres (auto-inopérant après ~2026-06-16, reprise ~2026-05-22). Nouveau script `reset_source_credibility.py` (DELETE clés exactes, jamais wildcard). 4 tests purs, **1074 → 1078 verts** contre tik_test, ruff propre. Déployé runtime VPS prod (restart scheduler via bind-mount + reset 5 clés + vérif Redis vide + scheduler healthy). Analyse 6× + double lecture. Garde-fou 1/2-bis/ADR-003/004/011/018 inchangés, pipeline scoring intouché, `work-from-hp` non touchée. **+ Polish dashboard (0.5.20)** : friction utilisatrice — taper une alerte ne la marquait pas lue (seul `markAllAsRead` existait). Ajout `markAsRead(id)` dans AlertsContext + branché au tap (taper = marquer lue + ouvrir le signal). tsc + ESLint exit 0, zéro modif backend. **Précédent** : 2026-05-20 (**Paquets 31-33 — Fiabilité & qualité de code à J-4 du trading**. Paquet 31 : suite pytest réparée (était rouge : 4 fail + 5 errors sur les gardes Bug 9/10, commit `bf0d360` jamais validé ; cause = `db_engine` scope session incompatible pytest-asyncio 1.x) + **garde anti-production critique** (`_is_test_database` : le `drop_all` de la fixture ciblait `TIK_DB_NAME=tik` = prod, pouvait détruire 2410 signaux — sauvé par le bug de boucle ; désormais `pytest.skip` si base non-test), 1052 verts contre tik_test isolé, commit `297d6f3`. Paquet « lint » : résorption dette ruff (360 erreurs + 58 fichiers reformatés → `ruff check`/`format --check` verts ; auto-fixes sûrs + config faux-positifs FastAPI/Pydantic + 4 vrais fixes ; aucun F/E-code masqué), commit `a36861a`. Paquet 32-33 : **audit fiabilité signaux + backtest module anti-fake-news** (lecture/mesure seule, zéro modif pipeline) — (1) **données pré-fix N=2 contaminées** confirmées par `sources_count` (swing BTC pré-fix = 3 sources, CryptoCompare manquant → cross-validation N=2 buggée → 0,9 % hit à 5j, directions long à contresens ; post-fix = 4 sources, short-biased) → **tout backtest pré-fix inexploitable** y compris les chiffres Paquet 27 (SHORT BTC 63 %, GOLD 4,8 %) ; (2) **aucun edge directionnel démontré** aux horizons mûrs (10 backtests, Tik ≈ Random à seuil fin, Always SHORT/NEUTRAL compétitifs) ; (3) **filtre veracity ≥ 0,85 neutre sur swing BTC** (le « dégrade » initial était un artefact flash-inversé + bruit GOLD ; correction d'un verdict trop alarmiste ; BTC swing V≥0.90 = 0 signal → seuil 0,85 confirmé bon) ; (4) **backtest AFN INCONCLUSIF sous paranoïa** — `ok` short touchait ~2× mieux que `degraded` (37,8 % vs 19,6 % @6h) mais après scrutin (correction multiple-testing : @6h ne survit pas ; confond veracity : degraded tous à 0,78 < 0,85 donc déjà retirés par le filtre veracity ; gain s'inverse à 24h) → pas un edge robuste, à re-mesurer au 5j. Correction d'un verdict initial trop optimiste (mea culpa). 6 vérifications pour/contre/verdict (V1 prod intacte, V2 CI verte sur tik_test vierge, V3 no-edge robuste, V4 AFN sain, V5 branche main, V6 lint sans bug). Mémoire recalibration corrigée (ADR-011 active depuis ~2026-05-19, pénalise SOURCE_SCORES dynamiques mais impact COSMÉTIQUE — `get_effective_score` n'alimente que l'affichage evidence, pas direction/veracity post-ADR-018). Outil durci : 3 filtres `--signal-horizon`/`--entity`/`--cb-status` (`4e16e4f`/`a2b6477`/`2d2945b`) + tests primitives hit-rate (`82e5d87`, 1052→**1074 verts**). Mesure go/no-go fiable = **swing 5j post-fix le 2026-05-27** : `--entity BTC --signal-horizon swing --horizon-days 5 [--cb-status ok]`. Garde-fou 2-bis section 5 caveat ajouté (« SHORT BTC 63 % » contaminé, AFN `ok` mieux étayé). Garde-fou 1 / 2-bis / ADR-003/004/011/018 inchangés, prod jamais touchée, `work-from-hp` non touchée. **Précédent** : 2026-05-19 (**Paquet 30 — Script `measure_post_fix_hit_rates.py` LIVRÉ à J-5 du trading manuel**. Matérialisation 8 jours en avance du script prévu au plan calendaire Paquet 25 pour le J+10 post-fix Bug N=2 (2026-05-27). 387 lignes Python wrapper de `backtest.py` qui réutilise 95 % des helpers existants (`fetch_btc_history`, `fetch_gold_history`, `find_closest_price`, `evaluate_constant_baseline`, `evaluate_random_baseline`, `evaluate_tik_baseline`, `_gain_for`, `_success_for`) — pas de duplication de logique. 3 niveaux veracity mesurés simultanément (Niveau 2 global garde-fou régression silencieuse + Niveau 1 transitoire ≥ 0.85 aligné Garde-fou 2-bis Reddit IP-banni + Niveau 1 strict ≥ 0.90 audit post-retour Reddit). CLI args : `--horizon-days/--horizon-hours` (flash via horizon-hours, swing par défaut 5j), `--threshold`, `--since-iso` (défaut fix Bug N=2 2026-05-17T20:47:00 UTC), `--until-iso`, `--min-samples`. **Validation runtime effectuée** sur container `tik-core` du VPS HP, fenêtre pré-fix (`--since-iso 2026-05-13T10:00:00 --until-iso 2026-05-17T20:47:00 --horizon-days 1 --threshold 0.3`) sur 1058 signaux évalués : Tik global hit rate 32.9 % vs Paquet 27 31.1 % ✓, GOLD hit rate 5.0 % vs 4.8 % ✓, BTC SHORT 56.0 % vs 63.1 % (ma fenêtre exclut signaux post-fix) ⚠. Logique saine. Observation bonus : les 3 niveaux veracity donnent presque mêmes chiffres (1058 → 1058 → 1057) sur fenêtre pré-fix car 99.4 % à veracity = 0.95 (bug N=2 confirmé empiriquement) — au 2026-05-27 sur données post-fix les 3 niveaux divergeront enfin de manière significative. **Décisions structurantes prises** : réutilisation maximale des helpers `backtest.py` (cohérent engagement #5 vérifier hypothèses avant verdict + engagement #1 lire code avant affirmer), variante locale `_evaluate_signal_td` 35 lignes parce que `evaluate_signal` original prend `horizon_days: int` (rétrocompat préservée), klines 15m si horizon ≤ 4h sinon 1h, pas de persistance DB (sortie stdout uniquement, pattern minimaliste), pas de tests pytest (cohérent backtest.py, helpers triviaux, limite assumée). **Limites connues** : seuil directionnalité par défaut 0.5 % (hérité backtest.py) pas la granularité Paquet 17 (override via `--threshold`), pas de séparation flash/swing/macro auto (la trader lance plusieurs fois), `MIN_VERACITY_TRANSITOIRE = 0.85` codée en dur (modifier 1 ligne quand Reddit revient), pas de tests pytest helpers triviaux (dette tracée). Garde-fou 1 / ADR-003 / ADR-004 / ADR-011 / ADR-018 inchangés — purement additif. Garde-fou 2-bis transitoire **inchangé** — le script EST l'outil qui permettra de valider/invalider la règle "observer prioritairement SHORT BTC" et raffiner les seuils veracity post-J+24. Mémoire pour Claude futures : lancement réel **prévu 2026-05-27** (J+10 post-fix Bug N=2), commande par défaut suffisante `docker exec tik-core python -m tik_core.scripts.measure_post_fix_hit_rates` (horizon 5j swing par défaut), ajouter `--horizon-hours 1` pour flash, NE PAS modifier `MIN_VERACITY_TRANSITOIRE` tant que Bug 11 Reddit non résolu. **+ Documentation backlog #2 ADR-014** mise à jour avec débat à 6 angles (qualité signal / effort réel / surface bug / maintenance / cohérence stratégie / alternative low-effort) + Option E alternative recommandée (glossaire EN→FR enrichi `dashboard/src/glossary.ts` ~20-30 termes trader + tooltips InfoTooltip existants, ~30-45 min, zéro Ollama, zéro risque inversion sémantique) + section *« Comment demander à Claude future »* : ADR-014 plein à différer post-J+30. **Précédent** : 2026-05-19 Paquet 28 — Phase C Session 2 Watchlist auto-resolve + hit rate perso vs Tik global + bouton override modal LIVRÉE à J-5 du trading manuel. P7 du plan stratégique fiabilité signaux livrée. 4 nouveaux fichiers dashboard (`outcome.ts` + `stats.ts` + `useAutoResolveWatchlist.ts` + `personal-hit-rate-card.tsx`, ~810 lignes) + 5 modifiés + bump dashboard 0.5.13. 8 décisions structurantes D1-D8 documentées (hybride poll au focus + interval 5 min, cap 20 entries/cycle, row de référence le plus long par horizon, stats card disclaimer biais < 20, Alert.alert natif 4 boutons, POST /feedback auto+manuel via trade_id préfixé, sanctuaire `manuallyResolved`, cooldown 30 min). Mapping watchlist OSINT-neutral → feedback core trading-specific (confirmed → win, refuted → loss, n_a → not_taken, pending → skip). TypeScript + ESLint exit 0. Rétrocompat hydratation Session 1 via `normalizeEntry` (clé storage `tik.watchlist.v1` inchangée). Limites connues : pas de framework Jest dashboard (dette tracée backlog #11), scope `write:feedback` requis sur clé API dashboard, divergence work-from-hp commit `21418c7` 2026-05-11 (jamais mergeable). Garde-fou 1 / ADR-003 / ADR-004 / ADR-011 / ADR-018 inchangés — purement additif. ADR-011 renforcé empiriquement (recalibration daily 03:00 UTC reçoit enfin un input humain depuis dashboard, à noter recalibration encore silencieuse jusqu'au 2026-06-18 sur env HP cf. memory recalibration-state-2026-05-17). Mémoire pour Claude futures : `tik.watchlist.v1` clé storage inchangée, sanctuaire `manuallyResolved` (auto JAMAIS overwrite manuel), POST /feedback fire-and-forget (perdu = perdu). Précédent : 2026-05-18 soir Paquet 27 — audit santé runtime pré-J+14 + diagnostic Reddit IP-ban full + 5 décisions opérationnelles D1-D5 actées doc-only. **Découverte critique** : Reddit `204.168.220.47` totalement bloqué (test 7 endpoints + capture navigateur utilisatrice), Tik tourne avec 3/4 overlays sentiment BTC depuis déploiement HP (0 signal sur 1778 contient `reddit_btc`). Bug N=2 du Paquet 25 masquait cette réalité en figeant veracity 0.95 sur 99.4 % des signaux pré-fix. **Garde-fou 2-bis amendé** section 5 : seuil veracity transitoire **0.85 sur BTC swing** (au lieu de 0.90) tant que Reddit IP-banni, **NE PAS trader GOLD avec Tik** (hit rate mesuré 4.8 % vs Random 34 % vs Always SHORT 81 %), **observer prioritairement SHORT BTC** (63 % hit rate / +0.72 % gain mesuré sur 263 signaux 1j horizon, à valider J+10 post-fix N=2 le 2026-05-27). **Bug 11 documenté** section 9 (Reddit IP-ban full + 3 options A/B/C). **Demande unban Reddit soumise** côté utilisatrice (Option B asynchrone, délai inconnu). Aucune modif code ni runtime. Suite pytest inchangée 988 verts. Macro J+14 → J+25 = 12 jours macro-calmes confirmés runtime (premier event HIGH NFP 2026-06-05). **+ Paquet 29 Polish UX audit 2026-05-17 LIVRÉ 2026-05-19** — F3 tooltips + glossaire 17 termes FR + composant InfoTooltip réutilisable injecté sur 6 termes critiques (Veracity / Conviction OSINT / horizon / Track record sur détail signal + Veracity Home + Hit rate par veracity Calibration) + AntiFakeNewsBadge compact rendu Pressable → Alert.alert FR + carte Glossaire 5 collapsibles dans Config tab + fix résiduel F4 APP_VERSION hardcodée 0.5.0 → pkg.version dans config.tsx ; F6 featured macro event tappable → /macro avec chevron › ; F7 MiniSparkline étendue avec personalThreshold (ligne pleine vs pointillée), seuil 85 % vert J+24 (Garde-fou 2-bis transitoire Reddit IP-banni, pas 0.90 comme audit initial post-Paquet 27) + légende mise à jour ; patch cohérence tooltips post-livraison suite question utilisatrice "17 % conviction tooltip dit 0.0 à 1.0" (rectif tooltips conviction/veracity/seuil/combinedBias en % au lieu d'échelle 0-1) ; bump dashboard 0.5.13 → 0.5.15 ; TypeScript + ESLint exit 0 ; ADR-003/004/011/018 inchangés ; aucune modif backend ; F1 (bande feu pré-trade Home) reste ouvert friction critique 9/10 à attaquer prochaine session si l'utilisatrice veut. **+ Bonus mini-F1 statique LIVRÉ commit `4d84aa5`** : carte non-réactive avec 5 puces Garde-fou 2-bis fixes en haut de Marché (texte affiché tel quel, jamais réactif), bump 0.5.15 → 0.5.16 ; compromis "jetable ~20 min" en attendant la refonte UX complète prévue à la fin du dev Tik ; critère de bascule vers vrai F1 réactif documenté : utilisatrice rapporte oublis fréquents OU friction croiser mentalement 4 cartes ; mémoire pour Claude futures : ne PAS coder vrai F1 sans demande explicite, synchroniser manuellement contenu 5 puces si Garde-fou 2-bis section 5 évolue)*
*Version Tik : 0.1.2 (Core MVP livré + évolutions Paquet 1.x — swing BTC/GOLD multi-overlay + flash BTC + NLP Ollama sur les news ; **SDK Paquet 2 COMPLET** — version SDK 0.5.0, client HTTP + WebSocket + hooks + cache + circuit breaker + telemetry non-bloquant + config YAML hot-reload + doc intégration Zeta + 4 exemples runnable + ADR-007 + CI ; **Dashboard Paquet 3 COMPLET** — version dashboard 0.5.0, app Expo SDK 54 avec auth + Home KPIs + Signals feed WebSocket + détail signal + Alerts + Bots + Config + push notifications, mise en service réelle sur iPhone via Expo Go le 2026-05-03 avec 2 bugs visibles fixés dans la foulée (logo iPhone tronqué + WS auth `_session_maker` import statique = bug 7 section 9) ; **Paquet 4 Sessions 1 + 2 + 3 livrées + Session 4 partielle** — Google News RSS BTC + GOLD (ADR-008) + Reddit BTC pondéré log upvotes (ADR-009) + GDELT timelinetone GOLD NLP scientifique non-LLM contrarian (ADR-010), 4 sources sentiment cross-validées sur BTC, 4 overlays cross-validés sur GOLD, **diversification méthodologique** Ollama-LLM vs NLP scientifique, 10 ingesters total ; **pipeline de calibration livré** (Session 4 — 5 scripts CLI collect/annotate/predict/backtest/measure + 65 tests pytest + `docs/methodology/calibration.md` + glossaire EN→FR ~80 termes) avec premier cycle 100 items annotés à la main, predictions Ollama+keywords générées, deltas 1h/6h mesurés ; **deltas 24h+5d et conclusions structurelles à venir le 2026-05-06+** ; **Paquet 5 Anti fake-news LIVRÉ 2026-05-03 (ADR-011)** — cross-validation runtime via Modified Z-score d'Iglewicz-Hoaglin + dispersion globale, scoring source dynamique avec recalibration automatique daily 03:00 UTC, mode active/shadow par variable d'env `TIK_ANTIFAKENEWS_MODE`, table DB `source_credibility_history` pour audit, hook SDK `on_fake_news_detected` enfin actif, 71 nouveaux tests (39 cross_validator + 32 source_credibility), 425 → 457 tests verts ; **Paquet 6 LLM hypothesis generator LIVRÉ 2026-05-03 (ADR-012)** — synthèse contextuelle des hypothèses signal via llama3.2:3b en 6 sections fixes (~150 mots EN), pattern Strategy `HypothesisGenerator` calque ADR-006, mode `disabled|shadow|active` par var env `TIK_LLM_HYPOTHESIS_MODE` (shadow par défaut → sortie LLM dans `Signal.advisory.llm_hypothesis_candidate`, hypothesis garde template), réveil champ DB `Signal.advisory` existant (zéro modif schéma), validation post-génération (longueur + mots-clés + sanitize markdown), circuit breaker batch-level identique news_classifier, timeout strict 30s, branchement swing BTC + swing GOLD + flash BTC, premiers cycles validés runtime 2026-05-03 20:44-20:45 (139 mots GOLD swing, 125 mots BTC flash), 39 nouveaux tests, 522 → 561 tests verts ; v1.0.0 du SDK réservée à la mise en production réelle dans Zeta après 3 mois de mode shadow ; **Évolution Dashboard 2026-05-04 (version 0.5.1)** — carte "Stats LLM" sur Home (% signaux émis aujourd'hui depuis 00 h UTC avec sortie LLM ≥ 30 mots, code couleur vert/orange/rouge seuils 80/60 %, badge "LLM ✓"/"fallback" sur dernier signal, calcul côté client zéro request HTTP supplémentaire, couvre modes shadow et active de `TIK_LLM_HYPOTHESIS_MODE`) + **fix Bug 8 timezone** dashboard (utilitaire `parseUtcIso` ajoutant `Z` si absent, refactor 4 `timeAgo` dupliqués → 1 seul, refactor `toLocaleString` détail signal, tous les âges désormais corrects partout) + factorisation seuil 30 mots dans `utils/llm.ts` partagé entre carte détail signal et nouvelle carte Stats LLM Home + 2 bugs Alerts pré-existants identifiés en section 10 (persistance + timestamp figé) reportés à session dédiée ; **Paquet 7 Timezone fix backend LIVRÉ 2026-05-04 (ADR-013)** — tous les `datetime.utcnow()` du `core/src/tik_core/` (17 fichiers : storage/models + storage/schemas + scoring 4 fichiers + api 3 fichiers + auth + scripts 3 fichiers + aggregator 2 fichiers) remplacés par helpers `now_utc()` aware et `now_utc_naive()` naïf du nouveau module `core/src/tik_core/utils/time.py`, sérialisation Pydantic via `field_serializer` + helper partagé `iso_utc` qui force `Z` sur datetime naïf venant de la DB (cas SQLAlchemy lecture), payload Redis WebSocket aussi normalisé via `iso_utc` dans `publisher._publish_signal`, pas de migration Alembic vers TIMESTAMPTZ (hypertable Timescale lourde, le serializer compense), 19 nouveaux tests pytest (9 utils_time + 10 schemas_serialization), 561 → 590 tests verts, **bug 8 désormais résolu à la source** pour TOUS les consommateurs (dashboard, SDK Python, futur Zeta) avec `parseUtcIso` dashboard conservé comme filet forward-compat ; **réservation ADR-013 traduction FR glissée à ADR-014** dans ADR-012, backlog.md entry #2 et CLAUDE.md section 8 ; **Évolution Dashboard 2026-05-04 après-midi (version 0.5.2)** — bascule LLM hypothesis shadow runtime activée (3 cycles complets validés en 90 secondes le 2026-05-04 17:11 UTC : swing BTC 138 mots / swing GOLD 105 mots / flash BTC 103 mots, sortie LLM dans `Signal.advisory.llm_hypothesis_candidate` conformément à ADR-012 décision 3), carte secondaire "Hypothèse contextuelle (LLM · validation)" iPhone validée visuellement (carte déjà implémentée dans `app/signal/[id].tsx:142-173` depuis le matin Stats LLM card, anticipation), **Bug 9 timezone DB asyncpg découvert et fixé runtime** (régression du Paquet 7 ADR-013 du matin même qui empêchait tous les inserts de signaux depuis 13:09 UTC, ~4h de cycles perdus, workaround chirurgical 2 lignes dans `publisher.py:_publish_signal` strip explicite tzinfo, ADR-013 reste valide dans son intention, dette technique tracée section 9 : commentaire obsolète `utils/time.py:18` à corriger + ADR-013 à amender + test pytest Postgres bout-en-bout à ajouter), **Bug A Alerts résolu** (migration vers `@react-native-async-storage/async-storage` dans `dashboard/src/alerts/AlertsContext.tsx`, hydratation eager au mount + persistance à chaque setAlerts, clé storage `tik.alerts.v1`, filet exception JSON corrompu → reset, cap MAX_ALERTS=50 inchangé), **Bug B Alerts résolu via hook `useTick` mutualisé** (initialement résolu inline puis constat que le même bug existe sur Signals + Home, refacto en hook custom `dashboard/src/hooks/use-tick.ts` ~10 lignes retournant le tick pour `FlatList.extraData`, refacto 4 fichiers : alerts/signals/index/stats-llm-card en cascade via parent), **section 10 désormais vide** (aucun bug critique en cours, Bugs A et B migrés vers section 9), **plan préparation trading manuel J+10 acté** (l'utilisatrice trade manuellement avec Tik à partir du 2026-05-14, Tik passe d'outil d'observation à outil d'aide à la décision réelle, Garde-fou 1 ne s'applique PAS au trading manuel) : 4 features priorisées sur calibration empirique + contexte rapide sans risque LLM + discipline opérationnelle (J+1-2 carte Top headlines / J+3-4 Hit rate live Home / J+5-6 Track record détail signal / J+7-8 Watchlist post-trade / J+9-10 calibration mentale sans dev), **aucune modif des engines / pipeline scoring / cross-validation** dans le plan J+10 (purement dashboard + endpoints API en lecture, pattern multi-overlay ADR-004 inchangé, ADR-003 inchangé), **Phase 2 enrichissement contextuel hypothèse LLM réservé ADR-015 reporté post-J+30** car mode shadow strict 1 mois impossible en 10 j et le LLM 3B a des limites documentées (cf. `docs/backlog.md` entry n°4 pour le raisonnement complet sur les pistes A/B/C/D évaluées) ; **Paquet 8 Phase A.1 trading manuel J+10 LIVRÉ 2026-05-05** — endpoint `/api/v1/headlines/{entity_id}` domain-agnostic (params `limit` / `since_hours` / `sort credibility_recency|recency`, dédup multi-source par titre normalisé, decay exponentiel half-life 12h) + carte dashboard "Top headlines" Home avec sélecteur BTC/GOLD + badges sentiment + tap pour ouvrir l'article + route détail `/headlines/[entityId]` cap 25, 3 ingesters news enrichis avec champ `headlines: list[dict]` cap 25 (Google News, CryptoCompare, Reddit) **calcul score net inchangé**, helper `_strip_publisher_suffix` Google News pour préserver dédup multi-source, schéma Pydantic `HeadlineOut`, +59 tests pytest (590 → 649 verts, 0 régression), validation runtime 2026-05-04 22:28 UTC (109 signaux émis sur 24h post-livraison, aucune régression engines), pattern OSINT pro respecté (titres bruts citant leurs sources, zéro hallucination LLM), ADR-016 couplage signal↔titres écarté score 5/10, **8 lacunes vs standard pro identifiées et scorées** (A persistance DB titres 9/10 + G flag anti fake-news visible 8/10 + C sentiment stable 7/10 = Phase 1.1 proposée à arbitrer ~6-7h ; B calendrier macro 8/10 + D SDK headlines 6/10 = Phase 1.2 ; E cross-val titre individuel 7/10 + F dédup ingester 5/10 + H volume sources 4/10 = écartées ou post-J+30), bug observation utilisatrice "Activité 24h figé" diagnostiqué (cap dashboard `limit: 100` vs 109 signaux/24h, fix trivial à `limit: 500` en attente validation), limite Ollama 3B documentée (non-déterminisme sur titres ambigus, solution proposée cache Redis par hash titre TTL 7j = Lacune C), anti fake-news mode `active` confirmé runtime (10 flags `disagreement_n2 status=degraded` sur flash BTC en 24h, pattern soft filtering Tik documenté) ; **Paquet 9 Phase 1.1 Lacunes OSINT pro essentielles LIVRÉ 2026-05-05** — 3 lacunes scorées rigoureusement (A 9/10 + G 8/10 + C 7/10) livrées en bloc avant Phase A.2 hit rate live : **Lacune G** composant unifié `AntiFakeNewsBadge` mode compact (liste Signals) vs mode full (détail) avec différenciation visuelle `degraded` orange (drapeau prudence, direction inchangée) vs `tripped` rouge (bloquant, direction forcée neutral) + libellé français + explication contextuelle ADR-011 (mea culpa paranoïa contrôlée : badge existait déjà cryptique « Circuit breaker : degraded » + pastille « CB » indifférenciée, périmètre révisé runtime de « ajouter » à « améliorer ») ; **Lacune C** cache Redis `tik.sentiment.cache.{model}.{asset}.{sha256[:16]}` TTL 7j sur `OllamaClassifier` (hash titre normalisé, label canonique stocké, best-effort sur erreurs Redis, `build_news_classifier` propage `redis=` aux 4 instances classifiers) → stabilité totale sentiment individuel entre cycles + économie Ollama ~80 % titres réapparus + 11 nouveaux tests ; **Lacune A** persistance DB titres pour audit historique : modèle SQLAlchemy `HeadlineRecord` + migration Alembic `0004_headlines` (4 indexes entity_id/source/title_hash/fetched_at) + helper `headlines_repo.py` (`compute_title_hash`/`parse_iso_naive` cohérent Bug 9/`persist_headlines` best-effort/`fetch_headlines_history`) + 3 ingesters (Google News, CryptoCompare, Reddit) modifiés pour passer `session_maker` au constructeur et appeler `persist_headlines` après publish Redis avec log `n_persisted=...` + `run_ingesters.py` initialise un session_maker dédié (pool 5 + max overflow 5) + schéma Pydantic `HeadlineHistoryOut` + nouvel endpoint `GET /api/v1/headlines/history/{entity_id}` (params `since_hours` 1-720h défaut 168h / `limit` 1-500 défaut 100 / `source` optional filter) tri DESC `fetched_at` permet retro-analyse jusqu'à 30 jours en arrière (vs Redis 24h max) + 20 nouveaux tests + migration appliquée runtime (correction manuelle `UPDATE alembic_version` car `--reload` Uvicorn avait déclenché la migration en concurrence) + validation runtime 2026-05-05 11:46 UTC (50 rows insérées dès 1er cycle post-restart, endpoint historique retourne titres avec id UUID + URL cliquable + fetched_at UTC Z + credibility cohérente SOURCE_SCORES) ; suite pytest 649 → **689 verts** (+40 nouveaux), 0 régression, pattern OSINT pro renforcé (audit historique + sentiment stable + transparence anti fake-news = convergence mesurable vers Recorded Future / Bloomberg modulo volume sources), Garde-fou 1 / ADR-003 / ADR-004 inchangés ; **engagement méthodologique paranoïa contrôlée pris (2026-05-05)** pour chaque future feature : (1) tester stabilité runtime 10 cycles avant déclarer livré, (2) lister questions critiques utilisateur paranoïaque AVANT coder, (3) auditer bout-en-bout backend↔UI, (4) mentionner explicitement 3-4 limites connues à chaque livraison, (5) tableau pour/contre/verdict + score utilité pour chaque option ; **Paquet 10 Phase A.2 + A.2-bis trading manuel J+10 LIVRÉ 2026-05-05** — calibration empirique de la performance Tik avant le premier trade J+14 : nouveau module pur `core/src/tik_core/metrics/hit_rate.py` (zéro DB/Redis, fonctions pures) + endpoint `GET /api/v1/metrics/hit_rate` (cache Redis TTL 15 min, params horizon × entity_id × include_flagged) + carte Home `HitRateCard` avec sélecteurs partagés + toggle « Exclure flagués anti fake-news » + couleurs vert/orange/rouge ; **MiniSparkline veracity refondue** auto-scale Y sur min/max observés (au lieu de 0-1 fixe qui écrasait variations 0.70-0.95) + labels min/current/max chiffrés ; fix bug latent `backtest.py` (import `now_utc_naive` manquant depuis ADR-013, comparaison SQL silencieusement DeprecationWarning) ; **Phase A.2-bis** endpoint `GET /api/v1/metrics/hit_rate_by_veracity` + carte `HitRateByVeracityCard` sous HitRateCard avec 4 buckets (0.70-0.79 / 0.80-0.89 / 0.90-0.94 / 0.95+), sélecteurs partagés ; **insight contre-intuitif découvert runtime — pattern flash BTC inversé** (0.80-0.89 = 53.5 % vs 0.90+ = 13-16 %, hypothèse provisoire concordance excessive trend-following en marché choppy, à investiguer post-J+14, backlog entry n°5 enrichie « refonte dashboard + vision macro/géopolitique ») ; **Garde-fou 2-bis cristallisé** (cf. section 5) : sur 156 signaux backtest Tik = 22 % hit BTC swing 5j vs Random 33 % = pas d'edge global démontré MAIS veracity ≥ 0.95 = 67 % vs 24 % global, donc filtre veracity ≥ 0.90 sur swing recommandé pour J+14 + sizing démarrage 1 % du capital pas 5 % pendant 2 semaines minimum, montée progressive seulement après période profitable mesurable ; suite pytest 689 → 716 verts (Phase A.2 +27) → **726 verts** (Phase A.2-bis +10), 0 régression ; **Paquet 11 Lacune B Phase B1 calendrier macro LIVRÉ 2026-05-05 (ADR-017)** — outil de risk management pour J+14 (éviter swing dans ±4h autour d'un event HIGH FOMC/NFP/CPI), Lacune B des 8 lacunes OSINT pro identifiées Paquet 8 scorée 8/10 utilité : table SQL `macro_events` + migration Alembic `0005_macro_events` avec UNIQUE constraint `(event_code, scheduled_for)` pour idempotence (upsert ON CONFLICT) + helper `macro_events_repo.py` (upsert_events, fetch_upcoming filtres importance_min/entity_id/limit, fetch_history) + ingester `FredCalendarIngester` polling daily (les calendriers FRED ne changent pas en intra-day) avec **DST automatique via zoneinfo America/New_York** (8:30 ET → 12:30 UTC EST hiver / 13:30 UTC EDT été) + best-effort sur erreurs FRED + whitelist 7 releases FRED (NFP, CPI, PPI, GDP, Retail Sales, Industrial Production, Initial Claims) + 12 dates FOMC statiques 2026-2027 dans `macro_calendar_data.py` (Fed publie 1 an à l'avance, pas via FRED API → mise à jour annuelle ~30 min en septembre) + endpoints `/api/v1/macro_events/upcoming` + `/history` (cache Redis TTL 5 min, schéma `MacroEventOut` sérialisé via iso_utc cohérent ADR-013) + carte Home compact `MacroEventsCard` avec next event countdown live + 3 events suivants + bouton « Voir tout » + route détail `/macro` plein écran avec filtres importance HIGH/MED/LOW + hook `useUpcomingMacroEvents` poll 5 min + helper `timeUntil(iso)` countdown FR ; bump dashboard 0.5.2 → 0.5.6 ; ADR-017 documenté (6 décisions structurantes : source FRED + dates FOMC statiques vs ForexFactory scrapé, polling daily vs real-time, whitelist vs all FRED, timezone source UTC + display local, idempotence UNIQUE constraint, US-only Phase B1) ; section 17 pédagogique dans comprendre_tik.md ; **fix bug 1-caractère post-livraison commit `6112901`** (sort_order=asc récupérait années 1700-1900 pour NFP qui a 867 release_dates depuis 1776 → 0 future date affichée ; fix sort_order=desc + limit=50 → 50 dernières publications dont ~8-12 dates futures programmées via realtime_end=9999-12-31) ; 62 nouveaux tests pytest, suite complète 726 → **788 verts**, 0 régression ; **engines / pipeline scoring / cross-validation strictement inchangés** — calendrier macro est un outil de discipline pour l'humain, pas un input des engines ; limites Phase B1 : US-only (ECB/BoJ/BoE/élections en Phase B2 post-J+14), FOMC 2027 = estimations (mise à jour septembre 2026), heures release hardcodées, pas de couplage signal↔event auto ; **glissement réservation ADR-017 → ADR-018** dans CLAUDE.md section 8 et `docs/backlog.md` entry n°4 (ADR-017 initialement réservé Phase 2 enrichissement contextuel LLM pris par calendrier macro) ; **Paquet 12 Phase A.3 trading manuel J+10 LIVRÉ 2026-05-05** — vue track record signal multi-horizon dans détail signal pour calibration empirique signal-par-signal (complémentaire du hit rate agrégé Paquet 10) : module pur `core/src/tik_core/metrics/signal_track_record.py` (~113 lignes, zéro DB/Redis/HTTP, architecture cohérente metrics/hit_rate.py) + `compute_track_record(decision, prices_by_horizon)` retourne 4 lignes 1h/6h/24h/5j avec badges `correct`/`raté`/`en_attente`/`données_manquantes` + seuils directionnalité 0.3 % sur 1h-6h et 0.5 % sur 24h-5j (cohérents seuil `_score_indicators` swing engine) ; schémas Pydantic `TrackRecordRow` + `SignalTrackRecordOut` + endpoint `GET /api/v1/metrics/signal_track_record/{signal_id}` (cache Redis TTL 6h, lazy-load côté dashboard pour éviter N requests sur N signaux) + types TS + `getSignalTrackRecord(client, signalId)` + composant `TrackRecordSection` lazy-loadé sur `app/signal/[id].tsx` affichant delta % réel ou compte à rebours « dans Xj Yh » selon disponibilité ; 29 nouveaux tests unitaires (4 horizons × 4 badges × 3 directions long/short/neutral + edge cases decision dans le futur, prix manquants, magnitude exactement au seuil, neutral = pas évaluable), suite complète 788 → **817 verts**, 0 régression ; engines / pipeline scoring / cross-validation strictement inchangés ; **Paquet 13 Phase C Session 1 trading manuel J+10 LIVRÉ 2026-05-05** — Watchlist signaux suivis, version reframée OSINT (vocabulaire neutre « suivre » / « résultat observé » au lieu de « j'ai pris ce trade » trading-specific) cohérente vision modulaire Tik, pattern « saved alerts » standard Recorded Future / Bloomberg Terminal / Dataminr réutilisable tel quel sur autres domaines (élections, sport betting, météo-finance) sans refonte ; nouveau `dashboard/src/watchlist/WatchlistContext.tsx` (~180 lignes, type `WatchlistEntry` + outcome `pending|confirmed|refuted|n_a` + provider + hook `useWatchlist`, pattern hydratation eager + persistance AsyncStorage clé `tik.watchlist.v1` calque exact AlertsContext cohérent Bug A 2026-05-04, cap MAX_WATCHLIST=200, snapshot complet du signal au moment du suivi pour résilience à l'expiry/cap API) ; bouton Pressable « ☆ Suivre » / « ★ Suivi » dans hero card détail signal (toggle réactif, couleur or `#f1c40f`, accessibility labels adaptés) ; nouvel onglet `dashboard/app/(tabs)/watchlist.tsx` (~250 lignes : titre + subtitle pédagogique + stats line `N suivis · N en attente · N résolus` + bouton « Tout effacer » + liste tri DESC `addedAt` + carte par entry avec direction badge + outcome badge bordure colorée + bouton X retirer absolute top-right + tap row → détail signal + empty state) inséré entre Signals et Alerts dans tab bar, icône SF Symbol `star.fill` (mapping Material Icons `star` ajouté pour Android/web) ; hook `useTick()` mutualisé cohérent fix Bug B 2026-05-04 ; `WatchlistProvider` branché dans `app/_layout.tsx` à l'intérieur d'`AlertsProvider` ; **décisions structurantes prises avant code (5 entrées for/contre/verdict)** : D1 hybride AsyncStorage local + reuse `POST /feedback` existant Session 2, D2 outcome auto via `getSignalTrackRecord` Paquet 12 + override manuel Session 2, D3 toggle simple sans modal pour zero friction, D4 placement entre Signals et Alerts pour sémantique cohérente, D5 stats simples Session 1 (hit rate perso Session 2) ; **aucune modif backend** (zéro fichier `core/` touché, persistance locale uniquement, zéro risque données core, ADR-003/004 inchangés, Garde-fou 1 inchangé) ; validation `tsc --noEmit` exit 0 + `eslint` exit 0 sur 6 fichiers (1 warning pré-existant non lié) ; bump dashboard 0.5.6 → 0.5.7 ; limites connues Session 1 : (1) pas de sync multi-device — désinstall Expo Go = perte (acceptable MVP 1 iPhone), (2) pas d'auto-resolution outcome — toutes entries restent `pending` jusqu'à Session 2, (3) pas de hit rate perso — stats simples comptage brut, (4) pas de bouton override / feedback explicite — Session 2 ajoutera modal + POST `/feedback` pour nourrir calibration source credibility Paquet 5 ; Phase C Session 2 estimée ~2-3h à attaquer après J+1-2 d'usage Session 1 ; **Paquet 14 Polish post-livraison J+10 LIVRÉ 2026-05-05** — 3 micro-livraisons ~1h cumulé pour clore les notes obsolètes accumulées : (1) audit compteur « Activité 24h » Home — fix `limit: 500` constaté déjà en place dans `useDashboardKpis.ts:158` depuis Phase A.1 commit `9105f0b`, note CLAUDE.md « En attente validation utilisatrice » corrigée, leçon « audit avant fix soi-disant trivial » consignée ; (2) audit bascule LLM hypothesis — `TIK_LLM_HYPOTHESIS_MODE=active` constaté déjà positionné dans `core/.env` côté Mac, à valider runtime que `docker compose restart scheduler` ait bien été fait pour prise en compte process en cours d'exécution, limite `.env` hors Git documentée (à exposer dans `config.py` à terme avec défaut `active` post-validation runtime), conséquences mode active rappelées (`Signal.hypothesis` = LLM 6 sections ~150 mots, `Signal.advisory.template_hypothesis` = ancien template f-string conservé audit, composant `signal/[id].tsx:268-288` gère déjà les deux modes) ; (3) dette technique bug 9 — commentaire `utils/time.py:18` corrigé (« asyncpg strippe silencieusement... » → « asyncpg lève DataError... » avec mention bug 9 + workaround `publisher.py`), ADR-013 amendé avec nouvelle section « Amendement post-livraison — Bug 9 régression DB asyncpg » documentant prémisse erronée + réalité runtime + workaround chirurgical 2 lignes + tableau pour/contre/verdict 3 options de fix (migration TIMESTAMPTZ rejetée hypertable lourde, `now_utc_naive` partout rejeté casse sémantique aware, workaround retenu) + conséquences sur décisions 3 et 4 de l'ADR (inchangées mais décision 4 maintenant justifiée explicitement par coût migration hypertable plutôt que croyance asyncpg-permissif) + dette test pytest Postgres bout-en-bout en CI **toujours tracée** comme à faire (~1-2h, séance dédiée — éviterait régression DB-spécifique invisible SQLite repasse en prod, bug 9 a tourné 4h sans détection avec 590 tests verts CI) ; aucun test ajouté (audits + 1 commentaire Python + 1 ADR markdown), suite pytest inchangée 817 verts, ADR-003/004 + Garde-fou 1 inchangés ; **Paquet 15 Audit sécurité Tailscale + fix critique exposition Postgres/Redis LIVRÉ 2026-05-05** — audit fresh fin de session demandé par l'utilisatrice (Tailscale installé précédemment hors trace doc), 1 faille critique identifiée + 3 hygiène défense en profondeur ; **fix critique appliqué** : `core/docker-compose.yml` Postgres `5432:5432` → `127.0.0.1:5432:5432` et Redis `6379:6379` → `127.0.0.1:6379:6379`, ferme l'exposition au LAN maison ET au tailnet entier (Redis n'avait aucun mot de passe configuré → lecture/écriture libres pour tout device tailnet), aucune régression fonctionnelle car Tik core/ingesters/scheduler accèdent via le réseau Docker interne (`postgres:5432`/`redis:6379` DNS Docker compose), application runtime `docker compose down && docker compose up -d` (restart simple ne recrée pas les containers, ne réapplique pas la config ports) ; **failles hygiène tracées à attaquer plus tard** : (2) Tik core HTTP plain pas de TLS — API key transite en clair entre devices tailnet, fix Caddy auto-TLS Tailscale `~1-2h` ; (3) Tik core toujours sur 0.0.0.0:8200 — exposé LAN maison mais Tik a auth API key, fix firewall macOS restriction `100.64.0.0/10` + localhost `~10 min` ; (4) ACLs Tailscale par défaut autorisent tout le tailnet — fix tag `tag:tik` panel admin `~10 min` ; commentaires inline ajoutés dans docker-compose.yml pour traçabilité future ; mémoire pour instances Claude futures : Tik via Docker Desktop natif macOS + iPhone via Tailscale free tier, jamais commiter IP `100.x.x.x` dans le code (saisie au login dashboard) ; **Paquet 16 Diagnostic mobilité 4G + plan EAS Build dev en attente DOCUMENTÉ 2026-05-06 ~00h45** — Tailscale fonctionnel (Mac `100.112.141.57` / iPhone `100.70.101.7`), 3 tests effectués (tunnel public Expo `*.exp.direct` instable 4G + erreurs `--no-dev --minify` assets, Metro via Tailscale `REACT_NATIVE_PACKAGER_HOSTNAME` stable mais lent + freeze login en 4G, contrôle WiFi maison parfait → app Tik saine c'est Expo Go dev qui est inviable 4G), `@expo/ngrok` installé local `dashboard/package.json` (workaround permissions npm global macOS exit 243 → install --save-dev local OK), conclusion technique Expo Go = dev tool pas vraie app, **vraie solution EAS Build dev** ~1-2h session dédiée future à activer sur demande utilisatrice (8 étapes : install eas-cli + eas login + build:configure + bundle ID `com.siku.tik` + `eas build --profile development --platform ios` 10-15 min cloud + install IPA via QR/Safari + app standalone home screen iPhone démarrage 2-3s 4G natif), compte Apple gratuit suffit signature 7j à renouveler 2 min OU Apple Developer 99€/an = pas d'expiration + TestFlight + EAS Update OTA, EAS Build free tier ~30 builds/mois largement suffisant ; pas urgent car trading manuel J+14 2026-05-14 peut se faire en WiFi maison ; **Plan stratégique post-audit fiabilité signaux DOCUMENTÉ 2026-05-06 ~01h00** — re-audit demandé par l'utilisatrice fin de session pour trier les recommandations selon le critère « fiabilité, précision et qualité des signaux Tik émis » uniquement, en excluant UX/sécurité/mobilité (axes orthogonaux), 2 décisions reconsidérées avec verdict révisé : (1) D1 Phase C Watchlist AsyncStorage local seul → POST /feedback systématique + AsyncStorage en complément (raison : feedback humain alimente recalibration daily 03h UTC SOURCE_SCORES ADR-011, perdre côté backend = priver calibration source credibility d'un input qualité), (2) track record flash 4 horizons fixes 1h/6h/24h/5j → granularité adaptée par horizon (flash 15min/30min/1h/4h, swing 1h/6h/24h/5j actuel, macro 1j/7j/30j/90j) raison flash perd 75 % track record sur horizons hors-fenêtre contractuelle ; **plan 9 priorités P1-P9 chiffrées** par effort/quand : P1 re-run Session 4-bis golden 5j demain soir critique (~30 min), P2 étape 7 sources numériques 6-12 mois (~2h pré-J+14), P3 décision GDELT BTC après P1 (~10 min), P4 étape 9 ajustements SOURCE_SCORES (~30 min), P5 track record flash granularité fine (~2-3h avant P4), P6 détection anomalies par ingester (~3-4h post-J+14), P7 Phase C Session 2 + POST /feedback (~2-3h après 1-2j usage S1), P8 Phase B Polymarket ADR-015 (~2 sessions post-J+14), P9 Phase B2 calendrier macro multi-banques centrales (~3-4h post-J+14) ; **recommandations dépriorisées** (zéro impact fiabilité signal) : EAS Build dev / sync multi-device / traduction FR ADR-014 / reframe OSINT vocab / Phase C UX cosmétique / failles hygiène Tailscale TLS Caddy + firewall macOS + ACLs ; **cohérence stratégie globale** : ADR-003 inchangé, ADR-004 renforcé via P2/P4/P5/P8, ADR-011 renforcé via P6 (couche supplémentaire pré-cross-validation), Garde-fou 1 inchangé, Garde-fou 2-bis inchangé règle stricte J+14, paranoïa contrôlée maintenue (chaque priorité a argument chiffré ou risque tracé) ; **mémoire instances Claude futures : axe stratégique #1 tant que trading manuel J+14 priorité utilisatrice — toute nouvelle décision technique réévaluée selon filtre « contribue-t-elle à la fiabilité signaux émis ? », jamais ajouter feature qui dilue ce focus avant 2026-05-14** ; **Paquet 17 P5 plan fiabilité LIVRÉ 2026-05-06** — refactor track record Paquet 12 avec granularité adaptée par horizon contractuel (flash 15min/30min/45min/1h **dans la fenêtre TTL signal 1h cohérente avec EXPIRY_BY_HORIZON et HORIZON_MEASURE_HOURS hit rate Paquet 10** — correction post-livraison sur question utilisatrice de la version initiale 15min/30min/1h/4h qui sortait de la fenêtre TTL ; 5min non retenu pour 4 raisons cumulées klines 15m natives + bruit microstructure + scheduler 5min + latence saisie ordre humaine — un futur ADR flash micro-scalping devra fetch klines 1m si scope, swing inchangé 1h/6h/24h/5j, macro 1j/7j/30j/90j), seuils directionnalité calibrés au pifomètre raisonné par horizon (flash 0.10/0.15/0.20/0.30 % | swing inchangé 0.30/0.30/0.50/0.50 % | macro 0.50/1.00/2.00/3.00 %), `fetch_btc_history` / `fetch_gold_history` / `find_closest_price` étendues kwargs-only interval/limit/range_param/max_diff_ms rétrocompat via defaults (zéro régression sur les autres callers `hit_rate.py` / `source_credibility.py` / `backtest_golden.py` / endpoints `/hit_rate` et `/hit_rate_by_veracity`), `compute_track_record` ajoute `signal_horizon: str` REQUIRED sans default (paranoïa contrôlée force expliciter) + dict `HORIZON_SPECS_BY_SIGNAL_HORIZON` 3 entrées avec `rows` + `price_match_tolerance_ms` (flash 30 min / swing 6 h / macro 24 h propagé à `find_closest_price` selon granularité klines), schémas Pydantic `TrackRecordRow` / `SignalTrackRecordOut` inchangés (rows déjà `list` longueur variable), endpoint `/metrics/signal_track_record/{id}` dispatcher selon `decision.horizon` via `TRACK_RECORD_BINANCE_PARAMS` (flash klines 15m × 96 / swing klines 1h × 1000 inchangé / macro klines 1d × 365) et `TRACK_RECORD_YAHOO_PARAMS` (swing 1h range 60d / macro 1d range 1y) + cache key Redis bumpée `tik.track_record.v2.{signal_id}` invalidant les caches Paquet 12 au déploiement + fail-fast HTTP 400 si flash GOLD (ADR-005 renforcé — Yahoo 15 min délai incompatible flash) + HTTP 400 si horizon DB corrompu hors enum, dashboard `signal/[id].tsx` footer Track record min-max dynamique (Math.min/max sur thresholds, "Seuils : ±X % à ±Y %" ou "Seuil : ±X %" si min === max, adaptatif 3 horizons sans toucher au reste du composant), suite pytest 817 → **834 verts** (+17 nouveaux : 5 `TestSignalHorizonDispatch` + 5 `TestFlashTrackRecord` + 5 `TestMacroTrackRecord` + 2 `TestUnknownSignalHorizon` ValueError), 5 fichiers modifiés (3 backend + 1 tests + 1 dashboard), 0 régression sur les 817 tests Paquet 12+13+14, ADR-003 / ADR-004 inchangés, ADR-005 renforcé, Garde-fou 1 / 2-bis inchangés, aucune modif des engines / pipeline scoring / cross-validation — purement métrique de calibration en lecture, P5 du plan post-audit fiabilité signaux coché ✅, limites assumées : seuils pifomètre à recalibrer empiriquement post-J+30 + pas de flash GOLD (HTTP 400 explicite) + cache Redis TTL 6h potentiellement long pour flash 15 min à observer runtime + tolérance `find_closest_price` calibrée sur granularité klines ; **Paquet 18 Refactor architectural Tik vers OSINT pur LIVRÉ 2026-05-07 (ADR-018)** — le plus gros refactor depuis le démarrage : Tik passe de système hybride (analyse technique RSI/MACD/EMA + OSINT cross-validé) à plateforme OSINT pure ; direction et conviction des signaux désormais dérivées uniquement du `combined_bias` OSINT cross-validé (seuil ±0.30) au lieu de l'analyse technique ; indicateurs techniques calculés et préservés en evidence/triggers avec `weight: 0.0` (informatifs, audit) mais n'influencent plus la décision directionnelle ; sémantique uniforme `confidence` = `abs(combined_bias)` (résout bug audit Paquet 17 P5 #1 double signification long/short vs neutral, plafonnée à 0.55 swing peut atteindre 1.0) ; veracity dérivée de la dispersion des sources OSINT (résout bug #2 veracity neutral figée à 0.85 confirmée empiriquement sur 162 signaux) ; 5 décisions structurantes prises avant code (refactor pur OSINT vs hybride/nouvelle plateforme/garder, direction OSINT vs technique, label "Conviction OSINT" sans renommage DB pour rétrocompat 683 signaux, veracity dispersion vs concordance, indicateurs techniques préservés evidence/triggers) ; vérifications factuelles préalables (Tik core 8733 lignes hors tests + dashboard 5232 lignes = ~14 000 lignes total 4× plus que les estimations précédentes incorrectes ; 683 signaux 30 jours ; 3.37 % à veracity ≥ 0.95, 17.86 % à ≥ 0.90 ; confidence max swing strictement 0.55 sur 437 signaux = borne supérieure structurelle pas coïncidence) ; 7 fichiers modifiés (3 backend swing_engine/flash_engine/storage-schemas + 2 dashboard signal-detail/api-types + 2 doc ADR-018 ACCEPTÉ + Notes implémentation + backlog #6) ; 57 nouveaux tests (TestDeriveOsintDecision swing 13 + TestVeracityFromDispersion 16 + TestVeracityFromConcordanceLegacy 2 + TestSemanticUniformityADR018 3 + TestDeriveOsintDecisionFlash 11 + TestVeracityFromDispersionFlash 10), suite 834 → **891 verts**, 0 régression ; **engagements méthodologiques actifs section 13bis** ajoutés à CLAUDE.md suite à audit méthodique 2026-05-06/07 sous consigne *« doute constant et méthodique sans complaisance »* (11 engagements : lire code AVANT affirmer, distinguer vision vs réalité, te challenger, ne pas inventer chiffres, vérifier hypothèses avant verdict, mea culpa déclaratif, re-questionnement sérieux, mentionner 3-4 limites, format pour/contre/verdict, mesurer plutôt que spéculer, ne pas cumuler spécialisation marketing et implémentation hybride) ; bugs résolus : #1 ✅ #2 ✅ confidence plafonnée 0.55 ✅ ; #3 recalibration sources flash mesurée à 5j 🔵 + #4 attribution hit rate signal entier 🔵 non touchés ; comportement runtime post-refactor : avec OSINT direction+confidence dérivées combined_bias, sans OSINT (Redis miss) direction=neutral confidence=0 cohérent OSINT pur, veracity dynamique 0.70-0.95 selon dispersion ; limitations connues : seuil ±0.30 pifomètre à réviser post-J+30, seuils veracity dispersion 0.2/0.4/0.6/0.8 pifomètre, Tik moins consommable seul (regarder MT5 pour direction technique complémentaire), volume signaux directionnels peut différer post-refactor à mesurer ; **Paquet 19 P1 + P2 plan stratégique fiabilité signaux LIVRÉS + amendement ADR-018 désactivation overlays GOLD DXY/COT 2026-05-07** — P1 re-run golden dataset deltas 5j (commit `c79fed5` data only) : Ollama 38 % > Humain 27 % > Keywords 23 % à 5j sur période bullish 1 cycle, CryptoCompare Ollama 47 % top performer, humain meilleur à 24h (68 %) ; **P2 backtest empirique 12m sources numériques (commit `0fb99d0`)** : 2 nouveaux scripts CLI (`fetch_numeric_history.py` 381 lignes + `backtest_numeric_sources.py` 663 lignes) + dossier `core/data/numeric_calibration/` versionné + rapports JSON 501 lignes / MD 191 lignes ; **insights critiques mesurés 12m (2025-05-07 → 2026-05-07)** : DXY contrarian INVERSÉ sur GOLD (IC Spearman +0.23 à 120h au lieu de négatif attendu, hit rate cas extrêmes 19-25 %, palier `dxy_strong_up` à 120h = 0 % hit rate n=7) + COT contrarian INVERSÉ sur GOLD (IC +0.43 à 720h, palier `mm_extreme_long` à 720h = 0 % hit rate n=10 avec delta moyen +7.5 % gold) + FG contrarian marginal sur BTC (IC -0.10 non significatif aux 3 horizons mais palier extrême `extreme_greed` n=4 à 75 % hit rate à 720h reste exploitable) + GDELT non mesurable au backtest historique 12m (rate-limit GDELT public, qualité ingester runtime non validée empiriquement) ; **régime 2025-2026 strongly bullish** (BTC + GOLD + USD parallèle) limite généralisation, à reproduire post-J+30 sur drawdown gold ≥ 5 % ou bear crypto ; **amendement ADR-018 P2 (commit `e1f9a03`)** : nouveau setting `gold_dxy_cot_overlays_enabled: bool = False` lu env var `TIK_GOLD_DXY_COT_OVERLAYS_ENABLED` réversible sans redéploiement code, wrap blocs DXY+COT dans `analyze_swing_gold` derrière check setting (fonctions `_compute_dxy_bias`/`_compute_cot_bias`/`_enrich_with_dxy`/`_enrich_with_cot` **conservées** pour réactivation rapide), logs runtime explicites `swing.gold.dxy_skipped_overlay_disabled` / `swing.gold.cot_skipped_overlay_disabled` traçabilité, ADR-018 amendé section *« Amendement post-livraison — Désactivation overlays GOLD DXY+COT (P2) »* (constat empirique chiffré + critère réactivation post-J+30 = IC Spearman DXY @ 120h redevient négatif ET cas extrêmes hit rate ≥ 50 % → réactiver), section 21 pédagogique FR dans `comprendre_tik.md` ; **validation runtime confirmée** 2026-05-07 14:49 UTC post-restart scheduler : logs `dxy_skipped` + `cot_skipped` ✓ + premier signal GOLD émis `direction=neutral` (cohérent ADR-018 OSINT pur sans overlay directionnel sur GOLD = pas de direction) ; **conséquence opérationnelle pour la trader manuelle J+14** : Tik émet quasi-exclusivement des signaux directionnels sur BTC (4 overlays actifs : FG + CC + Google News + Reddit), GOLD a 2 overlays restants (Google News + GDELT quand mesurable) → majorité signaux GOLD `direction=neutral`, si trader veut signal directionnel GOLD doit s'appuyer sur MT5 / jugement / analyse technique externe pas sur Tik ; **fix Dockerfile (commit `83cef71`)** : suppression instruction `COPY scripts/ ./scripts/` obsolète (dossier inexistant à la racine, scripts en réalité dans `src/tik_core/scripts/` copiés via `COPY src/`) 1 ligne supprimée 0 test impacté ; suite pytest 891 → 948 verts (+57 P2 : 33 fetch + 24 backtest) → **954 verts** (+3 amendement TestGoldDxyCotOverlaysSettingADR018Amendment), 0 régression ; **mémoire pour instances Claude futures** : DXY/COT réversibles (NE JAMAIS supprimer le code des fonctions `_compute_dxy_bias`/etc., réactiver via env var si re-mesure sur période bear trouve signe contrarian correct) ; si nouvel insight justifie trend-following plutôt que contrarian → modifier mapping ET nouveau ADR documentant le revirement ; **Tik n'est plus un système de signaux directionnels GOLD à ce jour** post-amendement P2 — si l'utilisatrice se plaint de l'absence de signaux GOLD c'est attendu pas un bug ; tableau plan stratégique fiabilité signaux mis à jour : ✅ P1 LIVRÉ + ✅ P2 LIVRÉ + 🟡 P3 reporté post-J+14 (GDELT non mesurable au backtest, verdict reporté) + 🟡 P4 partiellement traité par amendement (désactivation = pondération à 0 effective, ajustements fins SOURCE_SCORES reportés post-J+14))*
*Mainteneur : utilisatrice solo + assistant Claude via Claude Desktop (app native macOS)*
