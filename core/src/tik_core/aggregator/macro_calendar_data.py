"""Données statiques du calendrier macro (Lacune B Phases B1 + B2 J+10).

Cf. ADR-017 (Phase B1 — FOMC + FRED US releases) et ADR-020 (Phase B2 —
multi-banques centrales ECB / BoJ / BoE).

Ce module centralise :

1. **Whitelist FRED releases** (`FRED_RELEASES`) — release_id officiels +
   métadonnées (event_code, label, importance, assets impactés, heure
   release dans le fuseau US/Eastern). L'ingester FRED Calendar polle
   `/fred/release/dates` pour chacun de ces release_id et upsert les
   dates futures dans la table `macro_events`.

2. **FOMC meeting dates statiques** (`FOMC_STATIC_DATES`) — 2026-2027.
   Source : Federal Reserve Board (
   https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
   ). FRED ne couvre pas proprement le statement FOMC.

3. **ECB / BoJ / BoE meeting dates statiques** — Phase B2 (ADR-020). Les
   banques centrales internationales publient leur calendrier 1 an à
   l'avance comme la Fed. Dates 2026-2027. Sources :
   - ECB : https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
   - BoJ : https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm
   - BoE : https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates

   **À VÉRIFIER avant déploiement runtime** : les dates ci-dessous sont
   basées sur les patterns publiés. L'UNIQUE constraint `(event_code,
   scheduled_for)` côté DB protège contre les doublons accidentels mais
   pas contre une date incorrecte. Si une date est erronée, la corriger
   ici et re-run l'ingester (idempotent).

4. **Helpers de transformation purs** : `date_to_utc_release`,
   `build_event_from_fred`, `build_event_from_static`, `all_static_events`.
   Déplacés depuis `fred_calendar_ingester.py` en Phase B2 pour permettre
   leur réutilisation par `macro_static_ingester.py` (FOMC + ECB + BoJ +
   BoE) sans dépendance circulaire.

**Pourquoi hardcoder en Python plutôt qu'en YAML/JSON :** auditabilité par
le code review, type-checking, testabilité. Mise à jour annuelle ~30 min
de maintenance (1 fois/an quand chaque BC publie son calendrier suivant).

**Timezones et DST** : chaque spec porte un `tz_name` IANA
(`America/New_York`, `Europe/Paris`, `Asia/Tokyo`, `Europe/London`). Le
DST (passage été/hiver) est géré automatiquement par `zoneinfo`.

**Importance** :
- HIGH : FOMC, NFP, CPI, ECB Governing Council, BoJ MPM (mouvements
  violents BTC/GOLD/JPY/EUR).
- MEDIUM : PPI, GDP, Retail Sales, BoE MPC (impact réel mais plus lissé).
- LOW : Initial Claims, Industrial Production (data hebdomadaire/mensuelle).

**Assets impactés** : tous les events centraux affectent BTC + GOLD
(transmission via DXY pour les non-US, carry trade pour BoJ). Phase B3
introduira potentiellement des entities supplémentaires (US_DEBT, OIL,
EUR_USD, EM_RISK, GEOPOLITICAL_RISK).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class FredReleaseSpec:
    """Métadonnées d'un release FRED qu'on watch dans le calendrier macro."""

    release_id: int
    event_code: str
    event_name: str
    importance: str  # "HIGH" | "MEDIUM" | "LOW"
    # Heure de release dans le fuseau US/Eastern (DST géré par zoneinfo).
    # Ex: (8, 30) = 8h30 AM ET. Tous les releases BLS/BEA/Census sont à 8:30 ET.
    # FRB Industrial Production = 9:15 ET. Voir BLS schedule public.
    release_hour_et: int
    release_minute_et: int
    assets_impacted: tuple[str, ...]
    # Phase B2 : tz_name IANA pour la conversion UTC. Default = US/Eastern
    # car toutes les FRED releases sont publiées par BLS/BEA/Census/FRB
    # (organismes US).
    tz_name: str = "America/New_York"


@dataclass(frozen=True)
class StaticEventSpec:
    """Métadonnées d'un événement macro hardcodé (FOMC, ECB, BoJ, BoE…).

    Phase B2 (ADR-020) : ajout du champ `tz_name` IANA pour supporter les
    banques centrales hors-US (ECB Europe/Paris, BoJ Asia/Tokyo, BoE
    Europe/London). Default rétrocompat = `America/New_York` pour les
    FOMC dates existantes (Phase B1).

    `release_hour_et` / `release_minute_et` gardent leur nom historique
    (ET = Eastern Time pour FOMC) bien qu'ils représentent désormais
    l'heure dans le fuseau `tz_name` quel qu'il soit. Pas renommés pour
    éviter la cascade de migrations sur les tests existants Phase B1.
    Pour ECB / BoJ / BoE c'est l'heure locale Frankfurt / Tokyo / London.
    """

    event_code: str
    event_name: str
    importance: str
    # ISO date du release (sans heure — l'heure est appliquée séparément).
    iso_date: str
    release_hour_et: int  # historique : "ET" mais en réalité "local au tz_name"
    release_minute_et: int
    assets_impacted: tuple[str, ...]
    # Code source pour l'upsert DB. Default rétrocompat = "fed_static" pour
    # les FOMC dates Phase B1. ECB → "ecb_static", BoJ → "boj_static",
    # BoE → "boe_static".
    source: str = "fed_static"
    tz_name: str = "America/New_York"


# =============================================================================
# Helpers de transformation (déplacés depuis fred_calendar_ingester en B2)
# =============================================================================


def date_to_utc_release(
    iso_date: str,
    release_hour_local: int,
    release_minute_local: int,
    tz_name: str = "America/New_York",
) -> datetime:
    """Convertit une date calendaire ISO + heure locale (dans `tz_name`) en
    datetime UTC aware.

    Le DST est géré automatiquement par `zoneinfo` :
    - 8h30 ET en janvier → 13h30 UTC (EST = UTC-5)
    - 8h30 ET en juin → 12h30 UTC (EDT = UTC-4)
    - 14h15 CET en janvier → 13h15 UTC (CET = UTC+1)
    - 14h15 CET en juin → 12h15 UTC (CEST = UTC+2)
    - 12h JST → 03h UTC (JST = UTC+9, pas de DST au Japon)
    - 12h GMT en janvier → 12h UTC (GMT = UTC)
    - 12h GMT en juin → 11h UTC (BST = UTC+1)

    Retourne un datetime UTC aware (`tzinfo=UTC`). Le caller convertira
    en naïf via `to_naive_utc()` avant insertion DB.
    """
    d = date.fromisoformat(iso_date)
    local_tz = ZoneInfo(tz_name)
    local_dt = datetime(
        d.year,
        d.month,
        d.day,
        release_hour_local,
        release_minute_local,
        tzinfo=local_tz,
    )
    return local_dt.astimezone(timezone.utc)


def build_event_from_fred(
    spec: FredReleaseSpec, iso_date: str
) -> dict[str, Any]:
    """Construit un dict event prêt pour `upsert_many` à partir d'un FRED spec."""
    return {
        "event_code": spec.event_code,
        "event_name": spec.event_name,
        "scheduled_for": date_to_utc_release(
            iso_date,
            spec.release_hour_et,
            spec.release_minute_et,
            tz_name=spec.tz_name,
        ),
        "importance": spec.importance,
        "assets_impacted": list(spec.assets_impacted),
        "source": "fred",
        "release_id": spec.release_id,
    }


