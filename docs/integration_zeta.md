# Intégration Tik ↔ Zeta — guide concret

> **À qui s'adresse ce document** : à toute personne (humaine ou Claude)
> qui s'apprête à câbler le SDK `tik-sdk` dans Zeta. Suppose que tu as
> lu CLAUDE.md sections 4-5 (ADR + garde-fous) et ADR-003.

## Rappel des règles non-négociables

1. **ADR-003 — pas de bypass du guard V01-V15**. Tik est une **source
   d'edge additionnelle** pour `turbo_v2.py`, jamais un canal d'exécution
   privilégié. Le SDK ne contient aucune méthode `place_order`,
   `execute`, etc. (verrouillé par test).
2. **Garde-fou 1 — mode SHADOW obligatoire 3 mois minimum**. Pendant
   cette période, Tik observe Zeta (statut, positions, PnL) mais
   **n'influence aucun trade**. Aucun signal Tik n'est relayé vers
   `turbo_v2.py` en mode actif tant que les 3 mois ne sont pas passés.
3. **Garde-fou 2 — budget test 5 % maximum** lors du passage en mode
   actif. Compte Zeta de test séparé. Pendant 1 mois minimum.
4. Toute proposition qui contourne 1, 2 ou 3 doit **alerter
   l'utilisateur explicitement** et lui rappeler ces règles.

## Vue d'ensemble

```
                    ┌───────────────────────────┐
                    │       Core Tik            │
                    │  (FastAPI + Postgres +    │
                    │   Redis + ingesters)      │
                    └──────────┬────────────────┘
                               │
                    ┌──────────┴────────────────┐
                    │                            │
              HTTP REST                    WebSocket
              (signals,                    (stream live
               feedback)                    + hooks)
                    │                            │
                    ▼                            ▼
                ┌────────────────────────────────────┐
                │           tik-sdk Python           │
                │  TikClient + TikStream + queues    │
                └──────────────┬─────────────────────┘
                               │
                          (async calls)
                               │
                ┌──────────────▼─────────────────────┐
                │              ZETA                   │
                │  cranial_bot/turbo_v2.py            │  ← overlay confidence
                │  cranial_bot/micro_live_guard.py    │  ← V16 optionnel
                │  services/kill_switch_service.py    │  ← hook crash
                │  services/risk_engine.py            │  (intouché)
                │  api/websocket_router.py            │  ← relay scores Tik vers UI
                └─────────────────────────────────────┘
```

Tik **augmente** Zeta. Aucun fichier Zeta n'est **remplacé**.

## Pattern 1 — Overlay confidence dans `turbo_v2.py`

**But** : prendre le signal interne de Zeta, et le moduler à la marge
selon ce que Tik dit. Le `risk_engine.py` et le guard V01-V15
**continuent de fonctionner exactement comme avant**.

### Code à ajouter dans `cranial_bot/turbo_v2.py`

