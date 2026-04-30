# tik-sdk

Client Python pour consommer les signaux du **core Tik** — destiné aux bots
clients (Zeta aujourd'hui, Totem demain).

> **Statut** : Sessions 1 + 2 du Paquet 2 livrées — client HTTP + WebSocket
> avec hooks événementiels et reconnexion auto. Cache, telemetry, config
> YAML : sessions 3-5 (cf. plan dans CLAUDE.md section 8).

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

## À venir (sessions suivantes)

- **Session 3** — Cache local (in-memory + Redis optionnel) + fallback
  offline + circuit breaker LOCAL côté SDK.
- **Session 4** — Config YAML hot-reloadable + telemetry feedback
  automatique (`POST /feedback`).
- **Session 5** — Documentation d'intégration overlay Zeta + exemples
  + polish.
