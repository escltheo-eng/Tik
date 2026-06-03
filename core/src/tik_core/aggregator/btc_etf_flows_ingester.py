"""Flux ETF spot BTC US (couche 1 — données de flux institutionnel, MODE SHADOW).

⚠ SHADOW (ADR-024) : collecte les FLUX QUOTIDIENS des ETF spot Bitcoin US
(inflow/outflow net, encours, détail par fonds) et les stocke dans Redis.
**Aucun overlay n'est branché** : il n'existe volontairement PAS de
`_enrich_with_btc_etf_flows` dans les moteurs de scoring, et aucun toggle de
config. Tant que rien n'est écrit côté engine, ces clés Redis n'influencent
AUCUN signal (direction / véracité / conviction strictement inchangées) — elles
ne font qu'accumuler de l'historique.

But du shadow : c'est une famille de données **différente du sentiment retardé**
(Fear & Greed, news, Reddit, CoinGecko) ET du positionnement dérivés (ADR-023).
Les flux ETF sont de la demande institutionnelle réelle (>50 G USD d'encours
post-janvier 2024). Hypothèse à MESURER (pas à supposer) : un inflow net
persistant a-t-il une valeur prédictive indépendante des sources actuelles, ou
ne fait-il que suivre le prix (colinéaire au trend, comme le reste) ?

⚠ NE PAS ENRÔLER avant : ≥ 2 semaines de collecte + mesure (IC vs rendements
forward via `measure_btc_etf_flows.py`, indépendance vs sources existantes, gain
apparié vs Always SHORT). Cf. CLAUDE.md §8 « mesurer chaque nouvelle source en
shadow ≥ 2 semaines AVANT tout enrôlement sur le combined_bias ».

Source : SoSoValue openapi v2 (https://api.sosovalue.xyz), type `us-btc-spot`,
**sans clé API**. Joignabilité depuis le VPS Hetzner vérifiée 2026-06-03
(currentEtfDataMetrics + historicalInflowChart → HTTP 200, code:0, données
réelles). Farside bloque les bots (403 vérifié, backlog V1.3), CoinGlass est
payant (aucun free tier) → SoSoValue est la seule source gratuite qui répond.
Limite assumée : l'accès sans clé n'est pas garanti contractuellement et peut se
fermer un jour — `source_health` (clé `tik.etf.btc`) le détecterait (stale/missing).
"""

import asyncio
import json
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester

log = structlog.get_logger()

SOSOVALUE_BASE = "https://api.sosovalue.xyz/openapi/v2/etf"
CURRENT_METRICS_URL = f"{SOSOVALUE_BASE}/currentEtfDataMetrics"
HISTORICAL_CHART_URL = f"{SOSOVALUE_BASE}/historicalInflowChart"
ETF_TYPE = "us-btc-spot"  # ETF spot Bitcoin US (IBIT, FBTC, GBTC, …)

USER_AGENT = "tik-osint-bot/0.1 (research; contact escltheo@gmail.com)"
REDIS_KEY_TPL = "tik.etf.{entity}"  # snapshot du dernier jour publié
REDIS_HISTORY_KEY_TPL = "tik.etf.{entity}.history"  # série quotidienne complète
# 4 jours : un flux publié le vendredi soir doit survivre à un week-end + un
# jour férié US (lundi) sans nouvelle donnée. L'ingester ré-écrit fetched_at à
# chaque cycle même si la donnée du jour n'a pas changé → la clé reste fraîche
# tant que l'ingester tourne ; le TTL n'est qu'un filet si l'ingester meurt.
REDIS_TTL_S = 4 * 24 * 3600
HISTORY_CAP = 500  # ~16 mois de jours ouvrés US — borne la taille de la clé


