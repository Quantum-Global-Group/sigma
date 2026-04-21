#!/usr/bin/env python
"""
Seed the dev database with a test user and API key.
Run from apps/api/ after migrations have been applied:
    python scripts/seed_db.py
"""

import asyncio
import hashlib
import os
import secrets
import sys

# Resolve imports relative to apps/api
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy import select

from config import settings
from db.models import APIKey, User


async def seed():
    engine = create_async_engine(settings.database_url, echo=False)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        # Check if test user already exists
        result = await session.execute(select(User).where(User.email == "dev@sigma.local"))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                clerk_id="dev_clerk_id",
                email="dev@sigma.local",
                plan="pro",
            )
            session.add(user)
            await session.flush()

        # Generate a fresh test key each run
        raw_key = f"sk_test_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:12]

        api_key = APIKey(
            user_id=user.id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name="dev-seed-key",
        )
        session.add(api_key)
        await session.commit()

    print("─" * 60)
    print("Dev seed complete!")
    print(f"  Email:   dev@sigma.local")
    print(f"  Plan:    pro")
    print(f"  API Key: {raw_key}")
    print()
    print("Test signal call:")
    print(f'  curl -X POST http://localhost:8000/signals \\')
    print(f'    -H "Authorization: Bearer {raw_key}" \\')
    print(f'    -H "Content-Type: application/json" \\')
    print(f'    -d \'{{"ticker": "AAPL", "timeframe": "daily"}}\'')
    print("─" * 60)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
