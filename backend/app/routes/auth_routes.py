"""
Authentication routes: login, current user info.
"""
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field

import database as db
from auth import (
    UserInDB,
    create_access_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)

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
async def login(form_data: Annotated[OAuth2PasswordRequestForm, Depends()]):
    user_data = await db.get_json(db.key_user(form_data.username.lower()))
    if not user_data:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    user = UserInDB(**user_data)
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token({"sub": user.username, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {"username": user.username, "display_name": user.display_name, "role": user.role},
    }


@router.get("/me")
async def me(current_user: Annotated[UserInDB, Depends(get_current_user)]):
    return {
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": current_user.role,
    }


@router.get("/users")
async def list_users(current_user: Annotated[UserInDB, Depends(get_current_user)]):
    """All users visible to any authenticated user (for autocomplete in project config)."""
    usernames = await db.smembers(db.SET_USERS)
    users = []
    for uname in usernames:
        data = await db.get_json(db.key_user(uname))
        if data:
            users.append({
                "username": data["username"],
                "display_name": data["display_name"],
                "role": data["role"],
            })
    users.sort(key=lambda u: u["username"])
    return users


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    _admin: Annotated[UserInDB, Depends(require_admin)],
):
    key = db.key_user(body.username.lower())
    if await db.get_json(key):
        raise HTTPException(status_code=409, detail="Username already taken")

    user = UserInDB(
        username=body.username.lower(),
        display_name=body.display_name,
        role=body.role,
        hashed_password=hash_password(body.password),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    await db.set_json(key, user.model_dump())
    await db.sadd(db.SET_USERS, user.username)
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    admin: Annotated[UserInDB, Depends(require_admin)],
):
    if username.lower() == admin.username:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    await db.delete_key(db.key_user(username.lower()))
    await db.srem(db.SET_USERS, username.lower())
    return {"status": "deleted"}


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    updated = current_user.model_dump()
    updated["hashed_password"] = hash_password(body.new_password)
    await db.set_json(db.key_user(current_user.username), updated)
    return {"status": "ok"}
