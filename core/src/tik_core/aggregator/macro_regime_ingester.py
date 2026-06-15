"""Macro Regime ingester — couche 4 (macro-économique objective, CONTEXTE).

Calcule des indicateurs macro OBJECTIFS (zéro affirmation, zéro LLM) à partir de
séries FRED gratuites et publie un blob unique `tik.macro.regime`, consommé par
le cockpit dashboard (endpoints `/api/v1/macro/regime` et `/api/v1/macro/cockpit`).

Famille de données NON-SENTIMENT (cf. CLAUDE.md §8 : « l'edge, s'il existe, vit
dans des familles DIFFÉRENTES du sentiment »). Inspiré du *menu de données* de
centralbank.watch, mais reproduit via les sources primaires gratuites (FRED) —
PAS de scraping de site tiers (centralbank.watch n'a pas d'API, et réimporter ses
verdicts re-marcherait sur la mine de la « Lecture macro » supprimée le 2026-05-30).

⚠️ CONTEXTE STRICT (ADR-028) : ne touche JAMAIS le `combined_bias`, la veracity ou
la direction des signaux. Aucun overlay branché, aucun toggle. C'est de l'affichage
de chiffres bruts officiels datés (bilan Fed, taux réels, proba récession), pas une
prédiction. On n'AFFIRME rien (contrairement à la « Lecture macro » retirée) : on
expose des séries FRED avec leur date. Si plus tard une mesure shadow ≥ 2 sem
démontre un edge, un overlay `_enrich_with_net_liquidity` pourra être proposé dans
un ADR dédié — JAMAIS avant mesure (règle Axe #1 / protocole Polymarket/dérivés/ETF).

Pièges résolus en Phase 0 (vérifiés en live via l'API FRED le 2026-06-15) :
- UNITÉS : WALCL et WTREGEN sont en MILLIONS de $, RRPONTSYD en MILLIARDS de $.
  Net liquidity normalisé en milliards : `WALCL/1000 − TGA/1000 − RRP`.
  (Oublier la normalisation = erreur d'un facteur 1000.)
- CADENCE : WALCL/TGA hebdo (mercredi), RRP quotidien → la série net liquidity est
  HEBDO (alignée sur les mercredis WALCL). C'est le standard des graphes publics.
- Sanity check 2026-06-15 : 6725,4 − 828,1 − 0,5 ≈ 5896,8 Md$ (~5,90 T$), ordre de
  grandeur cohérent avec les références publiques (TradingView FRED).
"""

from __future__ import annotations

import asyncio
import json
import statistics
from datetime import date, timedelta

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.utils.time import now_utc

log = structlog.get_logger()

FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"

# Composants du Fed Net Liquidity (récupérés avec historique pour le calcul série).
NET_LIQUIDITY_SERIES = {
    "walcl": "WALCL",  # bilan Fed, millions $, hebdo (mercredi)
    "tga": "WTREGEN",  # Treasury General Account, millions $, hebdo (mercredi)
    "rrp": "RRPONTSYD",  # reverse repo overnight, MILLIARDS $, quotidien
}

# Indicateurs de régime : on ne garde que la dernière valeur valide (clé du blob).
SERIES_LATEST = {
    "RECPROUSM156N": "recession_prob_12m",  # proba récession 12m (NY Fed probit), mensuel
    "DFII10": "real_rate_10y",  # taux réel 10Y (TIPS), quotidien
    "T10YIE": "breakeven_inflation_10y",  # inflation anticipée 10Y, quotidien
    "T10Y2Y": "curve_2s10s",  # pente 2s10s, quotidien
    "T10Y3M": "curve_3m10y",  # pente 3m10y, quotidien
    "NFCI": "financial_conditions_nfci",  # conditions financières Chicago Fed, hebdo
    "DGS10": "nominal_10y",  # taux nominal 10Y, quotidien
}

REDIS_KEY = "tik.macro.regime"


# ---------------------------------------------------------------------------
# Fonctions PURES (sans I/O) — unit-testables directement (test_macro_regime.py)
# ---------------------------------------------------------------------------


def parse_observations(observations: list[dict]) -> dict[str, float]:
    """FRED observations -> dict {date_iso: float}. Ignore les valeurs manquantes ('.')."""
    out: dict[str, float] = {}
    for o in observations:
        v = o.get("value")
        if v in (".", "", None):
            continue
        try:
            out[o["date"]] = float(v)
        except (ValueError, KeyError, TypeError):
            continue
    return out


