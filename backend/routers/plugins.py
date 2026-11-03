"""Plugin center administration endpoints."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from routers.admin import verify_admin_key
from services.plugin_service import plugin_service

router = APIRouter()


class PluginSourceRequest(BaseModel):
    github_repo: str = Field(min_length=3, max_length=200)


class PluginInstallRequest(BaseModel):
    tag_name: str = Field(min_length=1, max_length=200)
    plugin_id: str = Field(default="video-world", pattern=r"^[a-z0-9][a-z0-9_-]{1,62}$")


class PluginEnabledRequest(BaseModel):
    enabled: bool


@router.get("/plugins")
async def list_plugins(auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    return {
        "source": plugin_service.get_source(),
        "installed": plugin_service.list_installed(),
        "frontend": plugin_service.list_frontend_plugins(),
    }


@router.get("/plugins/releases")
async def list_plugin_releases(auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    try:
        return {"items": plugin_service.list_releases()}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Plugin release lookup failed: {exc}") from exc


@router.put("/plugins/source")
async def update_plugin_source(data: PluginSourceRequest, auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    try:
        return plugin_service.set_source(data.github_repo)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/plugins/{plugin_id}/enabled")
async def set_plugin_enabled(plugin_id: str, data: PluginEnabledRequest, auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    try:
        result = plugin_service.set_enabled(plugin_id, data.enabled)
        return {**result, **plugin_service.schedule_restart()}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/plugins/{plugin_id}")
async def uninstall_plugin(plugin_id: str, auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    try:
        result = plugin_service.uninstall(plugin_id)
        return {**result, **plugin_service.schedule_restart()}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plugins/{plugin_id}/frontend/{asset_path:path}")
async def get_plugin_frontend_asset(plugin_id: str, asset_path: str):
    try:
        return FileResponse(plugin_service.frontend_file(plugin_id, asset_path))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/plugins/import")
async def import_plugin(file: UploadFile = File(...), auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="Plugin import requires a ZIP file")
    plugin_service.ROOT.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(dir=plugin_service.ROOT, suffix=".zip", delete=False) as target:
        temp_path = target.name
        while chunk := await file.read(1024 * 1024):
            target.write(chunk)
            if target.tell() > plugin_service.MAX_ARCHIVE_BYTES:
                target.close()
                Path(temp_path).unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Plugin archive exceeds allowed size")
    try:
        result = plugin_service.install_archive(Path(temp_path))
        return {**result, **plugin_service.schedule_restart()}
    finally:
        Path(temp_path).unlink(missing_ok=True)


@router.post("/plugins/install")
async def install_plugin(data: PluginInstallRequest, auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator permission required")
    try:
        result = plugin_service.install_release(data.tag_name, data.plugin_id)
        return {**result, **plugin_service.schedule_restart()}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Plugin installation failed: {exc}") from exc
