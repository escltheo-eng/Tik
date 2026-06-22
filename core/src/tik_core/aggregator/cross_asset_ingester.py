"""Cross-asset ingester — couche 4 (corrélations de marché objectives, CONTEXTE).

Mesure avec quoi le BTC **co-bouge** en ce moment : actions (S&P 500, Nasdaq), or,
dollar (DXY). Répond à la question « le BTC se comporte-t-il comme un actif risqué
(suit les actions), comme l'or, ou évolue-t-il tout seul ? ». Données : cours
journaliers Yahoo Finance (gratuit), corrélation de Pearson des rendements alignés.

Famille de données **NON-sentiment** (cf. CLAUDE.md §8). 4e et dernière des familles
macro de contexte prévues au backlog.

⚠️ CONTEXTE STRICT (ADR-032) : ne touche JAMAIS le `combined_bias`, la veracity ou la
direction. Une **corrélation n'est NI une prédiction NI une causalité** : elle décrit
un co-mouvement RÉCENT, qui peut s'inverser. On affiche un fait descriptif daté, pas
un signal. La liquidité/la macro ne prédisent pas le BTC (mesuré 2026-06-19).

⭐ Piège résolu : le BTC cote 7 j/7 (~93 points sur 3 mois) alors que les actions /
l'or / le DXY ne cotent qu'en semaine (~63). On ALIGNE donc chaque paire sur ses dates
communes AVANT de calculer les rendements et la corrélation (sinon décalage de dates =
corrélation fausse). Source Yahoo `query1.finance.yahoo.com/v8/finance/chart`,
joignabilité VPS vérifiée 2026-06-21 (HTTP 200 sur BTC-USD, ^GSPC, ^IXIC, GC=F, DX-Y.NYB).
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

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = "Mozilla/5.0 (compatible; TikBot/0.1; +https://tik.local)"
REDIS_KEY = "tik.macro.cross_asset"

BTC_SYMBOL = "BTC-USD"
# (symbole Yahoo, clé interne, libellé FR). Ordre = ordre d'affichage.
CROSS_ASSETS = [
    ("^GSPC", "sp500", "S&P 500"),
    ("^IXIC", "nasdaq", "Nasdaq"),
    ("GC=F", "gold", "Or"),
    ("DX-Y.NYB", "dxy", "Dollar (DXY)"),
]

RECENT_WINDOW = 30  # nb de paires de rendements récentes pour la corrélation « courante »
# Seuil (transparent mais arbitraire) du label de comportement.
BEHAVIOR_THRESHOLD = 0.25


# ---------------------------------------------------------------------------
# Fonctions PURES (sans I/O) — unit-testables (test_cross_asset.py)
# ---------------------------------------------------------------------------


def parse_chart(raw: dict) -> dict[str, float]:
    """JSON Yahoo chart → {date_iso: close}. Ignore les closes manquants (null)."""
    out: dict[str, float] = {}
    try:
        res = raw["chart"]["result"][0]
        ts = res["timestamp"]
        close = res["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        return out
    for t, c in zip(ts, close, strict=False):
        if c is None:
            continue
        try:
            d = datetime.fromtimestamp(int(t), tz=UTC).date().isoformat()
            out[d] = float(c)
        except (ValueError, TypeError):
            continue
    return out


def aligned_returns(base: dict[str, float], other: dict[str, float]) -> tuple[list[float], list[float]]:
    """Rendements journaliers de deux séries, ALIGNÉS sur leurs dates COMMUNES.

    Indispensable car le BTC cote 7 j/7 et les actifs TradFi seulement en semaine :
    on échantillonne les deux séries sur les dates où l'actif TradFi a une valeur, puis
    on calcule les rendements entre dates communes consécutives (le mouvement BTC du
    week-end est absorbé dans le rendement vendredi→lundi, comme pour l'actif).
    """
    common = sorted(set(base) & set(other))
    br: list[float] = []
    orr: list[float] = []
    for i in range(1, len(common)):
        b0, b1 = base[common[i - 1]], base[common[i]]
        o0, o1 = other[common[i - 1]], other[common[i]]
        if b0 and o0:
            br.append(b1 / b0 - 1.0)
            orr.append(o1 / o0 - 1.0)
    return br, orr


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Corrélation de Pearson (None si < 3 points ou variance nulle)."""
    n = min(len(xs), len(ys))
    if n < 3:
        return None
    xs, ys = xs[-n:], ys[-n:]
    # Variance nulle d'un côté (série de rendements constante) → corrélation indéfinie.
    # statistics.correlation renvoie ±0.0 dans ce cas au lieu de lever → on garde None.
    if len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    try:
        return round(statistics.correlation(xs, ys), 3)
    except statistics.StatisticsError:
        return None


def compute_cross_asset(
    btc: dict[str, float],
    assets: list[tuple[str, str, dict[str, float]]],
    recent: int = RECENT_WINDOW,
) -> dict:
    """Corrélations BTC ↔ chaque actif + label de comportement descriptif.

    `assets` = liste de (clé, libellé, série). `behavior` ∈ {risk_asset, digital_gold,
    decoupled, mixed} décrit AVEC QUOI le BTC co-bouge le plus récemment — descriptif,
    jamais prédictif.
    """
    if not btc:
        return {"available": False}
    out: dict = {"available": True, "context_only": True, "as_of": max(btc), "assets": []}

    for key, label, series in assets:
        if not series:
            continue
        br, orr = aligned_returns(btc, series)
        if len(br) < 5:
            continue
        out["assets"].append(
            {
                "key": key,
                "label": label,
                "corr_recent": pearson(br[-recent:], orr[-recent:]),
                "corr_full": pearson(br, orr),
                "n": len(br[-recent:]),
            }
        )

    corrs = {a["key"]: a["corr_recent"] for a in out["assets"] if a["corr_recent"] is not None}
    eq_vals = [corrs[k] for k in ("sp500", "nasdaq") if k in corrs]
    eq = max(eq_vals) if eq_vals else None
    gold = corrs.get("gold")
    abs_max = max((abs(v) for v in corrs.values()), default=0.0)

    if not corrs or abs_max < BEHAVIOR_THRESHOLD:
        out["behavior"] = "decoupled"
    elif eq is not None and eq >= BEHAVIOR_THRESHOLD and (gold is None or eq >= gold):
        out["behavior"] = "risk_asset"
    elif gold is not None and gold >= BEHAVIOR_THRESHOLD:
        out["behavior"] = "digital_gold"
    else:
        out["behavior"] = "mixed"
    return out


# ---------------------------------------------------------------------------
# Ingester (I/O Yahoo + Redis)
# ---------------------------------------------------------------------------


class CrossAssetIngester(BaseIngester):
    """Polle Yahoo, calcule les corrélations BTC ↔ actions/or/dollar, publie le blob."""

    name = "cross_asset_ingester"
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
        log.info("cross_asset.ingester.started", interval_s=self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("cross_asset.ingester.stopped")

    async def _fetch_series(self, client: httpx.AsyncClient, symbol: str) -> dict[str, float]:
        """Série journalière 3 mois d'un symbole Yahoo. {} si erreur."""
        try:
            r = await client.get(
                YAHOO_CHART_URL.format(symbol=symbol),
                params={"interval": "1d", "range": "3mo"},
                headers={"User-Agent": USER_AGENT},
                timeout=20.0,
            )
            r.raise_for_status()
            return parse_chart(r.json())
        except Exception as exc:  # noqa: BLE001
            log.warning("cross_asset.fetch.error", symbol=symbol, error=str(exc))
            return {}

    async def build_blob(self, client: httpx.AsyncClient) -> dict:
        """Construit le blob `tik.macro.cross_asset`."""
        blob: dict = {
            "source": "yahoo_cross_asset",
            "fetched_at": now_utc().isoformat(),
            "context_only": True,
        }
        btc = await self._fetch_series(client, BTC_SYMBOL)
        assets: list[tuple[str, str, dict[str, float]]] = []
        for symbol, key, label in CROSS_ASSETS:
            assets.append((key, label, await self._fetch_series(client, symbol)))
        blob.update(compute_cross_asset(btc, assets))
        return blob

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                try:
                    blob = await self.build_blob(client)
                    await self.redis.set(REDIS_KEY, json.dumps(blob), ex=self.ttl_s)
                    log.info(
                        "cross_asset.published",
                        behavior=blob.get("behavior"),
                        n_assets=len(blob.get("assets", [])),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("cross_asset.cycle.error", error=str(exc))
                await asyncio.sleep(self.interval_s)
