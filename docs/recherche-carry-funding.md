# Note de recherche — Le « carry » (funding rate) comme edge NON-directionnel

> Statut : **recherche / shadow** — aucun enrôlement, aucune décision structurante (pas un ADR).
> Date : 2026-06-29. Auteur : session Claude + Lola. À mesurer dès retour de l'accès serveur.
> Règle inchangée : **mesure ≥ 2 semaines vs baselines AVANT tout enrôlement** (cf. CLAUDE.md §8).

---

## 0. Pourquoi cette piste (et pas une autre)

Le go/no-go du 2026-05-27 = **NO-GO directionnel** : prédire si le BTC monte/descend
n'a aucun edge prouvé. Le labo `btc-research-lab` a confirmé ce mur de façon brutale —
ML, réversion à la moyenne, trend, online learning, algos génétiques, causalité,
régime macro : **TOUS réfutés après frais**. Verdict du labo : *« Aucun horizon ne
satisfait `précision × taille_move > coût` en taker. Ce n'est pas un problème de
modèle — c'est structurel. »* La littérature académique dit la même chose (rendements
spectaculaires **avant frais**, négatifs après).

**Conséquence** : la bonne question n'est plus « quelle math pour mieux prédire la
direction », mais **« quel edge existe SANS parier sur la direction »**. Le carry est
le candidat n°1 :
- **Non-directionnel** (market-neutral) → le NO-GO ne s'y applique pas.
- **Famille non-sentiment** (positionnement / structure de marché).
- **Tik collecte DÉJÀ la donnée** : `tik.deriv.binance.btc.history` (funding/OI/mark,
  shadow depuis ADR-023). La piste du labo (P3b / `backtest_carry_deep.py`) et la
  donnée de Tik **convergent**.

---

## 1. Ce qu'est le carry, en clair

Sur les **contrats perpétuels** (« perps »), un petit paiement périodique (le *funding
rate*, toutes les 8 h sur Binance) circule entre les positions longues et courtes pour
arrimer le prix du perp au prix au comptant. Quand la foule est longue/leveragée, les
longs **paient** les shorts (funding positif).

Stratégie **market-neutral** : on **achète le BTC au comptant** (spot) **+ on vend le
perp** (short). Les deux jambes s'annulent en direction → on ne gagne/perd RIEN sur le
mouvement du BTC. On **encaisse le funding** tant qu'il est positif. Deux sources de
gain :
1. **Les paiements de funding** (le flux régulier).
2. **La convergence de base** (l'écart perp↔spot qui se referme à l'échéance/au temps).

> ⚠️ Ce n'est **PAS** un « free lunch » : c'est une **prime de risque**. On est payé
> pour porter des risques réels (krach, contrepartie, liquidation) — voir §4.

---

## 2. L'évidence (labo + académie, convergente)

| Source | Mesure | Nuance |
|---|---|---|
| Labo `btc-research-lab` (P3b / carry_deep) | **+12,5 %/an**, Sharpe **6,45** (base incluse), maxDD −2,5 %, 7382 settlements / 6,7 ans | **Pas de red-team ni forward-test formel.** Sharpe réel plausible ~2-4. |
| BIS Working Paper No 1087 « Crypto carry » | Sharpe **6,45** plein échantillon (≈ même chiffre, indépendant), funding mean ~8 % vol 0,8 % | Validation externe forte. |
| Littérature 2025-2026 | Compression : Sharpe **4,06 en 2024 → négatif en 2025** ; base BTC **25 % (fév. 2024) → 4,46 % (déc. 2025)**, 93 % des jours sous le seuil de rentabilité ~5 % | **L'edge s'use vite** (afflux institutionnel). |

**Lecture honnête** : le carry EST un edge réel et documenté (deux sources
indépendantes au même Sharpe 6,45), **mais l'argent facile sur le BTC « gros cap » est
en train de disparaître**. Données publiées s'arrêtant ~fin 2025 → **le régime 2026 est
inconnu et doit être re-mesuré sur les données shadow de Tik** (c'est tout l'intérêt
d'avoir collecté).

---

## 3. Comment le mesurer proprement dans Tik (le plan)

Données : `tik.deriv.binance.btc.history` (snapshots horaires : `funding_rate`,
`open_interest`, `long_short_ratio` global+top, `mark_price`, `fetched_at`).

**Étape 1 — Caractériser le régime de funding (le plus important).**
Sur toute la fenêtre shadow : distribution du `funding_rate` → moyenne, % de temps
positif, équivalent annualisé. Question : *le funding est-il actuellement POSITIF et
suffisant (carry récoltable), ou compressé/négatif (edge mort) ?* C'est la 1re chose à
trancher, et elle ne demande qu'une lecture descriptive.

**Étape 2 — Simuler le P&L carry market-neutral depuis l'historique shadow.**
Funding cumulé encaissé − **coûts réalistes** (frais sur les DEUX jambes spot+perp,
spread, rebalancing). Comparer au P3b du labo. ⚠️ Le script Tik actuel
`measure_btc_derivatives.py` mesure l'**IC directionnel** du funding (≠ ce qu'on veut) ;
il faut soit l'**étendre** pour simuler la récolte de carry, soit **rejouer le backtest
carry du labo** (`backtest_carry_deep.py`) sur l'historique funding de Tik.