```python
# En haut du fichier, à côté des autres imports :
from tik_sdk import TikClient, TikError

# Au démarrage de la classe (ex : __init__ ou un setup() async) :
self._tik_client = None  # lazy init

async def _get_tik_client(self) -> TikClient | None:
    """Retourne un client Tik prêt, ou None si Tik est désactivé."""
    if not self.config.tik_enabled:
        return None
    if self._tik_client is None:
        from tik_sdk import ApiKeyAuth, InMemoryCache, CircuitBreaker
        self._tik_client = TikClient(
            base_url=self.config.tik_base_url,        # ex "http://localhost:8200"
            auth=ApiKeyAuth(self.config.tik_api_key),
            cache=InMemoryCache(maxsize=500),
            circuit_breaker=CircuitBreaker(failure_threshold=5, reset_timeout_s=30),
        )
        await self._tik_client.__aenter__()
    return self._tik_client


async def _apply_tik_overlay(self, internal_signal):
    """Applique l'overlay Tik sur la confidence du signal interne.

    AUCUN court-circuit du guard V01-V15. AUCUN remplacement du signal.
    On modifie uniquement `internal_signal.confidence` à la marge.
    """
    client = await self._get_tik_client()
    if client is None:
        return internal_signal  # Tik désactivé → bypass propre

    try:
        tik_signals = await client.get_latest_signals(
            entity=internal_signal.symbol,    # "BTC" ou "GOLD"
            horizon="swing",                  # ou "flash" selon ton bot
            limit=1,
        )
    except TikError as exc:
        # Tik est down → on continue sans overlay (ADR-003)
        log.warning("tik.overlay.unavailable", error=str(exc))
        return internal_signal

    if not tik_signals:
        return internal_signal

    tik = tik_signals[0]

    # Vérifier que le signal Tik est encore valide
    if tik.expiry and tik.expiry < datetime.utcnow():
        log.debug("tik.overlay.signal_expired", id=tik.id)
        return internal_signal

    # Vérifier que Tik n'est pas en circuit breaker (anti-fake-news du core)
    if tik.circuit_breaker_status != "ok":
        log.warning("tik.overlay.circuit_tripped_skip", id=tik.id)
        return internal_signal

    # Modulation : facteur = confidence_tik × veracity_tik
    # → varie entre 0 et 1, plafonné par les facteurs ci-dessous
    factor = tik.confidence * tik.veracity

    if tik.direction == internal_signal.direction:
        # Tik confirme → on boost la confidence (max +20%)
        boost = factor * 0.20
        new_confidence = min(1.0, internal_signal.confidence + boost)
        log.info(
            "tik.overlay.boost",
            internal=internal_signal.confidence,
            boost=boost,
            new=new_confidence,
            tik_id=tik.id,
        )
    elif tik.direction != "neutral":
        # Tik contredit → on baisse la confidence (max -15%)
        penalty = factor * 0.15
        new_confidence = max(0.0, internal_signal.confidence - penalty)
        log.info(
            "tik.overlay.penalty",
            internal=internal_signal.confidence,
            penalty=penalty,
            new=new_confidence,
            tik_id=tik.id,
        )
    else:
        # Tik est neutre → pas de modulation
        new_confidence = internal_signal.confidence

    internal_signal.confidence = new_confidence
    internal_signal.tik_signal_id = tik.id  # pour la telemetry feedback (Pattern 4)
    return internal_signal
```

### Insertion dans la boucle de décision

Là où `turbo_v2.py` produit aujourd'hui `internal_signal` puis appelle
`micro_live_guard.evaluate(signal)` :

```python
# AVANT (sans Tik) :
internal_signal = self._evaluate_market_data(market_data)
guard_result = await self.micro_live_guard.evaluate(internal_signal)
if guard_result.allowed:
    await self.risk_engine.size_and_send(internal_signal)

# APRÈS (avec overlay Tik) :
internal_signal = self._evaluate_market_data(market_data)
internal_signal = await self._apply_tik_overlay(internal_signal)  # ← UNE LIGNE
guard_result = await self.micro_live_guard.evaluate(internal_signal)
if guard_result.allowed:
    await self.risk_engine.size_and_send(internal_signal)
```

**Exactement une ligne ajoutée** dans la boucle de décision. Le guard
et le risk engine continuent de fonctionner normalement.

## Pattern 2 — Hook crash → `kill_switch_service`

**But** : si Tik détecte un risque de crash macro (`Signal.advisory.macro_crash_warning = True`),
on freezer Zeta via le `kill_switch_service` existant. C'est la **seule**
voie autorisée par ADR-003 pour Tik d'arrêter Zeta.

### Code à ajouter (probablement dans `services/tik_listener.py`, nouveau)

```python
"""tik_listener.py — écoute le stream WS Tik et déclenche kill_switch sur crash."""

import asyncio
from tik_sdk import TikClient, ApiKeyAuth, Signal, TikStream

from services.kill_switch_service import KillSwitchService


class TikListener:
    def __init__(
        self,
        config,
        kill_switch: KillSwitchService,
    ):
        self._config = config
        self._kill_switch = kill_switch
        self._client: TikClient | None = None
        self._stream: TikStream | None = None
        self._stream_task: asyncio.Task | None = None

    async def start(self):
        if not self._config.tik_listener_enabled:
            return

        self._client = TikClient(
            base_url=self._config.tik_base_url,
            auth=ApiKeyAuth(self._config.tik_api_key),
        )
        await self._client.__aenter__()

        self._stream = self._client.stream(
            entity=None,                     # tous les actifs
            horizon=None,                    # tous les horizons
            veracity_collapse_threshold=0.4, # plus strict que le défaut
        )
        self._stream.on_crash_warning(self._on_crash_warning)
        self._stream.on_veracity_collapse(self._on_veracity_collapse)
        # NB : on ne s'abonne PAS à on_signal — turbo_v2 fait des GET au moment voulu.
        # Le WS sert UNIQUEMENT aux alertes critiques.

        await self._stream.__aenter__()
        self._stream_task = asyncio.create_task(self._stream.run())

    async def stop(self):
        if self._stream_task:
            await self._stream.stop()
            await self._stream_task
        if self._stream:
            await self._stream.__aexit__(None, None, None)
        if self._client:
            await self._client.__aexit__(None, None, None)

    async def _on_crash_warning(self, signal: Signal):
        """Tik signale un risque de crash macro → on freeze Zeta."""
        await self._kill_switch.handle_alert(
            source="tik",
            severity="high",
            reason=(
                f"tik.macro_crash_warning sur {signal.entity_id} "
                f"(conf={signal.confidence:.2f}, verac={signal.veracity:.2f})"
                f": {signal.hypothesis or 'no hypothesis'}"
            ),
        )

    async def _on_veracity_collapse(self, signal: Signal):
        """Veracity en chute libre — alerte sans freeze (le bot peut décider)."""
        # Ici on log + envoie une notification, pas de kill_switch
        # (la veracity bas signifie « je ne suis plus fiable », pas « crash »).
        log.warning(
            "tik.veracity_collapse",
            entity=signal.entity_id,
            veracity=signal.veracity,
            id=signal.id,
        )
```

