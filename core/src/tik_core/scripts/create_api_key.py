"""CLI — génération d'une API key pour un bot client.

Usage :
    python -m tik_core.scripts.create_api_key --client zeta --name "Zeta Prod"
    python -m tik_core.scripts.create_api_key --client totem --scopes read:signals,read:veracity,write:feedback

La clé en clair est affichée UNE SEULE FOIS. À stocker immédiatement côté client.
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from tik_core.auth.api_key import generate_key
from tik_core.config import get_settings
from tik_core.storage.models import ApiKey
from tik_core.utils.time import now_utc_naive

DEFAULT_SCOPES = [
    "read:signals",
    "read:veracity",
    "read:entities",
    "write:feedback",
]


async def _create(client_id: str, name: str | None, scopes: list[str]) -> None:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    raw_key, key_hash, key_suffix = generate_key()

    async with session_maker() as session:
        existing = await session.execute(
            select(ApiKey).where(ApiKey.client_id == client_id)
        )
        if existing.scalar_one_or_none() is not None:
            print(f"❌ Client '{client_id}' existe déjà. Utilisez un autre nom ou désactivez l'ancienne clé.")
            await engine.dispose()
            return

        key = ApiKey(
            name=name or f"{client_id}-key",
            client_id=client_id,
            key_hash=key_hash,
            key_suffix=key_suffix,
            scopes=scopes,
            active=True,
            created_at=now_utc_naive(),
        )
        session.add(key)
        await session.commit()

    await engine.dispose()

    print("=" * 60)
    print("✅ API key créée avec succès")
    print("=" * 60)
    print(f"Client ID : {client_id}")
    print(f"Nom       : {name or client_id}")
    print(f"Scopes    : {', '.join(scopes)}")
    print(f"Suffix    : ...{key_suffix}")
    print()
    print("🔑 CLÉ (à copier MAINTENANT, elle ne sera plus jamais affichée) :")
    print()
    print(f"    {raw_key}")
    print()
    print("Usage côté client :")
    print('    curl -H "Authorization: Bearer <key>" http://localhost:8200/api/v1/signals/latest')
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a Tik API key")
    parser.add_argument("--client", "--bot", dest="client", required=True, help="Client ID (ex: zeta, totem)")
    parser.add_argument("--name", help="Nom affiché")
    parser.add_argument(
        "--scopes",
        help=f"Scopes CSV (defaut: {','.join(DEFAULT_SCOPES)})",
        default=",".join(DEFAULT_SCOPES),
    )
    args = parser.parse_args()
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    asyncio.run(_create(args.client, args.name, scopes))


if __name__ == "__main__":
    main()
