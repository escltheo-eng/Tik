# ADR-034 — Connexion micro : labo btc-research-lab → Tik (shadow, mesurée)

- **Statut** : ACCEPTÉ (décision utilisatrice 2026-07-02 : « finir la chaîne »)
- **Date** : 2026-07-02
- **Contexte amont** : ADR-030 (fusion macro+micro, chemin F2), audit E2E micro 2026-07-02
- **Numérotation** : 032/033 sont VOLONTAIREMENT sautés — la branche `refonte-cosmique`
  les utilise déjà (030=risk-regime, 031=stablecoins, 032=cross-asset, 033=fusion
  macro+micro = notre 030). 034 est libre des deux côtés. Réconciliation des numéros
  à faire au merge des branches (obstacle O16 du plan).

---

## 1. Problème

L'audit E2E du 2026-07-02 a montré que la chaîne micro (ADR-030) était une coquille :
UI et endpoint prêts, mais **producteur absent (labo : 0 ligne de code Tik)**, sous-système
de mesure qui rejette l'horizon micro (track record → 400, hit rate → 422), **aucun
kill-switch**, et pièges UI (fausses alertes, tuile héro). Décision utilisatrice : finir
la chaîne **en connaissant les pièges**, avec un contrat défini et une checklist d'obstacles.

## 2. Décision

Le détail opérationnel (contrat champ par champ, checklist d'obstacles O1-O20, procédure
de mise en service) vit dans [`docs/plan-connexion-micro.md`](../plan-connexion-micro.md).
Points structurants :

1. **Producteur** : `tik_adapter.py` dans le labo + boucle `tik_push_loop` (60 s) dans
   `dashboard.py`. Stdlib uniquement (urllib), best-effort (le labo ne meurt jamais à
   cause de Tik), **OFF par défaut** (`TIK_INGEST_ENABLED`).
2. **Mapping honnête, long-only** : `GO_LONG→long`, `WAIT/NO_GO→neutral`, jamais `short` ;
   modèle pas prêt (aucune proba) → **rien n'est envoyé**. Verdict brut conservé dans
   `advisory.lab_verdict`. Confidence catégorielle → scalaire conservateur ; veracity
   non envoyée (défaut serveur 0.70).
3. **Anti-flood** : émission sur transition de verdict + heartbeat 30 min (pattern
   flash ADR-005). Un seul horizon labo poussé (`TIK_INGEST_HORIZON`, défaut 1h).
4. **Serveur** : kill-switch `TIK_MICRO_INGEST_ENABLED` (défaut **False**, conforme
   ADR-030 Étape 2) → 503 ; whitelist `TIK_MICRO_ALLOWED_ENTITIES` (défaut BTC) → 422
   propre au lieu d'un 500 FK.
5. **Mesure enfin possible** : fenêtres micro ajoutées partout — hit rate 2h (seuil
   0.4 % ≈ 0.3 × √2), track record 15min/30min/1h/2h (klines 15m, tolérance 30 min),
   alignées sur l'expiry 2h du publisher. `/signal_freshness` **exclut** micro (un flux
   externe ne doit pas masquer une panne des moteurs internes).
6. **UI (`main`)** : micro exclu des déclencheurs d'alertes fake-news ET veracity_collapse,
   ne peut plus être la tuile « dernier signal », fenêtre watchlist 2h, type `Horizon`
   complété. Deux correctifs restent à porter sur `refonte-cosmique` (plan §6).

## 3. Alternatives rejetées

| Option | Verdict | Pourquoi |
|---|---|---|
| `NO_GO→short` (récupérer les prédictions baissières) | ❌ | Le labo ne shorte pas by-design ; un NO_GO mélange « baisse prédite » et « données manquantes » — perte d'info garantie |
| Pousser les 6 horizons labo | ❌ | Flood DB/UI ; commencer par 1, élargir après mesure si apport |
| Fabriquer une veracity depuis la calibration | ❌ | Vernis de certitude (Axe #1) ; défaut conservateur 0.70 |
| requests/httpx côté labo | ❌ | Nouvelle dépendance pour 1 POST/30 min ; urllib suffit |
| Toggle serveur ON par défaut | ❌ | ADR-030 Étape 2 dit explicitement défaut False |
| Special-caser `degraded` pour inclure micro dans le hit rate par défaut | ❌ (différé) | Changerait la sémantique du flag pour tous ; le paramètre `include_flagged=true` suffit à mesurer (piège documenté O8 + test) |

## 4. Garde-fous rappelés

- **Shadow strict** : `horizon='micro'` + `circuit_breaker_status='degraded'` forcés
  serveur ; ne touche JAMAIS `combined_bias` ; NO-GO directionnel intact.
- **Mesure ≥ 2 semaines** (fenêtres non chevauchantes, apparié vs Always SHORT,
  corrélation vs swing) AVANT toute discussion d'enrôlement — critère de fin plan §7.
- Réversibilité : 2 kill-switchs indépendants (labo + serveur), aucun rebuild Docker
  (aucune nouvelle dépendance).

## 5. Limites connues (honnêtes)

1. **HTTP en clair** vers `ip:8200` (clé API exposée en transit) — accepté court terme,
   TLS/Tailscale à trancher avec la décision hébergement.
2. **Pas de sentinelle source_health** pour le flux labo : si le Mac s'éteint, aucun
   signal ET aucune alerte — accepté en shadow (obstacle O4/O18).
3. **H1 réfutée côté labo** : rien ne laisse attendre un edge ; la connexion sert à
   MESURER proprement, pas à espérer.
4. Les tests labo mockent le HTTP ; le POST réel n'a pas encore été exercé bout-en-bout
   (fait à la mise en service, plan §5 étape C).
