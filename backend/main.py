import json
import uuid
import csv
import io
import os
import math
from pathlib import Path
from typing import Optional, List, Dict, Any

import aiofiles
import redis.asyncio as aioredis
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
import pandas as pd

app = FastAPI(title="MultiTag Suite API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path("/app/data")
MEDIA_DIR = DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379")
redis_client: aioredis.Redis = None


@app.on_event("startup")
async def startup():
    global redis_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)


@app.on_event("shutdown")
async def shutdown():
    if redis_client:
        await redis_client.close()


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/media/{filename:path}")
async def get_media(filename: str):
    file_path = MEDIA_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


class SessionCreate(BaseModel):
    name: str
    annotators: List[str]
    verification_mode: bool = False
    display_columns: List[str] = []
    item_ids: List[str] = []
    taxonomy: List[Dict[str, Any]] = []


async def get_item_meta(item_id: str):
    raw = await redis_client.get(f"item:{item_id}")
    if not raw:
        return "Unknown", "unknown"
    obj = json.loads(raw)
    return obj.get("name", "Unknown"), obj.get("type", "unknown")


@app.post("/api/upload-universal")
async def upload_universal(files: List[UploadFile] = File(...)):
    item_ids = []
    columns_set = set()
    stats = {"images": 0, "pdfs": 0, "texts": 0, "tables": 0, "svgs": 0}

    for f in files:
        filename = f.filename or ""
        base_name = os.path.basename(filename)
        ext = os.path.splitext(base_name)[1].lower()

        if base_name.startswith('.') or base_name == '':
            continue

        item_id = str(uuid.uuid4())

        if ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff']:
            content = await f.read()
            file_path = MEDIA_DIR / f"{item_id}{ext}"
            async with aiofiles.open(file_path, 'wb') as out:
                await out.write(content)
            meta = {"id": item_id, "name": base_name, "type": "image", "ext": ext, "filename": f"{item_id}{ext}"}
            await redis_client.set(f"item:{item_id}", json.dumps(meta))
            item_ids.append(item_id)
            stats["images"] += 1

        elif ext == '.svg':
            content = await f.read()
            file_path = MEDIA_DIR / f"{item_id}.svg"
            async with aiofiles.open(file_path, 'wb') as out:
                await out.write(content)
            meta = {"id": item_id, "name": base_name, "type": "image", "ext": ".svg", "filename": f"{item_id}.svg"}
            await redis_client.set(f"item:{item_id}", json.dumps(meta))
            item_ids.append(item_id)
            stats["svgs"] += 1

        elif ext == '.pdf':
            content = await f.read()
            file_path = MEDIA_DIR / f"{item_id}.pdf"
            async with aiofiles.open(file_path, 'wb') as out:
                await out.write(content)
            meta = {"id": item_id, "name": base_name, "type": "pdf", "ext": ".pdf", "filename": f"{item_id}.pdf"}
            await redis_client.set(f"item:{item_id}", json.dumps(meta))
            item_ids.append(item_id)
            stats["pdfs"] += 1

        elif ext in ['.csv', '.tsv', '.xlsx', '.xls']:
            content = await f.read()
            try:
                if ext in ['.xlsx', '.xls']:
                    df = pd.read_excel(io.BytesIO(content))
                else:
                    sep = '\t' if ext == '.tsv' else None
                    df = pd.read_csv(io.BytesIO(content), sep=sep, engine='python')
                df = df.where(pd.notnull(df), None)
                for _, row in df.iterrows():
                    row_id = str(uuid.uuid4())
                    row_dict = {str(k): (str(v) if v is not None else '') for k, v in row.to_dict().items()}
                    for k in row_dict.keys():
                        columns_set.add(k)
                    meta = {"id": row_id, "name": f"Row from {base_name}", "type": "table", "data": row_dict, "source_file": base_name}
                    await redis_client.set(f"item:{row_id}", json.dumps(meta))
                    item_ids.append(row_id)
                    stats["tables"] += 1
            except Exception as e:
                print(f"Error parsing {base_name}: {e}")

        elif ext in ['.txt', '.md']:
            content = (await f.read()).decode('utf-8', errors='ignore')
            meta = {"id": item_id, "name": base_name, "type": "text", "content": content}
            await redis_client.set(f"item:{item_id}", json.dumps(meta))
            item_ids.append(item_id)
            stats["texts"] += 1

    return {"item_ids": item_ids, "columns": sorted(list(columns_set)), "stats": stats}


