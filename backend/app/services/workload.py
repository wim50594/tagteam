"""
Workload distribution service.
Uses the BatchAssignment table for persistent, stable distribution.
"""
from __future__ import annotations

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app._sqlmodel_compat import col_in
from app.models import Annotation, Project, ProjectMember, ProjectItemRef, User as UserModel


class WorkloadService:
    """Stateless service for batch computation and redistribution."""

    @staticmethod
    def compute_batches(
        item_ids: list[str],
        member_usernames: list[str],
        mode: str,
        k_verifiers: int = 1,
    ) -> dict[str, list[str]]:
        """Compute stable batch assignments (deterministic, no label dependency)."""
        a = len(member_usernames)
        if a == 0:
            return {}

        batches: dict[str, list[str]] = {u: [] for u in member_usernames}

        if mode == "split":
            for i, item_id in enumerate(item_ids):
                batches[member_usernames[i % a]].append(item_id)
            return batches

        # verification mode: greedy min-load, k annotators per item
        k = min(k_verifiers, a)
        loads: dict[str, int] = {u: 0 for u in member_usernames}
        for item_id in item_ids:
            chosen = sorted(member_usernames, key=lambda x: loads[x])[:k]
            for u in chosen:
                batches[u].append(item_id)
                loads[u] += 1
        return batches

    @staticmethod
    async def redistribute_on_member_added(
        db: AsyncSession,
        project: Project,
        new_member_username: str,
    ) -> dict[str, list[str]]:
        """Redistribute batches when a single new member joins a project.

        The new member gets unlabeled items taken from existing members.
        Existing members keep their labeled items; unlabeled ones may shift.
        """
        old_batches: dict[str, list[str]] = project.batches or {}

        # If no stored batches, try reading from the BatchAssignment table
        if not old_batches:
            from app.models import BatchAssignment
            result = await db.exec(
                select(BatchAssignment).where(BatchAssignment.project_id == project.id)
            )
            for row in result.all():
                old_batches.setdefault(row.annotator_username, []).append(row.item_id)

        # Get all member usernames (including the new one)
        member_result = await db.exec(
            select(ProjectMember).where(ProjectMember.project_id == project.id)
        )
        member_users = member_result.all()
        user_ids = [m.user_id for m in member_users]
        user_map: dict[int, str] = {}
        if user_ids:
            users_result = await db.exec(
                select(UserModel).where(col_in(UserModel.id, user_ids))
            )
            for u in users_result.all():
                user_map[u.id] = u.username
        all_members = [user_map[m.user_id] for m in member_users if m.user_id in user_map]

        # Get all item IDs
        refs_result = await db.exec(
            select(ProjectItemRef).where(ProjectItemRef.project_id == project.id)
        )
        all_items = [r.item_id for r in refs_result.all()]

        if not old_batches or not all_items:
            # No existing batches or no items — compute fresh
            return WorkloadService.compute_batches(
                all_items, all_members, project.mode, project.k_verifiers
            )

        # Get annotations: which items have been labeled (by any annotator)
        annotations_result = await db.exec(
            select(Annotation).where(Annotation.project_id == project.id)
        )
        # Map: (annotator_id, item_id) -> has labels (latest version)
        latest_version: dict[tuple[int, str], int] = {}
        labeled_by: dict[tuple[int, str], bool] = {}
        for ann in annotations_result.all():
            key = (ann.annotator_id, ann.item_id)
            if key not in latest_version or ann.version > latest_version[key]:
                latest_version[key] = ann.version
                labeled_by[key] = bool(ann.labels)

        # Items already labeled by a specific annotator (keep with them)
        labeled_item_annotators: dict[str, set[str]] = {}  # item_id -> set of usernames who labeled it
        for (aid, iid), has_labels in labeled_by.items():
            if has_labels and aid in user_map:
                labeled_item_annotators.setdefault(iid, set()).add(user_map[aid])

        k = project.k_verifiers if project.mode == "verification" else 1

        # Count how many items have been labeled at all
        labeled_count = sum(1 for annotators in labeled_item_annotators.values() if annotators)

        # If few or no items are labeled, just do a clean full recompute.
        if labeled_count == 0 or labeled_count <= len(all_items) * 0.25:
            return WorkloadService.compute_batches(
                all_items, all_members, project.mode, k,
            )

        if project.mode == "split":
            # Split mode: each item goes to exactly 1 person
            # Keep labeled items with their annotators; redistribute unlabeled
            batches: dict[str, list[str]] = {u: [] for u in all_members}
            for u in old_batches:
                for iid in old_batches[u]:
                    if iid in labeled_item_annotators and u in labeled_item_annotators[iid]:
                        batches[u].append(iid)
            # Unlabeled items: full round-robin across all members
            unlabeled = [iid for iid in all_items
                         if iid not in labeled_item_annotators or not labeled_item_annotators[iid]]
            a = len(all_members)
            for i, iid in enumerate(unlabeled):
                batches[all_members[i % a]].append(iid)
            return batches

        # Verification mode: keep labeled assignments, recompute unlabeled
        batches: dict[str, list[str]] = {u: [] for u in all_members}
        loads: dict[str, int] = {u: 0 for u in all_members}

        # Phase 1: keep labeled items with their annotators
        unlabeled_items: list[str] = []
        for iid in all_items:
            labelers = labeled_item_annotators.get(iid, set())
            if labelers:
                for u in labelers:
                    if u in batches:
                        batches[u].append(iid)
                        loads[u] += 1
            else:
                unlabeled_items.append(iid)

        # Phase 2: redistribute unlabeled items from scratch with all members
        if unlabeled_items:
            unlabeled_batches = WorkloadService.compute_batches(
                unlabeled_items, all_members, "verification", k,
            )
            for u, items in unlabeled_batches.items():
                batches[u].extend(items)
                loads[u] += len(items)

        return batches

    @staticmethod
    def batch_summary(
        item_count: int,
        annotator_count: int,
        mode: str,
        k_verifiers: int = 1,
    ) -> str:
        """Human-readable summary of the workload distribution."""
        a = annotator_count
        if not a:
            return "No annotators assigned"

        if mode == "split":
            return f"~{item_count // a + (1 if item_count % a else 0)} items/person · {item_count} total · {a} people"

        k = min(k_verifiers, a)
        total = item_count * k
        base = total // a
        extra = total % a
        msg = f"{item_count} items × {k} people = {total} annotations · "
        if extra > 0:
            msg += f"{extra} person(s) with {base + 1}, {a - extra} person(s) with {base}"
        else:
            msg += f"{a} people with {base} each"
        return msg
