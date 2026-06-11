"""
Session management, labelling, progress tracking, conflict resolution, CSV export.

Multi-project file sharing
--------------------------
Items are deduplicated globally (see upload_routes.py). Each item owns a
reference set `item_refs:<item_id>` containing every session_id that uses it.

* `save_session` ADDs the session_id to every referenced item's ref set.
  Re-saving an existing session (admin edit) only adds new items and
  removes the session_id from items that are no longer referenced.
* `delete_session` REMOVES the session_id from every ref set; the item +
  on-disk file are deleted only when the set becomes empty.
"""
import csv
import io
import math
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

import database as db
from auth import UserInDB, get_current_user, require_admin
from config import get_settings

router = APIRouter(prefix="/api", tags=["sessions"])


# ── Helpers ───────────────────────────────────────────────────

async def _item_meta(item_id: str) -> tuple[str, str]:
    obj = await db.get_json(db.key_item(item_id))
    if not obj:
        return "Unknown", "unknown"
    return obj.get("name", "Unknown"), obj.get("type", "unknown")


def _user_can_access_annotator(current_user: UserInDB, annotator_username: str) -> bool:
    """Admins can act as any annotator; regular users only as themselves."""
    if current_user.role == "admin":
        return True
    return current_user.username == annotator_username.lower()


async def _gc_item(item_id: str) -> None:
    """Delete item + on-disk file when no session references it any more."""
    if await db.scard(db.key_item_refs(item_id)) > 0:
        return
    item = await db.get_json(db.key_item(item_id))
    if not item:
        await db.delete_key(db.key_item_refs(item_id))
        return

    fn = item.get("filename")
    if fn:
        p = get_settings().media_path / fn
        if p.exists():
            p.unlink()

    content_hash = item.get("content_hash")
    if content_hash:
        await db.delete_key(db.key_hash_to_item(content_hash))
    source_hash = item.get("source_hash")
    if source_hash:
        await db.delete_key(f"table_rows:{source_hash}")

    await db.delete_key(db.key_item(item_id))
    await db.delete_key(db.key_item_refs(item_id))


async def _attach_session_to_items(session_id: str, new_item_ids: list[str]) -> None:
    """Diff against existing references and update each item's ref set."""
    previous = await db.get_json(db.key_session(session_id)) or {}
    old_items: set[str] = set(previous.get("item_ids", []))
    new_items: set[str] = set(new_item_ids)

    for item_id in new_items - old_items:
        await db.sadd(db.key_item_refs(item_id), session_id)

    for item_id in old_items - new_items:
        await db.srem(db.key_item_refs(item_id), session_id)
        await _gc_item(item_id)


# ── Sessions CRUD ─────────────────────────────────────────────

@router.post("/sessions/save-full")
async def save_session(
    payload: dict[str, Any],
    _admin: Annotated[UserInDB, Depends(require_admin)],
):
    session_id = payload.get("id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session id")

    item_ids: list[str] = list(payload.get("item_ids") or [])
    await _attach_session_to_items(session_id, item_ids)

    await db.set_json(db.key_session(session_id), payload)
    await db.sadd(db.SET_SESSIONS, session_id)
    return {"status": "ok", "id": session_id}


@router.get("/sessions")
async def list_sessions(current_user: Annotated[UserInDB, Depends(get_current_user)]):
    """
    Admins see all sessions.
    Annotators only see sessions they are assigned to.
    """
    sids = await db.smembers(db.SET_SESSIONS)
    sessions = []
    for sid in sids:
        data = await db.get_json(db.key_session(sid))
        if not data:
            continue
        if current_user.role == "admin" or current_user.username in [
            a.lower() for a in data.get("annotators", [])
        ]:
            sessions.append(data)
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    data = await db.get_json(db.key_session(session_id))
    if not data:
        raise HTTPException(status_code=404, detail="Session not found")
    if current_user.role != "admin" and current_user.username not in [
        a.lower() for a in data.get("annotators", [])
    ]:
        raise HTTPException(status_code=403, detail="Not assigned to this session")
    return data


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    _admin: Annotated[UserInDB, Depends(require_admin)],
):
    data = await db.get_json(db.key_session(session_id))
    if data:
        # Detach session from every item, then GC items with zero refs.
        for item_id in data.get("item_ids", []):
            await db.srem(db.key_item_refs(item_id), session_id)
            await _gc_item(item_id)

        for ann in data.get("annotators", []):
            await db.delete_key(db.key_labels(session_id, ann))
        await db.delete_key(db.key_final_labels(session_id))
        await db.delete_key(db.key_session(session_id))

    await db.srem(db.SET_SESSIONS, session_id)
    return {"status": "deleted"}


# ── Items ─────────────────────────────────────────────────────

