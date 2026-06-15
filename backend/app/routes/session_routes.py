"""
Session management, labelling, progress tracking, conflict resolution, CSV export.

Multi-project file sharing
--------------------------
Items are deduplicated globally (see upload_routes.py). Each item owns a
set of `ItemRef` rows containing every session_id that uses it.

* `save_session` adds the session_id to every referenced item's ref set.
  Re-saving an existing session (admin edit) only adds new items and
  removes the session_id from items that are no longer referenced.
* `delete_session` removes the session_id from every ref set; the item +
  on-disk file are deleted only when the set becomes empty.

Redis (if configured) is used purely as a read-through cache for sessions,
items and progress. The RDBMS remains the single source of truth and is
always written first; the cache is invalidated on every write.
"""
import csv
import io
import math
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from auth import User, get_current_user, require_admin
from config import get_settings
from database import (
    cache_delete,
    cache_get,
    cache_key_item,
    cache_key_progress,
    cache_key_session,
    cache_set,
    get_session,
)
from models import FinalLabel, Item, ItemRef, Label, Session as SessionModel, TableUpload

router = APIRouter(prefix="/api", tags=["sessions"])


# ── Helpers ───────────────────────────────────────────────────

async def _item_meta(db: AsyncSession, item_id: str) -> tuple[str, str]:
    cached = await cache_get(cache_key_item(item_id))
    if cached:
        return cached.get("name", "Unknown"), cached.get("type", "unknown")

    item = await db.get(Item, item_id)
    if not item:
        return "Unknown", "unknown"

    await cache_set(cache_key_item(item_id), {"name": item.name, "type": item.type})
    return item.name, item.type


def _user_can_access_annotator(current_user: User, annotator_username: str) -> bool:
    """Admins can act as any annotator; regular users only as themselves."""
    if current_user.role == "admin":
        return True
    return current_user.username == annotator_username.lower()


async def _ref_count(db: AsyncSession, item_id: str) -> int:
    result = await db.exec(select(ItemRef).where(ItemRef.item_id == item_id))
    return len(result.all())


async def _gc_item(db: AsyncSession, item_id: str) -> None:
    """Delete item + on-disk file when no session references it any more."""
    if await _ref_count(db, item_id) > 0:
        return

    item = await db.get(Item, item_id)
    if not item:
        return

    if item.filename:
        p = get_settings().media_path / item.filename
        if p.exists():
            p.unlink()

    if item.source_hash:
        upload = await db.get(TableUpload, item.source_hash)
        if upload:
            await db.delete(upload)

    await db.delete(item)
    await cache_delete(cache_key_item(item_id))


async def _attach_session_to_items(
    db: AsyncSession, session_id: str, new_item_ids: list[str]
) -> None:
    """Diff against existing references and update each item's ref set."""
    existing_session = await db.get(SessionModel, session_id)
    old_items: set[str] = set(existing_session.item_ids) if existing_session else set()
    new_items: set[str] = set(new_item_ids)

    for item_id in new_items - old_items:
        db.add(ItemRef(item_id=item_id, session_id=session_id))

    for item_id in old_items - new_items:
        ref = await db.get(ItemRef, (item_id, session_id))
        if ref:
            await db.delete(ref)
        await db.flush()
        await _gc_item(db, item_id)


def _collapse_hierarchy(labels: list[str]) -> list[str]:
    """Keep only the deepest label per hierarchy path.

    "Travel" is dropped if "Travel > Air" or "Travel > Air > Plane" is also
    selected. Labels without children stay as-is.
    """
    labels = sorted(set(labels))
    return [a for a in labels if not any(b != a and b.startswith(a + " > ") for b in labels)]


# ── Sessions CRUD ─────────────────────────────────────────────