def _unwrap(value: object) -> float | None:
    """Convertit en float un champ SoSoValue, enveloppé ou brut.

    SoSoValue enveloppe ses nombres dans `{value, lastUpdateDate, status}`
    (currentEtfDataMetrics) mais renvoie des floats bruts dans la série
    historique (historicalInflowChart). On gère les deux. None si invalide.
    """
    if isinstance(value, dict):
        value = value.get("value")
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _data_date(value: object) -> str | None:
    """Extrait `lastUpdateDate` d'un champ enveloppé SoSoValue (sinon None)."""
    if isinstance(value, dict):
        d = value.get("lastUpdateDate")
        return d if isinstance(d, str) else None
    return None


def _extract_data(envelope: object) -> object | None:
    """SoSoValue enveloppe : `{code, msg, data}`. `code == 0` = succès.

    Retourne `data` si succès, None sinon (erreur applicative ou payload
    illisible). Distingue un 200 HTTP « code applicatif erreur » d'un vrai succès.
    """
    if not isinstance(envelope, dict):
        return None
    if envelope.get("code") != 0:
        return None
    return envelope.get("data")


def _build_funds(raw: object) -> list[dict]:
    """Détail par fonds (IBIT, FBTC, …) à partir de `data.list`.

    On ne garde que l'essentiel (ticker, émetteur, flux net du jour, flux cumulé,
    encours) pour borner la taille du payload Redis. Ignore les entrées mal formées.
    """
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for f in raw:
        if not isinstance(f, dict):
            continue
        ticker = f.get("ticker")
        if not isinstance(ticker, str):
            continue
        institute = f.get("institute")
        out.append(
            {
                "ticker": ticker,
                "institute": institute.strip() if isinstance(institute, str) else None,
                "daily_net_inflow_usd": _unwrap(f.get("dailyNetInflow")),
                "cum_net_inflow_usd": _unwrap(f.get("cumNetInflow")),
                "net_assets_usd": _unwrap(f.get("netAssets")),
            }
        )
    return out


def _build_snapshot(metrics: dict | None, fetched_at_iso: str) -> dict | None:
    """Assemble le snapshot du dernier jour à partir de `currentEtfDataMetrics.data`.

    Retourne None si la donnée cœur (flux net quotidien ET cumulé) est absente —
    inutile de publier un snapshot vide.
    """
    if not isinstance(metrics, dict):
        return None

    daily_net_inflow = _unwrap(metrics.get("dailyNetInflow"))
    cum_net_inflow = _unwrap(metrics.get("cumNetInflow"))
    total_net_assets = _unwrap(metrics.get("totalNetAssets"))
    total_holdings = _unwrap(metrics.get("totalTokenHoldings"))
    daily_value_traded = _unwrap(metrics.get("dailyTotalValueTraded"))

    if daily_net_inflow is None and cum_net_inflow is None:
        return None

    # Prix BTC implicite = actifs nets / BTC détenus (NAV moyen par BTC, proche
    # du spot). Pratique pour aligner les flux sur le prix sans source externe.
    implied_btc_price = None
    if total_net_assets is not None and total_holdings not in (None, 0):
        implied_btc_price = round(total_net_assets / total_holdings, 2)

    data_date = _data_date(metrics.get("dailyNetInflow")) or _data_date(
        metrics.get("totalNetAssets")
    )
    funds = _build_funds(metrics.get("list"))

    return {
        "source": "sosovalue_btc_etf",
        "entity": "BTC",
        "data_date": data_date,  # jour de bourse US du flux (≠ fetched_at)
        "daily_net_inflow_usd": daily_net_inflow,
        "cum_net_inflow_usd": cum_net_inflow,
        "total_net_assets_usd": total_net_assets,
        "total_token_holdings_btc": total_holdings,
        "daily_value_traded_usd": daily_value_traded,
        "implied_btc_price": implied_btc_price,
        "n_funds": len(funds),
        "funds": funds,
        "fetched_at": fetched_at_iso,
    }


