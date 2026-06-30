# ADR-031 — Recommandations techniques TradingView, macro + micro (SHADOW)

**Date** : 2026-06-30
**Statut** : ACCEPTÉ (collecte SHADOW, AUCUN overlay branché)
**Demande utilisatrice** : « intégrer une API TradingView, avec une différenciation
info macro et micro » + précision « l'instrument s'utilisera sur le BTC et le GOLD ».

> ⚠️ À ne pas confondre avec l'**ADR-030** (« Fusion macro+micro dans un backend
> unique », Tik × btc-research-lab), qui emploie « macro/micro » dans un sens
> **différent** (macro = Tik OSINT, micro = labo quant). Ici « macro/micro »
> désigne le **contexte macro-économique** vs la **microstructure de marché**.

---

## Contexte

L'utilisatrice veut intégrer TradingView avec une distinction macro-éco / micro,
sur les deux actifs qu'elle trade manuellement (BTC et GOLD).

**Vérité technique d'abord (engagement #4 « ne pas inventer », #10 « mesurer ») :**
TradingView **n'a pas d'API publique officielle** de données de marché. Trois voies
existaient : (A) récupérer les **recommandations techniques** que TradingView calcule
(lib non-officielle `tradingview-ta` qui interroge `scanner.tradingview.com`) ;
(B) recevoir des **alertes Pine Script** par webhook (officiel, mais nécessite un
abonnement TradingView payant + création manuelle d'alertes) ; (C) **widgets de
graphiques** (affichage seul, aucune donnée exploitable). L'utilisatrice a choisi
**A**, et « macro vs micro » = **contexte macro-éco vs microstructure**.

**Joignabilité non vérifiable depuis l'environnement de dev** : le proxy réseau de
l'environnement Claude refuse `scanner.tradingview.com` (politique réseau,
`403 connect_rejected` mesuré). Ça ne présume rien du VPS/Mac — comme pour les
dérivés (ADR-023) et les ETF (ADR-024), la **joignabilité réelle est à confirmer au
déploiement** par un `curl` (commande fournie en §Validation). PyPI étant accessible,
la lib s'installe et le code se teste avec des données simulées.

## Décisions

### D1 — Source = recommandations techniques `tradingview-ta` (non-officielle)

Lib `tradingview-ta>=3.3.0`, gratuite, sans clé. Par cible (instrument × timeframe)
on récupère la **note agrégée** TradingView (`STRONG_BUY / BUY / NEUTRAL / SELL /
STRONG_SELL`), les compteurs BUY/SELL/NEUTRAL, la note **oscillateurs** vs **moyennes
mobiles** (souvent divergentes = info utile), et quelques valeurs brutes (RSI, close)
pour le contexte. La lib est **synchrone** (requests) → chaque appel tourne dans un
thread via `asyncio.to_thread` pour ne pas bloquer l'event loop.

### D2 — Deux familles : MACRO (commun) + MICRO (par actif BTC et GOLD)

- **MACRO** (timeframe 1D, contexte commun) : DXY (dollar), S&P 500, US 10Y (taux),
  Or, VIX (volatilité). Clé Redis `tik.tradingview.macro`.
- **MICRO** (timeframes 5m/15m/1h, **un panier par actif tradé**) : BTCUSDT (BINANCE,
  crypto) et XAUUSD (OANDA, forex). Clés `tik.tradingview.micro.btc` /
  `tik.tradingview.micro.gold`.

Le GOLD micro via TradingView est un **contexte technique indépendant de Yahoo**,
donc compatible micro — contrairement au flash GOLD *interne* de Tik (ADR-005),
bloqué par le délai Yahoo 15 min. Ici on n'émet aucun signal, on lit du contexte.

### D3 — SHADOW STRICT : aucun overlay, aucun toggle, ne touche pas `combined_bias`

Conformément au cadre du projet (NO-GO directionnel du 2026-05-27, règle « mesurer
≥ 2 semaines avant enrôlement »), cette source part en **shadow strict**, exactement
comme dérivés Binance (ADR-023) et flux ETF (ADR-024) : il n'existe volontairement
**aucun `_enrich_with_tradingview`** dans les moteurs et **aucun toggle de config**.
Les clés Redis n'influencent **aucun signal** (direction / véracité / conviction
inchangées). Retrait = retirer une ligne dans `run_ingesters.py`.