def build_event_from_static(spec: StaticEventSpec) -> dict[str, Any]:
    """Construit un dict event prêt pour `upsert_many` à partir d'un Static spec.

    Phase B2 : `spec.source` (default "fed_static") et `spec.tz_name`
    (default "America/New_York") permettent de gérer FOMC + ECB + BoJ +
    BoE dans la même structure.
    """
    return {
        "event_code": spec.event_code,
        "event_name": spec.event_name,
        "scheduled_for": date_to_utc_release(
            spec.iso_date,
            spec.release_hour_et,
            spec.release_minute_et,
            tz_name=spec.tz_name,
        ),
        "importance": spec.importance,
        "assets_impacted": list(spec.assets_impacted),
        "source": spec.source,
        "release_id": None,
    }


# =============================================================================
# FRED whitelist — 7 releases stables (Phase B1)
# =============================================================================
#
# Les release_id sont vérifiables via :
#   curl "https://api.stlouisfed.org/fred/releases?api_key=$FRED_API_KEY&file_type=json&limit=200"
#
FRED_RELEASES: tuple[FredReleaseSpec, ...] = (
    FredReleaseSpec(
        release_id=50,
        event_code="NFP",
        event_name="Employment Situation (NFP)",
        importance="HIGH",
        release_hour_et=8,
        release_minute_et=30,
        assets_impacted=("BTC", "GOLD"),
    ),
    FredReleaseSpec(
        release_id=10,
        event_code="CPI",
        event_name="Consumer Price Index",
        importance="HIGH",
        release_hour_et=8,
        release_minute_et=30,
        assets_impacted=("BTC", "GOLD"),
    ),
    FredReleaseSpec(
        release_id=46,
        event_code="PPI",
        event_name="Producer Price Index",
        importance="MEDIUM",
        release_hour_et=8,
        release_minute_et=30,
        assets_impacted=("BTC", "GOLD"),
    ),
    FredReleaseSpec(
        release_id=53,
        event_code="GDP",
        event_name="Gross Domestic Product",
        importance="MEDIUM",
        release_hour_et=8,
        release_minute_et=30,
        assets_impacted=("BTC", "GOLD"),
    ),
    FredReleaseSpec(
        release_id=17,
        event_code="RETAIL_SALES",
        event_name="Advance Monthly Sales for Retail and Food Services",
        importance="MEDIUM",
        release_hour_et=8,
        release_minute_et=30,
        assets_impacted=("BTC", "GOLD"),
    ),
    FredReleaseSpec(
        release_id=13,
        event_code="INDUSTRIAL_PRODUCTION",
        event_name="Industrial Production and Capacity Utilization",
        importance="LOW",
        release_hour_et=9,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
    ),
    FredReleaseSpec(
        release_id=14,
        event_code="INITIAL_CLAIMS",
        event_name="Unemployment Insurance Weekly Claims",
        importance="LOW",
        release_hour_et=8,
        release_minute_et=30,
        assets_impacted=("BTC", "GOLD"),
    ),
)


