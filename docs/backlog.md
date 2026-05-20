# Backlog Tik — améliorations différées

> Ce fichier liste les pistes identifiées mais non implémentées tout de suite.
> Chaque entrée explique le contexte et le coût/bénéfice estimé.

---

## 1. Renforcer le keyword classifier (fallback Ollama)

**Date d'identification** : 2026-04-30

**Contexte** : suite à l'intégration d'Ollama (`llama3.2:3b`) comme premier
classifier de sentiment news, le `KeywordClassifier` devient un mode dégradé
utilisé uniquement quand Ollama est indisponible (cf. `news_classifier.py`).
Une suggestion d'enrichissement des listes a été analysée puis écartée pour
le bloc principal car la majorité des cas (négation, polarité contextuelle,
multi-mots) sont déjà couverts par construction par le LLM.

### 1.A — Ajouter ~8 mots-clés mono-mot non ambigus

À ajouter dans `news_classifier.py:BULLISH_KEYWORDS` :

- `reclaim`, `reclaims`, `reclaimed` *(ex : "BTC reclaims 100k")*

À ajouter dans `news_classifier.py:BEARISH_KEYWORDS` :

- `topping` *(formation de sommet)*
- `rejection` *(rejet d'un niveau de résistance)*
- `breakdown` *(cassure baissière de support)*
- `outflows` *(sorties de capitaux ETF/exchange)*
- `unloading` *(distribution agressive)*

**Coût estimé** : 5 minutes (ajout listes + 1-2 tests paramétrés).

**Bénéfice** : marginal (le fallback est rare, déclenché seulement quand
Ollama est down ou que son circuit breaker batch est ouvert). Mais le coût
est si faible que ça reste rentable.

**Mots écartés volontairement** car ambigus mono-mot :

- `inflows` (bull pour ETF, bear pour "miner inflows to exchanges")
- `distribution` (bull "wide distribution" vs bear "smart money distribution")
- `consolidation`, `expansion`, `absorption`, `volatility`, `correction`
  (tous interprétables dans les deux sens selon le contexte)
- `fear`, `risk`, `capitulation` (déjà flaggés ambigus, ne pas étendre)

**Mots multi-mots à NE PAS implémenter côté keywords** : tout ce qui demande
n-grammes (`higher low`, `losing support`, `failed breakout`, `panic selling`,
`fear spike`, `risk off`, etc.). Ces cas sont précisément le rôle d'Ollama.

### 1.B — Dataset golden pour benchmark quantitatif

L'angle vraiment utile à terme. Créer `core/tests/data/golden_titles.json`
avec ~50 titres réels annotés manuellement (BULLISH / BEARISH / NEUTRAL),
incluant :

- Les cas clairs (sanity check)
- Les cas pièges multi-mots (`Bitcoin holding support` vs `losing support`)
- Les cas avec polarité contextuelle (`fear has eased, traders resume buying`)
- Les cas techniques précis (`higher low forming`, `lower high rejected`)

Puis un test paramétré qui lance `KeywordClassifier` ET `OllamaClassifier`
sur le dataset, avec rapport comparatif (accuracy, precision, recall par
classe). C'est ce qui permettra de **mesurer** objectivement le gain
Ollama vs keywords plutôt que de débattre.

**Coût estimé** : 1-2 h (sélection + annotation manuelle + script de
benchmark). À déclencher quand Ollama aura tourné 2-3 semaines pour
collecter des cas réels intéressants depuis les logs.

**Lié au backtest existant** : le ingester loggue déjà
`method=ollama:llama3.2:3b` ou `method=keywords` dans Redis pour chaque
publication, donc le backtest pourra aussi comparer le hit rate par méthode
sur les vrais signaux Tik.

---

## 2. Traduction native française des signaux Tik (réservé ADR-014)

**Date d'identification** : 2026-05-02 (Paquet 4 Session 4, en cours d'annotation
manuelle du golden dataset)

> **MAJ 2026-05-03** : ADR-011 a finalement été utilisé pour l'anti fake-news,
> ADR-012 pour le LLM hypothesis generator (Paquet 6).
>
> **MAJ 2026-05-04** : ADR-013 a finalement été utilisé pour le fix timezone
> bug 8 (cf. `docs/adr/013-timezone-aware-datetimes.md`). **L'ADR de la
> traduction FR sera donc ADR-014** au moment de l'attaquer. Le périmètre
> s'élargit toujours depuis ADR-012 : l'hypothèse contextualisée ~150 mots
> rejoint la liste des champs à traduire.
>
> **MAJ 2026-05-19** : débat à 6 angles mené en session J-5 du trading manuel
> J+24. **Verdict : différer ADR-014 plein à post-J+30, attaquer Option E
> (glossaire enrichi) à la place si besoin pré-J+24.** Voir section
> *« Débat 6 angles 2026-05-19 »* en bas de cette entrée.

### Débat 6 angles 2026-05-19 (J-5 trading manuel)

**Faits factuels établis lors du débat** :

- **Champs textuels par signal** (lus dans `core/src/tik_core/storage/schemas.py`
  + `scoring/hypothesis_generator.py`) : `hypothesis` (~150 mots LLM, depuis
  ADR-012), `evidence[].fact` (3-4 strings courts par signal), `counter_scenarios[].mitigation`
  (2 strings), `advisory.notes` (souvent null), `advisory.llm_hypothesis_candidate`
  (~150 mots en mode shadow), `advisory.template_hypothesis` (en mode active).
  **~7-10 strings/signal**.
- **Volume runtime** : 79 signaux/6h mesurés Paquet 26 → ~316 signaux/jour →
  ~3160 traductions/j à cache froid.
- **Bug `supply ↔ demand` mesuré empiriquement** dans Paquet 4 Session 4 : le
  modèle Ollama llama3.2:3b *"inverse parfois la sémantique sur le jargon
  précis"*. Pas une spéculation — fait documenté.
- **Glossaire FR existant** (Paquet 29) : 17 entrées dans
  `dashboard/src/glossary.ts` mais ciblées sur les **termes Tik** (veracity,
  conviction, AFN), PAS sur le jargon EN de l'hypothesis (RSI, rally,
  breakdown, supply).
- **Plan stratégique post-audit fiabilité signaux** (CLAUDE.md section 8)
  classe explicitement la traduction FR dans *"Recommandations dépriorisées
  (zéro impact fiabilité signal)"*, aux côtés de EAS Build dev, ACLs Tailscale,
  Phase C UX cosmétique.

**Synthèse 6 angles** :

| # | Angle | Verdict |
|---|---|---|
| 1 | Qualité du signal (fiabilité traduction Ollama 3B) | 🟡 Risque inversion sémantique mesuré (`supply↔demand`, `rally`, `tip`, `support`, `breakdown`). Pas de dataset golden FR pour valider. |
| 2 | Effort réel vs annoncé | 🔴 Probable 5-6h pas 2-3h. Backlog sous-estimait (a) debug Ollama timeout VPS, (b) tests inversions sémantiques (impossible sans golden), (c) ADR-014 sérieux, (d) câblage SDK + dashboard + UI toggle, (e) validation runtime 24h. |
| 3 | Surface de bug et régression | 🟢 Technique faible (fallback EN si Ollama plante, aucun impact engines/DB/scoring/ADR-003). 🟡 UX moyenne (signaux EN sporadiques font douter la trader débutante, pire = traduction partielle EN+FR mélangée). |
| 4 | Maintenance long terme | 🟡 Modeste mais réelle. Suivre évolutions Ollama 3B, jargon finance évolutif (`tariff` politiquement chargé 2025-2026), pas de golden FR pour détecter régressions silencieuses. |
| 5 | Cohérence avec stratégie globale Tik | 🔴 Conflit direct avec plan post-audit fiabilité signaux (CLAUDE.md section 8). Engagement utilisatrice transposé 2026-05-14 → 2026-05-24 : *"ne jamais ajouter une feature qui dilue le focus avant le trading manuel"*. |
| 6 | Alternative low-effort qui résout 80 % du besoin | 🟢 **Option E** (glossaire enrichi ~30-45 min) couvre 80 % du besoin pour ~10 % de l'effort, zéro Ollama, zéro risque inversion. |

**Verdict final** : NON pour ADR-014 plein avant J+24. 3 raisons cumulées :

1. Risque sémantique mesuré sur signal pré-trade débutante.
2. Conflit explicite avec stratégie post-audit fiabilité signaux.
3. Alternative Option E disponible à ~10 % du coût.

### Option E — Glossaire EN→FR enrichi (alternative recommandée pré-J+24)

**Effort estimé** : ~30-45 min.

**Périmètre** :

