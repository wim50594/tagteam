"""
TagTeams Suite – FastAPI application entry point.
Mounts all routers; handles lifespan events.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.auth import ensure_bootstrap_admin
from app.config import get_settings
from app.database import async_session_factory, connect_cache, disconnect_cache, init_db
from app.routes.auth_routes import router as auth_router
from app.routes.project_routes import router as project_router
from app.routes.upload_routes import router as upload_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    await init_db()
    await connect_cache()
    async with async_session_factory() as session:
        await ensure_bootstrap_admin(session)
    yield
    # Shutdown
    await disconnect_cache()


settings = get_settings()

app = FastAPI(
    title="TagTeams API",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(upload_router)
app.include_router(project_router)


# ── Utility endpoints ─────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": settings.app_version}


@app.get("/api/media/{filename:path}")
async def get_media(filename: str):
    file_path = settings.media_path / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)