@app.post("/api/parse-labels")
async def parse_labels(
    file: UploadFile = File(...),
    has_header: bool = Form(True),
    delimiter: str = Form("")
):
    content = await file.read()
    fname = (file.filename or "").lower()

    # Plain text: one label per line
    if fname.endswith('.txt'):
        text = content.decode('utf-8', errors='ignore')
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        taxonomy = []
        for line in lines:
            # Support hierarchical lines separated by > or ;
            if '>' in line:
                parts = [p.strip() for p in line.split('>') if p.strip()]
            elif ';' in line:
                parts = [p.strip() for p in line.split(';') if p.strip()]
            else:
                parts = [line]
            # Build all ancestor nodes too
            for i, part in enumerate(parts):
                path = " > ".join(parts[:i+1])
                if not any(t['full_path'] == path for t in taxonomy):
                    taxonomy.append({"name": part, "level": i + 1, "full_path": path, "parent": " > ".join(parts[:i]) if i > 0 else None})
        return {"taxonomy": taxonomy}

    try:
        # Infer separator
        if fname.endswith('.tsv'):
            sep = '\t'
        elif delimiter and delimiter.strip():
            sep = delimiter.strip()
        else:
            # Sniff
            sample = content[:2048].decode('utf-8', errors='ignore')
            sniff_sep = None
            for s in [',', '\t', ';', '|']:
                if s in sample:
                    sniff_sep = s
                    break
            sep = sniff_sep

        df = pd.read_csv(io.BytesIO(content), sep=sep, header=0 if has_header else None, engine='python', dtype=str)
        df = df.where(pd.notnull(df), None)

        taxonomy = []
        for _, row in df.iterrows():
            parts = [str(x).strip() for x in row if x is not None and str(x).strip() not in ('', 'nan', 'None')]
            if not parts:
                continue
            # Build ancestor nodes
            for i, part in enumerate(parts):
                path = " > ".join(parts[:i+1])
                if not any(t['full_path'] == path for t in taxonomy):
                    taxonomy.append({
                        "name": part,
                        "level": i + 1,
                        "full_path": path,
                        "parent": " > ".join(parts[:i]) if i > 0 else None
                    })
        return {"taxonomy": taxonomy}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/sessions/save-full")
async def save_full_session(payload: Dict[str, Any]):
    session_id = payload.get("id")
    if not session_id:
        raise HTTPException(status_code=400, detail="Missing session id")
    await redis_client.set(f"session:{session_id}", json.dumps(payload))
    await redis_client.sadd("sessions", session_id)
    return {"status": "ok", "id": session_id}


@app.get("/api/sessions")
async def list_sessions():
    sids = await redis_client.smembers("sessions")
    sessions = []
    for sid in sids:
        raw = await redis_client.get(f"session:{sid}")
        if raw:
            sessions.append(json.loads(raw))
    sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)
    return sessions


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    raw = await redis_client.get(f"session:{session_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Session not found")
    return json.loads(raw)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    raw = await redis_client.get(f"session:{session_id}")
    if raw:
        session = json.loads(raw)
        item_ids = session.get("item_ids", [])
        for item_id in item_ids:
            item_raw = await redis_client.get(f"item:{item_id}")
            if item_raw:
                item = json.loads(item_raw)
                fn = item.get("filename")
                if fn:
                    p = MEDIA_DIR / fn
                    if p.exists():
                        p.unlink()
                await redis_client.delete(f"item:{item_id}")
        for ann in session.get("annotators", []):
            await redis_client.delete(f"labels:{session_id}:{ann}")
        await redis_client.delete(f"labels:{session_id}:final")
        await redis_client.delete(f"session:{session_id}")
    await redis_client.srem("sessions", session_id)
    return {"status": "deleted"}


@app.get("/api/items/{item_id}")
async def get_item(item_id: str):
    raw = await redis_client.get(f"item:{item_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Item not found")
    return json.loads(raw)


@app.post("/api/labels/{session_id}/{annotator}")
async def save_labels(session_id: str, annotator: str, payload: Dict[str, List[str]]):
    existing_raw = await redis_client.get(f"labels:{session_id}:{annotator}")
    existing = json.loads(existing_raw) if existing_raw else {}
    existing.update(payload)
    await redis_client.set(f"labels:{session_id}:{annotator}", json.dumps(existing))
    return {"status": "ok"}


@app.get("/api/labels/{session_id}/{annotator}")
async def get_labels(session_id: str, annotator: str):
    raw = await redis_client.get(f"labels:{session_id}:{annotator}")
    if not raw:
        return {}
    return json.loads(raw)


@app.get("/api/sessions/{session_id}/progress")
async def get_progress(session_id: str):
    raw = await redis_client.get(f"session:{session_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Session not found")
    session = json.loads(raw)
    progress = {}
    for ann in session.get("annotators", []):
        lbl_raw = await redis_client.get(f"labels:{session_id}:{ann}")
        lbls = json.loads(lbl_raw) if lbl_raw else {}
        batch = session.get("batches", {}).get(ann, [])
        labeled_count = sum(1 for item_id in batch if item_id in lbls and len(lbls[item_id]) > 0)
        b_total = len(batch)
        progress[ann] = {
            "labeled": labeled_count,
            "total": b_total,
            "pct": math.floor((labeled_count / b_total) * 100) if b_total > 0 else 0
        }
    return progress