- Ajouter ~20-30 termes trader EN→FR dans `dashboard/src/glossary.ts` (déjà
  17 entrées Tik depuis Paquet 29). Liste indicative (à raffiner au moment
  d'attaquer) :
  - Direction & momentum : `long`, `short`, `bullish`, `bearish`, `rally`,
    `dip`, `breakdown`, `breakout`, `pullback`, `consolidation`, `range-bound`
  - Technique : `RSI`, `MACD`, `EMA`, `support`, `resistance`, `crossover`,
    `divergence`, `momentum`, `oversold`, `overbought`
  - Marché : `supply`, `demand`, `volume spike`, `liquidity`, `volatility`,
    `whipsaw`, `chop`
- Composant `InfoTooltip` déjà en place (Paquet 29) avec mapping `entryKey`,
  pas de nouveau dev composant nécessaire.
- Attacher tooltips tap-ables aux termes pertinents dans la carte hypothesis
  du détail signal `dashboard/app/signal/[id].tsx`.
- Pas de bouton "switcher FR/EN" — l'EN reste affiché, le tooltip donne le
  sens FR + 1 ligne de contexte trading. Pédagogie active : la trader apprend
  en lisant ses signaux, capital cognitif long terme.

**Avantages** :

- Zéro dépendance Ollama runtime → zéro risque inversion sémantique.
- Zéro modification backend → aucun risque sur les engines / pipeline scoring /
  cross-validation / ADR-003.
- Cohérent avec préférence utilisatrice in-app (memory `in_app_preference.md`).
- Survit à la refonte UX finale (glossaire = couche données, pas couche
  visuelle).
- Effort divisé par 10 vs ADR-014 plein.

**Limites assumées** :

1. Couvre uniquement les termes du glossaire — un mot EN absent du dict reste
   en anglais sans tooltip. À élargir empiriquement selon retour terrain.
2. Tooltips tap-ables : friction +1 tap vs traduction inline native. Compromis
   accepté pour zéro risque sémantique.
3. Détection auto des termes dans le texte hypothesis = parsing simple
   regex/split. Pas de NLP. Suffisant pour le besoin.
4. Pas de pédagogie sur l'hypothesis 6 sections en entier — uniquement
   vocabulaire trader. Pour comprendre la structure d'une hypothesis, la
   trader utilisera la carte Glossaire de l'onglet Config (déjà livrée Paquet
   29).

### Comment demander à Claude future

- **« Attaque Option E glossaire EN→FR enrichi »** → ~30-45 min, périmètre
  défini ci-dessus. Cohérent stratégie post-audit fiabilité signaux.
- **« Attaque ADR-014 plein traduction FR via Ollama »** → ~5-6h réaliste,
  voir sections Options A/B/C ci-dessous + ADR-014 à créer. Sort consciemment
  du focus fiabilité signaux. À privilégier post-J+30 quand runtime trading
  stabilisé.

---

### Historique pré-2026-05-19 (Options A/B/C ADR-014 plein)

**Contexte** : tous les champs textuels produits par Tik aujourd'hui sont en
anglais (cohérent : les sources Google News, CryptoCompare, GDELT, Reddit
filtrent toutes `lang=EN`). Concrètement :

- `evidence[].fact` (preuves)
- `counter_scenarios[].description` et `.mitigation` (contre-scénarios)
- `advisory[].message` (avis additionnels)

L'utilisatrice principale du projet (lectrice francophone, débutante en
trading) doit aujourd'hui lire ces signaux en anglais via curl ou via le
SDK. Le dashboard Expo (Paquet 3, livré 2026-05-03) a confirmé le besoin
en pratique. Depuis ADR-012 (Paquet 6, LLM hypothesis generator), un
nouveau champ textuel ~150 mots s'ajoute à la liste : `Signal.hypothesis`
contextualisée + son candidate `Signal.advisory.llm_hypothesis_candidate`
en mode shadow. Pour les bots clients (Zeta, Totem), c'est sans importance
— ils consomment du JSON structuré pas du texte humain.

### Options évaluées

**Option A — Param `?lang=fr` au niveau API**
Ajouter un paramètre query optionnel à `/api/v1/signals/...` qui passe les
champs textuels par Ollama avant de renvoyer le JSON. Cache Redis avec TTL
aligné sur le TTL du signal pour ne pas re-traduire à chaque requête.

| Pour | Contre |
|---|---|
| Centralisé, le SDK et le dashboard en bénéficient sans code | Latence (~1 sec par champ × N champs si cache miss) |
| Cohérent avec le pattern strategy ADR-001/006 | Charge Ollama supplémentaire |
| Effort modéré (~2-3 h) | Dépendance externe Mac hôte (cf. ADR-006) |

**Option B — Module dédié `tik_core/i18n/translator.py`**
Module réutilisable consommé par l'API, le SDK et plus tard le dashboard.
Même effort que Option A mais plus modulaire.

**Option C — Bilingue à la source (en DB)**
Les engines (`swing_engine.py`, `flash_engine.py`) génèrent FR + EN au moment
de la création du signal. Stocké en DB.

| Pour | Contre |
|---|---|
| Zéro latence runtime | Refactor lourd de tous les engines |
| Fonctionne même si Ollama est down | Doublement de l'espace en DB |
| | Si on ajoute une langue plus tard, re-refactor complet |

### Verdict envisagé

**Option A** quand on l'attaquera. Architecture propre, faible coupling,
bénéfices SDK + dashboard, et le pattern de cache Redis avec TTL aligné sur
le signal limite proprement la charge Ollama.

**Coût estimé** : ~2-3 h pour Option A :
- Module `tik_core/i18n/translator.py` (Strategy : `OllamaTranslator` +
  `NoopTranslator` pour fallback EN), ~50 lignes
- Param `lang` ajouté à `/api/v1/signals/latest`, `/signals/{id}`,
  `/signals/search` (3 endpoints)
- Cache Redis `tik.translation.{signal_id}.{lang}`, TTL = TTL signal
- Tests pytest (~10 tests : cache hit/miss, fallback Ollama down, lang
  inconnue → 400, EN par défaut inchangé)
- ADR-014 documente le choix Option A vs B/C *(ADR-011 = anti fake-news 2026-05-03, ADR-012 = LLM hypothesis 2026-05-03, ADR-013 = timezone fix 2026-05-04)*

**Bénéfice** :
- L'utilisatrice lit ses signaux en FR sans avoir besoin d'apprendre le
  jargon trader anglais
- Le futur dashboard Expo aura juste à passer `lang=fr` selon la locale
  device
- Pas de blocage pour les bots Zeta/Totem (ils ignorent le param `lang`)

### Quand l'attaquer

Pas avant la fin de la Session 4 (calibration en cours). Idéalement :

- **Si la calibration de Session 4 fait remonter des ajustements
  structurants** sur `SOURCE_SCORES` ou les engines → enchaîner Session 5
  sur ces ajustements d'abord, puis Session 6 sur la traduction.
- **Sinon** → Session 5 dédiée à la traduction native FR (avec ADR-014).

**Risque rappelé** : Garde-fou 1 (mode shadow 3 mois) **strictement applicable**
à ce nouveau code de traduction (pas de risque trading mais le contrat ADR-003
de non-bypass V01-V15 reste **inchangé** — la traduction ne touche aucune logique
décisionnelle).

---

## 3. Plan préparation trading manuel J+10 (2026-05-04 → 2026-05-14)

**Date d'identification** : 2026-05-04

**Contexte** : l'utilisatrice principale a annoncé son intention de **trader
manuellement avec Tik dans 10 jours**. Ça change le statut de Tik : il passe
d'outil d'observation (mode shadow vs Zeta) à outil d'aide à la décision
réelle avec son capital. Le Garde-fou 1 (Tik shadow 3 mois) **ne s'applique
pas** au trading manuel humain — c'est son jugement qui filtre, pas un guard
pipeline V01-V15. La séquence ci-dessous priorise donc **calibration empirique
de la confiance + contexte rapide sans risque LLM + discipline opérationnelle**
plutôt que des features narratives risquées (cf. entry n°4 ci-dessous, Phase 2
LLM enrichi reportée post-J+30).

### Séquence proposée (4 features + calibration)

