# ADR-006 — NLP via Ollama pour le sentiment news (CryptoCompare)

- **Statut** : Accepté
- **Date** : 2026-04-30

## Contexte

L'ingester `cryptocompare_ingester.py` (couche 6 sentiment textuel, ajouté
le 2026-04-29) classifiait les titres de news via une **analyse par
mots-clés** simple (sets `BULLISH_KEYWORDS` / `BEARISH_KEYWORDS` + match
exact mot-à-mot). Trois limites documentées dès l'origine :

1. **Pas de gestion de la négation** : "Fear has eased" est tagué bear
   à cause de `fear`, alors que la sémantique est haussière.
2. **Pas de gestion du contexte / multi-mots** : "Bitcoin holding support"
   et "Bitcoin losing support" matchent tous deux `support` (bull) — faux
   positif net pour le second.
3. **Pas de gestion du sarcasme / second degré** : un titre ironique ou
   un retournement contextuel ("scared but buying") n'est pas captable
   par regex mono-mot.

Ces limites étaient acceptées comme MVP, avec note explicite dans le
fichier source : *« Évolution future : remplacer cette heuristique simple
par un vrai modèle NLP (FinBERT, ou un LLM local via Ollama). »*

Trois questions architecturales se posent au moment de remplacer :

1. **Quel modèle ?** Petit LLM via Ollama (llama3.2:3b, qwen2.5:3b,
   phi3-mini) vs BERT spécialisé via transformers (FinBERT, CryptoBERT).
2. **Quelle stratégie d'intégration ?** Remplacement direct ou
   abstraction permettant de basculer entre méthodes ?
3. **Que faire si le LLM est indisponible** (Ollama down, modèle non
   téléchargé, latence excessive) ?

## Décision

### 1. Modèle : Ollama + `llama3.2:3b` (par défaut, configurable)

**Choix Ollama plutôt que FinBERT/CryptoBERT** malgré une légère
infériorité technique pour la tâche pure de sentiment classification :

| Critère | Ollama (llama3.2:3b) | CryptoBERT (transformers) |
|---|---|---|
| Taille disque | ~2 GB | ~440 MB |
| Latence par titre (M1) | ~150-1000 ms | ~10-30 ms |
| Qualité crypto news | Bonne (zero-shot) | Excellente (fine-tuné) |
| Réutilisable ailleurs dans Tik | ✅ Oui | ❌ Mono-tâche |
| Dépendances Python ajoutées | Aucune | `transformers` + `torch` (~2 GB) |

L'argument **décisif** est la **réutilisabilité** : Tik prévoit (cf.
CLAUDE.md section 8) un module anti-fake-news, un pipeline NLP sentiment
généralisé, voire de la génération d'hypothèses. Une infra Ollama mise
en place une fois sert à tous ces cas. Une dépendance `transformers`
mono-tâche n'apporte rien aux usages futurs.

**Pas de FinBERT** : entraîné sur news financières classiques (stocks,
ratios), pas sur le vocabulaire crypto-spécifique.

**Pas d'API LLM payante** (OpenAI, Anthropic) : budget API à zéro
(cf. CLAUDE.md section 7).

### 2. Pattern Strategy : `NewsClassifier` abstrait avec injection de dépendance

Nouveau fichier `core/src/tik_core/aggregator/news_classifier.py` :

```
NewsClassifier (ABC)                      ← interface neutre
├─ KeywordClassifier                       ← code historique migré
└─ OllamaClassifier (avec fallback interne)
```

**Sélection au démarrage** via `build_news_classifier(settings)` qui
ping Ollama (`GET /api/tags`), vérifie que le modèle demandé est listé,
et retourne soit `OllamaClassifier`, soit `KeywordClassifier` (fallback
si Ollama indisponible au boot).

**Injection** : le `CryptoCompareIngester` reçoit son classifier au
constructeur (DI). Pas de couplage direct au type concret. Conforme à
l'esprit ADR-001 (auth pluggable) — même philosophie d'abstraction.

Trois nouvelles settings (`config.py`, prefix `TIK_`) :

- `news_classifier: Literal["ollama", "keywords"] = "ollama"`
- `ollama_url: str = "http://host.docker.internal:11434"` (défaut Mac)
- `ollama_model: str = "llama3.2:3b"`

### 3. Fallback automatique avec circuit breaker batch-level

Le `OllamaClassifier` possède **un `KeywordClassifier` interne** comme
fallback. Logique :

- Sur erreur HTTP / timeout / parsing échoué pour **un titre** → fallback
  keywords pour ce titre, compteur d'erreurs successives incrémenté.
- Si le compteur atteint **3 erreurs successives** dans le même batch →
  `_batch_circuit_open = True`, les titres restants du batch passent
  direct par les keywords sans tenter Ollama.
- À chaque cycle (toutes les heures), `reset_batch()` est appelé par le
  ingester pour réarmer le compteur et redonner sa chance à Ollama.

**Conséquence opérationnelle** : si Ollama tombe pendant 1 h, un seul
batch est dégradé en keywords ; le suivant retentera automatiquement.
Pas de circuit breaker permanent qui forcerait un redémarrage manuel.

### 4. Prompt et parsing tolérant

