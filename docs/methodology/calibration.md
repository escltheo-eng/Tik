# Méthodologie de calibration des sources sentiment Tik

> Document vivant, mis à jour à chaque cycle de calibration.
>
> **Version actuelle** : Paquet 4 Session 4 (2026-05-02).
>
> **Objectif** : mesurer objectivement la qualité prédictive de chaque source
> sentiment news intégrée à Tik (Google News BTC + GOLD, CryptoCompare BTC,
> Reddit BTC, GDELT GOLD), du classifier NLP utilisé (Ollama vs keywords),
> et des sources numériques (Fear & Greed, DXY, COT). Déclencher des
> ajustements **mesurés et justifiés** de `SOURCE_SCORES` plutôt qu'à
> l'intuition.

---

## 1. Pourquoi calibrer

Les Sessions 1 à 3 du Paquet 4 ont ajouté 3 nouveaux ingesters textuels
(Google News BTC + GOLD, Reddit BTC, GDELT GOLD), chacun avec un score
de crédibilité **provisoire** dans `SOURCE_SCORES` :

- `google_news_rss` : 0.70
- `cryptocompare_news` : 0.70
- `reddit_btc` : 0.65
- `gdelt_news` : 0.75

Ces scores sont des **hypothèses raisonnables** pour démarrer, pas des
mesures. La philosophie ADR-006 est *"on ne biaise pas a priori, on
mesurera"* — la Session 4 met en place le protocole de mesure.

Sans calibration :

- On ne sait pas si Ollama capte mieux la sémantique financière qu'une
  analyse par mots-clés simpliste
- On ne sait pas si Reddit (retail bruité) apporte autant ou moins
  d'information que les sources mainstream
- On ne sait pas si le mapping contrarian de GDELT (ADR-010) est valide
  pour BTC (déploiement reporté Session 4+)
- On ne peut pas justifier objectivement un ajustement de `SOURCE_SCORES`

## 2. Protocole en 6 étapes

### Vue d'ensemble

```
┌──────────────────┐
│ collect_golden   │  Récupère 100 items frais depuis les sources de prod
│   (script CLI)   │  (50 BTC mixés + 50 GOLD), stockés dans raw_items.jsonl
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ annotate_golden  │  L'humain annote bull/bear/neutral à la main, blinded
│   (CLI interactif)│  Sortie : annotations.jsonl
└────────┬─────────┘
         │ (l'humain n'a PAS vu les predictions)
         ▼
┌──────────────────┐
│ predict_golden   │  Recalcule les predictions Ollama + keywords sur les mêmes items
│   (script batch) │  Sortie : predictions.jsonl
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ backtest_golden  │  Récupère le prix asset à T+1h, T+6h, T+24h, T+5j
│   (script batch) │  Sortie : prices.jsonl (multi-horizon)
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│measure_calibration│ Joint les 4 fichiers par id, calcule métriques
│   (script CLI)   │  Sortie : calibration_report.json + .md
└──────────────────┘
```

### Étape 1 — Collecte (`collect_golden.py`)

**Refetch on-the-fly** depuis les sources de production (Google News RSS,
CryptoCompare API, Reddit JSON), sans modifier le schéma DB et sans
toucher aux ingesters Redis. Le script écrit directement dans
`core/data/golden_dataset/raw_items.jsonl` (mounté en volume Docker `rw`).

**Quotas par défaut** (50 items par asset) :

| Asset | Source | n |
|---|---|---|
| BTC | google_news (Bitcoin query) | 17 |
| BTC | cryptocompare (BTC category) | 17 |
| BTC | reddit (r/Bitcoin + r/CryptoMarkets) | 16 |
| GOLD | google_news ("gold price" query) | 50 |

**Note** : pas d'annotation textuelle pour les sources numériques (Fear &
Greed, GDELT tone, DXY, COT). Leur calibration se fait par un protocole
distinct (étape 7) qui compare directement le bias produit par leur
mapping au mouvement de prix sur série historique étendue.

**Format `raw_items.jsonl`** :

