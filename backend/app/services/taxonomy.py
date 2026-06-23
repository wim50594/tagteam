"""
Taxonomy service – hierarchical label management and cascading operations.
"""
from __future__ import annotations

from typing import Sequence

from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Annotation, TaxonomyNode


class TaxonomyService:
    """Stateless service for taxonomy operations."""

    @staticmethod
    def collapse_hierarchy(labels: list[str]) -> list[str]:
        """Keep only the deepest label per hierarchy path.

        "Travel" is dropped if "Travel > Air" or "Travel > Air > Plane" is
        also selected. Labels without children stay as-is.
        """
        labels = sorted(set(labels))
        return [
            a
            for a in labels
            if not any(b != a and b.startswith(a + " > ") for b in labels)
        ]

    @staticmethod
    def expand_labels(labels: list[str], all_nodes: list[TaxonomyNode]) -> list[str]:
        """Expand selected labels to include all ancestor paths.

        If a user picks "Attractions > Amusement and Theme Parks", this
        automatically includes "Attractions" (the parent path) in the
        stored annotation.  The UI can still display the collapsed form.
        """
        expanded = set()
        node_map: dict[str, TaxonomyNode] = {n.full_path: n for n in all_nodes}

        for label in labels:
            parts = label.split(" > ")
            # Add all prefix paths
            for i in range(1, len(parts) + 1):
                ancestor = " > ".join(parts[:i])
                expanded.add(ancestor)

        return sorted(expanded)

    @staticmethod
    async def import_taxonomy(
        db: AsyncSession,
        project_id: int,
        flat_nodes: list[dict],
    ) -> list[TaxonomyNode]:
        """Import a flat list of {name, level, full_path, parent} dicts into TaxonomyNode rows.

        Deletes any existing taxonomy for the project first.
        """
        # Delete existing taxonomy
        await db.exec(
            delete(TaxonomyNode).where(TaxonomyNode.project_id == project_id)
        )
        await db.flush()

        # Phase 1: create all nodes without parent_id, indexed by full_path
        node_map: dict[str, TaxonomyNode] = {}
        for node_data in flat_nodes:
            node = TaxonomyNode(
                project_id=project_id,
                name=node_data["name"],
                level=node_data.get("level", 1),
                full_path=node_data["full_path"],
                parent_id=None,  # resolved in phase 2
            )
            db.add(node)
            node_map[node_data["full_path"]] = node

        await db.flush()

        # Phase 2: set parent_id pointers
        for node_data in flat_nodes:
            parent_path = node_data.get("parent")
            if parent_path and parent_path in node_map:
                child = node_map[node_data["full_path"]]
                child.parent_id = node_map[parent_path].id
                db.add(child)

        await db.commit()

        # Refetch to return with relationships loaded
        result = await db.exec(
            select(TaxonomyNode)
            .where(TaxonomyNode.project_id == project_id)
            .order_by(TaxonomyNode.id)
        )
        return list(result.all())

    @staticmethod
    async def get_taxonomy_flat(
        db: AsyncSession, project_id: int
    ) -> list[dict]:
        """Return the taxonomy as a flat list of {name, level, full_path, parent} dicts."""
        result = await db.exec(
            select(TaxonomyNode)
            .where(TaxonomyNode.project_id == project_id)
            .order_by(TaxonomyNode.level, TaxonomyNode.full_path)
        )
        nodes = result.all()
        node_map = {n.id: n for n in nodes}
        return [
            {
                "name": n.name,
                "level": n.level,
                "full_path": n.full_path,
                "parent": node_map[n.parent_id].full_path if n.parent_id and n.parent_id in node_map else None,
            }
            for n in nodes
        ]

    @staticmethod
    async def get_taxonomy_nodes(
        db: AsyncSession, project_id: int
    ) -> list[TaxonomyNode]:
        """Return TaxonomyNode objects for a project."""
        result = await db.exec(
            select(TaxonomyNode)
            .where(TaxonomyNode.project_id == project_id)
            .order_by(TaxonomyNode.level, TaxonomyNode.full_path)
        )
        return list(result.all())

    @staticmethod
    async def remove_node_cascade(
        db: AsyncSession, node_id: int
    ) -> int:
        """Remove a taxonomy node and all its descendants. Cascade-unlabels items.

        Returns the number of annotations affected.
        """
        # Collect all descendant node full_paths
        node = await db.get(TaxonomyNode, node_id)
        if not node:
            return 0

        # Get the entire taxonomy for this project
        all_nodes = await TaxonomyService.get_taxonomy_nodes(db, node.project_id)
        node_map = {n.full_path: n for n in all_nodes}

        # Find all descendant paths (nodes whose full_path starts with this node's full_path)
        affected_paths: set[str] = set()
        for n in all_nodes:
            if n.full_path == node.full_path or n.full_path.startswith(node.full_path + " > "):
                affected_paths.add(n.full_path)

        if not affected_paths:
            return 0

        # Delete taxonomy nodes
        affected_ids = [n.id for n in all_nodes if n.full_path in affected_paths]
        for nid in affected_ids:
            node_obj = await db.get(TaxonomyNode, nid)
            if node_obj:
                await db.delete(node_obj)

        # Cascade: remove these labels from all annotations in this project
        annotations_result = await db.exec(
            select(Annotation).where(Annotation.project_id == node.project_id)
        )
        annotations = annotations_result.all()

        count = 0
        for ann in annotations:
            old_labels = set(ann.labels)
            new_labels = [l for l in ann.labels if l not in affected_paths]
            if len(new_labels) != len(old_labels):
                ann.labels = new_labels
                db.add(ann)
                count += 1

        await db.commit()
        return count
