"""
Identity & Access Management service.
Handles registration, invitations, and profile management.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth import hash_password, promote_first_user
from app.models import Invitation, Project, ProjectMember, User
from app.services.workload import WorkloadService


class IAMService:
    """Stateless service for user and invitation operations."""

    @staticmethod
    async def create_invitation(
        db: AsyncSession,
        project_id: int,
        role: str,
        created_by: int,
        expires_in_days: int | None = None,
    ) -> Invitation:
        """Generate a secure invite token for a project and role."""
        token = secrets.token_urlsafe(32)
        expires_at = None
        if expires_in_days:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

        invitation = Invitation(
            token=token,
            project_id=project_id,
            role=role,
            created_by=created_by,
            expires_at=expires_at,
        )
        db.add(invitation)
        await db.commit()
        await db.refresh(invitation)
        return invitation

    @staticmethod
    async def validate_invitation(
        db: AsyncSession, token: str
    ) -> Invitation:
        """Validate an invitation token. Returns the Invitation or raises."""
        result = await db.exec(select(Invitation).where(Invitation.token == token))
        invitation = result.first()
        if not invitation:
            raise ValueError("Invalid invitation token")
        if invitation.used:
            raise ValueError("Invitation token has already been used")
        if invitation.expires_at and invitation.expires_at < datetime.now(timezone.utc):
            raise ValueError("Invitation token has expired")
        return invitation

    @staticmethod
    async def register_with_invitation(
        db: AsyncSession,
        token: str,
        username: str,
        display_name: str,
        password: str,
    ) -> User:
        """Register a new user using a valid invitation token.

        Creates the user, marks the invitation as used, and adds the
        user as a project member with the invited role.
        """
        invitation = await IAMService.validate_invitation(db, token)

        # Check username uniqueness
        result = await db.exec(select(User).where(User.username == username.lower()))
        if result.first():
            raise ValueError("Username already taken")

        # Create user (first user gets admin if no admin exists)
        user = User(
            username=username.lower(),
            display_name=display_name,
            hashed_password=hash_password(password),
            is_admin=False,
        )
        db.add(user)
        await db.flush()

        # Delete invitation (no longer needed)
        await db.delete(invitation)

        # Add as project member
        membership = ProjectMember(
            project_id=invitation.project_id,
            user_id=user.id,
            role=invitation.role,
        )
        db.add(membership)

        # Redistribute batches: give new member unlabeled items from existing members
        project = await db.get(Project, invitation.project_id)
        if project:
            from app.routes.project_routes import _read_batches, _write_batches
            old_batches = await _read_batches(db, project.id)
            if not old_batches:
                old_batches = project.batches or {}
            if old_batches:
                # Temporarily set for redistribution
                project.batches = old_batches
                new_batches = await WorkloadService.redistribute_on_member_added(
                    db=db,
                    project=project,
                    new_member_username=user.username,
                )
                if new_batches:
                    await _write_batches(db, project.id, new_batches)

        await promote_first_user(db)
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_project_role(
        db: AsyncSession, project_id: int, user_id: int
    ) -> str | None:
        """Return the user's role in a project, or None if not a member."""
        result = await db.exec(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        member = result.first()
        return member.role if member else None

    @staticmethod
    async def can_manage_project(
        db: AsyncSession, project_id: int, user: User
    ) -> bool:
        """Check whether a user can manage (edit/delete/resolve) a project."""
        if user.is_admin:
            return True
        role = await IAMService.get_project_role(db, project_id, user.id)
        return role in ("owner", "maintainer")

    @staticmethod
    async def can_annotate_project(
        db: AsyncSession, project_id: int, user: User
    ) -> bool:
        """Check whether a user can annotate in a project."""
        if user.is_admin:
            return True
        role = await IAMService.get_project_role(db, project_id, user.id)
        return role is not None  # any member can annotate

    @staticmethod
    async def update_profile(
        db: AsyncSession,
        user: User,
        display_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> User:
        """Update a user's profile fields. Returns the updated user."""
        if display_name is not None:
            user.display_name = display_name
        if username is not None:
            new_username = username.lower()
            # Ensure new username is not taken by someone else
            result = await db.exec(
                select(User).where(
                    User.username == new_username, User.id != user.id
                )
            )
            if result.first():
                raise ValueError("Username already taken")
            user.username = new_username
        if password is not None:
            user.hashed_password = hash_password(password)

        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
