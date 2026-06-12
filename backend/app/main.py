"""
MultiTag Suite – FastAPI application entry point.
Mounts all routers; handles lifespan events.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import database as db
from auth import ensure_bootstrap_admin
from config import get_settings
from routes.auth_routes import router as auth_router
from routes.session_routes import router as session_router
from routes.upload_routes import router as upload_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    await db.connect()
    await ensure_bootstrap_admin()
    yield
    # Shutdown
    await db.disconnect()


settings = get_settings()

app = FastAPI(
    title="TagTeam API",
    version="2.0.0",
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
app.include_router(session_router)


# ── Utility endpoints ─────────────────────────────────────────
@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "4.0.0"}


@app.get("/api/media/{filename:path}")
async def get_media(filename: str):
    from fastapi import HTTPException
    file_path = settings.media_path / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)
