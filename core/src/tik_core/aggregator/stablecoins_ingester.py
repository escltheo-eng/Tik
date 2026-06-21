"""Stablecoins ingester — couche 4 (liquidité crypto-native objective, CONTEXTE).

Mesure la **masse totale de stablecoins** (USDT, USDC, …) et sa tendance, à partir
de DefiLlama (gratuit, sans clé). C'est la « poudre sèche » du marché crypto : du
cash en USD parqué sur les rails on-chain, prêt à être déployé. Sa masse qui monte
= du capital qui entre (potentiel d'achat) ; qui descend = des sorties.

Famille de données **NON-sentiment** (cf. CLAUDE.md §8 : « l'edge, s'il existe, vit
dans des familles DIFFÉRENTES du sentiment »), différente aussi de la liquidité des
banques centrales (ADR-028) et du stress de marché (ADR-030). 3e des familles macro
de contexte prévues au backlog.

⚠️ CONTEXTE STRICT (ADR-031) : ne touche JAMAIS le `combined_bias`, la veracity ou la
direction des signaux. Aucun overlay branché, aucun toggle. C'est de l'affichage de
chiffres datés, PAS une prédiction (le macro/la liquidité ne prédisent pas le BTC —
mesuré 2026-06-19). Si un jour une mesure shadow ≥ 2 sem démontrait une valeur
prédictive INDÉPENDANTE des sources actuelles (IC vs rendements forward, gain apparié
vs Always SHORT), un overlay pourrait être proposé dans un ADR dédié — JAMAIS avant.

Source : DefiLlama Stablecoins API (https://stablecoins.llama.fi), **sans clé**.
Joignabilité depuis le VPS Hetzner vérifiée 2026-06-21 (HTTP 200, ~114 ms ; total
≈ 313 Md$ USD-pegged). Limite assumée : l'accès sans clé n'est pas garanti
contractuellement — `source_health` (clé `tik.macro.stablecoins`) le détecterait.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from datetime import UTC, datetime

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.utils.time import now_utc

log = structlog.get_logger()

CHART_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
STABLECOINS_URL = "https://stablecoins.llama.fi/stablecoins?includePrices=false"
REDIS_KEY = "tik.macro.stablecoins"

# Seuil (transparent mais arbitraire) du label de tendance sur 30 j. La masse de
# stablecoins bouge lentement (~0,5-1 %/mois en régime calme) → ±0,5 % = bande neutre.
TREND_BAND_30D = 0.005


# ---------------------------------------------------------------------------
# Fonctions PURES (sans I/O) — unit-testables (test_stablecoins.py)
# ---------------------------------------------------------------------------


def parse_chart_series(raw: list) -> list[tuple[str, float]]:
    """DefiLlama /stablecoincharts/all → série (date_iso, total_busd) triée asc.

    `total_busd` = `totalCirculatingUSD.peggedUSD` / 1e9 (valeur USD de tous les
    stablecoins USD-pegged, en milliards). Ignore les points malformés.
    """
    out: list[tuple[str, float]] = []
    for pt in raw or []:
        try:
            ts = int(pt["date"])
            tc = pt.get("totalCirculatingUSD") or {}
            usd = tc.get("peggedUSD")
            if usd is None:
                continue
            d = datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
            out.append((d, round(float(usd) / 1e9, 2)))
        except (KeyError, ValueError, TypeError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def compute_stablecoin_regime(series: list[tuple[str, float]]) -> dict:
    """Niveau + deltas + tendance de la masse de stablecoins (Md$), sur série quotidienne.

    `trend` ∈ {expansion, contraction, neutral, unknown} décrit le SENS du flux de
    capital vers les rails crypto (masse qui monte = entrées / poudre sèche, descend
    = sorties), CONTEXTUEL — jamais une prédiction de prix.
    """
    if not series:
        return {"available": False}
    values = [v for _, v in series]
    latest_date, latest = series[-1]
    out: dict = {
        "available": True,
        "as_of": latest_date,
        "total_busd": latest,
        "total_tusd": round(latest / 1000.0, 3),
        "n_days": len(series),
        "context_only": True,
    }

    def _delta(n: int) -> float | None:
        return round(latest - values[-1 - n], 2) if len(values) > n else None

    out["delta_7d_busd"] = _delta(7)
    out["delta_30d_busd"] = _delta(30)

    d30 = out["delta_30d_busd"]
    if d30 is None or not latest:
        out["trend"] = "unknown"
        out["pct_30d"] = None
    else:
        pct = d30 / latest
        out["pct_30d"] = round(pct * 100, 2)
        if pct > TREND_BAND_30D:
            out["trend"] = "expansion"  # masse en hausse = capital entrant
        elif pct < -TREND_BAND_30D:
            out["trend"] = "contraction"  # masse en baisse = sorties
        else:
            out["trend"] = "neutral"

    window = values[-90:]
    if len(window) >= 30:
        mu = statistics.mean(window)
        sd = statistics.pstdev(window)
        out["zscore_90d"] = round((latest - mu) / sd, 2) if sd > 0 else 0.0
    else:
        out["zscore_90d"] = None
    return out


def parse_breakdown(raw: dict, top_n: int = 5) -> list[dict]:
    """DefiLlama /stablecoins → top N stablecoins par circulating (Md$ + part %).

    `share` = part du stablecoin dans la masse USD-pegged totale (somme des
    `circulating.peggedUSD`). Transparence : montre la concentration (USDT domine).
    """
    pa = (raw or {}).get("peggedAssets") or []

    def circ(x: dict) -> float:
        c = x.get("circulating") or {}
        v = c.get("peggedUSD")
        return float(v) if isinstance(v, (int, float)) else 0.0

    total = sum(circ(x) for x in pa) or 1.0
    top = sorted(pa, key=circ, reverse=True)[:top_n]
    return [
        {
            "symbol": x.get("symbol"),
            "name": x.get("name"),
            "circulating_busd": round(circ(x) / 1e9, 2),
            "share": round(circ(x) / total, 4),
        }
        for x in top
    ]


# ---------------------------------------------------------------------------
# Ingester (I/O DefiLlama + Redis)
# ---------------------------------------------------------------------------


class StablecoinsIngester(BaseIngester):
    """Polle DefiLlama, calcule la masse + tendance des stablecoins, publie le blob."""

    name = "stablecoins_ingester"
    layer = 4

    def __init__(
        self,
        redis: Redis,
        interval_s: int = 6 * 3600,
        ttl_s: int = 36 * 3600,
    ) -> None:
        self.redis = redis
        self.interval_s = interval_s
        self.ttl_s = ttl_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("stablecoins.ingester.started", interval_s=self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("stablecoins.ingester.stopped")

    async def _fetch_json(self, client: httpx.AsyncClient, url: str):
        """GET JSON. None si erreur (best-effort, sections indépendantes)."""
        try:
            r = await client.get(url, timeout=20.0)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log.warning("stablecoins.fetch.error", url=url, error=str(exc))
            return None

    async def build_blob(self, client: httpx.AsyncClient) -> dict:
        """Construit le blob `tik.macro.stablecoins`."""
        blob: dict = {
            "source": "defillama_stablecoins",
            "fetched_at": now_utc().isoformat(),
            "context_only": True,
        }

        chart = await self._fetch_json(client, CHART_URL)
        series = parse_chart_series(chart) if isinstance(chart, list) else []
        regime = compute_stablecoin_regime(series)
        blob.update(regime)

        sb = await self._fetch_json(client, STABLECOINS_URL)
        blob["breakdown"] = parse_breakdown(sb) if isinstance(sb, dict) else []

        return blob

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                try:
                    blob = await self.build_blob(client)
                    await self.redis.set(REDIS_KEY, json.dumps(blob), ex=self.ttl_s)
                    log.info(
                        "stablecoins.published",
                        total_tusd=blob.get("total_tusd"),
                        trend=blob.get("trend"),
                        delta_30d_busd=blob.get("delta_30d_busd"),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("stablecoins.cycle.error", error=str(exc))
                await asyncio.sleep(self.interval_s)
