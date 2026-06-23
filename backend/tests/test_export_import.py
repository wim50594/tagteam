"""Integration tests for project export/import roundtrip."""
from __future__ import annotations

import io
import json
import zipfile

import pytest
from sqlmodel import select

from app._sqlmodel_compat import col_in
from app.auth import hash_password
from app.models import User, Project, ProjectMember, Item, Annotation, FinalDecision
from app.routes.project_routes import ProjectItemRef, _write_batches, _read_batches


def _make_user(username, is_admin=False):
    return User(
        username=username,
        display_name=username.capitalize(),
        hashed_password=hash_password("test123"),
        is_admin=is_admin,
    )


@pytest.mark.asyncio
async def test_export_import_roundtrip(db):
    """Create a project, export it, import it back, verify data matches."""
    admin = _make_user("admin", is_admin=True)
    alice = _make_user("alice")
    bob = _make_user("bob")
    db.add_all([admin, alice, bob])
    await db.flush()

    project = Project(name="Test Project", mode="verification", k_verifiers=2, owner_id=admin.id)
    db.add(project)
    await db.flush()

    db.add(ProjectMember(project_id=project.id, user_id=admin.id, role="owner"))
    db.add(ProjectMember(project_id=project.id, user_id=alice.id, role="annotator"))
    db.add(ProjectMember(project_id=project.id, user_id=bob.id, role="annotator"))

    item = Item(id="test-item-1", name="test.txt", type="text", content="hello world")
    db.add(item)
    await db.flush()

    await _write_batches(db, project.id, {"admin": ["test-item-1"], "alice": ["test-item-1"], "bob": []})

    db.add(Annotation(project_id=project.id, item_id="test-item-1", annotator_id=admin.id, labels=["cat"], version=1))
    db.add(Annotation(project_id=project.id, item_id="test-item-1", annotator_id=alice.id, labels=["dog"], version=1))
    db.add(FinalDecision(project_id=project.id, item_id="test-item-1", resolved_labels=["cat"], resolved_by=admin.id))
    await db.commit()

    # Export
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        batches = await _read_batches(db, project.id)
        zf.writestr("project.json", json.dumps({
            "name": project.name, "mode": project.mode, "k_verifiers": project.k_verifiers,
            "created_at": "", "taxonomy": [], "batches": batches,
        }))

        members = (await db.exec(select(ProjectMember).where(ProjectMember.project_id == project.id))).all()
        user_ids = [m.user_id for m in members]
        user_roles = {m.user_id: m.role for m in members}
        users_data = []
        for u in (await db.exec(select(User).where(col_in(User.id, user_ids)))).all():
            users_data.append({"username": u.username, "display_name": u.display_name, "language": u.language, "role": user_roles[u.id]})
        zf.writestr("users.json", json.dumps(users_data))

        zf.writestr("items.json", json.dumps({
            "test-item-1": {"name": "test.txt", "type": "text", "ext": None, "filename": None,
                            "content": "hello world", "size": 11, "data": None,
                            "content_hash": None, "source_file": None, "source_hash": None}
        }))

        annotations = (await db.exec(select(Annotation).where(Annotation.project_id == project.id))).all()
        zf.writestr("annotations.json", json.dumps([
            {"item_id": a.item_id, "annotator_username": (await db.get(User, a.annotator_id)).username,
             "labels": a.labels, "version": a.version, "created_at": ""}
            for a in annotations
        ]))

        decisions = (await db.exec(select(FinalDecision).where(FinalDecision.project_id == project.id))).all()
        zf.writestr("final_decisions.json", json.dumps([
            {"item_id": d.item_id, "resolved_labels": d.resolved_labels, "resolved_by_username": (await db.get(User, d.resolved_by)).username}
            for d in decisions
        ]))

    buf.seek(0)

    # Import (create new project from zip data)
    zf2 = zipfile.ZipFile(buf)
    pdata = json.loads(zf2.read("project.json"))
    udata = json.loads(zf2.read("users.json"))
    adata = json.loads(zf2.read("annotations.json"))
    ddata = json.loads(zf2.read("final_decisions.json"))

    project2 = Project(name=pdata["name"] + " (imported)", mode=pdata["mode"], k_verifiers=pdata["k_verifiers"], owner_id=admin.id)
    db.add(project2)
    await db.flush()

    for u in udata:
        uid = (await db.exec(select(User).where(User.username == u["username"]))).first().id
        db.add(ProjectMember(project_id=project2.id, user_id=uid, role=u["role"]))

    db.add(Item(id="imported-item-1", name="test.txt", type="text", content="hello world"))
    await db.flush()
    db.add(ProjectItemRef(item_id="imported-item-1", project_id=project2.id))

    # Remap batches to use new item IDs
    imported_batches = {}
    for username, items in pdata["batches"].items():
        imported_batches[username] = ["imported-item-1" if i == "test-item-1" else i for i in items]
    await _write_batches(db, project2.id, imported_batches)

    for a in adata:
        uid = (await db.exec(select(User).where(User.username == a["annotator_username"]))).first().id
        db.add(Annotation(project_id=project2.id, item_id="imported-item-1", annotator_id=uid, labels=a["labels"], version=a["version"]))

    for d in ddata:
        uid = (await db.exec(select(User).where(User.username == d["resolved_by_username"]))).first().id
        db.add(FinalDecision(project_id=project2.id, item_id="imported-item-1", resolved_labels=d["resolved_labels"], resolved_by=uid))

    await db.commit()

    # Verify (bob has 0 items, so he won't appear in the batches dict)
    batches2 = await _read_batches(db, project2.id)
    assert batches2.get("admin") == ["imported-item-1"]
    assert batches2.get("alice") == ["imported-item-1"]

    anns = (await db.exec(select(Annotation).where(Annotation.project_id == project2.id))).all()
    assert len(anns) == 2

    decs = (await db.exec(select(FinalDecision).where(FinalDecision.project_id == project2.id))).all()
    assert len(decs) == 1
    assert decs[0].resolved_labels == ["cat"]
