# ADR-012 — LLM hypothesis generator (synthèse contextuelle des signaux)

- **Statut** : Accepté
- **Date** : 2026-05-03

## Contexte

Tik produit aujourd'hui un signal complet (direction, confidence, veracity, evidence multi-source, triggers techniques, counter-scenarios, statut anti fake-news) mais l'**hypothèse résumée** affichée en tête du signal est limitée à une f-string déterministe :

```
Swing long on BTC based on EMA/RSI/MACD confluence (bull=0.65, bear=0.18)
```

Cette hypothèse ignore :
- Les overlays sentiment cross-validés (FG, Google News, Reddit, CryptoCompare, GDELT, DXY, COT) qui constituent l'edge structurant de Tik depuis le Paquet 4
- Le statut anti fake-news ADR-011 (sources flaggées outliers, dispersion globale, status `degraded`/`tripped`)
- Les contre-scénarios (paranoïa contrôlée — section 6 de CLAUDE.md)
- Les niveaux clés et seuils atteints

Le dashboard Expo (Paquet 3, livré le 2026-05-03) expose cette hypothèse au top de la carte signal — c'est ce que l'utilisatrice lit en **premier** pour comprendre pourquoi Tik recommande cette direction. La limite "hypothèses minimalistes" est documentée dans CLAUDE.md section 8 (Paquet 3) et identifiée comme axe d'amélioration prioritaire.

Quatre questions structurantes à résoudre :

