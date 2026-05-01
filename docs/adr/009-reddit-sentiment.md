# ADR-009 — Sentiment retail Reddit (BTC) avec pondération log par upvotes

- **Statut** : Accepté
- **Date** : 2026-05-01

## Contexte

À l'issue de la Session 1 du Paquet 4 (cf. ADR-008), Tik dispose désormais de **2 sources textuelles BTC** : `cryptocompare_news` (crypto-spécifique éditorial) et `google_news_rss` (mainstream). Ces deux sources partagent un même profil : **éditorial professionnel**. Elles passent par des filtres rédactionnels (CoinDesk, Reuters, Bloomberg, FT, Yahoo Finance), capturent le « narratif officiel », et reflètent une élite informationnelle.

Il manque à Tik la **voix retail communautaire** — le sentiment de l'utilisateur final, du trader amateur, du holder long terme. Cette voix :

- précède parfois les news mainstream (capitulation 2022 visible sur r/Bitcoin avant Reuters, FOMO retail novembre 2024 visible sur r/CryptoCurrency avant CoinDesk)
- expose les divergences éditorial vs marché (« les news disent bull, le retail panique » est un signal précieux)
- complète l'analyse cross-validation ADR-004 avec un angle indépendant des sources éditoriales

**Reddit** est la source publique la plus mature pour capter ce signal : API JSON gratuite (sans clé pour read-only), 60 req/min anonyme, communautés crypto stables depuis 2010+, format structuré avec **upvotes** comme proxy de validation communautaire.

Trois questions structurantes se posent au moment d'intégrer Reddit :

1. **Quels subreddits ?** r/Bitcoin (mainstream BTC), r/CryptoCurrency (large mais alts), r/CryptoMarkets (trading-focused), r/btc (biais BCH), r/wallstreetbets (macro/équités) ?
2. **Faut-il pondérer le sentiment par les upvotes ?** Reddit a une métrique unique (le score communautaire) que Google News et CryptoCompare n'ont pas. L'ignorer reviendrait à traiter un post à 1 upvote comme un post à 10 000 upvotes — perte d'information massive.
3. **Comment se protéger du brigading et des bots ?** La manipulation orchestrée est connue en crypto Reddit (pump and dump coordonnés, raids de subs).

## Décision

### 1. Subreddits : r/Bitcoin + r/CryptoMarkets agrégés en un score

**Choix de combiner ces deux subs** plutôt qu'un seul ou plus :

| Sub | Membres | Profil | Inclus | Raison |
|---|---|---|---|---|
| r/Bitcoin | ~5M | Retail crypto natif, BTC pur | ✅ | Sentiment communautaire BTC mainstream |
| r/CryptoMarkets | ~1.5M | Orienté trading, plus rationnel | ✅ | Complète r/Bitcoin avec angle trader |
| r/CryptoCurrency | ~7M | Large mais alts dominants | ❌ | Bruit BTC dilué par les memes alt-coins |
| r/btc | ~700k | Biais Bitcoin Cash (fork 2017) | ❌ | Pollution idéologique anti-BTC |
| r/wallstreetbets | ~16M | Macro/équités, ironie omniprésente | ❌ | Cf. décision GOLD ci-dessous |

L'agrégation des 2 subs en **un seul score** (plutôt qu'un score par sub) suit le même principe que l'agrégation cross-publishers de Google News : on cherche un sentiment retail consolidé, pas une analyse par segment.

### 2. Pondération log(score+1) par upvotes

C'est l'**innovation structurante** par rapport au pattern uniforme adopté pour Google News (1 vote par titre) et CryptoCompare (1 vote par article).

**Formule** : pour chaque post `i` avec `score_i = ups - downs` (si filtré `score_i >= 5`) et verdict `v_i ∈ {-1, 0, +1}` (bear, neutral, bull) :

```
weight_i = log(score_i + 1)
score_net = sum(weight_i × v_i) / sum(weight_i)
```

Le `score_net` reste dans `[-1, +1]`, compatible avec `_compute_reddit_bias` qui suit les mêmes paliers que `_compute_google_news_bias` / `_compute_cryptocompare_bias`.

