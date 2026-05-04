# ADR-013 — Timezone-aware datetimes (UTC explicite partout)

- **Statut** : Accepté
- **Date** : 2026-05-04

## Contexte

Le 2026-05-04, le bug 8 a été identifié : tous les libellés "il y a X" du dashboard étaient systématiquement en avance de l'écart UTC ↔ heure locale (2 h en CEST, 1 h en CET). Un signal émis il y a 5 min affichait "il y a 2 h 5 min".

**Cause racine** : le core sérialisait tous ses timestamps via `datetime.utcnow()` qui retourne un `datetime` **naïf** (sans tzinfo). Pydantic le sérialisait en chaîne ISO **sans suffixe `Z`** : `"2026-05-04T11:32:14.554767"`. Côté dashboard, `new Date("2026-05-04T11:32:14.554767")` interprète cette chaîne comme **heure locale** (spec ECMA-262), pas UTC. Conséquence : un signal émis à 11:32 UTC était traité côté dashboard comme 11:32 Paris CEST = 09:32 UTC, d'où le décalage systématique.

**Fix appliqué le 2026-05-04 (commit `47b4f4c`)** : utilitaire `parseUtcIso(iso)` côté dashboard qui ajoute `Z` si absent (`dashboard/src/utils/time.ts`). Bug visible côté utilisatrice immédiatement résolu.

**Limite du fix dashboard seul** : le SDK Python (Paquet 2, v0.5.0) et le futur connecteur Zeta n'ont pas ce filet. Tout consommateur autre que le dashboard verrait toujours des datetimes ambigus. Bug 8 a été ajouté à la section 9 de CLAUDE.md avec mention explicite *"Fix backend complémentaire reporté à une session dédiée"*.

ADR-013 traite ce fix backend. Quatre décisions structurantes à acter :

1. **Périmètre** : strict (scoring + storage models seulement) ou étendu (tout le core émettant ou comparant des datetimes) ?
2. **Sérialisation Pydantic** : field_serializer explicite ou BaseModel parent générique ?
3. **Helper centralisé** ou `datetime.now(timezone.utc)` partout ?
4. **Migration Alembic vers TIMESTAMPTZ** maintenant ou plus tard ?

## Décision

### 1. Périmètre — Tous les usages dans `core/src/tik_core/`

**Choix structurant** : tous les `datetime.utcnow()` du core sont remplacés par les helpers `now_utc()` ou `now_utc_naive()` (cf. décision 3). Aucun `datetime.utcnow()` ne subsiste dans `core/src/tik_core/`.

**Alternatives évaluées** :

| Alternative | Pour | Contre rédhibitoire |
|---|---|---|
| Strict (`scoring/*.py` + `storage/models.py` uniquement) | Surface minimale | Laisse 6 occurrences `api/*.py` non fixées. `last_computed` (KPI Home), `created_at` Entity continueraient d'être ambigus. Bug 8 partiellement résolu seulement côté dashboard (qui a `parseUtcIso`), pas côté SDK Python ni futur connecteur Zeta |
| Étendu (B) — scoring + storage + api + auth + scripts | Couvre tous les datetimes vers les consommateurs (dashboard + SDK + Zeta-future) | Laisse 4 occurrences `aggregator/*.py` + `scripts/backtest.py` deprecated en Python 3.12 |
| Maximal (C minimal) — tout `core/src/tik_core/` | Cohérence sémantique parfaite, élimine la dette `datetime.utcnow()` deprecated en un coup | +4 lignes Python supplémentaires vs B (négligeable) |

**Argument décisif** : le coût marginal entre B et C minimal est de 4 lignes. Tirer le trait à mi-chemin laisserait une dette `datetime.utcnow()` (deprecated en Python 3.12) qui reviendra demain comme un boomerang. Mieux vaut nettoyer en un coup.

### 2. Sérialisation Pydantic — `field_serializer` explicite via helper partagé

**Choix structurant** : ajout d'un `@field_serializer` Pydantic V2 explicite sur chaque champ datetime des schémas `Out` (`SignalOut`, `EntityOut`, `FeedbackOut`, `VeracityStatus`). Tous délèguent à un helper unique `iso_utc(value)` dans `core/src/tik_core/utils/time.py` qui :