def latest_valid(obs: dict[str, float]) -> tuple[str, float] | None:
    """Dernière observation valide (date max) d'un dict {date: value}."""
    if not obs:
        return None
    d = max(obs)
    return d, obs[d]


def _value_on_or_before(series: dict[str, float], target: str, max_back: int = 7) -> float | None:
    """Valeur de `series` à `target`, ou la plus proche en arrière (≤ max_back jours).

    Sert à aligner des séries de cadences différentes sur les dates WALCL (mercredi) :
    RRP/FX quotidiens (≤ 7 j), ECB hebdo (≤ 10 j), BoJ mensuel (report ≤ 40 j).
    """
    try:
        d0 = date.fromisoformat(target)
    except ValueError:
        return None
    for i in range(max_back + 1):
        key = (d0 - timedelta(days=i)).isoformat()
        if key in series:
            return series[key]
    return None


def _rrp_for_date(rrp_daily: dict[str, float], target: str, max_back: int = 7) -> float | None:
    """RRP (milliards) le jour `target` ou le plus proche en arrière (≤ max_back jours)."""
    return _value_on_or_before(rrp_daily, target, max_back)


def compute_net_liquidity_series(
    walcl_millions: dict[str, float],
    tga_millions: dict[str, float],
    rrp_billions_daily: dict[str, float],
) -> list[tuple[str, float]]:
    """Série hebdo du Fed Net Liquidity en MILLIARDS $, triée par date ascendante.

    `net_liq = WALCL/1000 − TGA/1000 − RRP` (tout ramené en milliards).
    Itère sur les dates WALCL (mercredi) ; TGA partage ces dates (mercredi) ; RRP
    quotidien pris le jour même ou le plus proche en arrière (≤ 7 j). Si RRP absent
    (rare : presque toujours présent le mercredi), traité comme 0 (best-effort ;
    RRP ≈ 0,5 Md$ en 2026, négligeable devant WALCL−TGA ~5900 Md$).
    """
    series: list[tuple[str, float]] = []
    for d in sorted(walcl_millions):
        if d not in tga_millions:
            continue
        rrp = _rrp_for_date(rrp_billions_daily, d)
        if rrp is None:
            rrp = 0.0
        net = walcl_millions[d] / 1000.0 - tga_millions[d] / 1000.0 - rrp
        series.append((d, round(net, 1)))
    return series


def compute_global_liquidity_series(
    walcl_mil_usd: dict[str, float],
    ecb_mil_eur: dict[str, float],
    boj_100mil_yen: dict[str, float],
    eurusd_daily: dict[str, float],
    jpyusd_daily: dict[str, float],
) -> list[tuple[str, float]]:
    """Série hebdo de la liquidité mondiale des banques centrales (Fed+ECB+BoJ) en
    MILLIARDS USD, triée par date ascendante.

    Conversions (pièges d'unités, vérifiés en live le 2026-06-15) :
    - Fed `WALCL` : déjà en millions USD.
    - ECB `ECBASSETSW` : millions d'EUR → × `DEXUSEU` (USD pour 1 €) = millions USD.
    - BoJ `JPNASSETS` : unité « 100 millions de ¥ » → × 100 = millions ¥, puis
      ÷ `DEXJPUS` (¥ pour 1 $) = millions USD.

    Alignée sur les dates WALCL (mercredi). ECB hebdo (report ≤ 10 j), BoJ mensuel
    (report ≤ 40 j), FX quotidien (report ≤ 7 j). Un point est produit seulement si
    toutes les composantes sont disponibles pour la date.
    """
    series: list[tuple[str, float]] = []
    for d in sorted(walcl_mil_usd):
        ecb = _value_on_or_before(ecb_mil_eur, d, 10)
        boj = _value_on_or_before(boj_100mil_yen, d, 40)
        fx_e = _value_on_or_before(eurusd_daily, d, 7)
        fx_j = _value_on_or_before(jpyusd_daily, d, 7)
        if ecb is None or boj is None or fx_e is None or fx_j is None or not fx_j:
            continue
        fed_mil = walcl_mil_usd[d]
        ecb_mil = ecb * fx_e
        boj_mil = boj * 100.0 / fx_j
        global_busd = (fed_mil + ecb_mil + boj_mil) / 1000.0
        series.append((d, round(global_busd, 1)))
    return series