1. **Moment de génération** : à la création (sync, dans l'engine) ou à la lecture (lazy, cache) ?
2. **Langue** : EN (cohérence evidence/triggers/CS) ou FR (UX utilisatrice) ?
3. **Mode de bascule** : `disabled` / `shadow` / `active` par défaut ? Comment basculer sans redéploiement ?
4. **Périmètre engines** : tous d'un coup (swing BTC + GOLD + flash BTC) ou step-by-step ?

## Décision

### 1. Moment de génération — Sync à la création (dans l'engine)

**Choix structurant** : la génération se fait dans `analyze_swing_btc/gold` et `analyze_flash_btc` après les enrichissements multi-overlay et la cross-validation anti fake-news, juste avant le retour de la decision. Le payload Redis publié et la row Postgres écrite contiennent l'hypothèse LLM dès t=0.

**Alternatives évaluées** :

| Alternative | Pour | Contre rédhibitoire |
|---|---|---|
| Lazy à la lecture (`/signals/{id}`) | Pas de blocage scheduler | Casse le pattern "1 signal = 1 payload immuable" du publisher (cf. `_publish_signal`). Le stream WS ne porte pas l'hypothèse. Cache Redis nécessaire pour ne pas re-générer à chaque lecture |
| Async post-création (worker en background) | Pas de blocage | Race condition publish initial vs update LLM. SDK reçoit 2 events. Update DB transitoire |

**Argument décisif** : la cohérence du contrat "1 signal = 1 payload immuable" est un invariant structurant de Tik (`_publish_signal` dans publisher.py construit le payload une seule fois). Le coût "1-3s/cycle" est un faux problème (96 swing BTC × 13s typique mesuré = 21 min/jour CPU LLM = 1.5% du temps disponible sur Mac M1). Mieux vaut payer ce coût que fragmenter le pattern.

**Garde-fou perf** : timeout strict 30s sur `apply_llm_hypothesis` (enveloppe asyncio.wait_for) + 25s sur le client httpx interne. Au-delà → fallback template, log warning, scheduler continue.

### 2. Langue — EN seul (FR via ADR-013 future)

| Critère fiabilité | A. EN seul | B. FR seul | C. Bilingue |
|---|---|---|---|
| Qualité llama3.2:3b | ✅ Corpus majoritairement EN | ❌ Erreurs sémantiques sur jargon documentées (CLAUDE.md Paquet 4 Session 4 — *"supply ↔ demand"*) | ⚠️ FR dégradé |
| Cohérence avec evidence/triggers/CS (en EN) | ✅ | ❌ Mix langues dans le même signal | ⚠️ Doubler tout |
| Compatibilité ADR-013 future (traduction lazy `?lang=fr`) | ✅ Hypothèse devient un champ traduisible parmi d'autres | ❌ Casse le pattern | ⚠️ Refonte |
| Coût LLM par signal | 1× | 1× | 2× |

**Argument décisif** : faire FR ici déclasserait la qualité de l'hypothèse à cause des limites du llama3.2:3b en français (déjà constaté lors de la traduction des titres golden dataset). Mieux vaut une hypothèse EN précise + ADR-013 future qui traduira tout le signal d'un coup (evidence + triggers + CS + hypothèse) avec un cache lazy. Cohérence > confort court terme.

**Conséquence** : `docs/backlog.md` entry #2 (traduction native FR) devient ADR-013 et traduira *tous* les champs textuels du signal.

### 3. Mode de bascule — Shadow par défaut, opt-in via env

Variable d'environnement **`TIK_LLM_HYPOTHESIS_MODE=disabled|shadow|active`** (défaut `shadow`).

| Mode | Comportement |
|---|---|
| `disabled` | Aucun appel LLM, `Signal.hypothesis` = template historique |
| `shadow` (défaut) | LLM s'exécute, sortie stockée dans `Signal.advisory["llm_hypothesis_candidate"]`. `Signal.hypothesis` garde le template — validation passive sans risque |
| `active` | LLM remplace `Signal.hypothesis`. Le template est conservé dans `Signal.advisory["template_hypothesis"]` pour audit |

Variable additionnelle **`TIK_LLM_HYPOTHESIS=template|ollama`** (défaut `template`) pour choisir la stratégie. `template` = pas d'appel LLM (mode dégradé permanent). `ollama` = appel LLM via le pattern Strategy.

**Pourquoi `shadow` par défaut (et non `active`)** : ADR-011 a choisi `active` par défaut pour anti fake-news parce que le risque trade était couvert par Garde-fou 1 (Tik shadow vs Zeta 3 mois). Ici le risque est **différent** : l'hypothèse est lue par un humain qui prend des décisions à partir de cette info. Une hypothèse hallucinée *"Strong bullish breakout confirmed"* alors que les données disent *"weak signal at resistance"* serait pire que le template actuel. Le mode shadow permet de valider la qualité de la sortie LLM sur 5-10 cycles avant bascule active.

**Validation côté dashboard** : carte secondaire optionnelle "Hypothèse LLM (en validation)" affichée si `signal.advisory.llm_hypothesis_candidate` existe. ~10 lignes de Tsx, à ajouter au moment de la bascule visuelle.

### 4. Périmètre engines — Tous d'un coup (swing BTC + GOLD + flash BTC)

| Critère fiabilité | A. Tous d'un coup | B. Step-by-step |
|---|---|---|
| Couverture validation shadow | ✅ Plus large dataset (~150 signaux/jour) | ⚠️ Plus étroit |
| Risque (couvert par mode shadow) | ✅ Zéro | ✅ Zéro |
| Effort | 1× | 3× |
| Cohérence pattern | ✅ Module `hypothesis_generator.py` partagé | ✅ |

**Argument décisif** : si shadow couvre le risque (Décision 3), le step-by-step n'a aucune justification. Pattern strictement identique entre les 3 engines = mutualisation parfaite du module. Pour le **flash**, la génération LLM se fait dans `analyze_flash_btc` même si le scheduler skip ensuite via `should_emit()` — coût ~10 min/jour cumulé sur Mac M1, négligeable face à la simplicité d'avoir une fonction self-contained pour tests/backtests directs.

### 5. Format de sortie — 6 sections ~150 mots EN structuré

Structure imposée au LLM via le prompt (ordre fixe) :

1. **Verdict + qualité** (1 phrase) — direction, asset, confidence, veracity, qualité de la concordance
2. **Lecture technique** (1-2 phrases) — quels indicateurs convergent, niveaux clés atteints
3. **Lecture sentiment cross-validée** (2-3 phrases) — chaque source nominativement avec son biais et un descripteur court
4. **Anti fake-news status** (1 phrase) — explicite si `circuit_breaker_status != "ok"` ou outliers, sinon mention courte
5. **Risque principal** (1-2 phrases) — contre-scénario le plus probable nommé, sa probabilité, sa mitigation
6. **À surveiller** (1 phrase) — niveau prix / événement / source à monitorer

**Cible** : 120-180 mots, 6-9 phrases. Lisible mobile en ≤ 30 secondes.

**Garde-fous prompt** :
- *"Use ONLY the data provided below — do NOT invent prices, levels, percentages, sources not present in the input."*
- *"Output ONLY the hypothesis text in the structure above. No preamble, no closing remark, no markdown formatting."*
- `temperature=0.0` (déterministe), `num_predict=350` tokens (~250 mots safety margin)

**Validation post-génération dans `OllamaHypothesisGenerator._is_valid_output`** :
- Longueur 50 ≤ N ≤ 400 mots (sinon fallback template)
- Doit contenir le mot `direction.upper()` (LONG/SHORT/NEUTRAL)
- Doit contenir l'`entity_id` (BTC/GOLD)
- Strip markdown si présent (`**`, `##`, ```, `__`) via `_sanitize_output`

Validation invalide ne décrémente PAS le compteur du circuit breaker (différencie un échec réseau d'un loupé ponctuel du modèle).

### 6. Pattern Strategy + circuit breaker batch-level (clone ADR-006)

Calque exact du pattern `news_classifier.py` (cf. ADR-006) :

- ABC `HypothesisGenerator` avec `async generate(decision, horizon) -> str`
- `TemplateHypothesisGenerator` (fallback historique, déterministe, synchrone)
- `OllamaHypothesisGenerator` (LLM local) avec :
  - Circuit breaker batch-level : 3 erreurs successives → bascule template pour le reste du batch
  - `reset_batch()` appelé en début de cycle scheduler pour réarmer
  - Fallback gracieux sur `TemplateHypothesisGenerator` à chaque erreur réseau OU sortie invalide
- Factory `build_hypothesis_generator(generator_type, ollama_url, ollama_model)` similaire à `build_news_classifier`
- Helper `apply_llm_hypothesis(decision, horizon, generator, mode, timeout_s)` qui gère shadow/active/disabled

**Mécanisme d'injection dans les engines** : paramètre `hypothesis_generator: HypothesisGenerator | None = None` ajouté aux signatures de `analyze_swing_btc`, `analyze_swing_gold`, `analyze_flash_btc`. Rétrocompat totale (tests existants `561 → 600` passants sans modification, default None).

**Préchargement au scheduler** : `build_hypothesis_generator(...)` appelé une fois au démarrage de `run_scheduler.main()`, partagé entre les 3 jobs. `reset_batch()` appelé au début de chaque cycle pour réarmer le circuit breaker.

### 7. Stockage du candidat shadow dans `Signal.advisory`

Le champ JSON `Signal.advisory` existe en DB depuis le Paquet 1 (cf. `models.py` ligne 117) mais n'a jamais été utilisé. ADR-012 le réveille :

- En mode `shadow` : `Signal.advisory["llm_hypothesis_candidate"]` = sortie LLM
- En mode `active` : `Signal.advisory["template_hypothesis"]` = ancienne hypothèse template (audit)

**Pas de modification de schéma DB ni du SDK** : le champ JSON existant accommode toute clé. Le payload Redis publié inclut désormais `advisory` (modification mineure dans `publisher.py:_publish_signal`).

**Update dashboard** : la carte "Hypothèse" affiche `signal.hypothesis` comme aujourd'hui. Une carte secondaire "Hypothèse LLM (en validation)" peut être ajoutée conditionnellement sur `signal.advisory.llm_hypothesis_candidate` — ~10 lignes Tsx, hors scope ADR-012 (sera ajouté au moment de la bascule visuelle).

### 8. Asymétrie volontaire avec d'autres ADR

Cette décision **NE modifie pas** :

- **ADR-003** — pas de bypass V01-V15 côté Zeta. L'hypothèse LLM est purement texte affiché à l'humain ; aucun nouveau canal d'exécution exposé.
- **ADR-004** — multi-overlay pattern. La cross-validation et le calcul de veracity restent inchangés. Le LLM lit la decision finale, ne la modifie pas (sauf le champ `hypothesis` en mode `active`).
- **ADR-006** — pattern Strategy classifier sentiment. Étendu, pas modifié. Le `news_classifier.py` reste indépendant du `hypothesis_generator.py` (deux instances Ollama séparées avec circuit breakers indépendants).
- **ADR-011** — anti fake-news. Inchangé. Le LLM reçoit le `circuit_breaker_status` en entrée et le restitue dans la section 4 de l'hypothèse.

## Conséquences

**Positives**

- **Réveil de l'infra dormante** `Signal.advisory` (Paquet 1) : aucune modification de schéma DB.
- **Hypothèse contextuelle riche** : ~150 mots structurés en 6 sections, citant les sources nominativement, restituant la cross-validation, le risque principal et le niveau à surveiller. Élève la qualité narrative du signal sans toucher la logique décisionnelle.
- **Pattern Strategy mature** : calque exact d'ADR-006, faible coût d'apprentissage. Permet de plugger d'autres backends LLM (OpenAI, Anthropic, mistral local) sans refonte si Ollama 3B s'avère trop limité.
- **Réversibilité totale** : `TIK_LLM_HYPOTHESIS=template` ou `TIK_LLM_HYPOTHESIS_MODE=disabled` désactive tout en 1 ligne d'env + restart. Si la qualité LLM se dégrade, bascule shadow ou disabled sans perdre les anciens signaux.
- **Compatibilité ADR-013 future** (traduction FR) : l'hypothèse EN devient un champ traduisible standard.
- **39 nouveaux tests pytest** couvrant : template, formatters (triggers/evidence/CS/outliers), sanitize markdown, validation post-génération (longueur, mots-clés), generate success + fallback HTTP error + invalid output, circuit breaker open/reset, modes apply (disabled/shadow/active/timeout/exception/unknown/advisory not dict), factory (template/ollama alive/unreachable/model missing).
- **Pas de modification SDK** : le champ `Signal.hypothesis` existe déjà côté SDK Pydantic. Le champ `Signal.advisory` est un dict — le SDK le passera tel quel.

**Négatives**

- **Latence** : ~13s/cycle mesurée sur Mac M1 avec llama3.2:3b et prompt ~600 tokens / 350 num_predict. Cumulé : ~95 min/jour CPU LLM (swing BTC 21 + swing GOLD 10 + flash BTC 62 si on tient compte des cycles skippés par should_emit). Sur un Mac qui tourne 24h/jour, c'est 6.6% du temps — non bloquant mais visible.
- **Markdown résiduel parfois** : llama3.2:3b ne respecte pas toujours la consigne *"no markdown"* et produit des `**Verdict**:` qui sont strippés par `_sanitize_output`. Acceptable.
- **Coefficients timeout 25s/30s calibrés au pifomètre** sur la mesure typique 13s. À réviser si les cycles flash deviennent plus lourds (plus d'overlays).
- **Dépendance Mac hôte Ollama** : héritée d'ADR-006. Si Ollama plante, fallback template robuste — pas de perte de signal.
- **Pas de mesure de hit rate "hypothèse LLM vs template"** : le LLM n'influence pas la décision, donc pas de notion de "succès" mesurable. La qualité reste une appréciation humaine. À évaluer après 2-3 jours de mode shadow.
- **L'hypothèse n'est pas encore traduite en FR** : l'utilisatrice francophone doit lire EN sur son dashboard. Sera résolu par ADR-013 (traduction lazy `?lang=fr`).

**Risques opérationnels rappelés**

- **Garde-fou 1 (mode shadow Tik vs Zeta 3 mois)** **strictement applicable**. L'hypothèse LLM est purement texte affiché — zéro impact sur la décision Tik et zéro impact sur les trades Zeta.
- **ADR-003 (pas de bypass V01-V15)** **inchangé**. Aucun nouveau canal d'exécution.
- **Garde-fou 2 (budget test 5%)** rappelé pour mémoire au moment du switch shadow → actif Zeta.
- **Section 6 paranoïa contrôlée** : maintenue. Les contre-scénarios continuent d'être attachés à chaque signal et sont *résumés* dans la section 5 de l'hypothèse, pas remplacés.

## Implémentation (fichiers touchés)

### Nouveaux

- `core/src/tik_core/scoring/hypothesis_generator.py` *(nouveau, ~370 lignes : ABC + Template + Ollama + factory + apply helper)*
- `core/tests/test_hypothesis_generator.py` *(39 tests pytest)*
- `docs/adr/012-llm-hypothesis-generator.md` *(ce fichier)*

### Modifiés

- `core/src/tik_core/config.py` *(ajout `llm_hypothesis: Literal["ollama","template"] = "template"` + `llm_hypothesis_mode: Literal["disabled","shadow","active"] = "shadow"`)*
- `core/src/tik_core/scoring/swing_engine.py` *(ajout `advisory: dict` à SwingDecision, paramètre `hypothesis_generator` aux 2 fonctions analyze, appel `apply_llm_hypothesis` après cross-validation)*
- `core/src/tik_core/scoring/flash_engine.py` *(idem swing pour FlashDecision et `analyze_flash_btc`)*
- `core/src/tik_core/scoring/publisher.py` *(propagation `decision.advisory` vers `Signal.advisory` + inclusion dans payload Redis)*
- `core/src/tik_core/scripts/run_scheduler.py` *(build du generator au démarrage, passage aux 3 jobs swing/swing/flash, `reset_batch()` au début de chaque cycle, `aclose()` à l'arrêt)*

### Documentation

- `docs/comprendre_tik.md` *(nouvelle section accessible "Comment Tik rédige ses hypothèses")*
- `docs/backlog.md` *(entry #2 "traduction FR" devient ADR-013)*
- `CLAUDE.md` *(section 8 — Paquet 6 livré, MAJ version + ADR list)*
