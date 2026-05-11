# ADR-019 — Politique d'ajustement `SOURCE_SCORES` post-P1+P2 (no-op manuel + surveillance auto-cal)

- **Statut** : Accepté
- **Date** : 2026-05-11

## Contexte

Le plan stratégique post-audit fiabilité signaux (CLAUDE.md Paquet 18, révision 2026-05-06) liste 9 priorités P1-P9 dont **P4 — étape 9 ajustements `SOURCE_SCORES` selon mesures cumulées P1+P2 — re-pondération chiffrée du multi-overlay** (~30 min, après P1+P2).

Au 2026-05-11, l'état du plan est :

- ✅ **P1 livré 2026-05-07** (Paquet 19) — re-run golden dataset 5j sur les 100 items annotés (Paquet 4 Session 4). Hit rate par source mesuré (Ollama) : CryptoCompare 47.1 % (n=17), Google News 38.8 % (n=67), Reddit 25.0 % (n=16). Random baseline 32.5 %. Always_bull = 100 % sur la fenêtre (période strongly bullish).
- ✅ **P2 livré 2026-05-07** (Paquet 19) — backtest 12m sources numériques : FG IC -0.10 (marginalement contrarian, 46.9 % cas extrêmes), GDELT 0 point évaluable (rate-limit), DXY IC +0.23 (inversé), COT IC +0.43 (inversé).
- ✅ **P2 amendement** : désactivation overlays GOLD DXY+COT via toggle `TIK_GOLD_DXY_COT_OVERLAYS_ENABLED=false`. Réversible post-J+30 sur période bear.
- 🟡 **P4 partiellement traité** (DXY+COT désactivés). Reste : FG, GDELT, sources textuelles (CryptoCompare, Google News, Reddit), sources flash (orderbook, aggtrades).

Cet ADR examine ce qu'il **reste à faire** pour P4. Verdict spoiler : **rien manuellement**. Cet ADR documente pourquoi.

### Rappel du mécanisme de scoring source actuel

Tik dispose de **deux couches** pour le scoring de crédibilité source :

**Couche 1 — fallback statique** (`SOURCE_SCORES` dans `core/src/tik_core/scoring/swing_engine.py` et `FLASH_SOURCE_SCORES` dans `flash_engine.py`). Valeurs hardcodées Paquet 1.x et enrichies aux Paquets 4 Sessions 1-3. Utilisées au boot et en cas de miss Redis.

**Couche 2 — auto-calibration ADR-011** (Paquet 5, livré 2026-05-03). Job APScheduler `recalibrate_sources` daily 03:00 UTC dans `run_scheduler.py` :

- Lit les **signaux réels** des `LOOKBACK_DAYS=30` derniers jours en DB
- Calcule hit rate par source pour `HORIZON_DAYS=5`, `THRESHOLD_PCT=0.5`
- Algorithme asymétrique (paranoïa contrôlée — pénalité plus rapide que récompense) :
  - hit rate `< 40 %` sur `≥ 30 samples` → score `÷ 1.2` (penalty)
  - `40 % ≤ hit rate ≤ 70 %` → inchangé
  - hit rate `> 70 %` sur `≥ 30 samples` → score `× 1.1` (reward)
  - `< 30 samples` → inchangé (statistique trop faible)
- Cap final `[0.30, 0.95]`
- Stockage Redis (`tik.source_credibility.<source>`, TTL 8 j) + Postgres (`source_credibility_history`, 1 row par cycle pour audit)

`RECALIBRATABLE_SOURCES` (frozenset, `source_credibility.py:74`) =
`alternative_me_fng, cryptocompare_news, google_news_rss, reddit_btc, gdelt_news, fred_dtwexbgs, cftc_cot, binance_orderbook, binance_aggtrades`. Les sources de prix (`binance_klines`, `yahoo_finance`, `binance_klines_1m`) sont **exclues** volontairement de l'auto-cal.

### Tableau de référence — état actuel des sources

