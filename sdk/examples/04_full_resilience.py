"""Exemple 4 — Bot complet avec config YAML + cache + breaker + telemetry.

Combine TOUTES les fonctionnalités du SDK :
- Config YAML hot-reloadable
- Cache local + circuit breaker (configurés depuis le YAML)
- Stream WebSocket avec hooks
- Telemetry feedback non-bloquante (POST /feedback)
- Sortie propre sur Ctrl+C

Lancement :
    export TIK_API_KEY=tik_xxxxxxxxxxxx
    python sdk/examples/04_full_resilience.py sdk/tik.example.yaml

Modifie `sdk/tik.example.yaml` pendant que ça tourne pour voir le
hot-reload (toutes les 5 s, le watcher détecte mtime change et applique
les settings mutables).
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

from tik_sdk import (
    ApiKeyAuth,
    ConfigWatcher,
    Signal,
    TikClient,
    TikConfig,
    diff_mutable_settings,
    warn_immutable_changes,
)


async def on_signal(s: Signal) -> None:
    print(f"[WS] {s.entity_id}/{s.horizon} {s.direction} verac={s.veracity:.2f}")


async def on_collapse(s: Signal) -> None:
    print(f"⚠️ veracity collapse {s.entity_id} verac={s.veracity:.3f}")


async def main(config_path: str) -> None:
    api_key = os.environ.get("TIK_API_KEY")
    if not api_key:
        raise SystemExit("TIK_API_KEY env var is required")

    # Charge la config initiale
    config = TikConfig.load_from_yaml(config_path)
    print(f"Config chargée depuis {config_path}")
    print(f"  cache.enabled={config.cache.enabled}")
    print(f"  circuit_breaker.enabled={config.circuit_breaker.enabled}")
    print(f"  feedback.enabled={config.feedback.enabled}")

    # Crée le client
    client = TikClient.from_config(config, auth=ApiKeyAuth(api_key))

    # Stream
    stream = client.stream(
        veracity_collapse_threshold=config.stream.veracity_collapse_threshold,
    )
    stream.on_signal(on_signal)
    stream.on_veracity_collapse(on_collapse)

    # Watcher hot-reload : applique cache.ttl_by_horizon + stream threshold
    watcher = ConfigWatcher(config_path, poll_interval_s=5.0)

    def _on_reload(old: TikConfig, new: TikConfig) -> None:
        print(f"\n♻️  Config rechargée — diff mutable: {diff_mutable_settings(old, new)}")
        warns = warn_immutable_changes(old, new)
        if warns:
            print(f"   (changements non mutables ignorés : {warns} — restart requis)")
        client.apply_mutable_config(new)
        # Le seuil veracity_collapse du stream se règle aussi à chaud :
        stream._veracity_collapse_threshold = new.stream.veracity_collapse_threshold

    watcher.on_reload(_on_reload)

    # Câblage Ctrl+C
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # Démarrage
    async with client:
        async with stream, watcher:
            print("\nBot prêt. Ctrl+C pour quitter, modifie le YAML pour tester le reload.\n")

            stream_task = asyncio.create_task(stream.run())

            # Démo telemetry — envoie 1 feedback toutes les 30 s
            # (en réalité, c'est Zeta qui appelle ça après chaque close de trade)
            async def _telemetry_demo() -> None:
                count = 0
                while not stop_event.is_set():
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=30.0)
                        return
                    except asyncio.TimeoutError:
                        pass
                    count += 1
                    ok = await client.report_outcome(
                        signal_id=f"DEMO-{count}",
                        outcome="win" if count % 2 else "loss",
                        pnl_pct=0.5 if count % 2 else -0.3,
                    )
                    print(f"[FEEDBACK] enqueue #{count} ok={ok}")

            telemetry_task = asyncio.create_task(_telemetry_demo())

            await stop_event.wait()
            print("\nArrêt en cours...")
            await stream.stop()
            await asyncio.gather(stream_task, telemetry_task, return_exceptions=True)

    queue = client.feedback_queue
    if queue:
        print(
            f"Queue feedback : {queue.sent_count} envoyés, "
            f"{queue.dropped_count} dropés, "
            f"{queue.failed_count} en échec."
        )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python 04_full_resilience.py <chemin_vers_tik.yaml>")
    asyncio.run(main(sys.argv[1]))
