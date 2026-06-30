# Plan — Fusion micro (labo `btc-research-lab`) × Tik : shadow, mesure, breakout

> Rédigé 2026-06-24. Ancré sur le **code réel** des deux dépôts (vérifié), pas sur la doc.
> Consigne : doute méthodique continu, sans complaisance, tout en SHADOW, mesurer avant de croire.

## Cadre honnête (à relire avant chaque étape)
- **Labo : H1 RÉFUTÉE** (le modèle ML fait ~51 % = pile/face, net −100 % après frais ; une bête stratégie de *retour à la moyenne* le bat). **Tik : NO-GO directionnel.** → **Aucun edge prouvé** d'aucun côté.
- La fusion **ne crée pas d'edge par magie** (écrit dans `FUSION.md`). Ce plan = **mesurer rigoureusement**, pas « brancher un edge ».
- **Règle d'or** : ≥ 2 semaines en shadow + comparaison **vs baselines** (retour-à-la-moyenne, buy-hold, frais réels, fenêtres non chevauchantes) **AVANT** tout enrôlement. Rien ne touche direction/veracity/`combined_bias` avant le verdict (futur **ADR-034**).

## Séquencement global (les 3 directions s'imbriquent)
- **Phase 0** — Vérifier l'état réel sur le VPS *(je ne peux pas le faire moi-même)*. **[bloquant]**
- **Phase 1 = Direction (a)** — Activer le shadow + brancher la mesure → **démarre le chrono des 2 semaines**.
- **Phase 2 = Direction (b)** — **En parallèle** des 2 semaines : prototyper la détection volatilité/breakout dans le labo + backtester.
- **Phase 3 = Direction (c)** — Deep-dives ciblés au fil de l'eau (comprendre les briques).
- **Phase 4** — Verdict **ADR-034** (micro + breakout) → enrôler ou rester contexte.

---

## PHASE 0 — Vérifications préalables (ce que JE n'ai PAS pu vérifier)
Commandes SSH **lecture seule** à coller sur le VPS (résultat → je décide la suite) :
- `0.1` Conteneur micro vivant ? `docker ps | grep micro`
- `0.2` Inerte ou actif ? `docker exec tik-micro env | grep -E "TIK_MICRO|TIK_API"` → voir `TIK_MICRO_ENABLED`, `TIK_API_URL`, `TIK_API_KEY` présents/absents.
- `0.3` Des signaux micro déjà en base ? `curl -s -H "Authorization: Bearer <clé>" "http://localhost:8200/api/v1/signals/latest?horizon=micro" | head`
- `0.4` Le pont poste-t-il ? `docker logs --tail 80 tik-micro | grep -i "tik_bridge\|ingest\|désactivé"`
- `0.5` Le core déployé (dépôt `Lolasiku-prog`) a-t-il bien l'endpoint ? `docker exec tik-core python -c "import tik_core.api.signals as s; print(hasattr(s,'ingest_micro_signal'))"`
→ **Si inerte** → Phase 1 = activer. **Si déjà actif** → Phase 1 = juste vérifier + brancher la mesure.

---

## DIRECTION (a) — Activer le shadow + MESURER  *(colonne vertébrale)*

**Objectif** : le labo produit des signaux `micro` visibles dans Tik, **sans influence**, et on monte le dispositif de mesure pour trancher dans 2 semaines.

**Actions (ordonnées, commandes vérifiées dans le code) :**
- `A1` [VPS/core] Créer une clé API avec le scope `write:signals` :
  `docker exec tik-core python -m tik_core.scripts.create_api_key --client micro --name "Micro bridge" --scopes write:signals`
  → **copier la clé affichée** (montrée une seule fois).
- `A2` [VPS/micro] Renseigner le `.env` du conteneur micro :
  `TIK_MICRO_ENABLED=1`, `TIK_API_KEY=<clé A1>`, `TIK_API_URL=http://host.docker.internal:8200` *(ou `http://core:8200` si micro et core partagent le même réseau Docker — à confirmer en Phase 0)*, `TIK_MICRO_INTERVAL_S=300`.
- `A3` [VPS] Recréer le conteneur : `docker compose -f docker-compose.micro.yml up -d --force-recreate micro`.
- `A4` [VPS] Vérifier le pont : logs = POST 200 vers Tik ; en base, signaux `horizon=micro` + `circuit_breaker=degraded` ; dans l'app, filtre **« Micro »** non vide.
- `A5` [Tik] Écrire `core/src/tik_core/scripts/measure_micro.py` **calqué sur** `measure_btc_derivatives.py` + `measure_calibration.py` (vérifiés présents) : pour chaque signal micro, récupérer le prix réel ultérieur → **hit rate par horizon**, **calibration de l'amplitude** (q50 prédit vs réalisé), et **comparaison vs baselines** : *retour-à-la-moyenne* (la baseline qui a gagné au labo), *always-flat*, *buy-hold* — fenêtres **non chevauchantes**, **frais réels**.
- `A6` [process] Laisser tourner **≥ 2 semaines**, snapshot hebdo.
- `A7` [verdict] **ADR-034** : enrôler **seulement si** ça bat les baselines de façon significative (intervalle de confiance ne croisant pas 0, après frais). Sinon → rester contexte/shadow, **l'écrire honnêtement**.

**Définition de « fini »** : signaux micro live en shadow + script de mesure reproductible + 1er snapshot.