| Source | Score statique fallback | Mesure P1 golden 5j | Mesure P2 12m | Si même hit rate en prod : auto-cal trigger ? |
|---|---:|---|---|---|
| `alternative_me_fng` (FG, BTC) | 0.65 | n/a | 46.9 % cas extrêmes (n=140 sur 365j) | **unchanged** (dans 40-70 %) |
| `cryptocompare_news` (BTC) | 0.70 | 47.1 % (n=17) | n/a | **unchanged** (dans 40-70 %, et n<30) |
| `google_news_rss` (BTC + GOLD) | 0.70 | 38.8 % (n=67) | n/a | **penalty potentielle** si même hit rate en prod (n>30, hit rate<40 %) |
| `reddit_btc` | 0.65 | 25.0 % (n=16) | n/a | n<30 → **unchanged** ; si en prod n≥30 et taux similaire → **penalty** |
| `gdelt_news` (GOLD) | 0.75 | n/a | **0 point évaluable** (rate-limit GDELT 12m) | impossible à mesurer |
| `fred_dtwexbgs` (DXY, GOLD) | 0.85 | n/a | IC +0.23 (inversé) | **désactivé** via P2 amendement ADR-018 |
| `cftc_cot` (GOLD) | 0.80 | n/a | IC +0.43 (inversé) | **désactivé** via P2 amendement ADR-018 |
| `binance_orderbook` (flash BTC) | 0.85 | n/a | n/a | dépend signaux flash réels en prod |
| `binance_aggtrades` (flash BTC) | 0.85 | n/a | n/a | dépend signaux flash réels en prod |

### Observation critique méthodologique

**Le golden dataset (P1) et le backtest 12m (P2) ne nourrissent PAS automatiquement l'auto-cal.** L'auto-cal lit les **signaux réels présents en DB**, pas les datasets de calibration historique. Conclusion : les hit rates mesurés dans P1/P2 sont des **observations exploratoires** — ils n'agissent pas tout seuls sur les scores live. Tout ajustement basé sur P1/P2 serait nécessairement **manuel**.

## Décision

**P4 ne fera l'objet d'aucun ajustement manuel des `SOURCE_SCORES` au 2026-05-11.** L'auto-cal ADR-011 est laissée à son régime normal.

### 1. Justification

**a. P1 a un échantillon fragile** :
- 100 items annotés à la main sur **1 seul cycle** de marché (mai 2026, strongly bullish, `always_bull = 100 %`).
- Samples par source : n=17 / 67 / 16. CryptoCompare et Reddit sont **sous le seuil 30 de l'auto-cal** — l'auto-cal ne les ajusterait même pas avec ces données.
- Annotateur unique (l'utilisatrice elle-même, débutante en trading) → biais possible vers `neutral` (56 % d'annotations neutrales). Ce biais n'invalide pas l'annotation mais limite la généralisation.

**b. P2 a un sous-ensemble structurellement non-utilisable** :
- GDELT : 0 point évaluable (rate-limit). Impossible de mesurer.
- DXY + COT : déjà désactivés via P2 amendement.
- FG : mesure faite, dans la zone 40-70 % de l'auto-cal → unchanged.

**c. L'auto-cal converge naturellement vers les bonnes valeurs** :
- Dès que Tik tournera de nouveau (cloud, nouveau Mac, etc.) et accumulera ≥30 samples par source, l'auto-cal commencera à pénaliser ou récompenser selon les hit rates **réels** (signaux Tik vs marché).
- C'est strictement plus fiable que l'ajustement manuel sur golden 100 items période bullish.

**d. Risque d'ajustement manuel prématuré** : si on baisse `google_news_rss` de 0.70 à 0.55 (penalty 38.8 %) sur la base de P1, et qu'en réalité Google News performe correctement (≥40 %) sur signaux réels, on aura **biaisé le point de départ de l'auto-cal**. L'auto-cal pourra remonter le score mais avec un délai et à partir d'une base faussée.

### 2. Décision opérationnelle

**Aujourd'hui** (2026-05-11) :
- Aucune modification de `SOURCE_SCORES` ou `FLASH_SOURCE_SCORES` dans le code.
- Aucune modification de Redis (`tik.source_credibility.*`).
- DXY + COT restent désactivés via toggle settings (P2 amendement déjà appliqué).
- Cet ADR documente la décision pour mémoire.

