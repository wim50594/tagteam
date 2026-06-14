"""
File upload and label parsing routes.

File classification
--------------------
Rather than relying purely on the filename extension, files are classified
by inspecting their content:

* `filetype` (magic-byte based, pure Python) identifies images and PDFs.
* ZIP-based containers (including modern Office formats like .docx/.xlsx)
  are detected directly via `zipfile.is_zipfile()`, which is more reliable
  than magic-byte sniffing for small/edge-case ZIP files. A ZIP hit is then
  disambiguated by peeking at `[Content_Types].xml` inside the archive.
* Plain-text formats (csv/tsv/txt/md/json/yaml/...) have no magic bytes,
  so they're identified by extension + a UTF-8 decodability check.
"""
from __future__ import annotations

import hashlib
import io
import os
import uuid
import zipfile
from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Any, Awaitable, Callable

import aiofiles
import filetype
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
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from auth import User, get_current_user
from config import get_settings
from database import cache_delete, cache_key_item, get_session
from models import Item, ItemRef, TableUpload

router = APIRouter(prefix="/api", tags=["upload"])


# ── File-type taxonomy ────────────────────────────────────────

class FileCategory(str, Enum):
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"  # Word/OOXML documents - preview hint only, no text extraction
    TABLE = "table"
    TEXT = "text"


# Plural keys used in the UI / stats dict.
STATS_KEY: dict[FileCategory, str] = {
    FileCategory.IMAGE: "images",
    FileCategory.PDF: "pdfs",
    FileCategory.DOCUMENT: "documents",
    FileCategory.TABLE: "tables",
    FileCategory.TEXT: "texts",
}


def _empty_stats() -> dict[str, int]:
    return {v: 0 for v in STATS_KEY.values()}


# Extensions accepted for plain-text content (no reliable magic bytes).
# Anything here is treated as FileCategory.TEXT if it decodes as UTF-8.
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".tsv", ".json", ".yaml", ".yml"}

# OOXML "Content-Type" markers used to disambiguate ZIP-based Office files.
# https://en.wikipedia.org/wiki/Office_Open_XML
_OOXML_MARKERS: dict[str, tuple[FileCategory, str]] = {
    "spreadsheetml": (FileCategory.TABLE, ".xlsx"),
    "wordprocessingml": (FileCategory.DOCUMENT, ".docx"),
    "presentationml": (FileCategory.DOCUMENT, ".pptx"),
}

# Legacy (pre-OOXML) Office formats. These use the OLE2/CFB binary format,
# which `filetype` recognises directly via magic bytes.
_LEGACY_OFFICE_MIME: dict[str, tuple[FileCategory, str]] = {
    "application/vnd.ms-excel": (FileCategory.TABLE, ".xls"),
    "application/msword": (FileCategory.DOCUMENT, ".doc"),
}


def _classify_zip(content: bytes, ext: str) -> tuple[FileCategory, str] | None:
    """Peek inside a ZIP/OOXML container to tell docx from xlsx etc.

    Returns (category, extension) or None if it's an unsupported/plain ZIP.
    """
    if not zipfile.is_zipfile(io.BytesIO(content)):
        return None

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            try:
                content_types = zf.read("[Content_Types].xml").decode("utf-8", "ignore")
            except KeyError:
                content_types = ""
    except zipfile.BadZipFile:
        return None

    for marker, (category, detected_ext) in _OOXML_MARKERS.items():
        if marker in content_types:
            return category, (ext or detected_ext)

    # OOXML container but content-types didn't match a known marker
    # (e.g. a .pptx, or an unusual variant) -> fall back on the extension
    # if it's one we recognise.
    if ext == ".xlsx":
        return FileCategory.TABLE, ext
    if ext == ".docx":
        return FileCategory.DOCUMENT, ext

    return None


