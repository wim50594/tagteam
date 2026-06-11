"""
File upload and label parsing routes.
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Awaitable, Callable
from pydantic import BaseModel

import aiofiles
import pandas as pd
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)

import database as db
from auth import UserInDB, get_current_user
from config import get_settings

router = APIRouter(prefix="/api", tags=["upload"])


# ── File-type taxonomy ────────────────────────────────────────

class FileCategory(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    TABLE = "table"
    TEXT = "text"


# Maps each accepted extension to its category. Single source of truth.
EXTENSION_MAP: dict[str, FileCategory] = {
    ".png":  FileCategory.IMAGE,
    ".jpg":  FileCategory.IMAGE,
    ".jpeg": FileCategory.IMAGE,
    ".gif":  FileCategory.IMAGE,
    ".webp": FileCategory.IMAGE,
    ".bmp":  FileCategory.IMAGE,
    ".tiff": FileCategory.IMAGE,
    ".svg":  FileCategory.IMAGE,
    ".pdf":  FileCategory.PDF,
    ".csv":  FileCategory.TABLE,
    ".tsv":  FileCategory.TABLE,
    ".xlsx": FileCategory.TABLE,
    ".xls":  FileCategory.TABLE,
    ".txt":  FileCategory.TEXT,
    ".md":   FileCategory.TEXT,
}

# Plural keys used in the UI / stats dict.
STATS_KEY: dict[FileCategory, str] = {
    FileCategory.IMAGE: "images",
    FileCategory.PDF:   "pdfs",
    FileCategory.TABLE: "tables",
    FileCategory.TEXT:  "texts",
}


class BatchDeleteRequest(BaseModel):
    item_ids: list[str]


def _empty_stats() -> dict[str, int]:
    return {v: 0 for v in STATS_KEY.values()}


def classify(filename: str) -> tuple[str, FileCategory | None]:
    """Returns (lowercased extension, category-or-None)."""
    ext = os.path.splitext(filename)[1].lower()
    return ext, EXTENSION_MAP.get(ext)


# ── Per-file result returned to the frontend ──────────────────

@dataclass
class UploadedFile:
    item_id: str
    name: str
    category: FileCategory
    size: int
    duplicate: bool       # True if content was already known (any project)
    row_count: int = 0    # for tables: number of rows produced

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "name": self.name,
            "category": self.category.value,
            "size": self.size,
            "duplicate": self.duplicate,
            "row_count": self.row_count,
        }


# ── Hash-based deduplication ──────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def _existing_item_for_hash(content_hash: str) -> str | None:
    item_id = await db.get_str(db.key_hash_to_item(content_hash))
    if not item_id:
        return None
    # Make sure the item still exists (could have been GC'd).
    if await db.get_json(db.key_item(item_id)) is None:
        await db.delete_key(db.key_hash_to_item(content_hash))
        return None
    return item_id


async def _register_hash(content_hash: str, item_id: str) -> None:
    await db.set_str(db.key_hash_to_item(content_hash), item_id)


# ── Per-category handlers ─────────────────────────────────────
# Each handler persists the file + item and returns an UploadedFile.
# Tables are special: they yield N items (one per row) and update `columns_set`.

CategoryHandler = Callable[..., Awaitable[list[UploadedFile]]]


async def _handle_binary(
    *,
    content: bytes,
    base_name: str,
    ext: str,
    category: FileCategory,
    item_type: str,       # value persisted in item["type"]
    media_dir,
) -> list[UploadedFile]:
    content_hash = _sha256(content)
    size = len(content)

    existing = await _existing_item_for_hash(content_hash)
    if existing:
        return [UploadedFile(existing, base_name, category, size, duplicate=True)]

    item_id = str(uuid.uuid4())
    stored_name = f"{item_id}{ext}"
    async with aiofiles.open(media_dir / stored_name, "wb") as out:
        await out.write(content)

    await db.set_json(
        db.key_item(item_id),
        {
            "id": item_id,
            "name": base_name,
            "type": item_type,
            "ext": ext,
            "filename": stored_name,
            "content_hash": content_hash,
            "size": size,
        },
    )
    await _register_hash(content_hash, item_id)
    return [UploadedFile(item_id, base_name, category, size, duplicate=False)]


async def _handle_text(*, content: bytes, base_name: str, **_) -> list[UploadedFile]:
    content_hash = _sha256(content)
    size = len(content)

    existing = await _existing_item_for_hash(content_hash)
    if existing:
        return [UploadedFile(existing, base_name, FileCategory.TEXT, size, duplicate=True)]

    item_id = str(uuid.uuid4())
    text = content.decode("utf-8", errors="ignore")
    await db.set_json(
        db.key_item(item_id),
        {
            "id": item_id,
            "name": base_name,
            "type": "text",
            "content": text,
            "content_hash": content_hash,
            "size": size,
        },
    )
    await _register_hash(content_hash, item_id)
    return [UploadedFile(item_id, base_name, FileCategory.TEXT, size, duplicate=False)]


async def _handle_table(
    *,
    content: bytes,
    base_name: str,
    ext: str,
    columns_set: set[str],
    **_,
) -> list[UploadedFile]:
    """Tables: dedup at *file* level. Same file → reuse all previously-created row items."""
    content_hash = _sha256(content)
    size = len(content)

    # Reuse previous rows if this exact file was uploaded before.
    cached = await db.get_json(f"table_rows:{content_hash}")
    if cached:
        for col in cached.get("columns", []):
            columns_set.add(col)
        return [
            UploadedFile(
                row_id, base_name, FileCategory.TABLE, size,
                duplicate=True, row_count=len(cached["row_ids"]),
            )
            for row_id in cached["row_ids"]
        ]

    try:
        if ext in {".xlsx", ".xls"}:
            df = pd.read_excel(io.BytesIO(content))
        else:
            sep = "\t" if ext == ".tsv" else None
            df = pd.read_csv(io.BytesIO(content), sep=sep, engine="python")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse {base_name}: {exc}",
        )

    df = df.where(pd.notnull(df), None)
    row_ids: list[str] = []
    local_cols: set[str] = set()
    for idx, row in df.iterrows():
        row_id = str(uuid.uuid4())
        row_dict = {
            str(k): (str(v) if v is not None else "")
            for k, v in row.to_dict().items()
        }
        local_cols.update(row_dict.keys())
        await db.set_json(
            db.key_item(row_id),
            {
                "id": row_id,
                "name": f"Row#{idx} from {base_name}",
                "type": "table",
                "data": row_dict,
                "source_file": base_name,
                "source_hash": content_hash,
            },
        )
        row_ids.append(row_id)

    columns_set.update(local_cols)
    await db.set_json(
        f"table_rows:{content_hash}",
        {"row_ids": row_ids, "columns": sorted(local_cols)},
    )
    return [
        UploadedFile(
            row_id, base_name, FileCategory.TABLE, size,
            duplicate=False, row_count=len(row_ids),
        )
        for row_id in row_ids
    ]


# ── Universal upload ──────────────────────────────────────────

@router.post("/upload-universal")
async def upload_universal(
    files: list[UploadFile] = File(...),
    _user: Annotated[UserInDB, Depends(get_current_user)] = None,
):
    settings = get_settings()
    media_dir = settings.media_path

    files_meta: list[dict[str, Any]] = []
    item_ids: list[str] = []
    columns_set: set[str] = set()
    stats = _empty_stats()
    skipped: list[dict[str, str]] = []

    for f in files:
        base_name = os.path.basename(f.filename or "")
        if not base_name or base_name.startswith("."):
            continue

        ext, category = classify(base_name)
        if category is None:
            skipped.append({"name": base_name, "reason": f"unsupported extension '{ext}'"})
            continue

        content = await f.read()
        if not content:
            skipped.append({"name": base_name, "reason": "empty file"})
            continue

        try:
            if category is FileCategory.IMAGE:
                produced = await _handle_binary(
                    content=content, base_name=base_name, ext=ext,
                    category=category, item_type="image", media_dir=media_dir,
                )
            elif category is FileCategory.PDF:
                produced = await _handle_binary(
                    content=content, base_name=base_name, ext=ext,
                    category=category, item_type="pdf", media_dir=media_dir,
                )
            elif category is FileCategory.TEXT:
                produced = await _handle_text(content=content, base_name=base_name)
            elif category is FileCategory.TABLE:
                produced = await _handle_table(
                    content=content, base_name=base_name, ext=ext,
                    columns_set=columns_set,
                )
            else:  # pragma: no cover - exhaustive
                continue
        except HTTPException:
            raise
        except Exception as exc:
            skipped.append({"name": base_name, "reason": str(exc)})
            continue

        for uf in produced:
            item_ids.append(uf.item_id)
            files_meta.append(uf.to_dict())
            # FIX: Da wir über jedes Item loopen, erhöhen wir einfach um 1.
            # Verhindert die Multiplikation (3x3=9) bei Tabellenzeilen.
            stats[STATS_KEY[uf.category]] += 1

    return {
        "item_ids": item_ids,
        "files": files_meta,
        "columns": sorted(columns_set),
        "stats": stats,
        "skipped": skipped,
    }


# ── High-Performance Batch Draft Item Removal ──────────────────

@router.post("/items/draft/batch-delete")
async def batch_delete_draft_items(
    req: BatchDeleteRequest,
    _user: Annotated[UserInDB, Depends(get_current_user)],
):
    """
    High-performance batch cleanup for drafts.
    Skips destroying items that are active in other projects (REUSED).
    """
    deleted_count = 0
    detached_count = 0
    source_hashes_to_delete = set()

    for item_id in req.item_ids:
        item = await db.get_json(db.key_item(item_id))
        if not item:
            continue

        ref_count = await db.scard(db.key_item_refs(item_id))
        if ref_count > 0:
            # Reused by another launched project -> skip deletion, count as detached
            detached_count += 1
            continue

        # Clean file from disk
        fn = item.get("filename")
        if fn:
            media_path = get_settings().media_path / fn
            if media_path.exists():
                media_path.unlink()

        content_hash = item.get("content_hash")
        if content_hash:
            await db.delete_key(db.key_hash_to_item(content_hash))

        source_hash = item.get("source_hash")
        if source_hash:
            source_hashes_to_delete.add(source_hash)

        await db.delete_key(db.key_item(item_id))
        await db.delete_key(db.key_item_refs(item_id))
        deleted_count += 1

    for sh in source_hashes_to_delete:
        await db.delete_key(f"table_rows:{sh}")

    return {
        "status": "success", 
        "deleted_count": deleted_count,
        "detached_count": detached_count
    }


# ── Draft item removal ────────────────────────────────────────

@router.delete("/items/{item_id}/draft")
async def delete_draft_item(
    item_id: str,
    _user: Annotated[UserInDB, Depends(get_current_user)],
):
    """
    Safely handles item removal from a draft configuration.
    If the item is REUSED (has active session references), it simply unlinks it
    locally for the client without touching the file or global database registry.
    """
    item = await db.get_json(db.key_item(item_id))
    if not item:
        return {"status": "not_found"}

    ref_count = await db.scard(db.key_item_refs(item_id))
    
    # If other projects use it, do NOT delete it.
    if ref_count > 0:
        return {
            "status": "detached", 
            "message": f"Item kept intact because it is active in {ref_count} other project(s)."
        }

    # If NO other projects are using it, completely scrub it from disk/cache
    fn = item.get("filename")
    if fn:
        media_path = get_settings().media_path / fn
        if media_path.exists():
            media_path.unlink()

    content_hash = item.get("content_hash")
    if content_hash:
        await db.delete_key(db.key_hash_to_item(content_hash))

    source_hash = item.get("source_hash")
    if source_hash:
        await db.delete_key(f"table_rows:{source_hash}")

    await db.delete_key(db.key_item(item_id))
    await db.delete_key(db.key_item_refs(item_id))
    return {"status": "deleted"}


# ── Taxonomy / label parsing ──────────────────────────────────

@router.post("/parse-labels")
async def parse_labels(
    file: UploadFile = File(...),
    has_header: bool = Form(True),
    delimiter: str = Form(""),
    _user: Annotated[UserInDB, Depends(get_current_user)] = None,
):
    content = await file.read()
    fname = (file.filename or "").lower()

    if fname.endswith(".txt"):
        text = content.decode("utf-8", errors="ignore")
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        taxonomy: list[dict] = []
        for line in lines:
            if ">" in line:
                parts = [p.strip() for p in line.split(">") if p.strip()]
            elif ";" in line:
                parts = [p.strip() for p in line.split(";") if p.strip()]
            else:
                parts = [line]
            for i, part in enumerate(parts):
                path = " > ".join(parts[: i + 1])
                if not any(t["full_path"] == path for t in taxonomy):
                    taxonomy.append({
                        "name": part, "level": i + 1, "full_path": path,
                        "parent": " > ".join(parts[:i]) if i > 0 else None,
                    })
        return {"taxonomy": taxonomy}

    try:
        if fname.endswith(".tsv"):
            sep = "\t"
        elif delimiter and delimiter.strip():
            sep = delimiter.strip()
        else:
            sample = content[:2048].decode("utf-8", errors="ignore")
            sep = next((s for s in [",", "\t", ";", "|"] if s in sample), None)

        df = pd.read_csv(
            io.BytesIO(content),
            sep=sep,
            header=0 if has_header else None,
            engine="python",
            dtype=str,
        )
        df = df.where(pd.notnull(df), None)
        taxonomy = []
        for _, row in df.iterrows():
            parts = [
                str(x).strip() for x in row
                if x is not None and str(x).strip() not in ("", "nan", "None")
            ]
            if not parts:
                continue
            for i, part in enumerate(parts):
                path = " > ".join(parts[: i + 1])
                if not any(t["full_path"] == path for t in taxonomy):
                    taxonomy.append({
                        "name": part, "level": i + 1, "full_path": path,
                        "parent": " > ".join(parts[:i]) if i > 0 else None,
                    })
        return {"taxonomy": taxonomy}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
