# Audit complet module par module + E2E — 2026-07-02

> Audit mené le 2026-07-02 dans un environnement isolé (conteneur cloud, clone frais
> des deux dépôts `Tik` et `btc-research-lab`). Méthode : lecture intégrale du code
> de chaque module par des agents d'audit indépendants (un par module), exécution de
> la suite pytest complète contre un PostgreSQL 16 + Redis 7 réels, et un scénario
> E2E « bout-en-bout » sur l'application réelle démarrée (uvicorn + lifespan complet).
> Engagements méthodologiques 13bis relus et appliqués : uniquement des constats
> vérifiés dans le code (fichier:ligne), pas de chiffres inventés.

---

## 1. Résultats d'exécution (E2E)

### 1.1 Suite pytest core (Tik)

- **1610 tests, 1610 verts, 0 échec, 0 skip, en 29,6 s** — contre `tik_test`
  (PostgreSQL 16.13 réel) + Redis 7 réel. Les tests d'intégration DB et Redis
  (publisher timezone, flux publisher, WS lifespan, macro_events DB) ont donc
  **réellement tourné**, pas seulement les garde-fous « code source ».
- Config identique à la CI (`.github/workflows/ci.yml`) : `TIK_DB_NAME=tik_test`,
  garde anti-prod `_is_test_database` active.

### 1.2 Scénario E2E application réelle

Application démarrée avec `uvicorn tik_core.main:app` (lifespan complet), clé API
créée via `python -m tik_core.scripts.create_api_key`. Parcours vérifié :

| # | Vérification | Résultat |
|---|---|---|
| 1 | `GET /api/v1/health` public | ✅ 200 |
| 2 | REST sans clé / mauvaise clé | ✅ 401 dans les deux cas |
| 3 | REST bonne clé (`/signals/latest`) | ✅ 200 |
| 4 | Connexion WebSocket (auth query param) | ✅ connectée |
| 5 | **Survie WS à 7 s d'inactivité** (régression Bug 16) | ✅ survit |
| 6 | Publication d'un signal via le **vrai publisher** (DB + Redis pubsub) | ✅ persisté |
| 7 | Réception du signal en **temps réel sur la WS** | ✅ reçu en ~0,8 s |
| 8 | Timestamp suffixé `Z` (ADR-013) | ✅ |
| 9 | ≥ 2 contre-scénarios dans le payload (paranoïa contrôlée) | ✅ |
| 10 | `GET /signals/{id}` + recherche `GET /signals` retrouvent le signal | ✅ |
| 11 | Ligne présente en DB Postgres (direction/veracity corrects) | ✅ |
| 12 | Tour des endpoints : entities, veracity/sources, metrics/source_health, macro/regime, macro/cockpit, macro_events/upcoming, headlines/top, polymarket/snapshot, derivatives/btc, signals/latest?horizon=flash | ✅ tous 200 |
| 13 | `GET /metrics/hit_rate?entity_id=BTC&horizon=swing` sans accès Binance | ✅ **503 propre** avec message explicite (dégradation contrôlée, pas de 500) |

**Deux découvertes faites PAR le scénario E2E** (pas par la lecture de code) :

- **E2E-1 (MAJEUR)** : le publisher accepte et persiste des `evidence` / `triggers` /
  `counter_scenarios` qui ne respectent pas les schémas Pydantic de sortie
  (`storage/schemas.py` : `Evidence.fact`, `Trigger.type/value`,
  `CounterScenario.name`). Conséquence mesurée : **un seul signal mal formé en DB
  fait tomber en 500 `GET /signals/{id}` ET tout le listing `GET /signals`**
  (`ResponseValidationError` à la sérialisation). En prod les engines produisent
  toujours la bonne forme, mais tout futur caller de `publish_*_signal` (couche
  micro ADR-030 incluse — `POST /signals/ingest` est lui validé par `MicroSignalIn`,
  mais un appel direct au publisher ne l'est pas) peut empoisonner les endpoints
  de liste. Recommandation : valider le payload contre les schémas au moment du
  publish (fail-fast) plutôt qu'à la lecture.
- **E2E-2 (confirme le constat API)** : la clé API WS apparaît **en clair dans les
  logs d'accès uvicorn** (`ws/signals?api_key=tik_...` observé dans les logs du
  scénario). Cf. constat A-1 ci-dessous.

### 1.3 Suite pytest btc-research-lab