@router.get("/items/{item_id}")
async def get_item(
    item_id: str,
    _user: Annotated[UserInDB, Depends(get_current_user)],
):
    data = await db.get_json(db.key_item(item_id))
    if not data:
        raise HTTPException(status_code=404, detail="Item not found")
    return data


# ── Labels ────────────────────────────────────────────────────

@router.post("/labels/{session_id}/{annotator}")
async def save_labels(
    session_id: str,
    annotator: str,
    payload: dict[str, list[str]],
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    if not _user_can_access_annotator(current_user, annotator):
        raise HTTPException(status_code=403, detail="Cannot save labels for another user")
    existing = await db.get_json(db.key_labels(session_id, annotator)) or {}
    existing.update(payload)
    await db.set_json(db.key_labels(session_id, annotator), existing)
    return {"status": "ok"}


@router.get("/labels/{session_id}/{annotator}")
async def get_labels(
    session_id: str,
    annotator: str,
    current_user: Annotated[UserInDB, Depends(get_current_user)],
):
    if not _user_can_access_annotator(current_user, annotator):
        raise HTTPException(status_code=403, detail="Cannot read labels for another user")
    return await db.get_json(db.key_labels(session_id, annotator)) or {}


# ── Progress ──────────────────────────────────────────────────

@router.get("/sessions/{session_id}/progress")
async def get_progress(
    session_id: str,
    _user: Annotated[UserInDB, Depends(get_current_user)],
):
    session = await db.get_json(db.key_session(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    progress = {}
    for ann in session.get("annotators", []):
        lbls = await db.get_json(db.key_labels(session_id, ann)) or {}
        batch = session.get("batches", {}).get(ann, [])
        labeled = sum(1 for i in batch if i in lbls and lbls[i])
        total = len(batch)
        progress[ann] = {
            "labeled": labeled,
            "total": total,
            "pct": math.floor(labeled / total * 100) if total else 0,
        }
    return progress


# ── Conflicts & resolution (admin only) ───────────────────────

@router.get("/sessions/{session_id}/conflicts")
async def get_conflicts(
    session_id: str,
    _admin: Annotated[UserInDB, Depends(require_admin)],
):
    session = await db.get_json(db.key_session(session_id))
    if not session:
        return {"conflicts": []}

    annotators = session.get("annotators", [])
    all_labels = {a: (await db.get_json(db.key_labels(session_id, a)) or {}) for a in annotators}
    final = await db.get_json(db.key_final_labels(session_id)) or {}

    conflicts = []
    for item_id in session.get("item_ids", []):
        votes = {
            ann: all_labels[ann].get(item_id, [])
            for ann in annotators
            if item_id in session.get("batches", {}).get(ann, [])
        }
        if len(votes) <= 1:
            continue
        if len({tuple(sorted(v)) for v in votes.values()}) <= 1:
            continue
        name, typ = await _item_meta(item_id)
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
    _admin: Annotated[UserInDB, Depends(require_admin)],
):
    item_id = payload.get("item_id")
    final_labels = payload.get("final_labels", [])
    existing = await db.get_json(db.key_final_labels(session_id)) or {}
    existing[item_id] = final_labels
    await db.set_json(db.key_final_labels(session_id), existing)
    return {"status": "ok"}


# ── Export (admin only) ───────────────────────────────────────

@router.get("/sessions/{session_id}/export")
async def export_session(
    session_id: str,
    _admin: Annotated[UserInDB, Depends(require_admin)],
    mode: str = "raw",
):
    session = await db.get_json(db.key_session(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    annotator_labels = {
        ann: (await db.get_json(db.key_labels(session_id, ann)) or {})
        for ann in session["annotators"]
    }
    final_map = await db.get_json(db.key_final_labels(session_id)) or {}
    rows: list[dict] = []

    if mode == "merged":
        fieldnames = ["item_id", "item_name", "item_type", "final_labels", "agreed_annotators"]
        for item_id in session["item_ids"]:
            name, typ = await _item_meta(item_id)
            votes = {
                ann: annotator_labels[ann].get(item_id, [])
                for ann in session["annotators"]
                if item_id in session["batches"].get(ann, [])
            }
            if item_id in final_map:
                resolved = final_map[item_id]
                final_set = set(resolved)
                # Annotator "agreed" if their label set matches the final labels exactly
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
                "final_labels": " | ".join(sorted(resolved)),
                "agreed_annotators": ", ".join(agreed) if agreed else "None",
            })
    else:
        fieldnames = ["item_id", "item_name", "item_type", "annotator", "labels"]
        for ann in session["annotators"]:
            for item_id in session["batches"].get(ann, []):
                labels = final_map.get(item_id) or annotator_labels[ann].get(item_id, [])
                name, typ = await _item_meta(item_id)
                rows.append({
                    "item_id": item_id, "item_name": name, "item_type": typ,
                    "annotator": ann, "labels": " | ".join(sorted(labels)),
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