**Plus tard** (post-J+30 minimum) :
- Quand Tik aura tourné en continu ≥30 jours après le retour en service (cloud, nouveau Mac, ou autre setup) :
  1. Query la table `source_credibility_history` (cf. `core/src/tik_core/storage/models.py`, modèle `SourceCredibilityHistory` créé Paquet 5).
  2. Identifier les sources qui ont divergé significativement vs le statique fallback.
  3. Comparer aux mesures golden (P1) et backtest (P2) pour cohérence.
  4. **Re-ouvrir cet ADR** (ou en créer un successeur ADR-020+) si action manuelle justifiée.

### 3. Critères de réouverture explicites

**Cet ADR est à reconsidérer SI et SEULEMENT SI** au moins un des trois critères suivants est rempli :

**C1 — Non-convergence auto-cal sur ≥60 jours runtime** :
- Une source `RECALIBRATABLE` montre un comportement instable (oscillation entre penalty et reward, ou stagnation à un score extrême) **sur ≥60 jours** de runtime continu post-retour en service.
- Symptôme observable : `source_credibility_history` montre des changements de score erratiques pour cette source sans tendance claire.
- Action : audit manuel des biais sortis par cette source, hypothèse sur la cause (changement de régime ? bug ingester ? dérive sémantique ?), ajustement raisonné ou désactivation temporaire.

**C2 — Source persistante < 30 % de hit rate** :
- Une source `RECALIBRATABLE` reste sous 30 % de hit rate (donc bien pire que random) **sur ≥60 jours** et **≥100 samples**.
- Symptôme : `source_credibility_history.hit_rate < 0.30` répété + `source_credibility_history.samples ≥ 100`.
- Action : **désactivation envisagée** (comme DXY + COT via P2 amendement). Nouveau toggle dans `config.py`, wrap dans `analyze_swing_xxx` / `analyze_flash_xxx`.

**C3 — Golden dataset étendu disponible** :
- Le dataset golden a été étendu à ≥200 items annotés sur ≥2 régimes de marché (bull + bear, ou bull + range) → P1 v2 livrable.
- ET les conclusions P1 v2 confirment ou infirment celles de P1 sur ≥1 source.
- Action : éventuelle re-calibration manuelle conservatrice basée sur P1 v2, en complément de l'auto-cal qui continue son boulot.

### 4. Surveillance post-retour en service

Quand Tik tournera de nouveau, **monitorer** :

- Logs scheduler : `scheduler.recalibrate_sources.*` à chaque cycle 03:00 UTC. Compter les penalties / rewards / unchanged.
- Table `source_credibility_history` (Postgres). Query manuelle (ou nouveau endpoint future si nécessaire) pour visualiser la dérive par source.
- Redis : valeurs courantes via `redis-cli KEYS "tik.source_credibility.*"` puis `GET`.
- Carte dashboard à terme (post-J+14) : visualisation graphique de la dérive des scores par source au fil du temps. Non livrée dans cet ADR — backlog futur.

## Conséquences

### Positives