@router.post("/sessions/save-full")
async def save_session(
    payload: dict[str, Any],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    session_id = payload.get("id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session id")

    item_ids: list[str] = list(payload.get("item_ids") or [])
    await _attach_session_to_items(db, session_id, item_ids)

    extra = {
        k: v for k, v in payload.items()
        if k not in {"id", "name", "created_at", "annotators", "item_ids", "batches"}
    }

    session_obj = await db.get(SessionModel, session_id)
    if session_obj is None:
        session_obj = SessionModel(id=session_id)

    session_obj.name = payload.get("name")
    session_obj.annotators = list(payload.get("annotators") or [])
    session_obj.item_ids = item_ids
    session_obj.batches = dict(payload.get("batches") or {})
    session_obj.extra = extra

    db.add(session_obj)
    await db.commit()

    await cache_delete(cache_key_session(session_id), cache_key_progress(session_id))
    return {"status": "ok", "id": session_id}


@router.get("/sessions")
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """
    Admins see all sessions.
    Annotators only see sessions they are assigned to.
    """
    result = await db.exec(
        select(SessionModel).order_by(SessionModel.created_at.desc())
    )
    sessions = []
    for s in result.all():
        if current_user.role == "admin" or current_user.username in [
            a.lower() for a in s.annotators
        ]:
            sessions.append(s.to_payload())
    return sessions


@router.get("/sessions/{session_id}")
async def get_session_detail(
    session_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    cached = await cache_get(cache_key_session(session_id))
    if cached:
        data = cached
    else:
        session_obj = await db.get(SessionModel, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")
        data = session_obj.to_payload()
        await cache_set(cache_key_session(session_id), data)

    if current_user.role != "admin" and current_user.username not in [
        a.lower() for a in data.get("annotators", [])
    ]:
        raise HTTPException(status_code=403, detail="Not assigned to this session")
    return data


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    session_obj = await db.get(SessionModel, session_id)
    if session_obj:
        # Detach session from every item, then GC items with zero refs.
        for item_id in session_obj.item_ids:
            ref = await db.get(ItemRef, (item_id, session_id))
            if ref:
                await db.delete(ref)
            await db.flush()
            await _gc_item(db, item_id)

        for ann in session_obj.annotators:
            label = await db.get(Label, (session_id, ann))
            if label:
                await db.delete(label)

        final = await db.get(FinalLabel, session_id)
        if final:
            await db.delete(final)

        await db.delete(session_obj)
        await db.commit()

    await cache_delete(cache_key_session(session_id), cache_key_progress(session_id))
    return {"status": "deleted"}


# ── Items ─────────────────────────────────────────────────────

@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    item = await db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item.model_dump()


# ── Labels ────────────────────────────────────────────────────

@router.post("/labels/{session_id}/{annotator}")
async def save_labels(
    session_id: str,
    annotator: str,
    payload: dict[str, list[str]],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    if not _user_can_access_annotator(current_user, annotator):
        raise HTTPException(status_code=403, detail="Cannot save labels for another user")

    label = await db.get(Label, (session_id, annotator))
    if label is None:
        label = Label(session_id=session_id, annotator=annotator, data={})

    label.data = {**label.data, **payload}
    db.add(label)
    await db.commit()

    await cache_delete(cache_key_progress(session_id))
    return {"status": "ok"}


@router.get("/labels/{session_id}/{annotator}")
async def get_labels(
    session_id: str,
    annotator: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    if not _user_can_access_annotator(current_user, annotator):
        raise HTTPException(status_code=403, detail="Cannot read labels for another user")

    label = await db.get(Label, (session_id, annotator))
    return label.data if label else {}


# ── Progress ──────────────────────────────────────────────────

@router.get("/sessions/{session_id}/progress")
async def get_progress(
    session_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    cached = await cache_get(cache_key_progress(session_id))
    if cached:
        return cached

    session_obj = await db.get(SessionModel, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")

    progress = {}
    for ann in session_obj.annotators:
        label = await db.get(Label, (session_id, ann))
        lbls = label.data if label else {}
        batch = session_obj.batches.get(ann, [])
        labeled = sum(1 for i in batch if i in lbls and lbls[i])
        total = len(batch)
        progress[ann] = {
            "labeled": labeled,
            "total": total,
            "pct": math.floor(labeled / total * 100) if total else 0,
        }

    await cache_set(cache_key_progress(session_id), progress, ttl=30)
    return progress


# ── Conflicts & resolution (admin only) ───────────────────────

@router.get("/sessions/{session_id}/conflicts")
async def get_conflicts(
    session_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    session_obj = await db.get(SessionModel, session_id)
    if not session_obj:
        return {"conflicts": []}

    annotators = session_obj.annotators
    all_labels: dict[str, dict[str, list[str]]] = {}
    for ann in annotators:
        label = await db.get(Label, (session_id, ann))
        all_labels[ann] = label.data if label else {}

    final_obj = await db.get(FinalLabel, session_id)
    final = final_obj.data if final_obj else {}

    conflicts = []
    for item_id in session_obj.item_ids:
        votes = {
            ann: all_labels[ann].get(item_id, [])
            for ann in annotators
            if item_id in session_obj.batches.get(ann, [])
        }
        if len(votes) <= 1:
            continue
        if len({tuple(sorted(v)) for v in votes.values()}) <= 1:
            continue
        name, typ = await _item_meta(db, item_id)
        conflicts.append({
            "item_id": item_id,
            "name": name,
            "type": typ,
            "details": [{"annotator": a, "labels": v} for a, v in votes.items()],
            "resolved": item_id in final,
            "final_labels": final.get(item_id, []),
        })
    return {"conflicts": conflicts}


@router.post("/sessions/{session_id}/resolve")
async def resolve_conflict(
    session_id: str,
    payload: dict[str, Any],
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    item_id = payload.get("item_id")
    final_labels = payload.get("final_labels", [])

    final_obj = await db.get(FinalLabel, session_id)
    if final_obj is None:
        final_obj = FinalLabel(session_id=session_id, data={})

    final_obj.data = {**final_obj.data, item_id: final_labels}
    db.add(final_obj)
    await db.commit()
    return {"status": "ok"}


# ── Export (admin only) ───────────────────────────────────────

@router.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    _admin: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_session)],
    mode: str = "raw",
):
    session_obj = await db.get(SessionModel, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Session not found")

    annotator_labels: dict[str, dict[str, list[str]]] = {}
    for ann in session_obj.annotators:
        label = await db.get(Label, (session_id, ann))
        annotator_labels[ann] = label.data if label else {}

    final_obj = await db.get(FinalLabel, session_id)
    final_map = final_obj.data if final_obj else {}

    rows: list[dict] = []

    if mode == "merged":
        fieldnames = ["item_id", "item_name", "item_type", "final_labels", "agreed_annotators"]
        for item_id in session_obj.item_ids:
            name, typ = await _item_meta(db, item_id)
            votes = {
                ann: annotator_labels[ann].get(item_id, [])
                for ann in session_obj.annotators
                if item_id in session_obj.batches.get(ann, [])
            }
            if item_id in final_map:
                resolved = final_map[item_id]
                final_set = set(resolved)
                agreed = [
                    ann for ann, lbls in votes.items()
                    if set(lbls) == final_set
                ]
            else:
                first = None
                match = True
                for lbls in votes.values():
                    if first is None:
                        first = sorted(lbls)
                    elif first != sorted(lbls):
                        match = False
                        break
                resolved = list(first) if (match and first) else []
                agreed = list(votes.keys()) if match else []
            rows.append({
                "item_id": item_id, "item_name": name, "item_type": typ,
                "final_labels": " | ".join(_collapse_hierarchy(resolved)),
                "agreed_annotators": ", ".join(agreed) if agreed else "None",
            })
    else:
        fieldnames = ["item_id", "item_name", "item_type", "annotator", "labels"]
        for ann in session_obj.annotators:
            for item_id in session_obj.batches.get(ann, []):
                labels = final_map.get(item_id) or annotator_labels[ann].get(item_id, [])
                name, typ = await _item_meta(db, item_id)
                rows.append({
                    "item_id": item_id, "item_name": name, "item_type": typ,
                    "annotator": ann, "labels": " | ".join(_collapse_hierarchy(labels)),
                })

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=multitag_{session_id[:8]}_{mode}.csv"},
    )
