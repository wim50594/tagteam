"""
Authentication routes: login, refresh, logout, registration via invitation,
current user info, user listing, profile management, and invitation creation.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlmodel.ext.asyncio.session import AsyncSession
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
    promote_first_user,
)
from app.config import get_settings
from app.database import get_session
from app.models import User, Invitation, ProjectMember, Project
from app.services.iam import IAMService

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Schemas ───────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict


class RegisterRequest(BaseModel):
    token: str = Field(..., description="Invitation token")
    username: str = Field(..., min_length=2, max_length=40)
    display_name: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=6)


class BootstrapRegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=40)
    display_name: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=6)


class CreateInviteRequest(BaseModel):
    project_id: int
    role: str = Field("user", pattern="^(maintainer|annotator)$")  # project-level role
    expires_in_days: int | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=80)
    username: str | None = Field(None, min_length=2, max_length=40)
    password: str | None = Field(None, min_length=6)


class LanguageRequest(BaseModel):
    language: str = Field(..., pattern="^[a-z]{2}$")


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=40)
    display_name: str = Field(..., min_length=1, max_length=80)
    password: str = Field(..., min_length=6)
    role: str = Field("user", pattern="^(admin|user)$")


# ── Login / Refresh / Logout ──────────────────────────────────

@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
):
    username = form_data.username.lower()
    result = await session.exec(select(User).where(User.username == username))
    user = result.first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    access_token = create_access_token(
        {"sub": user.username, "uid": user.id, "role": "admin" if user.is_admin else "user"}
    )
    refresh_token = create_refresh_token(user.id, user.username)
    set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "username": user.username,
            "display_name": user.display_name,
            "role": "admin" if user.is_admin else "user",
            "language": user.language,
        },
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token"
        )

    payload = decode_refresh_token(raw_token)
    user = await session.get(User, payload["uid"])
    if not user:
        clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )

    access_token = create_access_token(
        {"sub": user.username, "uid": user.id, "role": "admin" if user.is_admin else "user"}
    )
    new_refresh_token = create_refresh_token(user.id, user.username)
    set_refresh_cookie(response, new_refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "username": user.username,
            "display_name": user.display_name,
            "role": "admin" if user.is_admin else "user",
            "language": user.language,
        },
    }


@router.post("/logout")
async def logout(response: Response):
    clear_refresh_cookie(response)
    return {"status": "ok"}


# ── Registration via invitation ───────────────────────────────

@router.post("/register", status_code=201, response_model=Token)
async def register(
    body: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
):
    """Register a new user using an invitation token."""
    try:
        user = await IAMService.register_with_invitation(
            db=session,
            token=body.token,
            username=body.username,
            display_name=body.display_name,
            password=body.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    access_token = create_access_token(
        {"sub": user.username, "uid": user.id, "role": "admin" if user.is_admin else "user"}
    )
    refresh_token = create_refresh_token(user.id, user.username)
    set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "username": user.username,
            "display_name": user.display_name,
            "role": "admin" if user.is_admin else "user",
            "language": user.language,
        },
    }


@router.post("/bootstrap-register", status_code=201)
async def bootstrap_register(
    body: BootstrapRegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
):
    """First-user registration without invitation (when no users exist)."""
    result = await session.exec(select(User).limit(1))
    if result.first():
        raise HTTPException(status_code=400, detail="Setup already complete.")

    username = body.username.lower()
    existing = await session.exec(select(User).where(User.username == username))
    if existing.first():
        raise HTTPException(status_code=400, detail="Username already taken")

    user = User(
        username=username,
        display_name=body.display_name,
        is_admin=True,
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    access_token = create_access_token(
        {"sub": user.username, "uid": user.id, "role": "admin"}
    )
    refresh_token = create_refresh_token(user.id, user.username)
    set_refresh_cookie(response, refresh_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"username": user.username, "display_name": user.display_name, "role": "admin", "language": user.language},
    }


# ── Invitation management ─────────────────────────────────────

@router.post("/invitations", status_code=201)
async def create_invitation(
    body: CreateInviteRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Create an invitation token for a project and role.

    Only admins, the project owner, and maintainers can create invitations.
    """
    project = await db.get(Project, body.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    can_manage = await IAMService.can_manage_project(db, body.project_id, current_user)
    if not can_manage:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins, project owners, and maintainers can invite users",
        )

    invitation = await IAMService.create_invitation(
        db=db,
        project_id=body.project_id,
        role=body.role,
        created_by=current_user.id,
        expires_in_days=body.expires_in_days,
    )

    return {
        "token": invitation.token,
        "project_id": invitation.project_id,
        "role": invitation.role,
        "expires_at": invitation.expires_at.isoformat() if invitation.expires_at else None,
    }


