"""Login (FR-AUTH-01..02). One admin account in v1; username or email accepted."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from backend.app.api.deps import require_admin
from backend.app.security import authenticate, create_access_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200, description="Username or email")
    password: str = Field(min_length=1, max_length=200)


@router.post("/login")
async def login(body: LoginRequest, request: Request) -> dict:
    limiter = request.app.state.login_limiter
    client = request.client.host if request.client else "unknown"
    if limiter.blocked(client):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, "Too many failed attempts — wait a minute"
        )
    user = await authenticate(
        request.app.state.database.session_factory, body.username.strip(), body.password
    )
    if user is None:
        limiter.record_failure(client)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    limiter.reset(client)
    token, expires = create_access_token(user.username, request.app.state.config.env)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_at": expires,
        "user": {"username": user.username, "email": user.email, "role": user.role},
    }


@router.get("/me")
async def me(username: str = Depends(require_admin)) -> dict:
    return {"username": username}
