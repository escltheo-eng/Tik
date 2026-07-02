# Câblage des sources — vérification complète + tri (2026-07-02)

> Second volet de l'audit du 2026-07-02 (après `docs/audit-modules-e2e-2026-07-02.md`) :
> vérification que **chaque source est bien câblée de bout en bout**
> (ingester → clé Redis → consommateur), tri des sources inutilisables, et
> décisions. Méthode : croisement exhaustif des clés Redis écrites
> (`aggregator/`) et lues (`scoring/`, `api/`, `notify/`, `scripts/`), sur le
> code post-réconciliation `main` (ADR-034/036/037 inclus).

## 1. Matrice de câblage (vérifiée dans le code)

| Source / ingester | Clé Redis écrite | Consommateur | Câblage | Statut réel |
|---|---|---|---|---|
| Binance WS (prix BTC) | `tik.last_price.BTC` | flash (fraîcheur), briefing | ✅ | actif |
| Yahoo (prix GOLD) | `tik.last_price.GOLD` | swing GOLD, briefing | ✅ | actif (délai 15 min connu) |
| Fear & Greed | `tik.sentiment.fear_greed` | swing BTC (overlay) + API | ✅ | actif |
| CryptoCompare | `tik.sentiment.cryptocompare.btc` | swing BTC (overlay) + API | ✅ | **quota resetté ~1er juillet → doit être revenu — À VÉRIFIER sur le VPS** |
| Google News BTC/GOLD | `tik.sentiment.google_news.*` | swing (overlay) + API | ✅ | actif |
| Reddit | `tik.sentiment.reddit.btc` | swing BTC (overlay) | ✅ câblé mais | **MORT (IP-ban depuis 18/05, unban sans réponse)** — backoff 6 h posé, auto-récupération si unban |
| GDELT | `tik.sentiment.gdelt.gold` | swing GOLD (overlay) | ✅ | actif (throttlé ~75 %, mitigé) |
| CFTC COT | `tik.macro.cftc_cot.gold` | swing GOLD (toggle OFF) + API/cockpit | ✅ | collecté, overlay désactivé (critère ADR-018 P2) |
| DXY (FRED direct) | — (fetch direct dans swing) | swing GOLD (toggle OFF) | ✅ | désactivé (critère de réactivation défini) |
| CoinGecko | `tik.sentiment.coingecko.btc` (+history) | swing BTC (toggle OFF) + mesure | ✅ | shadow, toggle OFF |
| Polymarket BTC/GOLD | `tik.sentiment.polymarket.*` (+history) | API/carte dashboard + mesure | ✅ | shadow — **verdict ⚪ 30/06 (anti-prédictif)**, garde un rôle de contexte |
| Dérivés Binance | `tik.deriv.binance.btc` | API/carte + briefing + mesure | ✅ | shadow — ⚪ sauf fil L/S (re-mesure ~mi-août) |
| ETF flows | `tik.etf.btc` (+history) | API/carte + mesure | ✅ | shadow — ⚪ net (mécanisme absent) |
| TradingView TA | `tik.tradingview.*` (+history) | API/cartes | ✅ | shadow contexte |
| Macro Regime (ADR-028/035) | `tik.macro.regime` | API `/macro/regime` + cockpit | ✅ | actif (contexte strict) |
| Rate Probabilities (ADR-029) | `tik.macro.rate_probabilities` | API + cockpit | ✅ | actif (contexte strict) |
| Stablecoins (ADR-036) | `tik.macro.stablecoins` | API `/macro/stablecoins` + carte | ✅ | actif (contexte strict) |
| Cross-asset (ADR-037) | `tik.macro.cross_asset` | API `/macro/cross_asset` + carte | ✅ | actif (contexte strict) |
| Calendriers (FRED + statiques) | table `macro_events` | API + discipline ±4h + Telegram | ✅ | actif |
| Breaking news (ADR-027) | `tik.breaking.*` | API/carte + Telegram | ✅ | actif (intervalle 300 s post-audit) |
| Micro ML labo (ADR-034) | via `POST /signals/ingest` | DB + WS + mesure (shadow strict) | ✅ | actif en prod depuis 24/06, mesurable ~mi-juillet |
| **FRED ingester horaire** | `tik.macro.last.{7 séries}` | **PERSONNE** | ⚠ **ORPHELIN** | tourne pour rien (cf. §3.1) |
| Binance/Yahoo pub/sub | canal `tik.tick.*` | **aucun abonné** | ⚠ sans consommateur | inoffensif (pub/sub fire-and-forget) |
| **Hacker News (NOUVEAU, ADR-039)** | `tik.sentiment.hackernews.btc` (+history) | mesure future uniquement | ✅ shadow strict | **ajouté ce jour — candidat remplaçant Reddit** |

**Verdict global câblage : sain.** Toutes les sources actives sont consommées ;
tous les shadows ont un objectif documenté (mesure ou contexte) ; les deux
anomalies trouvées sont mineures (§3.1, §3.2). Aucune clé lue qui ne serait
écrite nulle part (pas de « consommateur fantôme »).

