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

### Garde-fou 2 — Budget de test limité

Quand on passera de shadow à actif, démarrage avec un compte Zeta de test séparé contenant **au maximum 5% du capital**. Pendant 1 mois minimum.

**Toute instance Claude qui propose de lever ces garde-fous doit alerter l'utilisateur explicitement et lui rappeler ces règles.**

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

### Paquet 2 — SDK Python : ⏳ À FAIRE

À implémenter dans `Tik/sdk/` :
- Package `tik-sdk` pip-installable
- Client HTTP + WebSocket vers le core
- Cache local Redis ou in-memory avec TTL
- Fallback offline si core indisponible
- Hooks événementiels : `on_signal`, `on_crash_warning`, `on_fake_news_detected`, `on_veracity_collapse`
- Circuit breaker LOCAL (indépendant du core)
- Telemetry retour automatique (`/feedback`)
- Config YAML hot-reloadable
- Tests
- Documentation d'intégration Zeta (overlay sur `turbo_v2.py`)

### Paquet 3 — Dashboard Expo : ⏳ À FAIRE

À implémenter dans `Tik/dashboard/` :
- App Expo SDK 54+ avec Expo Router
- Auth (login + storage push token Expo)
- Écrans : home (KPIs live), signals feed (WebSocket), alerts, bots Zeta/Totem, config
- Charts via Victory Native XL ou Skia
- Notifications push (Expo Push) avec deep links
- Connexion API + WebSocket vers Tik core local
- Future : connexion API Zeta existante pour afficher état trading

### Couches encore non-implémentées (évolutions futures)

- Engine macro (semaines-mois) — partiellement couvert via FRED
- Flash GOLD (bloqué par le délai 15 min de Yahoo Finance — nécessite une source temps réel alternative)
- Module anti-fake-news (cross-validation, scoring source dynamique) — l'infra Ollama est désormais en place, prête à être réutilisée
- Ingester news : Google News RSS, CryptoPanic, Reddit, Nitter (Twitter)
- Marchés prédictifs : Polymarket, Kalshi
- Backtesting service
- Data alternative : Google Trends

---

## 9. Bugs connus et résolus

6 bugs identifiés et corrigés depuis le démarrage du projet (les 3 premiers pendant le déploiement initial du Paquet 1, les 3 suivants pendant les évolutions post-livraison du 2026-04-28) :

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

**Ces 6 fixes sont déjà appliqués dans le code actuel** (et poussés sur GitHub).

---

## 10. Bugs non résolus / améliorations à faire

✅ **Pas de bug ouvert connu actuellement.**

Cette section sera repeuplée si de nouveaux bugs sont identifiés. Pour les évolutions fonctionnelles à venir (nouvelles sources, engines flash/macro, NLP, backtest, etc.), voir la section 8 — *Couches encore non-implémentées*.

---

## 11. Workflow de l'utilisateur

L'utilisateur est sur **macOS Tahoe 26.0** (Mac M1 Apple Silicon).

**Outils installés et fonctionnels** :
- VS Code avec extension Claude Code (Anthropic) — outil principal
- Docker Desktop — fait tourner Tik
- GitHub Desktop — gestion Git visuelle (l'utilisateur ne maîtrise PAS les commandes Git en ligne de commande)
- Ollama (app native macOS, installée le 2026-04-30 via le .dmg officiel sans Homebrew) avec le modèle `llama3.2:3b` téléchargé localement (~2 GB). Utilisé par le `OllamaClassifier` du ingester CryptoCompare (cf. ADR-006). L'app tourne en service au démarrage, l'icône lama est visible dans la barre de menus Mac. Les conteneurs Docker l'atteignent via `http://host.docker.internal:11434`. **Réutilisable pour tout futur besoin NLP** (module anti-fake-news, génération d'hypothèses, etc.).
- Le repo GitHub Tik est privé

**Outils NON installés** (et qui ont posé problème) :
- Homebrew — abandonné car nécessite Xcode Command Line Tools
- Xcode Command Line Tools — bloqué (la version dispo Apple Developer 26.4.1 exige macOS 26.2)
- jq — abandonné, on utilise `plutil -convert json -r -o - -` à la place pour formater le JSON
- Claude Desktop — bloqué par un bug d'auth email

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

*Dernière mise à jour : 2026-04-30*
*Version Tik : 0.1.0 (Core MVP livré + évolutions Paquet 1.x — swing BTC/GOLD multi-overlay + flash BTC + NLP Ollama sur les news)*
*Mainteneur : utilisateur solo + assistant Claude via extension VS Code*
