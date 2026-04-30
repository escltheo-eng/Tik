# ADR-007 — Architecture du SDK Python `tik-sdk`

- **Statut** : Accepté
- **Date** : 2026-04-30

## Contexte

Le Paquet 2 du projet livre un **SDK Python** (`sdk/`) destiné à être
consommé par Zeta (et plus tard Totem). Le SDK doit :

1. Exposer la lecture de signaux Tik via HTTP REST + WebSocket.
2. Renvoyer la telemetry des trades exécutés (PnL, win/loss) au core.
3. Rester robuste si le core Tik tombe (cf. ADR-003 *« si Tik est down,
   Zeta continue normalement »*).
4. **Ne JAMAIS** offrir de canal d'exécution d'ordres ni de bypass du
   guard V01-V15 de Zeta (cf. ADR-003).

Plusieurs choix d'architecture devaient être figés avant de commencer
le développement. Les décisions sont consignées ici pour servir de
référence aux futures évolutions.

## Décision

### 1. SDK strictement **read-only** côté signaux

Le `TikClient` n'expose **aucune** méthode `place_order`, `execute`,
`buy`, `sell`, `bypass_guard`, `force_signal`, etc. Un test pytest
(`test_client_does_not_expose_execution_methods`) vérifie en CI cette
propriété et bloquerait toute future PR qui tenterait d'ajouter un
tel chemin.

La **seule** opération d'écriture exposée est `report_outcome()` —
telemetry retour vers `POST /feedback`, **non bloquante** (cf. § 5).

### 2. Tout est `async`

Le SDK utilise `asyncio` partout. Justifications :

- Cohérence avec le core (FastAPI/uvicorn async).
- Permet de gérer simultanément HTTP, WebSocket, queue feedback,
  watcher de config, sans threads.
- `httpx.AsyncClient` et `websockets` sont les deux meilleurs choix
  pour ces deux protocoles en async.

Conséquence : Zeta doit appeler le SDK depuis un event loop
asyncio. Comme `cranial_bot/turbo_v2.py` est déjà majoritairement
async, c'est sans friction.

### 3. Pluggable partout via le pattern Strategy

Cohérent avec ADR-001 (auth pluggable) et ADR-006 (NLP pluggable),
les briques du SDK sont conçues comme des interfaces abstraites + une
implémentation par défaut :

| Brique             | Interface         | Implémentations livrées                          |
|--------------------|-------------------|--------------------------------------------------|
| Authentification   | `AuthMethod`      | `ApiKeyAuth` (Bearer + query param WS)           |
| Cache              | `Cache`           | `NoCache` (défaut), `InMemoryCache`              |
| Hooks événementiels| `HookRegistry`    | générique, sync OU async, isolation exceptions   |
| Auth WS            | `query_params()`  | extension de `AuthMethod`, override par méthode  |

Future : `OAuth2Auth`, `RedisCache`, `MtlsAuth` viendront se brancher
sur ces interfaces sans toucher au cœur du SDK.

### 4. Lifecycle géré par `async with`

`TikClient`, `TikStream`, `FeedbackQueue`, `ConfigWatcher` sont tous
des **async context managers**. Ouverture explicite (start worker /
charger config), fermeture explicite (stop worker / drain ou drop /
fermer connexion HTTP).

L'usage canonique :

```python
async with TikClient.from_config(config, auth=ApiKeyAuth(api_key)) as client:
    async with client.stream(entity="BTC", horizon="swing") as stream:
        stream.on_signal(handle)
        await stream.run()
```

Garantit qu'aucune ressource n'est laissée pendante en cas d'exception
ou de Ctrl+C.

### 5. Telemetry feedback **non bloquante**

`POST /feedback` ne doit JAMAIS retarder un trade Zeta. Implémentation :

- `report_outcome()` valide via Pydantic puis fait `queue.put_nowait()`.
  Retour immédiat (booléen `True` si accepté, `False` si queue pleine).
- Un worker async sort les payloads et fait le POST en arrière-plan.
- Retry exponentiel borné (défaut 3 tentatives, backoff 1/2/4 s).
- 4xx (404 si signal inconnu) → pas de retry, drop direct.
- Au-delà du retry → drop avec log error.
- Pas de queue persistante en Session 4 — les payloads en file sont
  perdus si le SDK crash. Acceptable car la prochaine émission de
  signal Tik recalibrera de toute façon. Persistance (SQLite ou Redis)
  pourra être ajoutée plus tard si l'opérationnel l'exige.

### 6. Cache local **opt-in**, sans dépendance externe par défaut

Sans configuration, le SDK utilise `NoCache` (no-op) — comportement
identique à un client HTTP nu. L'opt-in se fait au constructeur :

```python
TikClient(..., cache=InMemoryCache(maxsize=1000))
```

`InMemoryCache` est en stdlib pure (`OrderedDict` LRU + TTL), zéro
dépendance externe. `RedisCache` viendra via extras `[redis]` quand on
aura besoin de partager le cache entre processus.

TTL adapté à l'horizon : flash 60 s, swing 300 s, macro 3600 s
(alignés sur les expiry du publisher core, cf. ADR-005).

### 7. Circuit breaker **LOCAL** indépendant du core

Le `circuit_breaker_status` qu'on lit dans les `Signal` est **celui
du core** (anti-fake-news, à venir). Le `CircuitBreaker` du SDK est
**différent** : il protège contre l'épuisement des ressources réseau
quand le core est injoignable.

