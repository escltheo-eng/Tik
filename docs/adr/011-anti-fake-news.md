# ADR-011 — Anti fake-news (cross-validation runtime + scoring source dynamique)

- **Statut** : Accepté
- **Date** : 2026-05-03

## Contexte

Tik a livré aux Sessions 1-3 du Paquet 4 quatre overlays sentiment cross-validés sur BTC (Fear & Greed contrarian + CryptoCompare news + Google News + Reddit pondéré log) et quatre sur GOLD (DXY contrarian + COT contrarian + Google News + GDELT NLP scientifique). Le pipeline multi-overlay (ADR-004) calcule la veracity finale sur la moyenne des biais sources via `_veracity_from_concordance`. Mais ce pipeline a deux **angles morts** structurels :

**Angle 1 — Aucun mécanisme de détection des sources contradictoires individuellement aberrantes au moment de l'émission**

Si Reddit dit fortement bull (+0.95) alors que les 3 autres sources disent bear (-0.5), la veracity est calculée sur la moyenne (≈ -0.13) et descend mécaniquement, mais aucun signal "anti fake-news" n'est émis vers le bot client. Le `circuit_breaker_status` de `Signal` (existant en DB depuis le Paquet 1, default `"ok"`) n'est jamais réveillé. Le hook SDK `on_fake_news_detected` (existant depuis Paquet 2 v0.2.0) reste dormant.

**Angle 2 — Aucune adaptation des `SOURCE_SCORES` au comportement réel des sources**

Les scores sont **statiques** dans `SOURCE_SCORES` du `swing_engine.py` (0.65 à 0.90). Les Sessions 1-3 ont assumé volontairement *"on ne biaise pas a priori, on mesurera"* (ADR-006/008/009/010). La Session 4 a livré le pipeline de calibration manuelle (`docs/methodology/calibration.md`), mais l'ajustement reste **manuel** — il faut modifier le code et redéployer. Aucun mécanisme automatique n'apprend du hit rate marché.

Trois questions structurantes :

1. **Algorithme de détection d'outliers** : sur petit échantillon (N=2-5 sources sentiment par décision), quelle méthode statistique choisir ?
2. **Stockage des scores dynamiques** : Redis (rapide), Postgres (audit) ou les deux ?
3. **Activation immédiate ou shadow** : étant donné que l'algorithme peut introduire des bugs, faut-il une bascule sans redéploiement ?

## Décision

### 1. Cross-validation runtime — Modified Z-score + dispersion globale

**Choix structurant** : la détection d'outliers utilise une **logique adaptée à la taille de l'échantillon** plutôt qu'une formule uniforme.

| N | Mécanisme | Justification |
|---|---|---|
| 0-1 | No-op (status `"ok"`) | Trivial : pas de cross-validation possible |
| 2 | Règle disagreement | Modified Z impossible (médiane mal définie). Si signes opposés ET écart > 0.8, on flagge `"degraded"` mais aucune source individuelle marquée outlier (on ne peut pas dire qui ment) |
| ≥ 3 | **Modified Z-score d'Iglewicz-Hoaglin (1993)** + **dispersion globale** | Méthode académique standard pour outliers + détecteur complémentaire pour distributions bimodales |

**Modified Z-score d'Iglewicz-Hoaglin** (`0.6745 × (x - median) / MAD`, seuil 3.5) est l'**algorithme de référence** de la littérature outlier detection sur petit échantillon (Iglewicz & Hoaglin, *"How to Detect and Handle Outliers"*, ASQC, 1993). Il utilise la MAD (Median Absolute Deviation) au lieu de l'écart-type — robuste aux outliers eux-mêmes (MAD ne s'effondre pas face à 1 outlier extrême, contrairement à `std`).

**Fallback seuil absolu** quand MAD = 0 (cas où ≥50 % des valeurs sont identiques) : `|x - median| > 0.3` sur l'échelle [-1, +1] des biais Tik. Plus robuste que IQR (Tukey's fence) sur des distributions skewed avec 3-4 points (Q1 = Q3 = 0 → IQR = 0 → IQR fence inactivable).

