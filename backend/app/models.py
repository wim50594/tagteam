"""
SQLModel table definitions.

NOTE: deliberately NOT using `from __future__ import annotations`.
With PEP 563 deferred evaluation active, SQLAlchemy's relationship()
class-registry resolver receives the literal string "list['ItemRef']"
(including the `list[...]` wrapper) and fails with:
    InvalidRequestError: ... seems to be using a generic class as the
    argument to relationship() ...
Without the future-import, SQLModel/SQLAlchemy correctly strips the
list[...] wrapper and resolves "ItemRef" from the registry.
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel


def utcnow() -> datetime:
    """Naive UTC timestamp.

    Postgres columns created from a plain `datetime` field are
    TIMESTAMP WITHOUT TIME ZONE. asyncpg refuses to bind a
    timezone-aware datetime into such a column ("can't subtract
    offset-naive and offset-aware datetimes"), so we strip tzinfo
    here. All stored timestamps are implicitly UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Users ───────────────────────────────────────────────────

class User(SQLModel, table=True):
    __tablename__ = "users"

    username: str = Field(primary_key=True, max_length=40)
    display_name: str
    role: str = Field(default="annotator")  # "admin" | "annotator"
    hashed_password: str
    created_at: datetime = Field(default_factory=utcnow)


# ── Items (uploaded files / table rows) ────────────────────────

class Item(SQLModel, table=True):
    __tablename__ = "items"

    id: str = Field(primary_key=True)  # uuid4 string
    name: str
    type: str  # "image" | "pdf" | "document" | "text" | "table"
    ext: Optional[str] = None
    filename: Optional[str] = None  # for binary items stored on disk
    content: Optional[str] = None  # for text items
    size: Optional[int] = None

    content_hash: Optional[str] = Field(default=None, index=True)
    source_file: Optional[str] = None
    source_hash: Optional[str] = Field(default=None, index=True)

    # For table rows: arbitrary column -> value mapping.
    data: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    refs: List["ItemRef"] = Relationship(
        back_populates="item", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class ItemRef(SQLModel, table=True):
    """Tracks which sessions reference a given item (for ref-counted GC)."""
    __tablename__ = "item_refs"

    item_id: str = Field(foreign_key="items.id", primary_key=True)
    session_id: str = Field(primary_key=True)

    item: "Item" = Relationship(back_populates="refs")


class TableUpload(SQLModel, table=True):
    """Caches the row items produced for a previously-uploaded table file."""
    __tablename__ = "table_uploads"

    source_hash: str = Field(primary_key=True)
    row_ids: list = Field(sa_column=Column(JSON))
    columns: list = Field(sa_column=Column(JSON))


# ── Sessions ────────────────────────────────────────────────

class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(primary_key=True)
    name: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow, index=True)

    annotators: list = Field(default_factory=list, sa_column=Column(JSON))
    item_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    batches: dict = Field(default_factory=dict, sa_column=Column(JSON))

    # Free-form extra config (kept for forward-compatibility with the
    # previously schema-less payload).
    extra: dict = Field(default_factory=dict, sa_column=Column(JSON))

    labels: List["Label"] = Relationship(
        back_populates="session", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    final_labels: List["FinalLabel"] = Relationship(
        back_populates="session", sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )

    def to_payload(self) -> dict:
        """Reconstruct the legacy-shaped session dict expected by the frontend."""
        payload = dict(self.extra or {})
        payload.update({
            "id": self.id,
            "name": self.name,
            "created_at": self.created_at.isoformat() + "Z" if self.created_at else "",
            "annotators": self.annotators,
            "item_ids": self.item_ids,
            "batches": self.batches,
        })
        return payload


class Label(SQLModel, table=True):
    """Per-annotator labels for a session, stored as item_id -> list[str]."""
    __tablename__ = "labels"

    session_id: str = Field(foreign_key="sessions.id", primary_key=True)
    annotator: str = Field(primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))

    session: "Session" = Relationship(back_populates="labels")


class FinalLabel(SQLModel, table=True):
    """Admin-resolved final labels for a session, item_id -> list[str]."""
    __tablename__ = "final_labels"

    session_id: str = Field(foreign_key="sessions.id", primary_key=True)
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))

    session: "Session" = Relationship(back_populates="final_labels")