**Étape 3 — Analyse conditionnelle : quand ça marche vs casse** (voir §4) : croiser le
P&L carry avec le signe du funding, le stress de base, le régime de volatilité.

---

## 4. Carte honnête : où le carry MARCHE vs CASSE

**✅ Marche quand :**
- Funding **durablement positif** (marché bull/neutre, foule longue qui paie).
- Base perp-spot **> seuil de rentabilité** (~5 % annualisé historiquement).
- Faible stress de contrepartie/liquidité.

**❌ Casse / risques (les 5 à surveiller) :**
1. **Compression** — régime actuel (base <5 %, 93 % des jours sous le seuil fin 2025).
   Sur le BTC gros cap, l'edge est possiblement **~nul en ce moment**.
2. **Funding qui devient négatif** (capitulation bear) → on **paie** au lieu d'encaisser
   (ou il faut inverser les jambes).
3. **Risque de contrepartie / plateforme** (type FTX) — la **queue catastrophique**.
4. **Risque de liquidation** sur la jambe short perp si sous-collatéralisée lors d'un
   squeeze.
5. **Rendement-sur-capital** — le « +12,5 % » est sur le notionnel, pas sur la marge
   immobilisée ; le vrai rendement net dépend du collatéral.

---

## 5. Garde-fous méthodologiques (repris de la discipline du labo)

- **Coûts réels obligatoires** : deux jambes, taker/maker, spread, granularité funding 8 h.
  Refuser tout P&L net sans `slippage` mesuré.
- **Forward-test, pas seulement backtest** — le labo signale que le carry n'a **PAS**
  encore passé de red-team 3-attaques ni de vrai forward-test. C'est la prochaine marche.
- **Carry conditionnel** : couper quand funding négatif / base stressée ; modéliser la
  liquidation réelle.
- **Reporter le NET** avec intervalle de confiance par block-bootstrap, jamais un
  point-estimate seul. Battre les baselines.
- **Rester SHADOW** jusqu'à mesure concluante. Pas d'enrôlement. Un futur ADR seulement
  si ça tient.

---

## 6. À faire dès que l'accès serveur revient (commandes prêtes)

```bash
# Sur le VPS, dans le repo Tik :
# 1) Diagnostic existant (IC directionnel — sert à caractériser funding/OI) :
docker exec tik-core python -m tik_core.scripts.measure_btc_derivatives
docker exec tik-core python -m tik_core.scripts.measure_btc_derivatives --horizon-hours 24

# 2) Côté labo (carry market-neutral, base incluse) :
#    (dans /opt/btc-research-lab, adapter au point d'entrée réel du conteneur micro)
#    python backtest_carry_deep.py
```

**Ce qu'on cherche** : (a) le funding 2026 est-il encore positif/suffisant ? (b) le P&L
carry net (après frais) sur la fenêtre shadow récente est-il > 0 et > baseline ? (c) dans
quelles conditions il devient négatif.

---

## 7. Limites connues (4)

1. **L'edge se compresse MAINTENANT** — le meilleur candidat est en déclin mesuré ; il
   peut être déjà trop tard sur le BTC gros cap (opportunité résiduelle = altcoins /
   écarts inter-plateformes, **hors périmètre Tik actuel**).
2. **Prime de risque ≠ sans risque** : krach, contrepartie, liquidation (§4).
3. **Complexité pour du trading manuel** : deux jambes (spot + perp) + gestion de marge —
   nettement plus dur que du spot simple. À évaluer vs le profil de la trader (sizing 1 %).
4. **« Fiable » ≠ « certain »** : au mieux une prime statistique sur la durée, pas une
   garantie ; et les chiffres publiés s'arrêtent fin 2025 → 2026 à re-mesurer.

---

## 8. Décision

**Aucune** à ce stade. On **mesure d'abord** (étapes §3 + §6). Si le carry net tient sur
les données 2026 de Tik après frais ET passe un forward-test → on rédige un **ADR
dédié** (prochain numéro libre, vérifié sur la prod Lolasiku selon la règle « un seul
endroit pour les numéros »). Sinon → on archive cette note comme piste réfutée, sans
regret (c'est l'hygiène épistémique du projet).
