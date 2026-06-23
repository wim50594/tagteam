import os
import pytest_asyncio

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_URL", "")



@pytest_asyncio.fixture
async def setup_db():
    """Recreate tables fresh before each DB test."""
    from app.database import engine
    from sqlmodel import SQLModel
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)


@pytest_asyncio.fixture
async def db(setup_db):
    """Provide a database session for a test (depends on setup_db)."""
    from app.database import async_session_factory
    async with async_session_factory() as session:
        yield session
