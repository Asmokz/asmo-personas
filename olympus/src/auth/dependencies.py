"""Auth FastAPI dependencies — get_current_user, require_admin."""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Validate Bearer token and return the decoded user payload.

    Raises 401 if missing or invalid.
    """
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise exc

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise exc

    return {
        "id": int(payload["sub"]),
        "username": payload.get("username", ""),
        "is_admin": bool(payload.get("is_admin", False)),
    }


async def require_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """Require the current user to be an admin."""
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


def get_current_user_from_token(token: str) -> dict | None:
    """Validate a raw token string (used for WebSocket auth)."""
    payload = decode_access_token(token)
    if payload is None:
        return None
    return {
        "id": int(payload["sub"]),
        "username": payload.get("username", ""),
        "is_admin": bool(payload.get("is_admin", False)),
    }
