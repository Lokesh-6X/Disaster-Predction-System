"""Shared API helpers: admin authentication, time ranges and serialisation."""

from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.app.security import decode_token

bearer = HTTPBearer(auto_error=False)


async def require_admin(
    request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)
) -> str:
    """The logged-in admin's username; 401 without a valid token (FR-AUTH-02)."""
    username = None
    if credentials is not None:
        username = decode_token(credentials.credentials, request.app.state.config.env)
    if username is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Not logged in or session expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return username


def utc(value: datetime) -> datetime:
    """Query-string datetimes without a zone are taken as UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def time_range(
    start: datetime | None, end: datetime | None, default: timedelta, maximum: timedelta
) -> tuple[datetime, datetime]:
    end = utc(end) if end else datetime.now(UTC)
    start = utc(start) if start else end - default
    if start >= end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "'from' must be before 'to'")
    if end - start > maximum:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"range is longer than {maximum.days} days"
        )
    return start, end


def check_kit(request: Request, kit_id: str) -> None:
    if request.app.state.config.site.kit(kit_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"unknown kit '{kit_id}'")


def rounded(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(float(value), digits)
