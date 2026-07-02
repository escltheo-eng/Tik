# Plan de connexion micro — labo btc-research-lab → Tik (ADR-034)

> **Décision utilisatrice 2026-07-02** : « en sachant ces pièges je préfère finir la
> chaîne — une connexion fiable et bien définie, avec un plan clair et une checklist
> de tous les obstacles. » Ce document EST ce plan. Il s'appuie sur l'audit E2E
> micro du 2026-07-02 (4 volets : labo, backend, dashboard déployé, dashboard main).
>
> **Rappels non négociables** : NO-GO directionnel intact ; le micro est en SHADOW
> strict (`circuit_breaker_status='degraded'`, ne touche JAMAIS le `combined_bias`) ;
> mesure ≥ 2 semaines vs baselines AVANT toute décision d'enrôlement (règle CLAUDE.md §8).

---

## 1. Architecture de la connexion

```
  Mac utilisatrice (labo)                        VPS Hetzner (Tik)
┌───────────────────────────┐                 ┌──────────────────────────────┐
│ dashboard.py (mono-process)│    HTTP POST    │ core FastAPI                 │
│  └─ tik_push_loop (60s)   │ ──────────────► │  POST /api/v1/signals/ingest │
│      └─ tik_adapter.py    │  Bearer API key │   ├─ kill-switch 503         │
│          ├─ mapping        │                 │   ├─ whitelist entités 422   │
│          ├─ throttle       │                 │   └─ _publish_signal         │
│          └─ urllib (stdlib)│                 │       ├─ Postgres horizon    │
└───────────────────────────┘                 │       │   ='micro' (expiry 2h)│
                                              │       └─ Redis pubsub        │
                                              │  tik.signal.BTC.micro → WS   │
                                              └──────────────────────────────┘
```

## 2. Contrat de la connexion (décisions figées — ne pas « améliorer » en douce)

