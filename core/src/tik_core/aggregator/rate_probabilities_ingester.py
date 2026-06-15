"""Rate Probabilities ingester — proba de baisse/hausse des taux Fed (ADR-029).

Reproduit le « flagship » de centralbank.watch (probabilités par réunion FOMC)
via la maths CME éprouvée de **pyfedwatch** + des données 100 % gratuites :
- prix des futures Fed Funds (ZQ) par échéance via Yahoo Finance (même source que
  l'ingester Yahoo existant) ;
- range de taux cible courant + taux effectif via FRED (clé de Tik) ;
- dates FOMC via le calendrier de Tik (+ dates passées d'ancrage).

⚠️ CONTEXTE STRICT (ADR-029) : ne touche JAMAIS le combined_bias / la veracity /
la direction. Aucun overlay, aucun toggle directionnel. C'est l'anticipation du
marché (pricée dans les futures), affichée comme contexte — pas un signal Tik.

Pièges résolus (validés en live le 2026-06-15) :
- pyfedwatch importe pandas_datareader (cassé pandas≥2.2) + matplotlib (plot) →
  neutralisés via `_pyfedwatch_compat` (+ install --no-deps).
- Il faut fournir `watch_rate_range=(ll, ul)` sinon il tente un fetch FRED via
  pandas_datareader (cassé) → on passe DFEDTARL/DFEDTARU explicitement.
- L'ancrage utilise le contrat du mois sans-FOMC précédent (souvent EXPIRÉ →
  Yahoo 404). On le synthétise au taux effectif courant (un mois sans FOMC = taux
  constant = taux courant), série constante couvrant tout le mois.
- Tik ne stocke que les dates FOMC futures (Bug 14) → on ajoute les dates passées
  de l'année courante (PAST_FOMC_DATES) pour l'ancrage.
"""

from __future__ import annotations

import asyncio
import json
from calendar import monthrange
from datetime import date

import httpx
import structlog
from redis.asyncio import Redis

from tik_core.aggregator.base import BaseIngester
from tik_core.utils.time import now_utc

log = structlog.get_logger()

FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}.CBT"
REDIS_KEY = "tik.macro.rate_probabilities"
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Codes de mois CME (norme contrats futures).
CME_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}
_CODE_TO_MONTH = {v: k for k, v in CME_MONTH_CODES.items()}

# Dates FOMC PASSÉES de l'année courante (statement = 2e jour de réunion), requises
# par pyfedwatch pour ancrer le taux courant (Tik ne garde que les dates futures,
# cf. Bug 14). ⚠️ À METTRE À JOUR chaque année, en parallèle de macro_calendar_data.
# Source : Federal Reserve Board (calendrier officiel).
PAST_FOMC_DATES = ("2026-01-28", "2026-03-18", "2026-04-29")


# ---------------------------------------------------------------------------
# Fonctions PURES (sans I/O) — unit-testables (test_rate_probabilities.py)
# ---------------------------------------------------------------------------


def parse_cme_symbol(symbol: str) -> tuple[int, int]:
    """'ZQN26' -> (2026, 7). Lève ValueError si format inattendu."""
    if len(symbol) < 5 or not symbol.startswith("ZQ"):
        raise ValueError(f"symbole CME inattendu: {symbol}")
    code = symbol[2]
    yy = int(symbol[3:5])
    return 2000 + yy, _CODE_TO_MONTH[code]


def summarize_meeting(prob_row: dict[str, float], current_lower: float) -> dict:
    """Agrège les probas par range en hold/hike/cut vs le range courant.

    `current_lower` = borne basse du range cible courant (DFEDTARL). Un range dont
    la borne basse == courant → maintien ; > courant → hausse ; < courant → baisse.
    """
    hold = hike = cut = 0.0
    most_range, most_p = "", -1.0
    for rng, p in prob_row.items():
        try:
            lower = float(rng.split("-")[0])
        except (ValueError, IndexError):
            continue
        if abs(lower - current_lower) < 1e-6:
            hold += p
        elif lower > current_lower:
            hike += p
        else:
            cut += p
        if p > most_p:
            most_range, most_p = rng, p
    return {
        "hold": round(hold, 4),
        "hike": round(hike, 4),
        "cut": round(cut, 4),
        "most_likely_range": most_range,
        "most_likely_prob": round(max(most_p, 0.0), 4),
    }


def build_blob(hike_info_df, ll: float, ul: float, effr: float, watch_date: str) -> dict:
    """Transforme la sortie pyfedwatch (DataFrame) en blob JSON pour le cockpit.

    `hike_info_df` : index (WatchDate, FOMCDate), colonnes = ranges 'x.xx-y.yy',
    valeurs = probabilités sommant à 1 par réunion.
    """
    current_range = f"{ll:.2f}-{ul:.2f}"
    meetings = []
    for idx, row in hike_info_df.iterrows():
        fomc_date = idx[1] if isinstance(idx, tuple) else idx
        d = str(fomc_date)[:10]
        full_row = {col: float(row[col]) for col in hike_info_df.columns}
        probs = {col: round(v, 4) for col, v in full_row.items() if v > 0.0005}
        summ = summarize_meeting(full_row, ll)
        meetings.append({"date": d, "probabilities": probs, **summ})
    return {
        "source": "pyfedwatch",
        "fetched_at": now_utc().isoformat(),
        "watch_date": watch_date,
        "current_range": current_range,
        "effr": effr,
        "meetings": meetings,
        "context_only": True,
    }