def classify(filename: str, content: bytes) -> tuple[str, FileCategory | None]:
    """Classify file content, falling back to the filename extension.

    Returns (extension-to-store, category-or-None).
    """
    ext = os.path.splitext(filename)[1].lower()

    # 1. ZIP-based containers (incl. modern Office formats) - check first,
    #    since this is more reliable than magic-byte sniffing for OOXML.
    if ext in {".docx", ".xlsx", ".pptx"} or zipfile.is_zipfile(io.BytesIO(content)):
        zip_result = _classify_zip(content, ext)
        if zip_result:
            return zip_result[1], zip_result[0]
        # If the extension strongly suggests OOXML but the zip inspection
        # didn't confirm it, still trust the extension rather than reject.
        if ext == ".xlsx":
            return ext, FileCategory.TABLE
        if ext == ".docx":
            return ext, FileCategory.DOCUMENT
        if zipfile.is_zipfile(io.BytesIO(content)):
            # Plain zip, not a supported container.
            return ext, None

    # 2. Magic-byte detection for images/PDF/legacy Office binary formats.
    kind = filetype.guess(content)
    if kind is not None:
        mime = kind.mime
        if mime.startswith("image/"):
            return ext or f".{kind.extension}", FileCategory.IMAGE
        if mime == "application/pdf":
            return ext or ".pdf", FileCategory.PDF
        if mime in _LEGACY_OFFICE_MIME:
            category, detected_ext = _LEGACY_OFFICE_MIME[mime]
            return ext or detected_ext, category
        # Some other recognised binary format we don't support.
        return ext, None

    # 3. No magic bytes matched -> likely plain text. Validate via extension
    #    + UTF-8 decodability rather than trusting the extension blindly.
    if ext in TEXT_EXTENSIONS:
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return ext, None
        category = FileCategory.TABLE if ext in {".csv", ".tsv"} else FileCategory.TEXT
        return ext, category

    return ext, None


class BatchDeleteRequest(BaseModel):
    item_ids: list[str]


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


async def _existing_item_for_hash(db: AsyncSession, content_hash: str) -> str | None:
    result = await db.exec(select(Item).where(Item.content_hash == content_hash))
    item = result.first()
    return item.id if item else None


# ── Per-category handlers ─────────────────────────────────────
# Each handler persists the file + item and returns an UploadedFile.
# Tables are special: they yield N items (one per row) and update `columns_set`.

CategoryHandler = Callable[..., Awaitable[list[UploadedFile]]]


async def _handle_binary(
    *,
    db: AsyncSession,
    content: bytes,
    base_name: str,
    ext: str,
    category: FileCategory,
    item_type: str,       # value persisted in item.type
    media_dir,
) -> list[UploadedFile]:
    content_hash = _sha256(content)
    size = len(content)

    existing = await _existing_item_for_hash(db, content_hash)
    if existing:
        return [UploadedFile(existing, base_name, category, size, duplicate=True)]

    item_id = str(uuid.uuid4())
    stored_name = f"{item_id}{ext}"
    async with aiofiles.open(media_dir / stored_name, "wb") as out:
        await out.write(content)

    item = Item(
        id=item_id,
        name=base_name,
        type=item_type,
        ext=ext,
        filename=stored_name,
        content_hash=content_hash,
        size=size,
    )
    db.add(item)
    return [UploadedFile(item_id, base_name, category, size, duplicate=False)]


async def _handle_text(
    *, db: AsyncSession, content: bytes, base_name: str, **_
) -> list[UploadedFile]:
    content_hash = _sha256(content)
    size = len(content)

    existing = await _existing_item_for_hash(db, content_hash)
    if existing:
        return [UploadedFile(existing, base_name, FileCategory.TEXT, size, duplicate=True)]

    item_id = str(uuid.uuid4())
    text = content.decode("utf-8", errors="ignore")
    item = Item(
        id=item_id,
        name=base_name,
        type="text",
        content=text,
        content_hash=content_hash,
        size=size,
    )
    db.add(item)
    return [UploadedFile(item_id, base_name, FileCategory.TEXT, size, duplicate=False)]