def _build_history(chart: object, fetched_at_iso: str, cap: int = HISTORY_CAP) -> dict | None:
    """Série quotidienne complète à partir de `historicalInflowChart.data`.

    SoSoValue renvoie tout l'historique à chaque appel → on l'écrit en entier
    (auto-cicatrisant : pas d'accumulation manuelle, pas de doublon de date).
    Trie par date décroissante et cap aux `cap` jours les plus récents. None si
    aucune ligne exploitable.
    """
    if not isinstance(chart, list):
        return None
    rows: list[dict] = []
    for row in chart:
        if not isinstance(row, dict):
            continue
        date = row.get("date")
        net = _unwrap(row.get("totalNetInflow"))
        if not isinstance(date, str) or net is None:
            continue
        rows.append(
            {
                "date": date,
                "net_inflow_usd": net,
                "cum_net_inflow_usd": _unwrap(row.get("cumNetInflow")),
                "total_net_assets_usd": _unwrap(row.get("totalNetAssets")),
                "value_traded_usd": _unwrap(row.get("totalValueTraded")),
            }
        )
    if not rows:
        return None
    rows.sort(key=lambda r: r["date"], reverse=True)
    rows = rows[:cap]
    return {
        "source": "sosovalue_btc_etf",
        "entity": "BTC",
        "fetched_at": fetched_at_iso,
        "n_days": len(rows),
        "daily": rows,
    }


class BtcEtfFlowsIngester(BaseIngester):
    """Polle les flux ETF spot BTC US (SoSoValue) et les stocke (SHADOW)."""

    name = "btc_etf_flows_ingester"
    layer = 1  # données de flux/marché (comme binance_derivatives)

    def __init__(
        self,
        redis: Redis,
        entity: str = "BTC",
        interval_s: int = 6 * 3600,
        history_cap: int = HISTORY_CAP,
    ) -> None:
        self.redis = redis
        self.entity = entity
        self.interval_s = interval_s  # 6 h : les flux ETF sont quotidiens, pas intra-day
        self.history_cap = history_cap
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
            "btc_etf_flows.ingester.started",
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
        log.info("btc_etf_flows.ingester.stopped")

    async def _get_json(self, client: httpx.AsyncClient, url: str, payload: dict) -> object | None:
        """POST best-effort : retourne le JSON décodé ou None (jamais d'exception)."""
        try:
            r = await client.post(url, json=payload, timeout=20.0)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("btc_etf_flows.fetch.error", url=url, error=str(exc))
            return None

    async def _fetch(self, client: httpx.AsyncClient) -> tuple[dict | None, dict | None]:
        fetched_at = datetime.now(tz=UTC).isoformat()
        payload = {"type": ETF_TYPE}
        metrics_env = await self._get_json(client, CURRENT_METRICS_URL, payload)
        chart_env = await self._get_json(client, HISTORICAL_CHART_URL, payload)
        metrics = _extract_data(metrics_env)
        chart = _extract_data(chart_env)
        snap = _build_snapshot(metrics if isinstance(metrics, dict) else None, fetched_at)
        history = _build_history(chart, fetched_at, self.history_cap)
        return snap, history

    async def _run(self) -> None:
        async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
            while self._running:
                snap, history = await self._fetch(client)
                if snap is not None:
                    try:
                        await self.redis.setex(self.redis_key, REDIS_TTL_S, json.dumps(snap))
                        if history is not None:
                            # Série persistante (pas de TTL) : survit à une coupure
                            # de la source au-delà du TTL du snapshot.
                            await self.redis.set(self.history_key, json.dumps(history))
                    except Exception as exc:  # noqa: BLE001
                        log.warning("btc_etf_flows.redis.error", error=str(exc))
                    log.info(
                        "btc_etf_flows.published",
                        data_date=snap["data_date"],
                        daily_net_inflow_usd=snap["daily_net_inflow_usd"],
                        cum_net_inflow_usd=snap["cum_net_inflow_usd"],
                        n_funds=snap["n_funds"],
                    )
                else:
                    log.info("btc_etf_flows.no_data")
                await asyncio.sleep(self.interval_s)