Prompt one-shot (pas de few-shot, le modèle 3B suit déjà bien
l'instruction) :

```
You are a financial sentiment classifier for crypto news headlines.
Classify the following headline by its likely impact on the Bitcoin price.
Reply with EXACTLY one word: BULLISH, BEARISH, or NEUTRAL.

Headline: "{title}"
```

Options Ollama : `temperature=0.0` (déterministe), `num_predict=10`
(coupe la génération court).

**Parsing tolérant** : on cherche le premier mot-clé connu
(`BULLISH`/`BEARISH`/`NEUTRAL`) dans la réponse, pas un match strict.
Permet de gérer "BULLISH.", "I think this is BULLISH because...",
"\nbullish\n", etc. Si rien n'est trouvé → log warning + retour neutre
(pas de fallback keywords car le LLM a répondu, juste pas exploitable —
un fallback ici biaiserait le signal).

### 5. Traçabilité backtest : champ `method`

Chaque payload publié dans Redis (clé `tik.sentiment.cryptocompare.btc`)
porte désormais `method: "ollama:llama3.2:3b"` ou `method: "keywords"`,
selon ce qui a réellement classifié le batch. Le script de backtest
(`tik_core.scripts.backtest`) pourra à terme comparer le hit rate des
signaux selon la méthode utilisée — preuve quantitative de l'apport
LLM vs keywords.

## Conséquences

**Positives**

- Gestion native de la **négation** ("Fear has eased" → BULLISH validé
  empiriquement), de la **polarité contextuelle** ("Capitulation may be
  near, smart money accumulating" → BULLISH), et des **multi-mots**
  ("Bitcoin losing support" → BEARISH).
- Architecture **étendable** : ajouter un 3e classifier (CryptoBERT,
  modèle plus gros, API externe) = nouvelle classe + entrée dans la
  factory. Aucun impact sur le ingester.
- **Aucune nouvelle dépendance Python** : seul `httpx` (déjà présent)
  est utilisé pour parler à Ollama.
- **Fallback robuste** : si Ollama tombe, le système continue à publier
  des sentiments via les keywords — pas de hole dans les données.
- **Réutilisabilité** : l'infra Ollama est désormais en place pour les
  modules NLP futurs (anti-fake-news, génération d'hypothèses, etc.).

**Négatives**

- **Dépendance externe au Mac hôte** : Ollama tourne en dehors de Docker.
  Si l'utilisateur éteint son Mac ou ferme l'app Ollama, les ingesters
  Docker basculent en mode dégradé (keywords). Acceptable tant que Tik
  est un projet local — à reconsidérer au déploiement cloud.
- **Latence** : ~1 s par titre × 50 titres = ~50 s par cycle vs <1 s
  avec keywords. Le cycle reste sous le `interval_s = 3600 s`, donc
  aucun impact sur le scheduling. Mais si on étendait CryptoCompare à
  ETH/SOL (× 2-3 currencies), on approcherait du seuil — à surveiller.
- **Variabilité non-zéro** : avec `temperature=0.0`, le LLM est
  largement déterministe, mais pas garanti à 100 %. Un même titre peut
  occasionnellement basculer d'une classification à une autre. Acceptable
  pour un signal agrégé sur 50 titres ; problématique si on classifiait
  un seul titre critique.
- **Faiblesse sur termes techniques précis** : `llama3.2:3b` retourne
  NEUTRAL sur "Higher low forming on the BTC chart" (validé
  empiriquement). Petit modèle, vocabulaire technique de l'analyse
  graphique pas captée. Si on veut couvrir ces cas, monter à
  `llama3.1:8b` (~4.7 GB) — tradeoff RAM/qualité, à arbitrer plus tard.

**Risques opérationnels rappelés**

- **Garde-fou 1 (mode shadow 3 mois)** reste **strictement applicable**
  à ce changement. Tik continue à observer sans influencer Zeta. La
  bascule en classifier LLM ne raccourcit pas la période d'observation.
- **ADR-003 (pas de bypass V01-V15)** **inchangé**. Le score sentiment
  produit par Ollama suit le même chemin d'agrégation que celui des
  keywords (overlay dans `analyze_swing_btc`, contribue à la veracity
  dynamique via `_veracity_from_concordance`).
- **Pas d'augmentation du score de crédibilité `cryptocompare_news`
  dans `SOURCE_SCORES`** (toujours 0.70). Tant qu'on n'a pas mesuré
  quantitativement le gain Ollama vs keywords sur des données réelles,
  on ne biaise pas la veracity à la hausse. Une réévaluation est prévue
  une fois le dataset golden construit (cf. `docs/backlog.md` § 1.B).

## Implémentation (fichiers touchés)

- `core/src/tik_core/aggregator/news_classifier.py` *(nouveau)*
- `core/src/tik_core/aggregator/cryptocompare_ingester.py` *(allégé,
  reçoit `classifier` en DI)*
- `core/src/tik_core/config.py` *(+3 settings)*
- `core/src/tik_core/scripts/run_ingesters.py` *(build du classifier
  au démarrage, injecté dans le ingester)*
- `core/tests/test_news_classifier.py` *(nouveau, 55 tests : 30
  keywords migrés + 25 Ollama mockés)*
- `core/tests/test_cryptocompare_ingester.py` *(supprimé, migré)*
- `docs/backlog.md` *(nouveau, liste des améliorations différées)*
