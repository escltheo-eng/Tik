# ADR-040 — Flash GOLD via le proxy PAXG (SHADOW, contexte + mesure)

> **Renumérotation 2026-07-03** : cet ADR est né « ADR-039 » sur la lignée VPS,
> mais 039 était déjà pris par le shadow HackerNews (même jour, autre session).
> Renommé 040 à la réconciliation — les messages de commit historiques disent « ADR-039 ».


- **Statut** : ACCEPTÉ (décision utilisatrice 2026-07-02 : « je veux le mettre en place maintenant »)
- **Date** : 2026-07-02
- **Numérotation** : 038 est réservé au verdict de la mesure micro (cf. CLAUDE.md §8) → 039.

---

## 1. Contexte et avertissement épistémique (à ne jamais maquiller)

Le flash GOLD était impossible depuis l'ADR-005 : les prix GOLD viennent de Yahoo
(15 min de retard), incompatible avec un horizon minutes-heures. La mesure du
2026-06-30 a montré que **PAXG (or tokenisé, Binance) suit GC=F à r≈0,975** (1h)
en temps réel → un flash GOLD devient *techniquement* possible via ce proxy.

**⚠ Espérance d'edge ≈ nulle, assumée d'entrée** : le flash BTC — même famille
d'overlays microstructure (carnet + agression) — est mesuré **NO-GO** le
2026-07-02 (hit 33,0 % vs Always SHORT 39,4 %, significativement pire que la
tendance, 9160 signaux). Ce moteur est du **CONTEXTE microstructure à MESURER
en shadow**, pas un générateur de trades. GOLD n'est PAS tradé avec Tik
(hit rate mesuré 4,8 %, Garde-fou 2-bis) — ce flash ne change rien à ça.

## 2. Décision

`analyze_flash_gold()` dans `scoring/flash_engine.py`, **miroir assumé** de
`analyze_flash_btc` (duplication volontaire, comme swing/flash : le chemin BTC
mesuré reste intouché — zéro risque de régression). Différences :

| Sujet | Décision | Pourquoi |
|---|---|---|
| Données | klines 1m + depth + aggTrades **PAXGUSDT** Binance | Temps réel ; Yahoo reste la source du swing GOLD (ADR-005 inchangé) |
| Fraîcheur | âge du dernier kline ≤ 180 s, sinon skip | Pas de flux WS PAXG (contrairement à `tik.last_price.BTC`) |
| Heures de marché | **skip du vendredi 21:00 UTC au dimanche 22:00 UTC** (`is_gold_market_open`) | PAXG cote 24/7 mais l'or réel ferme : un signal « or » sans sous-jacent ancré serait trompeur. Jours fériés US non gérés (approximation assumée) |
| Crédibilité source | `binance_paxg_klines_1m` = **0.80** (< 0.90 BTC) | Prime/décote du proxy + carnet moins liquide |
| Overlays | mêmes fonctions/sources (`binance_orderbook`/`binance_aggtrades`) | Réutilisation ; un split de crédibilité PAXG-spécifique est différé (dette documentée) |
| Émission | transitions + heartbeat 30 min, clé `tik.flash.last_direction.GOLD` | Pattern anti-flood ADR-005 |
| Scheduler | job `flash_gold` toutes les 5 min, LLM exclu (comme flash BTC, fix A1) | Symétrie |
| **Mesure** | track record ET hit rate flash GOLD mesurés sur **klines PAXG Binance** (`fetch_paxg_history`) | **Cohérence source→mesure** : le signal naît sur PAXG, il est évalué sur PAXG. L'ancien fail-fast 400 « pas de flash GOLD » ne reste que pour micro GOLD |
| advisory | `proxy: "PAXGUSDT (r≈0.975 vs GC=F)"` | Traçabilité honnête dans chaque signal |

## 3. Risques connus (honnêtes)

1. **Le proxy peut décrocher** : r=0,975 mesuré sur 1h en régime calme ; en stress
   (rachats PAXG, dépeg partiel), le flash « or » refléterait PAXG, pas l'or.
   L'`advisory.proxy` le rappelle sur chaque signal.
2. **Liquidité fine** : le carnet PAXG est ~100× plus mince que BTCUSDT → OBI et
   agression plus bruités. Les seuils hérités du BTC ne sont PAS recalibrés —
   à re-regarder si le moteur sur-émet ou sous-émet (mesure d'abord).
3. **Espérance d'edge nulle** (cf. §1) : interdiction de re-tuner le seuil 0,30
   pour « améliorer » un hit rate flash (constat 2026-07-02, overfitting).
4. Fenêtres de mesure chevauchantes, un seul régime : mêmes caveats que le
   backtest flash BTC.

## 4. Critère de mesure

Après ≥ 2 semaines d'émission : étendre `backtest_flash.py` à GOLD/PAXG
(paramétrer le symbole) et mesurer hit/gain vs Always LONG/SHORT/NEUTRAL +
test apparié — même protocole que le constat flash BTC. Verdict écrit.
Réversibilité : retirer le job `flash_gold` du scheduler = extinction propre.
