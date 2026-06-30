"""Ingester recommandations techniques TradingView (MODE SHADOW — contexte, ADR-031).

⚠ SHADOW STRICT (ADR-031) : collecte les **recommandations techniques** que
TradingView calcule (note agrégée Achat fort → Vente forte + compteurs
oscillateurs / moyennes mobiles) et les stocke dans Redis. **Aucun overlay n'est
branché** : il n'existe volontairement PAS de `_enrich_with_tradingview` dans les
moteurs de scoring, et aucun toggle de config. Tant que rien n'est écrit côté
engine, ces clés Redis n'influencent AUCUN signal (direction / véracité /
conviction strictement inchangées) — elles ne font qu'accumuler de l'historique
et alimenter une carte de contexte dans le dashboard.

Deux familles, conformément à la demande « différenciation macro / micro », sur
les **deux actifs tradés (BTC et GOLD)** :

- **MACRO** (contexte macro-économique, commun aux deux actifs) : posture
  technique du dollar (DXY), du S&P 500, du taux US 10 ans, de l'or et de la
  volatilité (VIX), en timeframe journalier (1D). Répond à « dans quel régime
  macro est-on, vu par la techno ? ».
- **MICRO** (microstructure, par actif) : posture technique du BTC/USDT et de
  l'or (XAU/USD) sur eux-mêmes, en timeframes courts (5 min, 15 min, 1 h).
  Répond à « comment l'actif est-il positionné à court terme ? ».

⚠ NE PAS ENRÔLER sur le `combined_bias`. Double raison documentée dans l'ADR-031 :
(1) Tik est en NO-GO directionnel officiel (2026-05-27, aucun edge prouvé) ;
(2) ce sont des recommandations d'**analyse technique** — Tik calcule DÉJÀ ses
propres indicateurs RSI/MACD/EMA, mais à **poids 0** (ADR-018, OSINT pur), donc
risque de **redondance**, pas une nouvelle famille d'edge. Comme toute source, à
MESURER ≥ 2 semaines en shadow (cf. CLAUDE.md §8) avant toute décision d'usage.

Source : bibliothèque non-officielle `tradingview-ta` (scrape `scanner.tradingview.com`).
Gratuit, sans clé. ⚠ Fragile par nature (peut casser si TradingView change son
site) : chaque cible est best-effort, un échec ne casse jamais le reste du
pipeline. La lib est **synchrone** (requests) → chaque appel tourne dans un thread
via `asyncio.to_thread` pour ne pas bloquer l'event loop.
"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from redis.asyncio import Redis
from tradingview_ta import TA_Handler

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()


@dataclass(frozen=True)
class TVTarget:
    """Une cible TradingView à interroger (un instrument × un timeframe)."""

    label: str  # libellé court affiché ("DXY", "BTC 15m")
    basket: str  # "macro" | "micro"
    screener: str  # "cfd" | "america" | "crypto" (catégorie TradingView)
    exchange: str  # "TVC" | "SP" | "BINANCE"
    symbol: str  # "DXY" | "SPX" | "BTCUSDT"
    interval: str  # Interval.* ("1d", "5m"…) — chaîne attendue par la lib


# --- Panier MACRO (contexte macro-économique, timeframe journalier) ---
# Symboles / screeners vérifiés contre la convention TradingView. Si l'un d'eux
# ne résout pas côté runtime (log `tradingview.target.error`), ajuster ici.
MACRO_TARGETS: list[TVTarget] = [
    TVTarget("DXY", "macro", "cfd", "TVC", "DXY", "1d"),  # dollar index
    TVTarget("S&P 500", "macro", "america", "SP", "SPX", "1d"),  # actions US
    TVTarget("US 10Y", "macro", "cfd", "TVC", "US10Y", "1d"),  # taux 10 ans
    TVTarget("Or", "macro", "cfd", "TVC", "GOLD", "1d"),  # or spot
    TVTarget("VIX", "macro", "cfd", "TVC", "VIX", "1d"),  # volatilité
]

# --- Panier MICRO (microstructure par actif, timeframes courts) ---
# Un panier par entité tradée. GOLD via OANDA:XAUUSD (spot continu, bonne donnée
# intraday) ; c'est du CONTEXTE technique indépendant de Yahoo, donc compatible
# micro contrairement au flash GOLD interne (ADR-005, bloqué par le délai Yahoo).
MICRO_TARGETS: dict[str, list[TVTarget]] = {
    "BTC": [
        TVTarget("BTC 5m", "micro", "crypto", "BINANCE", "BTCUSDT", "5m"),
        TVTarget("BTC 15m", "micro", "crypto", "BINANCE", "BTCUSDT", "15m"),
        TVTarget("BTC 1h", "micro", "crypto", "BINANCE", "BTCUSDT", "1h"),
    ],
    "GOLD": [
        TVTarget("Or 5m", "micro", "forex", "OANDA", "XAUUSD", "5m"),
        TVTarget("Or 15m", "micro", "forex", "OANDA", "XAUUSD", "15m"),
        TVTarget("Or 1h", "micro", "forex", "OANDA", "XAUUSD", "1h"),
    ],
}

REDIS_KEY_MACRO = "tik.tradingview.macro"
REDIS_HISTORY_MACRO = "tik.tradingview.macro.history"
REDIS_KEY_MICRO_TPL = "tik.tradingview.micro.{entity}"  # {entity} = btc | gold
REDIS_HISTORY_MICRO_TPL = "tik.tradingview.micro.{entity}.history"
REDIS_TTL_S = 6 * 3600  # tolérance large au-delà du cycle (30 min)
HISTORY_MAX = 2000  # ~41 jours à 1 snapshot / 30 min


def _safe_float(value: object) -> float | None:
    """Convertit en float arrondi, None si invalide/absent."""
    if value is None:
        return None
    try:
        return round(float(value), 4)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _build_item(target: TVTarget, analysis: object) -> dict | None:
    """Normalise un objet Analysis TradingView en dict compact.

    Retourne None si l'analyse est inexploitable (None ou sans summary) — la lib
    renvoie None quand TradingView n'a pas assez de données pour l'instrument.
    """
    summary = getattr(analysis, "summary", None)
    if not isinstance(summary, dict) or not summary.get("RECOMMENDATION"):
        return None
    oscillators = getattr(analysis, "oscillators", None) or {}
    moving_averages = getattr(analysis, "moving_averages", None) or {}
    indicators = getattr(analysis, "indicators", None) or {}
    return {
        "label": target.label,
        "symbol": f"{target.exchange}:{target.symbol}",
        "interval": target.interval,
        # Note agrégée TradingView (STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL)
        "recommendation": summary.get("RECOMMENDATION"),
        "buy": summary.get("BUY"),
        "sell": summary.get("SELL"),
        "neutral": summary.get("NEUTRAL"),
        # Détail oscillateurs vs moyennes mobiles (souvent divergents = info utile)
        "osc_recommendation": oscillators.get("RECOMMENDATION"),
        "ma_recommendation": moving_averages.get("RECOMMENDATION"),
        # Quelques valeurs brutes pour le contexte (pas pour décider)
        "rsi": _safe_float(indicators.get("RSI")),
        "close": _safe_float(indicators.get("close")),
    }


class TradingViewTAIngester(BaseIngester):
    """Polle les recommandations techniques TradingView (macro + micro) — SHADOW."""

    name = "tradingview_ta_ingester"
    layer = 1  # données de marché / techniques

    def __init__(
        self,
        redis: Redis,
        interval_s: int = 1800,
        request_timeout_s: float = 15.0,
    ) -> None:
        self.redis = redis
        self.interval_s = interval_s
        self.request_timeout_s = request_timeout_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        # Ne lève jamais : un échec ici ne doit pas empêcher les autres
        # ingesters de démarrer (cf. boucle `for ing in ingesters` du runner).
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "tradingview_ta.ingester.started",
            interval_s=self.interval_s,
            n_macro=len(MACRO_TARGETS),
            micro_entities=list(MICRO_TARGETS.keys()),
            mode="shadow",
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("tradingview_ta.ingester.stopped")

    def _fetch_target_sync(self, target: TVTarget) -> dict | None:
        """Appel synchrone TradingView pour une cible (exécuté dans un thread).

        Best-effort : toute exception (instrument inconnu, réseau, parsing lib)
        est capturée → retourne None, l'ingester continue avec les autres cibles.
        """
        try:
            handler = TA_Handler(
                symbol=target.symbol,
                screener=target.screener,
                exchange=target.exchange,
                interval=target.interval,
                timeout=self.request_timeout_s,
            )
            analysis = handler.get_analysis()
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "tradingview_ta.target.error",
                label=target.label,
                symbol=f"{target.exchange}:{target.symbol}",
                error=str(exc),
            )
            return None
        return _build_item(target, analysis)

    async def _fetch_basket(self, targets: list[TVTarget]) -> list[dict]:
        """Interroge séquentiellement toutes les cibles d'un panier (best-effort).

        Séquentiel (et non en parallèle) pour garder une empreinte réseau lisible
        sur un endpoint non-officiel et éviter tout burst — ~0.5 s × N cibles est
        négligeable sur un cycle de 30 min.
        """
        items: list[dict] = []
        for target in targets:
            item = await asyncio.to_thread(self._fetch_target_sync, target)
            if item is not None:
                items.append(item)
        return items

    async def _publish(self, key: str, history_key: str, payload: dict) -> None:
        try:
            blob = json.dumps(payload)
            await self.redis.setex(key, REDIS_TTL_S, blob)
            await self.redis.lpush(history_key, blob)
            await self.redis.ltrim(history_key, 0, HISTORY_MAX - 1)
        except Exception as exc:  # noqa: BLE001
            log.warning("tradingview_ta.redis.error", key=key, error=str(exc))

    async def _cycle(self) -> None:
        fetched_at = datetime.now(tz=UTC).isoformat()

        macro_items = await self._fetch_basket(MACRO_TARGETS)
        if macro_items:
            await self._publish(
                REDIS_KEY_MACRO,
                REDIS_HISTORY_MACRO,
                {
                    "source": "tradingview_ta",
                    "basket": "macro",
                    "mode": "shadow",
                    "items": macro_items,
                    "fetched_at": fetched_at,
                },
            )
            log.info("tradingview_ta.published", basket="macro", n=len(macro_items))
        else:
            log.info("tradingview_ta.no_data", basket="macro")

        for entity, targets in MICRO_TARGETS.items():
            micro_items = await self._fetch_basket(targets)
            key = REDIS_KEY_MICRO_TPL.format(entity=entity.lower())
            history_key = REDIS_HISTORY_MICRO_TPL.format(entity=entity.lower())
            if micro_items:
                await self._publish(
                    key,
                    history_key,
                    {
                        "source": "tradingview_ta",
                        "basket": "micro",
                        "entity": entity,
                        "mode": "shadow",
                        "items": micro_items,
                        "fetched_at": fetched_at,
                    },
                )
                log.info(
                    "tradingview_ta.published",
                    basket="micro",
                    entity=entity,
                    n=len(micro_items),
                )
            else:
                log.info("tradingview_ta.no_data", basket="micro", entity=entity)

    async def _run(self) -> None:
        while self._running:
            try:
                await self._cycle()
            except Exception as exc:  # noqa: BLE001
                # Garde-fou ultime : un cycle ne doit jamais tuer la boucle.
                log.warning("tradingview_ta.cycle.error", error=str(exc))
            await asyncio.sleep(self.interval_s)