### Démarrage dans le main de Zeta

```python
# Quelque part dans le startup de Zeta
self._tik_listener = TikListener(self.config, self.kill_switch_service)
await self._tik_listener.start()

# Au shutdown
await self._tik_listener.stop()
```

## Pattern 3 — V16 optionnel dans `micro_live_guard.py`

**But** : ajouter un 16ᵉ check au pipeline existant. Si activé, il
bloque les nouveaux trades quand la veracity globale Tik est en
collapse (suspicion de désinformation massive ou sources compromises).

### Important — V16 s'**ajoute**, ne **remplace** rien

Les 15 checks existants sont préservés tels quels. V16 est une
couche supplémentaire optionnelle, désactivée par défaut.

### Code à ajouter dans `cranial_bot/micro_live_guard.py`

```python
# En haut du fichier
from tik_sdk import TikClient, TikError

# Nouvelle méthode dans la classe MicroLiveGuard
async def check_v16_tik_veracity(
    self,
    signal,
    tik_client: TikClient | None,
) -> tuple[bool, str]:
    """V16 (optionnel) — Bloque si veracity globale Tik en collapse.

    Activable via config `tik_v16_enabled: true`.
    S'AJOUTE aux V01-V15. Ne les remplace pas.

    Returns:
        (True, reason)  : check OK, trade autorisé sur ce critère.
        (False, reason) : check KO, trade bloqué.
    """
    if not self.config.tik_v16_enabled:
        return (True, "v16_disabled")

    if tik_client is None:
        return (True, "v16_skipped_no_client")

    try:
        veracity = await tik_client.get_global_veracity()
    except TikError:
        # Tik est down → fail-OPEN : on PASSE ce check (ADR-003)
        # Cohérent avec « si Tik est down, Zeta continue normalement ».
        return (True, "v16_skipped_tik_unavailable")

    if veracity.status == "collapse":
        return (
            False,
            f"v16_blocked_tik_collapse_{veracity.global_veracity:.3f}",
        )

    return (True, "v16_ok")
```

### Branchement dans la pipeline existante

Là où le guard appelle V01 → V15 :

```python
async def evaluate(self, signal):
    # Existant : V01 → V15
    for check_name, check_fn in self.checks_v01_v15:
        allowed, reason = await check_fn(signal)
        if not allowed:
            return GuardResult(allowed=False, reason=reason, blocked_by=check_name)

    # NOUVEAU : V16 optionnel
    allowed_v16, reason_v16 = await self.check_v16_tik_veracity(signal, self.tik_client)
    if not allowed_v16:
        return GuardResult(allowed=False, reason=reason_v16, blocked_by="V16_tik")

    return GuardResult(allowed=True, reason="all_checks_passed")
```

V16 bloque **uniquement** si Tik dit explicitement « collapse ». Si
Tik est down, V16 passe (fail-open). Le guard V01-V15 reste la
protection capital principale.

## Pattern 4 — Telemetry feedback après chaque trade

**But** : envoyer au core Tik le résultat de chaque trade pris sur un
signal Tik, pour qu'il recalibre ses engines. **Non bloquant** (ADR-003).

### Code à ajouter

Dans le code de Zeta qui ferme une position (après l'enregistrement en
DB, avant le retour) :