```json
{
  "id": "<sha256(asset|source|text)[:16]>",
  "asset": "btc" | "gold",
  "source": "google_news" | "cryptocompare" | "reddit",
  "text": "<titre>",
  "metadata": { "publisher": "...", "url": "...", "subreddit": "...", "score": 123 },
  "fetched_at": "2026-05-01T18:09:06+00:00",
  "fetch_price": 78529.83
}
```

`fetch_price` est snapshoté **au moment de la collecte** pour servir de
prix de référence dans le backtest. `id` est un hash stable
(sha256 hex tronqué à 16 chars) qui sert de clé de jointure entre les
4 fichiers JSON Lines.

### Étape 2 — Annotation manuelle blinded (`annotate_golden.py`)

**Trinaire** : `bull` / `bear` / `neutral`. Annoter dans un ordre
**randomisé avec seed fixe** (42) pour réduire la fatigue d'ordre et le
biais d'effet de groupe (tous les BTC d'affilée → fatigue concentrée
sur GOLD).

**Blindness garantie** par construction : le script ne charge **pas**
`predictions.jsonl`. L'humain annote sans voir ce que les classifiers
ont prédit. Une fois `predict_golden.py` lancé, `annotate_golden.py`
peut continuer à compléter mais l'annotateur est responsable de ne pas
ouvrir `predictions.jsonl`.

**Aide à l'annotation** (sessions 4+) :

- **Traduction live anglais → français** via Ollama (modèle `llama3.2:3b`,
  ~1-2 sec par titre). Affichage côte-à-côte EN + FR pour vérification.
- **Glossaire** `core/data/golden_dataset/glossaire-news-fr.md` (~80 termes
  ciblés crypto / or / macro / régulation / technique). À garder ouvert
  dans VS Code à côté du terminal d'annotation.

**Limites assumées du LLM 3B** : la traduction inverse parfois la
sémantique des termes techniques précis (ex. "supply" ↔ "demand"). Le
glossaire reste la référence absolue en cas de divergence.

**Format `annotations.jsonl`** :

```json
{ "id": "<hash16>", "verdict": "bull" | "bear" | "neutral",
  "annotated_at": "2026-05-02T13:30:00+00:00" }
```

**Resume-friendly** : append immédiat à chaque verdict. Sortie cleanly
via `q` ou Ctrl+C, reprise via la même commande.

### Étape 3 — Predictions classifier (`predict_golden.py`)

Pour chaque item, on appelle :

- `KeywordClassifier` (asset-agnostic, mots-clés statiques, sync interne)
- `OllamaClassifier` **asset-aware** : un classifier par asset BTC/GOLD
  avec son `asset_name` injecté dans le prompt (cf. ADR-008). Construit
  en parallèle via `asyncio.gather` au boot (économie ~2s).

**Format `predictions.jsonl`** :

```json
{
  "id": "<hash16>",
  "asset": "btc" | "gold",
  "source": "...",
  "predictions": {
    "keywords": { "verdict": "bull" | "bear" | "neutral",
                  "n_bull": int, "n_bear": int, "method": "keywords" },
    "ollama":   { "verdict": "bull" | "bear" | "neutral" | null,
                  "method": "ollama:llama3.2:3b" | null }
  },
  "predicted_at": "..."
}
```