- Premier passage sur environnement vierge : **811 verts, 15 échecs en
  12 min 15 s** — les 15 échecs sont TOUS dans `test_monthly_performance.py`,
  cause unique : `pytz` absent (DuckDB en a besoin pour
  `to_timestamp`/`date_trunc`, et il n'est pas dans `requirements.txt` — il
  arrivait en dépendance transitive de pandas, que pandas 3.x n'installe plus).
- Après `pip install pytz` : les 34 tests du fichier passent → **suite complète
  équivalente à 826/826 verts**. Constat MINEUR de reproductibilité : ajouter
  `pytz` à `requirements.txt` du lab.

### 1.4 Limites de cet E2E (à dire honnêtement)

- Réseau sortant restreint dans le bac à sable : **pas de fetch réel** Binance /
  Yahoo / FRED / Google News — les ingesters n'ont pas été exercés contre les
  vraies APIs (mais leurs parseurs le sont par ~360 tests unitaires).
- Postgres de test **sans extension TimescaleDB** : le schéma vient de
  `Base.metadata.create_all` (comme en CI), donc l'hypertable, la PK composite
  `(id, timestamp)` et les migrations Alembic n'ont pas été exercées ici
  (c'est d'ailleurs un trou de couverture identifié — cf. constat S-6).
- Pas d'Ollama : chemins LLM en fallback keywords/template (comportement prévu
  par la factory ADR-006, c'est le chemin dégradé documenté).

---

## 2. Synthèse générale

**État global : sain et discipliné pour un projet solo.** Les 16 bugs historiques
documentés dans CLAUDE.md sont bien fixés dans le code actuel (vérifié un par un :
Bug 7, 9, 10, 12, 16 notamment), la suite de tests est massive (1610 verts) et la
logique pure est très bien couverte. L'application réelle démarre, s'authentifie,
publie et diffuse des signaux correctement.

**Les vrais risques ne sont pas là où le projet a déjà regardé.** Les constats les
plus sérieux de cet audit se concentrent sur :

1. **La rigueur statistique des scripts de mesure « officiels »** (section 8) — un
   constat CRITIQUE : les scripts qui serviront aux prochaines décisions
   (retour CryptoCompare, re-mesure DXY/COT, enrôlement dérivés/ETF) calculent des
   p-values sur des fenêtres massivement chevauchantes et contiennent deux
   look-ahead réels (COT daté au mardi au lieu du vendredi de publication ; DXY
   FRED publié avec ~1 semaine de retard). C'est exactement le piège que les
   mémoires `measurement-overlapping-returns` dénoncent — il est corrigé dans
   `analyze_colinearity.py` mais PAS dans `measure_post_fix_hit_rates.py`,
   `backtest_dual_lens.py` ni `backtest_numeric_sources.py`.
2. **La robustesse des boucles d'ingesters** (section 4) — 8 ingesters anciens
   meurent silencieusement sur une erreur Redis (tasks non supervisées, exception
   jamais logguée), et le warm-up du breaking-news avale un cycle d'alertes tous
   les 7 jours.
3. **Des désynchronisations config ↔ runtime** (section 7) — `source_health`
   surveille CryptoCompare à 3 h alors qu'elle polle toutes les 12 h → fausse
   alerte critique quasi permanente dès le retour du quota (maintenant, en
   juillet) ; titres de news non échappés dans les messages Telegram HTML →
   un titre contenant `<` fait perdre le briefing entier.

Aucun constat ne remet en cause le NO-GO directionnel ni les garde-fous — au
contraire, plusieurs constats montrent que les biais de mesure actuels risquent
de faire paraître Tik MEILLEUR qu'il n'est (chevauchement, look-ahead) : raison de
plus pour ne rien enrôler avant correction des scripts de mesure.

### Constats par sévérité (les deux dépôts)

| Sévérité | Nombre | Où |
|---|---|---|
| CRITIQUE | 1 | scripts de mesure Tik (p-values sur fenêtres chevauchantes + verdict « significatif ») |
| MAJEUR | 27 | Tik : scripts (7), aggregator (3), storage (2), metrics/notify (2), api (1), E2E (1), dashboard (2), sdk au dégel (2) ; lab : pipeline (4), backtests (3) — détail par section |
| MINEUR / INFO | ~50 | répartis, aucun bloquant |

---

## 3. Module `scoring/` (4 262 lignes) — moteurs swing/flash, cross-validation

**Synthèse** : bon état. Conformité ADR-018 réelle et vérifiée (poids techniques à
0 partout, direction dérivée exclusivement du `combined_bias` OSINT), veracity
bornée 0.70–0.95, émission conditionnelle flash conforme ADR-005. Aucun bug
critique actif.

Constats principaux :

- **MAJEUR — `cross_validator.py:97-127`** : le fallback zero-MAD (seuil absolu
  0.3) peut exclure comme « outlier » une source de **même signe** que les autres,
  car les biais sont quantifiés au pas de 0.5. Exemple calculé : {FG +1.0,
  CC +0.5, GN +0.5} → MAD=0 → FG exclu du combined_bias alors que les 3 sources
  sont haussières. Un désaccord d'intensité est traité comme une suspicion de fake
  news. Comportement « as designed » (testé), mais calibré pour des biais continus
  qui n'existent pas.
- **MAJEUR (connu, ADR-026)** — dispersion de veracity calculée outliers inclus
  alors que le combined_bias les exclut (`cross_validator.py:271-280`) →
  `circuit=ok` + `veracity=0.70` sur le même signal. Documenté, recalibration
  différée volontairement (Axe #1) — rien de nouveau, confirmé présent.
- MINEUR — `swing_engine.py:819/1207`, `flash_engine.py:656` : `iloc[-1]` sans
  garde sur DataFrame vide → un retour API vide (0 kline) fait perdre le cycle
  (rattrapé par le catch-all scheduler, mais silencieux côté UI).
- MINEUR — en mode AFN `shadow`, la promesse « décision inchangée » est fausse :
  le combined_bias utilisé exclut déjà les outliers (`cross_validator.py:295-317`).
  Sans effet en prod (mode `active` par défaut), piège si on bascule le toggle.
- INFO — `veracity=0.85` par défaut du dataclass : un signal sans AUCUN overlay
  disponible sort neutral/confidence 0 mais veracity 0.85 « moyenne » — trompeur.
- **Divergences doc vs code** : ADR-004/005 de CLAUDE.md périmés sur 2 points —
  la veracity est calculée par **dispersion** (plus `_veracity_from_concordance`),
  et le seuil de directionnalité flash est **0.30** (pas 0.10) identique au swing.

**Couverture** : excellente sur la logique pure (~230 tests). Trous nets :
`analyze_swing_btc/gold` et `analyze_flash_btc` (l'orchestration complète, là où
vivait le bug N=2) ont **zéro test** ; `_compute_technical_evidence`,
`_apply_anomaly_ponderation` et les indicateurs unitaires (rsi/ema/macd/atr)
non testés.

---

## 4. Module `aggregator/` (6 569 lignes) — 19 ingesters + news_classifier

**Synthèse** : pattern commun propre, cohérence intervalle/TTL correcte **partout**
(tableau complet vérifié : aucun cas où la donnée expire avant le refresh ; leçons
des Bugs 15/GDELT appliquées), news_classifier conforme ADR-006 sur ses 5 exigences
(fallback par titre, circuit breaker batch à 3 échecs, factory ping Ollama,
traçabilité `method`).

Constats principaux :

- **MAJEUR — écritures Redis non protégées dans 8 ingesters anciens**
  (`yahoo_ingester.py:115-123`, `fred_ingester.py:139-146`,
  `fear_greed_ingester.py:83-84`, `cryptocompare_ingester.py:265-266`,
  `google_news_ingester.py:277-278`, `reddit_ingester.py:301-302`,
  `gdelt_ingester.py:180-181`, `cftc_cot_ingester.py:124-125`) : une
  `ConnectionError`/`TimeoutError` Redis entre le fetch et le `setex` tue la
  boucle de l'ingester. Aggravant : les tasks `create_task` ne sont **ni
  supervisées ni dotées de done-callback** → l'exception n'est même pas logguée
  (« Task exception was never retrieved »), l'ingester reste mort jusqu'au
  restart du conteneur. Les ingesters récents (polymarket, coingecko, deriv, etf,
  tradingview) sont blindés — le rétro-portage n'a jamais été fait.
- **MAJEUR — warm-up breaking-news réarmé tous les 7 jours**
  (`breaking_news_ingester.py:78-79, 609-623`) : le flag « premier démarrage »
  (`SET NX EX 7j`) expire sur un process qui tourne en continu → tous les ~7 jours,
  la première fournée d'items matchés est consommée par la dédup 48 h **sans
  alerte Telegram** — ces breaking news ne seront jamais alertées. L'intention
  documentée (« 1er démarrage uniquement ») n'est pas respectée par l'implémentation.
- **MAJEUR (risque quota)** — le breaking-news envoie **~4 800 req/jour vers
  news.google.com** (5 flux × cycle 90 s) depuis la même IP que l'overlay
  sentiment Google News (96 req/jour), qui est l'**un des 2 seuls overlays BTC
  actifs**. Précédents : Reddit a banni l'IP pour ~96 req/jour, GDELT throttle.
  Si Google throttle l'IP, BTC swing passe à 1/4 overlay (FG seul).
- MINEUR — `tik.macro.last.{series}` écrit en `SET` **sans TTL**
  (`fred_ingester.py:143-146`) : si l'ingester FRED meurt, les consommateurs
  lisent indéfiniment des valeurs périmées sans le détecter.
- MINEUR — traçabilité ADR-006 faussée quand le circuit breaker s'ouvre en cours
  de batch : tout le batch est étiqueté `method: ollama:...` même si la moitié a
  été classifiée par keywords → le futur backtest par méthode sera biaisé.
- MINEUR — baseline « publisher diversity » CryptoCompare calibrée pour un polling
  horaire disparu : la fenêtre « 7 jours » documentée est devenue ~84 jours réels.
- INFO — Reddit continue d'être pollé (2 req 403 / 30 min) sur l'IP bannie —
  maintient l'IP « chaude » côté anti-abus pendant la demande d'unban.

**Couverture** : ~360 tests, bonne sur les parseurs. Trous : **zéro test** pour
binance (WS), yahoo, fred, fear_greed (3 des 8 ingesters fragiles du constat 1) ;
les 43 tests breaking-news ne couvrent que les helpers purs (pas `scan_once`,
dédup, warm-up — le bug du warm-up aurait été attrapé par un test) ; aucun test
ne simule une erreur Redis en `_run` ; les intervalles anti-quota (CC 12 h,
GDELT 2 h — invariants du Bug 15) ne sont assertés nulle part : un revert
accidentel à 1 h ne casserait aucun test.

---

## 5. Modules `api/` + `auth/` + `main.py` + `config.py` (~2 900 lignes)

**Synthèse** : surface saine — 35/35 routes REST non-health exigent un scope
(vérifié exhaustivement), zéro SQL brut, paramètres bornés partout, les 3 fixes
WS historiques (Bug 7/10/16) **présents et vérifiés ligne par ligne** (et
confirmés par le scénario E2E : survie idle > 5 s, réception temps réel).

Constats principaux :

- **A-1 MAJEUR — clé API WS en clair dans les logs d'accès** (`ws.py:69`, auth par
  `?api_key=`) : uvicorn logue l'URL complète — **confirmé en E2E** (la clé
  apparaît dans les logs du scénario). Quiconque lit `docker compose logs core`
  récupère une clé `read:signals` valide. Mitigation : filtrer la query dans
  l'access log, ou passer la clé par sous-protocole/premier message.
