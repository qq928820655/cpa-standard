"""
FastAPI application entrypoint.
"""

import asyncio
import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

# 强制注册关键 MIME 类型，防止某些服务器环境（尤其 Linux）返回 text/plain
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("application/wasm", ".wasm")

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from config import settings, export_config
from database import async_session_maker, init_db
from routers import admin_router, proxy_router, stats_router, auth_router, openai_plus_router
from services import usage_rollup_service

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIST_DIR = BACKEND_DIR.parent / "frontend" / "dist"


async def _periodic_close_stale_image_tasks() -> None:
    """后台定时回收过期图片任务，读取 export_config 获取间隔"""
    from routers.admin import close_stale_running_image_tasks, STALE_TASK_CLEANUP_INTERVAL_DEFAULT

    while True:
        try:
            interval = int(export_config.get("image_stale_task_cleanup_interval_seconds", STALE_TASK_CLEANUP_INTERVAL_DEFAULT))
            interval = max(10, min(interval, 3600))
        except (TypeError, ValueError):
            interval = STALE_TASK_CLEANUP_INTERVAL_DEFAULT

        await asyncio.sleep(interval)

        try:
            async with async_session_maker() as db:
                await close_stale_running_image_tasks(db)
        except Exception as exc:
            logger.warning("periodic_close_stale_image_tasks failed: %s", exc)


async def _periodic_clear_stale_result_meta() -> None:
    """后台定时清空超过 3 小时未回填的结果冗余字段"""
    from routers.admin import clear_stale_result_meta, RESULT_META_CLEANUP_INTERVAL_DEFAULT

    while True:
        try:
            interval = int(export_config.get("image_result_meta_cleanup_interval_seconds", RESULT_META_CLEANUP_INTERVAL_DEFAULT))
            interval = max(60, min(interval, 86400))
        except (TypeError, ValueError):
            interval = RESULT_META_CLEANUP_INTERVAL_DEFAULT

        await asyncio.sleep(interval)

        try:
            async with async_session_maker() as db:
                await clear_stale_result_meta(db)
        except Exception as exc:
            logger.warning("periodic_clear_stale_result_meta failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and tear down application resources."""
    await init_db()
    async with async_session_maker() as session:
        await usage_rollup_service.maintain(session)

    cleanup_task = asyncio.create_task(_periodic_close_stale_image_tasks())
    meta_cleanup_task = asyncio.create_task(_periodic_clear_stale_result_meta())

    print("[CPA] System started")
    print(f"[CPA] Master Key: {settings.master_key}")
    yield
    cleanup_task.cancel()
    meta_cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    try:
        await meta_cleanup_task
    except asyncio.CancelledError:
        pass
    print("[CPA] System stopped")


app = FastAPI(
    title=settings.app_name,
    description="API Key relay service with unified management and proxy endpoints",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_router, prefix="/api/admin", tags=["admin"])
app.include_router(stats_router, prefix="/api/stats", tags=["stats"])
app.include_router(proxy_router, tags=["proxy"])
app.include_router(openai_plus_router, tags=["openai-plus"])


def _guess_media_type(filepath: Path) -> str | None:
    """推断文件 MIME 类型，对 .js/.mjs 强制返回正确类型防止白屏。"""
    suffix = filepath.suffix.lower()
    if suffix in (".js", ".mjs"):
        return "application/javascript"
    guessed, _ = mimetypes.guess_type(str(filepath))
    return guessed


def _serve_frontend_file(request_path: str) -> FileResponse:
    if not FRONTEND_DIST_DIR.exists():
        raise HTTPException(status_code=404, detail="Frontend build not found")

    normalized_path = request_path.strip("/")
    if normalized_path:
        candidate = (FRONTEND_DIST_DIR / normalized_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(FRONTEND_DIST_DIR):
            headers = {"Cache-Control": "no-cache"} if candidate.suffix == ".html" else {}
            media_type = _guess_media_type(candidate)
            return FileResponse(candidate, headers=headers, media_type=media_type)

    return FileResponse(FRONTEND_DIST_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/")
async def root():
    if FRONTEND_DIST_DIR.exists():
        return FileResponse(FRONTEND_DIST_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/{full_path:path}", include_in_schema=False)
async def spa_fallback(full_path: str):
    return _serve_frontend_file(full_path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