async def _handle_table(
    *,
    db: AsyncSession,
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
    cached = await db.get(TableUpload, content_hash)
    if cached:
        for col in cached.columns:
            columns_set.add(col)
        return [
            UploadedFile(
                row_id, base_name, FileCategory.TABLE, size,
                duplicate=True, row_count=len(cached.row_ids),
            )
            for row_id in cached.row_ids
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
        db.add(Item(
            id=row_id,
            name=f"Row#{idx} from {base_name}",
            type="table",
            data=row_dict,
            source_file=base_name,
            source_hash=content_hash,
        ))
        row_ids.append(row_id)

    columns_set.update(local_cols)
    db.add(TableUpload(source_hash=content_hash, row_ids=row_ids, columns=sorted(local_cols)))
    return [
        UploadedFile(
            row_id, base_name, FileCategory.TABLE, size,
            duplicate=False, row_count=len(row_ids),
        )
        for row_id in row_ids
    ]


# ── Universal upload ──────────────────────────────────────────

@router.post("/upload/items")
async def upload_universal(
    db: Annotated[AsyncSession, Depends(get_session)],
    files: list[UploadFile] = File(...),
    _user: Annotated[User, Depends(get_current_user)] = None,
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

        content = await f.read()
        if not content:
            skipped.append({"name": base_name, "reason": "empty file"})
            continue

        ext, category = classify(base_name, content)
        if category is None:
            skipped.append({"name": base_name, "reason": f"unsupported file type '{ext or '?'}'"})
            continue

        try:
            if category is FileCategory.IMAGE:
                produced = await _handle_binary(
                    db=db, content=content, base_name=base_name, ext=ext,
                    category=category, item_type="image", media_dir=media_dir,
                )
            elif category is FileCategory.PDF:
                produced = await _handle_binary(
                    db=db, content=content, base_name=base_name, ext=ext,
                    category=category, item_type="pdf", media_dir=media_dir,
                )
            elif category is FileCategory.DOCUMENT:
                produced = await _handle_binary(
                    db=db, content=content, base_name=base_name, ext=ext,
                    category=category, item_type="document", media_dir=media_dir,
                )
            elif category is FileCategory.TEXT:
                produced = await _handle_text(db=db, content=content, base_name=base_name)
            elif category is FileCategory.TABLE:
                produced = await _handle_table(
                    db=db, content=content, base_name=base_name, ext=ext,
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
            # We increment by exactly 1 per produced item, which avoids
            # over-counting (e.g. 3x3=9) for table rows.
            stats[STATS_KEY[uf.category]] += 1

    await db.commit()

    return {
        "item_ids": item_ids,
        "files": files_meta,
        "columns": sorted(columns_set),
        "stats": stats,
        "skipped": skipped,
    }


# ── Batch draft item removal ───────────────────────────────────

@router.post("/items/draft/batch-delete")
async def batch_delete_draft_items(
    req: BatchDeleteRequest,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """
    Batch cleanup for drafts.
    Skips destroying items that are active in other projects (REUSED).
    """
    deleted_count = 0
    detached_count = 0
    source_hashes_to_delete: set[str] = set()

    for item_id in req.item_ids:
        item = await db.get(Item, item_id)
        if not item:
            continue

        result = await db.exec(select(ItemRef).where(ItemRef.item_id == item_id))
        if result.first():
            # Reused by another launched project -> skip deletion, count as detached
            detached_count += 1
            continue

        # Clean file from disk
        if item.filename:
            media_path = get_settings().media_path / item.filename
            if media_path.exists():
                media_path.unlink()

        if item.source_hash:
            source_hashes_to_delete.add(item.source_hash)

        await db.delete(item)
        await cache_delete(cache_key_item(item_id))
        deleted_count += 1

    for sh in source_hashes_to_delete:
        upload = await db.get(TableUpload, sh)
        if upload:
            await db.delete(upload)

    await db.commit()

    return {
        "status": "success",
        "deleted_count": deleted_count,
        "detached_count": detached_count,
    }


# ── Draft item removal ────────────────────────────────────────

@router.delete("/items/{item_id}/draft")
async def delete_draft_item(
    item_id: str,
    _user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
):
    """
    Safely handles item removal from a draft configuration.
    If the item is REUSED (has active session references), it simply unlinks it
    locally for the client without touching the file or global database registry.
    """
    item = await db.get(Item, item_id)
    if not item:
        return {"status": "not_found"}

    result = await db.exec(select(ItemRef).where(ItemRef.item_id == item_id))
    ref_count = len(result.all())

    # If other projects use it, do NOT delete it.
    if ref_count > 0:
        return {
            "status": "detached",
            "message": f"Item kept intact because it is active in {ref_count} other project(s).",
        }

    # If NO other projects are using it, completely scrub it from disk/db/cache
    if item.filename:
        media_path = get_settings().media_path / item.filename
        if media_path.exists():
            media_path.unlink()

    if item.source_hash:
        upload = await db.get(TableUpload, item.source_hash)
        if upload:
            await db.delete(upload)

    await db.delete(item)
    await db.commit()
    await cache_delete(cache_key_item(item_id))
    return {"status": "deleted"}


# ── Taxonomy / label parsing ──────────────────────────────────

@router.post("/upload/labels")
async def parse_labels(
    file: UploadFile = File(...),
    has_header: bool = Form(True),
    delimiter: str = Form(""),
    _user: Annotated[User, Depends(get_current_user)] = None,
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