- `None` → `None`
- naïf → assumé UTC, suffixé `Z` (cas DB SQLAlchemy lecture)
- aware → converti en UTC, suffixé `Z` (offset `+00:00` normalisé en `Z`)

Le serializer s'applique uniquement à la sérialisation **JSON** (`when_used="json"`) — la représentation Python interne (`model_dump()` non-JSON) garde le datetime tel quel pour les usages internes.

**Pourquoi le piège** : SQLAlchemy retourne des datetimes **naïfs** depuis les colonnes `DateTime` (sans `timezone=True`). Sans serializer, Pydantic sortirait `"2026-05-04T11:32:14.554767"` (sans Z) → bug 8 reproduit. Le serializer compense à la sortie en marquant `Z`.

**Alternatives évaluées** :

| Alternative | Pour | Contre rédhibitoire |
|---|---|---|
| `TikBaseModel(BaseModel)` parent avec `@model_serializer` générique | DRY (4 schémas → 1 endroit) | Pydantic V2 : introspection à chaque sérialisation = coût caché. Magie cachée — un dev futur ajoutant un champ datetime ne saurait pas qu'il est UTC-forcé. Bénéfice marginal pour 4 schémas |
| Aucun serializer, `datetime.now(timezone.utc)` partout | Zéro code custom | **CASSE** : SQLAlchemy retourne naïf depuis la DB, Pydantic sortirait sans Z → bug 8 reproduit côté lecture |
| Migration colonnes en `DateTime(timezone=True)` | Le datetime sortant DB est aware naturellement | Lourde (hypertable Timescale `signals`) — voir décision 4 |

### 3. Helper centralisé — `core/src/tik_core/utils/time.py` avec 3 fonctions

**Choix structurant** : nouveau fichier `core/src/tik_core/utils/time.py` exposant 3 fonctions pures :

- `now_utc()` → datetime **aware** (`tzinfo=UTC`). Pour la création de nouveaux objets métier (`signal.timestamp`, `decision.timestamp`, `expiry`, `last_computed`).
- `now_utc_naive()` → datetime **naïf** (UTC sémantique). Pour les `default=` des colonnes SQLAlchemy `DateTime` (sans `timezone=True`) et les comparaisons SQL `Signal.timestamp >= since`.
- `iso_utc(value)` → chaîne ISO-8601 avec suffixe `Z`. Utilisé par les `field_serializer` Pydantic ET par le publisher pour les payloads Redis WebSocket.

**Pourquoi 2 helpers `now_*`** : avec une colonne `DateTime` sans `timezone=True`, comparer à un datetime aware déclenche un `DeprecationWarning` SQLAlchemy 2 (asyncpg strippe silencieusement la tz). `now_utc_naive()` documente l'intention "je compare à une colonne DB sans tz" et reste explicite. Si on migre un jour vers `DateTime(timezone=True)`, seul ce helper sera supprimé, en un seul fichier.

**Alternatives évaluées** :

| Alternative | Pour | Contre |
|---|---|---|
| `datetime.now(timezone.utc)` partout, pas de helper | Stdlib pure | 26+ occurrences. Demain si on migre vers TIMESTAMPTZ, on doit refactorer 26 endroits |
| `now_utc()` aware partout (y compris SQL) | Un seul pattern | Warnings SQLAlchemy. Mélange aware/naïf à la lecture DB devient confus |

**Symétrie côté dashboard** : `dashboard/src/utils/time.ts` (Paquet 3 / commit `47b4f4c`) expose déjà `parseUtcIso`, `timeAgo`, `formatLocal`. Le pattern "1 fichier `utils/time.*` par tier" est désormais cohérent front + back.

### 4. Pas de migration Alembic vers TIMESTAMPTZ

**Choix structurant** : on garde les colonnes `DateTime` (sans `timezone=True`) telles quelles. Postgres stocke en `TIMESTAMP WITHOUT TIME ZONE`, asyncpg strippe silencieusement la tzinfo des aware à l'insertion. Le serializer Pydantic compense à la sortie.

**Pourquoi pas la migration maintenant** :

