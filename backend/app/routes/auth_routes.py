"""
Authentication routes: login, refresh, logout, current user info, user management.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth import (
    clear_refresh_cookie,
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    get_current_user,
    hash_password,
    require_admin,
    set_refresh_cookie,
    verify_password,
)
from app.config import get_settings
from app.database import get_session
from app.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=40)
    display_name: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=6)
    role: str = Field("annotator", pattern="^(admin|annotator)$")


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
):
    username = form_data.username.lower()
    user = await session.get(User, username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token({"sub": user.username, "role": user.role})
    refresh_token = create_refresh_token(user.username)
    set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"username": user.username, "display_name": user.display_name, "role": user.role},
    }


@router.post("/refresh", response_model=Token)
async def refresh(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    settings = get_settings()
    raw_token = request.cookies.get(settings.refresh_cookie_name)
    if raw_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    username = decode_refresh_token(raw_token)
    user = await session.get(User, username)
    if not user:
        clear_refresh_cookie(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists")

    access_token = create_access_token({"sub": user.username, "role": user.role})
    # Re-issue the refresh cookie too, so an active user's session keeps
    # sliding forward instead of hard-expiring after exactly 7 days from
    # the original login.
    new_refresh_token = create_refresh_token(user.username)
    set_refresh_cookie(response, new_refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"username": user.username, "display_name": user.display_name, "role": user.role},
    }


@router.post("/logout")
async def logout(response: Response):
    clear_refresh_cookie(response)
    return {"status": "ok"}


@router.get("/me")
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return {
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": current_user.role,
    }


@router.get("/users")
async def list_users(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """All users visible to any authenticated user (for autocomplete in project config)."""
    result = await session.exec(select(User).order_by(User.username))
    return [
        {"username": u.username, "display_name": u.display_name, "role": u.role}
        for u in result.all()
    ]


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    username = body.username.lower()
    if await session.get(User, username):
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        username=username,
        display_name=body.display_name,
        role=body.role,
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    username = username.lower()
    if username == admin.username:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    user = await session.get(User, username)
    if user:
        await session.delete(user)
        await session.commit()
    return {"status": "deleted"}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(body.new_password)
    session.add(current_user)
    await session.commit()
    return {"status": "ok"}
