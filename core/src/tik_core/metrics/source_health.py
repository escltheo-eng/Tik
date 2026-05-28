"""Santé par source OSINT — détection de dégradation silencieuse (complète M4).

M4 (`freshness.py`) surveille la production AGRÉGÉE de signaux : si plus rien ne
sort, c'est une panne. Mais Tik peut tourner en **dégradé silencieux** — continuer
à produire des signaux sur 3 overlays alors qu'une source est morte depuis des
jours, sans que personne ne le voie. C'est exactement ce qui s'est passé avec :
- **Bug 11** (Reddit IP-ban) : invisible tout le déploiement HP, 0 signal n'a
  jamais contenu reddit_btc, découvert par archéologie manuelle ;
- **Bug 9** (inserts DB cassés 4 h) et **Bug 10** (WS zombie 3 h) : avalés en log.

Ce module surveille **chaque source individuellement** via la fraîcheur de sa clé
Redis (`fetched_at` pour les overlays sentiment, `timestamp` pour les flux prix).
Une clé absente = source qui ne publie pas (ex. Reddit 403) ; une clé trop vieille
= source bloquée (ex. ingester mort, rate-limit persistant).

Logique pure (zéro IO) : l'endpoint lit les clés Redis et passe les valeurs brutes
ici. `parse_fetched_at` / `classify_source` / `compute_source_health` / `summarize`
sont testables seuls. Intervalles de polling vérifiés dans `run_ingesters.py`
(2026-05-28) ; `max_age_s ≈ 3× l'intervalle` pour tolérer un cycle manqué sans
faux positif.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

_H = 3600
_M = 60


@dataclass(frozen=True)
class SourceSpec:
    """Source surveillée : clé Redis + champ timestamp + tolérance d'âge."""

    name: str
    redis_key: str
    ts_field: str  # "fetched_at" (overlays) ou "timestamp" (flux prix)
    max_age_s: int
    critical: bool  # son absence dégrade-t-elle la production de signaux actuelle ?
    note: str = ""


# Intervalles réels (run_ingesters.py) : FG/CC/CoinGecko/Polymarket=3600s,
# GoogleNews/Reddit/GDELT=1800s, last_price.BTC=WS continu, GOLD=60s.
SOURCE_SPECS: tuple[SourceSpec, ...] = (
    SourceSpec(
        "fear_greed",
        "tik.sentiment.fear_greed",
        "fetched_at",
        3 * _H,
        True,
        "overlay sentiment BTC (contrarian)",
    ),
    SourceSpec(
        "cryptocompare_news",
        "tik.sentiment.cryptocompare.btc",
        "fetched_at",
        3 * _H,
        True,
        "overlay news BTC",
    ),
    SourceSpec(
        "google_news_btc",
        "tik.sentiment.google_news.btc",
        "fetched_at",
        3 * 30 * _M,
        True,
        "overlay news BTC",
    ),
    SourceSpec(
        "google_news_gold",
        "tik.sentiment.google_news.gold",
        "fetched_at",
        3 * 30 * _M,
        False,
        "overlay news GOLD",
    ),
    SourceSpec(
        "gdelt_gold",
        "tik.sentiment.gdelt.gold",
        "fetched_at",
        4 * 30 * _M,
        False,
        "overlay tone GOLD — rate-limit 429 fréquent (backlog #9), tolérance large",
    ),
    SourceSpec(
        "reddit_btc",
        "tik.sentiment.reddit.btc",
        "fetched_at",
        3 * 30 * _M,
        False,
        "IP-ban connu (Bug 11) — 4e overlay BTC absent, mitigé (CoinGecko candidat)",
    ),
    SourceSpec(
        "coingecko_btc",
        "tik.sentiment.coingecko.btc",
        "fetched_at",
        3 * _H,
        False,
        "shadow (ADR-021, overlay OFF) — collecte pour mesure",
    ),
    SourceSpec(
        "polymarket_btc",
        "tik.sentiment.polymarket.btc",
        "fetched_at",
        3 * _H,
        False,
        "shadow (non enrôlé) — collecte pour mesure",
    ),
    SourceSpec(
        "polymarket_gold",
        "tik.sentiment.polymarket.gold",
        "fetched_at",
        3 * _H,
        False,
        "shadow (non enrôlé) — contexte marché OR pour le trader",
    ),
    SourceSpec(
        "price_btc",
        "tik.last_price.BTC",
        "timestamp",
        10 * _M,
        True,
        "flux WS Binance — alimente le flash + le check de fraîcheur",
    ),
    SourceSpec(
        "price_gold",
        "tik.last_price.GOLD",
        "timestamp",
        15 * _M,
        False,
        "poller Yahoo (60s, upstream flaky/délai 15 min → tolérance large)",
    ),
)


@dataclass(frozen=True)
class SourceHealth:
    name: str
    redis_key: str
    status: str  # "ok" | "stale" | "missing"
    age_seconds: float | None
    max_age_seconds: int
    critical: bool
    note: str


def parse_fetched_at(raw: str | None, ts_field: str) -> datetime | None:
    """Extrait le timestamp aware (UTC) d'un payload JSON Redis.

    Retourne None si le payload est absent / illisible / sans le champ attendu.
    Un timestamp naïf est interprété comme UTC (défensif — les payloads réels
    sont tous aware +00:00, cf. ADR-013).
    """
    if not raw or not isinstance(raw, str):
        return None
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    val = d.get(ts_field)
    if not val or not isinstance(val, str):
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def classify_source(spec: SourceSpec, fetched_at: datetime | None, now: datetime) -> SourceHealth:
    """Classe une source : missing (pas de clé), stale (trop vieille), ok.

    `now` doit être aware (UTC) — cohérent avec les `fetched_at` aware des payloads.
    Âge négatif (skew d'horloge) ramené à 0 (considéré frais).
    """
    if fetched_at is None:
        return SourceHealth(
            spec.name, spec.redis_key, "missing", None, spec.max_age_s, spec.critical, spec.note
        )
    age = max(0.0, (now - fetched_at).total_seconds())
    status = "stale" if age > spec.max_age_s else "ok"
    return SourceHealth(
        spec.name, spec.redis_key, status, age, spec.max_age_s, spec.critical, spec.note
    )


def compute_source_health(
    raw_by_key: dict[str, str | None],
    now: datetime,
    specs: tuple[SourceSpec, ...] = SOURCE_SPECS,
) -> list[SourceHealth]:
    """Santé de toutes les sources à partir des valeurs Redis brutes déjà lues."""
    return [
        classify_source(spec, parse_fetched_at(raw_by_key.get(spec.redis_key), spec.ts_field), now)
        for spec in specs
    ]


def summarize(items: list[SourceHealth]) -> dict[str, object]:
    """Compteurs + liste des sources CRITIQUES dégradées (condition d'alerte)."""
    critical_down = [i.name for i in items if i.critical and i.status != "ok"]
    return {
        "n_total": len(items),
        "n_ok": sum(1 for i in items if i.status == "ok"),
        "n_stale": sum(1 for i in items if i.status == "stale"),
        "n_missing": sum(1 for i in items if i.status == "missing"),
        "critical_down": critical_down,
        "any_critical_down": bool(critical_down),
    }