| Jour | Feature | Effort | Valeur trading |
|---|---|---|---|
| **J+1-2** | ✅ **Phase A.1 — Carte "Top headlines aujourd'hui"** dashboard (livrée 2026-05-05). Réutilise les news déjà ingérées (Google News BTC/GOLD + CryptoCompare + Reddit). 5-10 titres affichés bruts avec source, sentiment et heure. Tri par crédibilité × récence. | ~½ session ✅ | Contexte rapide brut. Tu vois les news qui motivent les sentiments avant de regarder les signaux. **Zéro risque LLM hallucination** — c'est de la donnée brute citant ses sources. Pattern OSINT pro classique (Recorded Future, Bellingcat). |
| | ✅ **Phase 1.1 — Lacunes OSINT pro essentielles A+G+C** (livrée 2026-05-05). Persistance DB titres + flag anti fake-news visible + cache Redis sentiment 7j. | ~6-7h ✅ | Audit historique + sentiment stable + transparence anti fake-news. |
| **J+3-4** | ✅ **Carte Home "Hit rate live"** (livrée 2026-05-04 soir, Phase A.2 + A.2-bis). Pourcentage de signaux Tik corrects sur les 30 derniers jours par horizon × asset, hit rate par tranche de veracity. | ~1 session ✅ | Calibre ta confiance. Insight clé : 67% sur veracity 0.95+ vs 24% global → filtre veracity ≥ 0.90 recommandé. |
| **J+5-6** | ✅ **Lacune B Phase B1 — Calendrier macro/géopolitique** (livrée 2026-05-06, ADR-017). FRED Releases API + FOMC dates statiques + carte Home compact + route détail. | ~7-8h ✅ | Outil de risk management : éviter d'entrer en swing 4h avant un FOMC. Pendant la phase d'observation sans edge démontré, c'est la discipline simple qui réduit le drawdown. |
| **J+7-8** | ✅ **Vue "Track record signal"** dans le détail signal (livrée 2026-05-05, Paquet 12 puis refactoré granularité adaptée par horizon Paquet 17 2026-05-06). Pour chaque signal historique, affiche le delta de prix après 1h/6h/24h/5j (swing) ou paliers adaptés (flash/macro). Badges visuels ✓ correct / ✗ raté / ⚠ neutre. | ~1 session ✅ | Tu apprends à reconnaître les types de signaux qui marchent vs ceux qui ratent. Ton oeil se forme avant le live. |
| **J+8-9** | ✅ **Workflow Watchlist Session 1** (livré 2026-05-05, Paquet 13) — bouton ★ Suivre sur détail signal + onglet Watchlist dédié + persistance AsyncStorage cap 200. **Session 2 LIVRÉE 2026-05-19 (Paquet 28)** : auto-resolution outcome via track record, hit rate perso vs Tik global avec disclaimer biais de sélection < 20, bouton override Alert.alert natif + POST /feedback systématique nourrissant la recalibration source credibility ADR-011. | ~1 session ✅ | Discipline opérationnelle + calibration empirique. Tu sais quel signal a déclenché quel trade. Indispensable pour tirer des leçons après. |
| **J+9-10** | **Run de validation finale + calibration mentale** — usage Tik en mode "préparation trading" pendant 2 jours sans prendre de trade pour de vrai. Identification des manques. | 0 dev | Calibration mentale avant le live. Identification des features manquantes pour itérer post-J+10. |

### Décisions structurantes prises

- **Pas de Phase 2 LLM enrichi avant J+10** (cf. entry n°4) : l'argument décisif d'ADR-012 (*"hypothèse hallucinée serait pire que template"*) s'applique encore plus fort en trading live. Le LLM 3B a des limites documentées (markdown résiduel, sortie parfois trop courte, hallucinations potentielles sur input long) et 10 jours ne suffisent pas pour valider en mode shadow strict.
- **Aucune modification des engines / pipeline scoring / cross-validation** : les 4 features sont purement dashboard + endpoints API en lecture. Garde-fou 1 préservé. ADR-003 inchangé. Le pattern multi-overlay ADR-004 inchangé. Aucun risque de régression sur le calcul des signaux.
- **Réutilisation maximale de l'infra existante** : `backtest.py` (CLI déjà livré Paquet 1.x) devient un module importable, klines Binance + Yahoo Finance déjà câblés, AsyncStorage pattern déjà déployé pour Alerts. Faible effort = faible risque.
- **Persistance Watchlist AsyncStorage et non DB Postgres** : la watchlist est un workflow utilisateur **personnel** (pas une donnée Tik partagée). AsyncStorage est suffisant et cohérent avec Alerts. Si à terme on voulait sync multi-device, on migrerait vers un endpoint API + DB.

### Risques opérationnels rappelés

- Garde-fou 1 (mode shadow Tik vs Zeta 3 mois) **strictement applicable** — Tik continue de **ne jamais passer d'ordre Zeta**. Le trading manuel est exécuté par l'utilisatrice elle-même via son broker habituel.
- Garde-fou 2 (budget test 5%) **rappelé fortement** au moment du démarrage trading manuel J+10. Recommandation : commencer avec un capital **inférieur à 5%** du capital total et augmenter progressivement après 2-3 semaines de live profitable.
- ADR-003 (pas de bypass V01-V15) **inchangé** — Tik ne crée jamais d'ordre. Ces 4 features sont en lecture seule côté Tik.
- Paranoïa contrôlée maintenue — chaque signal continue de livrer hypothèse + contre-scénarios + evidence + triggers + cross-validation anti fake-news.

---

## 4. Phase 2 — Enrichissement contextuel hypothèse LLM (réservé ADR-015, post-J+30)

**Date d'identification** : 2026-05-04

**Contexte** : retour utilisatrice constaté lors de la session de bascule LLM
shadow runtime (2026-05-04 après-midi) — *"L'hypothèse contextuelle je la
voyais autrement, un vrai contexte qui ne fait pas que la synthèse des autres
cartes mais aussi une synthèse de contexte de la situation d'un point de vue
économique, politique, etc."*. Aujourd'hui le LLM ne reçoit que les données
internes de la `decision` Tik (direction + confidence + veracity + evidence +
triggers + counter-scenarios + statut anti fake-news). Donc il synthétise ce
qu'on lui donne — **par construction**, c'est un résumé des autres cartes du
détail signal. C'est le choix d'ADR-012 décision 5 (*"Use ONLY the data
provided"*) pour éviter les hallucinations.

**Reporté volontairement post-J+30** car :

1. **Mode shadow strict impossible en 10 jours** — ADR-012 dit explicitement *"valider la qualité de la sortie LLM sur 5-10 cycles avant bascule active"*. Phase 2 augmente le risque hallucination en élargissant le contexte du prompt. 1 mois shadow + dataset golden d'évaluation (~30 signaux annotés sur "narrative pertinente vs hallucinée") sont nécessaires avant bascule. Pas faisable en 10j.
2. **Llama 3.2:3b a des limites documentées** — sortie parfois trop courte (cycles à 76 mots vs cible 120-180, observé 2026-05-04 17:11), markdown résiduel, hallucinations potentielles sur input long.
3. **Doctrine OSINT pro** — plateformes OSINT classiques (Recorded Future, Maltego, Palantir Foundry) fournissent des **données structurées** et laissent l'humain interpréter. Les nouvelles plateformes émergentes qui intègrent du LLM (Anduril Lattice, Perplexity Sonar) le font avec très haute exigence sur la traçabilité des sources. La carte Top headlines (entry n°3 Phase 1) répond déjà au besoin contextuel **sans risque LLM**.

### Pistes évaluées

| Piste | Pour | Contre rédhibitoire |
|---|---|---|
| **A. Top 5-10 headlines du jour injectés dans le prompt** (réutilise les ingesters Google News + CryptoCompare + Reddit + GDELT déjà en place) | Données déjà collectées, zéro coût additionnel d'ingestion. Pattern cohérent avec multi-overlay ADR-004. | Ne reste plus que du sentiment headlines, pas vraiment "macro". Risque hallucination LLM sur input long. |
| B. Calendrier économique (FOMC, NFP, CPI, GDP, élections) — nouveau ingester FRED événements / investing.com | Vrai contexte macro. Sources gratuites. | Nouveau ingester à coder (~1 session). Risque hallucination LLM identique. |
| C. LLM avec accès web (Anthropic Claude API + web search, ou Perplexity Sonar) | Contexte vraiment large, sans nouvel ingester. Traçabilité sources si bien implémenté. | Sort du scope "Ollama local gratuit". Coût API. Latence. Dépendance externe Anthropic/Perplexity. |
| D. Snapshot quotidien rédigé par un autre LLM call ("Quels sont les 3 enjeux dominants du jour pour BTC/Or ?") | Un seul LLM call/jour distillé en 200 mots passés au prompt signal. Reste local. | Risque hallucination amplifié si data brute pas disponible. Cumul 2 niveaux LLM = 2× risque. |

### Verdict envisagé

**Piste A en mode shadow strict 1 mois** quand on l'attaquera, avec
dataset golden d'évaluation (~30 signaux annotés humain-ressenti
"narrative pertinente vs hallucinée vs trop générique"). Bascule active
**uniquement si** le hit rate "narrative juge humain → score acceptable"
est > 80% sur le golden. Sinon revert à template.

**Pré-requis** : avoir validé **empiriquement** au moins 2-3 semaines de
trading manuel sur la carte Top headlines (entry n°3 Phase 1) pour savoir
si le contexte brut suffit OU s'il manque vraiment une couche narrative
LLM. Sinon on code une feature dont on ne sait pas encore si on en a besoin.

### Quand l'attaquer

**Post-J+30** (après 2-3 semaines de trading manuel avec carte Top
headlines), uniquement si le retour utilisatrice confirme un manque
contextuel narratif que la carte brute ne couvre pas.

**Coût estimé** : ~1-2 sessions de dev + 1 mois shadow + ~1 session de
mesure golden. Soit ~6 semaines calendaires depuis le démarrage.