Trois états : `closed → open → half_open → closed/open`. Compteur
d'échecs consécutifs, timer de reset, `time_fn` injectable pour des
tests déterministes.

POST `/feedback` n'est volontairement **pas** soumis au circuit
breaker (sinon les retries du worker l'ouvriraient et ça bloquerait
les GET de signaux — couplage indésirable). Le worker feedback fait
son propre retry isolé.

### 8. Config YAML hot-reload, mais périmètre limité

Toutes les briques du SDK peuvent être pilotées par `tik.yaml`. Le
`ConfigWatcher` poll la mtime du fichier (défaut 5 s — pas de
dépendance à `watchdog`/inotify pour la portabilité).

**Périmètre du hot-reload** :

| Mutables à chaud                          | Non mutables (warning loggué)                    |
|-------------------------------------------|--------------------------------------------------|
| `cache.ttl_by_horizon`                    | `core.base_url`, `core.timeout_s`                |
| `stream.veracity_collapse_threshold`      | `cache.enabled`, `cache.maxsize`                 |
|                                           | `circuit_breaker.*`                              |
|                                           | `feedback.*`                                     |

Justification : changer `base_url` ou `breaker.failure_threshold`
nécessiterait de recréer `httpx.AsyncClient` ou `CircuitBreaker` à
chaud, avec des risques de fuite de connexions / état partiellement
recréé. Restart du SDK est plus sûr et acceptable (Zeta tourne 24/7
mais les redémarrages contrôlés sont prévus).

Si le YAML est cassé au reload → log error + **conservation de
l'ancien config** (jamais d'état corrompu).

### 9. WebSocket avec reconnexion automatique

Pas d'option « ne pas se reconnecter ». La reconnexion est transparente,
backoff exponentiel + jitter pour désynchroniser plusieurs SDK clients
après crash core. Backoff plafonné à 60 s. Reset à chaque connexion
réussie.

Si le handshake renvoie 401/403 → `AuthError` immédiate sans retry
(évite le hammer sur clé révoquée).

### 10. Hooks événementiels génériques + isolation des exceptions

`HookRegistry` accepte handlers sync OU async, plusieurs handlers par
événement. Une exception dans un handler est **loggée et avalée** —
les autres handlers sont quand même appelés, et la boucle WS continue.

Justification : un bot qui tourne 24/7 ne peut pas tomber à cause
d'une exception dans un handler de telemetry. Mieux vaut perdre un
événement que perdre tout le stream.

## Conséquences

**Positives**

- Aucun risque que le SDK contourne le guard V01-V15 de Zeta — le test
  ADR-003 le verrouille.
- Toutes les briques sont remplaçables (Strategy partout) → évolutions
  futures faciles (Redis cache, OAuth2, etc.).
- Lifecycle async with → pas de fuite de ressource.
- Telemetry non bloquante → ADR-003 § « si Tik est down, Zeta continue »
  respecté.
- Cache + breaker opt-in → pas de surprise pour qui veut le SDK basique.
- 186 tests pytest verts en 17 s, dont des tests d'intégration WS avec
  vrai serveur — couverture solide.

**Négatives**

- 5 modules disjoints (`auth`, `cache`, `circuit_breaker`, `hooks`,
  `feedback`, `config`, `_http`, `_ws`, `stream`, `client`, `models`,
  `exceptions`) → courbe d'apprentissage initiale plus longue qu'un
  client HTTP plat. Atténué par la doc + les exemples de Session 5.
- Hot-reload limité aux settings mutables → certaines évolutions
  nécessitent un restart. Acceptable pour le scope MVP.
- Pas de queue persistante pour la telemetry → perte possible des
  payloads en file si crash. Documenté ; persistance plus tard si
  besoin opérationnel.

## Alternatives rejetées

- **SDK synchrone** : aurait forcé Zeta à utiliser `asyncio.run_in_executor`
  pour chaque appel. Incompatible avec la nature async de
  `cranial_bot/turbo_v2.py`. Rejeté.
- **Cache toujours actif par défaut** : surprenant, pourrait masquer
  des incidents (cache hit alors qu'on s'attend à de la fraîcheur).
  Opt-in plus sûr.
- **Telemetry synchrone bloquante** : violerait directement ADR-003.
  Rejeté.
- **Watchdog (inotify/fsevents) pour le hot-reload** : ajoute une
  dépendance système, peu fiable cross-platform pour les éditeurs qui
  font « write + rename » plutôt que « write in place ». Polling 5 s
  est largement suffisant pour de la config qui change rarement.
- **Une classe géante `TikClient` avec tout dedans** : moins maintenable
  et casserait le principe Strategy. Modules disjoints retenus.

## Versionnage

- 0.1.0 → fondations + HTTP (Session 1)
- 0.2.0 → + WebSocket + hooks (Session 2)
- 0.3.0 → + cache + circuit breaker (Session 3)
- 0.4.0 → + telemetry feedback + config YAML (Session 4)
- 0.5.0 → + doc intégration Zeta + exemples + ADR-007 + CI (Session 5)
- 1.0.0 → bumped quand le SDK sera **wiré en production** dans Zeta et
  aura passé les 3 mois de mode shadow (Garde-fou 1, cf. CLAUDE.md § 5).
