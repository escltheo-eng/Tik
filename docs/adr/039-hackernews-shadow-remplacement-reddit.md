# ADR-039 — Hacker News en shadow, candidat remplaçant de Reddit

**Date** : 2026-07-02
**Statut** : Accepté (shadow) — enrôlement NON décidé
**Contexte amont** : Bug 11 (IP-ban Reddit), backlog #10 (Option C.1), audit
modules + E2E 2026-07-02, règle « mesurer ≥ 2 semaines avant tout enrôlement ».

## Contexte

Reddit est IP-bannie sur l'IP du VPS depuis le **2026-05-18** (Bug 11). La
demande d'unban soumise le soir même n'a **jamais reçu de réponse** (~6,5
semaines au 2026-07-02). Conséquence structurelle : BTC swing tourne durablement
avec un overlay sentiment en moins, et l'ingester Reddit ne produit **aucune
donnée** (il tourne désormais en backoff 6 h sur 403, auto-récupérant si l'unban
arrive un jour).

Le backlog #10 avait évalué les remplaçants et retenu **Hacker News (API
Algolia)** en verdict préliminaire : gratuit, JSON propre, sans clé, limites
généreuses (~10 000 req/h documentées), communauté tech crédible qui couvre
crypto + macro, pas d'historique d'IP-ban.

## Décision

Ajouter un `HackerNewsIngester` en **MODE SHADOW STRICT** :

- **Source** : `GET https://hn.algolia.com/api/v1/search` avec
  `tags=story`, requêtes `bitcoin` + `btc` (dédupliquées par `objectID`),
  filtre `points >= 5`.
- **Méthode identique à Reddit (ADR-009)** pour une comparaison à armes
  égales : titres classifiés par le même `NewsClassifier` (DI, 5e classifier
  isolé pour son circuit breaker Ollama), score net **pondéré par
  log(points+1)**, mêmes seuils de filtrage bas-étage.
- **Sorties Redis** : `tik.sentiment.hackernews.btc` (TTL 2 h) + historique
  cappé `tik.sentiment.hackernews.btc.history` (LPUSH/LTRIM 2000 ≈ 40 j)
  pour la future mesure.
- **Polling 30 min** (48 req/jour, marge ~500× sous la limite), intervalle
  centralisé dans `aggregator/polling.py`.
- **AUCUN câblage moteur** : pas de `_enrich_with_hackernews`, pas de toggle,
  zéro ligne dans `swing_engine`/`flash_engine`/`cross_validator`. Un test
  garde-fou (`test_shadow_strict_no_engine_wiring`) échoue si quelqu'un
  référence hackernews dans `scoring/`.
- **Pas de persistance `headlines` en DB** tant que non mesuré (pas
  d'apparition dans l'UI — une source non validée ne doit pas gagner en
  visibilité avant sa mesure).

## Critère d'enrôlement (inchangé, règle projet)

Mesure shadow **≥ 2 semaines** (IC / hit rate / gain apparié vs Always SHORT,
fenêtres non chevauchantes — utiliser les scripts corrigés par l'audit
2026-07-02) **PUIS décision utilisatrice** + nouvel amendement ADR. Vérité
empirique à garder en tête : les 3 dernières familles mesurées ont donné ⚪, et
HN est du **sentiment retardé** comme Reddit — la probabilité a priori d'un
edge est faible ; l'objectif premier est de **restaurer la robustesse du
pipeline sentiment** (3-4 sources au lieu de 2), pas de trouver un edge.

## Conséquences / limites connues

1. **Joignabilité de hn.algolia.com non vérifiée depuis l'environnement de
   dev** (réseau sortant restreint) — à valider sur le VPS au déploiement :
   `curl -s "https://hn.algolia.com/api/v1/search?query=bitcoin&tags=story" | head -c 200`.
2. Volume attendu plus faible que Reddit (~10-20 titres pertinents/jour) et
   tonalité tech-sceptique — le score peut être plus souvent neutre.
3. Pas de détection brigading v1 (mécanique de vote HN ≠ Reddit, seuils non
   calibrés) — à évaluer à la mesure.
4. Si Reddit est unbannie entre-temps, les deux coexistent sans conflit
   (clés Redis distinctes) et la comparaison directe Reddit vs HN devient
   possible — c'est même le meilleur scénario pour choisir.

## Réversibilité

Retrait = retirer la ligne du runner (`run_ingesters.py`) + l'entrée
`hackernews_btc` de `polling.py`. Aucun autre couplage.
