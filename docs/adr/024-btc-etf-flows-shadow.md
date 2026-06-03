# ADR-024 — Flux ETF spot BTC (famille edge non-sentiment, SHADOW)

**Date** : 2026-06-03
**Statut** : ACCEPTÉ (collecte SHADOW, AUCUN overlay branché)
**Implémenté dans** : Paquet 52
**Backlog** : `docs/backlog-osint.md` V1.3 (« Flux ETF spot BTC — arbitrage de source »)

---

## Contexte

Le go/no-go officiel du 2026-05-27 est un **NO-GO directionnel** : Tik n'ajoute pas
d'alpha au-dessus de la meilleure baseline de tendance, il est colinéaire au trend
(cf. mémoires `tik-empirical-state-2026-05-23`, `measurement-overlapping-returns`).
Diagnostic central (CLAUDE.md §8) : **toutes les sources actuelles sont du sentiment
retardé** (Fear & Greed, CryptoCompare, Google News, Reddit, CoinGecko). En empiler
davantage ne crée pas d'edge — ça le **dilue**. L'edge, s'il existe, vit dans des
**familles de données DIFFÉRENTES**.

Après les dérivés Binance (ADR-023, positionnement), la 2ᵉ famille non-sentiment du
backlog est le **flux ETF spot BTC** : la demande institutionnelle réelle. Les ETF
spot Bitcoin US pèsent >50 G USD d'encours depuis janvier 2024 ; le détail quotidien
des inflows/outflows par fonds est publié gratuitement. Mécanisme distinct d'un
sondage de sentiment — candidat sérieux à un apport d'information indépendant.

**Arbitrage de source — vérification empirique depuis le VPS Hetzner (2026-06-03,
engagement #10 « mesurer plutôt que spéculer »)**. Le backlog V1.3 (MAJ 2026-05-24)
avait déjà éliminé DefiLlama (endpoint flux = Pro 300 $/mois) et CoinGlass (aucun
free tier, 29 $/mois mini) ; restait à trancher la source gratuite au codage. Probes :

| Source | Endpoint | HTTP | Verdict |
|---|---|---|---|
| **SoSoValue** | `openapi/v2/etf/currentEtfDataMetrics` (POST, us-btc-spot) | **200 `code:0`** | ✅ données réelles, **sans clé** |
| **SoSoValue** | `openapi/v2/etf/historicalInflowChart` (POST, us-btc-spot) | **200 `code:0`** | ✅ 300 j de backfill, **sans clé** |
| SoSoValue (web) | `sosovalue.com/assets/etf/us-btc-spot` | 403 | bloqué (anti-bot front) |
| Farside | `farside.co.uk/btc/` + `/bitcoin-etf-flow-all-data/` | 403 | bloque les bots (confirme V1.3) |
| CoinGlass | `open-api-v4.coinglass.com/api/etf/bitcoin/flow-history` | 200 « API key missing » | payant, exclu (§7 no-budget) |

**Conclusion** : SoSoValue openapi v2 est la **seule source gratuite qui répond**
avec de la donnée exploitable depuis le VPS. Farside reste 403 (inutilisable même en
cross-val), CoinShares n'a pas d'API. Smoke test live (2026-06-03) : flux net du
02-06 = −519,2 M$, cumul +54,7 Md$, 13 fonds (IBIT, FBTC, ARKB…), prix BTC implicite
67 587 $, 300 jours d'historique (24-03-2025 → 02-06-2026).

## Décisions

### D1 — Source = SoSoValue openapi v2, type `us-btc-spot`, sans clé

Deux endpoints POST par cycle :
- `currentEtfDataMetrics` → snapshot du dernier jour : flux net quotidien + cumulé,
  encours total, BTC détenu, volume échangé, détail des 13 fonds.
- `historicalInflowChart` → **série quotidienne complète** (auto-cicatrisante : la
  source renvoie tout l'historique à chaque appel → pas d'accumulation manuelle, pas
  de doublon de date). Donne ~300 jours de backfill immédiat pour la mesure.

Polling **6 h** : les flux ETF sont **quotidiens** (publiés le soir, jour de bourse
US), pas intra-day. 4 appels/jour, très loin de toute limite.

### D2 — SHADOW STRICT : aucun overlay, aucun toggle (comme ADR-023)

On **n'écrit AUCUN `_enrich_with_btc_etf_flows` ni toggle de config**. Zéro ligne
touchée dans `swing_engine.py` / `flash_engine.py` / `config.py` → les signaux émis
sont **mathématiquement inchangés**, pas seulement « gatés OFF ». Le mapping flux →
bias n'est PAS évident (un inflow net est-il prédictif, ou suit-il simplement le
prix ?) — le **deviner** maintenant serait une faute. C'est la **mesure** (D4) qui
informera ce mapping, dans un futur ADR au moment de l'enrôlement.

