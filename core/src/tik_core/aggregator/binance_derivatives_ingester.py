"""Binance derivatives positioning ingester (couche 1 — données dérivés, MODE SHADOW).

⚠ SHADOW (ADR-023) : collecte le POSITIONNEMENT sur le perpétuel BTCUSDT de
Binance (funding rate, open interest, ratio long/short retail ET top traders) et
le stocke dans Redis. **Aucun overlay n'est branché** : il n'existe volontairement
PAS de `_enrich_with_binance_derivatives` dans les moteurs de scoring, et aucun
toggle de config. Tant que rien n'est écrit côté engine, cette clé Redis
n'influence AUCUN signal (direction / véracité / conviction strictement
inchangées) — elle ne fait qu'accumuler de l'historique.

But du shadow : c'est une famille de données **différente du sentiment retardé**
(Fear & Greed, news, Reddit, CoinGecko). Le positionnement dérivés est de l'argent
réel + du levier engagés. Hypothèse à MESURER (pas à supposer) : a-t-il une valeur
prédictive indépendante des sources actuelles ? Le funding extrême précède souvent
les squeezes (signal contrarian) ; l'open interest mesure la conviction ; la
divergence retail vs top traders est un signal de positionnement classique.

⚠ NE PAS ENRÔLER avant : ≥ 2 semaines de collecte + mesure (IC vs rendements
forward via `measure_btc_derivatives.py`, indépendance vs sources existantes,
gain apparié vs Always SHORT). Cf. CLAUDE.md §8 « mesurer chaque nouvelle source
en shadow ≥ 2 semaines AVANT tout enrôlement sur le combined_bias ». Le mapping
dérivés → bias (contrarian aux extrêmes ? OI comme multiplicateur ?) sera décidé
par la mesure, PAS deviné maintenant.

Source : API publique Binance USDⓈ-M futures (https://fapi.binance.com), sans clé.
Connectivité depuis le VPS Hetzner vérifiée 2026-06-03 (tous endpoints HTTP 200,
y compris les /futures/data/* parfois géo-restreints). 4 appels/heure, très
largement sous les limites du free tier public.
"""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

FAPI_BASE = "https://fapi.binance.com"
PREMIUM_INDEX_URL = f"{FAPI_BASE}/fapi/v1/premiumIndex"
OPEN_INTEREST_URL = f"{FAPI_BASE}/fapi/v1/openInterest"
GLOBAL_LS_URL = f"{FAPI_BASE}/futures/data/globalLongShortAccountRatio"
TOP_LS_URL = f"{FAPI_BASE}/futures/data/topLongShortAccountRatio"

USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"
REDIS_KEY_TPL = "tik.deriv.binance.{entity}"  # snapshot courant
REDIS_HISTORY_KEY_TPL = "tik.deriv.binance.{entity}.history"  # série temporelle cappée
REDIS_TTL_S = 25 * 3600  # tolérance au-delà du cycle horaire
HISTORY_MAX = 2000  # ~83 jours à 1 snapshot/heure


