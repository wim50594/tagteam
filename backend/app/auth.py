"""
Authentication: password hashing, JWT creation/verification,
FastAPI dependency for current user, and role guards.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel

import database as db
from config import get_settings

# ── Password hashing ──────────────────────────────────────────


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── JWT ───────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    settings = get_settings()
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    payload["exp"] = expire
    return jwt.encode(
        payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )


# ── User models ───────────────────────────────────────────────

class UserInDB(BaseModel):
    username: str
    display_name: str
    role: str          # "admin" | "annotator"
    hashed_password: str
    created_at: str


class TokenData(BaseModel):
    username: str
    role: str


# ── OAuth2 bearer scheme ──────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
) -> UserInDB:
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
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if not username or not role:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    user_data = await db.get_json(db.key_user(username))
    if not user_data:
        raise credentials_exc
    return UserInDB(**user_data)


async def require_admin(
    current_user: Annotated[UserInDB, Depends(get_current_user)],
) -> UserInDB:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


# ── Bootstrap ─────────────────────────────────────────────────

async def ensure_bootstrap_admin() -> None:
    """
    Creates the default admin from .env on first startup if missing.
    """
    settings = get_settings()
    from datetime import datetime, timezone

    key = db.key_user(settings.admin_username)
    if await db.get_json(key):
        return  # already exists

    admin = UserInDB(
        username=settings.admin_username.lower(),
        display_name=settings.admin_username,
        role="admin",
        hashed_password=hash_password(settings.admin_password),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await db.set_json(key, admin.model_dump())
    await db.sadd(db.SET_USERS, admin.username)
