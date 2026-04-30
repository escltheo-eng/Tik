# ADR-008 — Diversification des sources sentiment news multi-assets (Google News + classifier asset-aware)

- **Statut** : Accepté
- **Date** : 2026-04-30

## Contexte

À l'issue du Paquet 1.x (cf. `CLAUDE.md` section 8), Tik dispose d'**une seule source de sentiment news** : `cryptocompare_news` (cf. ADR-006). Cette mono-source pose deux problèmes structurels :

1. **Fragilité** : si CryptoCompare baisse en qualité éditoriale (rachat 2022 par CoinDesk, dépréciation des votes upvotes/downvotes) ou tombe en panne, l'overlay sentiment de BTC s'effondre. Le pipeline multi-overlay (ADR-004) n'a alors que `alternative_me_fng` comme source de sentiment cross-validée — donc pas de cross-validation effective entre deux **sources textuelles** indépendantes.

2. **Absence totale de news pour GOLD**. Aujourd'hui les seuls overlays GOLD sont `fred_dtwexbgs` (DXY, macro) et `cftc_cot` (positioning institutionnel). Aucun overlay textuel : on ne capte ni les annonces des banques centrales, ni les tensions géopolitiques, ni les flux ETF, qui sont pourtant les premiers drivers du prix de l'or.

L'extension naturelle est d'ajouter une seconde source textuelle, **commune aux deux entities** (BTC et GOLD), pour :
- cross-valider CryptoCompare sur BTC ;
- doter GOLD d'un overlay sentiment news (premier de son genre).

Trois questions architecturales se posent :

1. **Quelle source de news ?** Critères : gratuit, stable, large couverture, multi-asset.
2. **Comment réutiliser le `NewsClassifier`** (ADR-006) qui parle aujourd'hui exclusivement de "Bitcoin price" dans son prompt ?
3. **Comment garantir l'isolation des circuit breakers** entre les différents ingesters textuels qui partagent l'infrastructure Ollama ?

## Décision

### 1. Source : Google News RSS

**Choix Google News plutôt que d'autres sources gratuites** :

| Critère | Google News RSS | Reddit JSON | NewsAPI free | Bing News RSS |
|---|---|---|---|---|
| Clé API requise | Non | Non (read-only) | Oui (100 req/jour) | Non |
| Multi-asset (BTC + GOLD) | ✅ Oui | ⚠️ Crypto principalement | ✅ Oui | ✅ Oui |
| Largeur de couverture éditoriale | Très large (Reuters, Bloomberg, FT, CoinDesk, CNBC, WSJ…) | Communautaire (qualité variable) | Limité au free tier | Large mais Microsoft-centric |
| Stabilité dans le temps | Stable depuis 20 ans | Variable (rate-limit, modifs API fréquentes) | Free tier en risque permanent | Stable mais moins riche |
| Fraîcheur | Quasi temps réel | Quasi temps réel | Délai 24h sur free tier | Quasi temps réel |

L'argument **décisif** est la combinaison **gratuit + multi-asset + stabilité**. Reddit reste pertinent comme source complémentaire (sentiment retail, à venir Session 2 du Paquet 4), mais Google News est la fondation la plus fiable pour démarrer.

**Choix `feedparser` plutôt que parsing XML manuel** : parsing tolérant aux variations de format Google, gestion native RSS/Atom (utile aussi pour Reddit/GDELT à venir), zéro deps natives (pure Python, OK sur M1). Une dépendance ajoutée à `pyproject.toml` pour fiabilité long terme — la maintenance d'un parser maison qui rate silencieusement 10 % des titres est exactement le type de bug qui dégrade la veracity sans alerter.

