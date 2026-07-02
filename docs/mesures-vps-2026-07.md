# Mesures à lancer sur le VPS — juillet 2026 (commandes prêtes)

> Compagnon du plan du 2026-07-02. Toutes ces commandes se lancent connectée en
> SSH au VPS (`ssh root@204.168.220.47`). Elles **lisent** les données et
> produisent des rapports — aucune n'enrôle quoi que ce soit sur les signaux
> (règle : mesure ≥ 2 semaines + décision explicite avant tout enrôlement).
> Prérequis : avoir déployé le code du jour (`cd /opt/tik/core && git pull &&
> docker compose up -d --build`).

## 1. Re-mesure DXY/COT (GOLD) — en retard depuis le ~23/06

L'ancienne mesure est **caduque** : l'audit du 2026-07-02 a corrigé un
look-ahead (COT daté au mardi au lieu du vendredi de publication ; DXY publié
avec ~1 semaine de retard). Le script corrigé applique maintenant les bons
décalages et un sous-échantillonnage non chevauchant.

```
cd /opt/tik/core
docker exec tik-core python -m tik_core.scripts.backtest_numeric_sources --months 12
```

**Lecture du verdict** (critère ADR-018 P2, inchangé) : si l'IC DXY @120h est
**négatif** ET le hit des cas extrêmes ≥ 50 % (sur les colonnes *_indep, non
chevauchantes) → réactivation possible de `gold_dxy_cot_overlays_enabled=True`.
Sinon : rester OFF. Les recommandations marquées « indicatif — non significatif
après correction » ne comptent PAS.

## 2. Mesure CoinGecko prédictive (données shadow déjà accumulées)

```
docker exec tik-core python -m tik_core.scripts.measure_coingecko_predictive
```

**Lecture** : seule la ligne h=1 (non chevauchante) est fiable. Si Δup% ne
prédit pas le rendement BTC → CoinGecko reste OFF (et on arrête de la
considérer comme « candidat 4e overlay »).

## 3. Assainissement labo AVANT la mesure micro (~mi-juillet) — IMPORTANT

À faire UNE FOIS, avant de lancer la mesure micro :

```
cd /opt/btc-research-lab
git pull
docker compose -f docker-compose.micro.yml exec micro \
  python retro_invalidate_gap_resolutions.py            # dry-run : lire le rapport
docker compose -f docker-compose.micro.yml exec micro \
  python retro_invalidate_gap_resolutions.py --apply    # appliquer
docker compose -f docker-compose.micro.yml restart micro
```

Le restart est obligatoire : le modèle online a appris sur les vieilles
étiquettes, il se ré-entraîne au boot sur l'historique nettoyé.

## 4. Bascule du pont micro (tik_bridge → tik_adapter)

Checklist complète : `btc-research-lab/reports/2026-07-02_bascule_pont_micro.md`
(diff de sécurité avant retrait, `.env` inchangé grâce à l'alias, validation
201 côté Tik).

## 5. Validation Hacker News (ADR-039)

Après le déploiement, vérifier que la nouvelle source shadow publie :

```
curl -s "https://hn.algolia.com/api/v1/search?query=bitcoin&tags=story" | head -c 200
cd /opt/tik/core && docker compose logs ingesters --tail 100 | grep hackernews
```

Attendu : `hackernews.ingester.started` puis `hackernews.published` (cycle
30 min). La **date de début de collecte** fait foi pour la mesure ≥ 2 semaines
(si déploiement le 03/07 → mesurable ~17/07).

## 6. Échéancier des mesures suivantes

| Quand | Quoi | Script |
|---|---|---|
| ~15/07 | **Micro ML (ADR-038)** — le fil principal | à définir avec les fenêtres ADR-034 (hit 2h seuil 0.4 %) |
| ~17/07 | Hacker News (2 sem de collecte) | comparaison Reddit/HN à armes égales (même méthode) |
| ~mi-août | Dérivés L/S (le seul fil dérivés vivant) | `measure_btc_derivatives.py` |
