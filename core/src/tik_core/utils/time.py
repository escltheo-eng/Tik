"""Helpers timezone-aware pour Tik core (cf. ADR-013).

Contexte : avant ADR-013, le projet utilisait `datetime.utcnow()` qui
retourne un datetime *naïf* (sans tzinfo). Pydantic le sérialisait
sans suffixe `Z`, JavaScript le réinterprétait comme heure locale, d'où
le bug 8 (décalage de 2 h sur tous les âges affichés au dashboard).

Deux fonctions distinctes :

- `now_utc()` retourne un datetime **aware** (`tzinfo=UTC`). À utiliser
  pour la création de nouveaux objets métier (signal.timestamp,
  decision.timestamp, etc.) et tout ce qui sera sérialisé en JSON.
- `now_utc_naive()` retourne un datetime **naïf** (UTC sémantique mais
  `tzinfo=None`). À utiliser pour :
    1. les `default=` des colonnes SQLAlchemy `DateTime` (sans
       `timezone=True`) — Postgres stocke en TIMESTAMP WITHOUT TIME
       ZONE, asyncpg strippe silencieusement la tz d'un aware mais
       autant garder la cohérence ;
    2. les comparaisons SQL `Signal.timestamp >= since` où la colonne
       est naïve — éviter les `DeprecationWarning` SQLAlchemy 2.

Si on migre un jour les colonnes vers `DateTime(timezone=True)`
(TIMESTAMPTZ Postgres), seule cette dernière fonction sera à supprimer
et `now_utc()` deviendra le seul appel de l'horloge dans le projet.
"""

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Datetime UTC timezone-aware (`tzinfo=UTC`)."""
    return datetime.now(timezone.utc)


def now_utc_naive() -> datetime:
    """Datetime UTC timezone-naïf (`tzinfo=None`).

    Sémantiquement UTC, mais sans tzinfo — destiné aux colonnes
    SQLAlchemy `DateTime` (sans `timezone=True`) et aux comparaisons SQL.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso_utc(value: datetime | None) -> str | None:
    """Sérialise un datetime en ISO-8601 UTC explicite avec suffixe `Z`.

    - `None` → `None`
    - naïf → assumé UTC, suffixé `Z`
    - aware → converti en UTC, suffixé `Z` (`+00:00` normalisé)

    Utilisé par les `field_serializer` Pydantic (cf. `storage/schemas.py`)
    et par le publisher pour les payloads Redis WebSocket — garantit que
    tout timestamp sortant de Tik est UTC explicite, lisible directement
    par `new Date(...)` en JavaScript sans risque de réinterprétation
    en heure locale (cf. ADR-013, bug 8).
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")
