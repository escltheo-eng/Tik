# ADR-030 — Fusion « macro + micro » dans un backend unique (Tik ⨉ btc-research-lab)

- **Statut** : PROPOSÉ (en attente de validation utilisatrice sur le chemin F1 vs staged-F2→F1)
- **Date** : 2026-06-22
- **Auteur** : assistant Claude (sous consigne « doute méthodique continu, arguments/contre-arguments, transparence »)
- **Branche de travail** : `claude/compassionate-goodall-gpkg9q` (sur Tik **et** btc-research-lab)

---

## 0. Demande utilisatrice (verbatim reformulé)

Réunir **deux entités distinctes** en une seule application « qui comprend tout », avec **l'UI de Tik** :

- **« macro »** = **Tik** : cockpit OSINT / sentiment / contexte macro (Fear&Greed, news, régime
  macro ADR-028, calendrier Fed…), avec le **dashboard mobile Expo**.
- **« micro »** = **btc-research-lab** : labo quant/ML (prédiction BTC à la minute, micro-structure,
  carnet d'ordres L2, apprentissage en ligne river/LightGBM, backtests à frais réels).

Choix explicites de l'utilisatrice :
1. **Un seul backend fusionné** (pas « deux moteurs séparés que l'UI lit »).
2. **Les 3 buts à la fois** : (a) cockpit d'observation unique, (b) chercher un edge prédictif,
   (c) simplifier (une app au lieu de deux).

---

## 1. ⚠️ Avertissement épistémique (à ne jamais maquiller)

**Les DEUX projets ont, séparément, conclu qu'ils n'ont PAS d'edge prédictif prouvé :**

- **Tik** : verdict officiel **NO-GO directionnel** (2026-05-27). Repositionné comme outil de
  **contexte + discipline + alerting**. Cf. CLAUDE.md §8.
- **btc-research-lab** : hypothèse principale **H1 RÉFUTÉE** — un modèle ML technique ne bat pas
  les baselines naïves (`mean_reversion` domine) sur rendement net out-of-sample. Cf. `RESEARCH.md` §1.

> **Conséquence directe** : fusionner deux outils sans edge **n'en crée pas un**. Au mieux on obtient
> un **meilleur cockpit d'observation** (but a), au pire on **dilue** (piège explicitement décrit
> dans CLAUDE.md §8 : « en moyenner davantage ne crée pas d'edge, ça le dilue »). Le but (b)
> « chercher un edge » reste **légitime mais non garanti**, et **soumis à mesure rigoureuse** (§6).

**Règle non-négociable héritée des deux cultures** : tout signal « micro » entrant dans Tik le fait
**en mode shadow**, **mesuré ≥ 2 semaines** contre les baselines (Always SHORT / mean_reversion /
random, en fenêtres non chevauchantes), **AVANT** tout enrôlement qui influencerait une décision.
Il **ne touche jamais** le `combined_bias` des moteurs swing/flash existants. Le NO-GO reste intact.

---

## 2. État vérifié des deux backends (cartographie 2026-06-22)

### 2.1 Tik (cible de la fusion)
- **Déploiement** : Docker multi-conteneurs — `postgres` (TimescaleDB), `redis`, `core` (FastAPI),
  `ingesters`, `scheduler` (APScheduler).
- **Stockage partagé** : PostgreSQL/Timescale (hypertable `signals`) + Redis (pub/sub + cache).
- **Contrat de signal stable** : dataclass `*Decision` (`direction`, `confidence`, `veracity`,
  `hypothesis`, `counter_scenarios`, `evidence`, `triggers`, `circuit_breaker_status`, `advisory`).
- **Moteurs** : `scoring/swing_engine.py` (5 j), `scoring/flash_engine.py` (1 h). Slot **macro**
  réservé non implémenté.
- **Couture d'extension propre** = nouveau moteur : `scoring/X_engine.py` → job scheduler →
  alias publisher → route API → valeur `horizon`. Package **`tik_core/ml/` réservé et VIDE**
  (emplacement naturel pour vendoriser le noyau micro).
- **Python 3.11**, `numpy>=2.1.2`, FastAPI/SQLAlchemy2/Pydantic2.

### 2.2 btc-research-lab (source du « micro »)
- **Déploiement** : **mono-process** — `python dashboard.py` lance TOUT (UI Dash + boucle asyncio
  + ingest WS + pollers + boucles de ré-entraînement + step online).
- **Stockage** : **DuckDB** mono-fichier (`history.duckdb`) + état mémoire `shared.State`.
- **Noyau ML « micro » (sans dépendance UI, à fusionner)** :
  `features.py` → `predictor.py` (LightGBM direction) + `magnitude_predictor.py` (LightGBM quantile)
  + `online_predictor.py` (river, incrémental) → `calibrators.py` (Platt/Isotonic) →
  `signal_runner.py` (orchestrateur pur) → `long_signal.py` (verdict GO/WAIT/NO_GO) →
  `trade_setup.py`. Plus `orderbook.py` (micro-structure L2), `fundamentals.py` (pollers),
  `storage.py` (DuckDB), `shared.py` (état live).
- **À NE PAS porter** (outillage de recherche, orthogonal) : `dashboard.py` (5700 lignes),
  `backtest*.py`, `red_team*.py`, `forensics*.py`, `gp_search.py`, `audit.py`, etc.
- **Données nécessaires au noyau** : flux Binance WS klines `1s…1d` + `@trade` + **`@depth20@100ms`**
  (carnet L2 temps réel) — plus riche que ce que l'ingester Tik capture aujourd'hui.

### 2.3 Recouvrements à réconcilier (les deux les ont déjà)
`macro_regime`, `orderbook`, `risk_engine`, `source_confidence`, `signal_card` existent **des deux
côtés** avec des implémentations différentes. La fusion devra **choisir une source de vérité** par
concept (ne pas empiler deux régimes macro).

---

## 3. Points durs techniques (vérifiés / recherchés)

| # | Point dur | Constat | Implication |
|---|---|---|---|
| 1 | **DuckDB mono-écrivain** | DuckDB verrouille le fichier en écriture : **un seul process** peut écrire ; multi-process = lecture seule uniquement (recherche 2026-06 : DuckLake/Quack existent mais récents/beta). | Traîner DuckDB **à travers** les conteneurs Tik (core/ingesters/scheduler séparés) est un **anti-pattern**. Soit on **confine** tout le micro dans **un seul** conteneur (DuckDB interne OK), soit on **migre** vers Postgres/Timescale. |
| 2 | **numpy 2.x** | Tik épingle `numpy>=2.1.2`. `river 0.21` : compat numpy 2 **à confirmer**. `gplearn 0.4` : douteux — **mais hors noyau** (recherche only) → on ne le porte pas. | Risque de résolution pip **réel mais circonscrit** au trio `lightgbm`/`scikit-learn`/`river`. **NON vérifié** par un vrai `pip install` (cf. §7). |
| 3 | **UI Dash/Plotly abandonnée** | On garde l'UI Expo de Tik. `dash`/`plotly` ne sont **pas** portés. | Allège fortement la surface de dépendances à fusionner. |
| 4 | **Persistance des modèles** | Le labo **ré-entraîne au boot** (bootstrap replay 5000 barres) — les modèles river/LightGBM ne semblent **pas** persistés sur disque. | Au redémarrage d'un conteneur, ~quelques minutes de warm-up avant signaux valides. Acceptable en shadow ; à documenter. |
| 5 | **Coût CPU** | Ré-entraînement LightGBM périodique (toutes les 5 min check) + step river 60 s. | Doit tourner dans un conteneur **dédié** (ne pas alourdir l'API/scheduler OSINT). |
| 6 | **Données L2** | L'ingester Tik ne stream pas `@depth20@100ms` en continu (le flash utilise `GET /depth` REST ponctuel). | Le micro a besoin de son **propre flux WS L2** (réutilise l'ingest du labo dans son conteneur en F2 ; à recâbler en F1). |

---

## 4. Décision d'architecture — F1 (absorption) vs staged F2→F1

Le but final « **un seul backend / une seule app / une seule UI** » est commun aux deux options.
La question est **comment y arriver sans casser ce qui tourne**.

### Option F1 — Absorption directe dans `tik_core`
Vendoriser le noyau micro dans `tik_core/ml/`, créer `scoring/micro_engine.py` produisant un
`MicroDecision` (contrat Tik), **supprimer DuckDB** (→ Postgres/Timescale), **supprimer
`shared.State`** (→ Redis + ingester Tik enrichi du flux L2), persister `horizon="micro"`.

| ✅ Pour | ❌ Contre |
|---|---|
| **Vrai** backend unique, littéral (un seul codebase, un seul stockage). | **Effort élevé + risque élevé** : réécrire toute la couche données du labo. |
| Cohérence totale du contrat `Decision`, un seul Postgres. | Risque de casser un moteur ML **stateful et subtil** (anti-leakage, bootstrap, caches fundamentals) — régression **difficile à détecter**. |
| Pas de DuckDB multi-process (point dur #1 réglé d'emblée). | **Long avant la 1re mesure** → viole « mesurer vite / réversible ». |
| Maintenance unifiée à terme. | Si le micro s'avère sans apport (probable vu H1 réfutée), on aura payé le coût lourd **pour rien**. |

### Option F2 — Annexion par un conteneur `micro` (puis migration vers F1)
Ajouter un **nouveau service** `micro` au `docker-compose` de Tik, qui fait tourner le **pipeline
ML du labo tel quel** (DuckDB + `shared.State` **internes et isolés dans ce seul conteneur** → pas
de conflit mono-écrivain), + un **adaptateur fin** qui traduit ses sorties en `MicroDecision`,
**écrit les signaux `horizon="micro"` dans le Postgres de Tik** et **publie sur Redis**. Résultat :
**une seule commande `docker compose up`, une seule UI Expo, une seule API**.

| ✅ Pour | ❌ Contre |
|---|---|
| **Réversible et rapide** : ne casse ni Tik ni le labo. | Pas encore « un seul codebase » (deux moteurs **internes**). |
| DuckDB reste **mono-process** → point dur #1 neutralisé sans réécriture. | Duplication **temporaire** de la couche données (DuckDB + Postgres). |
| Cockpit unifié + **mesure shadow** en quelques jours. | Deux images Docker / deux stacks de deps à maintenir le temps de la transition. |
| On **apprend si le micro vaut la peine** AVANT d'investir dans la migration lourde. | — |

### Verdict recommandé : **chemin par étapes F2 → F1**

> **F2 d'abord** (livre l'app unifiée + la mesure shadow), **puis migration incrémentale vers F1**
> (de-DuckDB, vendorisation dans `tik_core/ml/`) **si et seulement si** le micro démontre un apport
> mesuré. **L'état final visé reste F1** (un seul codebase) — on ne fait que l'atteindre sans
> big-bang. C'est l'application directe des règles projet : *réversible*, *shadow ≥ 2 sem avant
> enrôlement*, *mesurer plutôt que spéculer*.

Ce verdict **respecte le choix « un seul backend »** (dès F2 il n'y a qu'un déploiement, une UI, une
API) tout en refusant le pari risqué d'une réécriture lourde sur un moteur dont l'apport n'est pas
démontré.

---

## 5. Architecture cible (après F2) — schéma

```
                ┌──────────────────────── UI unique : Expo (dashboard Tik) ───────────────────────┐
                │  onglet « Macro/Sentiment » (existant)      onglet « Micro » (nouveau, shadow)   │
                └───────────────▲──────────────────────────────────────────▲──────────────────────┘
                                │ REST + WebSocket (API Tik, /api/v1)        │
                ┌───────────────┴────────────────────────────────────────── core (FastAPI) ───────┐
                │  signals (swing/flash/…)  +  horizon="micro"  (lecture Postgres + WS Redis)       │
                └───────▲───────────────────────────▲───────────────────────────────▲──────────────┘
                        │ écrit                       │ pub/sub                        │ écrit
                ┌───────┴─────────┐          ┌────────┴────────┐            ┌──────────┴──────────────┐
                │ scheduler (OSINT)│          │     redis        │            │  micro (NOUVEAU conteneur)│
                │ swing/flash/...  │          │  pub/sub+cache   │            │  pipeline ML du labo      │
                └───────┬─────────┘          └────────┬────────┘            │  (DuckDB interne isolé)   │
                        │ écrit                        │                      │  + adaptateur MicroDecision│
                ┌───────┴──────────── postgres / TimescaleDB (hypertable signals) ◄──────────────────┘
```

- Le conteneur `micro` **n'écrit pas** dans le `combined_bias` ni dans les tables OSINT — il écrit
  **uniquement** des lignes `signals` avec `horizon="micro"` et `circuit_breaker_status="degraded"`
  (marqueur shadow), publiées sur un canal Redis dédié `tik.signal.BTC.micro`.

---

## 6. Discipline de mesure (but b « edge » — sous contrôle)

Avant tout enrôlement du micro dans une décision :
1. **≥ 2 semaines** de signaux `horizon="micro"` collectés en shadow.
2. Mesure **vs baselines** (Always SHORT, mean_reversion, random) en **fenêtres non chevauchantes**,
   test apparié, IC / hit rate / gain net **après frais réels** (le labo a déjà ce cadre).
3. **Corrélation** micro ↔ swing OSINT (Spearman) : si > 0.5 → redondant, pas d'apport indépendant.
4. Verdict écrit (SUPPORTED/REFUTED) dans un futur ADR-031, comme `RESEARCH.md` le fait déjà.

---

## 7. Ce que je n'ai PAS encore vérifié (transparence)

- [ ] **Résolution pip réelle** d'un environnement commun (Tik + `lightgbm`/`scikit-learn`/`river`)
      sous Python 3.11 / numpy 2.x — risque point dur #2 **non levé** (pas de `pip install` exécuté).
- [ ] Si le labo **tourne réellement** dans ce conteneur (jamais exécuté ici ; pas de Docker côté labo).
- [ ] Taille / santé réelle de `history.duckdb` et comportement exact au redémarrage (replay confirmé
      par lecture de code, pas par exécution).
- [ ] Si l'ingester Binance de Tik peut être **étendu** au flux `@depth20@100ms` sans régression
      (pour F1), ou s'il faut garder l'ingest L2 du labo.
- [ ] Compat des secrets / clés (Binance optionnel côté labo) avec la config Tik.
- [ ] Réconciliation des **doublons** (§2.3) : quelle implémentation de `macro_regime`/`orderbook`
      devient la source de vérité.

## 8. Risques & mitigations

| Risque | Mitigation |
|---|---|
| Conflit de dépendances (numpy 2 / river) | Conteneur `micro` **séparé** avec sa propre image (F2) → isole le risque ; test pip dédié avant F1. |
| Le micro dilue / induit en erreur | Shadow strict, `horizon="micro"`, ne touche jamais `combined_bias` ; NO-GO affiché honnêtement. |
| Coût CPU du ré-entraînement | Conteneur dédié, cadence inchangée du labo, monitoring `source_health`. |
| Casse d'un moteur ML stateful subtil | F2 = on ne réécrit PAS le moteur ; on l'enveloppe. Migration F1 seulement après preuve d'apport. |
| « Vernis de certitude » UX (Axe #1) | Onglet Micro étiqueté **shadow/expérimental**, pas de % de conviction vendu comme fiable. |

## 9. Plan par étapes (réversibles)

- **Étape 0 (cet ADR)** — décision + cadrage. *Réversible : c'est un document.*
- **Étape 1** — `Dockerfile.micro` + service `micro` dans `docker-compose` ; faire tourner le
  pipeline du labo en isolé (sans rien brancher sur Tik). *Réversible : conteneur indépendant.*
- **Étape 2** — adaptateur `MicroDecision` → écriture `horizon="micro"` en Postgres + publish Redis.
  *Réversible : toggle `TIK_MICRO_ENABLED=False` par défaut.*
- **Étape 3** — onglet « Micro » (shadow) dans l'UI Expo, lecture via API/WS existants.
- **Étape 4** — **mesure ≥ 2 sem** (§6) → ADR-031 verdict.
- **Étape 5 (conditionnelle)** — migration F1 : vendoriser le noyau dans `tik_core/ml/`,
  de-DuckDB → Postgres, retrait du conteneur `micro`. **Uniquement si Étape 4 = apport prouvé.**

---

## 10. Conséquences

- **Positif** : une app/un déploiement/une UI dès l'Étape 3 (but c) ; cockpit unifié macro+micro
  (but a) ; cadre de mesure propre pour le but b (edge), sans pari risqué.
- **Négatif / dette** : duplication temporaire DuckDB+Postgres ; deux images jusqu'à F1 ;
  réconciliation des doublons reportée à F1.
- **Réversibilité** : chaque étape est isolée par un toggle ou un conteneur ; abandon possible sans
  toucher au Tik en production.