**Risque rappelé** : Garde-fou 1 (mode shadow Tik vs Zeta 3 mois)
**strictement applicable**. ADR-003 (pas de bypass V01-V15) **inchangé**.
Mode shadow LLM strict obligatoire avant bascule active (ne pas répéter
l'erreur de raisonner *"bah on verra ben"* — l'hypothèse hallucinée serait
pire que template, cf. ADR-012 décision 3).

---

## 5. Vision Tik « conseiller financier macro/géopolitique » + refonte dashboard (post-J+14)

**Date d'identification** : 2026-05-05 (en cours de Phase A.2-bis)

**Contexte** : l'utilisatrice principale a clarifié sa vision long terme
de Tik — *« je veux que tik soit également le meilleur conseiller financier,
tous les secteurs d'activités BTC et gold qui sont liés à la geopolitique »*.
La vision domain-agnostic est déjà documentée dans `CLAUDE.md` section 1
(*« Périmètre futur : domain-agnostic — sport betting, politique, météo-finance,
tout système décisionnel ayant besoin d'OSINT + scoring »*) et techniquement
le pipeline est sur cette voie (GDELT géopolitique, FRED DXY, CFTC COT, pattern
multi-overlay ADR-004 extensible). Mais aujourd'hui Tik est focalisé
**trading direction (long/short/neutral)** et le dashboard est devenu
**dense (9-10 cartes Home empilées)**. Pour passer de « MVP trading » à
« plateforme de conseil financier macro », il manque 3 axes structurants
+ une refonte UX dashboard.

### A — Élargissement scope « conseiller financier macro »

3 chantiers (chacun ~1-2 sessions, à étaler sur 4-6 semaines post-J+14) :

1. ✅ **Calendrier événementiel macro** (FOMC, NFP, CPI, GDP, élections,
   sommets, sanctions) → ✅ **Phase B1 livrée 2026-05-06** (ADR-017) +
   ✅ **Phase B2 livrée 2026-05-16** (ADR-020 — banques centrales
   internationales ECB / BoJ / BoE, 36 events 2026-2027 ajoutés, nouvel
   ingester `MacroStaticIngester` séparé, fix bug latent FOMC sans clé
   FRED). **Phase B3 (élections G7) reportée post-J+30** selon retour
   utilisatrice sur l'utilité pratique des Phases B1+B2.

2. **Scope élargi des entities** — ajouter :
   - `US_DEBT` (dette US, watch sur crisis liquidity)
   - `OIL` (Brent + WTI, géopolitique Moyen-Orient)
   - `EUR_USD` (paire FX majeure, watch BCE/Fed)
   - `EM_RISK` (marchés émergents, risk-off)
   - `GEOPOLITICAL_RISK` (entity composite agrégeant GDELT + sanctions + élections)

   Chaque nouvelle entity = ses sources (FRED, CFTC pour la plupart, ICE pour Brent),
   son scoring multi-overlay. **L'archi le supporte sans refacto** (ADR-004).
   Coût estimé : ~1 session par entity (~5h).

3. **Format de signaux narratifs élargi** (au-delà du long/short/neutral) — pour
   coller au format « conseiller » :
   - *« rotation actions → cash si VIX > 30 »* (signal conditionnel)
   - *« scénario or +5 % si tensions Taiwan persistent »* (signal probabiliste)
   - *« risk-off généralisé, 4 sources alignées »* (signal qualitatif)

   C'est la **Phase 2 ADR-015** déjà tracée entry n°4 (post-J+30 après calibration LLM).

### B — Refonte dashboard (simplification visuelle + accès aux outils)

**Constat 2026-05-05** : la Home empile aujourd'hui 9-10 cartes (État du core,
Veracity, Stats LLM, Hit rate, Hit rate par veracity, Top headlines, Activité 24h,
Dernier signal par actif, Tendance veracity, Roadmap Paquet 3, Version box).
**Trop dense pour l'utilisatrice principale** qui n'a jamais codé.

4 leviers évalués pour/contre/verdict :

| Levier | Pour | Contre | Score |
|---|---|---|---|
| **A. Hiérarchiser** : "Avant trade" essentiel vs "Diagnostic" collapsed par défaut vs "Détail" via tap | Découverte progressive, scroll réduit | Effort moyen, risque de masquer des infos utiles | 7/10 |
| **B. Tabs internes Home** : `Marché` / `Système` / `Calibration` | Réduit la longueur de scroll, structure claire | 2 clics pour accéder à un info | 7/10 |
| **C. Mode contextuel** : avant J+14 = focus calibration, après = focus marché live | Adapté à l'usage réel | Complexité runtime, risque de bugs | 5/10 |
| **D. Élaguer obsolète** (Roadmap Paquet 3 livrée, Version box → footer App) | Quick win, ~30 min | Cosmétique, pas structurel | 6/10 |

**Verdict envisagé** : combiner **B (tabs) + D (élagage)**. Tabs `Marché / Calibration / Système` :
- **Marché** : Top headlines (en haut) + Veracity globale + Macro events + Dernier signal par actif + Activité 24h
- **Calibration** : Hit rate live + Hit rate par veracity + Tendance veracity + Stats LLM
- **Système** : État du core + Bouton refresh + Version box + lien vers Config/Bots/Alerts

L'écran d'accueil devient **« Marché »** par défaut (= ce dont tu as besoin avant un trade).
**Calibration** devient une vue d'audit séparée qu'on consulte en début de
journée. **Système** disparaît dans un menu secondaire.

### ✅ LIVRÉ Paquet 24 (2026-05-16)