**Choix de queries simples** :
- BTC : `Bitcoin` (Google News fait du contextual ranking efficace, l'ajout de `OR BTC` introduisait du bruit non-crypto comme Banco do Brasil, Battery Council, etc.)
- GOLD : `"gold price"` avec guillemets pour forcer la séquence exacte (XAUUSD est rare dans les news mainstream, l'ajouter n'apporte rien)

**Polling toutes les 30 min** plutôt que 1 h : la fraîcheur du sentiment est un facteur direct de la qualité de la veracity quand des événements majeurs tombent (hack, décision Fed, défaillance bancaire). ~1440 req/mois total (BTC + GOLD), largement sous radar de tout rate-limit observé. Aligné avec les cycles swing (15 min BTC / 30 min GOLD).

### 2. Classifier asset-aware via paramètre constructeur

Le prompt actuel de `OllamaClassifier` (cf. ADR-006) parle explicitement de **"Bitcoin price"** :

> *"Classify the following headline by its likely impact on the **Bitcoin price**. Reply with EXACTLY one word: BULLISH, BEARISH, or NEUTRAL."*

C'est correct pour CryptoCompare (BTC only) mais biaise le verdict pour GOLD. Un titre comme *"Inflation hits 7%"* est BULLISH pour GOLD (or = hedge inflation) mais MIXED/BEARISH court terme pour BTC — le LLM doit savoir pour quel asset on classifie.

**Solution retenue** : ajouter un paramètre **`asset_name: str = "Bitcoin"`** au constructeur de `OllamaClassifier`, le prompt devient :

> *"...impact on the **{asset_name}** price..."*

Rétrocompat totale (`asset_name` par défaut = "Bitcoin", `CryptoCompareIngester` ne change pas).

**Alternatives rejetées** :

- *Per-call `classify(title, asset_name)`* : casserait la signature actuelle et **partagerait le circuit breaker entre ingesters**. Si un batch Google News sature Ollama, CryptoCompare basculerait en keywords par effet domino — pollution opérationnelle inacceptable.
- *Prompt agnostique sans asset* : moins de contexte pour le LLM 3B → plus de NEUTRAL → moins de signal. La finesse asset-spécifique compte.

### 3. Isolation : 1 instance de classifier par ingester

Chaque `*Ingester` reçoit **sa propre instance** de classifier au constructeur (DI, esprit ADR-001/006). Conséquence opérationnelle Session 1 : 3 instances `OllamaClassifier` au démarrage du conteneur `ingesters` :
- `CryptoCompare-BTC` (asset_name="Bitcoin")
- `GoogleNews-BTC` (asset_name="Bitcoin")
- `GoogleNews-GOLD` (asset_name="Gold")

Coût : 3 pings Ollama au boot (~3 s, one-shot). Bénéfice : **circuit breakers indépendants**. Si Google News BTC fait 3 erreurs successives sur Ollama, son circuit s'ouvre pour son batch ; CryptoCompare BTC continue d'utiliser Ollama normalement. Robustesse opérationnelle supérieure au coût de boot.

### 4. Score de crédibilité `google_news_rss` = 0.70 (provisoire)

Cohérent avec la philosophie ADR-006 : **on ne biaise pas a priori, on mesurera**. Trois alternatives ont été pesées :

- 0.65 (sous CC) : pénalise Google News par hypothèse de bruit publicitaire/SEO — arbitraire sans mesure
- 0.75 (au-dessus de CC) : crédite la qualité éditoriale Reuters/Bloomberg/FT — arbitraire sans mesure
- **0.70 (équivalent CC)** : aucun biais a priori, le pipeline multi-overlay (ADR-004) absorbera les divergences via `_veracity_from_concordance`. Si Google News est de fait plus bruité, la discordance avec les autres sources fera baisser la veracity naturellement — pas besoin de pénaliser via le score.

Le score sert d'**information d'evidence** (transparent pour le bot client / dashboard), pas de pondération du bias dans la veracity. Réévaluation prévue après mesure quantitative via dataset golden (cf. Session 3 du Paquet 4).

### 5. Périmètre fonctionnel exact

- **Nouvelle clé Redis** `tik.sentiment.google_news.{currency}` (TTL 2 h, comme CryptoCompare). Currency = `btc` ou `gold`.
- **Payload identique en structure à CryptoCompare** pour cohérence : `source`, `method`, `currency`, `score`, `n_articles`, `n_bullish`, `n_bearish`, `n_neutral`, `fetched_at`. Champ supplémentaire `top_publishers` (top 5 sources observées) pour analyse a posteriori du biais SEO sans imposer un whitelist a priori.
- **Aucune modification du score de crédibilité `cryptocompare_news`** (toujours 0.70).
- **Aucune modification de l'engine flash** (BTC) : Google News reste sur l'horizon swing, sa fraîcheur 30 min ne convient pas au flash minute-heure.
- **Aucune dé-duplication intra-cycle ou inter-cycle** : la persistance d'un titre 2 cycles consécutifs est interprétée comme un signal d'importance (pertinence prolongée). Si on observe un biais lors du dataset golden, on ajoutera un set Redis de hash de titres avec TTL 24 h.

## Conséquences

**Positives**

- **Cross-validation effective sur BTC** : 2 sources textuelles indépendantes (CryptoCompare crypto-spécifique vs Google News mainstream) qui peuvent se neutraliser ou se renforcer via le pipeline ADR-004.
- **Premier overlay news pour GOLD** : remplit un trou structurel (l'or réagit beaucoup aux news macro/géopol qu'aucune source actuelle ne capte).
- **Architecture étendable** : ajouter Reddit (Session 2) ou GDELT (Session 3) = nouveau ingester + 1 classifier dédié + 1 ligne dans `analyze_swing_xxx`. Pas d'impact sur les sources existantes.
- **Réutilisation maximale de l'infra Ollama** : un seul backend NLP partagé, pas de duplication de modèle ou de logique de fallback.
- **Aucune dépendance API payante** ajoutée. Une seule dépendance Python (`feedparser`).
- **Robustesse opérationnelle** : circuit breakers Ollama isolés par ingester — un incident sur une source ne contamine pas les autres.

**Négatives**

- **Dépendance à un endpoint Google non officiel** : l'URL `news.google.com/rss/search?q=...` n'est pas officiellement documentée. Stable depuis 20 ans en pratique, mais Google peut le casser sans préavis. Mitigation : `feedparser` est tolérant aux variations, et un fail silencieux est loggué via `log.warning("google_news.fetch.error")` côté ingester. Pas de circuit cassant globalement, juste un cycle perdu.
- **Boot plus lent** : 3 pings Ollama (~3 s) avant que les ingesters textuels démarrent. One-shot, acceptable.
- **Volume de classification multiplié par 3** : aujourd'hui ~50 titres/h via CryptoCompare BTC, demain ~150 titres/30min total (3 batches × 50 titres). Latence Ollama estimée ~150 s en cumulé sur les 3 ingesters s'ils tournent en série. Si ça devenait un goulot, on pourrait paralléliser via `asyncio.gather()` les ingesters qui ont chacun leur classifier — pas un blocker pour Session 1, à mesurer en runtime.
- **Bruit SEO/pump non filtré** : Google News retourne tout type de site (Reuters comme PRNewswire). Le LLM Ollama compense beaucoup (titres pumper généralement classés NEUTRAL). On loggue les `top_publishers` observés pour analyse, mais on n'impose pas de whitelist Session 1 (biais de sélection, maintenance pénible). À reconsidérer si Session 3 révèle un biais net.

**Risques opérationnels rappelés**

- **Garde-fou 1 (mode shadow 3 mois)** reste **strictement applicable**. Tik continue à observer sans influencer Zeta. L'ajout de Google News + extension à GOLD ne raccourcit pas la période d'observation.
- **ADR-003 (pas de bypass V01-V15)** **inchangé**. Les nouveaux signaux suivent le même chemin d'agrégation que les sources existantes.
- **Garde-fou 2 (budget test 5 %)** rappelé pour mémoire.
- **Section 6 paranoïa contrôlée** : les contre-scénarios standard du swing restent attachés à chaque décision. L'ajout de Google News enrichit l'evidence, ne supprime aucun contre-scénario.

## Implémentation (fichiers touchés)

- `core/src/tik_core/aggregator/google_news_ingester.py` *(nouveau)*
- `core/src/tik_core/aggregator/news_classifier.py` *(ajout `asset_name` au constructeur de `OllamaClassifier` + factory `build_news_classifier` correspondante)*
- `core/src/tik_core/scoring/swing_engine.py` *(ajout `SOURCE_SCORES["google_news_rss"]=0.70`, helpers `_read_google_news` / `_compute_google_news_bias` / `_enrich_with_google_news`, branchement dans `analyze_swing_btc` et `analyze_swing_gold`)*
- `core/src/tik_core/scripts/run_ingesters.py` *(création de 3 classifiers asset-aware + 2 instances `GoogleNewsIngester`)*
- `core/pyproject.toml` *(+ `feedparser>=6.0.11`)*
- `core/tests/test_news_classifier.py` *(extension : tests asset_name)*
- `core/tests/test_google_news_ingester.py` *(nouveau)*
- `core/tests/test_swing_engine.py` *(extension : helpers Google News)*