# =============================================================================
# FOMC dates statiques (Phase B1) — Fed Reserve
# =============================================================================
# Source officielle : https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Statement publié à 14:00 ET le 2e jour de chaque meeting de 2 jours.
# Mise à jour annuelle nécessaire (Fed publie courant septembre N-1).
FOMC_STATIC_DATES: tuple[StaticEventSpec, ...] = (
    # 2026 (passées : Jan, Mar, Apr — gardées pour audit historique 30j)
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-01-29",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-03-19",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-04-30",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    # 2026 à venir
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-06-18",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-07-30",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-09-17",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-11-05",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-12-17",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    # 2027 (estimations sur le pattern Fed habituel)
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-01-28",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-03-18",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-04-29",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-06-17",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="fed_static",
        tz_name="America/New_York",
    ),
)


# =============================================================================
# ECB Governing Council monetary policy dates (Phase B2 — ADR-020)
# =============================================================================
# Source officielle : https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
# Statement publié à 14:15 Europe/Paris (Frankfurt). Press conference à 14:45.
# On cible le statement (mouvement de prix le plus brutal sur EUR/USD/DXY,
# transmission BTC/GOLD).
# 8 meetings/an, espacement ~6 semaines, généralement jeudi.
ECB_STATIC_DATES: tuple[StaticEventSpec, ...] = (
    # 2026 passées (gardées pour audit historique 30j)
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-01-22",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-03-05",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-04-16",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    # 2026 à venir
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-06-11",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-07-23",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-09-10",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-10-29",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2026-12-17",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    # 2027 (estimations sur pattern ECB habituel — à confirmer mi-2026
    # quand ECB publiera son calendrier 2027 officiel)
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2027-01-28",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2027-03-11",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2027-04-22",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
    StaticEventSpec(
        event_code="ECB_GOVERNING_COUNCIL",
        event_name="ECB Governing Council Monetary Policy",
        importance="HIGH",
        iso_date="2027-06-10",
        release_hour_et=14,
        release_minute_et=15,
        assets_impacted=("BTC", "GOLD"),
        source="ecb_static",
        tz_name="Europe/Paris",
    ),
)