# ---------------------------------------------------------------------------
# Ingester (I/O FRED + Yahoo + pyfedwatch)
# ---------------------------------------------------------------------------


class RateProbabilitiesIngester(BaseIngester):
    """Calcule les probabilités de taux Fed par réunion et publie `tik.macro.rate_probabilities`."""

    name = "rate_probabilities_ingester"
    layer = 4

    def __init__(
        self,
        redis: Redis,
        api_key: str,
        interval_s: int = 6 * 3600,
        ttl_s: int = 30 * 3600,
        max_upcoming: int = 6,
    ) -> None:
        self.redis = redis
        self.api_key = api_key
        self.interval_s = interval_s
        self.ttl_s = ttl_s
        self.max_upcoming = max_upcoming
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.api_key:
            log.warning("rate_probabilities.ingester.no_api_key_skipping")
            return
        self._running = True
        self._task = asyncio.create_task(self._run())
        log.info("rate_probabilities.ingester.started", interval_s=self.interval_s)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("rate_probabilities.ingester.stopped")

    # --- helpers I/O synchrones (exécutés dans un thread) ---

    def _fred_latest(self, client: httpx.Client, series: str) -> float:
        r = client.get(
            FRED_OBS,
            params={
                "series_id": series,
                "api_key": self.api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 1,
            },
            timeout=15.0,
        )
        r.raise_for_status()
        return float(r.json()["observations"][0]["value"])

    def _fomc_dates(self) -> list[str]:
        from tik_core.aggregator.macro_calendar_data import FOMC_STATIC_DATES

        return sorted(set(PAST_FOMC_DATES) | {s.iso_date for s in FOMC_STATIC_DATES})

    def _compute_blob_sync(self, watch_date: str) -> dict:
        """Tout le calcul bloquant (FRED + Yahoo + pyfedwatch). Lancé via to_thread."""
        # Import lazy : isole la dépendance pyfedwatch hors du module (tests purs OK).
        from tik_core.aggregator._pyfedwatch_compat import FedWatch

        import pandas as pd

        wd_year, wd_month = (int(x) for x in watch_date.split("-")[:2])

        with httpx.Client(headers={"User-Agent": _UA}) as client:
            ll = self._fred_latest(client, "DFEDTARL")
            ul = self._fred_latest(client, "DFEDTARU")
            effr = self._fred_latest(client, "DFF")
            synth_price = 100.0 - effr
            memo: dict[str, "pd.DataFrame"] = {}

            def read_price(symbol, **kwargs):  # noqa: ARG001 — signature pyfedwatch
                if symbol in memo:
                    return memo[symbol]
                y, m = parse_cme_symbol(symbol)
                url = YAHOO_CHART.format(symbol=symbol)
                try:
                    resp = client.get(
                        url, params={"interval": "1d", "range": "3mo"}, timeout=15.0
                    )
                    resp.raise_for_status()
                    res = resp.json()["chart"]["result"][0]
                    df = pd.DataFrame(
                        {
                            "Date": pd.to_datetime(res["timestamp"], unit="s"),
                            "Close": res["indicators"]["quote"][0]["close"],
                        }
                    ).dropna().set_index("Date")
                    if df.empty:
                        raise ValueError("empty")
                except Exception:
                    # Contrat PASSÉ (mois d'ancrage expiré) → synthèse au taux courant
                    # (un mois sans FOMC = taux constant). On NE synthétise PAS un
                    # mois futur (cela fabriquerait un faux « no change »).
                    if (y, m) >= (wd_year, wd_month):
                        raise
                    days = monthrange(y, m)[1]
                    idx = pd.date_range(
                        f"{y}-{m:02d}-01", f"{y}-{m:02d}-{days:02d}", freq="D", name="Date"
                    )
                    df = pd.DataFrame({"Close": [synth_price] * len(idx)}, index=idx)
                memo[symbol] = df
                return df

            fomc_dates = self._fomc_dates()
            df = None
            last_exc: Exception | None = None
            # num_upcoming adaptatif : les contrats lointains peuvent manquer sur
            # Yahoo → on réduit jusqu'à ce que le calcul aboutisse.
            for n in range(self.max_upcoming, 1, -1):
                try:
                    fw = FedWatch(
                        watch_date=watch_date,
                        num_upcoming=n,
                        fomc_dates=fomc_dates,
                        user_func=read_price,
                    )
                    df = fw.generate_hike_info(rate_cols=True, watch_rate_range=(ll, ul))
                    break
                except Exception as exc:  # noqa: BLE001
                    last_exc = exc
                    continue
            if df is None:
                raise last_exc or RuntimeError("pyfedwatch: aucun num_upcoming exploitable")

            return build_blob(df, ll, ul, effr, watch_date)

    async def _run(self) -> None:
        while self._running:
            try:
                watch_date = now_utc().date().isoformat()
                blob = await asyncio.to_thread(self._compute_blob_sync, watch_date)
                await self.redis.set(REDIS_KEY, json.dumps(blob), ex=self.ttl_s)
                log.info(
                    "rate_probabilities.published",
                    meetings=len(blob.get("meetings", [])),
                    current_range=blob.get("current_range"),
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("rate_probabilities.cycle.error", error=str(exc))
            await asyncio.sleep(self.interval_s)
