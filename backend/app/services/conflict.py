"""
Conflict resolution service – immutable annotation management.
"""
from __future__ import annotations


from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Annotation, FinalDecision, Project, User


class ConflictService:
    """Stateless service for managing annotations and conflict resolution."""

    @staticmethod
    async def save_annotations(
        db: AsyncSession,
        project_id: int,
        annotator_id: int,
        item_id: str,
        labels: list[str],
    ) -> Annotation:
        """Append a new annotation version (immutable log).

        Creates a new Annotation row with incremented version number.
        The old annotation rows remain untouched.
        """
        # Find current max version for this (project, item, annotator) triplet
        result = await db.exec(
            select(Annotation)
            .where(
                Annotation.project_id == project_id,
                Annotation.item_id == item_id,
                Annotation.annotator_id == annotator_id,
            )
            .order_by(Annotation.version.desc())
            .limit(1)
        )
        latest = result.first()

        version = (latest.version + 1) if latest else 1

        annotation = Annotation(
            project_id=project_id,
            item_id=item_id,
            annotator_id=annotator_id,
            labels=labels,
            version=version,
        )
        db.add(annotation)
        await db.commit()
        await db.refresh(annotation)
        return annotation

    @staticmethod
    async def get_latest_annotations(
        db: AsyncSession,
        project_id: int,
        annotator_id: int,
    ) -> dict[str, list[str]]:
        """Get the latest annotation for each item by this annotator.

        Returns {item_id: [labels]}.
        """
        result = await db.exec(
            select(Annotation)
            .where(
                Annotation.project_id == project_id,
                Annotation.annotator_id == annotator_id,
            )
            .order_by(Annotation.item_id, Annotation.version.desc())
        )
        all_rows = result.all()

        # Take only the latest version per item_id
        label_map: dict[str, list[str]] = {}
        for row in all_rows:
            if row.item_id not in label_map:
                label_map[row.item_id] = row.labels
        return label_map

    @staticmethod
    async def get_all_annotations_for_item(
        db: AsyncSession,
        project_id: int,
        item_id: str,
    ) -> dict[int, list[str]]:
        """Get the latest annotation for each annotator for a specific item.

        Returns {annotator_id: [labels]}.
        """
        result = await db.exec(
            select(Annotation)
            .where(
                Annotation.project_id == project_id,
                Annotation.item_id == item_id,
            )
            .order_by(Annotation.annotator_id, Annotation.version.desc())
        )
        all_rows = result.all()

        label_map: dict[int, list[str]] = {}
        for row in all_rows:
            if row.annotator_id not in label_map:
                label_map[row.annotator_id] = row.labels
        return label_map

    @staticmethod
    async def resolve_conflict(
        db: AsyncSession,
        project_id: int,
        item_id: str,
        resolved_labels: list[str],
        resolved_by: int,
    ) -> FinalDecision:
        """Create or update a final decision for an item.

        This does NOT modify any Annotation rows – they remain immutable.
        """
        result = await db.exec(
            select(FinalDecision).where(
                FinalDecision.project_id == project_id,
                FinalDecision.item_id == item_id,
            )
        )
        existing = result.first()

        if existing:
            existing.resolved_labels = resolved_labels
            existing.resolved_by = resolved_by
            db.add(existing)
            await db.commit()
            await db.refresh(existing)
            return existing
        else:
            decision = FinalDecision(
                project_id=project_id,
                item_id=item_id,
                resolved_labels=resolved_labels,
                resolved_by=resolved_by,
            )
            db.add(decision)
            await db.commit()
            await db.refresh(decision)
            return decision

    @staticmethod
    async def get_final_decision(
        db: AsyncSession,
        project_id: int,
        item_id: str,
    ) -> FinalDecision | None:
        """Get the final decision for an item."""
        result = await db.exec(
            select(FinalDecision).where(
                FinalDecision.project_id == project_id,
                FinalDecision.item_id == item_id,
            )
        )
        return result.first()

    @staticmethod
    async def get_all_final_decisions(
        db: AsyncSession, project_id: int
    ) -> dict[str, list[str]]:
        """Get all final decisions for a project as {item_id: [labels]}."""
        result = await db.exec(
            select(FinalDecision).where(FinalDecision.project_id == project_id)
        )
        return {fd.item_id: fd.resolved_labels for fd in result.all()}

    @staticmethod
    async def get_conflicts(
        db: AsyncSession,
        project: Project,
    ) -> list[dict]:
        """Return a list of conflict items for a project.

        A conflict exists when two or more annotators have different labels
        for the same item in verification mode.
        """
        if project.mode != "verification":
            return []

        # Get annotators who have actually annotated (not just current members)
        # This ensures we show real usernames even for removed members
        all_ann_result = await db.exec(
            select(Annotation)
            .where(Annotation.project_id == project.id)
            .order_by(Annotation.item_id, Annotation.annotator_id, Annotation.version.desc())
        )
        all_annotations = all_ann_result.all()

        # Collect all annotator IDs from the annotations
        annotator_ids_from_anns = set(ann.annotator_id for ann in all_annotations)
        user_map: dict[int, User] = {}
        if annotator_ids_from_anns:
            users_result = await db.exec(
                select(User).where(User.id.in_(list(annotator_ids_from_anns)))
            )
            for u in users_result.all():
                user_map[u.id] = u

        # Get final decisions
        final_decisions = await ConflictService.get_all_final_decisions(db, project.id)

        # Build latest annotation map: {item_id: {annotator_id: [labels]}}
        label_map: dict[str, dict[int, list[str]]] = {}
        for ann in all_annotations:
            if ann.item_id not in label_map:
                label_map[ann.item_id] = {}
            if ann.annotator_id not in label_map[ann.item_id]:
                label_map[ann.item_id][ann.annotator_id] = ann.labels

        # Determine conflicts
        conflicts = []
        for item_id, ann_labels in label_map.items():
            if len(ann_labels) <= 1:
                continue

            # Check if all annotators agree
            label_sets = [tuple(sorted(v)) for v in ann_labels.values()]
            if len(set(label_sets)) <= 1:
                continue

            details = [
                {
                    "annotator": user_map[aid].username,
                    "display_name": user_map[aid].display_name,
                    "labels": labels,
                }
                for aid, labels in ann_labels.items()
                if aid in user_map
            ]

            resolved = item_id in final_decisions

            conflicts.append({
                "item_id": item_id,
                "name": item_id[:8],  # Will be enriched by route
                "type": "unknown",  # Will be enriched by route
                "details": details,
                "resolved": resolved,
                "final_labels": final_decisions.get(item_id, []),
            })

        return sorted(conflicts, key=lambda c: c["resolved"])