| Sujet | Décision | Pourquoi |
|---|---|---|
| Verdict labo → direction Tik | `GO_LONG`→`long` ; `WAIT`/`NO_GO`→`neutral` ; **jamais `short`** | Labo long-only by-design ; verdict brut conservé dans `advisory.lab_verdict` |
| Modèle pas prêt (aucune proba) | **Signal NON envoyé** | Silence, pas du bruit — un NO_GO « données manquantes » n'est pas une opinion |
| Confidence | HIGH 0.8 / MEDIUM 0.6 / LOW 0.4 / NONE 0.2 | Catégoriel → scalaire, conservateur |
| Veracity | **Non envoyée** → défaut serveur 0.70 | On ne fabrique pas de certitude (Axe #1) |
| Contre-scénarios | 2 fixes honnêtes (H1 réfutée ; changement de régime vol) | Paranoïa contrôlée respectée |
| Triggers | proba + gates, **poids 0.0** | Informatif, aucun poids décisionnel |
| Horizon labo poussé | 1 seul, `TIK_INGEST_HORIZON` (défaut `1h`) | 6 horizons × chaque tick = flood ; on commence simple |
| Cadence | Transition de verdict OU heartbeat 30 min | Pattern anti-flood du flash (ADR-005) ; ~10-50 signaux/jour max |
| Entité | BTC uniquement (whitelist serveur) | Périmètre ADR-030 ; 422 propre sinon (plus de 500 FK) |
| Kill-switch | **Des deux côtés** : `TIK_INGEST_ENABLED` (labo, défaut OFF) + `TIK_MICRO_INGEST_ENABLED` (serveur, défaut OFF) | Réversibilité totale, conforme ADR-030 Étape 2 |
| Fenêtres de mesure Tik | hit rate 2h (seuil 0.4 %) ; track record 15min/30min/1h/2h, klines 15m | Alignées sur l'expiry 2h du publisher |

## 3. État de la chaîne (fait / à faire)

- [x] **Backend Tik** : kill-switch 503 + whitelist entités 422 + fenêtres de mesure micro (hit rate, track record) + `signal_freshness` exclut micro + tests (8 nouveaux + 2 durcis)
- [x] **Labo** : `tik_adapter.py` (mapping + throttle + HTTP best-effort, stdlib) + `tik_push_loop` dans `dashboard.py` + `.env.example` + 11 tests
- [x] **Dashboard `main`** : type `Horizon` + exclusion micro des alertes fake-news ET veracity_collapse + fenêtre watchlist 2h + libellé amplitude + le « dernier signal » n'est jamais un micro
- [ ] **Dashboard déployé (`refonte-cosmique`)** : 2 correctifs à porter (cf. §6) — branche gérée par la session refonte
- [ ] **Mise en service** (cf. §5) — actions utilisatrice sur VPS + Mac
- [ ] **Mesure 2 semaines** puis verdict écrit (SUPPORTED/REFUTED) dans un futur ADR

## 4. ✅ CHECKLIST DES OBSTACLES (demandée explicitement — à relire avant CHAQUE étape)

### Obstacles réseau / infra
- [ ] **O1 — Le Mac doit joindre le VPS** : `curl http://<ip-vps>:8200/api/v1/health` depuis le Mac DOIT répondre avant tout. Si la box/le FAI bloque le port 8200 sortant → rien ne passera. *Détection : timeout curl. Mitigation : tester d'abord, sinon Tailscale.*
- [ ] **O2 — HTTP en clair sur Internet** : la clé API transite non chiffrée vers `ip:8200`. *Mitigation acceptée court terme (clé au scope minimal, révocable) ; moyen terme : reverse-proxy TLS ou Tailscale — à décider avec l'hébergement (docs/hosting-and-app-options.md).*
- [ ] **O3 — IP du VPS qui change / VPS réinstallé** : `TIK_BASE_URL` devient invalide silencieusement (l'adaptateur loggue des warnings, le labo continue). *Détection : `grep tik_adapter` dans les logs labo + compteur signaux micro à 0.*
- [x] **O4 — CADUC (découvert au merge 2026-07-02)** : en prod le labo tourne dans un conteneur `micro` **sur le VPS** (`/opt/btc-research-lab`, pont `tik_bridge.py`, ACTIF depuis le 2026-06-24) — pas sur le Mac. `tik_adapter.py` (ce plan) reste la version committée/testée, OFF par défaut → **réconcilier les deux ponts** (nouvel obstacle O21).

### Obstacles clé API / auth
- [ ] **O5 — Scope `write:signals` ABSENT des scopes par défaut** de `create_api_key.py` : une clé créée sans `--scopes read:signals,write:signals` → 403 systématique. La commande exacte est dans `.env.example` du labo.
- [ ] **O6 — Client déjà existant** : `create_api_key` refuse si `--client micro-lab` existe déjà → choisir un autre nom ou désactiver l'ancienne clé.
- [ ] **O7 — Clé collée avec espace/retour ligne** dans `.env` → 403 inexplicable. *Vérifier avec un curl manuel avant d'accuser le code.*

### Obstacles de contrat / sémantique
- [ ] **O8 — Piège `include_flagged`** : les micro sont TOUS `degraded` by-design → `GET /metrics/hit_rate?horizon=micro` avec le défaut `include_flagged=false` renverra **toujours 0 signal**. Toute mesure DOIT passer `include_flagged=true`. (Verrouillé par test `test_micro_always_degraded_needs_include_flagged`.)
- [ ] **O9 — Ne jamais mapper NO_GO → short** : tentation future de « récupérer » les prédictions baissières. Le labo ne shorte pas by-design ; changer ça = nouvel ADR + re-mesure complète.
- [ ] **O10 — 3 sens du mot « micro »** : horizon ML (ADR-030/034), panier TradingView (ADR-031), microstructure (labo + triggers flash). Toujours préciser lequel dans les docs/discussions.
- [ ] **O11 — Warm-up labo au boot** : ré-entraînement ~minutes après démarrage → aucune proba → l'adaptateur skippe (voulu). *Ne pas « corriger » ce silence.*

### Obstacles de mesure (avant verdict)
- [ ] **O12 — Fenêtres chevauchantes** : heartbeat 30 min sur mesure 2h → signaux non indépendants. La mesure finale doit utiliser des fenêtres NON chevauchantes + test apparié vs Always SHORT (cf. `measurement-overlapping-returns`, `measurement-rigor-controls`).
- [ ] **O13 — Corrélation micro ↔ swing** : si Spearman > 0.5 avec les signaux OSINT → redondant, pas d'apport (ADR-030 §6).
- [ ] **O14 — Volume trop faible** : à ~10-50 signaux/jour dont beaucoup de neutral, 2 semaines peuvent ne pas suffire pour une puissance statistique correcte → prolonger plutôt que conclure faible.

### Obstacles d'exploitation
- [ ] **O21 — DEUX ponts labo→Tik en parallèle** (découvert au merge) : `tik_bridge.py` (prod VPS, actif 24/06) vs `tik_adapter.py` (committé ici, OFF). Un seul doit survivre à terme ; en attendant, ne JAMAIS activer les deux en même temps (doublons de signaux). Le kill-switch serveur `TIK_MICRO_INGEST_ENABLED` doit rester `true` en prod sinon le pont reçoit 503 (incident ~30-60 min le 02/07).
- [ ] **O15 — Divergence des dashboards** : les correctifs UI sont sur `main` ; l'app DÉPLOYÉE vient de `refonte-cosmique` qui a 2 trous (cf. §6). Tant que non portés : fausses alertes « Effondrement de l'accord » + un micro peut s'afficher en tuile héro du Cockpit.
- [x] **O16 — Collision de numérotation ADR — RÉSOLUE 2026-07-02** (merge des branches) : cosmiques renumérotés 030→035 (risk-regime), 031→036 (stablecoins), 032→037 (cross-asset) ; 033-fusion = doublon historique du 030 canonique ; « ADR-034 verdict » cosmique réservé → **ADR-038**. Références code mises à jour.
- [ ] **O17 — Déploiement VPS ≠ ce repo** : le VPS tourne sur le dépôt de prod (`Lolasiku-prog/Tik`) ; les changements backend d'ici doivent y être appliqués (git apply / copie des fichiers, comme fait pour TradingView) puis `docker restart tik-core` (bind-mount → pas de rebuild, aucune nouvelle dépendance).
- [ ] **O18 — Le micro ne doit pas masquer une panne** : réglé côté `/signal_freshness` (micro exclu du max), mais `source_health` n'a PAS de sentinelle « labo » → si le labo s'arrête, aucune alerte. Accepté en shadow ; à revoir si enrôlement.
- [ ] **O19 — Notifications Telegram** : les micro n'y apparaissent PAS (volontaire en shadow). Ne pas s'étonner de leur absence dans le briefing.
- [ ] **O20 — Redémarrage ingesters/core pendant un POST** : l'adaptateur encaisse (retry au tick suivant, état de throttle inchangé sur échec — testé).

## 5. Mise en service pas-à-pas (quand tu veux activer)

**Étape A — côté VPS (console Hetzner, l'invite `root@tik-server-1`) :**
1. Appliquer les changements backend au VPS (je te guiderai — même méthode que TradingView).
2. Créer la clé API du labo :
   `docker exec tik-core python -m tik_core.scripts.create_api_key --client micro-lab --name "Labo micro" --scopes read:signals,write:signals`
   → **copier la clé affichée** (montrée une seule fois).
3. Activer le kill-switch serveur : ajouter `TIK_MICRO_INGEST_ENABLED=true` dans `core/.env` puis `docker restart tik-core`.
4. Vérifier : `curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8200/api/v1/signals/ingest -H "Authorization: Bearer <la-clé>" -H "Content-Type: application/json" -d '{"direction":"neutral","confidence":0.2}'` → attendu **201** (403=scope, 503=toggle oublié).

**Étape B — côté Mac (labo) :**
1. Dans `btc-research-lab/.env`, ajouter les lignes `TIK_*` (modèle dans `.env.example`) avec l'IP du VPS et la clé.
2. Relancer `python dashboard.py` → chercher dans les logs `tik_push_loop: enabled`.

**Étape C — vérification bout-en-bout (dans l'heure) :**
1. Sur l'iPhone, onglet Signals, filtre « Micro » → un signal doit apparaître (badge `micro · ML (shadow)`).
2. Sur le VPS : `docker logs tik-core --tail 50 | grep micro` → `signal.published id=TIK-MICRO-BTC-...`.

## 6. Correctifs à porter sur `refonte-cosmique` (session refonte — spéc exacte)

1. **`dashboard/src/api/stream.ts` (~ligne 239)** : ajouter l'exclusion micro au déclencheur `veracity_collapse` (l'exclusion fake-news existe déjà à la ligne ~233) — même patch que `main` : garde `signal.horizon !== 'micro'` sur le `if` veracity.
2. **`dashboard/src/hooks/useDashboardKpis.ts` (`deriveLastByEntity`)** : `if (s.horizon === 'micro') continue;` pour que la tuile « Derniers signaux BTC/GOLD » du Cockpit n'affiche jamais un micro shadow.
3. (Optionnel, cosmétique) `src/watchlist/outcome.ts` : `micro: 2` dans `REFERENCE_HOURS_BY_HORIZON` ; glossaire : expliquer « micro ».

## 7. Critère de fin (mesure)

Après ≥ 2 semaines de signaux : script de mesure dédié (à écrire, modèle `measure_btc_derivatives.py`) — hit rate micro (`include_flagged=true` !), baselines Always SHORT/LONG/NEUTRAL/Random, test apparié en fenêtres non chevauchantes, corrélation vs swing. Verdict écrit SUPPORTED/REFUTED. **Aucun enrôlement sans ce verdict.**