## 2. Tri des sources inutilisables (demande du 2026-07-02)

Règle appliquée : *« ajouter ou remplacer les sources inutilisables, SAUF
celles qui ont un objectif précis »*.

| Source | État | Objectif précis ? | Décision |
|---|---|---|---|
| **Reddit** | Morte (6,5 sem d'IP-ban, unban sans réponse) | Oui (auto-récupération si unban) mais **plus crédible seul** | **GARDÉE (backoff 6 h) + REMPLAÇANTE AJOUTÉE : Hacker News en shadow (ADR-039)** |
| CryptoCompare | Quota resetté ~1er juillet | Oui (3e overlay BTC, intervalle 12 h sécurisé) | Gardée — vérifier le retour effectif sur le VPS |
| GDELT | Throttlée ~75 % mais fournit du tone | Oui (overlay GOLD, mitigation en place) | Gardée |
| DXY / COT overlays | Désactivés | Oui (critère de réactivation mesurable, ADR-018 P2) | Gardés OFF — re-mesure avec les **scripts corrigés** (le look-ahead COT/DXY corrigé par l'audit rend l'ancienne mesure caduque) |
| Polymarket | ⚪ anti-prédictif (verdict 30/06) | Oui (carte contexte + collecte historique) | Gardée en shadow — **ne jamais enrôler** sans nouvelle mesure |
| ETF flows | ⚪ net | Oui (carte contexte) | Gardée en shadow |
| Dérivés Binance | ⚪ sauf fil L/S | Oui (re-mesure ~mi-août) | Gardée en shadow |
| CoinGecko | Toggle OFF | Oui (mesure prédictive propre à faire) | Gardée OFF |
| **FRED horaire (`tik.macro.last.*`)** | Orphelin | **NON** (aucun consommateur) | **À TRANCHER** (§3.1) — non retiré unilatéralement |

## 3. Anomalies de câblage trouvées

### 3.1 `FredIngester` horaire : sorties 100 % orphelines

L'ingester `fred_macro` (polling 1 h, 7 séries : DGS10, DGS2, DTWEXBGS,
CPIAUCSL, M2SL, FEDFUNDS, UNRATE) écrit `tik.macro.last.{série}` et publie sur
pub/sub — **aucun consommateur dans tout le code** (vérifié : l'overlay DXY
fetch FRED directement, le régime macro ADR-028 fait ses propres appels FRED,
le briefing n'y touche pas). Coût : ~168 appels FRED/jour (gratuits, illimités)
+ écritures Redis (désormais avec TTL 25 h).

**Pour le garder** : coût quasi nul, séries brutes utiles au debug, FRED
illimité. **Pour le retirer** : bruit de câblage, 1 ingester de moins à
surveiller, ~19 → 18 process. **Verdict proposé : retirer** (le régime macro
couvre le besoin réel), mais c'est un retrait de fonctionnalité prod → décision
utilisatrice. En attendant : documenté ici + TTL posé (il s'auto-nettoie).

### 3.2 Canal pub/sub `tik.tick.*` sans abonné

`binance_ingester` et `yahoo_ingester` publient chaque tick sur un canal
pub/sub que personne n'écoute. Inoffensif (un publish sans abonné ne coûte
rien) et potentiellement utile à un futur consommateur temps réel — gardé,
noté ici pour que le prochain audit ne le « redécouvre » pas.

### 3.3 Doublon pont micro (déjà noté dans CLAUDE.md)

`tik_bridge.py` (prod VPS) vs `tik_adapter.py` (committé au labo, OFF) — deux
implémentations du même pont labo→Tik. À réconcilier (garder une seule
implémentation, celle de prod, et brancher le repo dessus). Inchangé ici.

## 4. Données mises à jour ce jour

- **CLAUDE.md** : compte de tests (~1395 → 1806), note CryptoCompare
  (« ~1er juillet » → échéance atteinte, à vérifier), entrée datée 2026-07-02
  (audit + corrections + ADR-039), correction des descriptions périmées
  ADR-004/005 (veracity par dispersion, seuil 0.30).
- **backlog.md #10** : Option C.1 Hacker News → **implémentée en shadow**
  (ADR-039).
- `aggregator/polling.py` : source unique des intervalles (+ `hackernews_btc`,
  `stablecoins`, `cross_asset`).

## 5. Ce qui n'a volontairement PAS été fait

- **Retrait du FRED horaire orphelin** : décision utilisatrice (§3.1).
- **Enrôlement de quoi que ce soit sur le `combined_bias`** : rien n'est
  enrôlé, rien ne change dans les moteurs — NO-GO et règle shadow ≥ 2 sem
  intacts (un test garde-fou le verrouille pour HN).
- **Validation réseau de hn.algolia.com** : impossible depuis l'environnement
  de dev (réseau restreint) — à faire au déploiement VPS (commande dans
  l'ADR-039).