def _regime_core(series: list[tuple[str, float]], zscore_window: int = 52) -> dict:
    """Métriques de régime GÉNÉRIQUES (niveau, deltas, z-score, label) sur une série
    hebdo (date, valeur en Md$). Le niveau brut est exposé sous `_level` (clé interne,
    renommée par les wrappers compute_regime / compute_global_regime).

    Le label `regime` (`expansion`/`contraction`/`neutral`/`unknown`) décrit un vent
    porteur/contraire CONTEXTUEL, jamais une prédiction de prix.
    """
    if not series:
        return {"available": False}
    values = [v for _, v in series]
    latest_date, latest = series[-1]
    out: dict = {
        "available": True,
        "as_of": latest_date,
        "_level": latest,
        "n_weeks": len(series),
    }

    def _delta(n: int) -> float | None:
        # Série hebdo : 4 points ≈ 1 mois, 13 points ≈ 1 trimestre.
        if len(values) > n:
            return round(latest - values[-1 - n], 1)
        return None

    out["delta_4w_busd"] = _delta(4)
    out["delta_13w_busd"] = _delta(13)

    window = values[-zscore_window:]
    if len(window) >= 8:
        mu = statistics.mean(window)
        sd = statistics.pstdev(window)
        out["zscore_52w"] = round((latest - mu) / sd, 2) if sd > 0 else 0.0
    else:
        out["zscore_52w"] = None

    d13 = out["delta_13w_busd"]
    if d13 is None or not latest:
        out["regime"] = "unknown"
    else:
        pct = d13 / latest
        if pct > 0.01:
            out["regime"] = "expansion"  # liquidité montante = vent porteur risque
        elif pct < -0.01:
            out["regime"] = "contraction"  # liquidité descendante = vent contraire
        else:
            out["regime"] = "neutral"

    out["context_only"] = True
    return out


def compute_regime(series: list[tuple[str, float]], zscore_window: int = 52) -> dict:
    """Régime du Fed Net Liquidity (clés `net_liquidity_busd`/`net_liquidity_tusd`)."""
    core = _regime_core(series, zscore_window)
    if not core.get("available"):
        return {"available": False}
    level = core.pop("_level")
    return {
        **core,
        "net_liquidity_busd": level,
        "net_liquidity_tusd": round(level / 1000.0, 3),
    }


def compute_global_regime(series: list[tuple[str, float]], zscore_window: int = 52) -> dict:
    """Régime de la liquidité mondiale (clés `global_liquidity_busd`/`_tusd`)."""
    core = _regime_core(series, zscore_window)
    if not core.get("available"):
        return {"available": False}
    level = core.pop("_level")
    return {
        **core,
        "global_liquidity_busd": level,
        "global_liquidity_tusd": round(level / 1000.0, 3),
    }


# ---------------------------------------------------------------------------
# Ingester (I/O FRED + Redis)
# ---------------------------------------------------------------------------


