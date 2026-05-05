"""Données statiques du calendrier macro (Lacune B Phase B1 J+10).

Cf. ADR-017 — Calendrier macro/géopolitique.

Ce module centralise :

1. **Whitelist FRED releases** (`FRED_RELEASES`) — release_id officiels +
   métadonnées (event_code, label, importance, assets impactés, heure
   release dans le fuseau US/Eastern). L'ingester FRED Calendar polle
   `/fred/release/dates` pour chacun de ces release_id et upsert les
   dates futures dans la table `macro_events`.

2. **FOMC meeting dates statiques** (`FOMC_STATIC_DATES`) — 2026-2027,
   source : Federal Reserve Board (https://www.federalreserve.gov/
   monetarypolicy/fomccalendars.htm). FRED ne couvre pas proprement le
   FOMC statement+press conference (les release IDs liés sont des séries
   continues type H.15 Selected Interest Rates). Le Fed publie son
   calendrier 1 an à l'avance, donc les dates sont stables et auditables.

**Pourquoi hardcoder en Python plutôt qu'en YAML/JSON :** auditabilité par
le code review, type-checking, testabilité. Mise à jour annuelle ~30 min
de maintenance (1 fois/an quand le Fed publie le calendrier suivant).

**Heures release** : toutes en US/Eastern via `zoneinfo.ZoneInfo`. Le
DST (passage été/hiver) est géré automatiquement par Python — un release
8:30 ET = 13:30 UTC en hiver, 12:30 UTC en été, sans intervention.

**Importance** :
- HIGH : FOMC, NFP, CPI (déclenchent vol violente sur BTC + GOLD)
- MEDIUM : PPI, GDP, Retail Sales (impact réel mais plus lissé)
- LOW : Initial Claims, Industrial Production (data hebdomadaire/mensuelle
  consultative, mouvements modérés sauf surprise extrême)

**Assets impactés** : pour Phase B1, tous les events US affectent BTC + GOLD
(BTC car les rates US drivent le risk-on/risk-off crypto, GOLD car
inversement corrélé au DXY qui réagit aux rates et au CPI). Phase B2
introduira des entities supplémentaires (US_DEBT, OIL, EUR_USD, EM_RISK)
avec des matrices d'impact plus fines.
"""

from __future__ import annotations

from dataclasses import dataclass


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


@dataclass(frozen=True)
class StaticEventSpec:
    """Métadonnées d'un événement macro hardcodé (FOMC, élections, etc.)."""

    event_code: str
    event_name: str
    importance: str
    # ISO date du release (sans heure — l'heure est appliquée séparément
    # via release_hour_et / release_minute_et).
    iso_date: str
    release_hour_et: int
    release_minute_et: int
    assets_impacted: tuple[str, ...]


# Whitelist FRED — 7 releases stables couverts par FRED Releases API.
#
# Les release_id sont vérifiables via :
#   curl "https://api.stlouisfed.org/fred/releases?api_key=$FRED_API_KEY&file_type=json&limit=200"
#
# Si un release_id devient incorrect (rare, mais Fed peut renuméroter), le
# ingester logge un warning au cycle suivant et l'event est skip — pas de
# crash. Validation runtime requise au déploiement (cf. ADR-017 §5).
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


# FOMC meeting dates 2026-2027.
# Source officielle : https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# Le statement + press conference est publié à 14:00 ET le 2e jour de chaque
# meeting de 2 jours. Press conference à 14:30 ET. On cible le statement
# (mouvement de prix le plus brutal sur BTC/GOLD).
#
# Mise à jour annuelle nécessaire : quand le Fed publie le calendrier N+1
# (généralement courant septembre), ajouter les dates à cette liste et
# documenter dans CLAUDE.md.
FOMC_STATIC_DATES: tuple[StaticEventSpec, ...] = (
    # 2026 (passées : Jan, Mar, Apr — gardées pour audit historique)
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-01-29",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-03-19",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-04-30",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
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
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-07-30",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-09-17",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-11-05",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2026-12-17",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    # 2027 (estimations sur le pattern Fed habituel — à confirmer quand
    # le Fed publiera son calendrier 2027 officiel courant septembre 2026)
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-01-28",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-03-18",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-04-29",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
    StaticEventSpec(
        event_code="FOMC_MEETING",
        event_name="FOMC Statement & Press Conference",
        importance="HIGH",
        iso_date="2027-06-17",
        release_hour_et=14,
        release_minute_et=0,
        assets_impacted=("BTC", "GOLD"),
    ),
)


def find_fred_release(release_id: int) -> FredReleaseSpec | None:
    """Retrouve un FredReleaseSpec par son release_id."""
    for spec in FRED_RELEASES:
        if spec.release_id == release_id:
            return spec
    return None
