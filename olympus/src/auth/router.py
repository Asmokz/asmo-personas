"""Auth router — /auth/* endpoints."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from .db import AuthDB
from .dependencies import get_current_user, require_admin
from .schemas import (
    ChangePasswordRequest,
    InviteResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from .security import (
    COOKIE_SECURE,
    REFRESH_TOKEN_EXPIRE_DAYS,
    create_access_token,
    generate_refresh_token,
    hash_password,
    refresh_token_expires_at,
    verify_password,
)

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"
_COOKIE_PATH = "/auth/refresh"


def _get_auth_db(request: Request) -> AuthDB:
    return request.app.state.auth_db


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
        path=_COOKIE_PATH,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=_COOKIE_NAME,
        path=_COOKIE_PATH,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="strict",
    )


# ---------------------------------------------------------------------------
# Rate limiting helpers (slowapi)
# ---------------------------------------------------------------------------

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address
    _limiter: Limiter | None = Limiter(key_func=get_remote_address)
except ImportError:
    _limiter = None


def _rate_limit(limit: str):
    """Decorator that applies slowapi rate limit if available, no-op otherwise."""
    def decorator(func):
        if _limiter is not None:
            return _limiter.limit(limit)(func)
        return func
    return decorator


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/invite", response_model=InviteResponse)
async def create_invite(
    request: Request,
    _admin: dict = Depends(require_admin),
):
    """Admin only — generate a 24h invite token."""
    auth_db: AuthDB = _get_auth_db(request)
    raw_token = str(uuid.uuid4())
    expires_at = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    await auth_db.create_invite_token(raw_token, _admin["id"], expires_at)
    logger.info("invite_created", by=_admin["username"])
    return InviteResponse(token=raw_token, expires_at=expires_at.isoformat())


@router.post("/register", response_model=TokenResponse)
@_rate_limit("5/minute")
async def register(
    request: Request,
    response: Response,
    body: RegisterRequest,
    token: str = "",
):
    """Register a new account — requires a valid invite token."""
    if not token:
        # Try query param
        token = request.query_params.get("token", "")
    if not token:
        raise HTTPException(status_code=400, detail="Invite token required")

    auth_db: AuthDB = _get_auth_db(request)

    invite = await auth_db.get_invite_token(token)
    if invite is None:
        raise HTTPException(status_code=400, detail="Invalid or expired invite token")

    expires_at = datetime.fromisoformat(invite["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invite token has expired")

    if await auth_db.get_user_by_email(body.email):
        raise HTTPException(status_code=400, detail="Email already registered")
    if await auth_db.get_user_by_username(body.username):
        raise HTTPException(status_code=400, detail="Username already taken")

    hashed = hash_password(body.password)
    user_id = await auth_db.create_user(body.username, body.email, hashed)
    await auth_db.consume_invite_token(token, user_id)

    logger.info("user_registered", username=body.username)

    access_token = create_access_token(user_id, body.username, is_admin=False)
    raw_refresh = generate_refresh_token()
    expires = refresh_token_expires_at()
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await auth_db.store_refresh_token(user_id, raw_refresh, expires, ip, ua)
    _set_refresh_cookie(response, raw_refresh)

    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
@_rate_limit("5/minute")
async def login(
    request: Request,
    response: Response,
    body: LoginRequest,
):
    """Authenticate and return access + refresh tokens."""
    auth_db: AuthDB = _get_auth_db(request)
    user = await auth_db.get_user_by_username(body.username)

    if user is None or not verify_password(body.password, user["hashed_password"]):
        logger.warning("login_failed", username=body.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user["is_active"]:
        raise HTTPException(status_code=403, detail="Account disabled")

    await auth_db.update_last_login(user["id"])

    access_token = create_access_token(user["id"], user["username"], bool(user["is_admin"]))
    raw_refresh = generate_refresh_token()
    expires = refresh_token_expires_at()
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await auth_db.store_refresh_token(user["id"], raw_refresh, expires, ip, ua)
    _set_refresh_cookie(response, raw_refresh)

    logger.info("login_success", username=user["username"])
    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: Request, response: Response):
    """Rotate refresh token and return a new access token.

    Reads the refresh_token httpOnly cookie.
    """
    raw_token = request.cookies.get(_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    auth_db: AuthDB = _get_auth_db(request)
    record = await auth_db.get_refresh_token(raw_token)
    if record is None:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Invalid or revoked refresh token")

    expires_at = datetime.fromisoformat(record["expires_at"])
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        await auth_db.revoke_refresh_token(raw_token)
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = await auth_db.get_user_by_id(record["user_id"])
    if user is None or not user["is_active"]:
        _clear_refresh_cookie(response)
        raise HTTPException(status_code=401, detail="User not found or disabled")

    # Rotation: revoke old, issue new
    await auth_db.revoke_refresh_token(raw_token)
    new_raw = generate_refresh_token()
    new_expires = refresh_token_expires_at()
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    await auth_db.store_refresh_token(user["id"], new_raw, new_expires, ip, ua)
    _set_refresh_cookie(response, new_raw)

    access_token = create_access_token(user["id"], user["username"], bool(user["is_admin"]))
    return TokenResponse(access_token=access_token)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
):
    """Revoke refresh token and clear the cookie."""
    raw_token = request.cookies.get(_COOKIE_NAME)
    if raw_token:
        auth_db: AuthDB = _get_auth_db(request)
        await auth_db.revoke_refresh_token(raw_token)
    _clear_refresh_cookie(response)
    return {"detail": "Logged out"}


@router.post("/change-password", status_code=204)
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: dict = Depends(get_current_user),
):
    """Change the authenticated user's password."""
    auth_db: AuthDB = _get_auth_db(request)
    db_user = await auth_db.get_user_by_id(user["id"])
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(body.current_password, db_user["hashed_password"]):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    hashed = hash_password(body.new_password)
    await auth_db.update_password(user["id"], hashed)
    logger.info("password_changed", user_id=user["id"])


@router.get("/me", response_model=UserResponse)
async def me(
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Return the currently authenticated user."""
    auth_db: AuthDB = _get_auth_db(request)
    db_user = await auth_db.get_user_by_id(user["id"])
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=db_user["id"],
        username=db_user["username"],
        email=db_user["email"],
        is_active=bool(db_user["is_active"]),
        is_admin=bool(db_user["is_admin"]),
        created_at=db_user.get("created_at"),
        last_login=db_user.get("last_login"),
    )