```python
async def _close_trade(self, trade):
    # ... fermeture existante : MT5 close, balance update, etc. ...
    self.balance_service.update_after_close(trade)

    # NOUVEAU : feedback à Tik (non-bloquant)
    if trade.tik_signal_id is not None:
        client = await self._get_tik_client()
        if client is not None:
            await client.report_outcome(
                signal_id=trade.tik_signal_id,
                outcome=self._classify_outcome(trade.pnl_pct),  # win/loss/breakeven
                trade_id=trade.id,
                pnl_points=trade.pnl_points,
                pnl_pct=trade.pnl_pct,
                duration_held_s=int(trade.duration_held.total_seconds()),
                exit_reason=trade.close_reason,  # "TP", "SL", "manual", etc.
            )
            # ↑ retour immédiat. Le HTTP part en background dans la queue feedback.

def _classify_outcome(self, pnl_pct: float) -> str:
    if abs(pnl_pct) < 0.05:
        return "breakeven"
    return "win" if pnl_pct > 0 else "loss"
```

`report_outcome` retourne immédiatement. Si Tik est down, la queue
retry en arrière-plan. Si la queue est pleine, le payload est dropé
avec log warning. **Aucun cas où le close du trade est ralenti**.

## Configuration recommandée pour démarrer en SHADOW

`tik.yaml` côté Zeta :

```yaml
core:
  base_url: http://localhost:8200    # core Tik en local sur le Mac
  timeout_s: 5.0

cache:
  enabled: true                       # réduit la pression sur le core
  maxsize: 500
  ttl_by_horizon:
    flash: 30                          # plus court qu'en prod (debug)
    swing: 120
    macro: 1800
    default: 120

circuit_breaker:
  enabled: true                       # protège Zeta si le core part en vrille
  failure_threshold: 3                # serré pour détecter vite
  reset_timeout_s: 15.0

stream:
  veracity_collapse_threshold: 0.4   # plus strict qu'en prod

feedback:
  enabled: true                       # collecte la telemetry dès le shadow
  max_queue_size: 1000
  max_retries: 3
```

Variables d'environnement Zeta :

```bash
# Active Tik
TIK_ENABLED=true                                    # active le client Tik dans turbo_v2
TIK_LISTENER_ENABLED=true                           # active TikListener (WS hooks)
TIK_V16_ENABLED=false                               # V16 désactivé en shadow
TIK_BASE_URL=http://localhost:8200
TIK_API_KEY=tik_xxxxxxxxxxxxx                       # généré via core/scripts/create_api_key.py
TIK_CONFIG_PATH=/path/to/tik.yaml
```

## Checklist de mise en service

- [ ] CLAUDE.md sections 4-5 et ADR-003 lus.
- [ ] Garde-fou 1 (mode shadow 3 mois) **explicitement validé** avant
      d'activer l'overlay confidence.
- [ ] Garde-fou 2 (budget test 5 %) **explicitement validé** avant le
      passage en mode actif.
- [ ] Clé API Tik générée via `core/scripts/create_api_key.py` avec les
      scopes `read:signals`, `read:entities`, `read:veracity`,
      `write:feedback`. **Pas** de scope `write:entities` (Zeta n'a pas
      à créer d'entité).
- [ ] `tik.yaml` copié depuis `sdk/tik.example.yaml` et adapté.
- [ ] Tests Zeta unitaires augmentés pour couvrir le cas « Tik down ».
- [ ] Logs `tik.overlay.*`, `tik.crash_warning.*`, `tik.feedback.*`
      monitorés (Grafana, Datadog, ou simple grep).
- [ ] V16 reste **désactivé** pendant les 3 premiers mois shadow. À
      activer seulement après revue des logs.

## Quoi faire si le test_client_does_not_expose_execution_methods plante

Si une PR future fait passer ce test du SDK en rouge, c'est qu'on a
ajouté par mégarde une méthode interdite (place_order, execute, trade,
etc.). **Ne jamais** retirer le test ou modifier la liste interdite
pour faire passer la PR. Renommer la méthode en quelque chose de neutre
(ex: `record_outcome` plutôt que `execute_trade`), ou abandonner la PR
si la méthode est vraiment un canal d'exécution.

## Références

- `docs/adr/003-zeta-integration.md` — règle absolue ADR-003
- `docs/adr/007-sdk-architecture.md` — architecture SDK
- `sdk/README.md` — API publique du SDK
- `sdk/examples/` — 4 exemples runnable
- `sdk/tik.example.yaml` — config YAML annotée

---

*Dernière mise à jour : 2026-04-30 (Session 5/5 du Paquet 2).*
