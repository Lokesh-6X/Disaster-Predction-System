"""Passwords, the start-up admin account, JWT tokens and login rate limiting (FR-AUTH-01..02)."""

import asyncio
import logging
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.app.models import User
from backend.app.settings import EnvSettings

log = logging.getLogger(__name__)

BCRYPT_ROUNDS = 12
BCRYPT_MAX_BYTES = 72
JWT_ALGORITHM = "HS256"
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW_S = 60


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


async def authenticate(
    session_factory: async_sessionmaker[AsyncSession], login: str, password: str
) -> User | None:
    """The user whose username or email is ``login``, if the password matches."""
    async with session_factory() as session:
        user = await session.scalar(
            select(User).where(or_(User.username == login, func.lower(User.email) == login.lower()))
        )
    if user is None:
        return None
    # bcrypt is deliberately slow; keep it off the event loop
    if not await asyncio.to_thread(verify_password, password, user.password_hash):
        return None
    return user


def create_access_token(username: str, env: EnvSettings) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires = now + timedelta(hours=env.jwt_expire_hours)
    token = jwt.encode(
        {"sub": username, "iat": now, "exp": expires},
        env.jwt_secret.get_secret_value(),
        algorithm=JWT_ALGORITHM,
    )
    return token, expires


def decode_token(token: str, env: EnvSettings) -> str | None:
    """Username from a valid, unexpired token; None otherwise."""
    try:
        payload = jwt.decode(
            token,
            env.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError:
        return None
    return payload["sub"]


class LoginRateLimiter:
    """At most MAX_FAILED_LOGINS failed attempts per client address per minute."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def _recent(self, client: str) -> deque[float]:
        failures = self._failures[client]
        cutoff = time.monotonic() - FAILED_LOGIN_WINDOW_S
        while failures and failures[0] < cutoff:
            failures.popleft()
        return failures

    def blocked(self, client: str) -> bool:
        return len(self._recent(client)) >= MAX_FAILED_LOGINS

    def record_failure(self, client: str) -> None:
        self._recent(client).append(time.monotonic())

    def reset(self, client: str) -> None:
        self._failures.pop(client, None)
