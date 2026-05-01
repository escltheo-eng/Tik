# ADR-010 — Overlay tone GDELT pour GOLD (mode timelinetone, contrarian, NLP scientifique non-LLM)

- **Statut** : Accepté
- **Date** : 2026-05-01

## Contexte

À l'issue des Sessions 1 et 2 du Paquet 4 (cf. ADR-008 et ADR-009), Tik dispose d'une grille robuste sur **BTC** : 4 sources sentiment cross-validées (Fear & Greed contrarian + CryptoCompare crypto-éditorial + Google News mainstream-éditorial + Reddit retail-communautaire). Toutes les sources textuelles BTC passent par le **même backend NLP** (`OllamaClassifier` avec `llama3.2:3b`).

**GOLD reste sous-équipé en news macro/géopol**. Ses 4 overlays actuels sont :

- **DXY** (FRED) — chiffré officiel, contrarian
- **CFTC COT** — positionnement institutionnel hebdomadaire avec lag 3-4 jours, contrarian
- **Google News GOLD** — sentiment éditorial mainstream texte, trend-following

Les **drivers historiques de l'or** sont essentiellement **les tensions globales** (guerre, sanctions, défaillances bancaires, inflation hors contrôle, rotations safe haven). Aucune source actuelle de Tik ne capture **directement** cette dimension géopolitique mondiale. Google News GOLD avec query `"gold price"` capture la couverture éditoriale du prix de l'or, mais pas la tonalité éditoriale **mondiale** qui prédit les flux safe haven.

**GDELT 2.0** (Global Database of Events, Language, and Tone) est précisément conçu pour ça :

- Agrégation scientifique de news mondiales en 65 langues, mise à jour toutes les 15 min
- Calcul d'un **tone score** dans `[-10, +10]` par méthode NLP académique (lexicons normalisés + agrégation pondérée par volume d'articles)
- Gratuit, sans clé requise pour la Doc API (`https://api.gdeltproject.org/api/v2/doc/doc`)
- Largement utilisé en littérature académique (Yale Climate Connection, Universities of Pittsburgh / Maryland, etc.)

Trois questions structurantes se posent au moment d'intégrer GDELT :

1. **Mode** : récupérer les articles individuels et les classifier nous-mêmes via Ollama (cohérent avec le pattern Sessions 1-2), ou consommer le tone agrégé pré-calculé par GDELT (`timelinetone`) ?
2. **Interprétation du tone** : trend-following (tone positif = bull GOLD) ou contrarian (tone négatif = tensions → safe haven → bull GOLD) ?
3. **Couverture** : GOLD seul, ou aussi BTC ?

## Décision

### 1. Mode : `timelinetone` (tone GDELT brut, sans classifier Ollama)

**Choix structurant** : c'est la **première source de Tik à ne PAS passer par OllamaClassifier**. Le ingester GDELT consomme directement le tone calculé par GDELT (champ `avgtone` du payload `timelinetone`).

| Aspect | `artlist + Ollama` | **`timelinetone` (retenu)** |
|---|---|---|
| Cohérence pattern P4 Session 1-2 | ✅ Identique | ❌ Premier écart |
| Diversification méthodologique | ❌ Encore Ollama-LLM | ✅ NLP scientifique non-LLM |
| Coût Ollama (5e classifier) | ❌ +50-80 s par cycle | ✅ 0 s |
| Contrôle sur les paliers | ✅ Total | ⚠️ Mapping à calibrer |
| Evidence détaillée par titre | ✅ Oui | ❌ Score agrégé seulement |

**Argument décisif** : la **diversification des méthodes de scoring** est un saut qualitatif que les Sessions 1-2 ne pouvaient pas offrir. Si Ollama classifie 4 sources qui se contredisent, c'est encore une seule perspective méthodologique — limites du LLM 3B partagées par les 4 sources. Si **GDELT (NLP scientifique) converge avec Ollama-LLM**, c'est un signal **plus fort** que 5 Ollama qui convergent. Si elles divergent, c'est une **information** qui remonte la diversité du sentiment réel. C'est l'esprit ADR-004 poussé plus loin : diversifier les *méthodes*, pas seulement les *sources*.

**Bonus opérationnel** : 0 latence Ollama supplémentaire au cycle. Le ingester GDELT est **ultra-léger** (1 appel HTTP, parsing JSON, mapping numérique). Aucun classifier au boot, aucun circuit breaker à manager.

### 2. Interprétation du tone : **contrarian** (cohérent avec FG, distinct de Google News)

C'est la décision **la plus subtile** de l'ADR. Elle reflète la sémantique économique de l'or comme **safe haven asset**.

**Pour trend-following** (tone positif → bull bias) :
- Plus d'articles positifs sur "gold price" → bull
- Cohérent avec Google News / CryptoCompare / Reddit (tous trend-following)