class MacroRegimeIngester(BaseIngester):
    """Polle FRED, calcule le régime macro objectif, publie `tik.macro.regime`."""

    name = "macro_regime_ingester"
    layer = 4

    def __init__(
        self,
        redis: Redis,
        api_key: str,
        interval_s: int = 6 * 3600,
        ttl_s: int = 36 * 3600,
    ) -> None:
        self.redis = redis
        self.api_key = api_key
        self.interval_s = interval_s
        self.ttl_s = ttl_s
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.api_key:
            log.warning("macro_regime.ingester.no_api_key_skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("macro_regime.ingester.started", interval_s=self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("macro_regime.ingester.stopped")

    async def _fetch_obs(
        self,
        client: httpx.AsyncClient,
        series_id: str,
        limit: int,
    ) -> list[dict]:
        """Récupère les `limit` dernières observations FRED (desc). [] si erreur."""
        try:
            r = await client.get(
                FRED_OBS,
                params={
                    "series_id": series_id,
                    "api_key": self.api_key,
                    "file_type": "json",
                    "sort_order": "desc",
                    "limit": limit,
                },
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json().get("observations", [])
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_regime.fetch.error", series=series_id, error=str(exc))
            return []

    async def build_blob(self, client: httpx.AsyncClient) -> dict:
        """Construit le blob `tik.macro.regime` (best-effort, sections indépendantes)."""
        blob: dict = {
            "source": "fred_macro_regime",
            "fetched_at": now_utc().isoformat(),
            "context_only": True,
        }

        # --- Net liquidity (besoin d'historique) ---
        try:
            walcl = parse_observations(
                await self._fetch_obs(client, NET_LIQUIDITY_SERIES["walcl"], 60)
            )
            tga = parse_observations(
                await self._fetch_obs(client, NET_LIQUIDITY_SERIES["tga"], 60)
            )
            rrp = parse_observations(
                await self._fetch_obs(client, NET_LIQUIDITY_SERIES["rrp"], 400)
            )
            series = compute_net_liquidity_series(walcl, tga, rrp)
            regime = compute_regime(series)
            # composants bruts (transparence) en milliards
            walcl_last = latest_valid(walcl)
            tga_last = latest_valid(tga)
            rrp_last = latest_valid(rrp)
            if regime.get("available"):
                regime["components"] = {
                    "walcl_busd": round(walcl_last[1] / 1000.0, 1) if walcl_last else None,
                    "walcl_date": walcl_last[0] if walcl_last else None,
                    "tga_busd": round(tga_last[1] / 1000.0, 1) if tga_last else None,
                    "tga_date": tga_last[0] if tga_last else None,
                    "rrp_busd": round(rrp_last[1], 1) if rrp_last else None,
                    "rrp_date": rrp_last[0] if rrp_last else None,
                }
            blob["net_liquidity"] = regime
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_regime.net_liquidity.error", error=str(exc))
            blob["net_liquidity"] = {"available": False}

        # --- Liquidité globale (Fed + ECB + BoJ, convertie en USD) ---
        try:
            walcl_g = parse_observations(
                await self._fetch_obs(client, NET_LIQUIDITY_SERIES["walcl"], 60)
            )
            ecb = parse_observations(await self._fetch_obs(client, "ECBASSETSW", 60))
            boj = parse_observations(await self._fetch_obs(client, "JPNASSETS", 24))
            eurusd = parse_observations(await self._fetch_obs(client, "DEXUSEU", 400))
            jpyusd = parse_observations(await self._fetch_obs(client, "DEXJPUS", 400))
            gl_series = compute_global_liquidity_series(walcl_g, ecb, boj, eurusd, jpyusd)
            gl = compute_global_regime(gl_series)
            if gl.get("available"):
                wl, el, bl = latest_valid(walcl_g), latest_valid(ecb), latest_valid(boj)
                eu, jp = latest_valid(eurusd), latest_valid(jpyusd)
                gl["components"] = {
                    "fed_tusd": round(wl[1] / 1e6, 2) if wl else None,
                    "ecb_tusd": round(el[1] * eu[1] / 1e6, 2) if (el and eu) else None,
                    "boj_tusd": (
                        round(bl[1] * 100.0 / jp[1] / 1e6, 2) if (bl and jp and jp[1]) else None
                    ),
                    "eurusd": eu[1] if eu else None,
                    "jpyusd": jp[1] if jp else None,
                    "fed_date": wl[0] if wl else None,
                    "ecb_date": el[0] if el else None,
                    "boj_date": bl[0] if bl else None,
                }
            blob["global_liquidity"] = gl
        except Exception as exc:  # noqa: BLE001
            log.warning("macro_regime.global_liquidity.error", error=str(exc))
            blob["global_liquidity"] = {"available": False}

        # --- Indicateurs (dernière valeur valide) ---
        indicators: dict[str, dict] = {}
        for series_id, key in SERIES_LATEST.items():
            obs = parse_observations(await self._fetch_obs(client, series_id, 10))
            lv = latest_valid(obs)
            if lv is not None:
                indicators[key] = {"value": lv[1], "date": lv[0], "series_id": series_id}
        blob["indicators"] = indicators

        return blob

    async def _run(self) -> None:
        async with httpx.AsyncClient() as client:
            while self._running:
                try:
                    blob = await self.build_blob(client)
                    await self.redis.set(REDIS_KEY, json.dumps(blob), ex=self.ttl_s)
                    nl = blob.get("net_liquidity", {})
                    log.info(
                        "macro_regime.published",
                        net_liquidity_tusd=nl.get("net_liquidity_tusd"),
                        regime=nl.get("regime"),
                        indicators=len(blob.get("indicators", {})),
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("macro_regime.cycle.error", error=str(exc))
                await asyncio.sleep(self.interval_s)