@router.get("/invitations/{token}")
async def validate_invitation(
    token: str,
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Look up an invitation token (public endpoint – used by registration page)."""
    try:
        invitation = await IAMService.validate_invitation(db, token)
        project = await db.get(Project, invitation.project_id)
        return {
            "valid": True,
            "project_name": project.name if project else "Unknown",
            "role": invitation.role,
        }
    except ValueError as e:
        return {"valid": False, "detail": str(e)}


# ── Current user / profile ────────────────────────────────────

@router.get("/me")
async def me(current_user: Annotated[User, Depends(get_current_user)]):
    return {
        "username": current_user.username,
        "display_name": current_user.display_name,
        "role": "admin" if current_user.is_admin else "user",
        "language": current_user.language,
    }


@router.put("/language")
async def update_language(
    body: LanguageRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """Update the user's preferred language (e.g. "en", "de")."""
    current_user.language = body.language
    db.add(current_user)
    await db.commit()
    return {"language": current_user.language}


@router.put("/profile")
async def update_profile(
    body: UpdateProfileRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    response: Response,
):
    """Update display name, username, and/or password.

    Returns a fresh access token when the username changes so the
    JWT sub claim stays in sync.
    """
    try:
        user = await IAMService.update_profile(
            db=db,
            user=current_user,
            display_name=body.display_name,
            username=body.username,
            password=body.password,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    username_changed = body.username is not None and body.username.lower() != current_user.username

    result: dict = {
        "username": user.username,
        "display_name": user.display_name,
        "role": "admin" if user.is_admin else "user",
        "language": user.language,
    }

    if username_changed:
        access_token = create_access_token(
            {"sub": user.username, "uid": user.id, "role": "admin" if user.is_admin else "user"}
        )
        refresh_token = create_refresh_token(user.id, user.username)
        set_refresh_cookie(response, refresh_token)
        result["access_token"] = access_token

    return result


# ── Setup check (public) ──────────────────────────────────────

@router.get("/check-setup")
async def check_setup(
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Returns whether any users exist. Used by the frontend to decide
    whether to redirect to /login or /register on first visit."""
    result = await session.exec(select(User).limit(1))
    has_users = result.first() is not None
    return {"has_users": has_users}


# ── User listing ──────────────────────────────────────────────

@router.get("/users")
async def list_users(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """All users visible to any authenticated user (for autocomplete)."""
    result = await session.exec(select(User).order_by(User.username))
    return [
        {
            "username": u.username,
            "display_name": u.display_name,
            "role": "admin" if u.is_admin else "user",
            "language": u.language,
            "created_at": u.created_at.isoformat() if u.created_at else None,
        }
        for u in result.all()
    ]


# ── Admin: create user ────────────────────────────────────────

@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    _admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Admin creates a user directly (without invitation)."""
    username = body.username.lower()
    result = await session.exec(select(User).where(User.username == username))
    if result.first():
        raise HTTPException(status_code=409, detail="Username already taken")

    user = User(
        username=username,
        display_name=body.display_name,
        is_admin=(body.role == "admin"),
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return {
        "username": user.username,
        "display_name": user.display_name,
        "role": "admin" if user.is_admin else "user",
        "language": user.language,
    }


# ── Admin: delete user ────────────────────────────────────────

@router.delete("/users/{username}")
async def delete_user(
    username: str,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    username = username.lower()
    if username == admin.username:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await session.exec(select(User).where(User.username == username))
    user = result.first()
    if user:
        await session.delete(user)
        await session.commit()
    return {"status": "deleted"}


# ── Change password (legacy) ──────────────────────────────────

@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    await IAMService.update_profile(db=db, user=current_user, password=body.new_password)
    return {"status": "ok"}