- MINEUR — `/openapi.json` reste **public en production** (`main.py:79-86`
  désactive docs/redoc mais pas `openapi_url`) : sur le VPS exposé `IP:8200`, un
  scanner récupère la description des 37 routes.
- MINEUR — `finally` de `ws.py:171-175` non défensif : si on sort sur
  `RedisError` (Redis down), `punsubscribe` lève à son tour → `pubsub.aclose()`
  / `redis.aclose()` sautés → fuite de connexion par client WS pendant une panne
  Redis. Même famille que Bug 10/16.
- MINEUR — heartbeat et boucle principale font des `send_json` concurrents sans
  verrou (`ws.py:116-124, 160`) — collision rare possible → déconnexion client
  injustifiée.
- MINEUR — `POST /entities` : TOCTOU (2 créations concurrentes → 500 au lieu de
  409) ; `POST /signals/ingest` avec `entity_id` inconnu → 500 (violation FK non
  gérée).
- MINEUR — `/metrics/hit_rate` charge TOUS les signaux de la fenêtre sans filtre
  SQL entity/horizon (`metrics.py:229-234, 413-418`) — ~27 k lignes ORM par
  cache-miss à terme.
- INFO — l'enforcement d'auth est **opt-in par route** (le `Depends(require_scope)`
  doit être pensé à chaque nouvelle route) : aucun trou aujourd'hui, mais aucun
  test générique ne détecterait une future route oubliée.
