"""
Authentication: password hashing, JWT creation/verification,
FastAPI dependency for current user, and role guards.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

import bcrypt
from fastapi import Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database import get_session
from models import User

__all__ = [
    "User",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_refresh_token",
    "set_refresh_cookie",
    "clear_refresh_cookie",
    "get_current_user",
    "require_admin",
    "ensure_bootstrap_admin",
]

# ── Password hashing ──────────────────────────────────────────


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT: access token ──────────────────────────────────────────

def create_access_token(data: dict) -> str:
    settings = get_settings()
    payload = data.copy()
    payload["type"] = "access"
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload["exp"] = expire
    return jwt.encode(
        payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


# ── JWT: refresh token ─────────────────────────────────────────

def create_refresh_token(username: str) -> str:
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.refresh_token_expire_days
    )
    payload = {"sub": username, "type": "refresh", "exp": expire}
    return jwt.encode(
        payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


def decode_refresh_token(token: str) -> str:
    """Validates a refresh token and returns the username it was issued for.

    Raises HTTPException(401) if the token is missing, expired, malformed,
    or not actually a refresh token (e.g. someone passing an access token).
    """
    settings = get_settings()
    invalid_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired refresh token",
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except JWTError:
        raise invalid_exc

    if payload.get("type") != "refresh":
        raise invalid_exc
    username = payload.get("sub")
    if not username:
        raise invalid_exc
    return username


# ── Refresh cookie helpers ──────────────────────────────────────

def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/api/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


# ── OAuth2 bearer scheme ──────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    settings = get_settings()
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
        # Reject refresh tokens presented as access tokens (e.g. if a
        # client mistakenly sends the refresh token as a Bearer header).
        if payload.get("type") not in (None, "access"):
            raise credentials_exc
        username: str | None = payload.get("sub")
        if not username:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user = await session.get(User, username)
    if not user:
        raise credentials_exc
    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ── Bootstrap ─────────────────────────────────────────────────

async def ensure_bootstrap_admin(session: AsyncSession) -> None:
    """
    Creates the default admin from .env on first startup if missing.
    """
    settings = get_settings()
    username = settings.admin_username.lower()

    existing = await session.get(User, username)
    if existing:
        return  # already exists

    admin = User(
        username=username,
        display_name=settings.admin_username,
        role="admin",
        hashed_password=hash_password(settings.admin_password),
    )
    session.add(admin)
    await session.commit()
