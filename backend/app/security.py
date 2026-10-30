"""Password hashing and the start-up admin account (FR-AUTH-01).

JWT handling is added in Phase 5.
"""

import logging

import bcrypt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models import User
from backend.app.settings import EnvSettings

log = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    data = password.encode("utf-8")
    if len(data) > BCRYPT_MAX_BYTES:
        raise ValueError(f"password is longer than {BCRYPT_MAX_BYTES} bytes")
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    data = password.encode("utf-8")
    if len(data) > BCRYPT_MAX_BYTES:
        return False
    return bcrypt.checkpw(data, password_hash.encode("ascii"))


async def ensure_admin(session_factory: async_sessionmaker[AsyncSession], env: EnvSettings) -> None:
    """Create the admin from .env if no user exists yet.

    Later changes to ADMIN_PASSWORD in .env do not overwrite the stored hash.
    """
    async with session_factory() as session, session.begin():
        if await session.scalar(select(func.count()).select_from(User)):
            return
        session.add(
            User(
                username=env.admin_username,
                email=env.admin_email,
                password_hash=hash_password(env.admin_password.get_secret_value()),
                role="admin",
            )
        )
    log.info("Created admin user '%s'", env.admin_username)
