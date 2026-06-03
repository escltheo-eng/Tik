# ADR-023 — Positionnement dérivés Binance BTC (famille edge non-sentiment, SHADOW)

**Date** : 2026-06-03
**Statut** : ACCEPTÉ (collecte SHADOW, AUCUN overlay branché)
**Implémenté dans** : Paquet 51

---

## Contexte

Le go/no-go officiel du 2026-05-27 est un **NO-GO directionnel** : Tik n'ajoute pas
d'alpha au-dessus de la meilleure baseline de tendance, il est colinéaire au trend
(cf. mémoires `tik-empirical-state-2026-05-23`, `measurement-overlapping-returns`).
Diagnostic central (CLAUDE.md §8) : **toutes les sources actuelles sont du sentiment
retardé** (Fear & Greed, CryptoCompare, Google News, Reddit, CoinGecko). En empiler
davantage ne crée pas d'edge — ça le **dilue**. L'edge, s'il existe, vit dans des
**familles de données DIFFÉRENTES**.

Une de ces familles, jamais codée, est explicitement au backlog (`454416a`) : le
**positionnement dérivés** (funding rate, open interest, ratio long/short,
liquidations). C'est de l'argent réel + du levier engagés, pas un sondage de
sentiment — mécanisme distinct, candidat sérieux à un apport d'information
indépendant.

**Vérification de joignabilité depuis le VPS Hetzner (mesurée 2026-06-03, engagement
#10 « mesurer plutôt que spéculer »)** — Binance géo-restreint parfois ses endpoints
*futures* (`fapi.binance.com`), et on a déjà été surpris par un ban réseau (Reddit
Bug 11) ; donc on teste avant de coder :

| Endpoint | HTTP | Donnée |
|---|---|---|
| `/fapi/v1/premiumIndex` | 200 | funding rate courant + mark price |
| `/fapi/v1/openInterest` | 200 | open interest (BTC) |
| `/futures/data/openInterestHist` | 200 | OI historique + valeur USD |
| `/futures/data/globalLongShortAccountRatio` | 200 | ratio long/short retail |
| `/futures/data/topLongShortAccountRatio` | 200 | ratio long/short top traders |

Tous joignables (~0,3 s), y compris les `/futures/data/*` parfois bloqués. Pas de
Bug-11-bis. Même fournisseur que nos klines spot (`api.binance.com`), gratuit, sans clé.

## Décisions

### D1 — Source = positionnement dérivés Binance USDⓈ-M BTCUSDT

Snapshot horaire : `funding_rate`, `mark_price`, `open_interest_btc/usd`,
`long_short_ratio_global` (retail) + `long_short_ratio_top` (« smart money »). La
divergence retail vs top traders est un signal de positionnement classique. On
collecte les deux dès maintenant pour qu'ils aient le même historique au moment de
la mesure.

### D2 — SHADOW STRICT : aucun overlay, aucun toggle (plus prudent que CoinGecko)

Contrairement à CoinGecko (ADR-021) qui a écrit son `_enrich_with_coingecko` gaté
OFF, ici on **n'écrit AUCUN `_enrich_with_binance_derivatives` ni toggle de config**.
Raison : zéro ligne touchée dans `swing_engine.py` / `flash_engine.py` / `config.py`
→ les signaux émis sont **mathématiquement inchangés**, pas seulement « gatés OFF ».
Et le mapping dérivés → bias n'est PAS évident (funding contrarian aux extrêmes ?
OI comme multiplicateur de conviction ? L/S retail contrarian ?) — le **deviner**
maintenant serait une faute. C'est la **mesure** (D4) qui informera ce mapping, dans
un futur ADR au moment de l'enrôlement.

### D3 — Stockage Redis + santé

- `BinanceDerivativesIngester` (couche 1) collecte dans `tik.deriv.binance.btc`
  (snapshot, TTL 25 h) + `tik.deriv.binance.btc.history` (liste cappée 2000 ≈ 83 j).
- Enregistré dans `run_ingesters.py` (best-effort, `start()` ne lève jamais → ne
  peut pas empêcher les autres ingesters de démarrer).
- Une `SourceSpec` ajoutée à `source_health.py` (non critique) → la source apparaît
  ok/stale/missing dans `/metrics/source_health` et la carte dashboard Système, ce
  qui capte un dégradé silencieux (cf. leçon Bug 11).

### D4 — Protocole MESURE-AVANT-ENRÔLEMENT (règle CLAUDE.md §8)

`scripts/measure_btc_derivatives.py` (lecture seule) calcule : inventaire + qualité,
distributions, divergence retail/top, et un **IC prédictif** (Spearman funding/L-S
vs rendement forward, via la série `mark_price` de l'historique). Avant tout
enrôlement sur le `combined_bias`, il faut **≥ 2 semaines** + :
1. IC stable et de signe cohérent (chevauchant ET non chevauchant) ;
2. **indépendance** vs les sources sentiment (sinon redondant → dilue) ;
3. gain apparié vs **Always SHORT** (pas Random), fenêtres non chevauchantes.

Le NO-GO directionnel reste inchangé : **aucun enrôlement directionnel** tant que la
mesure complète n'est pas concluante.

### D5 — Pas de dérivés GOLD ici

Binance fournit le perp BTC ; le positionnement OR institutionnel = COT (déjà codé,
désactivé empiriquement, ADR-018 P2). La famille non-sentiment candidate pour GOLD
est le **real yield** (FRED `DFII10`) — sujet d'un ADR séparé si l'utilisatrice le
demande.

## Conséquences

- **Positives** : première famille **non-sentiment** dans Tik ; risque de dilution
  **nul** tant que non branché (hors du calcul) ; contexte de positionnement utile
  au trader manuel dès maintenant ; réversible en retirant 1 ligne + 1 `SourceSpec`.
- **Limites connues (engagement 13bis #8)** :
  1. **« Famille différente » est une hypothèse, pas une preuve** : le funding peut
     être partiellement redondant avec la cupidité (FG). À MESURER (D4), pas supposer.
  2. **Snapshots horaires → rendements chevauchants** : un IC dessus gonfle la
     significativité (mémoire `measurement-overlapping-returns`) — le script rapporte
     aussi le N non chevauchant.
  3. **Dilution au branchement** : la moyenne du `combined_bias` est à plat (ADR-004),
     donc même une bonne source ne pèse que 1/N ; l'enrôlement devra peut-être passer
     par un poids dédié / une piste séparée, pas un vote égal de plus.
  4. **Dépendance IP** : si l'IP du VPS change/est bannie, les `/futures/data/*`
     pourraient se fermer (comme Reddit) — `source_health` le détecterait (stale/missing).

## Réversibilité

Retirer la ligne `BinanceDerivativesIngester(...)` de `run_ingesters.py` + la
`SourceSpec` `binance_derivatives_btc`. Aucune migration, aucun impact signaux
(rien n'était branché).
