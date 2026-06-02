# tik-sdk

Client Python pour consommer les signaux du **core Tik** — destiné aux bots
clients (Zeta aujourd'hui, Totem demain).

> ## 🧊 COUCHE GELÉE (depuis le 2026-06-01 — cf. [ADR-022](../docs/adr/022-gel-couche-zeta-sdk.md))
>
> **On ne code plus rien dans ce dossier.** Le trading est 100 % manuel, Zeta
> n'est pas câblé, et aucun plan daté ne l'exige. Le code est conservé intact
> (gel **réversible à coût nul**). Toute instance Claude : **ne pas modifier
> `sdk/` ni proposer de l'améliorer**, sauf demande explicite liée à un câblage
> Zeta réel. Critère de dégel dans l'ADR-022.

> **Statut Paquet 2 : ✅ COMPLET** — Sessions 1 à 5 livrées le 2026-04-30.
> Version 0.6.0 (gelée). Le SDK sera bumpé à 1.0.0 quand il sera wiré dans Zeta
> en production et aura passé les 3 mois de mode shadow.

## Liens utiles

- **[`docs/integration_zeta.md`](../docs/integration_zeta.md)** — guide
  concret pour câbler le SDK dans `cranial_bot/turbo_v2.py` de Zeta sans
  bypass V01-V15. **À lire avant toute intégration.**
- **[`docs/adr/007-sdk-architecture.md`](../docs/adr/007-sdk-architecture.md)**
  — ADR-007 qui formalise les choix d'architecture du SDK.
- **[`docs/adr/003-zeta-integration.md`](../docs/adr/003-zeta-integration.md)**
  — règle absolue ADR-003 : pas de bypass du guard V01-V15.
- **[`sdk/tik.example.yaml`](tik.example.yaml)** — config YAML annotée
  prête à copier-coller.
- **[`sdk/examples/`](examples/)** — 4 exemples runnable (basic, streaming,
  overlay Zeta, full resilience).

## Production checklist

Avant de mettre le SDK en service réel côté Zeta :

- [ ] CLAUDE.md sections 4-5 (ADR + garde-fous) lues.
- [ ] ADR-003 (intégration sans bypass V01-V15) **explicitement validé**.
- [ ] Garde-fou 1 (mode SHADOW 3 mois minimum) en place — Tik observe,
      n'influence rien.
- [ ] Garde-fou 2 (budget test 5 % capital) prêt pour le passage en
      mode actif après les 3 mois shadow.
- [ ] Clé API Tik générée via `core/scripts/create_api_key.py` avec
      les scopes `read:signals`, `read:entities`, `read:veracity`,
      `write:feedback`. Pas de `write:entities`.
- [ ] `tik.yaml` copié depuis `sdk/tik.example.yaml` et adapté.
- [ ] Logs `tik.overlay.*`, `tik.crash_warning.*`, `tik.feedback.*`
      monitorés.
- [ ] Tests Zeta couvrent le cas « Tik down » (overlay no-op, fallback cache).

## Règle fondamentale (ADR-003)

Le SDK est volontairement **sans canal d'exécution**.

- Aucune méthode du `TikClient` ne place un ordre, ne contourne ni ne
  désactive le guard V01-V15 de Zeta.
- Tik est une **source d'edge additionnelle** pour `cranial_bot/turbo_v2.py`
  de Zeta, pas un raccourci d'exécution.
- Le mode shadow 3 mois (Garde-fou 1) et le budget test 5 % (Garde-fou 2)
  sont à respecter avant toute connexion réelle.

Un test automatique (`test_client_does_not_expose_execution_methods`)
vérifie qu'aucune méthode `place_order`, `execute`, `trade`, `buy`,
`sell`, `bypass_guard`… ne soit ajoutée par mégarde dans une session
future.

## Installation (en mode développement, depuis la racine du repo)

```bash
pip install -e ./sdk
```

Pour développer :

```bash
pip install -e "./sdk[dev]"
```

## Utilisation minimale

```python
import asyncio
from tik_sdk import TikClient, ApiKeyAuth

async def main():
    async with TikClient("http://localhost:8200", ApiKeyAuth("tik_xxx")) as client:
        health = await client.get_health()
        print(health.status, health.version)

        signals = await client.get_latest_signals(entity="BTC", horizon="swing", limit=5)
        for s in signals:
            print(s.id, s.direction, s.confidence, s.veracity)

asyncio.run(main())
```

## Endpoints HTTP couverts (Session 1)

| Méthode SDK                       | Endpoint Tik                          |
|-----------------------------------|---------------------------------------|
| `get_health()`                    | `GET /api/v1/health` (sans auth)      |
| `list_entities(active_only=True)` | `GET /api/v1/entities`                |
| `get_entity(id)`                  | `GET /api/v1/entities/{id}`           |
| `get_latest_signals(...)`         | `GET /api/v1/signals/latest`          |
| `get_signal(id)`                  | `GET /api/v1/signals/{id}`            |
| `search_signals(...)`             | `GET /api/v1/signals`                 |
| `get_global_veracity()`           | `GET /api/v1/veracity/global`         |
| `list_sources(active_only=True)`  | `GET /api/v1/veracity/sources`        |
| `get_source(id)`                  | `GET /api/v1/veracity/sources/{id}`   |

## Streaming WebSocket + hooks événementiels (Session 2)

```python
import asyncio
from tik_sdk import TikClient, ApiKeyAuth, Signal

async def on_new_signal(s: Signal):
    print(f"[{s.entity_id}/{s.horizon}] {s.direction} conf={s.confidence:.2f} verac={s.veracity:.2f}")

async def on_collapse(s: Signal):
    # ADR-003 — Tik n'exécute jamais lui-même. On notifie Zeta via son
    # kill_switch_service (la SEULE voie autorisée pour freezer Zeta).
    print(f"⚠️ veracity collapse sur {s.entity_id} : {s.veracity}")

async def main():
    async with TikClient("http://localhost:8200", ApiKeyAuth("tik_xxx")) as client:
        stream = client.stream(entity="BTC", horizon="swing", veracity_collapse_threshold=0.5)
        stream.on_signal(on_new_signal)
        stream.on_veracity_collapse(on_collapse)
        async with stream:
            await stream.run()  # bloque jusqu'à stream.stop() ou Ctrl+C

asyncio.run(main())
```

### Quatre hooks disponibles

| Méthode                          | Déclencheur                                                    |
|----------------------------------|----------------------------------------------------------------|
| `on_signal(handler)`             | Tout signal reçu                                               |
| `on_crash_warning(handler)`      | `signal.advisory.macro_crash_warning is True` *(dormant aujourd'hui)* |
| `on_fake_news_detected(handler)` | `signal.circuit_breaker_status != "ok"` *(dormant aujourd'hui)* |
| `on_veracity_collapse(handler)`  | `signal.veracity < veracity_collapse_threshold` (défaut 0.5)   |

Les handlers peuvent être **sync ou async**. Une exception dans un handler est
loggée mais **n'arrête pas la boucle** ni les autres handlers — critique pour
un bot qui tourne 24/7.

### Reconnexion automatique

Si la connexion WS tombe (core en redémarrage, réseau coupé, etc.), le SDK
reconnecte automatiquement avec **backoff exponentiel + jitter** : 1 s → 2 s →
4 s → … plafonné à 60 s, désynchronisation aléatoire de 0-0.5 s pour éviter
le thundering herd. Le backoff se reset à chaque connexion réussie.

Si le handshake est refusé en 401/403, on lève `AuthError` immédiatement
(pas de retry sur clé invalide).

## Hiérarchie d'exceptions

```
TikError                  # base — capturer ça pour un fallback unique
├── AuthError             # 401 / 403
├── NotFoundError         # 404
├── ServerError           # 5xx côté core
└── NetworkError          # connexion / timeout / DNS
```

## Pattern d'authentification (pluggable, ADR-001)

`ApiKeyAuth` aujourd'hui. Future extension via la même interface
abstraite `AuthMethod` :

```python
class OAuth2Auth(AuthMethod):
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._access_token}"}
```

## Tests

```bash
cd sdk
pip install -e ".[dev]"
pytest -v
```

## Résilience : cache local + circuit breaker LOCAL (Session 3)

Tout est **opt-in**. Sans rien configurer, le SDK se comporte comme avant
(direct HTTP). Quand tu actives `cache=` et/ou `circuit_breaker=`, le SDK
absorbe les pannes du core Tik pour que ton bot continue à fonctionner —
strictement aligné sur ADR-003 *« si Tik est down, Zeta continue normalement »*.

```python
import asyncio
from tik_sdk import (
    TikClient, ApiKeyAuth,
    InMemoryCache, CircuitBreaker,
)

async def main():
    async with TikClient(
        "http://localhost:8200",
        ApiKeyAuth("tik_xxx"),
        cache=InMemoryCache(maxsize=1000),
        circuit_breaker=CircuitBreaker(failure_threshold=5, reset_timeout_s=30),
    ) as client:
        # Premier appel : HTTP + mise en cache (TTL adapté à l'horizon)
        signals = await client.get_latest_signals(entity="BTC", horizon="swing")
        # Appel suivant à l'intérieur du TTL : cache hit, pas de HTTP
        signals = await client.get_latest_signals(entity="BTC", horizon="swing")

asyncio.run(main())
```

### TTL par horizon (défauts)

| Horizon  | TTL | Pourquoi |
|----------|-----|----------|
| `flash`  | 60 s    | données qui bougent vite (BTC minutes) |
| `swing`  | 5 min   | swing typique RSI/MACD |
| `macro`  | 1 h     | macro lent (DXY, FRED) |
| autre    | 5 min   | entities, veracity, signal par id, etc. |
| `/health`| **jamais cached** | sinon on cache un état périmé |

Override possible : `TikClient(..., ttl_by_horizon={"flash": 30, "swing": 120, ...})`.

### Comportement du circuit breaker

États : `closed` (tout va bien) → après `failure_threshold` échecs consécutifs
→ `open` (refuse toutes les nouvelles requêtes pendant `reset_timeout_s`) → 
`half_open` (laisse passer 1 requête de test) → `closed` si succès, `open`
sinon (timer redémarré).

- Une réponse **5xx** (erreur côté core) compte comme échec → fait avancer le breaker.
- Une réponse **4xx** (404, 401, 403) ne compte **pas** : c'est un problème
  de requête, pas de disponibilité.
- Quand le breaker est `open` mais qu'un **cache hit** est disponible, le
  cache sert directement (court-circuit total — pas de HTTP, pas d'exception).
- Quand le breaker est `open` ET cache miss : `CircuitBreakerOpen` levée.

### Bascule sur Redis (futur)

L'interface `Cache` est pluggable. Le jour où tu veux partager le cache
entre plusieurs processus (ex : plusieurs instances de Zeta), une
implémentation `RedisCache(redis_url=...)` viendra dans `tik_sdk.cache`
sans toucher au reste du SDK. À ajouter via `pip install tik-sdk[redis]`.

## Telemetry feedback non-bloquante (Session 4)

Quand un trade Zeta se termine sur un signal Tik, on renvoie le résultat
au core pour qu'il recalibre ses engines. **`report_outcome()` est non
bloquant** (ADR-003) — l'envoi part en file et un worker async POST en
arrière-plan avec retry exponentiel.

```python
async with TikClient(...) as client:
    # Après fermeture d'un trade côté Zeta
    await client.report_outcome(
        signal_id="TIK-SWING-BTC-20260430-abc123",
        outcome="win",       # 'win' | 'loss' | 'breakeven' | 'not_taken'
        trade_id="trade_42",
        pnl_pct=1.4,
        duration_held_s=4200,
        exit_reason="TP",
    )
    # ↑ retour immédiat, le HTTP part en background
```

Comportement :
- Queue async par défaut (capacité 1000). Si pleine → drop avec log warning.
- Worker async POST `/feedback`. Si NetworkError → retry (défaut 3 fois,
  backoff 1s/2s/4s). Au-delà → drop avec log error.
- Erreurs 4xx (404 si signal inconnu) → pas de retry, drop direct avec log.
- À l'arrêt du `TikClient` (`__aexit__`), worker stoppé en fast shutdown
  (drop ce qui reste). Pour drainer proprement avant stop : 
  `await client.feedback_queue.stop(drain=True, timeout_s=10)`.

Pas de queue persistante en Session 4 : si le SDK crash, les feedbacks en
file sont perdus. Acceptable pour le MVP — le core peut être recalibré
sur les cycles suivants.

## Config YAML hot-reloadable (Session 4)

Toutes les briques précédentes (cache, breaker, hooks, feedback) peuvent
être pilotées par un fichier YAML rechargé à chaud.

`tik.yaml` :

```yaml
core:
  base_url: http://localhost:8200
  timeout_s: 10.0

cache:
  enabled: true
  maxsize: 1000
  ttl_by_horizon:
    flash: 60
    swing: 300
    macro: 3600
    default: 300

circuit_breaker:
  enabled: true
  failure_threshold: 5
  reset_timeout_s: 30.0

stream:
  veracity_collapse_threshold: 0.5

feedback:
  enabled: true
  max_queue_size: 1000
  max_retries: 3
```

Usage :

```python
from tik_sdk import TikClient, ApiKeyAuth, TikConfig, ConfigWatcher

config = TikConfig.load_from_yaml("tik.yaml")

async with TikClient.from_config(config, auth=ApiKeyAuth("tik_xxx")) as client:
    # Hot-reload : poll mtime toutes les 5 s, applique les settings mutables
    async with ConfigWatcher("tik.yaml", poll_interval_s=5.0) as watcher:
        watcher.on_reload(lambda old, new: client.apply_mutable_config(new))
        # ... ton bot tourne ici
```

Périmètre du hot-reload :
- **Mutables à chaud** : `cache.ttl_by_horizon`, `stream.veracity_collapse_threshold`.
- **Non mutables** (logué warning au reload) : `core.base_url`, `core.timeout_s`,
  `cache.enabled`, `cache.maxsize`, `circuit_breaker.*`, `feedback.*`.
  Ces changements nécessitent un redémarrage du SDK.

Sécurité :
- Si le YAML est cassé au reload → log error, on **garde l'ancien config**
  (jamais d'état corrompu).
- Si un handler de reload plante → log error, les autres handlers sont
  quand même appelés (isolation des exceptions).

## Roadmap

- **Paquet 2 (SDK)** — ✅ complet. Versions 0.1.0 → 0.5.0.
- **v1.0.0** — bumpé quand le SDK aura été déployé en production côté
  Zeta et qu'il aura passé les 3 mois de mode shadow (cf. CLAUDE.md § 5).
- **Extensions futures** :
  - `RedisCache` via extras `[redis]` quand on aura besoin de partager
    le cache entre processus (ex : plusieurs instances de Zeta).
  - `OAuth2Auth` si le core Tik accepte un jour OAuth2 (cf. ADR-001).
  - Queue feedback persistante (SQLite ou Redis) si l'opérationnel
    montre que les pertes de queue lors de crash sont gênantes.
  - Watchdog inotify/fsevents si le polling mtime 5 s devient un
    facteur limitant (peu probable pour de la config qui change rarement).
