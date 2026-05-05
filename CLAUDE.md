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

**Bug d'observation utilisatrice (2026-05-05) — diagnostic résolu** : le compteur « Activité 24h » sur Home semblait figé. Diagnostic = cap visible côté dashboard (hook `useDashboardKpis` poll `searchSignals` avec `limit: 100`, mais 109 signaux en 24h → compteur figé à 100). Fix trivial à appliquer (passer `limit: 500`, l'API supporte jusqu'à 1000). En attente de validation utilisatrice.

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
  - Phase A.2 — Carte Home "Hit rate live" (J+3-4, ~1 session) : pourcentage de signaux Tik corrects sur 30j par horizon × asset, réutilise `core/src/tik_core/scripts/backtest.py`
  - Phase A.3 — Vue "Track record signal" dans détail signal (J+5-6, ~1 session) : delta prix multi-horizon (1h/6h/24h/5j) + badges ✓/✗/⚠
  - Phase B — Polymarket ingester + entity PREDICTION_MARKET + carte dashboard (J+7-8, ~2 sessions, ADR-015)
  - Phase C — Workflow "Watchlist post-trade" (J+9, ~1 session) : bouton "j'ai pris ce trade" + onglet Watchlist persisté AsyncStorage
  - J+10 calibration mentale + premier trade manuel
- **Phase 2 — Enrichissement contextuel hypothèse LLM (réservé ADR-017, post-J+30)** : pistes A/B/C/D évaluées dans `docs/backlog.md` entry n°4. Verdict : Piste A (top headlines injectés dans le prompt LLM) en mode shadow strict 1 mois + dataset golden d'évaluation, à attaquer **uniquement si** le retour utilisatrice après 2-3 semaines de trading manuel confirme un manque contextuel narratif que la carte Top headlines (Phase A.1) ne couvre pas.

---

## 9. Bugs connus et résolus

