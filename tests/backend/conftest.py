"""Database fixture: each test gets its own temporary schema in the local database.

Tests that use it are skipped when .env or PostgreSQL is not available.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.models import Base
from backend.app.settings import ConfigError, load_env_settings


class FakeHub:
    """Collects broadcast messages instead of sending them."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, dict]] = []

    async def broadcast(self, message_type: str, data: dict) -> None:
        self.messages.append((message_type, data))

    def of_type(self, message_type: str) -> list[dict]:
        return [data for kind, data in self.messages if kind == message_type]


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest_asyncio.fixture
async def session_factory():
    try:
        url = load_env_settings().database_url
    except ConfigError:
        pytest.skip(".env is not configured")

    schema = f"test_{uuid.uuid4().hex[:10]}"
    admin = create_async_engine(url)
    try:
        async with admin.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as exc:
        await admin.dispose()
        pytest.skip(f"database not available: {exc}")

    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin.dispose()