def _safe_float(value: object) -> float | None:
    """Convertit en float, retourne None si invalide (champ Binance = str)."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _build_snapshot(
    premium: dict | None,
    open_interest: dict | None,
    global_ls: list | None,
    top_ls: list | None,
    fetched_at_iso: str,
) -> dict | None:
    """Assemble un snapshot dérivés à partir des 4 réponses Binance.

    Best-effort : tout sous-appel échoué (None) laisse ses champs à None, le
    snapshot est quand même produit avec ce qui a réussi. Retourne None
    seulement si AUCUNE donnée cœur n'est disponible (ni funding ni OI) —
    inutile de publier un snapshot vide.
    """
    funding_rate = mark_price = next_funding_time = None
    if isinstance(premium, dict):
        funding_rate = _safe_float(premium.get("lastFundingRate"))
        mark_price = _safe_float(premium.get("markPrice"))
        next_funding_time = premium.get("nextFundingTime")

    oi_btc = oi_usd = None
    if isinstance(open_interest, dict):
        oi_btc = _safe_float(open_interest.get("openInterest"))
        if oi_btc is not None and mark_price is not None:
            oi_usd = round(oi_btc * mark_price, 2)

    def _ls_fields(payload: list | None) -> tuple[float | None, float | None, float | None]:
        # Les endpoints /futures/data renvoient une liste ; on prend le plus récent.
        if not isinstance(payload, list) or not payload:
            return None, None, None
        last = payload[-1]
        if not isinstance(last, dict):
            return None, None, None
        return (
            _safe_float(last.get("longShortRatio")),
            _safe_float(last.get("longAccount")),
            _safe_float(last.get("shortAccount")),
        )

    ls_ratio_global, long_global, short_global = _ls_fields(global_ls)
    ls_ratio_top, long_top, short_top = _ls_fields(top_ls)

    # Données cœur minimales pour qu'un snapshot vaille la peine d'être stocké.
    if funding_rate is None and oi_btc is None:
        return None

    return {
        "source": "binance_derivatives",
        "entity": "BTC",
        "funding_rate": funding_rate,  # ex. 0.00003704 (par intervalle de 8h)
        "mark_price": mark_price,
        "next_funding_time": next_funding_time,
        "open_interest_btc": oi_btc,
        "open_interest_usd": oi_usd,
        "long_short_ratio_global": ls_ratio_global,  # comptes retail
        "long_account_global": long_global,
        "short_account_global": short_global,
        "long_short_ratio_top": ls_ratio_top,  # top traders (« smart money »)
        "long_account_top": long_top,
        "short_account_top": short_top,
        "fetched_at": fetched_at_iso,
    }


class BinanceDerivativesIngester(BaseIngester):
    """Polle le positionnement dérivés Binance BTCUSDT et le stocke (SHADOW)."""

    name = "binance_derivatives_ingester"
    layer = 1  # données de marché (comme binance_trades)

    def __init__(
        self,
        redis: Redis,
        entity: str = "BTC",
        symbol: str = "BTCUSDT",
        interval_s: int = 3600,
    ) -> None:
        self.redis = redis
        self.entity = entity
        self.symbol = symbol
        self.interval_s = interval_s
        self.redis_key = REDIS_KEY_TPL.format(entity=entity.lower())
        self.history_key = REDIS_HISTORY_KEY_TPL.format(entity=entity.lower())
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        # Ne lève jamais : un échec ici ne doit pas empêcher les autres
        # ingesters de démarrer (cf. boucle `for ing in ingesters` du runner).
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info(
            "binance_derivatives.ingester.started",
            symbol=self.symbol,
            interval_s=self.interval_s,
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
        log.info("binance_derivatives.ingester.stopped")

    async def _get_json(self, client: httpx.AsyncClient, url: str, params: dict) -> object | None:
        """GET best-effort : retourne le JSON décodé ou None (jamais d'exception)."""
        try:
            r = await client.get(url, params=params, timeout=15.0)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("binance_derivatives.fetch.error", url=url, error=str(exc))
            return None

    async def _fetch(self, client: httpx.AsyncClient) -> dict | None:
        sym = {"symbol": self.symbol}
        ls_params = {"symbol": self.symbol, "period": "1h", "limit": 1}
        # Appels séquentiels (4/h, latence ~0.3s chacun → négligeable) ; garde
        # l'empreinte réseau lisible dans les logs et évite tout burst.
        premium = await self._get_json(client, PREMIUM_INDEX_URL, sym)
        open_interest = await self._get_json(client, OPEN_INTEREST_URL, sym)
        global_ls = await self._get_json(client, GLOBAL_LS_URL, ls_params)
        top_ls = await self._get_json(client, TOP_LS_URL, ls_params)
        return _build_snapshot(
            premium if isinstance(premium, dict) else None,
            open_interest if isinstance(open_interest, dict) else None,
            global_ls if isinstance(global_ls, list) else None,
            top_ls if isinstance(top_ls, list) else None,
            datetime.now(tz=UTC).isoformat(),
        )

    async def _run(self) -> None:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            while self._running:
                snap = await self._fetch(client)
                if snap is not None:
                    try:
                        payload = json.dumps(snap)
                        await self.redis.setex(self.redis_key, REDIS_TTL_S, payload)
                        await self.redis.lpush(self.history_key, payload)
                        await self.redis.ltrim(self.history_key, 0, HISTORY_MAX - 1)
                    except Exception as exc:  # noqa: BLE001
                        log.warning("binance_derivatives.redis.error", error=str(exc))
                    log.info(
                        "binance_derivatives.published",
                        funding_rate=snap["funding_rate"],
                        open_interest_btc=snap["open_interest_btc"],
                        ls_ratio_global=snap["long_short_ratio_global"],
                        ls_ratio_top=snap["long_short_ratio_top"],
                    )
                else:
                    log.info("binance_derivatives.no_data")
                await asyncio.sleep(self.interval_s)