### D3 — Stockage Redis + santé

- `BtcEtfFlowsIngester` (couche 1) collecte dans `tik.etf.btc` (snapshot, TTL 4 j —
  tolère un week-end + jour férié US sans data neuve) + `tik.etf.btc.history` (série
  quotidienne complète, **persistante sans TTL** → survit à une coupure de la source).
- Enregistré dans `run_ingesters.py` (best-effort, `start()` ne lève jamais → ne peut
  pas empêcher les autres ingesters de démarrer).
- Une `SourceSpec` `btc_etf_flows` (non critique, `max_age` 18 h) ajoutée à
  `source_health.py` → la source apparaît ok/stale/missing dans
  `/metrics/source_health` et la carte dashboard Système (capte un dégradé silencieux,
  leçon Bug 11). `fetched_at` est ré-écrit à chaque cycle même le week-end (donnée du
  jour inchangée mais ingester vivant) → pas de faux positif sur les gaps de marché.

### D4 — Protocole MESURE-AVANT-ENRÔLEMENT (règle CLAUDE.md §8)

`scripts/measure_btc_etf_flows.py` (lecture seule) calcule : inventaire, distribution
du flux net quotidien, et un **IC prédictif** (Spearman flux[d] vs rendement BTC
forward via les klines Binance, anti-lookahead par un lag de publication). Avant tout
enrôlement sur le `combined_bias`, il faut **≥ 2 semaines** de shadow propre + :
1. IC stable et de signe cohérent (chevauchant ET non chevauchant) ;
2. **indépendance** vs le prix/trend (les inflows ne doivent pas que SUIVRE le prix) ;
3. gain apparié vs **Always SHORT** (pas Random), fenêtres non chevauchantes.

Le backfill (300 j) permet un IC **préliminaire** dès maintenant, mais il est
in-sample + régime-dépendant → à confirmer hors échantillon. Le NO-GO directionnel
reste inchangé : **aucun enrôlement directionnel** sans mesure complète concluante.

### D5 — Vérification croisée indisponible aujourd'hui (assumé)

Le plan B idéal du backlog (« bascule auto sur une source de cross-val si la
principale tombe ») n'a **aucune source gratuite de repli qui réponde** : Farside =
403, CoinShares = pas d'API. On l'assume : Plan B effectif = `source_health` détecte
le stale/missing + l'absence de signal-path (shadow) rend la panne sans conséquence.
Pas de fausse robustesse simulée. À revoir si une 2ᵉ source gratuite apparaît.

### D6 — Pas d'ETF GOLD ici

Les flux ETF or (WGC / SPDR GLD) sont le sujet du backlog **V1.2**, source et cadence
différentes (hebdo/PDF) — un ADR séparé si l'utilisatrice le demande.

## Conséquences

- **Positives** : 2ᵉ famille **non-sentiment** dans Tik (après les dérivés) ; risque
  de dilution **nul** tant que non branché (hors du calcul) ; 300 j de backfill
  immédiat → mesure préliminaire possible sans attendre ; contexte de flux
  institutionnel utile au trader manuel dès maintenant ; réversible en retirant
  1 ligne + 1 `SourceSpec`.
- **Limites connues (engagement 13bis #8)** :
  1. **Accès sans clé non garanti** : l'openapi SoSoValue répond sans clé aujourd'hui,
     mais rien ne le contractualise — un jour il pourrait exiger une clé ou
     rate-limiter. `source_health` le détecterait (stale/missing) ; réversible.
  2. **Source unique sans cross-val gratuite** : viole l'idéal « ne jamais dépendre
     d'une source » (D5) — mitigé par le shadow (hors signal-path) + monitoring.
  3. **Colinéarité prix probable** : un inflow ETF peut simplement SUIVRE le prix
     (acheter quand ça monte) → redondant avec le trend, pas un edge. « Famille
     différente » est une hypothèse, pas une preuve. À MESURER (D4), pas supposer.
  4. **N quotidien petit + chevauchement** : ~250 jours ouvrés/an, et un IC à horizon
     H > 1 sur pas quotidien chevauche (gonfle la significativité, mémoire
     `measurement-overlapping-returns`) — le script rapporte le N non chevauchant.
  5. **Dilution au branchement** : la moyenne du `combined_bias` est à plat (ADR-004),
     donc même une bonne source ne pèse que 1/N ; l'enrôlement devra peut-être passer
     par un poids dédié, pas un vote égal de plus.

## Réversibilité

Retirer la ligne `BtcEtfFlowsIngester(...)` de `run_ingesters.py` + la `SourceSpec`
`btc_etf_flows`. Aucune migration, aucun impact signaux (rien n'était branché).