**Intuition de l'échelle log** : un post à 10 000 upvotes pèse `log(10001) ≈ 9.2`, un post à 100 pèse `log(101) ≈ 4.6`, un post à 5 pèse `log(6) ≈ 1.8`. L'échelle log atténue les outliers sans les écraser — un post viral compte plus mais ne domine pas seul. Reflète mieux la réalité que `weight = score` (linéaire, dominé par les viraux) ou `weight = 1` (uniforme, ignore l'engagement).

**Alternatives rejetées** :

- *Pas de pondération* (cohérence avec Google News) : on ignore l'information unique de Reddit. Reddit sans upvotes c'est comme Twitter sans like-count.
- *Pondération linéaire `weight = score`* : un seul post viral à 50 000 upvotes éclipse 100 posts à 50 upvotes. Très instable.
- *Pondération sqrt* : moins extrême que log mais moins explicable. Log est le standard en analyse Reddit (cf. littérature bibliométrique).

### 3. Mitigation brigading et bots via 3 filtres

Le risque manipulation est réel sur Reddit crypto. On le mitige par 3 filtres conservateurs **avant pondération** :

- **`stickied = False`** : skip les posts épinglés par les modérateurs (sticky d'annonce, AMAs) qui forceraient un score artificiellement élevé non représentatif du sentiment courant.
- **`over_18 = False`** : skip les posts NSFW (rare sur subs crypto mais filtre de propreté).
- **`score >= 5`** : ignore les posts brand-new pas encore validés communautairement (en dessous de 5 upvotes, le signal communautaire est trop faible et trop facilement manipulable par 1-2 bots).

Le filtre `score >= 5` est le plus important : il garantit qu'un brigading orchestré nécessite **au minimum 5 votes coordonnés** (vs 1 seul pour passer un seuil plus laxiste). C'est une mitigation, pas une élimination — un brigading à 50+ votes coordonnés reste possible. Ce risque est tracké comme **observation en backlog** : si le dataset golden Session 3 révèle un biais Reddit anormal vs Google News sur des événements connus de pump, on durcira (ex : `score >= 50`, ou comparaison avec `num_comments` pour détecter les anomalies upvotes/comments).

### 4. Périmètre exact

- **Endpoint** : `https://www.reddit.com/r/<sub>/hot.json?limit=50` pour chaque sub. `hot` plutôt que `top:hour` (stale possible) ou `new` (bruit non validé). Algorithme Reddit `hot` = mélange popularité + récence, c'est ce que voient les utilisateurs par défaut.
- **User-Agent obligatoire** : `tik-osint-bot/0.1 (research; contact escltheo@gmail.com)`. Reddit exige un UA unique et descriptif sinon ban IP. Format conforme au guide [reddit-archive/reddit-api-docs](https://github.com/reddit-archive/reddit/wiki/API).
- **Polling toutes les 30 min** : aligné Google News (cohérence cross-source des cycles), ~96 req/jour total (2 subs × 48 cycles), très en dessous du rate-limit 60 req/min anonyme.
- **Score de crédibilité `reddit_btc = 0.65`** dans `SOURCE_SCORES` : un cran sous CryptoCompare et Google News (à 0.70) pour refléter la nature retail amateur, mais pas trop pénalisant. Provisoire — réévaluation après dataset golden Session 3.
- **Clé Redis** : `tik.sentiment.reddit.btc` (TTL 2 h, comme les autres sources textuelles).
- **Champ `top_subreddits`** dans le payload (analogue à `top_publishers` de Google News) : distribution post-filtrage par sub, pour analyse a posteriori sans imposer un ratio fixe r/Bitcoin vs r/CryptoMarkets.
- **Méthode de classification** : `OllamaClassifier(asset_name="Bitcoin")` dédié — 1 instance Reddit indépendante des classifiers Google News BTC et CryptoCompare BTC, pour préserver l'isolation des circuit breakers (cf. ADR-008 décision 3).
- **Pas de Reddit pour GOLD** : décidé en Session 2 et tracé ci-dessous.

### 5. Pourquoi pas Reddit pour GOLD ?

Question légitime, analysée et rejetée pour Session 2. Quatre raisons cumulatives :

- r/Gold (~70k) et r/GoldandSilverStackers (~250k) sont **trop petits et peu actifs** pour produire un échantillon représentatif (3-5 posts/jour vs 50+ pour r/Bitcoin).
- r/wallstreetbets (~16M) parle de gold seulement par épisode (chocs macro), avec ~2-5 % de posts pertinents → **échantillon effectif trop faible** par cycle (~1-3 posts) pour un score statistiquement significatif.
- WSB est culturellement **ironique et meme-driven**. Le LLM `llama3.2:3b` n'est pas calibré pour cet argot (*« apes »*, *« tendies »*, *« stonks »*, *« 🚀 »*). Faux positifs structurels qui dégraderaient la veracity GOLD au lieu de l'améliorer.
- WSB a un **biais long-stocks structurel** : le sentiment GOLD y est souvent connoté « tradfi safe haven boomer ». Pas neutre.

Pour le besoin légitime d'enrichir GOLD en macro/géopol, **GDELT est un meilleur candidat** (flux structuré officiel, ton mesuré scientifiquement, multilingue, pas d'ironie) — à évaluer en Session 3 du Paquet 4.

## Conséquences

**Positives**

- **Voix retail captée** dans le pipeline cross-validation BTC : 4 sources sentiment au total désormais (FG contrarian + CryptoCompare crypto-éditorial + Google News mainstream-éditorial + Reddit retail-communautaire), chacune avec un angle différent.
- **Premier signal pondéré par engagement communautaire** : la pondération log upvotes est une métrique unique à Reddit que les autres sources n'offrent pas. Elle reflète le poids réel d'un post dans la communauté.
- **Architecture étendable** : ajouter une 3e ou 4e sub plus tard = paramètre constructeur supplémentaire. Pas de refonte du pipeline.
- **Aucune dépendance API payante**. Aucune nouvelle dépendance Python (parsing JSON natif via `httpx.json()`, pas besoin de feedparser pour Reddit).
- **Robustesse opérationnelle** : 4e classifier `OllamaClassifier-Reddit-BTC` indépendant. Un incident Ollama sur un ingester ne contamine pas les autres.

**Négatives**

- **Risque manipulation non éliminé** : les filtres `score >= 5` + `stickied=False` mitigent mais n'éliminent pas le brigading orchestré à grande échelle. Acceptable tant qu'on opère en mode shadow et qu'on observera les divergences anormales avec les autres sources via le dataset golden.
- **Latence cumulée** : un 4e classifier Ollama ajoute ~50-80 s de classification par cycle de 30 min. Toujours sous le seuil. À surveiller si on étend à 5+ ingesters textuels.
- **Endpoint Reddit JSON non garanti à perpétuité** : Reddit a déjà serré l'API en 2023 (apocalypse Apollo / Reddit is fun). Le read-only sans clé fonctionne en 2026 mais pourrait évoluer. Mitigation : log warning + cycle suivant retentera, comme pour Google News (ADR-008).
- **Biais structurel r/Bitcoin pro-BTC** : la communauté est par construction holders/maximalistes BTC. Le sentiment y est rarement franchement bear même en marché baissier. Mitigation partielle via r/CryptoMarkets qui est plus neutre, et via la cross-validation ADR-004 (si Reddit dit bull mais Google + CryptoCompare disent bear, le bias moyen tend vers neutre → veracity 0.85).

**Risques opérationnels rappelés**

- **Garde-fou 1 (mode shadow 3 mois)** **strictement applicable**. L'ajout de Reddit ne raccourcit pas la période d'observation.
- **ADR-003 (pas de bypass V01-V15)** **inchangé**. Reddit suit le même chemin d'agrégation que les autres sources.
- **Garde-fou 2 (budget test 5 %)** rappelé pour mémoire.
- **Section 6 paranoïa contrôlée** : les contre-scénarios standard du swing restent attachés à chaque décision. Reddit enrichit l'evidence, ne supprime aucun contre-scénario.

## Implémentation (fichiers touchés)

- `core/src/tik_core/aggregator/reddit_ingester.py` *(nouveau)*
- `core/src/tik_core/scoring/swing_engine.py` *(ajout `SOURCE_SCORES["reddit_btc"]=0.65`, helpers `_read_reddit` / `_compute_reddit_bias` / `_enrich_with_reddit`, branchement dans `analyze_swing_btc`)*
- `core/src/tik_core/scripts/run_ingesters.py` *(ajout 4e `OllamaClassifier-Reddit-BTC` et instance `RedditIngester`)*
- `core/tests/test_reddit_ingester.py` *(nouveau)*
- `core/tests/test_swing_engine.py` *(extension : helpers Reddit)*
- `CLAUDE.md` *(section 8 Paquet 4 Session 2)*