@app.get("/api/sessions/{session_id}/conflicts")
async def get_conflicts(session_id: str):
    raw = await redis_client.get(f"session:{session_id}")
    if not raw:
        return {"conflicts": []}
    session = json.loads(raw)
    annotators = session.get("annotators", [])
    item_ids = session.get("item_ids", [])

    all_labels = {}
    for ann in annotators:
        lbl_raw = await redis_client.get(f"labels:{session_id}:{ann}")
        all_labels[ann] = json.loads(lbl_raw) if lbl_raw else {}

    final_labels_raw = await redis_client.get(f"labels:{session_id}:final")
    final_labels = json.loads(final_labels_raw) if final_labels_raw else {}

    conflicts = []
    for item_id in item_ids:
        item_votes = {}
        for ann in annotators:
            if item_id in session.get("batches", {}).get(ann, []):
                item_votes[ann] = all_labels[ann].get(item_id, [])
        if len(item_votes) <= 1:
            continue
        votes_sorted = [sorted(v) for v in item_votes.values()]
        has_conflict = len(set(tuple(v) for v in votes_sorted)) > 1
        if has_conflict:
            details = [{"annotator": ann, "labels": votes} for ann, votes in item_votes.items()]
            name_str, type_str = await get_item_meta(item_id)
            resolved = item_id in final_labels
            conflicts.append({
                "item_id": item_id,
                "name": name_str,
                "type": type_str,
                "details": details,
                "resolved": resolved,
                "final_labels": final_labels.get(item_id, [])
            })
    return {"conflicts": conflicts}


@app.post("/api/sessions/{session_id}/resolve")
async def resolve_conflict(session_id: str, payload: Dict[str, Any]):
    item_id = payload.get("item_id")
    final_labels = payload.get("final_labels", [])
    raw = await redis_client.get(f"labels:{session_id}:final")
    existing = json.loads(raw) if raw else {}
    existing[item_id] = final_labels
    await redis_client.set(f"labels:{session_id}:final", json.dumps(existing))
    return {"status": "ok"}


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, mode: str = "raw"):
    raw = await redis_client.get(f"session:{session_id}")
    if not raw:
        raise HTTPException(status_code=404, detail="Session not found")
    session = json.loads(raw)

    all_annotator_labels = {}
    for ann in session["annotators"]:
        lbl_raw = await redis_client.get(f"labels:{session_id}:{ann}")
        all_annotator_labels[ann] = json.loads(lbl_raw) if lbl_raw else {}

    final_labels_raw = await redis_client.get(f"labels:{session_id}:final")
    final_labels_map = json.loads(final_labels_raw) if final_labels_raw else {}

    rows = []

    if mode == "merged":
        fieldnames = ["item_id", "item_name", "item_type", "final_labels", "agreed_annotators"]
        for item_id in session["item_ids"]:
            name_str, type_str = await get_item_meta(item_id)
            if item_id in final_labels_map:
                resolved_labels = final_labels_map[item_id]
                agreed_users = ["RESOLVED"]
            else:
                votes = {ann: all_annotator_labels[ann].get(item_id, []) for ann in session["annotators"] if item_id in session["batches"].get(ann, [])}
                first_vote = None
                match = True
                for ann, lbls in votes.items():
                    if first_vote is None:
                        first_vote = sorted(lbls)
                    elif first_vote != sorted(lbls):
                        match = False
                        break
                resolved_labels = list(first_vote) if (match and first_vote) else []
                agreed_users = list(votes.keys()) if match else []
            rows.append({
                "item_id": item_id, "item_name": name_str, "item_type": type_str,
                "final_labels": " | ".join(sorted(resolved_labels)), "agreed_annotators": ", ".join(agreed_users) if agreed_users else "None"
            })
    else:
        fieldnames = ["item_id", "item_name", "item_type", "annotator", "labels"]
        for ann in session["annotators"]:
            raw_labels = all_annotator_labels[ann]
            batch = session["batches"].get(ann, [])
            for item_id in batch:
                labels = final_labels_map.get(item_id) or raw_labels.get(item_id, [])
                name_str, type_str = await get_item_meta(item_id)
                rows.append({
                    "item_id": item_id, "item_name": name_str, "item_type": type_str,
                    "annotator": ann, "labels": " | ".join(sorted(labels))
                })

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=multitag_{session_id[:8]}_{mode}.csv"}
    )