**Double raison de fond (à ne pas maquiller, Axe stratégique #1) :**
1. Tik est en **NO-GO directionnel** — aucun edge prouvé ; on n'ajoute pas de
   « vernis de certitude ».
2. Ce sont des recommandations d'**analyse technique** — or Tik calcule **déjà** ses
   propres indicateurs RSI/MACD/EMA, mais à **poids 0** (ADR-018, OSINT pur). Donc
   **risque de redondance**, PAS une nouvelle famille d'edge (contrairement aux
   dérivés / ETF qui sont du non-sentiment). La mesure shadow tranchera s'il y a un
   apport indépendant ; en attendant, c'est du **contexte/discipline**, pas un signal.

### D4 — Exposition API + carte dashboard (contexte, lecture seule)

- `GET /api/v1/tradingview/macro` et `GET /api/v1/tradingview/micro/{entity_id}`
  (BTC|GOLD) — lisent le snapshot Redis, retournent un snapshot vide (pas d'erreur)
  si l'ingester n'a pas encore publié. Schémas `TradingViewSnapshotOut` /
  `TradingViewItemOut`.
- Carte dashboard « Recommandations TradingView » (onglet Marché), badge
  `shadow · contexte`, panier macro + bascule BTC/GOLD pour le micro. Mêmes codes
  couleur que le reste de l'app (achat vert / vente rouge / neutre gris). Disclaimer
  explicite : « analyse technique, contexte, pas un signal Tik ».

## Conséquences

**Positif** : donne enfin un point de vue **technique externe** lisible (macro-éco +
microstructure BTC/GOLD), utile comme contexte/discipline pour le trading manuel,
sans renier le NO-GO. Pattern d'ajout identique aux autres shadows (réversible,
isolé). Best-effort partout : un instrument qui ne résout pas, ou TradingView
indisponible, n'affecte ni le reste du panier ni le pipeline.

**Limites connues (engagement #8) :**
1. **Lib non-officielle** → peut casser si TradingView change `scanner.tradingview.com`.
   Mitigé : chaque cible best-effort, log `tradingview_ta.target.error`, jamais bloquant.
2. **Boîte noire** : `Recommend.All` est la formule propriétaire TradingView agrégeant
   ~26 indicateurs — c'est « l'avis de l'algo TradingView », pas de la donnée brute.
3. **Joignabilité runtime non testée** depuis le dev (proxy 403) → à confirmer au
   déploiement (cf. Validation).
4. **Redondance probable** avec la techno déjà calculée par Tik (poids 0) → la mesure
   shadow ≥ 2 semaines est la seule façon de trancher un éventuel apport. **Ne PAS
   enrôler à l'aveugle.**

## Validation (à exécuter au déploiement par l'utilisatrice)

1. **Vérifier la joignabilité** depuis le VPS/Mac :
   ```bash
   curl -s -o /dev/null -w "HTTP %{http_code}\n" \
     -X POST "https://scanner.tradingview.com/crypto/scan" \
     -H "Content-Type: application/json" \
     --data '{"symbols":{"tickers":["BINANCE:BTCUSDT"],"query":{"types":[]}},"columns":["Recommend.All"]}'
   ```
   Attendu : `HTTP 200`. Si `000`/`403` → réseau bloqué (comme Reddit Bug 11) ; ne
   pas insister, documenter.
2. **Rebuild + restart** des ingesters (nouvelle dépendance `tradingview-ta`) :
   `docker compose up -d --build ingesters core`.
3. **Logs** : `tradingview_ta.ingester.started ... micro_entities=['BTC','GOLD']`
   puis `tradingview_ta.published basket=macro|micro entity=...`.
4. **API** : `curl -H "Authorization: Bearer <clé>" http://localhost:8200/api/v1/tradingview/macro`
   et `.../tradingview/micro/BTC` / `.../tradingview/micro/GOLD`.
5. **Dashboard** : la carte « Recommandations TradingView » se remplit (macro + micro
   via la bascule BTC/GOLD).

## Tests

`core/tests/test_tradingview_ta_ingester.py` : helper pur `_build_item` (+ cas
dégradés), `_fetch_target_sync` avec `TA_Handler` mocké (succès / lib qui lève /
analyse None), cycle complet avec faux Redis (3 clés écrites : macro + micro BTC +
micro GOLD, TTL, history) et cas no_data (rien écrit → on garde le dernier bon
snapshot). 13 tests, sans réseau ni Redis réelle.