**Pour** : démarre le chrono ; **risque ~nul** (shadow strict) ; réutilise l'outillage existant ; honnête.
**Contre** : 2 semaines d'attente ; le labo est **long-only** (jamais de short) → mesure **biaisée** en marché baissier (à neutraliser dans l'analyse) ; H1 réfutée → probable non-edge (mais il **faut** le mesurer, pas le présumer).

**Risques** : clé mal scoptée ; `host.docker.internal` indisponible selon le réseau Docker → fallback IP/`core:8200` ; DB micro qui gonfle.

---

## DIRECTION (b) — Prototyper la détection volatilité/breakout  *(recherche, en parallèle)*

**Objectif** : tester si une **compression de volatilité** prédit une **expansion** (= le **TIMING** d'un breakout), proprement, **sans toucher la direction**.

**Constat vérifié** : aucun détecteur de breakout n'existe (ATR & Bollinger ne sont que des features ; régime vol figé en 3 niveaux, **pas de détection de transition**).

**Actions :**
- `B1` [labo] Dans `features.py::make_features` (ligne 40) ajouter des features de **transition de vol** : ratio `ATR(14)/ATR(50)`, **largeur Bollinger vs sa moyenne 100 barres** (squeeze), `realized_vol(t)/realized_vol(t-20)`, compteur de barres en range serré. Les exposer via `feature_columns` (ligne 270).
- `B2` [labo] **Pré-déclarer** la cible et l'hypothèse (anti-data-mining) : *« H-vol : quand la largeur de Bollinger est dans son décile bas, la volatilité réalisée des N barres suivantes est dans son décile haut, mieux que le hasard. »* **Cible = TIMING** (amplitude future), **PAS** direction.
- `B3` [labo] Backtester **hors-échantillon** avec le harnais existant (vérifiés : `backtest_costed.py`, `red_team_baselines.py`, `forward_test.py`) : walk-forward, vs baseline aléatoire + persistance de vol ; **red-team** (permutation, placebo) pour écarter le hasard.
- `B4` [labo] Si le timing tient : l'exposer comme **CONTEXTE** (champ `vol_expansion_expected` dans `market_snapshot`/`advisory`), **jamais** comme direction.
- `B5` [Tik, optionnel] Le remonter comme **alerte/contexte** (modèle breaking-news ADR-027), pas comme overlay directionnel.

**Définition de « fini »** : un rapport mesuré « le timing de breakout est prédictible OUI/NON sur nos données » + features versionnées.

**Pour** : vise la partie **mesurable** (timing) plutôt que la direction (où tout a échoué) ; colle au rôle contexte/discipline de Tik ; le labo a déjà la discipline de mesure.
**Contre** : **risque de data-mining** (beaucoup de features → faux positifs) → d'où l'hypothèse pré-déclarée + red-team ; la vol peut être prévisible mais **inexploitable après frais** ; la donnée micro testée favorisait le **retour-à-la-moyenne** (anti-breakout) → prudence sur l'échelle choisie.

**Risques** : sur-ajustement ; confondre « la vol monte » avec « edge tradable » ; *window-shopping* (le labo lui-même prévient que choisir la fenêtre est un piège).

---

## DIRECTION (c) — Comprendre en profondeur  *(au fil de l'eau, modulaire)*

**Objectif** : que tu (et moi) maîtrisions les briques pour décider en connaissance — et **ne pas réapprendre les pièges déjà documentés**.

**Actions (à la demande, chacune = résumé FR simple + schéma + fichier:ligne) :**
- `C1` `signal_runner.py` + `long_signal.py` → comment un verdict `GO_LONG` est décidé (les 6 portes).
- `C2` `predictor.py` + `calibrators.py` → pourquoi 51 % et pourquoi la calibration compte.
- `C3` `RESEARCH.md` en entier → la généalogie des réfutations (H1, le « fluke » du 4h) = les leçons.
- `C4` `tik_bridge.py` → exactement ce qui part vers Tik (payload, gating, shadow).

**Pour** : évite de retomber dans les pièges ; te rend autonome.
**Contre** : du temps, pas d'output « produit » direct (mais réduit le risque de mauvaises décisions).

---

## Nouvelles questions (avant de lancer)
1. Le conteneur micro est-il déjà actif (`TIK_MICRO_ENABLED=1`) ? *(Phase 0 le dira.)*
2. La mesure compare le micro à un **retour-à-la-moyenne** (la baseline qui a gagné au labo) en plus de buy-hold ? *(Je recommande oui.)*
3. Breakout : on vise **uniquement le TIMING** (contexte), confirmé ? *(Je déconseille fortement de viser la direction.)*
4. Côté labo, on développe sur une **branche mesurée offline** (recommandé) ou directement sur le VPS (hot, risqué) ?

## Ce que je n'ai PAS vérifié (transparence)
- L'**état réel du conteneur micro** sur le VPS (actif/inerte) → Phase 0.
- Que le **core déployé** (`Lolasiku-prog`) a bien l'endpoint `/signals/ingest` (mon code `escltheo` l'a ; les 2 dépôts ont **divergé** sur le core → à confirmer, Phase 0.5).
- Que `host.docker.internal` fonctionne depuis le conteneur micro **sur ce VPS précis**.
- La **vol-clustering sur VOS données** : hypothèse, **non mesurée** (c'est tout l'objet de B3).
- Les flags exacts de `create_api_key.py` au-delà de `--client/--name/--scopes` (lus dans le code, mais non exécutés ici).
