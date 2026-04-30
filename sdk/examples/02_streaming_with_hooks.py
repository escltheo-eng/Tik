"""Exemple 2 — WebSocket + 4 hooks événementiels.

Se connecte au WS du core, dispatch chaque message reçu vers les bons
hooks. Reconnexion automatique transparente. Sortie propre sur Ctrl+C.

Lancement :
    export TIK_API_KEY=tik_xxxxxxxxxxxx
    python sdk/examples/02_streaming_with_hooks.py

Pour quitter : Ctrl+C.
"""

import asyncio
import os
import signal

from tik_sdk import ApiKeyAuth, Signal, TikClient


async def on_signal(s: Signal) -> None:
    """Tout signal reçu (le hook le plus chargé)."""
    print(
        f"[SIGNAL] {s.entity_id:>4}/{s.horizon:<5} "
        f"{s.direction:>7} "
        f"conf={s.confidence:.2f} "
        f"verac={s.veracity:.2f} "
        f"id={s.id}"
    )
    if s.hypothesis:
        print(f"         hyp: {s.hypothesis[:80]}")


async def on_crash_warning(s: Signal) -> None:
    """Tik signale un risque de crash macro.

    En production côté Zeta, ici on appellerait
    `kill_switch_service.handle_alert(...)` (cf. docs/integration_zeta.md
    Pattern 2). Voie la SEULE autorisée par ADR-003 pour Tik d'arrêter Zeta.
    """
    print(f"\n⚠️  [CRASH WARNING] {s.entity_id} — {s.hypothesis}")
    print("   (en prod : déclenchement kill_switch_service ici)")


async def on_fake_news_detected(s: Signal) -> None:
    """Le core a tripé son circuit breaker anti-fake-news."""
    print(
        f"\n🛑 [FAKE NEWS] core circuit breaker tripped sur {s.entity_id} "
        f"(status={s.circuit_breaker_status})"
    )


async def on_veracity_collapse(s: Signal) -> None:
    """La veracity du signal est sous le seuil — sources peu fiables."""
    print(
        f"\n📉 [VERACITY COLLAPSE] {s.entity_id}/{s.horizon} "
        f"verac={s.veracity:.3f} (< seuil)"
    )


async def main() -> None:
    base_url = os.environ.get("TIK_BASE_URL", "http://localhost:8200")
    api_key = os.environ.get("TIK_API_KEY")
    if not api_key:
        raise SystemExit("TIK_API_KEY env var is required")

    async with TikClient(base_url, ApiKeyAuth(api_key)) as client:
        # Stream sans filtre — tout BTC + GOLD, tous horizons.
        # Production : filtrer par entity/horizon pour réduire le bruit.
        stream = client.stream(
            entity=None,
            horizon=None,
            veracity_collapse_threshold=0.5,
        )
        stream.on_signal(on_signal)
        stream.on_crash_warning(on_crash_warning)
        stream.on_fake_news_detected(on_fake_news_detected)
        stream.on_veracity_collapse(on_veracity_collapse)

        # Câblage Ctrl+C → stream.stop()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(stream.stop()))

        async with stream:
            print("Listening on WS... (Ctrl+C pour quitter)")
            await stream.run()
            print("\nStream stopped.")


if __name__ == "__main__":
    asyncio.run(main())
