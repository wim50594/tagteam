"""
Thin wrappers around SQLModel / SQLAlchemy column operators that Pyright
cannot resolve because model fields are typed as their Python value types
(e.g. ``int``, ``str``) rather than ``InstrumentedAttribute``.

Usage::

    from app._sqlmodel_compat import col_in

    select(User).where(col_in(User.id, user_ids))
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def col_in(
    column: Any,
    values: Iterable[Any],
) -> Any:
    """``column.in_(values)`` – type-checker-safe wrapper."""
    return column.in_(values)  # pyright: ignore[reportAttributeAccessIssue]
