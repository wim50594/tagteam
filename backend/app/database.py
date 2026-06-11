"""
Redis connection management and low-level key helpers.
All keys are centralised here so naming is consistent across routes.
"""
import json
from typing import Any

import redis.asyncio as aioredis

from config import get_settings

# Module-level client; initialised in lifespan.
redis_client: aioredis.Redis | None = None


async def connect() -> None:
    global redis_client
    redis_client = aioredis.from_url(
        get_settings().redis_url, decode_responses=True
    )


async def disconnect() -> None:
    if redis_client:
        await redis_client.close()


def _get() -> aioredis.Redis:
    if redis_client is None:
        raise RuntimeError("Redis not initialised – call connect() first")
    return redis_client


# ── Generic helpers ───────────────────────────────────────────

async def get_json(key: str) -> Any | None:
    raw = await _get().get(key)
    return json.loads(raw) if raw else None


async def set_json(key: str, value: Any) -> None:
    await _get().set(key, json.dumps(value))


async def delete_key(key: str) -> None:
    await _get().delete(key)


async def sadd(key: str, *members: str) -> None:
    await _get().sadd(key, *members)


async def srem(key: str, *members: str) -> int:
    """Returns the number of members actually removed."""
    return await _get().srem(key, *members)


async def smembers(key: str) -> set[str]:
    return await _get().smembers(key)


async def scard(key: str) -> int:
    return await _get().scard(key)


async def get_str(key: str) -> str | None:
    return await _get().get(key)


async def set_str(key: str, value: str) -> None:
    await _get().set(key, value)


# ── Domain key helpers ────────────────────────────────────────

def key_user(username: str) -> str:
    return f"user:{username.lower()}"


def key_item(item_id: str) -> str:
    return f"item:{item_id}"


def key_session(session_id: str) -> str:
    return f"session:{session_id}"


def key_labels(session_id: str, annotator: str) -> str:
    return f"labels:{session_id}:{annotator}"


def key_final_labels(session_id: str) -> str:
    return f"labels:{session_id}:final"


def key_item_refs(item_id: str) -> str:
    """Set of session_ids that reference this item (for ref-counted GC)."""
    return f"item_refs:{item_id}"


def key_hash_to_item(content_hash: str) -> str:
    """SHA-256 of file content → item_id, used for deduplication."""
    return f"hash:{content_hash}"


SET_USERS = "users"
SET_SESSIONS = "sessions"