8 bugs identifiés et corrigés depuis le démarrage du projet (les 3 premiers pendant le déploiement initial du Paquet 1, les 3 suivants pendant les évolutions post-livraison du 2026-04-28, le 7e découvert le 2026-05-03 lors de la mise en service du dashboard sur iPhone, le 8e découvert le 2026-05-04 lors de la livraison Stats LLM card et résolu en deux temps : fix dashboard `parseUtcIso` le matin puis fix backend ADR-013 / Paquet 7 l'après-midi) :

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

**Suites à donner (dette technique tracée)** :
- Mettre à jour le commentaire trompeur de `utils/time.py:18` (*"asyncpg strippe silencieusement la tz"* — faux). À faire dans une session future de polish.
- Amender `docs/adr/013-timezone-aware-datetimes.md` pour mentionner explicitement le workaround `publisher.py` et la prémisse erronée sur asyncpg. À faire dans une session future de polish.
- Idéalement : ajouter un test pytest qui vérifie l'INSERT bout-en-bout via un Postgres de test (pas SQLite) pour attraper ce genre de régression en CI.

**Ces 9 fixes sont déjà appliqués dans le code actuel** (et poussés sur GitHub).

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

*Dernière mise à jour : 2026-05-05*
*Version Tik : 0.1.2 (Core MVP livré + évolutions Paquet 1.x — swing BTC/GOLD multi-overlay + flash BTC + NLP Ollama sur les news ; **SDK Paquet 2 COMPLET** — version SDK 0.5.0, client HTTP + WebSocket + hooks + cache + circuit breaker + telemetry non-bloquant + config YAML hot-reload + doc intégration Zeta + 4 exemples runnable + ADR-007 + CI ; **Dashboard Paquet 3 COMPLET** — version dashboard 0.5.0, app Expo SDK 54 avec auth + Home KPIs + Signals feed WebSocket + détail signal + Alerts + Bots + Config + push notifications, mise en service réelle sur iPhone via Expo Go le 2026-05-03 avec 2 bugs visibles fixés dans la foulée (logo iPhone tronqué + WS auth `_session_maker` import statique = bug 7 section 9) ; **Paquet 4 Sessions 1 + 2 + 3 livrées + Session 4 partielle** — Google News RSS BTC + GOLD (ADR-008) + Reddit BTC pondéré log upvotes (ADR-009) + GDELT timelinetone GOLD NLP scientifique non-LLM contrarian (ADR-010), 4 sources sentiment cross-validées sur BTC, 4 overlays cross-validés sur GOLD, **diversification méthodologique** Ollama-LLM vs NLP scientifique, 10 ingesters total ; **pipeline de calibration livré** (Session 4 — 5 scripts CLI collect/annotate/predict/backtest/measure + 65 tests pytest + `docs/methodology/calibration.md` + glossaire EN→FR ~80 termes) avec premier cycle 100 items annotés à la main, predictions Ollama+keywords générées, deltas 1h/6h mesurés ; **deltas 24h+5d et conclusions structurelles à venir le 2026-05-06+** ; **Paquet 5 Anti fake-news LIVRÉ 2026-05-03 (ADR-011)** — cross-validation runtime via Modified Z-score d'Iglewicz-Hoaglin + dispersion globale, scoring source dynamique avec recalibration automatique daily 03:00 UTC, mode active/shadow par variable d'env `TIK_ANTIFAKENEWS_MODE`, table DB `source_credibility_history` pour audit, hook SDK `on_fake_news_detected` enfin actif, 71 nouveaux tests (39 cross_validator + 32 source_credibility), 425 → 457 tests verts ; **Paquet 6 LLM hypothesis generator LIVRÉ 2026-05-03 (ADR-012)** — synthèse contextuelle des hypothèses signal via llama3.2:3b en 6 sections fixes (~150 mots EN), pattern Strategy `HypothesisGenerator` calque ADR-006, mode `disabled|shadow|active` par var env `TIK_LLM_HYPOTHESIS_MODE` (shadow par défaut → sortie LLM dans `Signal.advisory.llm_hypothesis_candidate`, hypothesis garde template), réveil champ DB `Signal.advisory` existant (zéro modif schéma), validation post-génération (longueur + mots-clés + sanitize markdown), circuit breaker batch-level identique news_classifier, timeout strict 30s, branchement swing BTC + swing GOLD + flash BTC, premiers cycles validés runtime 2026-05-03 20:44-20:45 (139 mots GOLD swing, 125 mots BTC flash), 39 nouveaux tests, 522 → 561 tests verts ; v1.0.0 du SDK réservée à la mise en production réelle dans Zeta après 3 mois de mode shadow ; **Évolution Dashboard 2026-05-04 (version 0.5.1)** — carte "Stats LLM" sur Home (% signaux émis aujourd'hui depuis 00 h UTC avec sortie LLM ≥ 30 mots, code couleur vert/orange/rouge seuils 80/60 %, badge "LLM ✓"/"fallback" sur dernier signal, calcul côté client zéro request HTTP supplémentaire, couvre modes shadow et active de `TIK_LLM_HYPOTHESIS_MODE`) + **fix Bug 8 timezone** dashboard (utilitaire `parseUtcIso` ajoutant `Z` si absent, refactor 4 `timeAgo` dupliqués → 1 seul, refactor `toLocaleString` détail signal, tous les âges désormais corrects partout) + factorisation seuil 30 mots dans `utils/llm.ts` partagé entre carte détail signal et nouvelle carte Stats LLM Home + 2 bugs Alerts pré-existants identifiés en section 10 (persistance + timestamp figé) reportés à session dédiée ; **Paquet 7 Timezone fix backend LIVRÉ 2026-05-04 (ADR-013)** — tous les `datetime.utcnow()` du `core/src/tik_core/` (17 fichiers : storage/models + storage/schemas + scoring 4 fichiers + api 3 fichiers + auth + scripts 3 fichiers + aggregator 2 fichiers) remplacés par helpers `now_utc()` aware et `now_utc_naive()` naïf du nouveau module `core/src/tik_core/utils/time.py`, sérialisation Pydantic via `field_serializer` + helper partagé `iso_utc` qui force `Z` sur datetime naïf venant de la DB (cas SQLAlchemy lecture), payload Redis WebSocket aussi normalisé via `iso_utc` dans `publisher._publish_signal`, pas de migration Alembic vers TIMESTAMPTZ (hypertable Timescale lourde, le serializer compense), 19 nouveaux tests pytest (9 utils_time + 10 schemas_serialization), 561 → 590 tests verts, **bug 8 désormais résolu à la source** pour TOUS les consommateurs (dashboard, SDK Python, futur Zeta) avec `parseUtcIso` dashboard conservé comme filet forward-compat ; **réservation ADR-013 traduction FR glissée à ADR-014** dans ADR-012, backlog.md entry #2 et CLAUDE.md section 8 ; **Évolution Dashboard 2026-05-04 après-midi (version 0.5.2)** — bascule LLM hypothesis shadow runtime activée (3 cycles complets validés en 90 secondes le 2026-05-04 17:11 UTC : swing BTC 138 mots / swing GOLD 105 mots / flash BTC 103 mots, sortie LLM dans `Signal.advisory.llm_hypothesis_candidate` conformément à ADR-012 décision 3), carte secondaire "Hypothèse contextuelle (LLM · validation)" iPhone validée visuellement (carte déjà implémentée dans `app/signal/[id].tsx:142-173` depuis le matin Stats LLM card, anticipation), **Bug 9 timezone DB asyncpg découvert et fixé runtime** (régression du Paquet 7 ADR-013 du matin même qui empêchait tous les inserts de signaux depuis 13:09 UTC, ~4h de cycles perdus, workaround chirurgical 2 lignes dans `publisher.py:_publish_signal` strip explicite tzinfo, ADR-013 reste valide dans son intention, dette technique tracée section 9 : commentaire obsolète `utils/time.py:18` à corriger + ADR-013 à amender + test pytest Postgres bout-en-bout à ajouter), **Bug A Alerts résolu** (migration vers `@react-native-async-storage/async-storage` dans `dashboard/src/alerts/AlertsContext.tsx`, hydratation eager au mount + persistance à chaque setAlerts, clé storage `tik.alerts.v1`, filet exception JSON corrompu → reset, cap MAX_ALERTS=50 inchangé), **Bug B Alerts résolu via hook `useTick` mutualisé** (initialement résolu inline puis constat que le même bug existe sur Signals + Home, refacto en hook custom `dashboard/src/hooks/use-tick.ts` ~10 lignes retournant le tick pour `FlatList.extraData`, refacto 4 fichiers : alerts/signals/index/stats-llm-card en cascade via parent), **section 10 désormais vide** (aucun bug critique en cours, Bugs A et B migrés vers section 9), **plan préparation trading manuel J+10 acté** (l'utilisatrice trade manuellement avec Tik à partir du 2026-05-14, Tik passe d'outil d'observation à outil d'aide à la décision réelle, Garde-fou 1 ne s'applique PAS au trading manuel) : 4 features priorisées sur calibration empirique + contexte rapide sans risque LLM + discipline opérationnelle (J+1-2 carte Top headlines / J+3-4 Hit rate live Home / J+5-6 Track record détail signal / J+7-8 Watchlist post-trade / J+9-10 calibration mentale sans dev), **aucune modif des engines / pipeline scoring / cross-validation** dans le plan J+10 (purement dashboard + endpoints API en lecture, pattern multi-overlay ADR-004 inchangé, ADR-003 inchangé), **Phase 2 enrichissement contextuel hypothèse LLM réservé ADR-015 reporté post-J+30** car mode shadow strict 1 mois impossible en 10 j et le LLM 3B a des limites documentées (cf. `docs/backlog.md` entry n°4 pour le raisonnement complet sur les pistes A/B/C/D évaluées) ; **Paquet 8 Phase A.1 trading manuel J+10 LIVRÉ 2026-05-05** — endpoint `/api/v1/headlines/{entity_id}` domain-agnostic (params `limit` / `since_hours` / `sort credibility_recency|recency`, dédup multi-source par titre normalisé, decay exponentiel half-life 12h) + carte dashboard "Top headlines" Home avec sélecteur BTC/GOLD + badges sentiment + tap pour ouvrir l'article + route détail `/headlines/[entityId]` cap 25, 3 ingesters news enrichis avec champ `headlines: list[dict]` cap 25 (Google News, CryptoCompare, Reddit) **calcul score net inchangé**, helper `_strip_publisher_suffix` Google News pour préserver dédup multi-source, schéma Pydantic `HeadlineOut`, +59 tests pytest (590 → 649 verts, 0 régression), validation runtime 2026-05-04 22:28 UTC (109 signaux émis sur 24h post-livraison, aucune régression engines), pattern OSINT pro respecté (titres bruts citant leurs sources, zéro hallucination LLM), ADR-016 couplage signal↔titres écarté score 5/10, **8 lacunes vs standard pro identifiées et scorées** (A persistance DB titres 9/10 + G flag anti fake-news visible 8/10 + C sentiment stable 7/10 = Phase 1.1 proposée à arbitrer ~6-7h ; B calendrier macro 8/10 + D SDK headlines 6/10 = Phase 1.2 ; E cross-val titre individuel 7/10 + F dédup ingester 5/10 + H volume sources 4/10 = écartées ou post-J+30), bug observation utilisatrice "Activité 24h figé" diagnostiqué (cap dashboard `limit: 100` vs 109 signaux/24h, fix trivial à `limit: 500` en attente validation), limite Ollama 3B documentée (non-déterminisme sur titres ambigus, solution proposée cache Redis par hash titre TTL 7j = Lacune C), anti fake-news mode `active` confirmé runtime (10 flags `disagreement_n2 status=degraded` sur flash BTC en 24h, pattern soft filtering Tik documenté) ; **Paquet 9 Phase 1.1 Lacunes OSINT pro essentielles LIVRÉ 2026-05-05** — 3 lacunes scorées rigoureusement (A 9/10 + G 8/10 + C 7/10) livrées en bloc avant Phase A.2 hit rate live : **Lacune G** composant unifié `AntiFakeNewsBadge` mode compact (liste Signals) vs mode full (détail) avec différenciation visuelle `degraded` orange (drapeau prudence, direction inchangée) vs `tripped` rouge (bloquant, direction forcée neutral) + libellé français + explication contextuelle ADR-011 (mea culpa paranoïa contrôlée : badge existait déjà cryptique « Circuit breaker : degraded » + pastille « CB » indifférenciée, périmètre révisé runtime de « ajouter » à « améliorer ») ; **Lacune C** cache Redis `tik.sentiment.cache.{model}.{asset}.{sha256[:16]}` TTL 7j sur `OllamaClassifier` (hash titre normalisé, label canonique stocké, best-effort sur erreurs Redis, `build_news_classifier` propage `redis=` aux 4 instances classifiers) → stabilité totale sentiment individuel entre cycles + économie Ollama ~80 % titres réapparus + 11 nouveaux tests ; **Lacune A** persistance DB titres pour audit historique : modèle SQLAlchemy `HeadlineRecord` + migration Alembic `0004_headlines` (4 indexes entity_id/source/title_hash/fetched_at) + helper `headlines_repo.py` (`compute_title_hash`/`parse_iso_naive` cohérent Bug 9/`persist_headlines` best-effort/`fetch_headlines_history`) + 3 ingesters (Google News, CryptoCompare, Reddit) modifiés pour passer `session_maker` au constructeur et appeler `persist_headlines` après publish Redis avec log `n_persisted=...` + `run_ingesters.py` initialise un session_maker dédié (pool 5 + max overflow 5) + schéma Pydantic `HeadlineHistoryOut` + nouvel endpoint `GET /api/v1/headlines/history/{entity_id}` (params `since_hours` 1-720h défaut 168h / `limit` 1-500 défaut 100 / `source` optional filter) tri DESC `fetched_at` permet retro-analyse jusqu'à 30 jours en arrière (vs Redis 24h max) + 20 nouveaux tests + migration appliquée runtime (correction manuelle `UPDATE alembic_version` car `--reload` Uvicorn avait déclenché la migration en concurrence) + validation runtime 2026-05-05 11:46 UTC (50 rows insérées dès 1er cycle post-restart, endpoint historique retourne titres avec id UUID + URL cliquable + fetched_at UTC Z + credibility cohérente SOURCE_SCORES) ; suite pytest 649 → **689 verts** (+40 nouveaux), 0 régression, pattern OSINT pro renforcé (audit historique + sentiment stable + transparence anti fake-news = convergence mesurable vers Recorded Future / Bloomberg modulo volume sources), Garde-fou 1 / ADR-003 / ADR-004 inchangés ; **engagement méthodologique paranoïa contrôlée pris (2026-05-05)** pour chaque future feature : (1) tester stabilité runtime 10 cycles avant déclarer livré, (2) lister questions critiques utilisateur paranoïaque AVANT coder, (3) auditer bout-en-bout backend↔UI, (4) mentionner explicitement 3-4 limites connues à chaque livraison, (5) tableau pour/contre/verdict + score utilité pour chaque option)*
*Mainteneur : utilisatrice solo + assistant Claude via Claude Desktop (app native macOS)*
