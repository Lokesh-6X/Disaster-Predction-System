"""Database engine and sessions (PostgreSQL via asyncpg)."""

import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url: str, **engine_options) -> None:
        self.engine: AsyncEngine = create_async_engine(url, pool_pre_ping=True, **engine_options)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self, timeout_s: float = 2.0) -> bool:
        """True if the database answers within the timeout."""
        try:
            async with asyncio.timeout(timeout_s):
                async with self.engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def dispose(self) -> None:
        await self.engine.dispose()