- La table `signals` est une **hypertable TimescaleDB**. Migrer vers `DateTime(timezone=True)` (TIMESTAMPTZ) impliquerait une migration Alembic non-triviale sur les partitions existantes
- Aucun bug fonctionnel : Postgres TIMESTAMP est sémantiquement UTC partout dans Tik (jamais d'heure locale insérée). Le risque de double-encoding n'existe pas
- Le serializer Pydantic + `iso_utc` dans le publisher couvrent tous les chemins de sortie

**Conditions de bascule future (ADR distinct)** :

- Si Tik gagne un consommateur qui consulte la DB en raw SQL (analyste BI, autre service) et qui assume la tzinfo de la session
- Si Postgres 18+ déprécie un comportement TIMESTAMP qu'on utilise
- Si on ajoute des datetimes en heure locale (jamais le cas aujourd'hui)

### 5. Pas de modification du SDK Python

Le SDK Python (Paquet 2, v0.5.0) consomme l'API REST `/signals/latest`, `/entities`, `/veracity/global`, etc. Tous ces endpoints retournent désormais du JSON avec timestamps `Z`. **Le SDK reçoit donc des datetimes UTC explicites** (parsing Pydantic V2 reconnaît `Z` natif). Aucune modification SDK requise.

**Validation** : le test `test_signal_out_timestamp_naive_serialized_with_z` verrouille que même un datetime naïf depuis la DB sort avec `Z` à la sérialisation Pydantic.

### 6. Asymétrie volontaire avec d'autres ADR

Cette décision **NE modifie pas** :

- **ADR-001** (auth pluggable) — inchangé. `expires_at` et `last_used_at` désormais cohérents UTC explicite.
- **ADR-003** (pas de bypass V01-V15) — inchangé. Aucun nouveau canal d'exécution.
- **ADR-004** (multi-overlay) — inchangé. Les `decision.timestamp` étaient déjà nominalement UTC, juste pas marqués.
- **ADR-005 à ADR-012** — tous compatibles. Le helper `iso_utc` s'applique uniformément à `Signal.timestamp`, `Signal.expiry`, `Signal.advisory.*` (qui ne contient pas de datetime aujourd'hui), etc.

## Conséquences

**Positives**

- **Bug 8 résolu à la source** pour tous les consommateurs (dashboard, SDK Python, futur Zeta). Le `parseUtcIso` côté dashboard reste comme filet forward-compat — double sécurité.
- **Cohérence sémantique** : "tout ce qui sort de Tik est UTC explicite". Convention claire, documentable, vérifiable au grep.
- **Élimination de la dette `datetime.utcnow()`** (deprecated en Python 3.12) sur tout `core/src/tik_core/`. Pas de tour 2 nécessaire.
- **Helper centralisé** : si on migre demain vers TIMESTAMPTZ, 1 seul fichier à toucher (`utils/time.py`). Refactor trivial.
- **2 nouveaux fichiers tests pytest** : `test_utils_time.py` (~9 tests sur les 3 helpers) + `test_schemas_serialization.py` (~10 tests verrouillant le format JSON sortant pour `SignalOut`, `EntityOut`, `VeracityStatus`, `FeedbackOut`, naïf ET aware). Suite complète : 561 → **590 tests verts**, aucune régression.
- **Symétrie front/back** : `core/src/tik_core/utils/time.py` (back) + `dashboard/src/utils/time.ts` (front), même nommage de helpers (`now_utc`, `iso_utc` côté back / `parseUtcIso`, `timeAgo`, `formatLocal` côté front).
- **Compatibilité ADR-014 future** (traduction FR signaux) : la traduction lazy n'a pas à se soucier des datetimes — ils sortent déjà standardisés UTC `Z`.

**Négatives**

- **Pas de migration Alembic vers TIMESTAMPTZ** : la table `signals` (hypertable) garde du `TIMESTAMP WITHOUT TIME ZONE`. Un consommateur futur qui interrogerait la DB en raw SQL devra savoir que la sémantique est UTC (à documenter dans le README si besoin).
- **2 fonctions `now_*` au lieu d'une** : `now_utc()` aware pour les nouveaux objets, `now_utc_naive()` pour les défauts colonnes et comparaisons SQL. Cohérent mais nécessite une légère vigilance (le caller doit choisir).
- **Le payload Redis WebSocket sortait avec `+00:00` si on avait laissé `signal.timestamp.isoformat()` brut** — résolu en utilisant `iso_utc(signal.timestamp)` dans `_publish_signal`. À ne pas oublier si on ajoute d'autres canaux de sortie (push notifications, MQTT, etc.).

**Risques opérationnels rappelés**

- **Garde-fou 1 (mode shadow Tik vs Zeta 3 mois)** **strictement applicable**. Ce fix ne touche pas la logique d'exécution Zeta — uniquement la sérialisation des timestamps émis par Tik.
- **ADR-003 (pas de bypass V01-V15)** **inchangé**. Aucun nouveau canal d'exécution.
- **Garde-fou 2 (budget test 5%)** rappelé pour mémoire au moment du switch shadow → actif Zeta.
- **Section 6 paranoïa contrôlée** : maintenue. Ce fix est purement technique (timezone), pas décisionnel.

## Glissement de la réservation ADR-013

ADR-012 ligne 57 réservait à l'origine ADR-013 pour la traduction FR des signaux. Avec cette décision, ADR-013 = timezone fix, et la traduction FR glisse à **ADR-014** (à rédiger plus tard). Mises à jour effectuées :

- ADR-012 ligne 57 : "ADR-013" → "ADR-014"
- `docs/backlog.md` entry #2 : "ADR-013" → "ADR-014"
- CLAUDE.md section 8 (Paquet 6) : mention "ADR-013 réservé" → "ADR-014 réservé"

## Implémentation (fichiers touchés)

### Nouveaux

- `core/src/tik_core/utils/__init__.py` *(nouveau, marqueur de package)*
- `core/src/tik_core/utils/time.py` *(nouveau, ~50 lignes : `now_utc` + `now_utc_naive` + `iso_utc`)*
- `core/tests/test_utils_time.py` *(9 tests pytest)*
- `core/tests/test_schemas_serialization.py` *(10 tests pytest)*
- `docs/adr/013-timezone-aware-datetimes.md` *(ce fichier)*

### Modifiés (17 fichiers)

- `core/src/tik_core/storage/models.py` *(8 défauts `datetime.utcnow` → `now_utc_naive`)*
- `core/src/tik_core/storage/schemas.py` *(field_serializer UTC sur 4 schémas via `iso_utc`)*
- `core/src/tik_core/scoring/swing_engine.py` *(2 occurrences, `now_utc()`)*
- `core/src/tik_core/scoring/flash_engine.py` *(3 occurrences, `now_utc()`)*
- `core/src/tik_core/scoring/publisher.py` *(2 occurrences `now_utc()` + 2 `iso_utc()` payload Redis)*
- `core/src/tik_core/scoring/source_credibility.py` *(2 occurrences SQL → `now_utc_naive()`)*
- `core/src/tik_core/api/signals.py` *(1 occurrence SQL → `now_utc_naive()`)*
- `core/src/tik_core/api/entities.py` *(3 occurrences `now_utc_naive()`)*
- `core/src/tik_core/api/veracity.py` *(2 occurrences `now_utc()`)*
- `core/src/tik_core/auth/api_key.py` *(2 occurrences `now_utc_naive()`)*
- `core/src/tik_core/scripts/run_scheduler.py` *(1 occurrence `now_utc()`)*
- `core/src/tik_core/scripts/backtest.py` *(1 occurrence SQL → `now_utc_naive()`)*
- `core/src/tik_core/scripts/create_api_key.py` *(1 occurrence `now_utc_naive()`)*
- `core/src/tik_core/aggregator/fred_ingester.py` *(1 occurrence `now_utc()`)*
- `core/src/tik_core/aggregator/yahoo_ingester.py` *(1 occurrence `now_utc()`)*
- `core/tests/test_source_credibility.py` *(4 occurrences `datetime.utcnow()` → `now_utc_naive()`)*

### Documentation

- `docs/adr/012-llm-hypothesis-generator.md` *(ligne 57 : "ADR-013" → "ADR-014")*
- `docs/backlog.md` *(entry #2 réservation : "ADR-013" → "ADR-014")*
- `docs/comprendre_tik.md` *(nouvelle section 14 "Pourquoi tous les timestamps Tik portent un Z")*
- `CLAUDE.md` *(section 9 bug 8 — fix backend résolu, section 8 — Paquet livré, pied de page MAJ version)*
