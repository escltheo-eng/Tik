# ADR-005 — Flash engine : horizon minutes-heures sur BTC

- **Statut** : Accepté
- **Date** : 2026-04-30

## Contexte

Le swing engine (ADR-004) couvre l'horizon jours-semaines : klines 4h pour
BTC, klines 1h pour GOLD. CLAUDE.md liste un *flash engine* parmi les
couches non-implémentées (section 8). L'utilisateur demande l'ajout d'un
flash engine sur BTC pour l'horizon minutes-heures, en complément du swing,
sans toucher au pattern existant.

Trois questions architecturales :

1. **Quelle source de données ?** Le flux Binance temps réel WebSocket est
   déjà ingéré (`binance_ingester.py`) et publie chaque trade sur un canal
   pub/sub Redis (`tik.tick.BTC.binance`) + cache `tik.last_price.BTC`
   (TTL 5 min, écrasé à chaque tick). Mais **aucune historisation** des
   ticks. Pour calculer un RSI 5 min ou un momentum, il faut de l'historique.
2. **Quels overlays sont pertinents pour le flash ?** Les overlays swing
   (Fear & Greed, news, DXY, COT) sont calibrés sur des fenêtres
   journalières → trop lents pour le flash.
3. **Faut-il émettre un signal à chaque cycle (5 min) ou seulement aux
   transitions de direction ?** Sur 5 min, ~288 signaux/jour BTC seul, ce
   qui dilue l'attention en DB et dans le futur dashboard.

## Décision

Nouveau fichier `core/src/tik_core/scoring/flash_engine.py`, séparé du
swing, suivant le **même pattern multi-overlay** (ADR-004).

### 1. Source de données : klines REST 1m + check fraîcheur sur le flux WS

- **Indicateurs techniques** : klines REST Binance `interval=1m`, 240
  dernières bougies (4h glissante).
- **Aucune modification** de l'ingester WebSocket existant — fichier qui
  tourne en shadow, pas touché.
- Le flux WS sert à **vérifier la fraîcheur** : avant chaque cycle flash,
  on lit `tik.last_price.BTC` ; si le timestamp a plus de 60 secondes,
  l'ingester WS est probablement déconnecté → on **skip le cycle** avec
  log warning (pas de signal émis sur des données stale).

Une évolution future possible (si on cible le scalp sub-seconde) serait
d'historiser les ticks dans un Redis ZSET via l'ingester. Hors scope ici.

### 2. Indicateurs techniques (court terme)

- **EMA 9 / EMA 21** (vs swing 20/50) → micro-tendance plus réactive
- **RSI 14** avec seuils plus extrêmes : overbought ≥ 75, oversold ≤ 25
  (vs swing 70/30) — sur 1m, on tape les zones extrêmes plus vite
- **MACD 12/26/9** standard
- **ATR 14** (volatilité, présent pour évolutions futures)
- **Momentum 15min** : variation % sur les 15 dernières bougies — règle
  spécifique flash, absente du swing
- **Seuil de directionnalité 0.10** (vs swing 0.08) — un cran plus strict
  pour limiter les faux signaux en marché choppy

### 3. Overlays initiaux (2 sources, extensible via `_enrich_with_*`)

| Helper | Source | Sémantique | Endpoint |
|---|---|---|---|
| `_enrich_with_orderbook` | Binance order book | Trend-following | `GET /api/v3/depth?limit=20` |
| `_enrich_with_aggression` | Binance aggregated trades | Trend-following | `GET /api/v3/aggTrades?limit=1000` |

**Order Book Imbalance (OBI)** : ratio `(bid_vol - ask_vol) / (bid_vol + ask_vol)`
sur le top 20 du carnet. Bias bull si déséquilibre côté acheteurs.

**Buyer/seller agression** : ratio `buy_vol / total_vol` sur les 1000
dernières aggTrades. Sur Binance, `m=true` ⇒ le maker était l'acheteur
(donc le **taker** était vendeur agressif), `m=false` ⇒ taker acheteur
agressif. Bias bull si majorité d'acheteurs agressifs.

Les deux helpers respectent strictement le contrat ADR-004 : retournent
un bias dans `[-1, +1]` ou `None`, n'altèrent pas la veracity directement.
La veracity finale est calculée via `_veracity_from_concordance(direction,
moyenne_des_biais)` comme pour le swing.

### 4. Émission conditionnelle des signaux

Géré dans le scheduler, pas dans l'engine :

- À chaque cycle (toutes les 5 min), comparaison de la direction émise
  avec la direction précédente stockée dans Redis sous
  `tik.flash.last_direction.BTC` (TTL 24h).
- Émission **si transition de direction** (long↔short↔neutral) — c'est le
  cas le plus utile à exposer.
- Émission **heartbeat** si plus de 30 minutes se sont écoulées depuis la
  dernière émission, même sans transition (pour conserver une trace
  périodique en DB).
- Sinon, pas d'écriture en DB ni de publish Redis (limite le volume).