`ollama.verdict = null` quand Ollama est indisponible au boot (la factory
`build_news_classifier` retourne un `KeywordClassifier` en fallback ; on
l'écarte dans ce script et la prédiction Ollama est marquée `null`).

### Étape 4 — Backtest items (`backtest_golden.py`)

Pour chaque item, calcule le delta % du prix asset à plusieurs horizons
après `fetched_at` :

| Horizon | Cas d'usage |
|---|---|
| 1h | Effet flash, news à très courte demi-vie |
| 6h | Effet swing court (réaction marché en cours de session) |
| 24h | Effet swing intra-day clos |
| 5d | Effet swing complet (cohérent avec sweet spot du backtest signaux DB) |

**Sources de prix** :

- BTC : Binance klines 1h (1000 dernières = ~41j de couverture, large)
- GOLD : Yahoo Finance klines 1h (60j de couverture)

**Multi-horizon dispo progressivement** : le script peut être lancé dès
la collecte (deltas 1h, 6h dispos rapidement), puis ré-exécuté plus
tard (deltas 5d dispos après J+5). L'étiquette `available: false` avec
`reason: "horizon_in_future"` rend l'absence explicite.

**Format `prices.jsonl`** :

```json
{
  "id": "<hash16>",
  "asset": "btc" | "gold",
  "fetch_price": 78529.83,
  "fetched_at": "...",
  "deltas": {
    "1h":  { "price": 78600.0, "delta_pct": 0.09, "available": true },
    "6h":  { "price": null, "delta_pct": null, "available": false,
             "reason": "horizon_in_future" },
    ...
  }
}
```

### Étape 5 — Mesure de calibration (`measure_calibration.py`)

Joint les 4 fichiers par `id` et calcule **3 familles de métriques** :

#### 5.1 Concordance humain ↔ classifier

Pour mesurer si le LLM Ollama produit des verdicts alignés avec un humain
qui lit les mêmes titres.

- **Accuracy** : proportion de records où prediction == annotation humaine
- **Confusion matrix** : pour chaque combinaison (predicted, reference),
  nombre de cas observés. Diagonale = accord, hors-diagonale = divergences
  par direction

Interprétation :

| Accuracy | Verdict |
|---|---|
| > 80% | Le LLM est cohérent avec un humain naïf (peut être survalorisé sans risque) |
| 60-80% | Désaccords ciblés, à analyser case par case (où Ollama se plante) |
| < 60% | Le LLM ne capte pas la sémantique comme un humain — réduire son poids dans `SOURCE_SCORES` |

#### 5.2 Calibration vs marché réel (la vérité de référence absolue)

Pour chaque predictor (humain, Ollama, keywords) et chaque horizon, on
mesure le **hit rate** vs delta prix réel :

- `verdict bull` correct si `delta_pct > +threshold` (défaut 0.5%)
- `verdict bear` correct si `delta_pct < -threshold`
- `verdict neutral` correct si `|delta_pct| < threshold`

**Comparaison avec baselines naïfs** :

- `random` (uniforme 1/3 long, 1/3 short, 1/3 neutral, moyenné 100 runs)
- `always_bull` / `always_bear` / `always_neutral`

Si Tik (humain ou Ollama) bat le baseline le plus performant, on apporte
un **edge réel**. Sinon, on est dans le bruit.

#### 5.3 Performance par source

Hit rate par source × predictor × horizon. Permet d'identifier :

- **Quelle source apporte le plus d'edge** (à survaloriser dans `SOURCE_SCORES`)
- **Quelle source est dans le bruit ou pénalisante** (à dévaluer)
- **Pour quelle source quel classifier marche mieux** (Ollama vs keywords)

### Étape 6 — Backtest sources numériques (à venir)

Pour FG, DXY, COT, GDELT tone (séries temporelles), un protocole distinct
parce qu'il n'y a pas de "titre" annotable :

- Récupération de la série historique sur 6-12 mois
- Pour chaque date, calcul du bias selon le mapping actuel
  (ex. tone GDELT ≤ -1 → +0.5 bull GOLD ; FG ≥ 75 → -0.5 bear BTC)
- Comparaison du bias au delta prix N jours après
- Hit rate par tranche de valeur (FG quartiles, GDELT bands ±1/±3)

Validation des seuils empiriques (par exemple les ±1/±3 de GDELT) sur
historique étendu plutôt que sur 50 items récents.

## 3. Architecture des fichiers

```
core/data/golden_dataset/
├── glossaire-news-fr.md          # Aide à l'annotation (~80 termes EN→FR)
├── raw_items.jsonl                # 1. Items collectés
├── annotations.jsonl              # 2. Verdicts humains
├── predictions.jsonl              # 3. Verdicts Ollama + keywords
├── prices.jsonl                   # 4. Deltas multi-horizon
├── calibration_report.json        # 5. Rapport machine-readable
└── calibration_report.md          # 5. Rapport human-readable
```

Tous **versionnés git** pour reproductibilité, sauf si volumes
sensibles. Pas de migration de schéma DB nécessaire.

## 4. Comment lancer le protocole

Pré-requis :

- `docker compose up -d` (Postgres + Redis + core actifs)
- Le service `core` doit avoir le mount `./data:/app/data:rw` actif
  (cf. `core/docker-compose.yml`)
- Ollama tournant sur le Mac hôte avec `llama3.2:3b` chargé

Séquence complète (depuis `core/`) :

```bash
# 1. Collecte (~10 sec)
docker compose exec core python -m tik_core.scripts.collect_golden \
    --asset all --n-per-asset 50

# 2. Annotation (~15-20 min, interactif, peut être fragmenté)
docker compose exec -it core python -m tik_core.scripts.annotate_golden

# 3. Predictions classifier (~2 min, ~1 sec/item via Ollama)
docker compose exec core python -m tik_core.scripts.predict_golden

# 4. Backtest items (~10 sec)
docker compose exec core python -m tik_core.scripts.backtest_golden

# 5. Mesure calibration et rapport (~1 sec)
docker compose exec core python -m tik_core.scripts.measure_calibration
```

Tous les scripts sont **resume-friendly** (sauf `measure_calibration.py`
qui regénère le rapport à chaque exécution — peu coûteux).

## 5. Limites assumées (ouvertement)

| Limite | Mitigation |
|---|---|
| Échantillon ~100 items, 1 cycle de marché | Ré-itérer le protocole tous les 3 mois pour accumuler des cycles |
| Annotateur unique (l'utilisatrice principale) | Les biais individuels existent. À terme : Cohen's κ avec un 2e annotateur |
| Annotation par lecture de titre seul, sans contexte article | Cohérent avec ce que les ingesters voient en prod (titre seul) |
| Traduction Ollama 3B imparfaite sur jargon précis | Affichage EN + FR + glossaire ; règle "dans le doute → neutral" |
| Pas de coûts de transaction inclus dans le hit rate | Cohérent avec le backtest signaux existant. À ajouter en post-prod |
| `seed=42` figé pour le shuffle d'annotation | Reproductibilité > diversité statistique. À varier en Session 5+ si besoin |
| Pas de pondération par confidence du verdict humain | L'utilisateur n'exprime pas son niveau de certitude. À ajouter si on étend |

## 6. Décisions à valider après chaque cycle

À l'issue de chaque exécution complète du protocole, le rapport
`calibration_report.md` doit être lu et permettre de trancher :

1. **Ajustement `SOURCE_SCORES`** : si une source a un hit rate vs marché
   significativement plus élevé / plus bas que la moyenne (delta > 10
   points sur 100 items, > 5 points sur 200+ items), réviser son score
   dans `core/src/tik_core/scoring/swing_engine.py`. Documenter dans un
   ADR si l'ajustement est structurel.

2. **Décision GDELT BTC** : la Session 3 a déployé GDELT uniquement sur
   GOLD parce que le mapping contrarian sur BTC était incertain. Si le
   protocole de calibration montre une corrélation tone GDELT ↔ delta
   BTC exploitable, déployer en Session 5 avec ADR-011. Sinon, archiver
   définitivement la piste BTC.

3. **Choix classifier (Ollama vs keywords)** : si Ollama bat keywords
   significativement sur la mesure marché, valider le choix par défaut
   ADR-006. Sinon, reconsidérer (passage à un modèle plus gros ou retour
   keywords pour certaines sources).

4. **Pertinence d'une source** : si une source a un hit rate vs marché
   au niveau ou en-dessous des baselines naïfs, envisager de la
   désactiver. Mais attention : un score moyen sur 100 items peut juste
   refléter la période — exiger 2+ cycles avant désactivation.

## 7. Risques opérationnels rappelés

- **Garde-fou 1 (mode SHADOW 3 mois)** : strictement applicable. Aucun
  ajustement de `SOURCE_SCORES` ne touche la logique d'exécution Zeta —
  on est en pure observation. CLAUDE.md section 5.
- **ADR-003 (pas de bypass V01-V15)** : inchangé. La calibration ne
  modifie pas le contrat — elle ajuste juste les pondérations internes.
- **Paranoïa contrôlée** : maintenue. Les contre-scénarios continuent
  d'être émis pour chaque signal, indépendamment des scores ajustés.

---

*Mainteneur : utilisateur solo + assistant Claude via extension VS Code.*
*Dernier rapport : `core/data/golden_dataset/calibration_report.md` (regénéré à chaque exécution).*