**Pour contrarian** (tone négatif → bull bias GOLD) :
- Le tone GDELT mesure la **tonalité éditoriale globale** du sujet (incluant le contexte macro mondial)
- Tone négatif = tensions, crises, panique mondiale → **rotation vers safe haven** → bull GOLD
- Corrélation historique forte : 1970s inflation, 2008 GFC, 2020-22 pandémie + invasion Ukraine, 2023 Silicon Valley Bank — **chaque épisode de stress a vu l'or monter**
- Cohérent avec **Fear & Greed** (FG bas = panique = contrarian bull crypto). Pour GOLD, le mécanisme est analogue mais inversé : GDELT bas (= panique mondiale) = bull GOLD

**Argument décisif** : la sémantique de l'or **est** contrarian par construction macro. Aller en trend-following sur GDELT pour GOLD reviendrait à dire « les news positives prédisent une montée de l'or », ce qui est l'opposé de la dynamique safe haven historique. Le pattern contrarian est **validé empiriquement** sur 50 ans d'histoire monétaire.

**Mapping retenu** (`_compute_gdelt_bias`) :

```
tone <= -3.0  →  +1.0  (tensions extrêmes mondiales → strong bull GOLD)
tone <= -1.0  →  +0.5  (climat tendu → bull GOLD)
-1.0 < tone < 1.0  →  0.0  (climat normal → neutral)
tone >= 1.0  →  -0.5  (climat optimiste → bear GOLD)
tone >= 3.0  →  -1.0  (euphorie → strong bear GOLD)
```

**Calibration provisoire**. Les seuils ±1, ±3 sont issus de la littérature GDELT et de l'observation empirique du bruit du tone score (la majorité du temps `|tone| < 1`, les épisodes de stress poussent vers `tone <= -2`). Réévaluation prévue Session 4 après mesure du dataset golden.

### 3. GOLD seul (pas BTC en Session 3)

La couverture BTC est **rejetée** pour Session 3, malgré la tentation de la symétrie (GOLD aurait 4 overlays incl. GDELT, BTC reste à 4).

**Raison principale** : le **mapping contrarian validé pour GOLD est incertain pour BTC**. La corrélation BTC ↔ tensions globales est **instable** :

- Mars 2020 : BTC sell-off avec les actions (corrélation positive, pas safe haven)
- Russie 2022 : BTC bull (sanctions → demande crypto, corrélation contrarian comme GOLD)
- 2023 SVB : BTC bull (« digital gold thesis »)
- Mais aussi des cas où BTC ne réagit pas du tout aux tensions

Déployer un mapping non-validé sur BTC introduirait du **bruit** dans le pipeline BTC qui marche bien actuellement (4 sources cohérentes mesurées en runtime). Stratégie échelonnée plus prudente :

| Session | GDELT scope | Action |
|---|---|---|
| **3 (cette session)** | GOLD seul | Valider en runtime que le mapping contrarian fonctionne |
| **4** | Dataset golden inclut titres macro BTC labellisés | Mesurer si GDELT BTC apporterait un signal et avec quel mapping |
| **5+** | Ajout GDELT BTC si validé | Mapping calibré empiriquement |

Cohérent avec la philosophie *"on ne biaise pas a priori, on mesure"* (ADR-006, ADR-008, ADR-009).

### 4. Périmètre exact