Levier B (tabs) + Levier D (élagage Roadmap Paquet 3 + Version box déplacée
dans Système) livrés. 1 fichier modifié (`dashboard/app/(tabs)/index.tsx`,
422 → ~430 lignes). Bump dashboard 0.5.6 → 0.5.7. Aucune nouvelle
dépendance. Validation TypeScript runtime à confirmer côté HP/Mac (env
serveur Claude Code n'a pas Node).

Leviers A (élargissement scope entities) et C (mode contextuel) restent
backlog, à reconsidérer post-J+30 selon retour usage.

### Pourquoi attendre post-J+14 — décision paranoïa contrôlée

1. **Tu as appris** le dashboard actuel pendant 4 jours (du 1er au 5 mai). Le
   re-shuffler avant J+14 = re-apprentissage forcé + risque de bugs visuels
   à un moment où ta concentration doit être sur le marché.
2. **Une refonte UX honnête** (3-4h cumulées) mérite : audit toutes pages +
   maquettes + livraison incrémentale (1 page à la fois, pas tout d'un coup).
   Minimum 2-3 sessions, jamais à la va-vite avant un trade.
3. **L'élargissement scope** (Levier A) demande de nouveaux ingesters
   (ICE Brent, FRED rates, etc.) qui ne s'écrivent pas en 1h.

### Quick win possible avant J+14 (optionnel)

**Just élaguer la Roadmap Paquet 3** (~30 min, 1 fichier modifié `index.tsx`)
si l'utilisatrice trouve que ça encombre. Quick win pur, zéro risque de
régression structurelle.

### Quand l'attaquer

**Post-J+14** (après les premières semaines de trading manuel). L'ordre proposé :
1. Élagage obsolète (~30 min) — n'importe quand
2. Tabs internes Home (~2-3h) — semaine du 15-22 mai
3. Élargissement scope entities (~5h × 4 entities) — sur 2-3 semaines
4. Format signaux narratifs (Phase 2 ADR-015) — post-J+30, après 2-3 semaines
   de trading manuel et calibration LLM hypothesis

**Coût estimé total** : ~3-4 semaines calendaires post-J+14.

**Risque rappelé** : Garde-fou 1 inchangé (Tik shadow vs Zeta), ADR-003
inchangé (Tik ne crée jamais d'ordre), ADR-004 (multi-overlay) inchangé.
Tous les nouveaux scopes/formats = ajouts non destructifs.

---

## 6. Refactor architectural Tik vers OSINT pur (ADR-018) ✅ LIVRÉ 2026-05-07

**Date d'identification** : 2026-05-07
**Statut** : ✅ LIVRÉ le jour même de l'identification (Sessions 1+2+3 cumulées,
891 tests verts post-livraison, 0 régression)

**Origine** : audit méthodique 2026-05-06/07 sous consigne *"doute constant
et méthodique, sans complaisance"*. L'audit a révélé que Tik n'est pas la
plateforme OSINT pure que CLAUDE.md laisse entendre — c'est un système
**hybride** où l'analyse technique (RSI/MACD/EMA dans `swing_engine.py` et
`flash_engine.py`) est le **cerveau de décision principal**, et les
overlays OSINT ne modulent que la veracity.

### Les 4 constats factuels

1. **Duplication conceptuelle** avec Zeta (qui fait l'analyse technique
   pour son moteur d'exécution, ~5211 lignes calibrées) et avec MT5 (qui
   affiche RSI/MACD/EMA en natif sur l'écran de la trader manuelle)
2. **Sémantique trompeuse de la `confidence`** : double signification
   selon `direction == "neutral"` ou pas (cf. audit Paquet 17 P5)
3. **Tik n'excelle pas en analyse technique** : seuils binaires, 14 magic
   numbers non calibrés, hit rate global 22 % vs Random 33 %
4. **Tik a un avantage différencié en OSINT** : Modified Z-score
   anti fake-news (ADR-011), LLM hypothesis local (ADR-012),
   recalibration daily des sources, multi-overlay cross-validé (ADR-004)

### Verdict

Refactor pur OSINT recommandé pour atteindre l'excellence dans une
discipline (OSINT crypto/finance cross-validé local-first). Confiance
70-75 % (audit méthodique du 2026-05-07). 4 hypothèses à vérifier avant
exécution (cf. ADR-018).

### Conditions d'activation

- Trading manuel J+14 démarré et stable (≥ 1 semaine post-2026-05-14)
- 4 hypothèses ADR-018 vérifiées (stratégie B2B, hit rate Zeta,
  proportion signaux veracity ≥ 0.95, fréquence trading)
- Hit rate Tik hybride mesuré empiriquement avec ≥ 30 trades manuels
  réels

### Effort estimé

~9h dev focus sur 3 sessions (refonte core + dashboard + doc/tests),
+ 1 semaine de validation runtime mode shadow avant bascule.

Touche **~500-700 lignes core + ~200-300 lignes dashboard** = 4-7 % du
code total Tik (~14 000 lignes au total). **Pas un "refactor majeur"**
comme initialement présenté lors des sessions précédentes.

### Ce qui change pour la trader manuelle

Avant : `BTC swing long, conf 55%, veracity 92%`
Après : `BTC swing long, osint_conviction 0.62, veracity 0.92`

`osint_conviction` = magnitude du `combined_bias` OSINT cross-validé.
Sémantique uniforme : haute = forte conviction directionnelle, basse =
marché OSINT équilibré. Plus de double sens.

Direction (`long`/`short`/`neutral`) dérivée du `combined_bias` avec
seuil ±0.30 (à calibrer empiriquement). Si on veut une direction
technique complémentaire pour décider d'un trade, on regarde MT5 (qui a
RSI/MACD/EMA en natif).

### Priorité

**HAUTE long terme**, **conditionnelle court terme** (à activer post-J+14
selon les 4 hypothèses). Le refactor n'est pas urgent, mais il est
**stratégiquement nécessaire** pour faire de Tik une plateforme
*"surpuissante, fiable, scores très haut"* (objectif énoncé par
l'utilisatrice 2026-05-06).

### Références

- ADR-018 (`docs/adr/018-tik-pure-osint-refactor.md`) — décision et plan
  de migration détaillé
- Audit Paquet 17 P5 (CLAUDE.md) — révélation des 14 magic numbers
- Sessions Claude 2026-05-06 et 2026-05-07 — discussion architecturale
  approfondie et reconnaissance des incohérences

### Risque rappelé

Garde-fou 1 (Tik shadow vs Zeta) **inchangé**. ADR-003 (pas de bypass
V01-V15) **inchangé**. ADR-004 (multi-overlay) **renforcé** (devient le
cerveau principal). Le refactor est **interne à Tik**, n'affecte ni
l'intégration Zeta ni la sécurité du capital.

---

## 7. Calibrations & validations à faire post Paquets 19-22 (identifiées 2026-05-16)

**Date d'identification** : 2026-05-16 (J+2 trading manuel, fin de
session de livraison Paquets 21+22)

**Contexte** : la session du 2026-05-16 a livré 4 commits sur main
(Paquet 19 doc / fix GDELT timing / P6 anomalies / Option B SDK alias)
qui introduisent **3 nouveaux paramètres calibrés au pifomètre raisonné**
+ **3 actions runtime à effectuer côté Mac/HP** que l'utilisatrice ne
peut pas faire depuis cette session Claude (l'environnement serveur
Linux n'a pas Docker / pas de pytest local / pas de Tik core qui tourne).

Cette entrée trace **toutes les calibrations et validations encore à
faire** pour ne rien oublier. Une partie est conditionnée à des
événements futurs (J+30, câblage Zeta = 3 mois shadow), une autre est
actionnable dès la prochaine session sur le Mac/HP.

### A. Actions runtime à faire dès la prochaine session Mac/HP (~30 min cumulés)

#### A.1 — Re-run du backtest P2 GDELT (commit `a7ef93d`)

Le fix `GDELT_MIN_BACKOFF_S = 6` permet enfin au backtest 12m de
récupérer les vraies mesures GDELT GOLD (vs 0 points avant le fix).
Commande à lancer (Tik core doit tourner) :

```bash
docker compose -f core/docker-compose.yml exec tik-core \
  python -m tik_core.scripts.backtest_numeric_sources \
  --days-back 365 \
  --output-json core/data/numeric_calibration/numeric_calibration_report.json \
  --output-md core/data/numeric_calibration/numeric_calibration_report.md \
  --fred-api-key TON_API_KEY_FRED
```

Une fois le re-run effectué, mettre à jour CLAUDE.md Paquet 19 section
P2 avec les nouveaux chiffres GDELT GOLD (`n_history_fetched.gdelt_tone`
devrait passer de 0 à ~365 points). Décision GDELT BTC peut alors être
tranchée (P3 plan stratégique).

#### A.2 — Validation pytest suite complète

Côté Mac/HP, lancer la suite complète pour confirmer 988 verts (954 base
+ 31 anomaly_detector + 3 backoff floor) :

```bash
docker compose -f core/docker-compose.yml exec tik-core pytest -v
```

Si régression inattendue, m'envoyer le log d'erreur dans la prochaine
session Claude pour diagnostic.

#### A.3 — Restart ingesters + observation runtime P6

Pour que la détection anomalies P6 soit active :

```bash
docker compose -f core/docker-compose.yml restart ingesters
```

Puis observer pendant 1-2 cycles (~30 min) que :
- Les payloads Redis contiennent bien la nouvelle clé `anomaly` (ex.
  `redis-cli GET tik.sentiment.reddit.btc | jq .anomaly`)
- Aucun log `*.anomaly_detected` ne flag tous les cycles (= seuils
  trop bas, faux positifs)
- La baseline CryptoCompare se construit progressivement (key
  `tik.anomaly.baseline.cryptocompare.btc` apparaît dans Redis)

### B. Calibrations empiriques à faire post-J+30 (entre 2026-05-31 et 2026-06-15)

#### B.1 — Recalibration seuils P6 anomalies (Paquet 21)

Les seuils suivants sont calibrés au pifomètre raisonné dans
`anomaly_detector.py` :

| Constante | Valeur | À recalibrer ? |
|---|---|---|
| `BRIGADING_THRESHOLD_HIGH` | 1.0 | Oui — observer 30j de ratios réels Reddit pour calibrer le 99e percentile |
| `BRIGADING_THRESHOLD_MEDIUM` | 0.5 | Idem (75e percentile) |
| `BRIGADING_MIN_POSTS` | 3 | Probablement OK |
| `PUBLISHER_DOMINANCE_THRESHOLD_HIGH` | 0.70 | Oui — observer 30j Google News pour calibrer (Yahoo Finance déjà à 40% sur certains cycles) |
| `PUBLISHER_DOMINANCE_THRESHOLD_MEDIUM` | 0.50 | Idem |
| `VOLUME_SPIKE_THRESHOLD_HIGH` | 5.0× | Oui — un vrai event macro peut générer un pic légitime |
| `VOLUME_SPIKE_THRESHOLD_MEDIUM` | 3.0× | Idem |

Méthodologie suggérée : exporter 30 jours de logs `*.anomaly_detected`
et `*.published` (avec `anomaly_score`), calculer les distributions
réelles, ajuster les seuils sur les 90e/99e percentiles.

#### B.2 — Validation/recalibration `OSINT_MIN_STRENGTH` (Paquet 22)

Constante du pattern Zeta dans `docs/integration_zeta.md` :
`OSINT_MIN_STRENGTH = 0.6`. Calibrée au pifomètre. Sera validée
empiriquement quand Zeta sera câblé en mode shadow (Garde-fou 1 = 3
mois minimum à compter de J+14, donc validation ~mi-août 2026).

Méthodologie : compter sur 30 jours de signaux Tik la proportion de
cycles où `osint_conviction × veracity > 0.6`. Si > 80% des cycles
passent ce seuil → seuil trop bas (Tik module trop souvent). Si <
10% → seuil trop haut (Tik n'apporte presque rien). Cible idéale
~30-50% des cycles.

#### B.3 — Re-mesure DXY/COT GOLD post période bear (amendement ADR-018 P2)

Décision désactivation `gold_dxy_cot_overlays_enabled = False` faite
le 2026-05-07 sur backtest 12m bullish. Critère de réactivation
explicite (cf. ADR-018 amendement P2) :

> Sur une période diversifiée (incluant idéalement un drawdown gold
> ≥ 5 %) :
> - Si IC Spearman DXY @ 120h **redevient négatif** ET cas extrêmes
>   hit rate ≥ 50 % → réactiver `TIK_GOLD_DXY_COT_OVERLAYS_ENABLED=true`
> - Sinon : maintenir désactivés et planifier P4 (refonte mappings
>   sources)

### C. Conditionnel — Câblage Zeta (post 3 mois shadow Tik vs Zeta)

#### C.1 — Adoption pattern overlay Paquet 22

Quand le Garde-fou 1 (mode shadow Tik vs Zeta 3 mois) sera levé (~mi-
août 2026 si trading manuel J+14 = 2026-05-14), le pattern
`docs/integration_zeta.md` Paquet 22 doit être adopté dans
`cranial_bot/turbo_v2.py` :
- Utiliser `tik.osint_conviction` (alias SDK 0.6.0+) au lieu de
  `tik.confidence`
- Implémenter le seuil `OSINT_MIN_STRENGTH = 0.6` avant modulation
- Utiliser le pattern `adjustment` proportionnel au-dessus du seuil

NE PAS revenir au pattern linéaire 2026-04-30 sans relire ADR-018 +
CLAUDE.md Paquet 22.

### Résumé : « Que faire concrètement avec ces calibrations ? »

| Quand | Action | Effort |
|---|---|---|
| Prochaine session Mac/HP | A.1 re-run backtest GDELT + A.2 pytest validation + A.3 restart ingesters + A.4 validation dates BC 2026-2027 (Phase B2) | ~45 min |
| Post-J+30 (mi-juin 2026) | B.1 recalibration seuils P6 selon distributions réelles + B.4 importance BoE selon vol BTC/GOLD observée | ~1h analyse |
| Post-période bear gold | B.3 re-mesure DXY/COT, possible réactivation overlays | ~30 min mesure |
| Post-câblage Zeta shadow (mi-août 2026) | B.2 validation `OSINT_MIN_STRENGTH` + C.1 adoption pattern | Conditionnel |

#### A.4 — Validation dates ECB/BoJ/BoE 2026-2027 (Phase B2 livrée 2026-05-16)

Les 36 dates ECB / BoJ / BoE hardcodées dans
`core/src/tik_core/aggregator/macro_calendar_data.py` (Paquet 23) sont
basées sur les patterns publiés mais doivent être **vérifiées contre les
sources officielles** avant production runtime :

- ECB : https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
- BoJ : https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm
- BoE : https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates

Si une date est incorrecte, éditer `macro_calendar_data.py` et restart
le `MacroStaticIngester` (idempotent — UNIQUE constraint DB protège
contre les doublons).

#### B.4 — Importance BoE (Phase B2 — calibration empirique)

L'importance BoE MPC est posée MEDIUM "au pifomètre raisonné"
(justification : GBP moins influente sur DXY que EUR/USD). À recalibrer
empiriquement post-J+30 sur 4-5 meetings BoE observés : si la vol
BTC/GOLD post-event est comparable ou supérieure à celle post-CPI US,
remonter à HIGH.

Méthodologie suggérée : exporter les signaux Tik et les prix BTC/GOLD
dans les ±4 h autour de chaque meeting BoE 2026, calculer la vol moyenne
réalisée vs vol moyenne sur un échantillon contrôle (jours sans event).
Si ratio ≥ 1.5 sur ≥ 3 meetings observés, bumper BoE de MEDIUM à HIGH.

### Risque rappelé

Garde-fou 1 inchangé. Garde-fou 2-bis inchangé. ADR-003 inchangé.
ADR-004 inchangé. ADR-011 inchangé. ADR-018 renforcé (calibrations
listées ici amélioreront empiriquement les choix pifomètre actuels).

## 8. Limite structurelle `detect_volume_spike` sur CryptoCompare (identifiée 2026-05-18, post-J+14)

Découverte lors de l'audit Issue #4 baseline WRONGTYPE (Paquet 26 →
résolution post-rebuild 2026-05-17). La clé `tik.anomaly.baseline.cryptocompare.btc`
est désormais propre (string, 20 points, mature, 0 erreur runtime sur 24h),
mais une limite structurelle a été mise en évidence.

### Constat factuel

L'API CryptoCompare `/data/v2/news/` retourne **~50 articles par défaut**
(le code `cryptocompare_ingester.py:_fetch` ne passe pas de paramètre
`lTs` ou `feeds` qui limiterait/étendrait la pagination). La baseline
mesurée en Redis est `[50, 50, 50, ..., 50]` — 20 entrées identiques.

Conséquence sur `detect_volume_spike` (Paquet 21 P6, ADR-011 surcouche) :

- Seuils définis : `medium` à ratio ≥ 3×, `high` à ratio ≥ 5×
- Avec baseline mean = 50, il faudrait `len(articles) ≥ 150` pour
  déclencher `medium` → **structurellement inatteignable** tant que
  l'API CC retourne le default 50

**La détection volume spike CC est donc dormante en pratique** depuis
le Paquet 21 (~25 jours de runtime). Aucun flag `cryptocompare.anomaly_detected`
de severity ≠ ok n'a été levé. **Non régressif** (l'anti fake-news
ADR-011 cross-validation Modified Z-score reste opérationnel, et les
détecteurs Reddit brigading + Google News dominance fonctionnent).

### Options envisagées (à choisir post-J+14)

| Option | Description | Risque | Bénéfice |
|---|---|---|---|
| **A** | Demander plus d'articles à l'API CC via pagination `lTs` | Risque API quota (free tier 11k req/mois, déjà ~720 req/mois actuels — marge confortable) | Détection volume spike fonctionnelle ; potentiel faux positif si volume API variable selon heure |
| **B** | Changer la métrique : compter `len(set(headlines.publisher))` (publishers distincts) | Aucun (pas de changement API) | Pic publishers distincts = événement majeur (ex. ETF approval, hack) → corrélation potentielle plus pertinente que volume brut |
| **C** | Mesurer vélocité publication (articles/heure si polling infra-horaire) | Nécessite changement polling | Métrique plus fine, capte les bursts ; mais polling > 1×/h coûte plus de quota |
| **D** | Accepter détection dormante, retirer le code mort | Aucun | Code plus simple, pas de fausse impression de couverture |

### Verdict préliminaire

**Option B** semble la plus alignée avec la philosophie OSINT pure (ADR-018) :
un pic de publishers distincts est un signal qualitatif plus riche qu'un
pic de volume brut. À valider empiriquement sur un dataset historique
post-J+30 avant de coder.

### Quand l'attaquer

Post-J+14, dans la séquence P6+ du plan stratégique fiabilité signaux
(cf. CLAUDE.md section 8). Pas urgent : (1) la détection volume CC
n'a jamais déclenché donc aucune régression par rapport au pre-Paquet 21,
(2) Reddit brigading + Google News dominance couvrent déjà la surcouche
P6 sur d'autres sources, (3) anti fake-news ADR-011 reste opérationnel
sur les agrégats croisés.

### Risque rappelé

Garde-fou 1 inchangé. Garde-fou 2-bis inchangé. ADR-003 inchangé.
ADR-004 inchangé. ADR-011 inchangé (la cross-validation Modified Z-score
n'est pas affectée — elle agit sur les biais agrégés, pas sur la
détection upstream par ingester). ADR-018 inchangé.

## 9. Recalibration / archivage GDELT post-J+30 (identifié 2026-05-18, P3 plan stratégique fiabilité)

Décision P3 prise le 2026-05-18 : **NE PAS déployer GDELT BTC** et
**recalibrer les seuils GDELT GOLD post-J+30** (cf. CLAUDE.md section 8).

### Constat factuel runtime HP (mesure 2026-05-18)

Sur les 5 jours de runtime HP depuis le premier signal en DB :

- 239 observations GDELT GOLD swing (couverture 92.6 % des 258 signaux GOLD)
- Distribution du tone : **100 % en zone neutre** `[-1, +1]` du mapping ADR-010
  - min = 0.070, max = 0.700, avg = 0.376, std = 0.208
  - 0 observations en zone `bull` (≤ -1.0)
  - 0 observations en zone `bear` (≥ 1.0)
- **Conséquence** : `_compute_gdelt_bias` retourne `bias = 0.0` sur 100 % des cycles
- **GDELT GOLD a apporté zéro information directionnelle au pipeline depuis le déploiement**

Cohérent avec le verdict Paquet 19 P2 : backtest historique 12m = 0 points
mesurables (rate-limit GDELT public sur fetch historique long). Le mapping
ADR-010 ±1/±3 est issu de littérature GDELT générique, pas de la
distribution réelle du tone sur la query "gold price" sourcelang:eng.

### Hypothèse sur la cause

Le query "gold price" + lang:eng retourne un mix d'articles éditoriaux
financiers et de cours techniques quotidiens → tone moyen lissé proche
de zéro, naturellement loin des seuils ±1. Le régime 2025-2026 est
plutôt "stable + faible crise géopol immédiate", contrairement à 2008
(GFC), 2020 (pandémie), 2022 (Ukraine) ou 2023 (SVB) où le tone GDELT
aurait probablement basculé dans la zone négative (tensions globales).

### Critère de décision post-J+30 (à appliquer ~2026-06-17)

Re-mesurer la distribution du tone GDELT GOLD sur 30j de runtime
(idéalement avec un événement de stress macro dans la fenêtre — FOMC,
NFP surprise, CPI choc, géopol majeur).

| Mesure observée sur 30j | Action |
|---|---|
| **> 80 % en zone neutre** `[-1, +1]` ET aucun événement extrême observé | Recalibrer seuils à `±0.5 / ±1.5` (au prorata `std_observed × 2.5 / 5.0`) puis re-mesurer 30j supplémentaires |
| **> 80 % en zone neutre** ET événement extrême observé sans bascule du tone | Archiver GDELT (ingester + `_enrich_with_gdelt` + entry `SOURCE_SCORES`) — le tone GDELT ne capte pas les régimes de stress que la query "gold price" devrait pourtant refléter |
| **Distribution s'élargit naturellement** (≥ 20 % hors zone neutre) | Valider mapping contrarian sur GOLD via IC Spearman vs delta 720h ; si IC négatif significatif → déployer GDELT BTC avec mapping à valider de la même façon |

### Critère secondaire : query alternative

Si recalibration tente une dernière fois avant archivage, envisager
un query plus restrictif :

- `"gold" AND (crisis OR war OR sanctions OR recession)` → focus
  événements générateurs de tensions, devrait amplifier les bascules
- `"federal reserve" "monetary policy"` → focus politique monétaire
  US (probablement plus volatile en tone que "gold price")

À tester côté script CLI avant tout changement du ingester runtime.

### Quand l'attaquer

Post-J+30 (~2026-06-17), dans la séquence P3+ du plan stratégique
fiabilité signaux (cf. CLAUDE.md section 8). Pas urgent : GDELT GOLD
émet bias = 0.0 systématique donc équivalent à un overlay absent —
zéro impact négatif sur le pipeline (ADR-018 OSINT pur reste opérationnel
sur les 3 autres overlays GOLD : Google News + DXY/COT désactivés
amendement P2 + technical evidence informatif).

### Risque rappelé

Garde-fou 1 inchangé. Garde-fou 2-bis inchangé. ADR-003 inchangé.
ADR-004 (multi-overlay) inchangé — on optimise la qualité OSINT par
recalibration empirique, pas par ajout aveugle d'overlays. ADR-010
(GDELT mapping initial) à amender lors de la recalibration. ADR-011
(anti fake-news) inchangé. ADR-018 (OSINT pur) renforcé empiriquement
par le respect strict de l'engagement "pas d'ajout sans manque mesuré".

## 10. Reddit IP-ban full sur IP HP — Option B unban en cours + Option C source alternative post-J+14 (identifié 2026-05-18, Paquet 27, Bug 11)

**Contexte** : audit santé pré-J+14 du 2026-05-18 (Paquet 27) a révélé
que Reddit est **totalement IP-bannie sur l'IP publique HP
`204.168.220.47`** depuis le déploiement HP entier (5 jours
d'historique en DB). 0/1778 signaux contiennent `reddit_btc` dans
l'evidence. Test 7 endpoints HTTP : tous bloqués (403) sauf
`/api/v1/access_token` (401, joignable mais inutile car
`oauth.reddit.com` aussi 403). Cf. CLAUDE.md section 9 Bug 11 pour le
diagnostic complet.

**Conséquence pipeline structurelle** : Tik tourne avec **3 overlays
sentiment au lieu de 4** sur BTC swing → veracity capée à 0.85-0.89
quand FG diverge contrarian des news (cas typique marché bear actuel),
**0/36 signaux BTC swing à veracity ≥ 0.90 sur 9h post-fix N=2**. Bug
N=2 du Paquet 25 (fixé 2026-05-17 20:47 UTC) masquait cette réalité.

### Option A retenue immédiatement (cf. Paquet 27 décision D1+D4)

Accepter Tik à 3 overlays + Garde-fou 2-bis transitoire seuil **0.85
sur BTC swing** (au lieu de 0.90). Réversible automatiquement quand
Reddit revient. **Aucun code modifié**, juste doc.

### Option B en cours (cf. Paquet 27 décision D2)

Demande unban formelle soumise par l'utilisatrice le 2026-05-18 soir
via le formulaire officiel Reddit
`support.reddithelp.com/hc/en-us/requests/new?ticket_form_id=21879292693140`
("Demande d'aide bloquée") avec :

- Adresse IP `204.168.220.47`
- Justification OSINT research non commerciale
- Engagement à migrer vers OAuth authentifié dès l'unban
- User-Agent descriptif conforme rules Reddit
  (`tik-osint-bot/0.1 (research; contact escltheo@gmail.com)`)

**Délai retour Reddit inconnu** (24h → plusieurs semaines, souvent
3-10 jours). À surveiller via email utilisatrice
(`escltheo@gmail.com`).

**Si retour positif Reddit** : vérification rapide `curl -s -o
/dev/null -w "%{http_code}\n" -H "User-Agent: test"
https://www.reddit.com/r/Bitcoin/hot.json` depuis container ingesters
→ si 200 → `docker compose up -d --force-recreate ingesters` → Reddit
réintégré au pipeline en ~5 min → automatiquement retour à 4 overlays
sans changement code.

### Option C à activer post-J+14 SI Reddit refuse définitivement (~4-5h dev)

Remplacer Reddit par une source sentiment alternative. **À ne pas
activer pré-J+14** (trop risqué de réécrire un ingester sentiment à
< 1 semaine du trading manuel).

**Sources évaluées** :

| Source | Pour | Contre | Score utilité |
|---|---|---|---|
| **Hacker News (Algolia HN Search API)** | Gratuit, JSON propre, communauté tech crédible (couverture crypto + macro), pas d'IP-ban historique | Volume crypto plus faible que Reddit (~10-20 titres pertinents/jour), tonalité tech-skeptique | 7/10 |
| **StockTwits API** | Free tier, focus crypto/symbols (`$BTC.X`, `$ETH.X`), sentiment natif bull/bear annoté par les utilisateurs | Demande inscription, rate limits stricts, communauté trader US plus retail que macro | 6/10 |
| **4chan /biz/ (4chan API JSON)** | Gratuit, signal contrarian fort (retail extrême) | Très bruité, ironie/troll non capté par LLM 3B, qualité éditoriale faible | 4/10 |
| **X/Twitter via snscrape** | Gratuit, volume énorme, signal crypto-natif | Fragile (X durcit régulièrement), snscrape peut casser, risque IP-ban X aussi | 4/10 |
| **Lemmy / Mastodon crypto instances** | Gratuit, fédéré, pas d'IP-ban | Très faible volume (~1-5 titres pertinents/jour), niche | 3/10 |
| **Bitcointalk forum** | Volume crypto historique fort | Pas d'API officielle, scraping HTML fragile, ban IP potentiel | 3/10 |

**Verdict préliminaire** : **Option C.1 Hacker News** (Algolia HN
Search API endpoint `https://hn.algolia.com/api/v1/search`) — score
utilité 7/10, infra propre, gratuit, pas d'IP-ban historique. À
valider empiriquement post-J+14 si Reddit refuse.

### Option D structurelle (ultime, ~1-2 sessions + coût mensuel)

Si Reddit refuse l'unban ET Option C ne convient pas → migrer Tik
core vers un VPS commercial avec IP propre (DigitalOcean, Hetzner,
Scaleway... ~5-10€/mois pour 2 GB RAM + 1 vCPU). L'IP serait dédiée à
Tik, sans réputation negative, et Reddit serait re-accessible.

**Trade-offs** :
- ✅ Résout tous les ban IP futurs (pas que Reddit)
- ✅ Améliore la résilience générale (plus de dépendance internet
  domestique)
- ❌ Coût mensuel ~60-120€/an
- ❌ Migration ~1-2 sessions (DB export/import + DNS + monitoring)
- ❌ Hébergement déjà HP serveur local qui marche bien sinon

À considérer **seulement si** Reddit refuse définitivement + Option C
ne convient pas + utilisatrice OK pour passer en VPS payant.

### Quand l'attaquer

| Action | Quand | Effort |
|---|---|---|
| Surveiller email pour réponse Reddit | Dès maintenant, asynchrone | 0 min |
| Si retour Reddit OK avant J+14 | Restart ingesters + vérif curl | 5 min |
| Si pas de retour Reddit dans 14 jours post-J+14 (= 2026-06-07) | Activer Option C (Hacker News ingester + ADR-021) | 4-5h |
| Si Option C insuffisante OU besoin résilience générale | Activer Option D (VPS migration) | 1-2 sessions + 5-10€/mois |

### Critère de réévaluation cette entry

**Date péremption** : 2026-06-15 (J+22 trading manuel). À cette date :
- Si Reddit a répondu (positivement ou négativement) → fermer cette
  entry et documenter résolution dans CLAUDE.md
- Si pas de retour Reddit + Option C activée → entry 11 dédiée à
  l'ingester Hacker News
- Si pas de retour Reddit + Option C pas activée → réévaluer
  l'urgence selon le hit rate Tik mesuré J+30

### Risque rappelé

Garde-fou 1 (Tik shadow vs Zeta 3 mois) inchangé. ADR-003 (pas de
bypass V01-V15) inchangé. ADR-004 (multi-overlay) inchangé — Tik
continue de fonctionner avec N-1 overlays, c'est la beauté du pattern
extensible. ADR-011 (anti fake-news) inchangé. ADR-018 (OSINT pur)
renforcé empiriquement (preuve que l'archi multi-overlay tolère bien
une source manquante sans casser le pipeline).

## 11. Tests Jest dashboard — dette technique (identifié 2026-05-19, Paquet 28)

**Contexte** : Phase C Session 2 (Paquet 28) a livré ~810 lignes de
code dans 4 fichiers nouveaux + 5 modifiés côté dashboard, dont
2 modules de helpers purs (`src/watchlist/outcome.ts` et
`src/watchlist/stats.ts`) qui mériteraient une couverture pytest-style.
Pattern Phase C Session 1 (Paquet 13) conservé : **pas de framework
Jest dashboard à ce stade**, validation runtime iPhone Expo Go côté HP.

### Constat factuel

Côté `core/` : ~988 tests pytest verts au 2026-05-18, frameworks
matures (pytest + httpx.MockTransport + AsyncMock). Côté `dashboard/`
: **0 tests**, validation strictement runtime.

Conséquences :
- Régressions silencieuses possibles sur des helpers purs simples
  (cf. bug latent `pick_new(quota=0)` corrigé Paquet 4 Session 4 par
  test pytest — équivalent possible côté `dominantHorizon` ou
  `isEligibleForAutoResolve` côté dashboard)
- Refactor frileux car pas de filet de sécurité

### Options évaluées

| Option | Effort | Couverture |
|---|---|---|
| **A.** Jest setup vanilla + tests `outcome.ts` / `stats.ts` | ~1-2h setup + ~50 tests | Helpers purs uniquement |
| **B.** Jest + React Native Testing Library + tests composants | ~2-3h setup + ~30 tests | Helpers + composants (PersonalHitRateCard, modal) |
| **C.** Maestro / Detox tests E2E iPhone | ~4-6h setup + ~10 scénarios | UI bout-en-bout sur device réel |
| **D.** Statu quo + validation runtime iPhone | 0h | Aucune |

### Verdict préliminaire

**Option A** post-J+14 — minimum vital : couvrir les helpers purs
de `outcome.ts` + `stats.ts` + `useAutoResolveWatchlist` (factory
`createResolveEntryFn`). Sortie test : Jest + ts-jest, ~50 tests
trivials qui pourraient passer en 1-2 sec.

Option B reportée post-J+30 selon volume de bugs UX rapportés.
Option C reportée indéfiniment (overkill MVP solo).

### Quand l'attaquer

Post-J+14, dans la semaine du 2026-05-24 → 2026-06-01 si la trader
n'est pas dans le rush du premier trade. Sinon différer au mois
suivant. Pas urgent — les helpers purs sont relus visuellement et
TypeScript strict catch ~80 % des erreurs de typage.

### Risque rappelé

Garde-fou 1 inchangé. ADR-003 inchangé. Dette technique purement
qualité de code, zéro impact runtime ou business.

## 12. Dette lint/format ruff massive sur src/ + tests/ (identifié 2026-05-20, Paquet 31)

**Contexte** : audit santé du 2026-05-20 (Paquet 31) a fait tourner la
commande CI exacte `ruff check src/ tests/` dans le conteneur core. Résultat :
**360 erreurs** ruff + `ruff format --check src/ tests/` voudrait reformater
**58 fichiers**. Dette pré-existante (pas introduite par le fix Paquet 31, dont
les 3 fichiers `conftest.py` modifié passent ruff proprement).

### Constat factuel

- `ruff check src/ tests/` : 360 erreurs, dont 188 auto-fixables (`--fix`),
  20 supplémentaires en `--unsafe-fixes`.
- Familles d'erreurs observées : `UP017` (datetime.UTC alias), `I001`
  (import sorting), `SIM105` (contextlib.suppress), etc.
- `ruff format --check` : 58 fichiers à reformater, 44 déjà OK.
- Conséquence : les étapes `ruff check` + `ruff format --check` de la CI
  (`.github/workflows/ci.yml` jobs core-lint et core-test) sont **rouges**
  depuis un moment. Le commit `bf0d360` (gardes Bug 9/10) a même introduit des
  `UP017` jamais validés.

### Options évaluées

| Option | Effort | Risque |
|---|---|---|
| **A.** `ruff check --fix` + `ruff format` sur tout `src/ tests/` en un coup | ~30 min | Gros diff (58+ fichiers), revue impossible visuellement, risque qu'un auto-fix change un comportement subtil |
| **B.** Par lots : d'abord `tests/` (sans risque runtime), puis `src/` fichier par fichier avec relance pytest | ~2-3h | Faible — chaque lot validé par la suite verte (1052) contre tik_test |
| **C.** Seulement `--fix` (pas `--unsafe-fixes`) + format, puis revue ciblée des hunks `src/` | ~1h | Modéré |
| **D.** Statu quo + ignorer plus de règles dans `[tool.ruff.lint] ignore` | ~10 min | Masque la dette au lieu de la résoudre |

### Verdict préliminaire

**Option B** recommandée (par lots, validée par pytest à chaque étape) — c'est
la seule qui garde un filet de sécurité. À faire **après** le fix Paquet 31
(commit séparé), et idéalement **après J+24** si la trader est dans le rush du
premier trade : c'est de la qualité de code, zéro impact runtime/business
immédiat (le code tourne, seul le lint CI est rouge).

### Risque rappelé

Garde-fou 1 / ADR-003 inchangés. Dette purement qualité de code. **Mais**
attention : un `ruff --fix` aveugle sur `src/` pourrait toucher de la logique
(ex. `RET`/`SIM` réécrivent des structures de contrôle). Toujours relancer la
suite pytest contre `tik_test` (jamais la prod, cf. memory
`pytest-run-safely-tik-test`) après chaque lot.

### ✅ RÉSOLU 2026-05-20 (même session que Paquet 31)

Approche finalement retenue : **Option B+config** (auto-fixes sûrs + format +
config ciblée pour les faux positifs framework, jamais de réécriture aveugle
de logique). Détail :

- **Auto-fixes sûrs** (`ruff check --fix`, **sans** `--unsafe-fixes`) : 260
  corrections mécaniques (UP017 `timezone.utc`→`datetime.UTC`, I001 tri imports,
  F401 imports inutilisés, F541, RET501, C420, UP035/041, SIM117/300…).
- **`ruff format`** : 56 fichiers reformatés (whitespace/quotes/wrapping, zéro
  logique).
- **Fixes code genuins/triviaux (validés pytest)** : F821 (vrai import
  `datetime` manquant dans `test_source_credibility.py` — annotation
  neutralisée par `from __future__ import annotations`), PIE810 (tuple
  `endswith`), B007 (suppression d'une boucle morte `for asset: pass` dans
  `backtest_golden.py`), RET504 (return inline dans `hypothesis_generator`).
- **Config ruff** (zéro risque code, cf. `pyproject.toml`) :
  - `flake8-bugbear.extend-immutable-calls` = FastAPI `Depends/Query/...` +
    `tik_core.auth.require_scope` → tue les 55 B008 (pattern DI idiomatique).
  - `per-file-ignores` `tests/**` = `ARG001/ARG002/N805/E402` (bruit helpers de
    test).
  - `ignore` global += `SIM103/108/105` (style), `B027` (ABC no-op Strategy),
    `UP042` (enum, churn différé).
  - 4 ARG src documentés via `# noqa` (conformité d'interface : lifespan
    FastAPI, adapter advisory, baselines backtest).

**Résultat** : `ruff check src/ tests/` = **All checks passed**, `ruff format
--check` = 102/102 formatés, **suite pytest 1052 verts** contre tik_test.
Les étapes lint CI (jobs core-lint + core-test) repassent vertes.

**Limite résiduelle** : 1 `DeprecationWarning` runtime non-lint subsiste
(`pubsub.close()` → `aclose()` dans `ws.py:127`) — warning bénin, hors scope
lint, à traiter avec le prochain bump de la lib redis.
