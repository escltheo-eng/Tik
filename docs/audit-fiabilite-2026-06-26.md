# Audit fiabilité Tik — 2026-06-26

> Audit « chaque composant, tous les fails, pour toutes les données » demandé par
> l'utilisatrice. Objectif : ce qu'il faut pour une appli **fiable**, avec une
> **majorité de bons signaux bien suivis**. Méthode : 4 explorations parallèles du
> code + vérifications manuelles de l'auditeur (corrections des sur-estimations).

## 0. Cadre & limites (honnêteté — engagements §13bis)

**Ce que cet audit A pu vérifier** : le **code** (repo dev `/home/user/Tik`), la
cartographie complète émission → suivi → affichage, les modes de défaillance par
composant (avec `fichier:ligne`), l'état runtime **documenté** dans CLAUDE.md.

**Ce qu'il N'a PAS pu vérifier (sandbox)** :
- ❌ **Aucun accès à la prod** (`204.168.220.47:8200` injoignable d'ici → `HTTP=000`) →
  pas de lecture des **vrais signaux émis**, hit-rates réels, santé runtime live.
- ❌ **Pas d'env Python / pytest** ici → la suite (« ~1595 tests verts » au 15/06) **non re-confirmée**.
- ⇒ L'analyse « chaque signal réel » nécessite des `curl` sur le VPS (cf. §5).

**Corrections apportées aux agents** (ils se sont trompés, mea culpa déclaratif) :
1. **Cartes legacy `components/dashboard/*` ≠ « 11 non-conformes »** : ce sont en quasi-
   totalité du **code mort** (vérifié : seules `HitRateByVeracityCard` + `StatsLLMCard`
   sont montées, dans l'onglet **Plus** ; les ~9 autres ne sont importées nulle part).
2. **« Un outage API fait crasher le scheduler » = FAUX** : chaque job de
   `run_scheduler.py:43-118` est enveloppé dans `try/except Exception` → log + continue
   (conforme Bug 9). Vraie gravité = **perte silencieuse d'un cycle**, pas un crash.
3. `watchlist.tsx` **existe** (l'agent dashboard le disait « non trouvé »).

---

## 1. Re-vérification « est-ce que tout fonctionne ? »

| Brique | État | Détail / preuve |
|---|---|---|
| Scheduler | ✅ Résilient | Tous les jobs `try/except` → un échec = cycle perdu + log, pas de crash (`run_scheduler.py`) |
| Tests pytest | ❔ Non re-testé ici | Dernière mesure connue : ~1595 verts (15/06) — **à re-confirmer sur le VPS** |
| WebSocket live | ✅ Fixé | Bug 16 (redis-py 8.0) corrigé 15/06 |
| Publisher DB | ✅ Fixé | Bug 9 (tz aware) strip explicite + test dédié |
| **BTC swing** | 🟠 **Dégradé structurel** | **2/4 overlays** (Reddit HS + CryptoCompare HS) → 0 short, que des LONG « FG achète-la-peur » |
| **GOLD swing** | 🟠 Dégradé | 2 sources (Google News + GDELT throttlé) → veracity plancher ; **non tradé** (hit 4.8 %) |
| Flash BTC | ✅ OK | Binance WS stable ; skip propre si feed > 60 s |
| Macro / contexte | ✅ OK | FRED + 4 familles contexte (régime, risque, stablecoins, cross-asset) |
| Micro (shadow) | 🟠 Non-suivable | Track-record → **HTTP 400** (horizon non géré), aucune mesure possible |

**Verdict** : l'**infrastructure** tourne et est résiliente. Ce qui est dégradé, ce
sont les **signaux directionnels BTC/GOLD**, par **manque de sources** (pannes externes
Reddit/CryptoCompare), pas par bug applicatif. **Cohérent avec le NO-GO du 27/05** :
Tik = contexte/discipline/alerting, pas un générateur de signaux fiables.

---

## 2. Cartographie composant par composant — TOUS les fails

### 2.1 SOURCES / INGESTERS (la matière première)

> Une source qui tombe ne **plante** pas un signal : elle le **dégrade** (un overlay en
> moins → direction moins contestée, veracity faussée). C'est le risque n°1 actuel.

- **Binance trades (BTC)** — prix temps réel (WS). État ✅. Fail : WS stale > 60 s → flash skip (garde-fou OK) ; reconnect exponentiel.
- **Yahoo (GOLD)** — prix +15 min. État ✅. Fail : timeout → skip cycle (TTL 300 s tolère) ; gaps marché fermé → `données_manquantes`.
- **Fear & Greed (BTC)** — overlay contrarian. État ✅. Fail : miss → perte du contrarian. **Régime peur extrême (FG≈9-18) → biais saturé +1.0** (domine à 2/4 overlays).
- **CryptoCompare news (BTC)** — overlay texte. 🔴 **HS depuis 11/06** (Bug 15, quota 100/mois). Réversible **~1er juillet** (reset). Polling repassé 8h.
- **Google News (BTC+GOLD)** — overlay texte. État ✅. Fail : 429 → skip (TTL 2h).
- **Reddit (BTC)** — overlay texte. 🔴 **IP-banni depuis 18/05** (Bug 11). 0 contribution. Demande unban en attente. Mitigé : seuil veracity 0.85.
- **GDELT (GOLD)** — overlay géopol. 🟡 **Throttlé ~75 % (429)**, mitigé (polling 2h, TTL 6h).
- **CoinGecko** — shadow (toggle OFF). Pas branché.
- **FRED / Macro Regime / Rate Probabilities / Risk / Stablecoins / Cross-asset** — contexte ✅. Famille NON-sentiment, ne touche jamais direction/veracity.
- **Polymarket / Binance dérivés / ETF flows** — shadow ✅ (collecte, **non enrôlés**). C'est **ici que vit l'edge potentiel** (familles non-sentiment).
- **Breaking news** — alerting ✅ (jamais directionnel).

**Synthèse sources** : `2 sources critiques HS` (Reddit + CryptoCompare) → **BTC swing à
2/4 overlays**. Réversible automatiquement (CryptoCompare ~1/7, Reddit = unban incertain).

### 2.2 ÉMISSION (comment un signal peut sortir faux / dégradé / trompeur)

- **Swing engine** (`swing_engine.py`)
  - 🟠 **Fetch klines sans try/except interne** (l.122-163) → exception remonte au scheduler (logué, **cycle perdu en silence**, pas de crash, pas d'alerte UI).
  - 🟡 Indicateurs techniques NaN → evidence vide en silence (pas de défaut de direction : poids 0 depuis ADR-018).
  - 🟠 **Seuil direction 0.30 jamais validé empiriquement** (guess de 05/2026).
  - ✅ Overlays Redis manquants → skip propre (fallback None).
- **Flash engine** (`flash_engine.py`)
  - ✅ Fraîcheur > 60 s → skip ; fetch orderbook/aggTrades → skip propre.
  - 🟡 Pas de débounce sur micro-transitions → N signaux en 30 min possible.
  - 🟡 LLM appelé même si `should_emit=False` → CPU gâché (cosmétique).
- **Cross-validation / anti-fake-news** (`cross_validator.py`)
  - 🔴 **Seuils dispersion (0.5/0.85) calibrés en régime « normal »** : en peur extrême (FG +1 vs news −1), dispersion≈1.0 → **tous les shorts BTC `tripped` → direction forcée neutral**. À recalibrer **post-régime** (mesure réelle multi-régime).
  - 🟠 **Incohérence « degraded + veracity 0.95 »** (A1/ADR-026) : l'outlier est exclu de la direction mais la dispersion résiduelle peut donner 0.95 → contre-intuitif. À expliciter à l'UI.
  - 🟡 `pstdev` (N=2) vs `stdev` (N≥3) incohérent (A5) → harmoniser sur `pstdev`.
  - ✅ Split extrême → `tripped` → neutral (fail-safe correct).
- **Anomaly detector (P6)** (`anomaly_detector.py`)
  - ✅ Brigading Reddit / dominance publisher (seuils recalibrés 10/06) / volume spike.
  - 🟡 Volume spike CryptoCompare **dormant** (API ~50 art. constant). Diversité publisher en **observation** (n'agit pas).
- **Source credibility (ADR-011)** (`source_credibility.py`)
  - ✅ Floor anti-contamination (pré-fix N=2) ; skip si N<30.
  - 🟠 **Attribution grossière** : un signal juste crédite **toutes** ses sources (pas de grain fin). Impact **cosmétique** (n'altère jamais direction/veracity post-ADR-018).
- **Hypothesis LLM (Ollama)** (`hypothesis_generator.py`)
  - ✅ Fallback template + circuit breaker 3-strike + validation (longueur/direction/entité) + détection prix inventés + lock anti-contention.
  - 🟠 Mode `shadow` : si le caller oublie de logguer → audit perdu (fragile).
- **Publisher** (`publisher.py`)
  - ✅ Strip tz (Bug 9) ; advisory non-dict → `{}`.
  - 🟠 **Redis publish échoue après commit DB** → clients ratent le signal (DB OK, WS manqué). Fallback = resync REST. À envelopper.
- **Config** (`config.py`)
  - 🟠 **`antifakenews_mode` non validé** : une typo (`"actif"`) → anti-fake-news **silencieusement désactivé**. Ajouter une whitelist + `.lower()`.

### 2.3 SUIVI (« bien suivis ») — `metrics.py` + dashboard watchlist

- **Auto-résolution watchlist** (`useAutoResolveWatchlist.ts`, poll 5 min)
  - 🔴 **Micro → HTTP 400** (`metrics.py:562-580`, horizon non géré) → favori micro reste `en attente` **à vie** (cooldown 30 min ne fait que retenter la même erreur).
  - 🟠 **`inconclusive` n'envoie jamais de feedback** → cas « presque bon » jamais appris.
- **Track-record par signal** (`signal_track_record.py`)
  - 🔴 **Aucune spec d'horizon `micro`** → même en corrigeant le 400, rien à mesurer (ADR-034 **impossible** en l'état).
  - 🟡 Cache adaptatif (Bug 12 fixé) ; reste un edge case si 1ʳᵉ ligne = `données_manquantes`.
  - 🟡 Klines REST non cachées + pas de batch → risque 503 si beaucoup de favoris ouverts.
- **Hit-rate vs baseline** (`hit_rate.py`)
  - 🟠 **`n_skipped` opaque** : agrège « prix manquant » + « pas assez vieux ». La trader voit `23/100` sans savoir combien sont juste **trop jeunes**.
  - 🟠 Pas de détection de **biais de distribution** (29 long / 1 short en marché haussier → 60 % flatteur).
  - 🟡 `beats_baseline=false` forcé si N<30 (conservateur mais peu communicant).
- **Hit-rate par veracity** (`metrics.py:337-495`)
  - 🟠 **Petits buckets non avertis** : bucket 0.95+ avec N=2 affiche **100 %** sans `sample_warning` → **fausse confiance** (anti-Axe #1).
- **Source health** (`source_health.py`)
  - 🟠 Reddit/CryptoCompare/GDELT sont `non-critical` → **pas d'alerte** « ton BTC swing tourne à 2/4 overlays ». Vu comme `stale/missing` sans conséquence affichée.
  - 🟠 FRED/macro **non monitoré** (pas de `fetched_at`) → un crash FRED = stale silencieux.

### 2.4 DASHBOARD (ce que la trader voit)

- ✅ **21 cartes cosmiques** : Contrat des 4 états respecté (`UnavailableState`/`humanizeError`), âges temps réel (livrés cette session).
- ✅ **Hooks** : aucun `catch → []/null` muet trouvé (contrairement aux craintes).
- 🟡 **2 cartes legacy montées** (onglet Plus) affichent l'erreur brute : `StatsLLMCard`
  (`stats-llm-card.tsx:42`) + `HitRateByVeracityCard` (`hit-rate-by-veracity-card.tsx`).
- ⚪ **~9 cartes legacy = code mort** (non importées) → à supprimer (ménage, pas un bug).
- 🟡 `cosmic-source-health.tsx` : texte brut « Santé indisponible » (pas `UnavailableState`) — cohérent mais à uniformiser.

---

## 3. Les fails classés par gravité RÉELLE (après vérification)

### 🔴 Vrais problèmes (dégradent le signal OU trompent la trader)
1. **BTC swing à 2/4 overlays** (Reddit + CryptoCompare HS) → 0 short, LONG « achète-la-peur » trompeurs. *Réversible : CryptoCompare ~1/7, Reddit = incertain.*
2. **Seuils dispersion mal calibrés en régime extrême** → tous les shorts `tripped`. *Recalibrer post-régime sur données réelles.*
3. **Micro non-suivable** (400 + pas de spec) → ADR-034 (verdict edge) **bloqué**.
4. **Petits buckets veracity à 100 % sans avertissement** → fausse confiance (anti-Axe #1).

### 🟠 Silencieux / observabilité (la panne existe mais invisible)
5. Cycle d'émission perdu en silence (fetch fail → log only, pas d'alerte UI).
6. `n_skipped` du hit-rate opaque (jeune vs prix manquant).
7. `source_health` ne crie pas « 2 overlays down » ; FRED non monitoré.
8. `inconclusive` jamais remonté ; Redis publish post-commit non protégé.
9. `antifakenews_mode` non validé (typo → désactivation muette).

### 🟡 Dette / cosmétique
10. 2 cartes legacy (Plus) en erreur brute ; ~9 cartes legacy mortes à supprimer.
11. `pstdev`/`stdev` à harmoniser ; attribution crédibilité grossière ; débounce flash ; mode shadow auto-log.

---

## 4. « Pour une appli fiable avec une majorité de bons signaux bien suivis »

> **Vérité à ne pas maquiller (Axe #1)** : aucun correctif de code ne *fabrique* un edge.
> Le NO-GO du 27/05 tient : les sources actuelles sont du **sentiment retardé**. Une
> « majorité de bons signaux » directionnels ne viendra **pas** de réparer le sentiment,
> mais **seulement** de mesurer les familles **non-sentiment** déjà en shadow. Le reste du
> plan rend l'appli **fiable et honnête** (contexte/discipline/suivi de confiance).

### Bloc A — Fiabilité immédiate (faible risque, fort rendement honnêteté)
- A1. **Avertir les petits buckets de veracity** (N<10 → `sample_warning`). *Anti-fausse-confiance.*
- A2. **Désopacifier `n_skipped`** : séparer « trop jeune » / « prix manquant » dans la réponse + l'UI.
- A3. **Valider `antifakenews_mode`** (whitelist + `.lower()`).
- A4. **Surfacer « BTC swing à N/4 overlays »** dans `source_health` + une bannière dashboard.
- A5. Envelopper le **Redis publish** du publisher (try/except → log, DB déjà OK).

### Bloc B — Suivi fiable (« bien suivis »)
- B1. **Débloquer le micro** : soit refuser proprement le favori micro côté UI (message clair), soit ajouter une spec d'horizon micro **pour mesurer en shadow** → condition *sine qua non* d'**ADR-034**.
- B2. **Remonter les `inconclusive`** (au moins en comptage) pour ne pas biaiser la calibration.
- B3. **Re-confirmer la suite de tests** sur le VPS (`pytest` contre `tik_test`).

### Bloc C — La seule voie vers « une majorité de bons signaux » (edge)
- C1. **Mesurer les shadows non-sentiment ≥ 2 sem** vs Always-SHORT apparié : **Polymarket**, **dérivés Binance**, **ETF flows**, **micro** → c'est le **cœur** de la demande. Verdict = **ADR-034**.
- C2. Si concluant : enrôler via le pattern overlay ADR-004. Si non concluant (Polymarket **et** dérivés) : déclencher le **reframe UX honnête** (Axe #1).
- C3. **Recalibrer les seuils dispersion** sur données multi-régime (dès que FG sort de la peur extrême).

### Bloc D — Ménage / dette
- D1. Migrer les 2 cartes legacy de l'onglet Plus vers `UnavailableState` (1 h).
- D2. Supprimer les ~9 cartes legacy mortes + routes orphelines (`bots`, `modal`, `signal/[id]`).
- D3. Harmoniser `pstdev` ; auto-log shadow LLM ; débounce flash.

### Ce qu'il NE faut PAS faire (garde-fous)
- ❌ Ne **pas** « remonter » la veracity 0.70 pour faire joli (veracity ≠ edge).
- ❌ Ne **pas** enrôler une source non mesurée (ni CoinGecko, ni un shadow) « pour combler ».
- ❌ Ne **pas** lire les LONG « FG achète-la-peur » actuels comme des signaux d'achat.

---

## 5. Passe « vrais signaux » (à faire tourner sur le VPS)

À lancer en SSH sur `204.168.220.47` (clé de **lecture**), résultats à me coller :

```bash
# Santé des sources (qui est down / stale)
curl -s -H "Authorization: Bearer <CLE_LECTURE>" http://localhost:8200/api/v1/metrics/source_health | python3 -m json.tool
# Hit-rate BTC swing 30j (+ baseline)
curl -s -H "Authorization: Bearer <CLE_LECTURE>" "http://localhost:8200/api/v1/metrics/hit_rate?entity_id=BTC&horizon=swing" | python3 -m json.tool
# Hit-rate par veracity (voir les petits buckets)
curl -s -H "Authorization: Bearer <CLE_LECTURE>" "http://localhost:8200/api/v1/metrics/hit_rate_by_veracity?entity_id=BTC&horizon=swing" | python3 -m json.tool
```
(Chemins à confirmer via `GET /docs` si un renvoie 404.)

---

*Limites connues de cet audit (3-4) : (1) verdicts de sévérité fondés sur le code + la
doc, pas sur les données live — la passe §5 les ancrera ; (2) certaines mesures CLAUDE.md
datent (régime FG peut avoir changé) ; (3) la suite de tests n'a pas été re-jouée ;
(4) l'edge éventuel reste **non mesuré** — tout le bloc C est conditionnel.*
