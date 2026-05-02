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

## 2. Traduction native française des signaux Tik

**Date d'identification** : 2026-05-02 (Paquet 4 Session 4, en cours d'annotation
manuelle du golden dataset)

**Contexte** : tous les champs textuels produits par Tik aujourd'hui sont en
anglais (cohérent : les sources Google News, CryptoCompare, GDELT, Reddit
filtrent toutes `lang=EN`). Concrètement :

- `evidence[].fact` (preuves)
- `counter_scenarios[].description` et `.mitigation` (contre-scénarios)
- `advisory[].message` (avis additionnels)

L'utilisatrice principale du projet (lectrice francophone, débutante en
trading) doit aujourd'hui lire ces signaux en anglais via curl ou via le
SDK. Le futur dashboard Expo (Paquet 3) aura le même problème. Pour les
bots clients (Zeta, Totem), c'est sans importance — ils consomment du
JSON structuré pas du texte humain.

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
- ADR-011 documente le choix Option A vs B/C

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
- **Sinon** → Session 5 dédiée à la traduction native FR (avec ADR-011).

**Risque rappelé** : Garde-fou 1 (mode shadow 3 mois) **strictement applicable**
à ce nouveau code de traduction (pas de risque trading mais le contrat ADR-003
de non-bypass V01-V15 reste **inchangé** — la traduction ne touche aucune logique
décisionnelle).