- **Endpoint** : `https://api.gdeltproject.org/api/v2/doc/doc?query="gold price"&mode=timelinetone&format=json&timespan=1d&lang:eng`
- **Pas de clé API requise**.
- **Filtre langue** : `lang:eng` (anglais seulement). Multi-langue rejeté pour Session 3 (biais translation incertains, NLP GDELT mieux calibré sur l'anglais selon la littérature). Réévaluation Session 4+ si dataset golden montre qu'on rate des signaux régionaux.
- **Query** : `"gold price"` avec guillemets pour séquence exacte. Cohérent avec la query Google News GOLD pour comparabilité cross-source. Élargissement éventuel (`OR "central bank gold" OR "gold reserves"`) reporté à Session 4+ si dataset golden montre des manques.
- **Timespan** : `1d` (dernières 24 h). GDELT lisse le tone sur la fenêtre demandée. Plus court → bruit excessif. Plus long → latence du signal trop élevée.
- **Polling toutes les 30 min** : aligné Google News + Reddit (cohérence cross-cycle). 1 req tous les 30 min = ~1440 req/mois. GDELT n'a pas de rate-limit documenté pour la Doc API en lecture publique.
- **Score `gdelt_news = 0.75`** dans `SOURCE_SCORES` : un cran au-dessus des news mainstream (CryptoCompare/Google News à 0.70) pour reconnaître la qualité éditoriale + scientifique de GDELT, un cran sous les sources gouvernementales chiffrées (FRED `dtwexbgs` à 0.85). Provisoire — réévaluation Session 4 après dataset golden.
- **Clé Redis** : `tik.sentiment.gdelt.gold` (TTL 2 h, comme les autres sources textuelles).
- **Champ payload** : on stocke le tone brut `avgtone`, le nombre d'articles agrégés `numarts`, le timespan, la query, le `fetched_at`. Pas de `top_publishers` (GDELT ne les expose pas en mode `timelinetone`) — c'est une perte d'info volontaire pour gagner en simplicité méthodologique.
- **Pas de classifier** : `GdeltIngester` n'a **pas** de paramètre `classifier`. C'est volontaire : GDELT est notre première source à diversification méthodologique pure.

### 5. Réutilisation infra existante

Le ingester GDELT suit le **même squelette** que les autres ingesters textuels (`BaseIngester`, `start`/`stop`, boucle `_run` avec polling), modulo :

- Pas de paramètre `classifier`
- Pas d'appel à `classifier.reset_batch()` / `classifier.aclose()`
- Pas de paramètre `entity_id` configurable (GOLD codé en dur — Session 3 single-asset)

L'ajout dans `swing_engine.py` suit le pattern multi-overlay strict (ADR-004) : helper `_compute_gdelt_bias` (avec mapping contrarian spécifique [-10, +10]), helper `_enrich_with_gdelt`, branchement dans `analyze_swing_gold` uniquement.

## Conséquences

**Positives**

- **Premier overlay GOLD avec dimension géopolitique mondiale** : capture les tensions internationales que Google News GOLD US-piloté rate. C'était le besoin identifié dans ADR-008 et ADR-009.
- **Diversification méthodologique** : Tik a désormais du sentiment Ollama-LLM (CC, Google News, Reddit) ET du sentiment NLP scientifique (GDELT). Si les deux convergent → veracity élevée. Si divergent → information riche sur la diversité du sentiment réel.
- **Pipeline GOLD à 4 overlays cross-validés** : DXY (FRED, contrarian) + COT (CFTC, contrarian) + Google News (trend-following) + GDELT (contrarian) — équilibre solide pour la veracity dynamique.
- **Aucun coût Ollama supplémentaire** : ingester ultra-léger (1 req HTTP par cycle, parsing JSON, mapping numérique). Pas de 5e classifier au boot.
- **Aucune nouvelle dépendance Python** (parsing JSON natif via `httpx.json()`, math du stdlib).

**Négatives**

- **Mapping contrarian à valider empiriquement** : le seuils ±1, ±3 sont issus de la littérature GDELT mais nécessiteront une calibration sur les données réelles. Risque que le tone observé soit toujours dans la zone neutre `[-1, +1]` → overlay peu actif. À mesurer Session 4.
- **Algo NLP propriétaire de GDELT** : pas explicable ligne par ligne, contrairement à Ollama où on contrôle le prompt. C'est un trade-off conscient (cf. décision 1).
- **Pas d'evidence détaillée par titre** : le payload `timelinetone` retourne un score agrégé, pas la liste des articles. Pour la transparence dashboard, on a moins de richesse que pour Google News (qui expose `top_publishers`). Mitigation : on log le `numarts` (nombre d'articles agrégés) pour traçabilité.
- **Endpoint GDELT non garanti à perpétuité** : la Doc API GDELT V2 fonctionne en 2026 mais GDELT a déjà eu des évolutions API (V1 → V2 en 2018). Mitigation : log warning + cycle suivant retentera, comme pour Google News (ADR-008) et Reddit (ADR-009).
- **GDELT BTC reporté** : asymétrie temporaire (BTC à 4 overlays Ollama, GOLD à 4 overlays mixtes incluant GDELT). Justifiée par la prudence du mapping contrarian non-validé sur BTC.

**Risques opérationnels rappelés**

- **Garde-fou 1 (mode shadow 3 mois)** **strictement applicable**. L'ajout de GDELT ne raccourcit pas la période d'observation.
- **ADR-003 (pas de bypass V01-V15)** **inchangé**. GDELT suit le même chemin d'agrégation que les autres sources.
- **Garde-fou 2 (budget test 5 %)** rappelé pour mémoire.
- **Section 6 paranoïa contrôlée** : les contre-scénarios standard du swing restent attachés à chaque décision. GDELT enrichit l'evidence GOLD, ne supprime aucun contre-scénario.

## Implémentation (fichiers touchés)

- `core/src/tik_core/aggregator/gdelt_ingester.py` *(nouveau, sans classifier)*
- `core/src/tik_core/scoring/swing_engine.py` *(ajout `SOURCE_SCORES["gdelt_news"]=0.75`, helpers `_read_gdelt` / `_compute_gdelt_bias` (mapping contrarian [-10,+10]) / `_enrich_with_gdelt`, branchement dans `analyze_swing_gold`)*
- `core/src/tik_core/scripts/run_ingesters.py` *(ajout instance `GdeltIngester`, total 10 ingesters, 4 classifiers Ollama inchangés)*
- `core/tests/test_gdelt_ingester.py` *(nouveau)*
- `core/tests/test_swing_engine.py` *(extension : helpers GDELT, mapping contrarian, edge cases tone)*
- `CLAUDE.md` *(section 8 Paquet 4 Session 3)*
