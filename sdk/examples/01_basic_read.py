"""Exemple 1 — Lecture HTTP basique.

Connecte le client, ping le health, liste les entités, lit les derniers
signaux BTC et GOLD. Le « hello world » du SDK.

Lancement :
    export TIK_API_KEY=tik_xxxxxxxxxxxx
    python sdk/examples/01_basic_read.py
"""

import asyncio
import os

from tik_sdk import ApiKeyAuth, TikClient, TikError


async def main() -> None:
    base_url = os.environ.get("TIK_BASE_URL", "http://localhost:8200")
    api_key = os.environ.get("TIK_API_KEY")
    if not api_key:
        raise SystemExit("TIK_API_KEY env var is required")

    async with TikClient(base_url, ApiKeyAuth(api_key)) as client:
        # 1. Health check (pas d'auth requise)
        try:
            health = await client.get_health()
            print(f"✓ core OK — version {health.version}, env {health.env}")
        except TikError as exc:
            print(f"✗ core unreachable: {exc}")
            return

        # 2. Lister les entités observées par Tik
        entities = await client.list_entities()
        print(f"\n{len(entities)} entités actives :")
        for e in entities:
            print(f"  - {e.id} ({e.domain}/{e.namespace})")

        # 3. Derniers signaux par entité × horizon
        for entity_id in ("BTC", "GOLD"):
            for horizon in ("flash", "swing"):
                if entity_id == "GOLD" and horizon == "flash":
                    continue  # pas de flash sur GOLD (cf. ADR-005)
                signals = await client.get_latest_signals(
                    entity=entity_id,
                    horizon=horizon,
                    limit=3,
                )
                print(f"\nDerniers signaux {entity_id}/{horizon} ({len(signals)}) :")
                for s in signals:
                    print(
                        f"  {s.timestamp.isoformat()[:19]} "
                        f"{s.direction:>7} "
                        f"conf={s.confidence:.2f} "
                        f"verac={s.veracity:.2f} "
                        f"id={s.id}"
                    )

        # 4. État global de la véracité
        v = await client.get_global_veracity()
        print(
            f"\n✓ Veracity globale : {v.global_veracity:.3f} "
            f"({v.status}, {v.sources_count_active} sources actives)"
        )


if __name__ == "__main__":
    asyncio.run(main())