# =============================================================================
# Bank of Japan Monetary Policy Meeting dates (Phase B2 — ADR-020)
# =============================================================================
# Source officielle : https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm
# Statement publié vers 12:00 Asia/Tokyo (JST) le 2e jour du meeting. Le
# Japon n'a pas de DST → JST = UTC+9 constant.
# 8 meetings/an, généralement 2 jours, statement du 2e jour pris ci-dessous.
# Impact violent sur USD/JPY → carry trade → BTC / safe haven flows → GOLD.
BOJ_STATIC_DATES: tuple[StaticEventSpec, ...] = (
    # 2026 passées (audit historique)
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-01-23",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-03-19",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-05-01",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    # 2026 à venir
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-06-17",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-07-31",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-09-19",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-10-30",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2026-12-18",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    # 2027 (estimations — à confirmer fin 2026)
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2027-01-22",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2027-03-18",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2027-04-30",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
    StaticEventSpec(
        event_code="BOJ_MPM",
        event_name="BoJ Monetary Policy Meeting Statement",
        importance="HIGH",
        iso_date="2027-06-18",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boj_static",
        tz_name="Asia/Tokyo",
    ),
)


# =============================================================================
# Bank of England MPC dates (Phase B2 — ADR-020)
# =============================================================================
# Source officielle : https://www.bankofengland.co.uk/monetary-policy/upcoming-mpc-dates
# Bank Rate decision publiée à 12:00 Europe/London (GMT/BST selon DST).
# 8 meetings/an. Importance MEDIUM (impact réel mais plus mesuré sur BTC/GOLD
# que Fed/ECB/BoJ — la GBP est moins influente sur le DXY).
BOE_STATIC_DATES: tuple[StaticEventSpec, ...] = (
    # 2026 passées (audit historique)
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-02-05",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-03-20",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-05-08",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    # 2026 à venir
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-06-19",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-08-07",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-09-18",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-11-06",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2026-12-18",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    # 2027 (estimations — à confirmer fin 2026)
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2027-02-04",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2027-03-25",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2027-05-13",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
    StaticEventSpec(
        event_code="BOE_MPC",
        event_name="BoE MPC Bank Rate Decision",
        importance="MEDIUM",
        iso_date="2027-06-24",
        release_hour_et=12,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
        source="boe_static",
        tz_name="Europe/London",
    ),
)


# =============================================================================
# Aggregation helper (Phase B2)
# =============================================================================


def all_static_events() -> tuple[StaticEventSpec, ...]:
    """Concatène FOMC + ECB + BoJ + BoE en une seule séquence.

    Utilisée par `MacroStaticIngester` pour itérer sur l'ensemble des
    events à upserter à chaque cycle.
    """
    return FOMC_STATIC_DATES + ECB_STATIC_DATES + BOJ_STATIC_DATES + BOE_STATIC_DATES


def find_fred_release(release_id: int) -> FredReleaseSpec | None:
    """Retrouve un FredReleaseSpec par son release_id."""
    for spec in FRED_RELEASES:
        if spec.release_id == release_id:
            return spec
    return None