- **Zéro risque** d'ajustement manuel basé sur des données fragiles (P1 = 1 cycle bullish, P2 = sous-ensembles non décisifs).
- **Auto-cal préservée** dans son régime normal — convergence naturelle vers les bonnes valeurs.
- **Décision documentée** pour mémoire future : si une instance Claude (ou l'utilisatrice elle-même) se demande dans 2 mois pourquoi P4 n'a pas été appliqué manuellement, cet ADR a la réponse.
- **Cohérence paranoïa contrôlée** : on n'agit que sur données solides, on accepte l'ignorance temporaire.

### Négatives

- **Aucune réponse chiffrée immédiate** à P4. Le tableau plan stratégique reste 🟡 partiel sur P4 (DXY+COT désactivés mais reste textuelles + FG + GDELT non ajustés). C'est une absence d'action, pas une livraison technique.
- **Effort intellectuel non capitalisé directement** : on a mesuré P1 et P2 mais on n'agit pas sur les chiffres. Les mesures restent utiles pour la **comparaison future** post-J+30, donc pas inutiles, juste pas immédiatement actionnables.
- **Dépendance forte à l'auto-cal** : si l'auto-cal a un bug latent (pas découvert au Paquet 5, par exemple un cas limite sur le calcul du hit rate par source), cet ADR repose sur une garantie non vérifiée. Mitigation : surveiller les premiers cycles post-retour en service.

## Risques

### R1 — L'auto-cal ne fonctionne pas comme attendu post-retour en service

**Probabilité** : faible. L'auto-cal a 71 tests pytest (Paquet 5) couvrant les edge cases (asymétrie, fallback, context-var, cap min/max). Mais elle n'a pas tourné en continu ≥30 jours en prod (Tik a tourné par intermittence depuis 2026-05-03).
**Impact** : moyen. Si l'auto-cal ne converge pas, on revient à cet ADR pour critère C1.
**Mitigation** : surveiller `source_credibility_history` pendant les 30 premiers jours post-retour. Si comportement anormal → audit du code de `recalibrate_sources_job` dans `run_scheduler.py`.

### R2 — Le contexte de marché change (bull → bear → range) pendant la période d'observation post-retour

**Probabilité** : moyenne. Mai 2026 a été strongly bullish, juin-juillet peuvent être différents.
**Impact** : neutre voire positif. Un changement de régime **est** ce qu'on veut pour calibrer correctement. Si une source qui marchait en bull ne marche plus en bear, l'auto-cal la pénalisera, ce qui est le comportement souhaité.
**Mitigation** : aucune nécessaire.

### R3 — Tik ne retourne pas en service avant J+14

**Probabilité** : élevée. Au 2026-05-11, Tik backend ne tourne nulle part (Mac en panne, Windows HP sans Docker). Décision runtime (cloud, nouveau Mac, autre) pas encore prise. J+14 dans 3 jours.
**Impact** : élevé sur le plan trading manuel J+14. **Pas d'impact direct sur cet ADR** — l'auto-cal ne peut juste pas tourner sans Tik en service.
**Mitigation** : cet ADR est indépendant de la décision runtime J+14. Quand Tik retournera en service (peu importe quand), cet ADR s'applique tel quel.

## Garde-fous opérationnels

- **Garde-fou 1** (Tik shadow vs Zeta 3 mois) : inchangé. Cet ADR ne touche pas la connexion Zeta.
- **Garde-fou 2-bis** (sizing 1 % capital, veracity ≥ 0.90 sur swing, discipline macro ±4 h) : inchangé. Cet ADR ne change pas la logique de scoring qui produit `veracity`.
- **ADR-003** (pas de bypass V01-V15) : inchangé. Aucune nouvelle voie d'exécution.
- **ADR-004** (multi-overlay) : inchangé. Le pipeline reste tel quel.
- **ADR-011** (anti fake-news + scoring source dynamique) : **renforcé** indirectement — cet ADR valide la confiance dans l'auto-cal d'ADR-011 comme mécanisme principal d'ajustement des `SOURCE_SCORES`.
- **ADR-018** (Tik OSINT pur) : inchangé. Cet ADR ne touche pas la dérivation direction → `combined_bias`.

## Mémoire pour instances Claude futures

**Si une future session te suggère « il faut faire P4 ajustements `SOURCE_SCORES` manuellement »** :

1. **Lire cet ADR** d'abord. La décision est documentée et raisonnée.
2. **Vérifier les critères C1/C2/C3** de réouverture (section 3). Si aucun n'est rempli, **ne pas faire P4 manuellement**.
3. **Vérifier l'état runtime** de l'auto-cal :
   - Tik tourne-t-il depuis ≥30 jours en continu ?
   - Query `source_credibility_history` — y a-t-il des entries pour chaque source ?
   - Combien de cycles de recalibration ont eu lieu ?
4. **Si critères de réouverture remplis** : créer un ADR successeur (ADR-020 ou +) qui s'appuie sur les nouvelles données. Ne pas modifier celui-ci (préserver l'historique de décision).

**Si une future session te dit que « l'auto-cal est cassée »** :

1. Vérifier les logs `scheduler.recalibrate_sources.*`.
2. Lire `core/src/tik_core/scoring/source_credibility.py` et les tests `core/tests/test_source_credibility.py` (32 tests Paquet 5).
3. **Avant de modifier** les valeurs statiques `SOURCE_SCORES` ou Redis, fixer l'auto-cal si elle est cassée.

**Convention** : ne jamais modifier `SOURCE_SCORES` ou `FLASH_SOURCE_SCORES` (statiques fallbacks) sans :
- (a) une mesure empirique sur ≥30 samples par source ET multi-régime, OU
- (b) un constat de bug runtime de l'auto-cal documenté dans cet ADR ou son successeur.
