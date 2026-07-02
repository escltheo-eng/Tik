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
sont testables seuls. Intervalles de polling centralisés dans
`aggregator/polling.py` (source unique de vérité) ; règle `max_age_s ≥ 3× l'intervalle`
pour tolérer des cycles manqués sans faux positif, verrouillée par
`tests/test_polling_intervals.py` (audit 2026-07-02, constat M-1 : la spec
CryptoCompare était restée à 3 h alors que le Bug 15 avait porté le polling à 12 h
→ fausse alerte critique quasi permanente dès le retour du quota).
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


# Intervalles réels : cf. aggregator/polling.py (INGESTER_INTERVALS_S), croisés
# automatiquement avec ces specs dans tests/test_polling_intervals.py.
# last_price.BTC = flux WS continu (pas de polling, absent du dict).
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
        # 36 h = 3× le polling 12 h (invariant anti-quota Bug 15 : free tier
        # 100 req/mois). Resynchronisé 2026-07-02 (audit M-1) — l'ancien 3 h datait
        # du polling horaire et aurait déclenché une fausse alerte critique ~75 %
        # du temps dès le retour du quota.
        36 * _H,
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
        # 6 h = 3× le polling 2 h (mitigation 429 du 2026-06-11). Resynchronisé
        # 2026-07-02 (audit M-1) — l'ancien 2 h = 1× l'intervalle flaggait « stale »
        # au moindre cycle raté. Aligné sur le TTL Redis 6 h de l'ingester.
        6 * _H,
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
        "hackernews_btc",
        "tik.sentiment.hackernews.btc",
        "fetched_at",
        3 * 30 * _M,
        False,
        "shadow strict (ADR-039) — candidat remplaçant Reddit, collecte pour mesure",
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
        "binance_derivatives_btc",
        "tik.deriv.binance.btc",
        "fetched_at",
        3 * _H,
        False,
        "shadow (ADR-023, aucun overlay) — dérivés funding/OI/long-short pour mesure",
    ),
    SourceSpec(
        "btc_etf_flows",
        "tik.etf.btc",
        "fetched_at",
        # Polling 6 h → tolérance 3 cycles = 18 h. `fetched_at` est ré-écrit à
        # chaque cycle même le week-end (la donnée du jour ne change pas mais
        # l'ingester re-publie), donc 18 h ne génère pas de faux positif sur les
        # gaps de marché US ; ça capte la mort de l'ingester en ≤ 3 cycles.
        6 * _H * 3,
        False,
        "shadow (ADR-024, aucun overlay) — flux ETF spot BTC (SoSoValue) pour mesure",
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