**Dispersion globale** par écart-type, indépendante de la détection individuelle : `std ≥ 0.5` → degraded ; `std ≥ 0.85` → tripped. Capture le **cas pathologique** que Modified Z-score laisse passer mathématiquement : la distribution bimodale 50/50 (ex: 2 sources +0.5, 2 sources -0.5 → médiane = 0 → aucun point n'est statistiquement outlier individuel, mais la situation est exactement le disagreement majeur à flagger). La dispersion est calculée sur les **non-outliers** uniquement pour éviter le double comptage.

Le **status final** = pire des deux (max sévérité entre détection individuelle et dispersion globale).

### 2. Effet sur la décision (mode `active`)

Quand `circuit_breaker_status != "ok"` :

- Chaque `evidence` correspondant à une source outlier reçoit `is_outlier: true` (transparence dashboard).
- Le `combined_bias` utilisé pour calculer la veracity **exclut** les outliers (neutralisés).
- Si status = `"tripped"` : `decision.direction` forcée à `"neutral"`, `hypothesis` préfixée *"Anti fake-news: X/Y sources flagged as outliers — direction forced to neutral. (Original: ...)"*. La hypothesis originale est conservée pour audit.
- Le hook SDK `on_fake_news_detected` se réveille naturellement via la propagation `Signal.circuit_breaker_status` → payload Redis → SDK stream.

### 3. Scoring source dynamique — Redis runtime + Postgres audit

| Aspect | Redis | Postgres | Décision |
|---|---|---|---|
| Lecture par cycle d'analyse | O(1) | Surcharge | **Redis** |
| Audit de l'évolution dans le temps | TTL 8j (volatile) | Permanent | **Postgres** (table dédiée) |
| Verdict | Les deux | Les deux | **Hybride** : Redis + table `source_credibility_history` |

**Lecture runtime via Redis** : clé `tik.source_credibility.<source>` (TTL 8 jours, > intervalle scheduler 24h, garantit pas de perte si le job daily skip une exécution). Fallback gracieux sur `SOURCE_SCORES` statique si miss/Redis down.

**Mécanisme d'injection** dans les `_enrich_with_<source>` via **`contextvars.ContextVar`** asyncio. Le caller (`analyze_swing_btc/gold`, `analyze_flash_btc`) précharge les scores Redis et active le context-var au début de son exécution ; chaque helper appelle `get_effective_score(source, fallback)` qui lookup le context-var avant le fallback. Évite de casser la signature des `_enrich_with_<source>` (rétrocompat tests existants 425 → 489 verts) et préserve l'isolation par task asyncio (pas de races inter-cycles).

**Audit Postgres** : nouvelle table `source_credibility_history` avec colonnes `(source, computed_at, score, previous_score, hit_rate, samples, lookback_days, adjustment)`. Une row par source par recalibration (~10 rows/jour). Permet de répondre à *"pourquoi ce score a-t-il été modifié il y a 2 mois ?"* sans avoir à fouiller des logs structlog éphémères.

### 4. Algorithme d'ajustement — asymétrique paranoïa contrôlée

Pénalité plus rapide que récompense :

```
hit rate < 40% sur ≥30 samples → score ÷ 1.2 (penalty)
40% ≤ hit rate ≤ 70% → unchanged
hit rate > 70% sur ≥30 samples → score × 1.1 (reward)
< 30 samples → unchanged (statistique trop faible)
```

Cap final `[0.30, 0.95]` :
- borne basse 0.30 évite l'effondrement total d'une source temporairement maladroite (récupérable),
- borne haute 0.95 évite la sur-confiance qui masquerait une dérive future.

**Asymétrie pénalité/récompense (÷1.2 vs ×1.1) : choix calibré au pifomètre, à réviser**. Les coefficients exacts (1.2, 1.1) sortent d'un point de départ raisonnable cohérent avec la philosophie *"mesurer avant de récompenser"*. La règle structurelle (**pénalité significativement plus forte que récompense**) est ce qui compte, pas les nombres précis. Réévaluation prévue au cycle de calibration suivant (Session 4-bis du 2026-05-06+).

**Lookback 30 jours** : compromis entre réactivité (7j → trop peu de samples) et latence d'adaptation (90j → trop lent). Avec 96 signaux BTC swing/jour × 30j × 4 sources = ~11 500 samples/source maximum théorique. En pratique avec déduplication des sources par signal et signaux GOLD plus rares : ~50-200 samples/source/cycle, suffisant pour un seuil de 30 minimum.

### 5. Mode `active` vs `shadow` (feature flag d'env)

Variable d'environnement **`TIK_ANTIFAKENEWS_MODE=active|shadow`** (défaut `active`).

| Mode | Comportement |
|---|---|
| `active` (défaut) | `circuit_breaker_status` mis à jour, evidence outlier flaggée, direction forcée à neutral si `tripped` |
| `shadow` | Cross-validation calculée, log structuré `anti_fake_news.flagged`, **decision inchangée** |

**Garantie de réversibilité sans redéploiement** : si l'algorithme a un bug en production, bascule via `TIK_ANTIFAKENEWS_MODE=shadow` + `docker compose restart` du scheduler. Coût ajouté : 10 lignes de code, négligeable.

**Pourquoi pas `shadow` par défaut** : la garde-fou 1 (Tik shadow vs Zeta pendant 3 mois) couvre déjà le risque d'impact sur les trades. Un signal `tripped` aujourd'hui ne déclenche aucune action Zeta — c'est le moment idéal d'activer la détection **avant** la connexion Zeta. Activer en production permet de valider sur les signaux réels (~96 BTC swing/jour × 4 overlays = 384 cross-validations/jour, dataset rapidement statistiquement parlant).

### 6. Périmètre exact

**Sources concernées par le scoring dynamique** (`RECALIBRATABLE_SOURCES`) :

```
alternative_me_fng, cryptocompare_news, google_news_rss, reddit_btc,
gdelt_news, fred_dtwexbgs, cftc_cot, binance_orderbook, binance_aggtrades
```

**Sources EXCLUES** : `binance_klines`, `yahoo_finance`, `binance_klines_1m`. Ce sont les sources de prix de marché elles-mêmes (les inputs techniques d'analyze) — leur "crédibilité" n'a pas de sens, elles n'apportent pas un overlay sentiment dont la qualité prédictive serait mesurable.

**Job APScheduler** : `recalibrate_sources` cron daily 03:00 UTC, dans `run_scheduler.py`. `max_instances=1, coalesce=True` (cohérent avec les autres jobs). Pas de premier run immédiat (30j de signaux ne sont peut-être même pas dispos en environnement frais).

**Schéma `Signal` (existant) propagé** : le payload Redis publié par `publisher.py` porte déjà `circuit_breaker_status` (cf. ligne 84 de `_publish_signal`). Le SDK consomme déjà ce champ pour réveiller le hook `on_fake_news_detected` (cf. `sdk/src/tik_sdk/stream.py:286`). Pas de changement schéma DB ni Pydantic — l'infra dormante du Paquet 1 + Paquet 2 est juste réveillée. Ajout d'un seul champ optionnel au schéma `Evidence` Pydantic : `is_outlier: bool | None = None` (transparence côté API/dashboard).

### 7. Asymétrie volontaire avec d'autres ADR

Cette décision **NE modifie pas** :

- ADR-003 — pas de bypass des V01-V15 côté Zeta. Tik en shadow pendant 3 mois reste applicable strictement. Anti fake-news enrichit la décision Tik, n'expose aucun nouveau canal d'exécution.
- ADR-004 — multi-overlay pattern. Le `combined_bias` reste calculé sur la moyenne des biais sources, juste avec exclusion des outliers détectés.
- ADR-006 — pattern Strategy classifier sentiment. Inchangé.
- Pipeline calibration manuel (Session 4) — coexistera avec le scoring dynamique automatique. Le manuel reste utile pour valider/ajuster les seuils d'algo (degraded/tripped, MIN_SAMPLES, lookback) ; l'automatique applique au runtime ce que le manuel a validé.

## Conséquences

**Positives**

- **Réveil de l'infra dormante** : `Signal.circuit_breaker_status` (Paquet 1) + hook SDK `on_fake_news_detected` (Paquet 2) sont enfin actifs. Pas de modification de schéma DB ni de SDK.
- **Détection symétrique** : Modified Z-score d'Iglewicz-Hoaglin couvre l'outlier individuel isolé ; dispersion globale couvre la distribution bimodale 50/50. Combinaison robuste sur petit échantillon (N=2-5).
- **Scoring auto-adaptatif** : les sources qui se révèlent peu prédictives (hit rate < 40 %) voient leur score baisser progressivement, sans intervention humaine. Pénalité asymétrique cohérente paranoïa contrôlée.
- **Audit traçable** : table `source_credibility_history` permet de comprendre pourquoi un score a évolué dans le temps. Couplé au pipeline de calibration manuel (Session 4), donne une vision long-terme de la qualité de chaque source.
- **Réversibilité** : `TIK_ANTIFAKENEWS_MODE=shadow` permet de basculer en cas de bug sans redéploiement.
- **71 nouveaux tests** (39 cross-validator + 32 source_credibility) couvrant les edge cases mathématiques (MAD=0, bimodal, asymétrie pénalité/récompense, cap min/max, fallback hiérarchique Redis/static).

**Négatives**

- **Coefficients ÷1.2 / ×1.1 calibrés au pifomètre** : assumé ouvertement. À réviser au cycle de calibration suivant.
- **Approximation hit-rate-par-source** : un signal qui réussit/échoue est attribué à TOUTES ses sources d'evidence simultanément. Approximation de premier ordre (les sources contributives ne sont pas individuellement attribuables) — une attribution plus fine demanderait des feedbacks granulaires (à venir quand Zeta enverra du POST /feedback). Dans l'attente, la moyenne sur 30+ samples lisse le bruit d'attribution.
- **Cas degraded/tripped via ratio outliers individuel rare en pratique sur N=4** : Modified Z avec seuil 3.5 est conservateur, peu de scénarios atteignent 50 %+ d'outliers individuels. C'est précisément pourquoi on ajoute la dispersion globale — qui couvre les distributions bimodales équilibrées que le ratio individuel rate.
- **Latence légèrement augmentée** : ~5-10 ms par cycle pour le préchargement Redis (4-5 GET) + cross_validate (statistics pure Python). Négligeable.
- **Recalibration job daily** : si la DB n'a pas 30+ jours de signaux, certaines sources ne seront pas ajustées (status `unchanged` avec 0 samples). Comportement défensif voulu — mieux pas ajuster que ajuster avec trop peu de données.

**Risques opérationnels rappelés**

- **Garde-fou 1 (mode shadow 3 mois)** **strictement applicable**. L'anti fake-news ne raccourcit pas la période d'observation Tik vs Zeta — il augmente la qualité observationnelle pendant cette période.
- **ADR-003 (pas de bypass V01-V15)** **inchangé**. Anti fake-news enrichit la décision Tik côté core ; le bot Zeta consomme cette décision exactement comme avant.
- **Garde-fou 2 (budget test 5 %)** rappelé pour mémoire au moment du switch shadow → actif.
- **Section 6 paranoïa contrôlée** : maintenue. Les contre-scénarios continuent d'être attachés à chaque signal, indépendamment de la cross-validation.

## Implémentation (fichiers touchés)

### Nouveaux

- `core/src/tik_core/scoring/cross_validator.py` *(nouveau, ~250 lignes)*
- `core/src/tik_core/scoring/source_credibility.py` *(nouveau, ~280 lignes)*
- `core/migrations/versions/20260503_0000_0003_source_credibility_history.py` *(nouveau)*
- `core/tests/test_cross_validator.py` *(39 tests)*
- `core/tests/test_source_credibility.py` *(32 tests)*

### Modifiés

- `core/src/tik_core/config.py` *(ajout `antifakenews_mode: Literal["active", "shadow"] = "active"`)*
- `core/src/tik_core/storage/models.py` *(ajout `SourceCredibilityHistory`)*
- `core/src/tik_core/storage/schemas.py` *(ajout `Evidence.is_outlier: bool | None`)*
- `core/src/tik_core/scoring/swing_engine.py` *(ajout `circuit_breaker_status` à SwingDecision, branchement cross_validator + context-var dans analyze_swing_btc/gold, remplacement `SOURCE_SCORES.get` par `get_effective_score` dans 7 helpers `_enrich_with_<source>`)*
- `core/src/tik_core/scoring/flash_engine.py` *(idem swing pour FlashDecision et `_enrich_with_orderbook/aggression`)*
- `core/src/tik_core/scoring/publisher.py` *(propagation `decision.circuit_breaker_status` au lieu de `"ok"` hardcodé)*
- `core/src/tik_core/scripts/run_scheduler.py` *(ajout job `recalibrate_sources` cron daily 03:00 UTC)*

### Documentation

- `docs/adr/011-anti-fake-news.md` *(ce fichier)*
- `docs/comprendre_tik.md` *(nouvelle section "Anti fake-news" en français accessible)*
- `docs/backlog.md` *(traduction FR future devient ADR-012)*
- `CLAUDE.md` *(section 8 — Paquet 5 livré, MAJ version + ADR list)*