La fonction de décision `should_emit(decision, last, now)` est exposée
publiquement dans `flash_engine.py`, donc testable unitairement.

### 5. Pas d'engine flash GOLD pour ce paquet

Yahoo Finance (source GOLD swing) a 15 min de délai → incompatible avec
l'horizon flash. GOLD flash nécessiterait une autre source (Polygon,
ActivTrades direct), hors scope budget API. À reconsidérer si Tik passe
sur des sources payantes.

## Conséquences

**Positives**

- Pattern symétrique au swing → faible coût d'apprentissage pour qui lit
  `swing_engine.py` puis `flash_engine.py`.
- Aucune modification des ingesters existants → zéro risque de régression
  sur le pipeline qui tourne déjà.
- Volume DB maîtrisé via émission conditionnelle (~10-50 signaux/jour
  estimés en marché normal vs 288 en émission systématique).
- Veracity dynamique opérationnelle dès le premier run (mêmes paliers
  0.70-0.95 que le swing).
- Les 2 overlays sont indépendants des sources swing → cross-validation
  réelle, pas de redondance d'information.

**Négatives**

- Charge REST Binance plus élevée : 3 appels REST toutes les 5 min
  (klines + depth + aggTrades) = ~36 req/h pour le flash. Rate limit
  Binance public = 1200 req/min, donc largement sous le plafond.
- Pas de pur sub-seconde : klines 1m + REST = latence de quelques
  secondes vs un vrai stream. Acceptable pour "5 min à quelques heures",
  insuffisant pour scalp.
- Duplication mineure entre `swing_engine.py` et `flash_engine.py` :
  fonction `_fetch_binance_klines` et `_veracity_from_concordance` (5-7
  lignes chacune). Acceptable pour ce paquet ; factorisation prévue au
  3ᵉ usage (engine macro).
- L'order book imbalance est sensible aux **spoofers** (gros ordres mis
  puis annulés pour manipuler la perception). Non corrigé pour le MVP ;
  à monitorer en backtest.

## Risques opérationnels (rappels stricts)

1. **Garde-fou 1 (mode shadow 3 mois)** reste **strictement applicable**
   au flash. Aucune connexion Tik flash → Zeta avant 3 mois minimum
   d'observation et d'analyse des signaux flash en DB.
2. **ADR-003 (pas de bypass V01-V15)** reste applicable : un futur signal
   flash consommé par Zeta passera intégralement par le guard, sans
   aucune exception.
3. **Coûts de transaction implicites** : sur horizon 1h, fees + spread
   mangent une plus grosse part du gain attendu. Tik ne place pas
   d'ordre, donc côté core c'est OK ; mais le futur SDK (Paquet 2) devra
   exposer cette limite à Zeta pour ne pas que `turbo_v2.py` traite un
   signal flash comme un signal swing.
4. **Whipsaw / faux signaux** : sur 5 min, le bruit domine. À mesurer en
   backtest dédié après 2-3 semaines de signaux stockés. L'émission
   conditionnelle (transition + heartbeat) atténue mais n'élimine pas le
   problème.
5. **Débounce / throttle Zeta-side** : quand on cablera l'intégration
   (dans plusieurs mois), un mécanisme de throttle sera nécessaire dans
   le SDK pour éviter que `turbo_v2.py` ne soit submergé de signaux flash
   modifiant la confidence en boucle. **À documenter dans un futur ADR
   au moment de l'intégration**, pas maintenant — pour l'instant Tik est
   en mode shadow et n'envoie rien à Zeta.

## Alternatives rejetées

- **100% WebSocket avec stockage Redis Stream/ZSET des ticks** : modifie
  un ingester qui tourne en shadow, ajoute de la complexité, pas justifié
  pour l'horizon minutes-heures (sub-seconde n'est pas la cible). À
  reconsidérer si on cible le scalp.
- **Réutiliser les overlays swing (FG, news)** : Fear & Greed change
  trop lentement (mise à jour journalière) pour avoir un signal sur 5
  min. CryptoCompare news pourrait être ajouté plus tard mais OBI +
  agression sont plus directement liés au timeframe court.
- **Émission systématique toutes les 5 min** : ~288 signaux/jour BTC,
  dilue l'attention dans la DB et le futur dashboard. Émission
  conditionnelle préférée.
- **Engine flash GOLD via Yahoo** : délai 15 min de Yahoo Finance
  incompatible avec l'horizon flash. Hors scope budget API.

## Évolutions futures envisagées

- **Funding rate Binance Futures** comme 3ᵉ overlay (contrarian, mesure
  la pression long/short des traders perpetual).
- **Cascade de liquidations** via `wss://fstream.binance.com/ws/!forceOrder@arr`
  comme signal très court terme.
- **Flash GOLD** quand une source temps réel sera disponible.
- **Historisation des ticks WS** dans un Redis ZSET pour viser le sub-seconde.
- **Backtest dédié flash** distinct du backtest swing actuel (horizons
  paramétrables : 15m, 1h, 4h).