- INFO — hash SHA-256 non salé des clés : acceptable (tokens ~256 bits d'entropie),
  jamais de clé en clair en DB.

**Fixes historiques** : Bug 7 ✅ (`ws.py:30,80` accès dynamique), Bug 10 ✅
(`break`/`continue` séparés, ws.py:152-168), Bug 16 ✅ (`psubscribe` avant
`accept`, `get_message(timeout=30)` + `continue` sur TimeoutError, ws.py:103-146).
**Nuance** : contrairement au Bug 10, il n'existe **aucun garde-fou « code
source » pour le Bug 16** — si quelqu'un remet un `pubsub.listen()`, seul le test
d'intégration (skippé en CI sans Redis) le verrait.

**Couverture** : bonne sur les routes métier. Trous : `/entities` (4 routes CRUD)
**zéro test HTTP** ; `ApiKeyProvider.authenticate` jamais exercé en HTTP réel
(la fixture override l'auth — expiration/inactif/X-Api-Key non testés) ;
`/macro/regime`, `/macro/cockpit`, `/rate_probabilities`, `/tradingview/*` sans
test de route ; pas de test générique « toute route sans clé → 401 ».

---

## 6. Module `storage/` + `migrations/` (~1 900 lignes + 6 migrations)

**Synthèse** : sain et discipliné. Le workaround Bug 9 (strip tzinfo) est présent,
durci (`astimezone(UTC)` avant strip) et vérifié sur **les 9 points d'insertion
DB** (tableau exhaustif dans l'audit détaillé — tous conformes). `get_session`
gère commit/rollback/close correctement, aucune fuite de session trouvée. Le
drift PK Signal (mono-colonne ORM vs composite DB) est intentionnel et verrouillé
par `test_signal_pk_contract.py`.

Constats principaux :

- **S-1 MAJEUR — aucune politique de rétention/compression sur aucune table** :
  zéro `add_retention_policy`/`drop_chunks` dans les migrations, aucun job de
  purge. Surtout `headlines` : la dédup à l'insertion est explicitement absente
  (`headlines_repo.py:114-117`) → plusieurs centaines de lignes dupliquées/jour,
  croissance non bornée du disque VPS.
- **S-2 MAJEUR (latent) — `upsert_macro_event` : résilience par-événement
  illusoire** (`macro_events_repo.py:111-154`) : le `except → return False` par
  event partage la transaction du batch ; en Postgres, après une erreur la
  transaction est avortée → **un seul event invalide fait perdre tout le
  calendrier macro du cycle** (dont les FOMC HIGH suivis ±4 h). Il faudrait un
  SAVEPOINT (`begin_nested()`) par event.
- MINEUR — drifts index modèle↔migration (`ix_entities_domain`,
  `ix_sources_category` en migration mais pas dans les modèles ; FK composite
  feedbacks absente du modèle) : la DB de test `create_all` ne reproduit pas le
  schéma prod exact.
- MINEUR — index timestamp probablement dupliqué en prod (`ix_signals_timestamp`
  + l'index par défaut de `create_hypertable`) — à vérifier sur le VPS avec
  `\di signals*` avant d'affirmer.
- S-6 (trou de couverture majeur) — **les migrations Alembic ne sont jamais
  exécutées en test** : hypertable, PK composite, FK composite, CASCADE ne sont
  exercés nulle part. Un test « `alembic upgrade head` sur base vierge puis
  comparaison avec metadata » comblerait ça.

---

## 7. Modules `metrics/` + `notify/` + `adapters/` + `utils/` + `ml/` (~1 900 lignes)

**Synthèse** : bien architecturés (logique pure séparée de l'IO, best-effort
systématique). Fix Bug 12 **présent et conforme** (`api/metrics.py:92-119`, clé
v4 ligne 540, verrouillé par 7 tests). `utils/time.py` conforme ADR-013.
`adapters/` est du code dormant (importé nulle part), `ml/` un stub vide.

Constats principaux :

- **M-1 MAJEUR — `source_health.py:56-63` désynchronisé du polling réel** :
  spec CryptoCompare `max_age_s=3h, critical=True` alors que le polling réel est
  **12 h** (Bug 15). Dès que CryptoCompare re-publie (reset quota ~1er juillet —
  c'est maintenant), le statut sera « stale » ~75 % du temps → **fausse alerte
  critique quasi permanente** sur `/metrics/source_health`, effet « cry wolf »
  qui masquera une vraie panne. Même désync (moins grave) sur GDELT (spec 2 h =
  1× l'intervalle au lieu de la règle ~3×).
- **M-2 MAJEUR — injection HTML Telegram** : `briefing.py:326`, `alerts.py:141`
  et `breaking_news_ingester.py:427-428` interpolent des **titres de news bruts**
  dans des messages `parse_mode=HTML` sans `html.escape`. Un titre contenant `<`
  (ex. « Bitcoin <$60k ») → Telegram répond 400 → **le message entier est perdu**
  (briefing du créneau ou alerte breaking), avec un simple log warning.
- MINEUR — `telegram.py:22-52` : aucun retry, pas de gestion du 429
  `retry_after`, pas de troncature à 4 096 caractères.
- MINEUR — hit rate flash structurellement imprécis : klines 1 h + tolérance 6 h
  pour une fenêtre de mesure de 1 h (`hit_rate.py:134-135`,
  `api/metrics.py:253`) — la « fenêtre 1 h » réelle peut aller de ~0 h à ~2 h.
- MINEUR — variante résiduelle du Bug 12 : badge `données_manquantes` traité
  comme résolu → TTL 6 h, alors qu'un trou de données peut être transitoire
  (week-end GOLD).
- Points vérifiés sains : divisions par zéro toutes gardées, signaux immatures
  exclus du hit rate (jamais comptés en échec), timezone cohérente partout,
  anti-spam alerts écrit uniquement après envoi réussi.

**Couverture** : excellente sur la logique pure (hit_rate 43 tests, track record
46, TTL Bug 12 : 7). Trous exactement sur les deux MAJEURS : aucun test ne croise
`SOURCE_SPECS.max_age_s` avec les intervalles réels de `run_ingesters.py` ;
aucun test d'échappement HTML ; `telegram.py` quasi non testé.

---

## 8. Module `scripts/` (8 221 lignes) — mesure, backtest, opérationnel

**Synthèse** : les scripts shadow récents (Polymarket, dérivés, ETF, CoinGecko,
`analyze_colinearity`) intègrent bien les leçons du projet (N non chevauchant,
baselines de tendance, planchers d'échantillon, anti-lookahead ETF propre). Mais
**les scripts des mesures officielles n'ont pas reçu ces corrections** — c'est le
constat le plus sérieux de tout l'audit, car ces scripts décideront du retour
CryptoCompare, de la re-mesure DXY/COT et de l'enrôlement dérivés/ETF.

- **C-1 CRITIQUE — `measure_post_fix_hit_rates.py:270-331` + `backtest.py:223-268`** :
  le test apparié « Tik vs Always SHORT » (verdict imprimé « Tik GAGNE (sig.) » si
  p < 0.05) est calculé sur tous les signaux mûrs émis toutes les 15-30 min avec
  un horizon 5 j → **les écarts partagent ~99 % de leurs fenêtres**, le z-test
  suppose l'indépendance → p massivement gonflée. Aucun sous-échantillonnage,
  aucun avertissement. La prochaine mesure officielle peut afficher
  « significatif p=0.003 » sur ~40 fenêtres réellement indépendantes maquillées
  en N=1500. (`analyze_colinearity.py:93-109` fait le bon traitement — le
  correctif existe déjà dans le repo, il n'a pas été porté.)
- **MAJEUR — look-ahead COT** (`fetch_numeric_history.py:294` +
  `backtest_numeric_sources.py:640-642`) : le point COT est daté au **mardi**
  (date de la photo de positions) alors que le rapport est publié le **vendredi**
  → le backtest « trade » 3 jours avant la publication. Gonfle l'IC/hit du COT —
  directement dans le chemin de décision `gold_dxy_cot_overlays_enabled`.
- **MAJEUR — look-ahead DXY probable** : DTWEXBGS (FRED) est publié via la
  release H.10 hebdomadaire (lag jusqu'à ~1 semaine) mais daté au jour J. À
  vérifier contre ALFRED avant la re-mesure.
- **MAJEUR — convention `neutral` incohérente entre scripts officiels** :
  `backtest.py:193-204` donne `gain(neutral) = −|delta|` (pénalité) là où
  `analyze_colinearity.py:392-399` modélise neutral = 0 (pas de position). Sur
  un échantillon récent à 79 neutral/192, le Δ Tik−baseline est biaisé vers le
  bas — les deux scripts ne mesurent pas la même chose.
- **MAJEUR — troncature silencieuse de la fenêtre klines** : 1000 bougies 1 h
  ≈ 41,6 j — les mesures « depuis le 2026-05-17 » sont déjà amputées des
  premiers jours sans avertissement, et la fenêtre shadow Polymarket (39 j au
  02/07) déborde dans quelques jours alors que le commentaire affirme « couvre
  TOUTE la fenêtre shadow ». Cette classe de bug a déjà été corrigée une fois
  (5m→1h) et revient.
- MAJEUR — `backtest_numeric_sources.py:389-459` : recommandations prescriptives
  par cellule source×horizon×palier (~36+ tests à seuils fixes) **sans correction
  multiple-testing** — le pattern exact dénoncé au Paquet 33.
- MAJEUR — `measure_btc_derivatives.py:102-147` : horizons forward en **indices
  de liste** sans contrôle des trous d'ingestion — un trou de 12 h fait qu'un
  « horizon 24 h » couvre 36 h ; le sous-échantillon « non chevauchant » ne l'est
  plus en temps réel. Script de décision ADR-023.
- MAJEUR — `measure_forexfactory_surprise.py:220-248` : surprise calculée avec
  les observations FRED **révisées** (pas le premier print) — la « surprise
  mesurée » n'est pas celle que le marché a vécue.
- MINEUR — bougie du jour en cours incluse dans les closes quotidiens
  (coingecko_predictive, etf_flows) ; exclusion silencieuse des signaux GOLD
  du week-end ; `measure_veracity_dispersion` parse les logs par regex fragile
  sans compteur de rejets.

**Couverture** : bons tests unitaires des helpers purs (backtest 36 tests,
forexfactory excellent sur les conversions). Trous : **`measure_btc_etf_flows.py`
zéro test** (y compris `_shift`/`aligned_flow_returns` — précisément la logique
anti-lookahead qui justifie le script) ; `measure_post_fix_hit_rates`,
`backtest_dual_lens`, `analyze_colinearity` sans test dédié alors que ce sont
les scripts officiels.

**Recommandation d'ensemble section 8** : avant TOUTE prochaine mesure de
décision (retour CryptoCompare, DXY/COT ~06/23 reporté, dérivés/ETF), porter le
sous-échantillonnage non chevauchant d'`analyze_colinearity` dans les 3 scripts
officiels, corriger la date COT (mardi→vendredi), vérifier DXY contre ALFRED,
unifier la convention neutral=0, et logger la couverture temporelle réelle des
klines vs fenêtre demandée.

---

## 9. `dashboard/` (~14 700 lignes TS/TSX) et `sdk/` (gelé ADR-022)

### Dashboard

**Synthèse** : qualité nettement supérieure à la moyenne pour un projet solo.
Fixes Bug 8 (parseUtcIso, 18 fichiers consommateurs) et Bug A/B (AsyncStorage +
use-tick) en place et généralisés ; reconnexion WS avec vrai backoff exponentiel
+ jitter + gestion foreground iOS ; intervalles tous nettoyés ; types TS fidèles
aux schémas Pydantic (échantillon vérifié : aucune divergence).

- **D-1 MAJEUR — clé API en clair sur le réseau** (déploiement, pas le code) :
  stockage local correct (Keychain iOS), mais l'accès prod documenté est
  `http://IP:8200` → Bearer et clé WS transitent non chiffrés. Fix côté infra
  (TLS / reverse proxy).
- **D-2 MAJEUR — onglet Alertes : pertes silencieuses** : contrairement à
  `useSignalStream`, l'`AlertsProvider` n'a ni resync REST ni reprise foreground
  (`AlertsContext.tsx:142-169`) → toute alerte émise app en fond/fermée est
  perdue définitivement, badge « Live » vert trompeur. Atténué par Telegram côté
  serveur.
- MINEUR — `outcome.ts:207` : seul site qui bypasse `parseUtcIso` (`new Date`
  direct sur un timestamp backend) ; race `cancelledRef` partagé dans
  `useDashboardKpis` ; fenêtre de quelques ms au boot où l'hydratation
  Alerts/Watchlist peut écraser l'historique persisté.
- **Couverture : zéro test** (aucun framework installé) — alors que plusieurs
  modules ont été conçus « purs et testables » (`ws.ts`, `outcome.ts`,
  `time.ts`). Candidats à ROI maximal : `parseUtcIso`/`timeUntil`,
  `nextBackoff`, `effectiveState`/`gainPct`.

### SDK (gelé)

**Synthèse** : état de conservation étonnamment bon — tous les endpoints appelés
existent encore avec les mêmes paramètres/auth/format WS. Aucune incompatibilité
cassante. Le gel ADR-022 reste **réversible à faible coût** (~½ session au dégel).

- MAJEUR (au dégel) — `stream.py:286-287` : le hook `on_fake_news_detected` se
  déclenche sur tout `circuit_breaker_status != "ok"`, or les signaux **micro**
  (ADR-030) sont toujours `degraded` par construction → faux positif systémique
  sur un stream non filtré. À corriger avant tout câblage Zeta.
- MAJEUR (au dégel) — dépendances en bornes basses sans lockfile : mécanisme
  exact du Bug 16 (upgrade silencieux). Figer les versions au dégel.
- MINEUR — modèles miroirs périmés (champs additifs core ignorés silencieusement :
  `Evidence.is_outlier`, `Advisory.near_macro_event` — la discipline ±4h serait
  invisible pour un bot SDK).

---

## 10. Dépôt `btc-research-lab` (~38 500 lignes, ADR-030 « micro »)

### 10.1 Recherche / backtests

**Synthèse** : niveau de rigueur nettement supérieur à la moyenne — walk-forward
strict testé **par mutation du futur** (gold standard anti-leakage), Deflated
Sharpe avec n_trials déclaré, coûts élargis par la volatilité, BH/Bonferroni sur
la grille régime, et surtout des **rapports qui concluent honnêtement au négatif**
(« direction RÉFUTÉE », « aucun horizon net-profitable ») — vérifié : les
conclusions écrites correspondent à ce que le code mesure. Aucun look-ahead franc,
aucune conclusion positive fabriquée.

Constats principaux :

- **L-1 MAJEUR — aucune baseline Always-SHORT dans tout le dépôt**
  (`baselines.py:55-61`, `backtest_costed.py:172-192` : random / last_value /
  mean_reversion / buy_hold / zero seulement, grep exhaustif). En régime baissier
  prolongé, un signal short colinéaire au trend « bat buy_hold et random » sans
  avoir été confronté à « vendre et attendre » — **exactement la contamination
  historique de Tik** (faux « 63 % hit SHORT »). Le `counterfactual_summary`
  (`backtest.py:252`) existe mais n'est branché sur aucun script.
- **L-2 MAJEUR — returns 21 j chevauchants dans les Sharpe de
  `regime_backtest.py:190-199`** : composés quotidiennement via `cumprod` →
  Sharpe point gonflé ~×√21 en niveau. Atténuants réels : baselines soumises au
  même biais, block bootstrap correct (bloc 100 > 21), et le chiffre « tradable »
  est bien le `discrete_summary` non chevauchant — mais les « Sharpe CIs »
  imprimés en tête de verdict sont inflatés.
- **L-3 MAJEUR — exécution zéro-latence au close du bar de signal** dans
  `backtest_p1_reversion.py:33-35` (entrée exactement au close qui déclenche le
  signal), en contradiction avec la règle de fer de `backtest.py:4-7` (« executed
  at the OPEN of bar t+1 »). Verdict P1 = RÉFUTÉ donc pas de fausse découverte
  ici, mais rendrait suspect un futur « SUPPORTED ».
- MINEUR — `gp_search.py` : l'en-tête promet une sélection « VAL only » mais le
  code retient le meilleur individu du TRAIN ; baseline « best single feature »
  choisie sur le holdout lui-même. — `train_evaluate.py:91` : ligne morte
  dangereuse (`sort_values()` par **valeur de prix**) écrasée par la ligne
  suivante correcte — un refactor la réactiverait silencieusement. —
  `per_horizon_benchmark.py` : best-of ~42 combos sans correction de
  multiplicité (résultat livré négatif, donc pas de fausse découverte en
  pratique). — `labels.py:33` : cadence 1 s exigée mais jamais vérifiée (shift
  positionnel : un trou de données décale l'horizon réel) ; `fillna(0)` masquant
  les trous dans `evaluation.py:189-201`.
- INFO — rapports vs code : fidèles sur l'échantillon vérifié, **sauf** la ligne
  P3c « validé sur 3 sous-périodes » qui n'est reproductible par aucun script
  committé (mesure ad hoc non archivée). Timezone : rien à signaler (epoch ms
  UTC de bout en bout).

**Couverture** : bonne et ciblée sur les bons risques (tests anti-leakage par
mutation du futur, DSR, purge K-fold). Manques : l'usage de `summarize_strategy`
sur returns chevauchants (L-2) et l'alignement signal/fwd des scripts P1/P3
(L-3) ne sont testés nulle part ; les scripts CLI n'ont pas de tests.

### 10.2 Pipeline opérationnel (ingest → features → modèle → signal)

**Synthèse** : lab autonome bien structuré, anti-fuite majoritairement rigoureux
(~801 fonctions de test), mais 4 défauts réels de fiabilité runtime, tous liés
aux gaps de données. **Divergence doc-vs-code importante** : aucune interface
avec Tik core n'existe dans ce dépôt — zéro référence à `tik`, au publisher, à
Redis, à « ADR-030 » ou à un horizon « micro » (grep exhaustif). Le côté Tik
(`POST /signals/ingest`) est prêt, mais **rien ne publie depuis le lab** : la
consommation SHADOW décrite dans les ADR n'est pas implémentée ici.

Constats principaux :

- **L-4 MAJEUR — `ingest.py:80-97` : la bougie en cours est persistée comme
  fermée, définitivement.** Le bootstrap REST marque toutes les lignes
  `closed: True` ; l'`INSERT OR IGNORE` de `storage.py` fait que la vraie bougie
  fermée arrivant ensuite par WS est ignorée → **une bougie corrompue par
  timeframe à chaque restart** (redémarrage à 14 h → la bougie 1d du jour figée
  avec 14 h de données), consommée par features, labels, entraînement et
  résolution des prédictions.
- **L-5 MAJEUR — aucun rattrapage de gap après reconnexion WS**
  (`ingest.py:110-175`) : les klines fermées pendant une déconnexion sont
  perdues ; après un trou de 30 min sur du 1m, `ret_60` couvre 90 min
  silencieusement.
- **L-6 MAJEUR — WS peut mourir silencieusement sans reconnexion**
  (`config.py:76` : pings désactivés ; connexion TCP semi-ouverte → `async for`
  bloqué indéfiniment). La staleness est observée (`ws_reliability`) mais **rien
  ne relance le stream**, et `state.ws_connected` reste True → même le malus de
  confiance ne s'applique pas. Stall permanent jusqu'au restart.
- **L-7 MAJEUR — labels/résolutions faussés autour des gaps**
  (`storage.py:450-455`, `online_predictor.py:188-204`) : une prédiction 1m
  peut être résolue contre une bougie 30 min plus tard comme si c'était +1 min.
  Ces labels erronés contaminent le hit rate, le **recalibrage** des
  calibrateurs et l'apprentissage online river.
- MINEUR — pas de purge/embargo aux frontières des folds walk-forward
  (`model.py:95-107`) — fuite matériellement nulle aujourd'hui (H=1 partout)
  mais piège latent pour tout H>1, et le test anti-fuite mute les retours en
  **préservant leur signe** (labels binaires inchangés → structurellement
  incapable de détecter cette fuite). — Calibrage réajusté sur tout l'historique
  sans fenêtre (`signal_runner.py:103`, mélange les versions de modèle). —
  Gate drift jamais actif sur 4h/1d (`no_data` → `stable` par construction).
- INFO — timezone propre (epoch ms UTC partout), DuckDB bien défendu
  (checkpoint atexit/SIGTERM), pas de fuite train/serve sur le chemin live
  (testée par symétrie).

**Couverture** : bonne à très bonne (77 fichiers, vrais tests de propriété
anti-fuite par mutation du futur, fault-injection WS, e2e go-long). Les 4 angles
morts correspondent exactement aux 4 MAJEURS : bootstrap non testé, aucun test
de gap, aucun test du hang WS, test anti-fuite walk-forward inopérant.

### 10.3 Suite de tests (exécutée le 2026-07-02)

**811 verts + 15 échecs au premier passage sur environnement vierge**, tous dans
`test_monthly_performance.py` pour une cause unique d'environnement : `pytz`
manquant (requis par DuckDB pour `to_timestamp`/`date_trunc`,
`monthly_performance.py:168`, non déclaré dans `requirements.txt` — pandas 3.x
ne le tire plus en transitif). Après installation de pytz : **826/826 verts**.
→ MINEUR : ajouter `pytz` à `requirements.txt`.

---

## 11. Priorités recommandées

**P0 — avant la prochaine mesure de décision (juillet) :**
1. C-1 : porter le sous-échantillonnage non chevauchant dans
   `measure_post_fix_hit_rates.py` / `backtest_dual_lens.py` /
   `backtest_numeric_sources.py` + unifier neutral=0.
2. Look-ahead COT (mardi→vendredi) et vérification DXY/ALFRED — avant la
   re-mesure DXY/COT.
3. M-1 : resynchroniser `source_health` (CryptoCompare 3 h→36 h, GDELT 2 h→6 h)
   — sinon fausse alerte critique permanente dès le retour du quota CC.

**P1 — fiabilité runtime (quelques heures de dev) :**
4. Rétro-porter le try/except Redis + superviser les tasks des 8 ingesters
   anciens (le pattern existe dans polymarket_ingester).
5. Fix warm-up breaking-news (rafraîchir le flag tant que le process vit, ou le
   remplacer par un flag mémoire process).
6. M-2 : `html.escape()` sur tous les titres injectés dans Telegram HTML.
7. E2E-1 : valider les payloads contre les schémas au publish (fail-fast).
8. S-2 : SAVEPOINT par event dans `upsert_macro_event`.

**P2 — hygiène (opportuniste) :**
9. A-1/D-1 : masquer la clé WS dans les logs d'accès ; TLS devant `IP:8200`.
10. S-1 : politique de rétention (au moins dédup/purge `headlines`).
11. `/openapi.json` privé en prod ; test générique « toute route sans clé → 401 ».
12. Espacer le breaking-news Google News (90 s → 5 min ?) pour protéger l'overlay
    sentiment BTC restant.
13. Tests manquants ciblés : orchestration `analyze_*`, warm-up breaking-news,
    invariants intervalles anti-quota, migration Alembic sur base vierge.

---

## 12. Statut des corrections (2026-07-02, même journée)

Suite à la demande « corrige tout », les constats actionnables ont été corrigés
le jour même, sur la même branche. **Vérification : suite Tik complète
1750/1750 verte (1610 + 140 nouveaux tests), ruff check + format verts sur
tous les fichiers modifiés ; suite lab 875/875 verte.**

### Corrigé — Tik

- **C-1 CRITIQUE** ✅ : helper `non_overlapping_subsample` partagé dans
  `backtest.py` ; les p-values/verdicts de `measure_post_fix_hit_rates` et
  `backtest_dual_lens` viennent désormais du sous-échantillon non chevauchant
  (N_total ET N_indépendant affichés). Convention `neutral = 0` unifiée
  (⚠ effet de bord assumé : l'`avg_gain_pct` des signaux neutral affiché par
  `/metrics/hit_rate` passe de −|delta| à 0).
- **Look-ahead COT** ✅ (`COT_PUBLICATION_LAG_DAYS = 3`, mardi → vendredi de
  publication) ; **look-ahead DXY** ✅ (`--dxy-lag-days`, défaut 7 j, à affiner
  contre ALFRED) ; **troncature klines** ✅ (couverture réelle vs fenêtre
  demandée + compteur dédié + WARNING) ; **multiple-testing des recos** ✅
  (Bonferroni par cellule, étiquetage « indicatif » sinon).
- **M-1 source_health** ✅ : CryptoCompare 3h→36h, GDELT 2h→6h + nouveau module
  `aggregator/polling.py` (source unique des intervalles) + test croisé
  `max_age_s ≥ 3× intervalle` + verrous anti-régression des intervalles
  anti-quota (Bug 15).
- **Ingesters** ✅ : écritures Redis des 8 ingesters anciens sous try/except
  (pattern polymarket), supervision des tasks (`task_supervision.py`, log
  `ingester.task_died`), `stop()` défensifs, TTL 25h sur `tik.macro.last.*`,
  warm-up breaking-news en flag processus (plus d'expiration à 7 j), intervalle
  breaking-news configurable (défaut 300 s pour protéger le quota Google News),
  backoff Reddit sur 403 répétés (6 h, auto-récupération), docstrings périmées
  corrigées.
- **M-2 Telegram** ✅ : `escape_html` appliqué à toutes les interpolations
  externes (briefing, alerts), troncature 4096, retry 429 (`retry_after`) et
  5xx/timeout — nouveau `test_telegram.py`.
- **E2E-1 publisher** ✅ : validation Pydantic fail-fast des
  evidence/triggers/counter_scenarios au publish. **S-2 macro** ✅ : SAVEPOINT
  par event dans `upsert_macro_event` (un event invalide ne perd plus le
  batch). **WS** ✅ : `finally` défensif + garde-fou « code source » Bug 16.
- **API** ✅ : `/openapi.json` masqué en production, filtre de redaction
  `api_key` dans les logs uvicorn (`ApiKeyRedactionFilter`), 409 sur TOCTOU
  entities, 422 sur `signals/ingest` avec entity inconnue, tests HTTP
  `/entities`, **test générique « toute route sans clé → 401 »** (verrouille
  l'auth opt-in pour les routes futures).
- **Scoring (gardes)** ✅ : DataFrame vide → cycle survivant + advisory
  `technical_note=insufficient_history` (testé bout-en-bout fetch mocké),
  momentum 15m off-by-one corrigé (iloc[-16]), libellé DXY « var {n}d »
  dynamique, docstring `get_source_score` honnête.
- **Dashboard** ✅ : `parseUtcIso` dans `outcome.ts` (dernier bypass), flag
  d'annulation local au cycle dans `useDashboardKpis`, fusion (au lieu
  d'écrasement) de l'historique persisté à l'hydratation Alerts/Watchlist,
  `busy` périmé retiré, typage `HttpClient` propre — `tsc --noEmit` vert.

### Corrigé — btc-research-lab

- **L-4** ✅ bougie en formation exclue du bootstrap (critère `close_time`
  passé) ; **L-5** ✅ rattrapage de gap borné (500/TF) à chaque connexion WS ;
  **L-6** ✅ watchdog staleness (`WS_STALE_RECONNECT_S=90`, `ws_connected=False`
  pendant le trou) ; **L-7** ✅ résolution contiguë uniquement (tolérance ±10 %,
  gap avéré → `unresolvable_at_ms`, migration schema v7, exclu des
  stats/calibration) + même contrôle avant `learn_one` online.
- **L-1** ✅ baselines `always_short`/`always_long` + contrat de discipline
  `passes_discipline_contract` (battre la meilleure baseline de tendance) +
  `always_short` auditée par le red-team ; **L-2** ✅ Sharpe/CIs de tête sur
  sous-échantillon non chevauchant (pas 21 j) ; **L-3** ✅ entrée décalée d'une
  barre dans le harnais P1 (le verdict RÉFUTÉ ne peut pas s'inverser — le fix
  dégrade strictement la perf mesurée ; à reconfirmer sur la DB réelle).
- Purge walk-forward (`label_horizon`) + test anti-fuite durci (inversion de
  signe), ligne morte `sort_values` supprimée, gp_search honnête (baseline
  sélectionnée sur VAL), `±inf → NaN` dans labels, fin des `fillna(0)`
  masquant les gaps (evaluation + robustness), `pytz` dans requirements.

### Volontairement NON corrigé (décisions réservées)

- **SDK** : gelé (ADR-022) — les 2 MAJEURS « au dégel » restent documentés
  dans ce rapport, à traiter à la levée du gel, pas avant.
- **cross_validator (zero-MAD, dispersion outliers incluse)** : recalibration
  explicitement différée par ADR-026 (Axe #1 — ne pas gonfler la veracity).
- **TLS devant `IP:8200`** (D-1/A-1 réseau) : infra VPS, pas du code — la
  redaction des logs est faite, le chiffrement du transport reste à décider
  (reverse proxy).
- **Resync REST de l'onglet Alertes** (D-2) : nécessite un endpoint backend
  d'historique d'alertes — décision produit.
- **Rétention/purge des tables** (S-1) : politique de rétention à décider
  (dédup `headlines`, `drop_chunks` Timescale) — nécessite un choix
  utilisatrice sur la profondeur d'historique à garder.
- **Correction rétroactive des prédictions lab déjà mal résolues** : le fix
  L-7 est forward-only ; re-labelliser ou invalider l'historique contaminé
  est une décision de mesure à prendre avant la prochaine évaluation.

---

*Audit réalisé en environnement isolé — aucune donnée ni service de production
touché. Rapport initial livré comme seul artefact, puis corrections appliquées
le même jour sur demande (cf. section 12).*
