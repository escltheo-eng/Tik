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
| **J+1-2** | **Phase 1 — Carte "Top headlines aujourd'hui"** dashboard. Réutilise les news déjà ingérées (Google News BTC/GOLD + CryptoCompare + Reddit + GDELT). 5-10 titres affichés bruts avec source, sentiment et heure. Tri par crédibilité × récence. | ~½ session (1 endpoint API + 1 carte Tsx) | Contexte rapide brut. Tu vois les news qui motivent les sentiments avant de regarder les signaux. **Zéro risque LLM hallucination** — c'est de la donnée brute citant ses sources. Pattern OSINT pro classique (Recorded Future, Bellingcat). |
| **J+3-4** | **Carte Home "Hit rate live"** — pourcentage de signaux Tik corrects sur les 30 derniers jours par horizon (flash 1h / swing 7j) et asset (BTC/GOLD). Réutilise `core/src/tik_core/scripts/backtest.py` déjà livré, expose en endpoint API + carte Home. | ~1 session | Calibre ta confiance. Si swing BTC est à 65% sur 30j, tu trades avec sizing X. Si à 45%, tu skip ou tu réduis. **C'est la feature N°1 d'un outil de signal pour démarrer un live trading.** |
| **J+5-6** | **Vue "Track record signal"** dans le détail signal. Pour chaque signal historique, affiche le delta de prix après 1h/6h/24h/5j (multi-horizon, cohérent avec le pipeline calibration Session 4 Paquet 4). Badges visuels ✓ correct / ✗ raté / ⚠ neutre. | ~1 session | Tu apprends à reconnaître les types de signaux qui marchent vs ceux qui ratent. Ton oeil se forme avant le live. |
| **J+7-8** | **Workflow "Watchlist post-trade"** — bouton "j'ai pris ce trade" sur le détail signal qui ajoute le signal à une watchlist persistée (AsyncStorage, pattern déjà déployé pour Alerts cf. bug A résolu 2026-05-04). Onglet Watchlist dédié. | ~1 session | Discipline opérationnelle. Tu sais quel signal a déclenché quel trade. Indispensable pour tirer des leçons après. |
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

1. **Calendrier événementiel macro** (FOMC, NFP, CPI, GDP, élections,
   sommets, sanctions) → c'est exactement la **Lacune B** prévue les 7-8
   mai (cf. entry n°3 ci-dessus). **Brique pivot** — sans calendrier, on
   ne peut pas anticiper les chocs macro.

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
- **Marché** : Top headlines (en haut) + Veracity globale + Dernier signal par actif + Activité 24h
- **Calibration** : Hit rate live + Hit rate par veracity + Tendance veracity + Stats LLM
- **Système** : État du core + Bouton refresh + Version box + lien vers Config/Bots/Alerts

L'écran d'accueil devient **« Marché »** par défaut (= ce dont tu as besoin avant un trade).
**Calibration** devient une vue d'audit séparée qu'on consulte en début de
journée. **Système** disparaît dans un menu secondaire.

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
