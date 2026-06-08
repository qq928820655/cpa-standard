"""
管理接口 - API Key 与模型管理
"""
import asyncio
import base64
import binascii
import hashlib
import hmac
import importlib.util
import ipaddress
import json
import logging
import os
import random
import struct
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, List, Any, TypedDict
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Header, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, func, or_, and_, delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings, export_config, DATA_DIR
from database import get_db, async_session_maker
from routers.models_seed import DEFAULT_MODELS
from services.pool_manager import pool_manager
from services.proxy_service import proxy_service
from services.key_check_task_service import key_check_task_service
from services.proxy_trace_service import proxy_trace_service, normalize_trace_config


router = APIRouter()
logger = logging.getLogger("cpa.image")


def has_psd_enhancement() -> bool:
    """判断 PSD 增强依赖是否可用"""
    return importlib.util.find_spec("services.psd_utils") is not None




class ImageTaskSnapshot(TypedDict, total=False):
    """图片任务快照"""
    id: int
    model: Optional[str]
    started_at: Optional[datetime]


class ImageApiKeySnapshot(TypedDict, total=False):
    """图片 Key 快照"""
    id: Optional[int]
    provider: Optional[str]
    name: Optional[str]
    base_url: Optional[str]


# ============ Pydantic 模型 ============

class ApiKeyCreate(BaseModel):
    """创建 API Key 请求"""
    name: str
    provider: str
    api_key: str
    api_type: Optional[str] = "other"
    base_url: str
    is_active: bool = True
    weight: int = Field(default=1, ge=0)
    enable_proxy: bool = False
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    enable_fake_ip: bool = False
    fake_ip: Optional[str] = None
    supported_models: Optional[List[str]] = None
    remark: Optional[str] = None
    password: Optional[str] = None
    wz_url: Optional[str] = None


class ApiKeyUpdate(BaseModel):
    """更新 API Key 请求"""
    name: Optional[str] = None
    provider: Optional[str] = None
    api_key: Optional[str] = None
    api_type: Optional[str] = None
    base_url: Optional[str] = None
    is_active: Optional[bool] = None
    weight: Optional[int] = Field(default=None, ge=0)
    enable_proxy: Optional[bool] = None
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    enable_fake_ip: Optional[bool] = None
    fake_ip: Optional[str] = None
    supported_models: Optional[List[str]] = None
    remark: Optional[str] = None
    password: Optional[str] = None
    wz_url: Optional[str] = None


class ApiKeyResponse(BaseModel):
    """API Key 响应"""
    id: int
    name: str
    provider: str
    api_key: str
    api_key_masked: str
    api_type: str = "other"
    base_url: str
    is_active: bool
    is_cooled_down: bool
    cooldown_until: Optional[datetime]
    cooldown_remaining_seconds: int
    weight: int
    enable_proxy: bool = False
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    enable_fake_ip: bool = False
    fake_ip: Optional[str] = None
    security_violation_count: int = 0
    last_security_violation: Optional[str] = None
    supported_models: List[str] = Field(default_factory=list)
    remark: Optional[str]
    password: Optional[str] = None
    wz_url: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ApiKeyBatchImportItem(BaseModel):
    name: str
    provider: str
    api_key: str
    api_type: Optional[str] = "other"
    base_url: str
    is_active: bool = True
    weight: Optional[int] = Field(default=None, ge=0)
    enable_proxy: bool = False
    proxy_url: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_password: Optional[str] = None
    enable_fake_ip: bool = False
    fake_ip: Optional[str] = None
    supported_models: Optional[List[str]] = None
    remark: Optional[str] = None
    password: Optional[str] = None
    wz_url: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_wz_url_alias(cls, data: Any):
        if isinstance(data, dict) and data.get("wz_url") is None:
            for alias in ("wzurl", "wzUrl", "web_url", "webUrl"):
                if data.get(alias) is not None:
                    data = dict(data)
                    data["wz_url"] = data.get(alias)
                    break
        return data


class ApiKeyBatchImportRequest(BaseModel):
    items: List[ApiKeyBatchImportItem]


class ApiKeyBatchImportResponse(BaseModel):
    count: int
    items: List[ApiKeyResponse]
    auto_created_model_count: int = 0
    created_count: int = 0
    updated_count: int = 0


class ApiKeyBatchExportResponse(BaseModel):
    count: int
    items: List[ApiKeyBatchImportItem]


class ApiKeyBatchSetActiveRequest(BaseModel):
    key_ids: List[int]
    is_active: bool


class ApiKeyBatchSetActiveResponse(BaseModel):
    count: int
    is_active: bool


class ApiKeyBatchClearCooldownRequest(BaseModel):
    key_ids: List[int]


class ApiKeyBatchClearCooldownResponse(BaseModel):
    count: int


class ApiKeyBatchDeleteResponse(BaseModel):
    count: int


class ApiKeyBatchUpdateModelsRequest(BaseModel):
    scope: str
    provider: Optional[str] = None
    providers: Optional[List[str]] = None
    models: Optional[List[str]] = None
    is_active: Optional[bool] = None
    key_ids: Optional[List[int]] = None
    key_names: Optional[List[str]] = None
    base_url: Optional[str] = None
    weight: Optional[int] = Field(default=None, ge=0)
    supported_models: Optional[List[str]] = None
    new_provider: Optional[str] = None  # 批量变更提供商
    api_type: Optional[str] = None


class ApiKeyBatchUpdateModelsResponse(BaseModel):
    count: int
    scope: str
    provider: Optional[str] = None
    providers: Optional[List[str]] = None
    models: Optional[List[str]] = None
    auto_created_model_count: int = 0


class ApiKeyBatchFakeIpRequest(BaseModel):
    key_ids: List[int]
    enabled: bool


class ApiKeyBatchFakeIpResponse(BaseModel):
    count: int
    enabled: bool


class ApiKeyBatchCheckRequest(BaseModel):
    scope: str
    provider: Optional[str] = None
    providers: Optional[List[str]] = None
    models: Optional[List[str]] = None
    is_active: Optional[bool] = None
    key_ids: Optional[List[int]] = None
    key_names: Optional[List[str]] = None
    target_model: Optional[str] = None


class ApiKeyBatchDeleteRequest(BaseModel):
    key_ids: List[int]


class ApiKeyCheckProbeResult(BaseModel):
    status: str
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    response_time_ms: int
    path: str
    url: str


class ApiKeyCheckItem(BaseModel):
    key_id: int
    name: str
    provider: str
    base_url: str
    status: str
    target_model: Optional[str] = None
    response_time_ms: int
    failure_category: Optional[str] = None
    failure_detail: Optional[str] = None
    address_check: ApiKeyCheckProbeResult
    model_check: Optional[ApiKeyCheckProbeResult] = None


class ApiKeyBatchCheckResponse(BaseModel):
    count: int
    success_count: int
    error_count: int
    scope: str
    provider: Optional[str] = None
    providers: Optional[List[str]] = None
    models: Optional[List[str]] = None
    target_model: Optional[str] = None
    items: List[ApiKeyCheckItem]


class ApiKeyCheckTaskResponse(BaseModel):
    id: int
    scope: str
    provider: Optional[str] = None
    providers: List[str] = Field(default_factory=list)
    models: List[str] = Field(default_factory=list)
    is_active: Optional[bool] = None
    key_ids: List[int] = Field(default_factory=list)
    target_model: str
    status: str
    total_count: int
    completed_count: int
    success_count: int
    error_count: int
    progress_percent: float
    failure_category_stats: dict[str, int] = Field(default_factory=dict)
    provider_stats: dict[str, dict[str, int]] = Field(default_factory=dict)
    model_stats: dict[str, dict[str, int]] = Field(default_factory=dict)
    error_summary: Optional[str] = None
    retry_of_task_id: Optional[int] = None
    report_file_path: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime


class ApiKeyCheckTaskListResponse(BaseModel):
    items: List[ApiKeyCheckTaskResponse]
    total: int
    page: int
    limit: int


class ApiKeyCheckTaskResultListResponse(BaseModel):
    items: List[ApiKeyCheckItem]
    total: int
    page: int
    limit: int


class ApiKeyCheckTaskStatsResponse(BaseModel):
    task: ApiKeyCheckTaskResponse
    status_breakdown: dict[str, int] = Field(default_factory=dict)


class ApiKeySingleCheckRequest(BaseModel):
    target_model: str


class ImageModelOption(BaseModel):
    model: str
    display_name: str
    provider: str = "openai"
    request_formats: List[str] = Field(default_factory=list)
    candidate_request_formats: List[str] = Field(default_factory=list)
    max_count: int = 1
    available_key_count: int = 0
    total_remaining_image_count: Optional[int] = None


class ImageModelListResponse(BaseModel):
    items: List[ImageModelOption]


IMAGE_INPUT_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp"}
IMAGE_INPUT_MAX_COUNT = 4
IMAGE_INPUT_MAX_SIZE_BYTES = 5 * 1024 * 1024
IMAGE_INPUT_DATA_URL_PREFIX = "data:image/"
IMAGE_STORAGE_CONFIG_PATH = DATA_DIR / "image_storage_config.json"
DEFAULT_IMAGE_STORAGE_DIR = DATA_DIR / "image_outputs"
IMAGE_OUTPUT_ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/vnd.adobe.photoshop"}
IMAGE_OUTPUT_EXTENSIONS = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


class ImageInput(BaseModel):
    """图生图输入图片"""
    data_url: str = ""
    image_url: Optional[str] = None
    name: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = Field(default=None, ge=0)


class ImageGenerationRequest(BaseModel):
    model: str
    prompt: str
    size: Optional[str] = None
    quality: Optional[str] = "auto"
    count: int = Field(default=1, ge=1, le=4)
    request_format: Optional[str] = None
    mode: Optional[str] = "text_to_image"
    input_images: Optional[List[ImageInput]] = None


class ImageGenerationValidateRequest(BaseModel):
    api_key_id: int
    model: str
    prompt: Optional[str] = None
    size: Optional[str] = None
    quality: Optional[str] = "high"
    request_format: Optional[str] = None
    probe_only: bool = True
    timeout_seconds: int = Field(default=25, ge=5, le=120)


class ImageGenerationValidateResponse(BaseModel):
    api_key_id: int
    api_key_name: str
    provider: str
    model: str
    status: str
    status_code: Optional[int] = None
    response_time_ms: int
    request_format: str
    path: Optional[str] = None
    image_count: int = 0
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    failure_category: Optional[str] = None
    error_message: Optional[str] = None
    checked_at: datetime


class ImageGenerationResultResponse(BaseModel):
    id: int
    task_id: int
    image_index: int
    api_key_id: Optional[int] = None
    provider: Optional[str] = None
    api_key_name: Optional[str] = None
    model: Optional[str] = None
    status: str
    image_url: Optional[str] = None
    image_base64: Optional[str] = None
    local_path: Optional[str] = None
    local_url: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    file_size_bytes: Optional[int] = None
    duration_ms: int = 0
    error_category: Optional[str] = None
    error_detail: Optional[str] = None
    created_at: datetime
    finished_at: Optional[datetime] = None


class ImageGenerationTaskResponse(BaseModel):
    id: int
    provider: Optional[str] = None
    api_key_id: Optional[int] = None
    api_key_name: Optional[str] = None
    base_url: Optional[str] = None
    model: str
    prompt: str
    request_params: dict = Field(default_factory=dict)
    status: str
    total_count: int
    completed_count: int
    success_count: int
    error_count: int
    duration_ms: int = 0
    failure_category_stats: dict[str, int] = Field(default_factory=dict)
    error_summary: Optional[str] = None
    pending_refresh: bool = False
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    updated_at: datetime
    results: List[ImageGenerationResultResponse] = Field(default_factory=list)


class ImageGenerationTaskListResponse(BaseModel):
    items: List[ImageGenerationTaskResponse]
    total: int
    page: int
    limit: int


class ImageGenerationResultListResponse(BaseModel):
    items: List[ImageGenerationResultResponse]
    total: int
    page: int
    limit: int


class ImageKeyStatsItem(BaseModel):
    api_key_id: int
    api_key_name: str
    provider: str
    model: Optional[str] = None
    weight: Optional[int] = None
    remaining_amount: Optional[float] = None
    remaining_image_count: Optional[int] = None
    total_count: int
    success_count: int
    error_count: int
    success_rate: float
    last_generated_at: Optional[datetime] = None


class ImageKeyStatsResponse(BaseModel):
    items: List[ImageKeyStatsItem]


class ImageStorageConfigResponse(BaseModel):
    storage_dir: str
    default_storage_dir: str


class ImageCapabilityResponse(BaseModel):
    psd_enabled: bool


class ImageStorageConfigUpdate(BaseModel):
    storage_dir: str


class OpenAIPlusQuotaRefreshConfigResponse(BaseModel):
    openai_plus_quota_refresh_concurrency: int
    openai_plus_quota_refresh_timeout_seconds: int
    openai_plus_quota_token_refresh_timeout_seconds: int


class OpenAIPlusQuotaRefreshConfigUpdate(BaseModel):
    openai_plus_quota_refresh_concurrency: int = Field(ge=1, le=20)
    openai_plus_quota_refresh_timeout_seconds: int = Field(ge=5, le=300)
    openai_plus_quota_token_refresh_timeout_seconds: int = Field(ge=5, le=300)


class ImageAutoRefreshConfigResponse(BaseModel):
    image_auto_refresh_delay_seconds: int
    image_auto_refresh_interval_seconds: int
    image_auto_refresh_max_attempts: int


class ImageAutoRefreshConfigUpdate(BaseModel):
    image_auto_refresh_delay_seconds: int = Field(ge=0, le=3600)
    image_auto_refresh_interval_seconds: int = Field(ge=1, le=3600)
    image_auto_refresh_max_attempts: int = Field(ge=1, le=100)


class StaleTaskCleanupConfigResponse(BaseModel):
    image_stale_task_cleanup_interval_seconds: int
    image_history_refresh_interval_seconds: int
    image_result_meta_cleanup_interval_seconds: int


class StaleTaskCleanupConfigUpdate(BaseModel):
    image_stale_task_cleanup_interval_seconds: int = Field(ge=10, le=3600)
    image_history_refresh_interval_seconds: int = Field(ge=1, le=60)
    image_result_meta_cleanup_interval_seconds: int = Field(ge=60, le=86400)


class ImageTaskRefreshByUpstreamRequest(BaseModel):
    upstream_task_id: str


class ImageTaskDeleteRequest(BaseModel):
    delete_files: bool = False


class ImageTaskDeleteResponse(BaseModel):
    task_id: int
    deleted_results: int
    deleted_files: int


class ImageFileActionResponse(BaseModel):
    ok: bool
    path: str


class QuickCreateModelsRequest(BaseModel):
    names: List[str]


class QuickCreateModelsResponse(BaseModel):
    count: int
    created_count: int
    existing_count: int
    items: List[str]
    created_items: List[str]


class ModelCatalogBase(BaseModel):
    model_id: str
    display_name: str
    provider: str
    protocol: str = "openai_chat"
    input_price: float = 0
    output_price: float = 0
    is_active: bool = True
    is_recommended: bool = False
    supports_codex: bool = False
    supports_claudecode: bool = False
    supports_gemini: bool = False
    aliases: Optional[List[str]] = None
    remark: Optional[str] = None


class ModelCatalogCreate(ModelCatalogBase):
    pass


class ModelCatalogUpdate(BaseModel):
    display_name: Optional[str] = None
    provider: Optional[str] = None
    protocol: Optional[str] = None
    input_price: Optional[float] = None
    output_price: Optional[float] = None
    is_active: Optional[bool] = None
    is_recommended: Optional[bool] = None
    supports_codex: Optional[bool] = None
    supports_claudecode: Optional[bool] = None
    supports_gemini: Optional[bool] = None
    aliases: Optional[List[str]] = None
    remark: Optional[str] = None


class ModelCatalogResponse(BaseModel):
    id: int
    model_id: str
    display_name: str
    provider: str
    protocol: str
    input_price: float
    output_price: float
    is_active: bool
    is_recommended: bool
    supports_codex: bool
    supports_claudecode: bool
    supports_gemini: bool
    aliases: List[str] = Field(default_factory=list)
    remark: Optional[str]
    created_at: datetime
    updated_at: datetime


class ModelCatalogBatchImportItem(ModelCatalogBase):
    pass


class ModelCatalogBatchImportRequest(BaseModel):
    items: List[ModelCatalogBatchImportItem]


class ModelCatalogBatchImportResponse(BaseModel):
    count: int
    items: List[ModelCatalogResponse]
    created_count: int


class ModelCatalogBatchExportResponse(BaseModel):
    count: int
    items: List[ModelCatalogBatchImportItem]


class ExportConfigResponse(BaseModel):
    api_key: str
    homepage: str
    claude_endpoint: str
    codex_endpoint: str
    gemini_endpoint: str
    default_model: str
    default_names: dict
    usage_guide_default_content: str


class MasterKeyResponse(BaseModel):
    """Master Key 响应"""
    master_key: str


class KeyCooldownConfigResponse(BaseModel):
    rate_limit_cooldown_seconds: int
    auth_failure_cooldown_seconds: int
    upstream_error_cooldown_seconds: int
    cloudflare_524_auto_continue_providers: List[str] = []


class KeyCooldownConfigUpdate(BaseModel):
    rate_limit_cooldown_seconds: int = Field(ge=0)
    auth_failure_cooldown_seconds: int = Field(ge=0)
    upstream_error_cooldown_seconds: int = Field(ge=0)
    cloudflare_524_auto_continue_providers: List[str] = []


class ProxyTimeoutConfigResponse(BaseModel):
    proxy_request_timeout_seconds: int
    proxy_stream_connect_timeout_seconds: int
    proxy_stream_first_byte_timeout_seconds: int
    proxy_stream_read_timeout_seconds: int


class ProxyTimeoutConfigUpdate(BaseModel):
    proxy_request_timeout_seconds: int = Field(ge=1)
    proxy_stream_connect_timeout_seconds: int = Field(ge=1)
    proxy_stream_first_byte_timeout_seconds: int = Field(ge=1)
    proxy_stream_read_timeout_seconds: int = Field(ge=1)


class ContentGuardConfigResponse(BaseModel):
    enabled: bool = False
    check_ads: bool = True
    check_dangerous_code: bool = True
    block_on_violation: bool = True
    ad_action: str = "record"
    auto_disable_key: bool = False
    disable_threshold: int = Field(default=3, ge=1, le=100)
    downgrade_weight: int = Field(default=1, ge=0, le=100)
    ad_patterns: List[str] = Field(default_factory=list)
    ad_regex_patterns: List[str] = Field(default_factory=list)
    dangerous_patterns: List[str] = Field(default_factory=list)


class ContentGuardConfigUpdate(ContentGuardConfigResponse):
    pass


class ContentGuardEventResponse(BaseModel):
    id: int
    api_key_id: int
    key_name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    path: Optional[str] = None
    category: str
    rule: Optional[str] = None
    snippet: Optional[str] = None
    explanation: Optional[str] = None
    action: str
    created_at: datetime

    class Config:
        from_attributes = True


class ContentGuardEventListResponse(BaseModel):
    items: List[ContentGuardEventResponse]
    total: int
    page: int
    limit: int


class KeyCheckDefaultConfigResponse(BaseModel):
    default_key_check_model: str


class KeyCheckDefaultConfigUpdate(BaseModel):
    default_key_check_model: Optional[str] = None


class KeyCheckShortcutModelsResponse(BaseModel):
    default_key_check_model: str
    shortcut_models: List[str] = Field(default_factory=list)


class KeyCheckShortcutModelsUpdate(BaseModel):
    default_key_check_model: Optional[str] = None
    shortcut_models: List[str] = Field(default_factory=list)


class ProxySessionConfigResponse(BaseModel):
    enabled: bool
    ttl_seconds: int
    binding_count: int


class ProxySessionConfigUpdate(BaseModel):
    enabled: bool
    ttl_seconds: int = Field(ge=1)


class ProviderListResponse(BaseModel):
    items: List[str]


class ProviderModelPriorityKeyOption(BaseModel):
    id: int
    name: str
    provider: str
    supported_models: List[str] = Field(default_factory=list)
    weight: int
    is_active: bool


class ProviderModelPriorityItem(BaseModel):
    model: str
    model_display_name: str
    provider: str
    priority_key_id: Optional[int] = None
    priority_key_name: Optional[str] = None
    priority_key_active: bool = False
    priority_key_weight: int = 0
    priority_key_supported: bool = False
    binding_enabled: bool = False
    issue: Optional[str] = None


class ProviderModelPriorityListResponse(BaseModel):
    provider: str
    items: List[ProviderModelPriorityItem]


class ProviderModelPriorityUpsertRequest(BaseModel):
    provider: str
    model: str
    key_id: int


class ProviderModelPriorityClearRequest(BaseModel):
    provider: str
    model: str


class ProviderModelPriorityMutationResponse(BaseModel):
    provider: str
    model: str
    priority_key_id: Optional[int] = None


class ProviderModelMappingItem(BaseModel):
    id: int
    provider: str
    provider_model: str
    real_model: str
    enabled: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProviderModelMappingListResponse(BaseModel):
    items: List[ProviderModelMappingItem]
    total: int


class ProviderModelMappingCreate(BaseModel):
    provider: str
    provider_model: str
    real_model: str
    enabled: bool = True
    remark: Optional[str] = None


class ProviderModelMappingImportRequest(BaseModel):
    items: List[ProviderModelMappingCreate]


class ProviderModelMappingImportResponse(BaseModel):
    count: int
    created_count: int = 0
    updated_count: int = 0
    items: List[ProviderModelMappingItem]


class ProviderModelMappingExportResponse(BaseModel):
    count: int
    items: List[ProviderModelMappingCreate]


class ProviderModelMappingUpdate(BaseModel):
    provider: str
    provider_model: str
    real_model: str
    enabled: bool = True
    remark: Optional[str] = None


class ProviderModelMappingMutationResponse(BaseModel):
    item: ProviderModelMappingItem


# ============ 认证依赖 ============

async def verify_admin_key(authorization: str = Header(None), db=Depends(get_db)):
    """验证管理员权限（支持 Master Key 或 Session Token）

    返回: {"is_admin": bool, "user_id": int|None}
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="缺少认证信息")

    token = authorization.replace("Bearer ", "").strip()

    # 优先尝试 Master Key
    if token == settings.master_key:
        return {"is_admin": True, "user_id": None}

    # 尝试 Session Token
    from sqlalchemy import select
    from models.admin_session import AdminSession
    from models.admin_user import AdminUser

    result = await db.execute(
        select(AdminSession).where(AdminSession.token == token)
    )
    session = result.scalar_one_or_none()

    if session is not None and not session.is_expired():
        from datetime import datetime, timedelta
        session.expires_at = datetime.utcnow() + timedelta(days=7)
        await db.commit()

        user_result = await db.execute(select(AdminUser).where(AdminUser.id == session.user_id))
        user = user_result.scalar_one_or_none()
        if user:
            return {"is_admin": user.is_admin, "user_id": user.id}
        return {"is_admin": False, "user_id": session.user_id}

    if session is not None:
        await db.delete(session)
        await db.commit()

    raise HTTPException(status_code=403, detail="无效的认证凭证")


# ============ 辅助函数 ============

def mask_api_key(api_key: str) -> str:
    """脱敏 API Key，只显示前8位和后4位"""
    if len(api_key) <= 12:
        return "*" * len(api_key)
    return f"{api_key[:8]}...{api_key[-4:]}"


def dumps_json_list(value: Optional[List[str]]) -> Optional[str]:
    """序列化字符串数组"""
    cleaned = normalize_string_list(value)
    return json.dumps(cleaned, ensure_ascii=False) if cleaned else None


def loads_json_list(value: Optional[str]) -> List[str]:
    """反序列化字符串数组"""
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return normalize_string_list(data)


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    """规范化可选文本"""
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalize_api_type(value: Any) -> str:
    """规范化 API 类型"""
    if not isinstance(value, str):
        return "other"
    normalized = value.strip().lower()
    if normalized in {"newapi", "sub2api", "other"}:
        return normalized
    return "other"


def is_newapi_key(api_key: Any) -> bool:
    """判断 Key 是否为 New API 类型"""
    return normalize_api_type(getattr(api_key, "api_type", None)) == "newapi"


def is_sub2api_key(api_key: Any) -> bool:
    """判断 Key 是否为 sub2api 类型"""
    return normalize_api_type(getattr(api_key, "api_type", None)) == "sub2api"


def resolve_web_origin(web_url: str) -> str:
    """解析网页访问 origin"""
    normalized = (web_url or "").strip().rstrip("/")
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    parsed = urlsplit(f"https://{normalized}")
    return f"{parsed.scheme}://{parsed.netloc}"


def get_nested_value(data: Any, paths: list[list[str]]) -> Any:
    """按多个候选路径读取嵌套字段"""
    for path in paths:
        current = data
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if current not in (None, ""):
            return current
    return None


def parse_sub2api_token(data: Any) -> Optional[str]:
    """解析 sub2api 登录 token"""
    value = get_nested_value(
        data,
        [
            ["data", "access_token"],
            ["data", "accessToken"],
            ["data", "token"],
            ["data", "jwt"],
            ["access_token"],
            ["accessToken"],
            ["token"],
            ["jwt"],
        ],
    )
    return str(value).strip() if value not in (None, "") else None


def parse_sub2api_user(data: Any) -> dict:
    """解析 sub2api 用户信息"""
    for path in (["data", "user"], ["data"], ["user"]):
        value = get_nested_value(data, [path])
        if isinstance(value, dict):
            return value
    return {}


def parse_sub2api_balance(user: dict, fallback_user: dict) -> tuple[float, float]:
    """解析 sub2api 余额"""
    balance_value = get_nested_value(user, [["balance"], ["quota"], ["remaining_quota"], ["credit"], ["credits"]])
    if balance_value in (None, ""):
        balance_value = get_nested_value(fallback_user, [["balance"], ["quota"], ["remaining_quota"], ["credit"], ["credits"]])
    used_value = get_nested_value(user, [["used_quota"], ["used"], ["used_balance"], ["used_credit"], ["used_credits"]]) or 0

    balance = float(balance_value)
    used = float(used_value or 0)
    if "quota" in user or "remaining_quota" in user:
        balance = balance / 500000
    if "used_quota" in user:
        used = used / 500000
    return round(balance, 6), round(used, 6)


def build_proxy_fields(data: Any) -> dict:
    """构建独立代理字段"""
    enable_proxy = bool(getattr(data, "enable_proxy", False))
    if not enable_proxy:
        return {
            "enable_proxy": False,
            "proxy_url": None,
            "proxy_username": None,
            "proxy_password": None,
        }

    proxy_url = normalize_optional_text(getattr(data, "proxy_url", None))
    if not proxy_url:
        raise HTTPException(status_code=400, detail="启用独立代理时代理地址不能为空")

    return {
        "enable_proxy": True,
        "proxy_url": proxy_url,
        "proxy_username": normalize_optional_text(getattr(data, "proxy_username", None)),
        "proxy_password": normalize_optional_text(getattr(data, "proxy_password", None)),
    }


def build_fake_ip_fields(data: Any) -> dict:
    """构建伪装 IP 字段"""
    enable_fake_ip = bool(getattr(data, "enable_fake_ip", False))
    if not enable_fake_ip:
        return {
            "enable_fake_ip": False,
            "fake_ip": None,
        }

    fake_ip = normalize_optional_text(getattr(data, "fake_ip", None))
    if not fake_ip:
        raise HTTPException(status_code=400, detail="启用伪装 IP 时请输入 IP 地址")

    try:
        ipaddress.ip_address(fake_ip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="伪装 IP 必须是合法的 IPv4 或 IPv6 地址") from exc

    return {
        "enable_fake_ip": True,
        "fake_ip": fake_ip,
    }


def import_item_needs_auto_fake_ip(data: Any) -> bool:
    """判断导入项是否需要自动分配伪装 IP"""
    return bool(getattr(data, "enable_fake_ip", False)) and not normalize_optional_text(getattr(data, "fake_ip", None))


def build_import_fake_ip_fields(data: Any, generated_fake_ip: Optional[str] = None) -> dict:
    """构建导入场景伪装 IP 字段"""
    if not import_item_needs_auto_fake_ip(data):
        return build_fake_ip_fields(data)

    fake_ip = normalize_optional_text(generated_fake_ip)
    if not fake_ip:
        raise HTTPException(status_code=400, detail="启用伪装 IP 时请输入 IP 地址")

    try:
        ipaddress.ip_address(fake_ip)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="伪装 IP 必须是合法的 IPv4 或 IPv6 地址") from exc

    return {
        "enable_fake_ip": True,
        "fake_ip": fake_ip,
    }


def build_batch_fake_ips(count: int) -> list[str]:
    """为批量操作生成低关联的伪装 IP"""
    if count <= 0:
        return []

    ten_capacity = 256 * 256 * 245
    private_172_capacity = 16 * 256 * 245
    private_192_capacity = 256 * 245
    test_net_capacity = 3 * 245
    total_capacity = ten_capacity + private_172_capacity + private_192_capacity + test_net_capacity
    if count > total_capacity:
        raise HTTPException(status_code=400, detail="单次开启独立 fake IP 的 Key 数量过多")

    test_net_prefixes = ((192, 0, 2), (198, 51, 100), (203, 0, 113))

    def map_candidate(index: int) -> str:
        if index < ten_capacity:
            fourth = 10 + (index % 245)
            value = index // 245
            third = value % 256
            second = value // 256
            return f"10.{second}.{third}.{fourth}"

        index -= ten_capacity
        if index < private_172_capacity:
            fourth = 10 + (index % 245)
            value = index // 245
            third = value % 256
            second = 16 + (value // 256)
            return f"172.{second}.{third}.{fourth}"

        index -= private_172_capacity
        if index < private_192_capacity:
            fourth = 10 + (index % 245)
            third = index // 245
            return f"192.168.{third}.{fourth}"

        index -= private_192_capacity
        fourth = 10 + (index % 245)
        prefix = test_net_prefixes[index // 245]
        return f"{prefix[0]}.{prefix[1]}.{prefix[2]}.{fourth}"

    return [map_candidate(index) for index in random.sample(range(total_capacity), count)]



def to_response(key: Any) -> ApiKeyResponse:
    """转换为响应模型"""
    cooldown_until = pool_manager.get_key_cooldown_until(key.id)
    cooldown_remaining_seconds = pool_manager.get_key_cooldown_remaining_seconds(key.id)
    return ApiKeyResponse(
        id=key.id,
        name=key.name,
        provider=key.provider,
        api_key=key.api_key,
        api_key_masked=mask_api_key(key.api_key),
        api_type=normalize_api_type(getattr(key, "api_type", None)),
        base_url=key.base_url,
        is_active=key.is_active,
        is_cooled_down=cooldown_remaining_seconds > 0,
        cooldown_until=cooldown_until,
        cooldown_remaining_seconds=cooldown_remaining_seconds,
        weight=key.weight,
        enable_proxy=bool(getattr(key, "enable_proxy", False)),
        proxy_url=getattr(key, "proxy_url", None),
        proxy_username=getattr(key, "proxy_username", None),
        proxy_password=getattr(key, "proxy_password", None),
        enable_fake_ip=bool(getattr(key, "enable_fake_ip", False)),
        fake_ip=getattr(key, "fake_ip", None),
        security_violation_count=int(getattr(key, "security_violation_count", 0) or 0),
        last_security_violation=getattr(key, "last_security_violation", None),
        supported_models=loads_json_list(getattr(key, "supported_models", None)),
        remark=key.remark,
        password=getattr(key, "password", None),
        wz_url=getattr(key, "wz_url", None),
        created_at=key.created_at,
        updated_at=key.updated_at,
    )


def build_key_import_item(key: Any) -> ApiKeyBatchImportItem:
    """构建 Key 导出项"""
    return ApiKeyBatchImportItem(
        name=key.name,
        provider=key.provider,
        api_key=key.api_key,
        api_type=normalize_api_type(getattr(key, "api_type", None)),
        base_url=key.base_url,
        is_active=key.is_active,
        weight=key.weight,
        enable_proxy=bool(getattr(key, "enable_proxy", False)),
        proxy_url=getattr(key, "proxy_url", None),
        proxy_username=getattr(key, "proxy_username", None),
        proxy_password=getattr(key, "proxy_password", None),
        enable_fake_ip=bool(getattr(key, "enable_fake_ip", False)),
        fake_ip=getattr(key, "fake_ip", None),
        supported_models=loads_json_list(getattr(key, "supported_models", None)) or None,
        remark=key.remark,
        password=getattr(key, "password", None),
        wz_url=getattr(key, "wz_url", None),
    )


def to_model_response(model: Any) -> ModelCatalogResponse:
    """转换模型响应"""
    return ModelCatalogResponse(
        id=model.id,
        model_id=model.model_id,
        display_name=model.display_name,
        provider=model.provider,
        protocol=model.protocol,
        input_price=model.input_price,
        output_price=model.output_price,
        is_active=model.is_active,
        is_recommended=model.is_recommended,
        supports_codex=model.supports_codex,
        supports_claudecode=model.supports_claudecode,
        supports_gemini=getattr(model, "supports_gemini", False),
        aliases=loads_json_list(model.aliases),
        remark=model.remark,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def build_model_import_item(model: Any) -> ModelCatalogBatchImportItem:
    """构建模型导出项"""
    return ModelCatalogBatchImportItem(
        model_id=model.model_id,
        display_name=model.display_name,
        provider=model.provider,
        protocol=model.protocol,
        input_price=model.input_price,
        output_price=model.output_price,
        is_active=model.is_active,
        is_recommended=model.is_recommended,
        supports_codex=model.supports_codex,
        supports_claudecode=model.supports_claudecode,
        supports_gemini=getattr(model, "supports_gemini", False),
        aliases=loads_json_list(model.aliases),
        remark=model.remark,
    )


def normalize_string_list(values: Optional[List[str]]) -> List[str]:
    """规范化字符串数组"""
    if not values:
        return []

    normalized = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        item = value.strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized


def normalize_int_list(values: Optional[List[int]]) -> List[int]:
    """规范化整数数组"""
    if not values:
        return []

    normalized = []
    seen = set()
    for value in values:
        try:
            item = int(value)
        except (TypeError, ValueError):
            continue
        if item <= 0 or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def build_key_identity_filters(api_key_model: Any, key_ids: Optional[List[int]], key_names: Optional[List[str]]) -> list[Any]:
    """构建 Key ID 与名称筛选条件"""
    filters = []
    key_id_values = normalize_int_list(key_ids)
    key_name_values = normalize_string_list(key_names)
    if key_id_values:
        filters.append(api_key_model.id.in_(key_id_values))
    filters.extend(api_key_model.name.ilike(f"%{name}%") for name in key_name_values)
    return filters


def normalize_model_name(value: Optional[str]) -> str:
    """规范化单个模型名称"""
    if not isinstance(value, str):
        return ""
    return value.strip().lower()


def split_model_mapping_values(value: Optional[str]) -> list[str]:
    """按中英文逗号拆分模型映射字段"""
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


def build_provider_model_mapping_fields(data: Any) -> dict:
    """构建提供商模型映射字段"""
    provider = normalize_optional_text(getattr(data, "provider", None))
    provider_model = normalize_optional_text(getattr(data, "provider_model", None))
    real_model = normalize_optional_text(getattr(data, "real_model", None))
    if not provider:
        raise HTTPException(status_code=400, detail="provider 不能为空")
    if not provider_model:
        raise HTTPException(status_code=400, detail="原始模型不能为空")
    if not real_model:
        raise HTTPException(status_code=400, detail="映射模型不能为空")

    provider_model_normalized = normalize_model_name(provider_model)
    real_model_normalized = normalize_model_name(real_model)
    if not provider_model_normalized or not real_model_normalized:
        raise HTTPException(status_code=400, detail="模型名称不能为空")

    return {
        "provider": provider,
        "provider_model": provider_model,
        "provider_model_normalized": provider_model_normalized,
        "real_model": real_model,
        "real_model_normalized": real_model_normalized,
        "enabled": bool(getattr(data, "enabled", True)),
        "remark": normalize_optional_text(getattr(data, "remark", None)),
    }


def to_provider_model_mapping_item(mapping: Any) -> ProviderModelMappingItem:
    """转换提供商模型映射响应"""
    return ProviderModelMappingItem(
        id=mapping.id,
        provider=mapping.provider,
        provider_model=mapping.provider_model,
        real_model=mapping.real_model,
        enabled=bool(mapping.enabled),
        remark=mapping.remark,
        created_at=mapping.created_at,
        updated_at=mapping.updated_at,
    )


def build_provider_model_mapping_import_item(mapping: Any) -> ProviderModelMappingCreate:
    """构建提供商模型映射导入导出项"""
    return ProviderModelMappingCreate(
        provider=mapping.provider,
        provider_model=mapping.provider_model,
        real_model=mapping.real_model,
        enabled=bool(mapping.enabled),
        remark=mapping.remark,
    )


def expand_provider_model_mapping_import_item(data: Any) -> list[dict]:
    """展开一行多模型映射导入项"""
    provider = normalize_optional_text(getattr(data, "provider", None))
    if not provider:
        raise HTTPException(status_code=400, detail="provider 不能为空")
    provider_models = split_model_mapping_values(getattr(data, "provider_model", None))
    real_models = split_model_mapping_values(getattr(data, "real_model", None))
    if not provider_models:
        raise HTTPException(status_code=400, detail="原始模型不能为空")
    if not real_models:
        raise HTTPException(status_code=400, detail="映射模型不能为空")
    if len(provider_models) != len(real_models):
        raise HTTPException(status_code=400, detail=f"provider={provider} 的原始模型数量与映射模型数量不一致")

    items = []
    for provider_model, real_model in zip(provider_models, real_models):
        item = ProviderModelMappingCreate(
            provider=provider,
            provider_model=provider_model,
            real_model=real_model,
            enabled=bool(getattr(data, "enabled", True)),
            remark=normalize_optional_text(getattr(data, "remark", None)),
        )
        items.append(build_provider_model_mapping_fields(item))
    return items


def persist_export_config() -> None:
    """持久化导出配置"""
    from config import EXPORT_CONFIG_PATH

    EXPORT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXPORT_CONFIG_PATH.write_text(
        json.dumps(export_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def infer_provider(model_name: str) -> str:
    """根据模型名称推断提供商"""
    text = model_name.lower()
    rules = [
        ("claude", "claude"),
        ("gpt", "openai"),
        ("gemini", "google"),
        ("grok", "xAI"),
        ("deepseek", "deepseek"),
        ("qwen", "qwen"),
        ("minimax", "minimax"),
        ("kimi", "Moonshot"),
        ("llama", "Meta"),
        ("glm", "智谱"),
    ]
    for keyword, provider in rules:
        if keyword in text:
            return provider
    return "custom"


def infer_protocol(provider: str) -> str:
    """根据提供商推断协议"""
    return "anthropic_messages" if provider == "claude" else "openai_chat"


def build_quick_model_data(model_name: str) -> ModelCatalogCreate:
    """构建快捷模型数据"""
    provider = infer_provider(model_name)
    return ModelCatalogCreate(
        model_id=model_name,
        display_name=model_name,
        provider=provider,
        protocol=infer_protocol(provider),
        input_price=0,
        output_price=0,
        is_active=True,
        is_recommended=False,
        supports_codex=True,
        supports_claudecode=True,
        supports_gemini=True,
        aliases=[],
        remark=None,
    )


def apply_rule_fields(model: Any, model_name: str):
    """按规则更新除价格外的模型字段"""
    provider = infer_provider(model_name)
    model.provider = provider
    model.protocol = infer_protocol(provider)
    model.supports_codex = True
    model.supports_claudecode = True
    model.supports_gemini = True


async def prune_model_catalog_to_key_support(db: AsyncSession) -> int:
    """按当前 Key 支持模型修剪模型广场"""
    from models import ApiKey, ModelCatalog

    keys_result = await db.execute(select(ApiKey.supported_models))
    supported_model_ids: set[str] = set()
    has_wildcard_key = False
    for value in keys_result.scalars().all():
        key_model_ids = loads_json_list(value)
        if not key_model_ids:
            has_wildcard_key = True
            continue
        supported_model_ids.update(key_model_ids)

    export_config["model_seed_enabled"] = False
    persist_export_config()

    if has_wildcard_key:
        return 0
    if not supported_model_ids:
        result = await db.execute(sql_delete(ModelCatalog))
        return int(result.rowcount or 0)

    result = await db.execute(
        sql_delete(ModelCatalog).where(ModelCatalog.model_id.notin_(supported_model_ids))
    )
    return int(result.rowcount or 0)


async def ensure_models_exist(db: AsyncSession, model_names: Optional[List[str]]) -> tuple[List[str], List[str]]:
    """确保模型存在，不存在则自动创建"""
    from models import ModelCatalog

    normalized_names = normalize_string_list(model_names)
    if not normalized_names:
        return [], []

    result = await db.execute(
        select(ModelCatalog).where(ModelCatalog.model_id.in_(normalized_names))
    )
    existing = {
        item.model_id.lower(): item.model_id
        for item in result.scalars().all()
    }

    created_names = []
    created = []
    for model_name in normalized_names:
        if model_name.lower() in existing:
            continue
        data = build_quick_model_data(model_name)
        model = ModelCatalog(
            model_id=data.model_id,
            display_name=data.display_name,
            provider=data.provider,
            protocol=data.protocol,
            input_price=data.input_price,
            output_price=data.output_price,
            is_active=data.is_active,
            is_recommended=data.is_recommended,
            supports_codex=data.supports_codex,
            supports_claudecode=data.supports_claudecode,
            supports_gemini=data.supports_gemini,
            aliases=dumps_json_list(data.aliases),
            remark=data.remark,
        )
        db.add(model)
        created.append(model)
        created_names.append(model_name)
        existing[model_name.lower()] = model_name

    if created:
        await db.commit()

    return normalized_names, created_names


async def list_provider_priority_items(db: AsyncSession, provider: str) -> list[ProviderModelPriorityItem]:
    """查询指定 provider 的模型优先 Key 列表"""
    from models import ApiKey, ModelCatalog, ProviderModelPriority

    provider_value = provider.strip()
    if not provider_value:
        raise HTTPException(status_code=400, detail="provider 不能为空")

    models_result = await db.execute(
        select(ModelCatalog)
        .where(ModelCatalog.provider == provider_value)
        .order_by(ModelCatalog.is_recommended.desc(), ModelCatalog.model_id.asc())
    )
    model_rows = list(models_result.scalars().all())

    keys_result = await db.execute(
        select(ApiKey)
        .where(ApiKey.provider == provider_value)
        .order_by(ApiKey.id.asc())
    )
    provider_keys = list(keys_result.scalars().all())
    key_map = {int(item.id): item for item in provider_keys}

    bindings_result = await db.execute(
        select(ProviderModelPriority)
        .where(ProviderModelPriority.provider == provider_value)
        .order_by(ProviderModelPriority.model.asc())
    )
    binding_map = {
        normalize_model_name(item.model): item
        for item in bindings_result.scalars().all()
        if normalize_model_name(item.model)
    }

    model_entries: dict[str, dict[str, str]] = {}
    for model in model_rows:
        normalized = normalize_model_name(model.model_id)
        if not normalized:
            continue
        model_entries[normalized] = {
            "model": model.model_id,
            "display_name": model.display_name or model.model_id,
        }

    for key in provider_keys:
        for supported_model in loads_json_list(getattr(key, "supported_models", None)):
            normalized = normalize_model_name(supported_model)
            if not normalized or normalized in model_entries:
                continue
            model_entries[normalized] = {
                "model": supported_model,
                "display_name": supported_model,
            }

    for normalized, binding in binding_map.items():
        if normalized in model_entries:
            continue
        raw_model = (getattr(binding, "model", "") or "").strip()
        if not raw_model:
            continue
        model_entries[normalized] = {
            "model": raw_model,
            "display_name": raw_model,
        }

    items: list[ProviderModelPriorityItem] = []
    for normalized in sorted(model_entries.keys()):
        model_entry = model_entries[normalized]
        binding = binding_map.get(normalized)
        bound_key = key_map.get(int(getattr(binding, "key_id", 0) or 0)) if binding else None
        binding_enabled = bool(getattr(binding, "enabled", False)) if binding else False
        priority_key_supported = bool(bound_key and pool_manager.key_supports_model(bound_key, model_entry["model"]))

        issue = None
        if binding_enabled:
            if not bound_key:
                issue = "绑定的 Key 不存在"
            elif not getattr(bound_key, "is_active", False):
                issue = "绑定的 Key 已关闭"
            elif int(getattr(bound_key, "weight", 0) or 0) <= 0:
                issue = "绑定的 Key 权重为 0"
            elif not priority_key_supported:
                issue = "绑定的 Key 不支持该模型"

        items.append(
            ProviderModelPriorityItem(
                model=model_entry["model"],
                model_display_name=model_entry["display_name"],
                provider=provider_value,
                priority_key_id=int(bound_key.id) if bound_key else None,
                priority_key_name=getattr(bound_key, "name", None) if bound_key else None,
                priority_key_active=bool(getattr(bound_key, "is_active", False)) if bound_key else False,
                priority_key_weight=int(getattr(bound_key, "weight", 0) or 0) if bound_key else 0,
                priority_key_supported=priority_key_supported,
                binding_enabled=binding_enabled,
                issue=issue,
            )
        )

    return items


async def build_provider_priority_key_options(db: AsyncSession, provider: str) -> list[ProviderModelPriorityKeyOption]:
    """查询指定 provider 的 Key 候选项"""
    from models import ApiKey

    provider_value = provider.strip()
    if not provider_value:
        return []

    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.provider == provider_value)
        .order_by(ApiKey.id.asc())
    )
    return [
        ProviderModelPriorityKeyOption(
            id=int(item.id),
            name=item.name,
            provider=item.provider,
            supported_models=loads_json_list(getattr(item, "supported_models", None)),
            weight=int(getattr(item, "weight", 0) or 0),
            is_active=bool(getattr(item, "is_active", False)),
        )
        for item in result.scalars().all()
    ]


async def validate_provider_priority_target(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    key_id: int,
) -> tuple[str, str, Any]:
    """校验 provider-model 优先 Key 保存目标"""
    normalized_provider = provider.strip() if isinstance(provider, str) else ""
    normalized_model = model.strip() if isinstance(model, str) else ""
    if not normalized_provider:
        raise HTTPException(status_code=400, detail="provider 不能为空")
    if not normalized_model:
        raise HTTPException(status_code=400, detail="model 不能为空")

    key = await pool_manager.get_key_by_id(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    if getattr(key, "provider", None) != normalized_provider:
        raise HTTPException(status_code=400, detail="所选 Key 与 provider 不一致")
    if not pool_manager.key_supports_model(key, normalized_model):
        raise HTTPException(status_code=400, detail="所选 Key 不支持该模型")

    return normalized_provider, normalized_model, key


async def upsert_provider_priority_binding(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
    key_id: int,
) -> tuple[str, str]:
    """保存 provider-model 优先 Key 绑定"""
    from models import ProviderModelPriority

    provider_value, model_value, _ = await validate_provider_priority_target(
        db,
        provider=provider,
        model=model,
        key_id=key_id,
    )
    normalized_model = normalize_model_name(model_value)

    result = await db.execute(
        select(ProviderModelPriority).where(
            ProviderModelPriority.provider == provider_value,
            ProviderModelPriority.model_normalized == normalized_model,
        )
    )
    binding = result.scalar_one_or_none()
    if binding:
        binding.model = model_value
        binding.model_normalized = normalized_model
        binding.key_id = key_id
        binding.enabled = True
        binding.updated_at = datetime.utcnow()
    else:
        db.add(
            ProviderModelPriority(
                provider=provider_value,
                model=model_value,
                model_normalized=normalized_model,
                key_id=key_id,
                enabled=True,
            )
        )

    await db.commit()
    return provider_value, model_value


async def clear_provider_priority_binding(
    db: AsyncSession,
    *,
    provider: str,
    model: str,
) -> tuple[str, str, bool]:
    """清空 provider-model 优先 Key 绑定"""
    from models import ProviderModelPriority

    provider_value = provider.strip() if isinstance(provider, str) else ""
    model_value = model.strip() if isinstance(model, str) else ""
    normalized_model = normalize_model_name(model_value)
    if not provider_value:
        raise HTTPException(status_code=400, detail="provider 不能为空")
    if not model_value:
        raise HTTPException(status_code=400, detail="model 不能为空")

    result = await db.execute(
        select(ProviderModelPriority).where(
            ProviderModelPriority.provider == provider_value,
            ProviderModelPriority.model_normalized == normalized_model,
        )
    )
    binding = result.scalar_one_or_none()
    if not binding:
        return provider_value, model_value, False

    await db.delete(binding)
    await db.commit()
    return provider_value, model_value, True


async def list_target_keys_for_batch_check(db: AsyncSession, data: ApiKeyBatchCheckRequest) -> tuple[list[Any], list[str]]:
    """按批量检测条件查询目标 Key"""
    from models import ApiKey

    if data.scope not in {"filtered", "selected"}:
        raise HTTPException(status_code=400, detail="无效的检测范围")

    query = select(ApiKey)
    if data.scope == "filtered":
        providers = normalize_string_list(data.providers)
        if not providers and data.provider:
            providers = [data.provider]
        if providers:
            query = query.where(ApiKey.provider.in_(providers))
        identity_filters = build_key_identity_filters(ApiKey, data.key_ids, data.key_names)
        if identity_filters:
            query = query.where(or_(*identity_filters))
        if data.is_active is not None:
            query = query.where(ApiKey.is_active == data.is_active)
    else:
        key_ids = data.key_ids or []
        if not key_ids:
            raise HTTPException(status_code=400, detail="按勾选项检测时 key_ids 不能为空")
        query = query.where(ApiKey.id.in_(key_ids))

    result = await db.execute(query)
    keys = list(result.scalars().all())
    if not keys:
        raise HTTPException(status_code=404, detail="未找到可检测的 Key")

    models_filter = normalize_string_list(data.models)
    if data.scope == "filtered" and models_filter:
        keys = [
            key for key in keys
            if any(pool_manager.key_supports_model(key, model) for model in models_filter)
        ]
        if not keys:
            raise HTTPException(status_code=404, detail="未找到可检测的 Key")

    return keys, models_filter


def build_api_key_check_item(key: Any, result: dict) -> ApiKeyCheckItem:
    """构建单项检测响应"""
    address_result = result.get("address_check") or {}
    model_result = result.get("model_check") or None

    return ApiKeyCheckItem(
        key_id=key.id,
        name=key.name,
        provider=key.provider,
        base_url=key.base_url,
        status=result.get("status") or "error",
        target_model=result.get("target_model"),
        response_time_ms=int(result.get("response_time_ms") or 0),
        failure_category=result.get("failure_category"),
        failure_detail=result.get("failure_detail"),
        address_check=ApiKeyCheckProbeResult(
            status=address_result.get("status") or "error",
            status_code=address_result.get("status_code"),
            error_message=address_result.get("error_message"),
            response_time_ms=int(address_result.get("response_time_ms") or 0),
            path=address_result.get("path") or "v1/models",
            url=address_result.get("url") or key.base_url,
        ),
        model_check=ApiKeyCheckProbeResult(
            status=model_result.get("status") or "error",
            status_code=model_result.get("status_code"),
            error_message=model_result.get("error_message"),
            response_time_ms=int(model_result.get("response_time_ms") or 0),
            path=model_result.get("path") or "",
            url=model_result.get("url") or key.base_url,
        ) if model_result else None,
    )


def load_json_object(value: Optional[str]) -> dict:
    """反序列化对象"""
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def get_default_image_storage_dir() -> Path:
    """获取默认图片存储目录"""
    return DEFAULT_IMAGE_STORAGE_DIR.resolve()


def normalize_storage_dir(value: str) -> Path:
    """规范化并校验图片存储目录"""
    storage_dir = normalize_optional_text(value)
    if not storage_dir:
        raise HTTPException(status_code=400, detail="图片存储目录不能为空")

    path = Path(storage_dir).expanduser()
    if not path.is_absolute():
        path = (DATA_DIR / path).resolve()
    else:
        path = path.resolve()

    try:
        path.mkdir(parents=True, exist_ok=True)
        probe_file = path / ".cpa_write_probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"图片存储目录不可写：{exc}") from exc

    return path


def load_image_storage_dir() -> Path:
    """读取图片存储目录配置"""
    default_dir = get_default_image_storage_dir()
    if not IMAGE_STORAGE_CONFIG_PATH.exists():
        return normalize_storage_dir(str(default_dir))

    try:
        data = json.loads(IMAGE_STORAGE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return normalize_storage_dir(str(default_dir))

    configured_dir = data.get("storage_dir") if isinstance(data, dict) else None
    try:
        return normalize_storage_dir(str(configured_dir or default_dir))
    except HTTPException:
        return normalize_storage_dir(str(default_dir))


def save_image_storage_dir(path: Path) -> None:
    """保存图片存储目录配置"""
    IMAGE_STORAGE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    IMAGE_STORAGE_CONFIG_PATH.write_text(
        json.dumps({"storage_dir": str(path)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def guess_image_extension(mime_type: Optional[str]) -> str:
    """根据图片类型推断扩展名"""
    return IMAGE_OUTPUT_EXTENSIONS.get((mime_type or "").lower(), ".png")


def parse_data_image_base64(value: str, fallback_mime_type: Optional[str]) -> tuple[bytes, str]:
    """解析输出图片 base64"""
    content = value.strip()
    mime_type = (fallback_mime_type or "image/png").lower()
    if content.startswith("data:image/"):
        header, separator, encoded = content.partition(",")
        if separator != "," or not encoded:
            raise ValueError("图片 data URL 格式不正确")
        meta_parts = header.split(";")
        mime_type = meta_parts[0].replace("data:", "", 1).lower()
        content = encoded

    if mime_type not in IMAGE_OUTPUT_ALLOWED_MIME_TYPES:
        mime_type = "image/png"

    return base64.b64decode(content, validate=True), mime_type


def parse_image_size(content: bytes, mime_type: Optional[str]) -> tuple[Optional[int], Optional[int]]:
    """解析常见图片尺寸"""
    current_mime_type = (mime_type or "").lower()
    try:
        if (current_mime_type == "image/png" or content.startswith(b"\x89PNG\r\n\x1a\n")) and len(content) >= 24:
            width, height = struct.unpack(">II", content[16:24])
            return int(width), int(height)

        if current_mime_type in {"image/jpeg", "image/jpg"} or content.startswith(b"\xff\xd8"):
            index = 2
            while index + 9 < len(content):
                if content[index] != 0xFF:
                    index += 1
                    continue
                marker = content[index + 1]
                index += 2
                if marker in {0xD8, 0xD9}:
                    continue
                if index + 2 > len(content):
                    break
                segment_length = struct.unpack(">H", content[index:index + 2])[0]
                if segment_length < 2 or index + segment_length > len(content):
                    break
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    if segment_length >= 7:
                        height, width = struct.unpack(">HH", content[index + 3:index + 7])
                        return int(width), int(height)
                index += segment_length

        if (current_mime_type == "image/webp" or content.startswith(b"RIFF")) and len(content) >= 30 and content[8:12] == b"WEBP":
            index = 12
            while index + 8 <= len(content):
                chunk_type = content[index:index + 4]
                chunk_size = struct.unpack("<I", content[index + 4:index + 8])[0]
                data_start = index + 8
                data_end = min(data_start + chunk_size, len(content))
                chunk = content[data_start:data_end]
                if chunk_type == b"VP8X" and len(chunk) >= 10:
                    width = 1 + int.from_bytes(chunk[4:7], "little")
                    height = 1 + int.from_bytes(chunk[7:10], "little")
                    return width, height
                if chunk_type == b"VP8 " and len(chunk) >= 10:
                    width = struct.unpack("<H", chunk[6:8])[0] & 0x3FFF
                    height = struct.unpack("<H", chunk[8:10])[0] & 0x3FFF
                    return int(width), int(height)
                if chunk_type == b"VP8L" and len(chunk) >= 5 and chunk[0] == 0x2F:
                    bits = int.from_bytes(chunk[1:5], "little")
                    width = (bits & 0x3FFF) + 1
                    height = ((bits >> 14) & 0x3FFF) + 1
                    return width, height
                index = data_start + chunk_size + (chunk_size % 2)
    except (struct.error, ValueError, IndexError):
        return None, None

    return None, None


def _save_input_image_file(task_id: int, index: int, data_url: str) -> Optional[str]:
    """将图生图上传的 data URL 参考图保存到本地文件，返回绝对路径"""
    try:
        content = data_url.strip()
        header, _, encoded = content.partition(",")
        if not encoded:
            return None
        meta_parts = header.split(";")
        mime_type = meta_parts[0].replace("data:", "", 1).lower() if meta_parts else "image/png"
        ext = guess_image_extension(mime_type)
        storage_dir = load_image_storage_dir()
        filename = f"input-{int(task_id)}-{int(index)}{ext}"
        filepath = storage_dir / filename
        filepath.write_bytes(base64.b64decode(encoded))
        return str(filepath.resolve())
    except Exception:
        return None


def safe_image_output_path(task_id: int, image_index: int, mime_type: Optional[str]) -> Path:
    """构建图片输出路径"""
    storage_dir = load_image_storage_dir()
    extension = guess_image_extension(mime_type)
    base_path = storage_dir / f"task-{int(task_id)}-{int(image_index)}{extension}"
    if not base_path.exists():
        return base_path

    suffix = 2
    while True:
        candidate = storage_dir / f"task-{int(task_id)}-{int(image_index)}-{suffix}{extension}"
        if not candidate.exists():
            return candidate
        suffix += 1


def save_output_image_file(task_id: int, image_index: int, image: dict) -> dict:
    """保存输出图片到本地"""
    content = None
    mime_type = (image.get("mime_type") or "image/png").lower()

    image_base64 = image.get("image_base64")
    if image_base64:
        content, mime_type = parse_data_image_base64(str(image_base64), mime_type)
    else:
        image_url = normalize_optional_text(image.get("image_url"))
        if not image_url or not image_url.startswith(("http://", "https://")):
            return {}
        request = urllib.request.Request(image_url, headers={"User-Agent": "CPA/1.0"})
        with urllib.request.urlopen(request, timeout=10) as response:
            response_mime_type = (response.headers.get_content_type() or "").lower()
            if response_mime_type in IMAGE_OUTPUT_ALLOWED_MIME_TYPES:
                mime_type = response_mime_type
            content = response.read(20 * 1024 * 1024 + 1)
            if len(content) > 20 * 1024 * 1024:
                raise ValueError("图片文件超过 20MB")

    if not content:
        return {}

    output_path = safe_image_output_path(task_id, image_index, mime_type)
    output_path.write_bytes(content)
    width, height = parse_image_size(content, mime_type)
    return {
        "local_path": str(output_path),
        "file_size_bytes": output_path.stat().st_size,
        "mime_type": mime_type,
        "width": width,
        "height": height,
    }


async def persist_output_image_file(task_id: int, image_index: int, image: dict) -> dict:
    """异步保存输出图片到本地"""
    try:
        return await asyncio.to_thread(save_output_image_file, task_id, image_index, image)
    except Exception:
        return {}


def apply_saved_image_file(row: Any, saved_file: dict) -> None:
    """应用已保存图片文件信息"""
    if not saved_file:
        return
    row.local_path = saved_file.get("local_path")
    row.file_size_bytes = saved_file.get("file_size_bytes")
    row.mime_type = saved_file.get("mime_type") or row.mime_type or "image/png"
    row.width = row.width or saved_file.get("width")
    row.height = row.height or saved_file.get("height")


def image_result_file_token(result_id: Any, local_path: Optional[str]) -> Optional[str]:
    """生成图片结果文件访问令牌"""
    if not local_path:
        return None
    message = f"{int(result_id)}:{local_path}".encode("utf-8")
    return hmac.new(settings.master_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def image_result_file_url(result_id: Any, local_path: Optional[str]) -> Optional[str]:
    """生成图片结果本地访问地址"""
    token = image_result_file_token(result_id, local_path)
    if not token:
        return None
    return f"/api/admin/image/results/{int(result_id)}/file?token={token}"


def guess_local_image_media_type(row: Any, path: Path) -> str:
    """推断本地图片响应类型"""
    mime_type = normalize_optional_text(getattr(row, "mime_type", None))
    if mime_type in IMAGE_OUTPUT_ALLOWED_MIME_TYPES:
        return mime_type
    extension = path.suffix.lower()
    if extension in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if extension == ".webp":
        return "image/webp"
    return "image/png"


def normalize_image_output_text(value: Any) -> Optional[str]:
    """规范化图片输出文本"""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def get_snapshot_value(source: Any, key: str, default: Any = None) -> Any:
    """从快照或对象读取值"""
    if isinstance(source, dict):
        return source.get(key, default)
    return getattr(source, key, default)


def build_api_key_snapshot(api_key: Any) -> ImageApiKeySnapshot:
    """生成图片 Key 快照"""
    return {
        "id": get_snapshot_value(api_key, "id"),
        "provider": get_snapshot_value(api_key, "provider"),
        "name": get_snapshot_value(api_key, "name"),
        "api_type": normalize_api_type(get_snapshot_value(api_key, "api_type")),
        "base_url": get_snapshot_value(api_key, "base_url"),
    }


async def finish_image_task_with_error(
    db: AsyncSession,
    task: Any,
    api_key: Any,
    *,
    error_category: str,
    error_detail: str,
    result_meta: Optional[dict] = None,
    count_key_failure: bool = False,
    task_snapshot: Optional[dict] = None,
    api_key_snapshot: Optional[dict] = None,
) -> tuple[Any, list[Any]]:
    """将图片任务按指定错误收尾"""
    from models import ImageGenerationTaskResult

    task_snapshot = dict(task_snapshot or {})
    api_key_snapshot = dict(api_key_snapshot or {})
    try:
        task_id = int(task_snapshot["id"])
        task_model = task_snapshot.get("model")
        task_started_at = task_snapshot.get("started_at")
        api_key_id = api_key_snapshot.get("id")
        api_key_provider = api_key_snapshot.get("provider")
        api_key_name = api_key_snapshot.get("name")
        await db.rollback()
        task = await db.get(type(task), task_id)
        if not task:
            raise HTTPException(status_code=502, detail=error_detail)
    except HTTPException:
        raise
    except Exception as rollback_error:
        logger.exception(
            "image_generation_finish_error_rollback_failed task_id=%s error=%s",
            task_snapshot.get("id"),
            str(rollback_error) or rollback_error.__class__.__name__,
        )
        raise HTTPException(
            status_code=502,
            detail=f"图片任务收尾失败：{str(rollback_error) or rollback_error.__class__.__name__}",
        ) from rollback_error

    finished_at = datetime.utcnow()
    duration_ms = calculate_duration_ms(task_started_at, finished_at)
    row = ImageGenerationTaskResult(
        task_id=task_id,
        image_index=1,
        api_key_id=api_key_id,
        provider=api_key_provider,
        api_key_name=api_key_name,
        model=task_model,
        status="error",
        error_category=error_category,
        error_detail=error_detail,
        duration_ms=duration_ms,
        result_meta_json=json.dumps(result_meta or {"error": error_detail}, ensure_ascii=False, default=str),
        created_at=finished_at,
        started_at=task_started_at,
        finished_at=finished_at,
        updated_at=finished_at,
    )
    try:
        db.add(row)
        task.status = "error"
        task.completed_count = 1
        task.success_count = 0
        task.error_count = 1
        task.failure_category_stats_json = json.dumps({error_category: 1}, ensure_ascii=False)
        task.error_summary = error_detail
        task.duration_ms = duration_ms
        task.finished_at = finished_at
        task.updated_at = finished_at
        if count_key_failure and api_key_id is not None:
            await upsert_image_key_model_stats(
                db,
                api_key_snapshot,
                task_model,
                total_delta=1,
                success_delta=0,
                error_delta=1,
                generated_at=finished_at,
            )
        await db.commit()
    except Exception as commit_error:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"图片生成失败，任务状态保存失败：{str(commit_error) or commit_error.__class__.__name__}") from commit_error

    if count_key_failure and api_key_id is not None:
        try:
            from models import ApiKey

            fresh_key = await db.get(ApiKey, int(api_key_id))
            if fresh_key:
                _, failure_providers = await apply_image_failure_policy(db, fresh_key)
                await db.commit()
                for p in failure_providers:
                    pool_manager.reset_index(p)
        except Exception:
            await db.rollback()

    try:
        await db.refresh(task)
        await db.refresh(row)
    except Exception as refresh_error:
        logger.exception(
            "image_generation_error_refresh_failed task_id=%s key_id=%s error=%s",
            task_id,
            api_key_id,
            str(refresh_error) or refresh_error.__class__.__name__,
        )
    return task, [row]


async def finish_image_task_with_internal_error(
    db: AsyncSession,
    task: Any,
    api_key: Any,
    error: Exception,
    *,
    task_snapshot: Optional[dict] = None,
    api_key_snapshot: Optional[dict] = None,
) -> tuple[Any, list[Any]]:
    """将图片任务收尾为内部错误"""
    original_error = str(error) or error.__class__.__name__
    task_snapshot = dict(task_snapshot or {})
    api_key_snapshot = dict(api_key_snapshot or {})
    task_id = int(task_snapshot.get("id") or task.id)
    task_model = task_snapshot.get("model")
    if task_model is None:
        task_model = getattr(task, "model", None)
    logger.exception(
        "image_generation_internal_error task_id=%s key_id=%s provider=%s model=%s error=%s",
        task_id,
        api_key_snapshot.get("id"),
        api_key_snapshot.get("provider"),
        task_model,
        original_error,
    )
    return await finish_image_task_with_error(
        db,
        task,
        api_key,
        error_category="internal_error",
        error_detail=f"CPA 图片结果处理失败：{original_error}",
        result_meta={"error": original_error},
        count_key_failure=True,
        task_snapshot=task_snapshot,
        api_key_snapshot=api_key_snapshot,
    )


def extract_upstream_task_from_meta(value: Optional[str]) -> dict:
    """从图片结果元数据中提取上游任务信息"""
    data = load_json_object(value)
    if isinstance(data.get("upstream_task"), dict):
        return data["upstream_task"]
    task_info = {}
    for key in (
        "task_id",
        "taskId",
        "generation_id",
        "generationId",
        "request_id",
        "requestId",
        "id",
        "status_url",
        "statusUrl",
        "polling_url",
        "pollingUrl",
        "poll_url",
        "pollUrl",
        "result_url",
        "resultUrl",
        "output_url",
        "outputUrl",
        "status",
        "state",
    ):
        if data.get(key):
            task_info[key] = data[key]
    if task_info.get("taskId") and not task_info.get("task_id"):
        task_info["task_id"] = task_info["taskId"]
    if task_info.get("generationId") and not task_info.get("generation_id"):
        task_info["generation_id"] = task_info["generationId"]
    if task_info.get("requestId") and not task_info.get("request_id"):
        task_info["request_id"] = task_info["requestId"]
    if task_info.get("statusUrl") and not task_info.get("status_url"):
        task_info["status_url"] = task_info["statusUrl"]
    if task_info.get("pollingUrl") and not task_info.get("polling_url"):
        task_info["polling_url"] = task_info["pollingUrl"]
    if task_info.get("pollUrl") and not task_info.get("poll_url"):
        task_info["poll_url"] = task_info["pollUrl"]
    if task_info.get("resultUrl") and not task_info.get("result_url"):
        task_info["result_url"] = task_info["resultUrl"]
    if task_info.get("outputUrl") and not task_info.get("output_url"):
        task_info["output_url"] = task_info["outputUrl"]
    if task_info.get("polling_url") and not task_info.get("status_url"):
        task_info["status_url"] = task_info["polling_url"]
    if task_info.get("poll_url") and not task_info.get("status_url"):
        task_info["status_url"] = task_info["poll_url"]
    if task_info.get("output_url") and not task_info.get("result_url"):
        task_info["result_url"] = task_info["output_url"]
    return task_info


IMAGE_TIMEOUT_AUTO_REFRESH_DELAY_SECONDS = 60
IMAGE_TIMEOUT_AUTO_REFRESH_INTERVAL_SECONDS = 30
IMAGE_TIMEOUT_AUTO_REFRESH_MAX_ATTEMPTS = 10


def coerce_int_config(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    """读取整数配置并限制范围"""
    try:
        current = int(value)
    except (TypeError, ValueError):
        current = default
    return min(max(current, minimum), maximum)


def get_image_auto_refresh_config() -> ImageAutoRefreshConfigResponse:
    """获取图片自动回填配置"""
    return ImageAutoRefreshConfigResponse(
        image_auto_refresh_delay_seconds=coerce_int_config(
            export_config.get("image_auto_refresh_delay_seconds"),
            IMAGE_TIMEOUT_AUTO_REFRESH_DELAY_SECONDS,
            minimum=0,
            maximum=3600,
        ),
        image_auto_refresh_interval_seconds=coerce_int_config(
            export_config.get("image_auto_refresh_interval_seconds"),
            IMAGE_TIMEOUT_AUTO_REFRESH_INTERVAL_SECONDS,
            minimum=1,
            maximum=3600,
        ),
        image_auto_refresh_max_attempts=coerce_int_config(
            export_config.get("image_auto_refresh_max_attempts"),
            IMAGE_TIMEOUT_AUTO_REFRESH_MAX_ATTEMPTS,
            minimum=1,
            maximum=100,
        ),
    )


STALE_TASK_CLEANUP_INTERVAL_DEFAULT = 60
HISTORY_REFRESH_INTERVAL_DEFAULT = 5
RESULT_META_CLEANUP_INTERVAL_DEFAULT = 1800


def get_stale_task_cleanup_config() -> StaleTaskCleanupConfigResponse:
    """获取过期任务回收配置"""
    return StaleTaskCleanupConfigResponse(
        image_stale_task_cleanup_interval_seconds=coerce_int_config(
            export_config.get("image_stale_task_cleanup_interval_seconds"),
            STALE_TASK_CLEANUP_INTERVAL_DEFAULT,
            minimum=10,
            maximum=3600,
        ),
        image_history_refresh_interval_seconds=coerce_int_config(
            export_config.get("image_history_refresh_interval_seconds"),
            HISTORY_REFRESH_INTERVAL_DEFAULT,
            minimum=1,
            maximum=60,
        ),
        image_result_meta_cleanup_interval_seconds=coerce_int_config(
            export_config.get("image_result_meta_cleanup_interval_seconds"),
            RESULT_META_CLEANUP_INTERVAL_DEFAULT,
            minimum=60,
            maximum=86400,
        ),
    )


async def auto_refresh_cloudflare_timeout_image_task(task_id: int) -> None:
    """自动回填 Cloudflare 超时后的图片任务"""
    from database import async_session_maker
    from models import ImageGenerationTask, ImageGenerationTaskResult

    refresh_config = get_image_auto_refresh_config()
    await asyncio.sleep(refresh_config.image_auto_refresh_delay_seconds)
    for attempt in range(1, refresh_config.image_auto_refresh_max_attempts + 1):
        try:
            async with async_session_maker() as db:
                task = await db.get(ImageGenerationTask, task_id)
                if not task or task.status != "running":
                    return

                result = await db.execute(
                    select(ImageGenerationTaskResult)
                    .where(ImageGenerationTaskResult.task_id == task.id)
                    .order_by(ImageGenerationTaskResult.image_index.asc(), ImageGenerationTaskResult.id.asc())
                )
                rows = list(result.scalars().all())
                if any(row.status == "success" for row in rows):
                    return

                refreshed_task, refreshed_rows, refreshed, message = await refresh_image_task_from_task_log(db, task)
                if refreshed and any(row.status == "success" for row in refreshed_rows):
                    logger.info(
                        "image_timeout_auto_refresh_success task_id=%s attempt=%s message=%s",
                        task_id,
                        attempt,
                        message,
                    )
                    return

                if attempt >= refresh_config.image_auto_refresh_max_attempts:
                    finished_at = datetime.utcnow()
                    failure_message = message or f"Cloudflare 超时后自动查询上游任务日志 {refresh_config.image_auto_refresh_max_attempts} 次仍未找到图片结果。"
                    existing_rows_result = await db.execute(
                        select(ImageGenerationTaskResult)
                        .where(ImageGenerationTaskResult.task_id == task.id)
                        .order_by(ImageGenerationTaskResult.id.asc())
                    )
                    existing_rows = list(existing_rows_result.scalars().all())
                    if not existing_rows:
                        row = ImageGenerationTaskResult(
                            task_id=task.id,
                            image_index=1,
                            api_key_id=task.api_key_id,
                            provider=task.provider,
                            api_key_name=task.api_key_name,
                            model=task.model,
                            status="error",
                            error_category="image_timeout_auto_refresh_failed",
                            error_detail=failure_message,
                            result_meta_json=json.dumps({"error": message or "image_timeout_auto_refresh_failed"}, ensure_ascii=False),
                            created_at=finished_at,
                            started_at=task.started_at,
                            finished_at=finished_at,
                            duration_ms=calculate_duration_ms(task.started_at, finished_at),
                            updated_at=finished_at,
                        )
                        db.add(row)
                    else:
                        for row in existing_rows:
                            if row.status != "success":
                                row.status = "error"
                                row.error_category = "image_timeout_auto_refresh_failed"
                                row.error_detail = failure_message
                                row.finished_at = finished_at
                                row.updated_at = finished_at
                    task.status = "error"
                    task.pending_refresh = False
                    task.completed_count = 1
                    task.success_count = 0
                    task.error_count = 1
                    task.failure_category_stats_json = json.dumps({"image_timeout_auto_refresh_failed": 1}, ensure_ascii=False)
                    task.error_summary = failure_message
                    task.finished_at = finished_at
                    task.duration_ms = calculate_duration_ms(task.started_at, finished_at)
                    task.updated_at = finished_at
                    await db.commit()
                    logger.warning(
                        "image_timeout_auto_refresh_failed task_id=%s attempts=%s message=%s",
                        task_id,
                        refresh_config.image_auto_refresh_max_attempts,
                        message,
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception as iteration_error:
            logger.exception(
                "image_timeout_auto_refresh_iteration_failed task_id=%s attempt=%s error=%s",
                task_id,
                attempt,
                str(iteration_error) or iteration_error.__class__.__name__,
            )

        await asyncio.sleep(refresh_config.image_auto_refresh_interval_seconds)


async def refresh_image_task_from_task_log(db: AsyncSession, task: Any, upstream_task_id: Optional[str] = None) -> tuple[Any, list[Any], bool, str]:
    """按上游任务日志回填图片结果，可选按上游任务 ID 精确查询"""
    from models import ApiKey, ImageGenerationTaskResult

    result = await db.execute(
        select(ImageGenerationTaskResult)
        .where(ImageGenerationTaskResult.task_id == task.id)
        .order_by(ImageGenerationTaskResult.image_index.asc(), ImageGenerationTaskResult.id.asc())
    )
    rows = list(result.scalars().all())
    if any(row.status == "success" for row in rows):
        return task, rows, True, "已有成功结果"

    api_key = await db.get(ApiKey, int(task.api_key_id or 0)) if task.api_key_id else None
    if not api_key:
        return task, rows, False, "原始 Key 不存在，无法查询上游任务日志"
    if not is_newapi_key(api_key):
        return task, rows, False, "当前 Key 类型不支持图片回填查询"

    task_started_at = getattr(task, "started_at", None) or getattr(task, "created_at", None)
    if not task_started_at:
        return task, rows, False, "任务缺少开始时间，无法查询上游任务日志"

    now_for_query = datetime.utcnow()
    task_timestamp = int(task_started_at.replace(tzinfo=timezone.utc).timestamp())
    start_timestamp = int((now_for_query - timedelta(hours=1)).replace(tzinfo=timezone.utc).timestamp())
    end_timestamp = int((now_for_query + timedelta(minutes=30)).replace(tzinfo=timezone.utc).timestamp())
    refresh_result = await proxy_service.fetch_magic666_task_log_result(
        api_key,
        prompt=task.prompt,
        model=task.model,
        start_timestamp=start_timestamp,
        end_timestamp=end_timestamp,
        target_timestamp=task_timestamp,
        use_time_window=False,
        upstream_task_id=upstream_task_id,
    )
    if not refresh_result.get("images"):
        refresh_result = await proxy_service.fetch_magic666_task_log_result(
            api_key,
            prompt=task.prompt,
            model=task.model,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            target_timestamp=task_timestamp,
            use_time_window=True,
            upstream_task_id=upstream_task_id,
        )
    return await apply_image_refresh_result(db, task, rows, api_key, refresh_result, refresh_result.get("upstream_task") or {"source": "magic666_task_log"})


async def apply_image_refresh_result(
    db: AsyncSession,
    task: Any,
    rows: list[Any],
    api_key: Any,
    refresh_result: dict,
    upstream_task: dict,
) -> tuple[Any, list[Any], bool, str]:
    """应用上游图片刷新结果"""
    from models import ImageGenerationTaskResult

    images = refresh_result.get("images") or []
    if not images:
        if rows:
            rows[0].result_meta_json = json.dumps(
                {
                    "upstream_task": refresh_result.get("upstream_task") or upstream_task,
                    "response_data": refresh_result.get("response_data") or {},
                },
                ensure_ascii=False,
                default=str,
            )
            rows[0].updated_at = datetime.utcnow()
            await db.commit()
        return task, rows, False, refresh_result.get("error_message") or "上游暂未返回可展示的图片结果"

    finished_at = datetime.utcnow()
    duration_ms = int(refresh_result.get("response_time_ms") or 0)
    for stale_row in rows:
        await db.delete(stale_row)
    rows = []
    for index, image in enumerate(images[: int(task.total_count or 1)], start=1):
        image_url = normalize_image_output_text(image.get("image_url"))
        image_base64 = normalize_image_output_text(image.get("image_base64"))
        saved_file = await persist_output_image_file(
            int(task.id),
            index,
            {
                "image_url": image_url,
                "image_base64": image_base64,
                "mime_type": image.get("mime_type") or "image/png",
                "width": image.get("width"),
                "height": image.get("height"),
            },
        )
        row = ImageGenerationTaskResult(
            task_id=task.id,
            image_index=index,
            api_key_id=task.api_key_id,
            provider=task.provider,
            api_key_name=task.api_key_name,
            model=task.model,
            status="success",
            image_url=image_url,
            image_base64=image_base64,
            local_path=saved_file.get("local_path"),
            mime_type=saved_file.get("mime_type") or image.get("mime_type") or "image/png",
            width=image.get("width") or saved_file.get("width"),
            height=image.get("height") or saved_file.get("height"),
            file_size_bytes=saved_file.get("file_size_bytes"),
            result_meta_json=json.dumps(
                {"upstream_task": refresh_result.get("upstream_task") or upstream_task, "image_meta": image.get("meta") or {}},
                ensure_ascii=False,
                default=str,
            ),
            created_at=finished_at,
            started_at=task.started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            updated_at=finished_at,
        )
        db.add(row)
        rows.append(row)

    # 回填成功后清空冗余大字段，图片已存本地文件
    for row in rows:
        if row.local_path:
            row.result_meta_json = None
            row.image_base64 = None

    task.status = "success"
    task.pending_refresh = False
    task.completed_count = len(rows)
    task.success_count = len(rows)
    task.error_count = 0
    task.failure_category_stats_json = None
    task.error_summary = None
    task.finished_at = finished_at
    task.duration_ms = calculate_duration_ms(task.started_at, finished_at)
    task.updated_at = finished_at
    await upsert_image_key_model_stats(
        db,
        build_api_key_snapshot(api_key),
        task.model,
        total_delta=0,
        success_delta=len(rows),
        error_delta=0,
        generated_at=finished_at,
    )
    await db.commit()
    await db.refresh(task)
    for row in rows:
        await db.refresh(row)
    return task, rows, True, "图片结果回填成功"


async def refresh_image_task_from_upstream(db: AsyncSession, task: Any, upstream_task_override: Optional[dict] = None) -> tuple[Any, list[Any], bool, str]:
    """按上游任务信息重抓取图片结果"""
    from models import ApiKey, ImageGenerationTaskResult

    result = await db.execute(
        select(ImageGenerationTaskResult)
        .where(ImageGenerationTaskResult.task_id == task.id)
        .order_by(ImageGenerationTaskResult.image_index.asc(), ImageGenerationTaskResult.id.asc())
    )
    rows = list(result.scalars().all())
    if any(row.status == "success" for row in rows):
        return task, rows, True, "已有成功结果"

    upstream_task = dict(upstream_task_override or {})
    if not upstream_task:
        for row in rows:
            upstream_task = extract_upstream_task_from_meta(row.result_meta_json)
            if upstream_task:
                break
    if not upstream_task:
        request_params = load_json_object(getattr(task, "request_params_json", None))
        if isinstance(request_params.get("upstream_task"), dict):
            upstream_task = request_params["upstream_task"]
    if not upstream_task:
        return task, rows, False, "没有保存上游任务 ID，无法无损重抓取；后续任务会保存任务 ID 后再刷新，不会重新发起生图。"

    api_key = await db.get(ApiKey, int(task.api_key_id or 0)) if task.api_key_id else None
    if not api_key:
        return task, rows, False, "原始 Key 不存在，无法重抓取"
    if not is_newapi_key(api_key):
        return task, rows, False, "当前 Key 类型不支持图片回填查询"

    refresh_result = await proxy_service.fetch_image_task_result(api_key, upstream_task)
    images = refresh_result.get("images") or []
    if not images and getattr(api_key, "base_url", None):
        task_started_at = getattr(task, "started_at", None) or getattr(task, "created_at", None)
        task_updated_at = getattr(task, "updated_at", None) or datetime.utcnow()
        if task_started_at:
            now_for_query = datetime.utcnow()
            start_timestamp = int((now_for_query - timedelta(hours=1)).replace(tzinfo=timezone.utc).timestamp())
            end_timestamp = int((now_for_query + timedelta(minutes=30)).replace(tzinfo=timezone.utc).timestamp())
            task_timestamp = int(task_started_at.replace(tzinfo=timezone.utc).timestamp())
            log_result = await proxy_service.fetch_magic666_task_log_result(
                api_key,
                prompt=task.prompt,
                model=task.model,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                target_timestamp=task_timestamp,
                use_time_window=False,
            )
            if not log_result.get("images"):
                log_result = await proxy_service.fetch_magic666_task_log_result(
                    api_key,
                    prompt=task.prompt,
                    model=task.model,
                    start_timestamp=start_timestamp,
                    end_timestamp=end_timestamp,
                    target_timestamp=task_timestamp,
                    use_time_window=True,
                )
            if log_result.get("images"):
                refresh_result = log_result
                images = log_result.get("images") or []
            elif refresh_result.get("status") != "error" and log_result.get("error_message"):
                refresh_result = {
                    **refresh_result,
                    "response_data": {
                        "probe": refresh_result.get("response_data") or {},
                        "magic666_task_log": log_result.get("response_data") or {},
                    },
                    "error_message": log_result.get("error_message") or refresh_result.get("error_message"),
                }
    if not images:
        if rows:
            rows[0].result_meta_json = json.dumps(
                {
                    "upstream_task": refresh_result.get("upstream_task") or upstream_task,
                    "response_data": refresh_result.get("response_data") or {},
                },
                ensure_ascii=False,
                default=str,
            )
            rows[0].updated_at = datetime.utcnow()
            await db.commit()
        return task, rows, False, refresh_result.get("error_message") or "上游暂未返回可展示的图片结果"

    finished_at = datetime.utcnow()
    duration_ms = int(refresh_result.get("response_time_ms") or 0)
    for stale_row in rows:
        await db.delete(stale_row)
    rows = []
    for index, image in enumerate(images[: int(task.total_count or 1)], start=1):
        image_url = normalize_image_output_text(image.get("image_url"))
        image_base64 = normalize_image_output_text(image.get("image_base64"))
        saved_file = await persist_output_image_file(
            int(task.id),
            index,
            {
                "image_url": image_url,
                "image_base64": image_base64,
                "mime_type": image.get("mime_type") or "image/png",
                "width": image.get("width"),
                "height": image.get("height"),
            },
        )
        row = ImageGenerationTaskResult(
            task_id=task.id,
            image_index=index,
            api_key_id=task.api_key_id,
            provider=task.provider,
            api_key_name=task.api_key_name,
            model=task.model,
            status="success",
            image_url=image_url,
            image_base64=image_base64,
            local_path=saved_file.get("local_path"),
            mime_type=saved_file.get("mime_type") or image.get("mime_type") or "image/png",
            width=image.get("width") or saved_file.get("width"),
            height=image.get("height") or saved_file.get("height"),
            file_size_bytes=saved_file.get("file_size_bytes"),
            result_meta_json=json.dumps(
                {"upstream_task": refresh_result.get("upstream_task") or upstream_task, "image_meta": image.get("meta") or {}},
                ensure_ascii=False,
                default=str,
            ),
            created_at=finished_at,
            started_at=task.started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            updated_at=finished_at,
        )
        db.add(row)
        rows.append(row)

    # 回填成功后清空冗余大字段，图片已存本地文件
    for row in rows:
        if row.local_path:
            row.result_meta_json = None
            row.image_base64 = None

    task.status = "success"
    task.completed_count = len(rows)
    task.success_count = len(rows)
    task.error_count = 0
    task.failure_category_stats_json = None
    task.error_summary = None
    task.finished_at = finished_at
    task.duration_ms = calculate_duration_ms(task.started_at, finished_at)
    task.updated_at = finished_at
    await upsert_image_key_model_stats(
        db,
        build_api_key_snapshot(api_key),
        task.model,
        total_delta=0,
        success_delta=len(rows),
        error_delta=0,
        generated_at=finished_at,
    )
    await db.commit()
    await db.refresh(task)
    for row in rows:
        await db.refresh(row)
    return task, rows, True, "重抓取成功"


async def close_stale_running_image_tasks(db: AsyncSession) -> int:
    """将长时间未收尾的图片任务标记为失败（同步版本，用于后台任务）"""
    from models import ImageGenerationTask, ImageGenerationTaskResult

    grace_seconds = max(int(settings.proxy_request_timeout_seconds or 60) * 3, 300)
    cutoff = datetime.utcnow() - timedelta(seconds=grace_seconds)
    result = await db.execute(
        select(ImageGenerationTask)
        .where(ImageGenerationTask.status == "running")
        .where(ImageGenerationTask.is_deleted.is_(False))
        .where(ImageGenerationTask.pending_refresh.is_(False))
        .where(ImageGenerationTask.started_at.isnot(None))
        .where(ImageGenerationTask.started_at < cutoff)
        .order_by(ImageGenerationTask.started_at.asc(), ImageGenerationTask.id.asc())
        .limit(20)
    )
    tasks = list(result.scalars().all())
    if not tasks:
        return 0

    closed_count = 0
    finished_at = datetime.utcnow()
    for task in tasks:
        try:
            refreshed_task, refreshed_rows, refreshed, _ = await refresh_image_task_from_upstream(db, task)
            if refreshed and any(row.status == "success" for row in refreshed_rows):
                closed_count += 1
                await db.commit()
                continue

            existing_rows_result = await db.execute(
                select(ImageGenerationTaskResult)
                .where(ImageGenerationTaskResult.task_id == task.id)
                .order_by(ImageGenerationTaskResult.id.asc())
            )
            existing_rows = list(existing_rows_result.scalars().all())
            if any(row.status == "success" for row in existing_rows):
                success_rows = [row for row in existing_rows if row.status == "success"]
                for row in existing_rows:
                    if row.status != "success":
                        await db.delete(row)
                latest_finished_at = max((row.finished_at or row.updated_at or row.created_at for row in success_rows), default=finished_at)
                task.status = "success"
                task.completed_count = len(success_rows)
                task.success_count = len(success_rows)
                task.error_count = 0
                task.failure_category_stats_json = None
                task.error_summary = None
                task.finished_at = latest_finished_at
                task.duration_ms = normalize_duration_ms(getattr(task, "duration_ms", 0), task.started_at, latest_finished_at)
                task.updated_at = datetime.utcnow()
                closed_count += 1
                await db.commit()
                continue

            duration_ms = calculate_duration_ms(task.started_at, finished_at)
            if not existing_rows:
                row = ImageGenerationTaskResult(
                    task_id=task.id,
                    image_index=1,
                    api_key_id=task.api_key_id,
                    provider=task.provider,
                    api_key_name=task.api_key_name,
                    model=task.model,
                    status="error",
                    error_category="stale_running_timeout",
                    error_detail="图片生成请求长时间未完成，系统已自动收尾。通常由客户端断开、服务重启或请求取消导致。",
                    result_meta_json=json.dumps({"error": "stale_running_timeout"}, ensure_ascii=False),
                    created_at=finished_at,
                    started_at=task.started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                    updated_at=finished_at,
                )
                db.add(row)
            task.status = "error"
            task.completed_count = max(int(task.completed_count or 0), 1)
            task.success_count = int(task.success_count or 0)
            task.error_count = max(int(task.error_count or 0), 1)
            task.failure_category_stats_json = json.dumps({"stale_running_timeout": 1}, ensure_ascii=False)
            task.error_summary = "图片生成请求长时间未完成，系统已自动收尾。通常由客户端断开、服务重启或请求取消导致。"
            task.finished_at = finished_at
            task.duration_ms = duration_ms
            task.updated_at = finished_at
            closed_count += 1
            await db.commit()
        except Exception as task_error:
            logger.exception(
                "image_generation_stale_close_task_failed task_id=%s error=%s",
                getattr(task, "id", None),
                str(task_error) or task_error.__class__.__name__,
            )
            await db.rollback()

    logger.warning("image_generation_stale_running_closed count=%s grace_seconds=%s", closed_count, grace_seconds)
    return closed_count


async def clear_stale_result_meta(db: AsyncSession) -> int:
    """清空超过 3 小时的结果记录中的冗余大字段（image_base64 / result_meta_json）"""
    from models import ImageGenerationTask, ImageGenerationTaskResult

    cutoff = datetime.utcnow() - timedelta(hours=3)
    result = await db.execute(
        select(ImageGenerationTaskResult)
        .join(ImageGenerationTask, ImageGenerationTaskResult.task_id == ImageGenerationTask.id)
        .where(ImageGenerationTask.created_at < cutoff)
        .where(ImageGenerationTaskResult.local_path.isnot(None))
        .where(
            (ImageGenerationTaskResult.image_base64.isnot(None)) |
            (ImageGenerationTaskResult.result_meta_json.isnot(None))
        )
        .limit(200)
    )
    rows = list(result.scalars().all())
    if not rows:
        return 0

    cleared = 0
    for row in rows:
        row.image_base64 = None
        row.result_meta_json = None
        cleared += 1

    await db.commit()
    logger.info("clear_stale_result_meta cleared=%s", cleared)
    return cleared


def resolve_managed_image_file(local_path: Optional[str]) -> Path:
    """解析并校验受管理图片文件路径"""
    if not local_path:
        raise HTTPException(status_code=400, detail="图片未保存到本地")

    storage_dir = load_image_storage_dir().resolve()
    path = Path(local_path).expanduser().resolve()
    try:
        path.relative_to(storage_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="图片文件不在当前存储目录内") from exc

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="图片文件不存在")

    return path


def open_windows_folder(path: Path, reveal: bool) -> None:
    """打开 Windows 文件夹或定位文件"""
    if os.name != "nt":
        raise HTTPException(status_code=400, detail="当前运行环境不支持打开本地文件夹")

    if reveal:
        subprocess.Popen(["explorer", f"/select,{str(path)}"])
    else:
        subprocess.Popen(["explorer", str(path.parent)])


def delete_managed_image_file(local_path: Optional[str]) -> bool:
    """删除受管理图片文件"""
    path = resolve_managed_image_file(local_path)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


def load_json_probe_result(value: Optional[str], *, fallback_url: str, fallback_path: str) -> ApiKeyCheckProbeResult:
    """反序列化探测结果"""
    data = load_json_object(value)
    return ApiKeyCheckProbeResult(
        status=data.get("status") or "pending",
        status_code=data.get("status_code"),
        error_message=data.get("error_message"),
        response_time_ms=int(data.get("response_time_ms") or 0),
        path=data.get("path") or fallback_path,
        url=data.get("url") or fallback_url,
    )


def build_api_key_check_item_from_task_result(item: Any) -> ApiKeyCheckItem:
    """从任务结果构建单项检测响应"""
    return ApiKeyCheckItem(
        key_id=int(item.api_key_id),
        name=item.name,
        provider=item.provider,
        base_url=item.base_url,
        status=item.status or "pending",
        target_model=item.target_model,
        response_time_ms=int(item.response_time_ms or 0),
        failure_category=item.failure_category,
        failure_detail=item.failure_detail,
        address_check=load_json_probe_result(
            item.address_check_json,
            fallback_url=item.base_url,
            fallback_path="v1/models",
        ),
        model_check=load_json_probe_result(
            item.model_check_json,
            fallback_url=item.base_url,
            fallback_path="",
        ) if item.model_check_json else None,
    )


def to_check_task_response(task: Any) -> ApiKeyCheckTaskResponse:
    """转换任务响应"""
    total_count = int(task.total_count or 0)
    completed_count = int(task.completed_count or 0)
    progress_percent = round((completed_count / total_count) * 100, 2) if total_count else 0
    raw_key_ids = []
    if task.key_ids_json:
        try:
            key_ids_data = json.loads(task.key_ids_json)
            if isinstance(key_ids_data, list):
                raw_key_ids = key_ids_data
        except json.JSONDecodeError:
            raw_key_ids = []
    key_ids = []
    for item in raw_key_ids:
        try:
            key_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ApiKeyCheckTaskResponse(
        id=int(task.id),
        scope=task.scope,
        provider=task.provider,
        providers=loads_json_list(task.providers_json),
        models=loads_json_list(task.models_json),
        is_active=task.is_active,
        key_ids=key_ids,
        target_model=task.target_model,
        status=task.status,
        total_count=total_count,
        completed_count=completed_count,
        success_count=int(task.success_count or 0),
        error_count=int(task.error_count or 0),
        progress_percent=progress_percent,
        failure_category_stats=load_json_object(task.failure_category_stats_json),
        provider_stats=load_json_object(task.provider_stats_json),
        model_stats=load_json_object(task.model_stats_json),
        error_summary=task.error_summary,
        retry_of_task_id=task.retry_of_task_id,
        report_file_path=task.report_file_path,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        updated_at=task.updated_at,
    )


IMAGE_MODEL_OPTIONS = [
    {
        "model": "gpt-image-2-pro",
        "display_name": "GPT Image 2 Pro",
        "provider": "openai",
        "request_formats": ["images", "chat"],
        "candidate_request_formats": ["images", "chat", "responses"],
        "max_count": 4,
    },
    {
        "model": "gpt-image-2",
        "display_name": "GPT Image 2",
        "provider": "openai",
        "request_formats": ["images", "chat"],
        "candidate_request_formats": ["images", "chat", "responses"],
        "max_count": 4,
    },
    {
        "model": "gpt-image-1-vip",
        "display_name": "GPT Image 1 VIP",
        "provider": "openai",
        "request_formats": ["images", "chat"],
        "candidate_request_formats": ["images", "chat", "responses"],
        "max_count": 4,
    },
    {
        "model": "gpt-image-1",
        "display_name": "GPT Image 1",
        "provider": "openai",
        "request_formats": ["images", "chat"],
        "candidate_request_formats": ["images", "chat", "responses"],
        "max_count": 4,
    },
    {
        "model": "nano-banana-pro",
        "display_name": "Nano Banana Pro",
        "provider": "openai",
        "request_formats": ["images", "chat"],
        "candidate_request_formats": ["images", "chat", "responses"],
        "max_count": 4,
    },
    {
        "model": "nano-banana-pro-4k",
        "display_name": "Nano Banana Pro 4K",
        "provider": "openai",
        "request_formats": ["images", "chat"],
        "candidate_request_formats": ["images", "chat", "responses"],
        "max_count": 4,
    },
]


IMAGE_MODEL_VALIDATE_MODELS = {"gpt-image-2", "gpt-image-2-pro", "gpt-image-1", "nano-banana-pro", "nano-banana-pro-4k"}
IMAGE_MODEL_VALIDATE_PROMPT = "Generate a simple blue square on a white background for API validation."
IMAGE_KEY_INITIAL_AMOUNT_UNITS = 1
IMAGE_MODEL_PRICE_UNITS = {
    "gpt-image-2": 0.04,
    "gpt-image-2-pro": 0.08,
    "gpt-image-1-vip": 0.04,
    "gpt-image-1": 0.04,
    "nano-banana-pro": 0.06,
    "nano-banana-pro-4k": 0.08,
}


IMAGE_MODEL_MAP = {
    item["model"].lower(): item
    for item in IMAGE_MODEL_OPTIONS
}


def get_image_model_config(model: str) -> dict:
    """获取图片模型配置"""
    model_name = normalize_model_name(model)
    config = IMAGE_MODEL_MAP.get(model_name)
    if not config:
        raise HTTPException(status_code=400, detail="暂不支持该图片模型")
    return config


def normalize_image_request_format(model_config: dict, request_format: Optional[str], *, include_candidates: bool = False) -> str:
    """规范化图片请求格式"""
    formats = list(model_config.get("request_formats") or ["images"])
    if include_candidates:
        for item in model_config.get("candidate_request_formats") or []:
            if item not in formats:
                formats.append(item)
    normalized = (request_format or "").strip().lower()
    if not normalized:
        return formats[0]
    if normalized not in formats:
        raise HTTPException(status_code=400, detail="当前模型不支持该请求格式")
    return normalized


def normalize_image_model_alias(model: str) -> str:
    """归一化图片模型别名"""
    value = normalize_model_name(model)
    aliases = {
        "gptimage2pro": "gpt-image-2-pro",
        "gpt-image2-pro": "gpt-image-2-pro",
        "gpt-image-2pro": "gpt-image-2-pro",
        "gptimage2": "gpt-image-2",
        "gpt-image2": "gpt-image-2",
        "gptimage1vip": "gpt-image-1-vip",
        "gpt-image1-vip": "gpt-image-1-vip",
        "gpt-image-1vip": "gpt-image-1-vip",
        "gptimage15": "gpt-image-1-vip",
        "gpt-image15": "gpt-image-1-vip",
        "gpt-image-15": "gpt-image-1-vip",
        "gpt-image-1.5": "gpt-image-1-vip",
        "gptimage1": "gpt-image-1",
        "gpt-image1": "gpt-image-1",
        "nanobananapro": "nano-banana-pro",
        "nano-banana-pro-4k": "nano-banana-pro-4k",
        "nanobananapro4k": "nano-banana-pro-4k",
    }
    compact = value.replace("-", "").replace("_", "").replace(" ", "")
    return aliases.get(value) or aliases.get(compact) or value


def normalize_image_model_item(value: Any) -> list[str]:
    """拆分并规范化图片模型名称"""
    if not isinstance(value, str):
        return []
    text = value.strip()
    if not text:
        return []
    for separator in ["，", ",", "\n", "\r", "\t", ";", "；", "|", "/", "、", "�"]:
        text = text.replace(separator, " ")
    return [item.strip() for item in text.split() if item.strip()]


def normalize_image_supported_models(value: Optional[str]) -> list[str]:
    """解析图片 Key 支持模型列表"""
    items = []
    for item in loads_json_list(value):
        items.extend(normalize_image_model_item(item))
    normalized = []
    seen = set()
    for item in items:
        model = normalize_image_model_alias(item)
        if not model or model in seen:
            continue
        seen.add(model)
        normalized.append(model)
    return normalized


def key_supports_image_model(key: Any, model: str) -> bool:
    """判断 Key 是否支持指定图片模型"""
    supported_models = normalize_image_supported_models(getattr(key, "supported_models", None))
    if not supported_models:
        return True
    target = normalize_image_model_alias(model)
    return target in supported_models


def is_bbimg_key(key: Any) -> bool:
    """判断是否为 bbimg 图片 Key"""
    values = [
        getattr(key, "name", ""),
        getattr(key, "provider", ""),
        getattr(key, "base_url", ""),
        getattr(key, "remark", ""),
    ]
    return any("bbimg" in str(value or "").lower() for value in values)


IMAGE_NON_KEY_FAILURE_KEYWORDS = [
    "too many requests",
    "429",
    "rate limit",
    "rate_limit",
    "prompt",
    "content policy",
    "content_policy",
    "safety",
    "moderation",
    "policy violation",
    "invalid model",
    "model_not_found",
    "model not found",
    "model does not exist",
    "unsupported model",
    "not supported",
    "does not support",
    "提示词",
    "提示语",
    "需要调整提示词",
    "提示词不准确",
    "模型不存在",
    "模型不支持",
    "不支持该模型",
    "无效模型",
    "安全策略",
    "内容安全",
    "内容政策",
    "审核",
    "违规",
    "敏感",
    "origin web server",
    "cloudflare",
    "proxy read timeout",
    "timeout window",
    "请求超时",
]


IMAGE_BALANCE_DEPLETED_KEYWORDS = [
    "预扣费额度失败",
    "用户剩余额度",
    "需要预扣费额度",
    "余额不足",
    "额度不足",
    "insufficient_user_quota",
    "insufficient quota",
    "insufficient balance",
    "insufficient credits",
    "not enough credits",
    "balance not enough",
    "quota exceeded",
]


IMAGE_MODEL_FAILURE_KEYWORDS = [
    "model",
    "模型",
]


def is_non_key_image_failure(category: Optional[str], status_code: Optional[int], error_message: Optional[str]) -> bool:
    """判断图片失败是否属于输入或模型配置问题"""
    category_text = normalize_optional_text(category) or ""
    category_text = category_text.lower()
    message = (error_message or "").lower()
    if status_code in {400, 422}:
        return True
    if any(keyword in message for keyword in IMAGE_NON_KEY_FAILURE_KEYWORDS):
        return True
    if category_text == "404" and any(keyword in message for keyword in IMAGE_MODEL_FAILURE_KEYWORDS):
        return True
    return False


def should_count_image_key_failure(category: Optional[str], status_code: Optional[int], error_message: Optional[str]) -> bool:
    """判断图片失败是否计入 Key 失败"""
    return not is_non_key_image_failure(category, status_code, error_message)


def should_count_image_task_failure(task: Any) -> bool:
    """判断历史图片任务是否计入连续失败"""
    category = None
    stats = load_json_object(getattr(task, "failure_category_stats_json", None))
    if isinstance(stats, dict) and stats:
        category = next(iter(stats.keys()))
    return should_count_image_key_failure(category, None, getattr(task, "error_summary", None))


def collect_image_error_texts(error_message: Optional[str], response_data: Any = None) -> list[str]:
    """提取图片错误文本用于业务分类"""
    texts: list[str] = []
    if error_message:
        texts.append(str(error_message))

    if isinstance(response_data, str):
        texts.append(response_data)
        try:
            response_data = json.loads(response_data)
        except Exception:
            response_data = None

    if isinstance(response_data, dict):
        error_data = response_data.get("error")
        if isinstance(error_data, dict):
            for key in ("message", "code", "type", "param"):
                value = error_data.get(key)
                if value:
                    texts.append(str(value))
        for key in ("message", "code", "type", "detail"):
            value = response_data.get(key)
            if value:
                texts.append(str(value))

    return texts


def is_image_balance_depleted_failure(error_message: Optional[str], response_data: Any = None) -> bool:
    """判断图片失败是否为余额不足"""
    message = "\n".join(collect_image_error_texts(error_message, response_data)).lower()
    return any(keyword in message for keyword in IMAGE_BALANCE_DEPLETED_KEYWORDS)


def extract_model_refusal_text(response_data: Any) -> Optional[str]:
    """从上游响应中提取模型的文本拒绝内容（当模型返回文本而非图片时）"""
    if not isinstance(response_data, dict):
        return None
    choices = response_data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            text = content.strip()
            if len(text) > 300:
                text = text[:300] + "..."
            return text
    return None


def is_cloudflare_image_timeout(error_message: Optional[str], response_data: Any = None, status_code: Optional[int] = None) -> bool:
    """判断图片请求是否属于可回填类错误（Cloudflare 超时 / 上游断连）

    匹配场景：
    - Cloudflare 专属超时（520/522/523/524 及对应错误文案）
    - Cloudflare 502（"invalid or incomplete response to Cloudflare"）
    - 上游无标准 HTTP 状态码的网络级断连（如 Server disconnected）
    非 Cloudflare 的标准 HTTP 错误码（如 429/500/503/504）不视为可回填超时。
    """
    # 429/500/501/503/504 直接排除
    if isinstance(status_code, int) and status_code in {429, 500, 501, 503, 504}:
        return False
    texts = collect_image_error_texts(error_message, response_data)
    message = "\n".join(texts).lower()
    response_status = None
    response_error_code = None
    if isinstance(response_data, dict):
        response_status = response_data.get("status")
        response_error_code = response_data.get("error_code")
    # Cloudflare 502：由 Cloudflare 代理返回的 502，上游可能已处理，可回填
    # 普通上游 502（无 Cloudflare 标记）直接返回 False，显示错误
    if isinstance(status_code, int) and status_code == 502:
        cf_markers = ["cloudflare", "origin_response_timeout", "proxy read timeout window",
                       "invalid or incomplete response"]
        return any(marker in message for marker in cf_markers)
    # Cloudflare 专属超时
    if (
        status_code in {520, 522, 523, 524}
        or str(response_status or "") in {"520", "522", "523", "524"}
        or str(response_error_code or "") in {"520", "522", "523", "524"}
        or "origin_response_timeout" in message
        or "proxy read timeout window" in message
    ):
        return True
    # 无标准 HTTP 状态码的上游断连：视为可重试
    if not isinstance(status_code, int) and any(
        marker in message for marker in ["server disconnected", "connection reset", "connection closed"]
    ):
        return True
    return False


async def apply_image_balance_depleted_policy(
    db: AsyncSession,
    api_key: Any,
    model: str,
    generated_at: datetime,
) -> list[str]:
    """图片余额不足时禁用 Key 并清零剩余额度，返回需要 reset_index 的 provider 列表"""
    from models import ImageKeyModelStats

    now = generated_at or datetime.utcnow()
    key_id = int(api_key.id)
    normalized_model = normalize_model_name(model)
    providers_to_reset: list[str] = []

    result = await db.execute(
        select(ImageKeyModelStats)
        .where(ImageKeyModelStats.api_key_id == key_id)
        .where(ImageKeyModelStats.model_normalized == normalized_model)
    )
    stats = result.scalar_one_or_none()
    if not stats:
        stats = ImageKeyModelStats(
            api_key_id=key_id,
            api_key_name=api_key.name,
            provider=api_key.provider,
            model=model,
            model_normalized=normalized_model,
            total_count=0,
            success_count=0,
            error_count=0,
            spent_units=0,
            remaining_units=0,
            created_at=now,
            updated_at=now,
        )
        db.add(stats)
        await db.flush()

    result = await db.execute(select(ImageKeyModelStats).where(ImageKeyModelStats.api_key_id == key_id))
    for item in result.scalars().all():
        item.api_key_name = api_key.name
        item.provider = api_key.provider
        item.remaining_units = 0
        item.updated_at = now

    api_key.is_active = False
    api_key.updated_at = now
    provider = str(api_key.provider or "")
    if provider:
        providers_to_reset.append(provider)
    return providers_to_reset


async def refresh_image_key_remaining_units(db: AsyncSession, key_id: int, updated_at: datetime) -> int:
    """刷新同一个 Key 下所有图片模型的剩余额度"""
    from models import ImageKeyModelStats

    result = await db.execute(select(ImageKeyModelStats).where(ImageKeyModelStats.api_key_id == key_id))
    rows = list(result.scalars().all())
    last_remaining_units = 0
    for row in rows:
        remaining_units = max(0.0, IMAGE_KEY_INITIAL_AMOUNT_UNITS - float(row.spent_units or 0))
        row.remaining_units = remaining_units
        row.updated_at = updated_at
        last_remaining_units = remaining_units
    return last_remaining_units


async def upsert_image_key_model_stats(
    db: AsyncSession,
    api_key: Any,
    model: str,
    *,
    total_delta: int,
    success_delta: int,
    error_delta: int,
    generated_at: datetime,
) -> None:
    """增量更新图片 Key 模型统计"""
    from models import ImageKeyModelStats

    total_delta = max(0, int(total_delta or 0))
    success_delta = max(0, int(success_delta or 0))
    error_delta = max(0, int(error_delta or 0))
    if total_delta == 0 and success_delta == 0 and error_delta == 0:
        return

    key_id = int(get_snapshot_value(api_key, "id"))
    key_name = get_snapshot_value(api_key, "name")
    key_provider = get_snapshot_value(api_key, "provider")
    normalized_model = normalize_model_name(model)
    price_units = IMAGE_MODEL_PRICE_UNITS.get(normalized_model)
    spent_delta = success_delta * price_units if price_units else 0
    now = generated_at or datetime.utcnow()

    result = await db.execute(
        select(ImageKeyModelStats)
        .where(ImageKeyModelStats.api_key_id == key_id)
        .where(ImageKeyModelStats.model_normalized == normalized_model)
    )
    stats = result.scalar_one_or_none()
    if not stats:
        stats = ImageKeyModelStats(
            api_key_id=key_id,
            api_key_name=key_name,
            provider=key_provider,
            model=model,
            model_normalized=normalized_model,
            total_count=0,
            success_count=0,
            error_count=0,
            spent_units=0,
            remaining_units=IMAGE_KEY_INITIAL_AMOUNT_UNITS,
            created_at=now,
            updated_at=now,
        )
        db.add(stats)

    stats.api_key_name = key_name
    stats.provider = key_provider
    stats.model = model
    stats.model_normalized = normalized_model
    stats.total_count = int(stats.total_count or 0) + total_delta
    stats.success_count = int(stats.success_count or 0) + success_delta
    stats.error_count = int(stats.error_count or 0) + error_delta
    stats.spent_units = float(stats.spent_units or 0) + spent_delta
    stats.last_generated_at = generated_at
    stats.updated_at = now
    await db.flush()
    await refresh_image_key_remaining_units(db, key_id, now)


async def calculate_total_remaining_image_count(db: AsyncSession, keys: list[Any], model: str) -> Optional[int]:
    """计算模型剩余可生成总数"""
    from models import ImageKeyModelStats

    normalized_model = normalize_image_model_alias(model)
    current_model_price_units = IMAGE_MODEL_PRICE_UNITS.get(normalized_model)
    if not current_model_price_units:
        return None

    image_key_ids = [int(key.id) for key in keys if getattr(key, "id", None) is not None]
    if not image_key_ids:
        return 0

    result = await db.execute(
        select(ImageKeyModelStats)
        .where(ImageKeyModelStats.api_key_id.in_(image_key_ids))
        .where(ImageKeyModelStats.model_normalized == normalized_model)
    )
    stats_by_key = {int(item.api_key_id): item for item in result.scalars().all()}

    total_remaining_units = 0.0
    for key_id in image_key_ids:
        stats = stats_by_key.get(key_id)
        spent_units = float(getattr(stats, "spent_units", 0.0) or 0.0)
        total_remaining_units += max(0.0, IMAGE_KEY_INITIAL_AMOUNT_UNITS - spent_units)

    return int(total_remaining_units / current_model_price_units + 1e-9)


def calculate_duration_ms(started_at: Optional[datetime], finished_at: Optional[datetime]) -> int:
    """计算毫秒耗时"""
    if not started_at or not finished_at:
        return 0
    return max(0, int((finished_at - started_at).total_seconds() * 1000))


def normalize_duration_ms(value: Any, started_at: Optional[datetime] = None, finished_at: Optional[datetime] = None) -> int:
    """归一化毫秒耗时"""
    duration = int(value or 0)
    if duration > 0:
        return duration
    return calculate_duration_ms(started_at, finished_at)


def get_image_validate_preview(images: list[dict]) -> dict[str, Any]:
    """提取图片验证预览信息"""
    if not images:
        return {}
    image = images[0] or {}
    return {
        "image_url": image.get("image_url"),
        "image_base64": image.get("image_base64"),
        "mime_type": image.get("mime_type") or "image/png",
        "width": image.get("width"),
        "height": image.get("height"),
    }


def to_image_result_response(item: Any) -> ImageGenerationResultResponse:
    """转换图片结果响应"""
    return ImageGenerationResultResponse(
        id=int(item.id),
        task_id=int(item.task_id),
        image_index=int(item.image_index or 0),
        api_key_id=item.api_key_id,
        provider=item.provider,
        api_key_name=item.api_key_name,
        model=item.model,
        status=item.status,
        image_url=item.image_url,
        image_base64=item.image_base64,
        local_path=item.local_path,
        local_url=image_result_file_url(item.id, item.local_path),
        mime_type=item.mime_type,
        width=item.width,
        height=item.height,
        file_size_bytes=item.file_size_bytes,
        duration_ms=normalize_duration_ms(getattr(item, "duration_ms", 0), item.started_at, item.finished_at),
        error_category=item.error_category,
        error_detail=item.error_detail,
        created_at=item.created_at,
        finished_at=item.finished_at,
    )


def to_image_task_response(task: Any, results: Optional[List[Any]] = None) -> ImageGenerationTaskResponse:
    """转换图片任务响应"""
    return ImageGenerationTaskResponse(
        id=int(task.id),
        provider=task.provider,
        api_key_id=task.api_key_id,
        api_key_name=task.api_key_name,
        base_url=task.base_url,
        model=task.model,
        prompt=task.prompt,
        request_params=load_json_object(task.request_params_json),
        status=task.status,
        total_count=int(task.total_count or 0),
        completed_count=int(task.completed_count or 0),
        success_count=int(task.success_count or 0),
        error_count=int(task.error_count or 0),
        duration_ms=normalize_duration_ms(getattr(task, "duration_ms", 0), task.started_at, task.finished_at),
        failure_category_stats=load_json_object(task.failure_category_stats_json),
        error_summary=task.error_summary,
        pending_refresh=bool(getattr(task, "pending_refresh", False)),
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        updated_at=task.updated_at,
        results=[to_image_result_response(item) for item in (results or [])],
    )


def normalize_image_input_data_url(value: Optional[str]) -> tuple[str, str]:
    """校验并解析图生图输入 data URL"""
    data_url = normalize_optional_text(value)
    if not data_url or not data_url.startswith(IMAGE_INPUT_DATA_URL_PREFIX):
        raise HTTPException(status_code=400, detail="参考图必须是 data URL 图片")

    header, separator, encoded = data_url.partition(",")
    if separator != "," or not encoded:
        raise HTTPException(status_code=400, detail="参考图 data URL 格式不正确")

    meta_parts = header.split(";")
    mime_type = meta_parts[0].replace("data:", "", 1).lower()
    if mime_type not in IMAGE_INPUT_ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="参考图仅支持 PNG、JPEG、WebP")
    if "base64" not in [item.lower() for item in meta_parts[1:]]:
        raise HTTPException(status_code=400, detail="参考图必须使用 base64 编码")

    return data_url, mime_type


def normalize_image_inputs(mode: Optional[str], items: Optional[List[ImageInput]]) -> tuple[str, list[dict], list[dict]]:
    """规范化图生图输入并生成可持久化元数据"""
    normalized_mode = normalize_optional_text(mode) or "text_to_image"
    if normalized_mode not in {"text_to_image", "image_to_image"}:
        raise HTTPException(status_code=400, detail="图片生成模式不支持")

    if normalized_mode == "text_to_image":
        return normalized_mode, [], []

    input_items = list(items or [])
    if not input_items:
        raise HTTPException(status_code=400, detail="图生图模式下请至少上传 1 张参考图")
    if len(input_items) > IMAGE_INPUT_MAX_COUNT:
        raise HTTPException(status_code=400, detail=f"参考图最多支持 {IMAGE_INPUT_MAX_COUNT} 张")

    normalized_images = []
    image_meta = []
    for index, item in enumerate(input_items, start=1):
        image_url = normalize_optional_text(item.image_url) or ""
        has_online_url = image_url.startswith(("http://", "https://"))
        raw_data_url = normalize_optional_text(item.data_url) or ""
        has_data_url = raw_data_url.startswith("data:image/")

        if has_online_url and has_data_url:
            # 同时提供在线 URL 和 data URL：保留两者
            # images 格式用 data_url（避免下载失败），chat 格式用 image_url
            data_url, parsed_mime_type = normalize_image_input_data_url(raw_data_url)
            mime_type = normalize_optional_text(item.mime_type) or parsed_mime_type
            mime_type = mime_type.lower()
            size_bytes = int(item.size_bytes or 0)
        elif has_online_url:
            # 仅在线 URL 模式
            mime_type = normalize_optional_text(item.mime_type) or "image/png"
            size_bytes = int(item.size_bytes or 0)
            data_url = ""
        else:
            # data URL 模式：需要校验 data_url
            data_url, parsed_mime_type = normalize_image_input_data_url(raw_data_url)
            mime_type = normalize_optional_text(item.mime_type) or parsed_mime_type
            mime_type = mime_type.lower()
            if mime_type != parsed_mime_type or mime_type not in IMAGE_INPUT_ALLOWED_MIME_TYPES:
                raise HTTPException(status_code=400, detail="参考图类型与 data URL 不一致")
            size_bytes = int(item.size_bytes or 0)
            image_url = ""

        image_name = normalize_optional_text(item.name) or f"image-{index}"
        normalized_images.append(
            {
                "data_url": data_url,
                "image_url": image_url,
                "name": image_name,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
            }
        )
        image_meta.append(
            {
                "name": image_name,
                "mime_type": mime_type,
                "size_bytes": size_bytes,
                "image_url": image_url,
                "data_url": data_url,
            }
        )

    return normalized_mode, normalized_images, image_meta


async def apply_image_failure_policy(db: AsyncSession, api_key: Any) -> tuple[int, list[str]]:
    """按图片生成连续失败次数调整 Key，返回 (连续失败次数, 需要 reset_index 的 provider 列表)"""
    from models import ImageGenerationTask

    result = await db.execute(
        select(ImageGenerationTask)
        .where(ImageGenerationTask.api_key_id == api_key.id)
        .order_by(ImageGenerationTask.finished_at.desc(), ImageGenerationTask.id.desc())
        .limit(5)
    )
    recent_tasks = list(result.scalars().all())
    consecutive_failures = 0
    for item in recent_tasks:
        if item.status != "error" or not should_count_image_task_failure(item):
            break
        consecutive_failures += 1

    providers_to_reset: list[str] = []
    provider = str(api_key.provider or "")
    if consecutive_failures >= 5:
        api_key.is_active = False
        api_key.updated_at = datetime.utcnow()
        if provider:
            providers_to_reset.append(provider)
    elif consecutive_failures >= 3 and int(api_key.weight or 0) > 0:
        api_key.weight = max(0, int(api_key.weight or 0) - 1)
        api_key.updated_at = datetime.utcnow()
        if provider:
            providers_to_reset.append(provider)

    return consecutive_failures, providers_to_reset


# ============ 路由 ============

@router.get("/master-key", response_model=MasterKeyResponse)
async def get_master_key():
    """
    获取 Master Key（仅用于首次配置）
    生产环境应禁用此接口
    """
    return MasterKeyResponse(master_key=settings.master_key)


class PagedResponse(BaseModel):
    """分页响应"""
    items: List[Any]
    total: int
    page: int
    limit: int


def parse_pagination(page: Optional[int], limit: int, offset: Optional[int]) -> tuple[int, int, int]:
    """解析分页参数"""
    if limit <= 0:
        limit = 50

    if offset is not None:
        offset_value = max(int(offset), 0)
        page_value = offset_value // limit + 1
        return page_value, limit, offset_value

    page_value = max(int(page or 1), 1)
    offset_value = (page_value - 1) * limit
    return page_value, limit, offset_value


@router.get("/image/models", response_model=ImageModelListResponse)
async def list_image_models(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取图片广场模型列表"""
    items = []
    for config in IMAGE_MODEL_OPTIONS:
        keys = await pool_manager.get_all_keys(
            db,
            active_only=True,
        )
        keys = [key for key in keys if key_supports_image_model(key, config["model"])]
        items.append(
            ImageModelOption(
                model=config["model"],
                display_name=config["display_name"],
                provider=config["provider"],
                request_formats=list(config["request_formats"]),
                candidate_request_formats=list(config.get("candidate_request_formats") or config["request_formats"]),
                max_count=int(config["max_count"]),
                available_key_count=len(keys),
                total_remaining_image_count=await calculate_total_remaining_image_count(db, keys, config["model"]),
            )
        )
    return ImageModelListResponse(items=items)


@router.post("/image/validate", response_model=ImageGenerationValidateResponse)
async def validate_image_generation(
    data: ImageGenerationValidateRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """验证指定 Key 的图片生成能力"""
    model_config = get_image_model_config(data.model)
    model = model_config["model"]
    if normalize_model_name(model) not in IMAGE_MODEL_VALIDATE_MODELS:
        raise HTTPException(status_code=400, detail="当前模型暂不支持生图验证")

    key = await pool_manager.get_key_by_id(db, data.api_key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    if not key_supports_image_model(key, model):
        raise HTTPException(status_code=400, detail="该 Key 未配置支持当前图片模型")

    request_format = normalize_image_request_format(model_config, data.request_format, include_candidates=True)
    prompt = normalize_optional_text(data.prompt) or IMAGE_MODEL_VALIDATE_PROMPT
    try:
        result = await proxy_service.generate_image(
            key,
            model=model,
            prompt=prompt,
            size=data.size,
            quality=data.quality,
            n=1,
            request_format=request_format,
            mode="text_to_image",
            input_images=[],
            probe_timeout_seconds=data.timeout_seconds if data.probe_only else None,
        )
    except Exception as exc:
        result = {
            "status": "error",
            "status_code": None,
            "response_time_ms": 0,
            "path": None,
            "images": [],
            "response_data": {"error": {"message": str(exc) or exc.__class__.__name__}},
            "error_message": f"图片验证失败：{str(exc) or exc.__class__.__name__}",
            "failure_category": "internal_error",
        }
    now = datetime.utcnow()
    finished_at = datetime.utcnow()
    duration_ms = int(result.get("response_time_ms") or 0)
    if duration_ms <= 0:
        duration_ms = calculate_duration_ms(now, finished_at)
    images = result.get("images") or []
    preview = get_image_validate_preview(images)

    if result.get("status") == "success" and images:
        from models import ImageGenerationTask, ImageGenerationTaskResult

        request_params = {
            "size": data.size,
            "quality": data.quality,
            "count": 1,
            "request_format": request_format,
            "mode": "validate",
        }
        task = ImageGenerationTask(
            provider=key.provider,
            api_key_id=key.id,
            api_key_name=key.name,
            base_url=key.base_url,
            model=model,
            prompt=prompt,
            request_params_json=json.dumps(request_params, ensure_ascii=False),
            status="success",
            total_count=1,
            completed_count=1,
            success_count=1,
            error_count=0,
            created_at=now,
            started_at=now,
            finished_at=finished_at,
            updated_at=finished_at,
            duration_ms=duration_ms,
        )
        db.add(task)
        await db.flush()

        image = images[0] or {}
        row = ImageGenerationTaskResult(
            task_id=task.id,
            image_index=1,
            api_key_id=key.id,
            provider=key.provider,
            api_key_name=key.name,
            model=model,
            status="success",
            image_url=image.get("image_url"),
            image_base64=image.get("image_base64"),
            local_path=None,
            mime_type=image.get("mime_type") or "image/png",
            width=image.get("width"),
            height=image.get("height"),
            file_size_bytes=None,
            result_meta_json=json.dumps(image.get("meta") or {}, ensure_ascii=False),
            created_at=now,
            started_at=now,
            finished_at=finished_at,
            updated_at=finished_at,
            duration_ms=duration_ms,
        )
        db.add(row)
        await upsert_image_key_model_stats(
            db,
            key,
            model,
            total_delta=1,
            success_delta=1,
            error_delta=0,
            generated_at=finished_at,
        )
        await db.commit()
        await db.refresh(task)
        await db.refresh(row)
        preview = {
            "image_url": row.image_url,
            "image_base64": row.image_base64,
            "mime_type": row.mime_type,
            "width": row.width,
            "height": row.height,
        }
        pool_manager.clear_key_cooldown(key.id)
    elif result.get("status") == "error":
        from models import ImageGenerationTask, ImageGenerationTaskResult

        category = result.get("failure_category") or "unknown"
        status_code = result.get("status_code")
        error_message = result.get("error_message") or "图片生成失败"
        request_params = {
            "size": data.size,
            "quality": data.quality,
            "count": 1,
            "request_format": request_format,
            "mode": "validate",
        }
        task = ImageGenerationTask(
            provider=key.provider,
            api_key_id=key.id,
            api_key_name=key.name,
            base_url=key.base_url,
            model=model,
            prompt=prompt,
            request_params_json=json.dumps(request_params, ensure_ascii=False),
            status="error",
            total_count=1,
            completed_count=1,
            success_count=0,
            error_count=1,
            failure_category_stats_json=json.dumps({category: 1}, ensure_ascii=False),
            error_summary=error_message,
            created_at=now,
            started_at=now,
            finished_at=finished_at,
            updated_at=finished_at,
            duration_ms=duration_ms,
        )
        db.add(task)
        await db.flush()
        row = ImageGenerationTaskResult(
            task_id=task.id,
            image_index=1,
            api_key_id=key.id,
            provider=key.provider,
            api_key_name=key.name,
            model=model,
            status="error",
            error_category=category,
            error_detail=error_message,
            result_meta_json=json.dumps(result.get("response_data") or {}, ensure_ascii=False, default=str),
            created_at=now,
            started_at=now,
            finished_at=finished_at,
            updated_at=finished_at,
            duration_ms=duration_ms,
        )
        db.add(row)
        balance_depleted = is_image_balance_depleted_failure(error_message, result.get("response_data"))
        count_key_failure = balance_depleted or should_count_image_key_failure(category, status_code, error_message)
        if count_key_failure:
            await upsert_image_key_model_stats(
                db,
                key,
                model,
                total_delta=1,
                success_delta=0,
                error_delta=1,
                generated_at=finished_at,
            )
            cooldown_seconds = pool_manager.get_cooldown_seconds_for_status(status_code)
            pool_manager.mark_key_cooldown(key.id, cooldown_seconds)
        balance_providers: list[str] = []
        if balance_depleted:
            balance_providers = await apply_image_balance_depleted_policy(db, key, model, finished_at)
            logger.warning(
                "image_key_balance_depleted key_id=%s key_name=%s provider=%s model=%s error=%s",
                key.id,
                key.name,
                key.provider,
                model,
                error_message,
            )
        await db.commit()
        for p in balance_providers:
            pool_manager.reset_index(p)
        if count_key_failure:
            try:
                _, failure_providers = await apply_image_failure_policy(db, key)
                await db.commit()
                for p in failure_providers:
                    pool_manager.reset_index(p)
            except Exception:
                await db.rollback()

    return ImageGenerationValidateResponse(
        api_key_id=int(key.id),
        api_key_name=key.name or f"Key {key.id}",
        provider=key.provider or "",
        model=model,
        status=result.get("status") or "error",
        status_code=result.get("status_code"),
        response_time_ms=int(result.get("response_time_ms") or 0),
        request_format=request_format,
        path=result.get("path"),
        image_count=len(result.get("images") or []),
        image_url=preview.get("image_url"),
        image_base64=preview.get("image_base64"),
        mime_type=preview.get("mime_type"),
        width=preview.get("width"),
        height=preview.get("height"),
        failure_category=result.get("failure_category") if result.get("status") == "error" else None,
        error_message=result.get("error_message") if result.get("status") == "error" else None,
        checked_at=datetime.utcnow(),
    )


async def run_image_generation_task(
    task_id: int,
    api_key_id: int,
    *,
    model: str,
    prompt: str,
    size: Optional[str],
    quality: Optional[str],
    count: int,
    request_format: str,
    mode: str,
    input_images: list[dict],
):
    """后台执行图片生成任务"""
    from database import async_session_maker
    from models import ApiKey, ImageGenerationTask, ImageGenerationTaskResult

    async with async_session_maker() as db:
        task = await db.get(ImageGenerationTask, task_id)
        api_key = await db.get(ApiKey, api_key_id)
        if not task or not api_key:
            logger.warning("image_generation_background_missing task_id=%s key_id=%s", task_id, api_key_id)
            return

        api_key_snapshot = build_api_key_snapshot(api_key)
        task_snapshot = {
            "id": int(task.id),
            "model": task.model,
            "started_at": task.started_at,
        }
        started_at = task.started_at or datetime.utcnow()
        balance_providers: list[str] = []
        tried_key_ids: list[int] = [api_key_id]
        max_key_retries = 2

        try:
            generation_result = await proxy_service.generate_image(
                api_key,
                model=model,
                prompt=prompt,
                size=size,
                quality=quality,
                n=count,
                request_format=request_format,
                mode=mode,
                input_images=input_images,
                upstream_tracking_id=f"cpa-image-task-{task_id}",
            )

            # 非 Key 自身问题的失败（如上游模型不支持），尝试切换 Key 重试
            if generation_result.get("status") != "success":
                category = generation_result.get("failure_category") or "unknown"
                status_code = generation_result.get("status_code")
                error_message = generation_result.get("error_message") or ""
                is_cf = is_cloudflare_image_timeout(error_message, generation_result.get("response_data"), status_code)
                is_non_key = is_non_key_image_failure(category, status_code, error_message)
                if not is_cf and is_non_key:
                    for retry_idx in range(max_key_retries):
                        new_key = await pool_manager.get_next_key(
                            db, provider=None, model=model,
                            exclude_key_ids=tried_key_ids, randomize_start=True,
                        )
                        if not new_key:
                            break
                        tried_key_ids.append(int(new_key.id))
                        logger.info(
                            "image_key_retry task_id=%s attempt=%s new_key_id=%s new_key_name=%s reason=%s",
                            task_id, retry_idx + 1, new_key.id, getattr(new_key, "name", ""), error_message[:120],
                        )
                        retry_result = await proxy_service.generate_image(
                            new_key,
                            model=model,
                            prompt=prompt,
                            size=size,
                            quality=quality,
                            n=count,
                            request_format=request_format,
                            mode=mode,
                            input_images=input_images,
                            upstream_tracking_id=f"cpa-image-task-{task_id}",
                        )
                        if retry_result.get("status") == "success":
                            generation_result = retry_result
                            api_key = new_key
                            api_key_snapshot = build_api_key_snapshot(new_key)
                            break
                        retry_err = retry_result.get("error_message") or ""
                        retry_cat = retry_result.get("failure_category") or "unknown"
                        retry_sc = retry_result.get("status_code")
                        if is_cloudflare_image_timeout(retry_err, retry_result.get("response_data"), retry_sc):
                            generation_result = retry_result
                            api_key = new_key
                            api_key_snapshot = build_api_key_snapshot(new_key)
                            break
                        if not is_non_key_image_failure(retry_cat, retry_sc, retry_err):
                            generation_result = retry_result
                            api_key = new_key
                            api_key_snapshot = build_api_key_snapshot(new_key)
                            break

            # 长网络调用后重新加载 api_key，避免使用过期的 ORM 对象
            fresh_api_key = await db.get(ApiKey, api_key_id)
            if fresh_api_key:
                api_key = fresh_api_key

            finished_at = datetime.utcnow()
            duration_ms = int(generation_result.get("response_time_ms") or 0)
            if duration_ms <= 0:
                duration_ms = calculate_duration_ms(started_at, finished_at)
            images = generation_result.get("images") or []
            rows = []
            count_key_failure = False
            cloudflare_timeout = False

            if generation_result.get("status") == "success" and images:
                selected_images = images[:count]
                for index, image in enumerate(selected_images, start=1):
                    image_url = normalize_image_output_text(image.get("image_url"))
                    image_base64 = normalize_image_output_text(image.get("image_base64"))
                    saved_file = await persist_output_image_file(
                        task_id,
                        index,
                        {
                            "image_url": image_url,
                            "image_base64": image_base64,
                            "mime_type": image.get("mime_type") or "image/png",
                            "width": image.get("width"),
                            "height": image.get("height"),
                        },
                    )
                    row = ImageGenerationTaskResult(
                        task_id=task_id,
                        image_index=index,
                        api_key_id=api_key_snapshot["id"],
                        provider=api_key_snapshot["provider"],
                        api_key_name=api_key_snapshot["name"],
                        model=model,
                        status="success",
                        image_url=image_url,
                        image_base64=image_base64,
                        local_path=saved_file.get("local_path"),
                        mime_type=saved_file.get("mime_type") or image.get("mime_type") or "image/png",
                        width=image.get("width") or saved_file.get("width"),
                        height=image.get("height") or saved_file.get("height"),
                        file_size_bytes=saved_file.get("file_size_bytes"),
                        result_meta_json=json.dumps(
                            {"upstream_task": generation_result.get("upstream_task") or {}, "image_meta": image.get("meta") or {}},
                            ensure_ascii=False,
                            default=str,
                        ),
                        created_at=started_at,
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_ms=duration_ms,
                        updated_at=finished_at,
                    )
                    db.add(row)
                    rows.append(row)

                # 生成成功后清空冗余大字段，图片已存本地文件
                for row in rows:
                    if row.local_path:
                        row.result_meta_json = None
                        row.image_base64 = None

                task.provider = api_key_snapshot["provider"]
                task.api_key_id = api_key_snapshot["id"]
                task.api_key_name = api_key_snapshot["name"]
                task.base_url = api_key_snapshot["base_url"]
                task.status = "success"
                task.completed_count = len(rows)
                task.success_count = len(rows)
                task.error_count = 0
                task.failure_category_stats_json = None
                task.error_summary = None
                await upsert_image_key_model_stats(
                    db,
                    api_key_snapshot,
                    model,
                    total_delta=count,
                    success_delta=len(rows),
                    error_delta=0,
                    generated_at=finished_at,
                )
                pool_manager.clear_key_cooldown(api_key_snapshot["id"])
            else:
                category = generation_result.get("failure_category") or "unknown"
                status_code = generation_result.get("status_code")
                error_message = generation_result.get("error_message") or "图片生成失败"
                cloudflare_timeout = is_cloudflare_image_timeout(
                    error_message,
                    generation_result.get("response_data"),
                    status_code,
                )
                should_auto_refresh = cloudflare_timeout and is_newapi_key(api_key)
                if cloudflare_timeout and not should_auto_refresh:
                    error_message = f"{error_message}；当前 Key 类型不支持图片回填查询，已跳过自动回填"
                    category = "image_refresh_not_supported"
                row_status = "pending" if should_auto_refresh else "error"
                row = ImageGenerationTaskResult(
                    task_id=task_id,
                    image_index=1,
                    api_key_id=api_key_snapshot["id"],
                    provider=api_key_snapshot["provider"],
                    api_key_name=api_key_snapshot["name"],
                    model=model,
                    status=row_status,
                    error_category=category if not should_auto_refresh else None,
                    error_detail=None if should_auto_refresh else error_message,
                    result_meta_json=json.dumps(
                        {
                            "upstream_task": generation_result.get("upstream_task") or {},
                            "response_data": generation_result.get("response_data") or {},
                            "request_body": generation_result.get("request_body") or {},
                            "request_path": generation_result.get("path"),
                            "request_url": generation_result.get("url"),
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                    created_at=started_at,
                    started_at=started_at,
                    finished_at=None if should_auto_refresh else finished_at,
                    duration_ms=duration_ms,
                    updated_at=finished_at,
                )
                db.add(row)
                rows.append(row)
                task.provider = api_key_snapshot["provider"]
                task.api_key_id = api_key_snapshot["id"]
                task.api_key_name = api_key_snapshot["name"]
                task.base_url = api_key_snapshot["base_url"]
                cloudflare_timeout = should_auto_refresh
                if should_auto_refresh:
                    task.status = "running"
                    task.pending_refresh = True
                    task.completed_count = 0
                    task.success_count = 0
                    task.error_count = 0
                    task.finished_at = None
                    task.failure_category_stats_json = None
                    task.error_summary = None
                else:
                    task.status = "error"
                    task.completed_count = 1
                    task.success_count = 0
                    task.error_count = 1
                    task.failure_category_stats_json = json.dumps({category: 1}, ensure_ascii=False)
                    task.error_summary = error_message
                balance_depleted = is_image_balance_depleted_failure(error_message, generation_result.get("response_data"))
                if not cloudflare_timeout:
                    count_key_failure = balance_depleted or should_count_image_key_failure(category, status_code, error_message)
                    if count_key_failure:
                        await upsert_image_key_model_stats(
                            db,
                            api_key_snapshot,
                            model,
                            total_delta=1,
                            success_delta=0,
                            error_delta=1,
                            generated_at=finished_at,
                        )
                        cooldown_seconds = pool_manager.get_cooldown_seconds_for_status(status_code)
                        pool_manager.mark_key_cooldown(api_key_snapshot["id"], cooldown_seconds)
                balance_providers: list[str] = []
                if balance_depleted:
                    try:
                        balance_providers = await apply_image_balance_depleted_policy(db, api_key, model, finished_at)
                    except Exception as balance_policy_error:
                        logger.exception(
                            "image_balance_depleted_policy_failed task_id=%s key_id=%s provider=%s model=%s error=%s",
                            task_id,
                            api_key_snapshot["id"],
                            api_key_snapshot["provider"],
                            model,
                            str(balance_policy_error) or balance_policy_error.__class__.__name__,
                        )
                    logger.warning(
                        "image_key_balance_depleted key_id=%s key_name=%s provider=%s model=%s error=%s",
                        api_key_snapshot["id"],
                        api_key_snapshot["name"],
                        api_key_snapshot["provider"],
                        model,
                        error_message,
                    )

            if not cloudflare_timeout:
                task.finished_at = finished_at
            task.duration_ms = duration_ms
            task.updated_at = finished_at
            await db.commit()
            logger.info(
                "image_generation_background_committed task_id=%s key_id=%s provider=%s model=%s status=%s rows=%s images=%s",
                task_id,
                api_key_snapshot["id"],
                api_key_snapshot["provider"],
                model,
                task.status,
                len(rows),
                len(images),
            )

            for p in balance_providers:
                pool_manager.reset_index(p)

            if cloudflare_timeout:
                asyncio.create_task(auto_refresh_cloudflare_timeout_image_task(task_id))

            if count_key_failure:
                try:
                    fresh_key = await db.get(ApiKey, int(api_key_snapshot["id"]))
                    if fresh_key:
                        _, failure_providers = await apply_image_failure_policy(db, fresh_key)
                        await db.commit()
                        for p in failure_providers:
                            pool_manager.reset_index(p)
                except Exception as policy_error:
                    logger.exception(
                        "image_generation_failure_policy_failed task_id=%s key_id=%s provider=%s model=%s error=%s",
                        task_id,
                        api_key_snapshot["id"],
                        api_key_snapshot["provider"],
                        model,
                        str(policy_error) or policy_error.__class__.__name__,
                    )
                    await db.rollback()
        except asyncio.CancelledError:
            logger.warning("image_generation_background_cancelled task_id=%s key_id=%s", task_id, api_key_id)
            raise
        except Exception as exc:
            try:
                await db.rollback()
                await finish_image_task_with_internal_error(
                    db,
                    task,
                    api_key_snapshot,
                    exc,
                    task_snapshot=task_snapshot,
                    api_key_snapshot=api_key_snapshot,
                )
            except Exception as handler_error:
                logger.exception(
                    "image_generation_background_error_handler_failed task_id=%s key_id=%s provider=%s model=%s error=%s",
                    task_id,
                    api_key_snapshot.get("id"),
                    api_key_snapshot.get("provider"),
                    model,
                    str(handler_error) or handler_error.__class__.__name__,
                )


@router.post("/image/generations", response_model=ImageGenerationTaskResponse)
async def create_image_generation(
    data: ImageGenerationRequest,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    """创建图片生成任务"""
    from models import ImageGenerationTask

    prompt = normalize_optional_text(data.prompt)
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt 不能为空")

    model_config = get_image_model_config(data.model)
    model = model_config["model"]
    request_format = normalize_image_request_format(model_config, data.request_format)
    count = min(int(data.count or 1), int(model_config["max_count"] or 1))
    mode, input_images, input_image_meta = normalize_image_inputs(data.mode, data.input_images)

    api_key = await pool_manager.get_next_key(db, provider=None, model=model, randomize_start=True)
    if not api_key:
        raise HTTPException(status_code=404, detail="没有启用且支持该图片模型的 Key")

    api_key_snapshot = build_api_key_snapshot(api_key)
    now = datetime.utcnow()
    request_params = {
        "size": data.size,
        "quality": data.quality,
        "count": count,
        "request_format": request_format,
        "mode": mode,
        "input_images_count": len(input_image_meta),
        "input_image_names": [item["name"] for item in input_image_meta],
        "input_image_mime_types": [item["mime_type"] for item in input_image_meta],
        "input_image_sizes": [item["size_bytes"] for item in input_image_meta],
        "input_image_urls": [item.get("image_url") or "" for item in input_image_meta],
    }
    task = ImageGenerationTask(
        provider=api_key_snapshot["provider"],
        api_key_id=api_key_snapshot["id"],
        api_key_name=api_key_snapshot["name"],
        base_url=api_key_snapshot["base_url"],
        model=model,
        prompt=prompt,
        request_params_json=json.dumps(request_params, ensure_ascii=False),
        status="running",
        total_count=count,
        completed_count=0,
        success_count=0,
        error_count=0,
        started_at=now,
        updated_at=now,
        user_id=auth_info.get("user_id"),
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    # 将上传的 data URL 参考图落盘，替换 input_image_urls 为可访问的 API URL
    saved_urls = []
    for idx, meta in enumerate(input_image_meta):
        if meta.get("image_url"):
            saved_urls.append(meta["image_url"])
        elif meta.get("data_url"):
            local_path = _save_input_image_file(task.id, idx + 1, meta["data_url"])
            if local_path:
                saved_urls.append(f"/api/admin/image/tasks/{task.id}/input/{idx + 1}")
            else:
                saved_urls.append("")
        else:
            saved_urls.append("")
    request_params["input_image_urls"] = saved_urls
    task.request_params_json = json.dumps(request_params, ensure_ascii=False)
    await db.commit()

    asyncio.create_task(
        run_image_generation_task(
            int(task.id),
            int(api_key_snapshot["id"]),
            model=model,
            prompt=prompt,
            size=data.size,
            quality=data.quality,
            count=count,
            request_format=request_format,
            mode=mode,
            input_images=input_images,
        )
    )

    return to_image_task_response(task, [])


@router.get("/image/auto-refresh-config", response_model=ImageAutoRefreshConfigResponse)
async def get_image_auto_refresh_config_api(
    _: bool = Depends(verify_admin_key),
):
    """获取图片自动回填配置"""
    return get_image_auto_refresh_config()


@router.put("/image/auto-refresh-config", response_model=ImageAutoRefreshConfigResponse)
async def update_image_auto_refresh_config(
    data: ImageAutoRefreshConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新图片自动回填配置"""
    payload = data.model_dump()
    export_config.update(payload)
    persist_export_config()
    return get_image_auto_refresh_config()


@router.get("/image/stale-task-cleanup-config", response_model=StaleTaskCleanupConfigResponse)
async def get_stale_task_cleanup_config_api(
    _: bool = Depends(verify_admin_key),
):
    """获取过期任务回收配置"""
    return get_stale_task_cleanup_config()


@router.put("/image/stale-task-cleanup-config", response_model=StaleTaskCleanupConfigResponse)
async def update_stale_task_cleanup_config(
    data: StaleTaskCleanupConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新过期任务回收配置"""
    payload = data.model_dump()
    export_config.update(payload)
    persist_export_config()
    return get_stale_task_cleanup_config()


@router.get("/image/capabilities", response_model=ImageCapabilityResponse)
async def get_image_capabilities(
    _: bool = Depends(verify_admin_key),
):
    """获取图片增强能力状态"""
    return ImageCapabilityResponse(psd_enabled=has_psd_enhancement())


@router.get("/image/storage-config", response_model=ImageStorageConfigResponse)
async def get_image_storage_config(
    _: bool = Depends(verify_admin_key),
):
    """获取图片存储配置"""
    if not has_psd_enhancement():
        storage_dir = get_default_image_storage_dir()
        return ImageStorageConfigResponse(
            storage_dir=str(storage_dir),
            default_storage_dir=str(storage_dir),
        )

    storage_dir = load_image_storage_dir()
    return ImageStorageConfigResponse(
        storage_dir=str(storage_dir),
        default_storage_dir=str(get_default_image_storage_dir()),
    )


@router.put("/image/storage-config", response_model=ImageStorageConfigResponse)
async def update_image_storage_config(
    data: ImageStorageConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新图片存储配置"""
    if not has_psd_enhancement():
        raise HTTPException(status_code=503, detail="图片增强包未安装，无法修改图片存储配置")

    storage_dir = normalize_storage_dir(data.storage_dir)
    save_image_storage_dir(storage_dir)
    return ImageStorageConfigResponse(
        storage_dir=str(storage_dir),
        default_storage_dir=str(get_default_image_storage_dir()),
    )


@router.delete("/image/tasks/{task_id}", response_model=ImageTaskDeleteResponse)
async def delete_image_task(
    task_id: int,
    data: ImageTaskDeleteRequest,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    """删除图片历史任务"""
    from models import ImageGenerationTask, ImageGenerationTaskResult

    task_result = await db.execute(
        select(ImageGenerationTask)
        .where(ImageGenerationTask.id == task_id)
    )
    task = task_result.scalar_one_or_none()
    if not task or task.is_deleted:
        return ImageTaskDeleteResponse(task_id=task_id, deleted_results=0, deleted_files=0)

    if not auth_info.get("is_admin") and task.user_id != auth_info.get("user_id"):
        return ImageTaskDeleteResponse(task_id=task_id, deleted_results=0, deleted_files=0)

    result = await db.execute(
        select(ImageGenerationTaskResult).where(ImageGenerationTaskResult.task_id == task_id)
    )
    rows = list(result.scalars().all())
    deleted_files = 0
    if data.delete_files:
        for row in rows:
            if not row.local_path:
                continue
            try:
                if delete_managed_image_file(row.local_path):
                    deleted_files += 1
                    row.local_path = None
                    row.file_size_bytes = None
                    row.updated_at = datetime.utcnow()
            except HTTPException as exc:
                if exc.status_code == 404:
                    row.local_path = None
                    row.file_size_bytes = None
                    row.updated_at = datetime.utcnow()
                    continue
                raise
            except OSError as exc:
                raise HTTPException(status_code=400, detail=f"图片文件删除失败：{exc}") from exc

    task.is_deleted = True
    task.updated_at = datetime.utcnow()
    await db.commit()

    return ImageTaskDeleteResponse(
        task_id=task_id,
        deleted_results=len(rows),
        deleted_files=deleted_files,
    )


@router.get("/image/results/{result_id}/file")
async def get_image_result_file(
    result_id: int,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """读取本地图片结果文件"""
    from models import ImageGenerationTaskResult

    result = await db.execute(select(ImageGenerationTaskResult).where(ImageGenerationTaskResult.id == result_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="图片结果不存在")

    expected_token = image_result_file_token(row.id, row.local_path)
    if not token or not expected_token or not hmac.compare_digest(token, expected_token):
        raise HTTPException(status_code=403, detail="无效的图片访问令牌")

    path = resolve_managed_image_file(row.local_path)
    return FileResponse(path, media_type=guess_local_image_media_type(row, path))


@router.get("/image/tasks/{task_id}/input/{index}")
async def get_input_image_file(
    task_id: int,
    index: int,
):
    """读取图生图上传的参考图本地文件"""
    storage_dir = load_image_storage_dir()
    # 按命名规则搜索匹配文件
    for ext in (".png", ".jpg", ".jpeg", ".webp"):
        candidate = storage_dir / f"input-{int(task_id)}-{int(index)}{ext}"
        if candidate.is_file():
            return FileResponse(candidate)
    raise HTTPException(status_code=404, detail="参考图文件不存在")


@router.post("/image/results/{result_id}/save-local", response_model=ImageGenerationResultResponse)
async def save_image_result_local(
    result_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """保存图片结果到本地"""
    from models import ImageGenerationTaskResult

    result = await db.execute(select(ImageGenerationTaskResult).where(ImageGenerationTaskResult.id == result_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="图片结果不存在")
    if row.status != "success":
        raise HTTPException(status_code=400, detail="只能保存成功的图片结果")

    if row.local_path:
        try:
            resolve_managed_image_file(row.local_path)
            return to_image_result_response(row)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise

    image = {
        "image_url": row.image_url,
        "image_base64": row.image_base64,
        "mime_type": row.mime_type or "image/png",
        "width": row.width,
        "height": row.height,
    }
    if not image["image_url"] and not image["image_base64"]:
        raise HTTPException(status_code=400, detail="图片结果没有可保存的内容")

    saved_file = await persist_output_image_file(row.task_id, row.image_index, image)
    if not saved_file:
        raise HTTPException(status_code=400, detail="图片保存到本地失败")

    apply_saved_image_file(row, saved_file)
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return to_image_result_response(row)


@router.post("/image/results/{result_id}/open-folder", response_model=ImageFileActionResponse)
async def open_image_result_folder(
    result_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """打开图片所在文件夹"""
    from models import ImageGenerationTaskResult

    result = await db.execute(select(ImageGenerationTaskResult).where(ImageGenerationTaskResult.id == result_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="图片结果不存在")

    path = resolve_managed_image_file(row.local_path)
    open_windows_folder(path, reveal=False)
    return ImageFileActionResponse(ok=True, path=str(path.parent))


@router.post("/image/results/{result_id}/reveal-file", response_model=ImageFileActionResponse)
async def reveal_image_result_file(
    result_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """定位图片文件"""
    from models import ImageGenerationTaskResult

    result = await db.execute(select(ImageGenerationTaskResult).where(ImageGenerationTaskResult.id == result_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="图片结果不存在")

    path = resolve_managed_image_file(row.local_path)
    open_windows_folder(path, reveal=True)
    return ImageFileActionResponse(ok=True, path=str(path))


@router.get("/image/results/{result_id}/psd")
async def get_image_result_psd(
    result_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """导出图片结果为 PSD（Photoshop 图层文件）"""
    if not has_psd_enhancement():
        raise HTTPException(status_code=503, detail="PSD 导出需要增强包，请安装图像增强组件后重试")

    from services.psd_utils import convert_result_to_psd

    psd_path = await convert_result_to_psd(result_id, db)
    if not psd_path or not psd_path.exists():
        raise HTTPException(status_code=404, detail="无法生成 PSD 文件，请确认图片已保存到本地且状态为成功")

    return FileResponse(
        psd_path,
        media_type="image/vnd.adobe.photoshop",
        filename=f"image-result-{result_id}.psd",
    )


@router.get("/image/tasks", response_model=ImageGenerationTaskListResponse)
async def list_image_tasks(
    model: Optional[str] = None,
    status: Optional[str] = None,
    api_key_id: Optional[int] = None,
    user_id: Optional[int] = Query(default=None),
    page: Optional[int] = None,
    limit: int = 20,
    offset: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    """查询图片生成历史任务"""
    from models import ImageGenerationTask

    # 普通用户只能看自己的任务
    effective_user_id = user_id if auth_info.get("is_admin") else auth_info.get("user_id")

    page_value, limit_value, offset_value = parse_pagination(page, limit, offset)
    query = select(ImageGenerationTask).where(ImageGenerationTask.is_deleted.is_(False))
    count_query = select(func.count(ImageGenerationTask.id)).where(ImageGenerationTask.is_deleted.is_(False))

    model_value = normalize_optional_text(model)
    status_value = normalize_optional_text(status)
    if model_value:
        query = query.where(ImageGenerationTask.model == model_value)
        count_query = count_query.where(ImageGenerationTask.model == model_value)
    if status_value:
        query = query.where(ImageGenerationTask.status == status_value)
        count_query = count_query.where(ImageGenerationTask.status == status_value)
    if api_key_id is not None:
        query = query.where(ImageGenerationTask.api_key_id == api_key_id)
        count_query = count_query.where(ImageGenerationTask.api_key_id == api_key_id)
    if effective_user_id:
        query = query.where(ImageGenerationTask.user_id == effective_user_id)
        count_query = count_query.where(ImageGenerationTask.user_id == effective_user_id)

    query = query.order_by(ImageGenerationTask.created_at.desc(), ImageGenerationTask.id.desc()).offset(offset_value).limit(limit_value)
    total = int((await db.execute(count_query)).scalar_one() or 0)
    result = await db.execute(query)
    tasks = list(result.scalars().all())

    return ImageGenerationTaskListResponse(
        items=[to_image_task_response(item) for item in tasks],
        total=total,
        page=page_value,
        limit=limit_value,
    )


@router.get("/image/tasks/{task_id}", response_model=ImageGenerationTaskResponse)
async def get_image_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    """查询图片生成任务详情"""
    from models import ImageGenerationTask, ImageGenerationTaskResult

    task_result = await db.execute(
        select(ImageGenerationTask)
        .where(ImageGenerationTask.id == task_id)
        .where(ImageGenerationTask.is_deleted.is_(False))
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="图片生成任务不存在")

    # 普通用户只能查看自己的任务
    if not auth_info.get("is_admin") and task.user_id != auth_info.get("user_id"):
        raise HTTPException(status_code=404, detail="图片生成任务不存在")

    result = await db.execute(
        select(ImageGenerationTaskResult)
        .where(ImageGenerationTaskResult.task_id == task_id)
        .order_by(ImageGenerationTaskResult.image_index.asc(), ImageGenerationTaskResult.id.asc())
    )
    return to_image_task_response(task, list(result.scalars().all()))


@router.post("/image/tasks/{task_id}/refresh", response_model=ImageGenerationTaskResponse)
async def refresh_image_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    """重新抓取图片生成任务结果"""
    from models import ImageGenerationTask, ImageGenerationTaskResult

    task_result = await db.execute(
        select(ImageGenerationTask)
        .where(ImageGenerationTask.id == task_id)
        .where(ImageGenerationTask.is_deleted.is_(False))
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="图片生成任务不存在")

    if not auth_info.get("is_admin") and task.user_id != auth_info.get("user_id"):
        raise HTTPException(status_code=404, detail="图片生成任务不存在")

    task, rows, success, message = await refresh_image_task_from_task_log(db, task)
    if not success:
        result = await db.execute(
            select(ImageGenerationTaskResult)
            .where(ImageGenerationTaskResult.task_id == task_id)
            .order_by(ImageGenerationTaskResult.image_index.asc(), ImageGenerationTaskResult.id.asc())
        )
        rows = list(result.scalars().all())
        raise HTTPException(status_code=400, detail=message)
    return to_image_task_response(task, rows)


@router.post("/image/tasks/{task_id}/refresh-by-upstream-id", response_model=ImageGenerationTaskResponse)
async def refresh_image_task_by_upstream_id(
    task_id: int,
    data: ImageTaskRefreshByUpstreamRequest,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    """按用户提供的上游任务 ID，通过 magic666 任务日志精确查询并回填"""
    from models import ImageGenerationTask, ImageGenerationTaskResult

    upstream_task_id = normalize_optional_text(data.upstream_task_id)
    if not upstream_task_id:
        raise HTTPException(status_code=400, detail="上游任务 ID 不能为空")

    task_result = await db.execute(
        select(ImageGenerationTask)
        .where(ImageGenerationTask.id == task_id)
        .where(ImageGenerationTask.is_deleted.is_(False))
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="图片生成任务不存在")

    if not auth_info.get("is_admin") and task.user_id != auth_info.get("user_id"):
        raise HTTPException(status_code=404, detail="图片生成任务不存在")

    task, rows, success, message = await refresh_image_task_from_task_log(db, task, upstream_task_id=upstream_task_id)
    if not success:
        result = await db.execute(
            select(ImageGenerationTaskResult)
            .where(ImageGenerationTaskResult.task_id == task_id)
            .order_by(ImageGenerationTaskResult.image_index.asc(), ImageGenerationTaskResult.id.asc())
        )
        rows = list(result.scalars().all())
        raise HTTPException(status_code=400, detail=message)
    return to_image_task_response(task, rows)


@router.get("/image/tasks/{task_id}/results", response_model=ImageGenerationResultListResponse)
async def list_image_task_results(
    task_id: int,
    page: Optional[int] = None,
    limit: int = 20,
    offset: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询图片生成任务结果"""
    from models import ImageGenerationTask, ImageGenerationTaskResult

    exists_result = await db.execute(
        select(ImageGenerationTask.id)
        .where(ImageGenerationTask.id == task_id)
        .where(ImageGenerationTask.is_deleted.is_(False))
    )
    if not exists_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="图片生成任务不存在")

    page_value, limit_value, offset_value = parse_pagination(page, limit, offset)
    total = int((await db.execute(
        select(func.count(ImageGenerationTaskResult.id)).where(ImageGenerationTaskResult.task_id == task_id)
    )).scalar_one() or 0)
    result = await db.execute(
        select(ImageGenerationTaskResult)
        .where(ImageGenerationTaskResult.task_id == task_id)
        .order_by(ImageGenerationTaskResult.image_index.asc(), ImageGenerationTaskResult.id.asc())
        .offset(offset_value)
        .limit(limit_value)
    )
    return ImageGenerationResultListResponse(
        items=[to_image_result_response(item) for item in result.scalars().all()],
        total=total,
        page=page_value,
        limit=limit_value,
    )


@router.get("/image/key-stats", response_model=ImageKeyStatsResponse)
async def get_image_key_stats(
    model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询每个 Key 的图片生成成功率"""
    from models import ApiKey, ImageKeyModelStats

    model_value = normalize_optional_text(model)
    normalized_model = normalize_image_model_alias(model_value) if model_value else ""
    current_model_price_units = IMAGE_MODEL_PRICE_UNITS.get(normalized_model)
    grouped: dict[int, dict[str, Any]] = {}
    key_map: dict[int, Any] = {}

    if model_value:
        available_keys = await pool_manager.get_all_keys(
            db,
            active_only=True,
        )
        available_keys = [key for key in available_keys if key_supports_image_model(key, model_value)]
        for key in available_keys:
            key_id = int(key.id)
            key_map[key_id] = key
            grouped[key_id] = {
                "api_key_id": key_id,
                "api_key_name": key.name or f"Key {key.id}",
                "provider": key.provider or "",
                "model": model_value,
                "weight": int(key.weight or 0),
                "remaining_amount": None,
                "remaining_image_count": None,
                "total_count": 0,
                "success_count": 0,
                "error_count": 0,
                "last_generated_at": None,
            }

    stats_query = select(ImageKeyModelStats)
    if normalized_model:
        stats_query = stats_query.where(ImageKeyModelStats.model_normalized == normalized_model)
    stats_result = await db.execute(stats_query)
    stats_rows = list(stats_result.scalars().all())

    for stats in stats_rows:
        key_id = int(stats.api_key_id)
        item = grouped.setdefault(
            key_id,
            {
                "api_key_id": key_id,
                "api_key_name": stats.api_key_name or f"Key {key_id}",
                "provider": stats.provider or "",
                "model": model_value or stats.model,
                "weight": None,
                "remaining_amount": None,
                "remaining_image_count": None,
                "total_count": 0,
                "success_count": 0,
                "error_count": 0,
                "last_generated_at": None,
            },
        )
        item["api_key_name"] = item["api_key_name"] or stats.api_key_name or f"Key {key_id}"
        item["provider"] = item["provider"] or stats.provider or ""
        item["total_count"] += int(stats.total_count or 0)
        item["success_count"] += int(stats.success_count or 0)
        item["error_count"] += int(stats.error_count or 0)
        stats_time = stats.last_generated_at or stats.updated_at or stats.created_at
        if stats_time and (not item["last_generated_at"] or stats_time > item["last_generated_at"]):
            item["last_generated_at"] = stats_time

    missing_key_ids = set(grouped.keys()) - set(key_map.keys())
    if missing_key_ids:
        key_result = await db.execute(select(ApiKey).where(ApiKey.id.in_(missing_key_ids)))
        for key in key_result.scalars().all():
            key_id = int(key.id)
            key_map[key_id] = key
            item = grouped.get(key_id)
            if item:
                item["api_key_name"] = key.name or item["api_key_name"]
                item["provider"] = key.provider or item["provider"]
                item["weight"] = int(key.weight or 0)

    if current_model_price_units and grouped:
        stats_result = await db.execute(
            select(ImageKeyModelStats)
            .where(ImageKeyModelStats.api_key_id.in_(grouped.keys()))
            .where(ImageKeyModelStats.model_normalized == normalized_model)
        )
        stats_by_key = {int(stats.api_key_id): stats for stats in stats_result.scalars().all()}

        for key_id, item in grouped.items():
            key = key_map.get(key_id)
            if key and is_bbimg_key(key):
                stats = stats_by_key.get(key_id)
                spent_units = float(getattr(stats, "spent_units", 0.0) or 0.0)
                remaining_units = max(0.0, IMAGE_KEY_INITIAL_AMOUNT_UNITS - spent_units)
                item["remaining_amount"] = round(remaining_units / IMAGE_KEY_INITIAL_AMOUNT_UNITS, 3)
                item["remaining_image_count"] = int(remaining_units / current_model_price_units + 1e-9)

    items = []
    for item in grouped.values():
        total = int(item["success_count"] or 0) + int(item["error_count"] or 0)
        item["success_rate"] = round((int(item["success_count"] or 0) / total) * 100, 2) if total else 0
        items.append(ImageKeyStatsItem(**item))

    items.sort(key=lambda item: (item.success_rate, item.success_count, item.total_count), reverse=True)
    return ImageKeyStatsResponse(items=items)


@router.get("/key-cooldown-config", response_model=KeyCooldownConfigResponse)
async def get_key_cooldown_config(
    _: bool = Depends(verify_admin_key),
):
    """获取 Key 冷却配置"""
    return KeyCooldownConfigResponse(**pool_manager.get_cooldown_config())


@router.put("/key-cooldown-config", response_model=KeyCooldownConfigResponse)
async def update_key_cooldown_config(
    data: KeyCooldownConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新 Key 冷却配置"""
    pool_manager.update_cooldown_config(**data.model_dump())
    return KeyCooldownConfigResponse(**pool_manager.get_cooldown_config())


@router.get("/proxy-timeout-config", response_model=ProxyTimeoutConfigResponse)
async def get_proxy_timeout_config(
    _: bool = Depends(verify_admin_key),
):
    """获取代理超时配置"""
    return ProxyTimeoutConfigResponse(
        proxy_request_timeout_seconds=settings.proxy_request_timeout_seconds,
        proxy_stream_connect_timeout_seconds=settings.proxy_stream_connect_timeout_seconds,
        proxy_stream_first_byte_timeout_seconds=settings.proxy_stream_first_byte_timeout_seconds,
        proxy_stream_read_timeout_seconds=settings.proxy_stream_read_timeout_seconds,
    )


@router.put("/proxy-timeout-config", response_model=ProxyTimeoutConfigResponse)
async def update_proxy_timeout_config(
    data: ProxyTimeoutConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新代理超时配置"""
    payload = data.model_dump()
    settings.proxy_request_timeout_seconds = payload["proxy_request_timeout_seconds"]
    settings.proxy_stream_connect_timeout_seconds = payload["proxy_stream_connect_timeout_seconds"]
    settings.proxy_stream_first_byte_timeout_seconds = payload["proxy_stream_first_byte_timeout_seconds"]
    settings.proxy_stream_read_timeout_seconds = payload["proxy_stream_read_timeout_seconds"]
    return ProxyTimeoutConfigResponse(**payload)


@router.get("/content-guard-config", response_model=ContentGuardConfigResponse)
async def get_content_guard_config(
    _: bool = Depends(verify_admin_key),
):
    """获取上游内容安全防护配置"""
    from services.content_guard_service import content_guard_service

    return ContentGuardConfigResponse(**content_guard_service.get_config())


@router.put("/content-guard-config", response_model=ContentGuardConfigResponse)
async def update_content_guard_config(
    data: ContentGuardConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新上游内容安全防护配置"""
    payload = data.model_dump()
    if payload.get("ad_action") not in {"record", "sanitize", "block"}:
        payload["ad_action"] = "record"
    payload["ad_patterns"] = [item.strip() for item in payload.get("ad_patterns") or [] if item.strip()]
    payload["ad_regex_patterns"] = [item.strip() for item in payload.get("ad_regex_patterns") or [] if item.strip()]
    payload["dangerous_patterns"] = [item.strip() for item in payload.get("dangerous_patterns") or [] if item.strip()]
    export_config["content_guard"] = payload
    persist_export_config()
    return ContentGuardConfigResponse(**payload)


@router.get("/content-guard-events", response_model=ContentGuardEventListResponse)
async def list_content_guard_events(
    provider: Optional[str] = None,
    category: Optional[str] = None,
    action: Optional[str] = None,
    key_id: Optional[int] = None,
    keyword: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取上游内容安全事件列表"""
    from models import ContentGuardEvent

    conditions = []
    if provider:
        conditions.append(ContentGuardEvent.provider == provider)
    if category:
        conditions.append(ContentGuardEvent.category == category)
    if action:
        conditions.append(ContentGuardEvent.action == action)
    if key_id:
        conditions.append(ContentGuardEvent.api_key_id == key_id)
    if keyword and keyword.strip():
        text = f"%{keyword.strip()}%"
        conditions.append(or_(
            ContentGuardEvent.key_name.like(text),
            ContentGuardEvent.base_url.like(text),
            ContentGuardEvent.model.like(text),
            ContentGuardEvent.path.like(text),
            ContentGuardEvent.rule.like(text),
            ContentGuardEvent.snippet.like(text),
            ContentGuardEvent.explanation.like(text),
        ))

    offset_value = (page - 1) * limit
    count_query = select(func.count(ContentGuardEvent.id))
    data_query = select(ContentGuardEvent).order_by(ContentGuardEvent.created_at.desc(), ContentGuardEvent.id.desc())
    if conditions:
        count_query = count_query.where(*conditions)
        data_query = data_query.where(*conditions)

    total = int((await db.execute(count_query)).scalar() or 0)
    rows = (await db.execute(data_query.offset(offset_value).limit(limit))).scalars().all()
    return ContentGuardEventListResponse(
        items=[ContentGuardEventResponse.model_validate(row) for row in rows],
        total=total,
        page=page,
        limit=limit,
    )


def normalize_openai_plus_quota_refresh_config(data: Optional[dict] = None) -> dict:
    """归一化 OpenAI Plus 配额刷新配置"""
    source = data if isinstance(data, dict) else export_config.get("openai_plus_quota_refresh") or {}
    return {
        "openai_plus_quota_refresh_concurrency": max(1, min(int(source.get("openai_plus_quota_refresh_concurrency") or 5), 20)),
        "openai_plus_quota_refresh_timeout_seconds": max(5, min(int(source.get("openai_plus_quota_refresh_timeout_seconds") or 30), 300)),
        "openai_plus_quota_token_refresh_timeout_seconds": max(5, min(int(source.get("openai_plus_quota_token_refresh_timeout_seconds") or 60), 300)),
    }


@router.get("/openai-plus/quota-refresh-config", response_model=OpenAIPlusQuotaRefreshConfigResponse)
async def get_openai_plus_quota_refresh_config(
    _: bool = Depends(verify_admin_key),
):
    """获取 OpenAI Plus 配额刷新配置"""
    return OpenAIPlusQuotaRefreshConfigResponse(**normalize_openai_plus_quota_refresh_config())


@router.put("/openai-plus/quota-refresh-config", response_model=OpenAIPlusQuotaRefreshConfigResponse)
async def update_openai_plus_quota_refresh_config(
    data: OpenAIPlusQuotaRefreshConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新 OpenAI Plus 配额刷新配置"""
    payload = normalize_openai_plus_quota_refresh_config(data.model_dump())
    export_config["openai_plus_quota_refresh"] = payload
    persist_export_config()
    return OpenAIPlusQuotaRefreshConfigResponse(**payload)


@router.get("/key-check-default-config", response_model=KeyCheckDefaultConfigResponse)
async def get_key_check_default_config(
    _: bool = Depends(verify_admin_key),
):
    """获取默认一键检测模型配置"""
    return KeyCheckDefaultConfigResponse(
        default_key_check_model=str(export_config.get("default_key_check_model") or ""),
    )


@router.put("/key-check-default-config", response_model=KeyCheckDefaultConfigResponse)
async def update_key_check_default_config(
    data: KeyCheckDefaultConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新默认一键检测模型配置"""
    normalized_model = normalize_optional_text(data.default_key_check_model) or ""
    export_config["default_key_check_model"] = normalized_model
    persist_export_config()
    return KeyCheckDefaultConfigResponse(default_key_check_model=normalized_model)


@router.get("/key-check-shortcut-models", response_model=KeyCheckShortcutModelsResponse)
async def get_key_check_shortcut_models(
    _: bool = Depends(verify_admin_key),
):
    """获取一键检测快捷模型配置"""
    shortcut_models = normalize_string_list(export_config.get("default_key_check_models") if isinstance(export_config, dict) else None)
    default_model = normalize_optional_text(export_config.get("default_key_check_model") if isinstance(export_config, dict) else None) or ""
    if default_model and default_model.lower() not in {item.lower() for item in shortcut_models}:
        shortcut_models = [default_model, *shortcut_models]
    shortcut_models = normalize_string_list(shortcut_models)
    while len(shortcut_models) < 6:
        shortcut_models.append("")
    return KeyCheckShortcutModelsResponse(
        default_key_check_model=default_model,
        shortcut_models=shortcut_models[:6],
    )


@router.put("/key-check-shortcut-models", response_model=KeyCheckShortcutModelsResponse)
async def update_key_check_shortcut_models(
    data: KeyCheckShortcutModelsUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新一键检测快捷模型配置"""
    default_model = normalize_optional_text(data.default_key_check_model) or ""
    shortcut_models = normalize_string_list(data.shortcut_models)
    if default_model and default_model.lower() not in {item.lower() for item in shortcut_models}:
        shortcut_models = [default_model, *shortcut_models]
    shortcut_models = normalize_string_list(shortcut_models)
    while len(shortcut_models) < 6:
        shortcut_models.append("")

    export_config["default_key_check_model"] = default_model
    export_config["default_key_check_models"] = shortcut_models[:6]
    persist_export_config()
    return KeyCheckShortcutModelsResponse(
        default_key_check_model=default_model,
        shortcut_models=shortcut_models[:6],
    )


@router.get("/keys", response_model=dict)
async def list_keys(
    provider: Optional[str] = None,
    providers: Optional[List[str]] = Query(default=None),
    models: Optional[List[str]] = Query(default=None),
    key_ids: Optional[List[int]] = Query(default=None),
    key_names: Optional[List[str]] = Query(default=None),
    is_active: Optional[bool] = Query(default=None),
    sort_by: Optional[str] = Query(default="id"),
    sort_order: Optional[str] = Query(default="ascending"),
    page: Optional[int] = None,
    limit: int = 50,
    offset: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取所有 API Key 列表"""
    provider_values = normalize_string_list(providers) or ([] if not provider else [provider])
    model_values = normalize_string_list(models)
    page_value, limit_value, offset_value = parse_pagination(page, limit, offset)

    from models import ApiKey
    from sqlalchemy import func

    # 允许排序的字段白名单，防止 SQL 注入
    _SORTABLE_COLUMNS = {
        "id": ApiKey.id,
        "name": ApiKey.name,
        "provider": ApiKey.provider,
        "weight": ApiKey.weight,
        "is_active": ApiKey.is_active,
        "created_at": ApiKey.created_at,
    }
    sort_col = _SORTABLE_COLUMNS.get(sort_by or "id", ApiKey.id)
    sort_expr = sort_col.asc() if (sort_order or "ascending") == "ascending" else sort_col.desc()

    def _build_base_conditions():
        conditions = []
        if provider_values:
            conditions.append(ApiKey.provider.in_(provider_values))
        identity_filters = build_key_identity_filters(ApiKey, key_ids, key_names)
        if identity_filters:
            conditions.append(or_(*identity_filters))
        if is_active is not None:
            conditions.append(ApiKey.is_active == is_active)
        return conditions

    base_conditions = _build_base_conditions()

    if model_values:
        # 有模型筛选：两阶段查询
        # 第一阶段：只加载 id + supported_models，在 Python 层过滤
        light_query = select(ApiKey.id, ApiKey.supported_models)
        if base_conditions:
            light_query = light_query.where(*base_conditions)
        light_rows = (await db.execute(light_query)).all()

        matched_ids = [
            row.id for row in light_rows
            if any(pool_manager.key_supports_model(row, model) for model in model_values)
        ]
        total = len(matched_ids)
        page_ids = matched_ids[offset_value:offset_value + limit_value]

        if not page_ids:
            return {"items": [], "total": total, "page": page_value, "limit": limit_value}

        # 第二阶段：按命中 ID 加载完整数据，保持排序
        data_query = select(ApiKey).where(ApiKey.id.in_(page_ids)).order_by(sort_expr)
        keys = (await db.execute(data_query)).scalars().all()
        # 按 matched_ids 顺序重排（保证分页顺序稳定）
        id_order = {key_id: idx for idx, key_id in enumerate(page_ids)}
        keys = sorted(keys, key=lambda k: id_order.get(k.id, 0))
    else:
        # 无模型筛选：直接 SQL COUNT + LIMIT/OFFSET
        count_query = select(func.count(ApiKey.id))
        if base_conditions:
            count_query = count_query.where(*base_conditions)
        total = int((await db.execute(count_query)).scalar() or 0)

        data_query = select(ApiKey).order_by(sort_expr)
        if base_conditions:
            data_query = data_query.where(*base_conditions)
        data_query = data_query.offset(offset_value).limit(limit_value)
        keys = (await db.execute(data_query)).scalars().all()

    return {
        "items": [to_response(key) for key in keys],
        "total": total,
        "page": page_value,
        "limit": limit_value,
    }


@router.get("/keys/export", response_model=ApiKeyBatchExportResponse)
async def export_keys(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """导出全部 API Key"""
    from models import ApiKey

    result = await db.execute(select(ApiKey).order_by(ApiKey.id))
    items = [build_key_import_item(item) for item in result.scalars().all()]
    return ApiKeyBatchExportResponse(count=len(items), items=items)


@router.post("/keys", response_model=ApiKeyResponse)
async def create_key(
    data: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """创建新的 API Key"""
    from models import ApiKey

    supported_models, _ = await ensure_models_exist(db, data.supported_models)
    proxy_fields = build_proxy_fields(data)
    fake_ip_fields = build_fake_ip_fields(data)

    key = ApiKey(
        name=data.name,
        provider=data.provider,
        api_key=data.api_key,
        api_type=normalize_api_type(data.api_type),
        base_url=data.base_url,
        is_active=data.is_active,
        weight=data.weight,
        supported_models=dumps_json_list(supported_models),
        remark=data.remark,
        password=data.password,
        wz_url=data.wz_url,
        **proxy_fields,
        **fake_ip_fields,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)
    await prune_model_catalog_to_key_support(db)
    await db.commit()

    # 重置轮询索引
    pool_manager.reset_index(data.provider)

    return to_response(key)


@router.post("/keys/import", response_model=ApiKeyBatchImportResponse)
async def import_keys(
    data: ApiKeyBatchImportRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量导入 API Key"""
    from models import ApiKey

    touched_providers = set()
    processed_items = []
    created_count = 0
    updated_count = 0
    auto_created_model_count = 0

    provider_values = normalize_string_list([item.provider for item in data.items])
    existing_keys_map: dict[tuple[str, str], Any] = {}
    if provider_values:
        existing_result = await db.execute(
            select(ApiKey).where(ApiKey.provider.in_(provider_values))
        )
        for existing_key in existing_result.scalars().all():
            name_value = normalize_optional_text(getattr(existing_key, "name", None))
            provider_value = normalize_optional_text(getattr(existing_key, "provider", None))
            if not name_value or not provider_value:
                continue
            existing_keys_map[(name_value.lower(), provider_value.lower())] = existing_key

    auto_fake_ip_values = iter(build_batch_fake_ips(sum(1 for item in data.items if import_item_needs_auto_fake_ip(item))))

    for item in data.items:
        supported_models, created_models = await ensure_models_exist(db, item.supported_models)
        auto_created_model_count += len(created_models)

        normalized_name = normalize_optional_text(item.name)
        normalized_provider = normalize_optional_text(item.provider)
        normalized_api_key = normalize_optional_text(item.api_key)
        normalized_base_url = normalize_optional_text(item.base_url)
        if not normalized_name or not normalized_provider or not normalized_api_key or not normalized_base_url:
            raise HTTPException(status_code=400, detail="名称、提供商、API Key、请求地址不能为空")

        matched_key = existing_keys_map.get((normalized_name.lower(), normalized_provider.lower()))
        serialized_models = dumps_json_list(supported_models)
        should_update_weight = "weight" in item.model_fields_set
        generated_fake_ip = next(auto_fake_ip_values) if import_item_needs_auto_fake_ip(item) else None
        proxy_fields = build_proxy_fields(item)
        fake_ip_fields = build_import_fake_ip_fields(item, generated_fake_ip)

        if matched_key:
            matched_key.api_key = normalized_api_key
            matched_key.api_type = normalize_api_type(item.api_type)
            matched_key.base_url = normalized_base_url
            matched_key.supported_models = serialized_models
            matched_key.enable_proxy = proxy_fields["enable_proxy"]
            matched_key.proxy_url = proxy_fields["proxy_url"]
            matched_key.proxy_username = proxy_fields["proxy_username"]
            matched_key.proxy_password = proxy_fields["proxy_password"]
            matched_key.enable_fake_ip = fake_ip_fields["enable_fake_ip"]
            matched_key.fake_ip = fake_ip_fields["fake_ip"]
            if should_update_weight:
                matched_key.weight = item.weight
            if item.password is not None:
                matched_key.password = item.password
            if item.wz_url is not None:
                matched_key.wz_url = item.wz_url
            matched_key.updated_at = datetime.utcnow()
            processed_items.append(matched_key)
            touched_providers.add(matched_key.provider)
            updated_count += 1
            continue

        key = ApiKey(
            name=normalized_name,
            provider=normalized_provider,
            api_key=normalized_api_key,
            api_type=normalize_api_type(item.api_type),
            base_url=normalized_base_url,
            is_active=item.is_active,
            weight=item.weight if should_update_weight and item.weight is not None else 1,
            supported_models=serialized_models,
            remark=item.remark,
            password=item.password,
            wz_url=item.wz_url,
            **proxy_fields,
            **fake_ip_fields,
        )
        db.add(key)
        processed_items.append(key)
        existing_keys_map[(normalized_name.lower(), normalized_provider.lower())] = key
        touched_providers.add(normalized_provider)
        created_count += 1

    await db.commit()
    await prune_model_catalog_to_key_support(db)
    await db.commit()
    for key in processed_items:
        await db.refresh(key)
    for provider in touched_providers:
        pool_manager.reset_index(provider)

    return ApiKeyBatchImportResponse(
        count=len(processed_items),
        items=[to_response(item) for item in processed_items],
        auto_created_model_count=auto_created_model_count,
        created_count=created_count,
        updated_count=updated_count,
    )


@router.post("/keys/batch/models", response_model=ApiKeyBatchUpdateModelsResponse)
async def batch_update_key_models(
    data: ApiKeyBatchUpdateModelsRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量调整 Key 请求地址与支持模型"""
    from models import ApiKey

    if data.scope not in {"filtered", "selected"}:
        raise HTTPException(status_code=400, detail="无效的批量更新范围")

    query = select(ApiKey)
    if data.scope == "filtered":
        providers = normalize_string_list(data.providers)
        if not providers and data.provider:
            providers = [data.provider]
        if providers:
            query = query.where(ApiKey.provider.in_(providers))
        identity_filters = build_key_identity_filters(ApiKey, data.key_ids, data.key_names)
        if identity_filters:
            query = query.where(or_(*identity_filters))
        if data.is_active is not None:
            query = query.where(ApiKey.is_active == data.is_active)
    else:
        key_ids = data.key_ids or []
        if not key_ids:
            raise HTTPException(status_code=400, detail="按勾选项批量更新时 key_ids 不能为空")
        query = query.where(ApiKey.id.in_(key_ids))

    result = await db.execute(query)
    keys = list(result.scalars().all())
    if not keys:
        raise HTTPException(status_code=404, detail="未找到可更新的 Key")

    models_filter = normalize_string_list(data.models)
    if data.scope == "filtered" and models_filter:
        keys = [
            key for key in keys
            if any(pool_manager.key_supports_model(key, model) for model in models_filter)
        ]
        if not keys:
            raise HTTPException(status_code=404, detail="未找到可更新的 Key")

    provided_fields = data.model_fields_set
    should_update_base_url = "base_url" in provided_fields
    should_update_weight = "weight" in provided_fields
    should_update_supported_models = "supported_models" in provided_fields
    should_update_provider = bool(data.new_provider and data.new_provider.strip())
    should_update_api_type = "api_type" in provided_fields

    normalized_base_url = data.base_url.strip() if isinstance(data.base_url, str) else None
    normalized_api_type = normalize_api_type(data.api_type) if should_update_api_type else None
    if not should_update_base_url and not should_update_weight and not should_update_supported_models and not should_update_provider and not should_update_api_type:
        raise HTTPException(status_code=400, detail="请至少选择一项要调整的内容")
    if should_update_base_url and not normalized_base_url and not should_update_weight and not should_update_supported_models and not should_update_provider and not should_update_api_type:
        raise HTTPException(status_code=400, detail="请求地址不能为空")

    supported_models = []
    created_models = []
    serialized_models = None
    if should_update_supported_models:
        supported_models, created_models = await ensure_models_exist(db, data.supported_models)
        serialized_models = dumps_json_list(supported_models)

    touched_providers = set()
    new_provider_value = data.new_provider.strip() if should_update_provider else None
    for key in keys:
        if should_update_base_url and normalized_base_url:
            key.base_url = normalized_base_url
        if should_update_weight:
            key.weight = data.weight
        if should_update_supported_models:
            key.supported_models = serialized_models
        if should_update_provider:
            touched_providers.add(key.provider)  # 旧 provider 也要重置
            key.provider = new_provider_value
        if should_update_api_type:
            key.api_type = normalized_api_type
        key.updated_at = datetime.utcnow()
        touched_providers.add(key.provider)

    await db.commit()
    if should_update_supported_models:
        await prune_model_catalog_to_key_support(db)
        await db.commit()
    for provider in touched_providers:
        pool_manager.reset_index(provider)

    return ApiKeyBatchUpdateModelsResponse(
        count=len(keys),
        scope=data.scope,
        provider=data.provider,
        providers=normalize_string_list(data.providers) or None,
        models=models_filter or None,
        auto_created_model_count=len(created_models),
    )


@router.post("/key-check/tasks", response_model=ApiKeyCheckTaskResponse)
async def create_key_check_task(
    data: ApiKeyBatchCheckRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """创建 Key 检测任务"""
    from models import ApiKeyCheckTask

    target_model = (data.target_model or "").strip()
    if not target_model:
        raise HTTPException(status_code=400, detail="检测模型不能为空")

    keys, models_filter = await list_target_keys_for_batch_check(db, data)
    task = await key_check_task_service.create_task(db, data, keys, models_filter)
    await key_check_task_service.start_task(int(task.id))

    refreshed_task = await db.get(ApiKeyCheckTask, task.id)
    if not refreshed_task:
        raise HTTPException(status_code=500, detail="任务创建失败")
    return to_check_task_response(refreshed_task)


@router.get("/key-check/tasks", response_model=ApiKeyCheckTaskListResponse)
async def list_key_check_tasks(
    page: Optional[int] = None,
    limit: int = 20,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询 Key 检测任务列表"""
    from models import ApiKeyCheckTask

    page_value, limit_value, offset_value = parse_pagination(page, limit, None)
    query = select(ApiKeyCheckTask).order_by(ApiKeyCheckTask.id.desc())
    if status:
        query = query.where(ApiKeyCheckTask.status == status)

    count_query = select(func.count()).select_from(ApiKeyCheckTask)
    if status:
        count_query = count_query.where(ApiKeyCheckTask.status == status)

    total = int((await db.execute(count_query)).scalar() or 0)
    result = await db.execute(query.offset(offset_value).limit(limit_value))
    items = [to_check_task_response(item) for item in result.scalars().all()]
    return ApiKeyCheckTaskListResponse(items=items, total=total, page=page_value, limit=limit_value)


@router.get("/key-check/tasks/{task_id}", response_model=ApiKeyCheckTaskResponse)
async def get_key_check_task(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询 Key 检测任务详情"""
    from models import ApiKeyCheckTask

    task = await db.get(ApiKeyCheckTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="检测任务不存在")
    return to_check_task_response(task)


@router.get("/key-check/tasks/{task_id}/results", response_model=ApiKeyCheckTaskResultListResponse)
async def list_key_check_task_results(
    task_id: int,
    page: Optional[int] = None,
    limit: int = 50,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询 Key 检测任务结果"""
    from models import ApiKeyCheckTask, ApiKeyCheckTaskResult

    task = await db.get(ApiKeyCheckTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="检测任务不存在")

    page_value, limit_value, offset_value = parse_pagination(page, limit, None)
    query = select(ApiKeyCheckTaskResult).where(ApiKeyCheckTaskResult.task_id == task_id).order_by(ApiKeyCheckTaskResult.id.asc())
    count_query = select(func.count()).select_from(ApiKeyCheckTaskResult).where(ApiKeyCheckTaskResult.task_id == task_id)
    if status:
        query = query.where(ApiKeyCheckTaskResult.status == status)
        count_query = count_query.where(ApiKeyCheckTaskResult.status == status)

    total = int((await db.execute(count_query)).scalar() or 0)
    result = await db.execute(query.offset(offset_value).limit(limit_value))
    items = [build_api_key_check_item_from_task_result(item) for item in result.scalars().all()]
    return ApiKeyCheckTaskResultListResponse(items=items, total=total, page=page_value, limit=limit_value)


@router.get("/key-check/tasks/{task_id}/stats", response_model=ApiKeyCheckTaskStatsResponse)
async def get_key_check_task_stats(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询 Key 检测任务统计"""
    from models import ApiKeyCheckTask, ApiKeyCheckTaskResult

    task = await db.get(ApiKeyCheckTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="检测任务不存在")

    result = await db.execute(
        select(ApiKeyCheckTaskResult.status, func.count(ApiKeyCheckTaskResult.id))
        .where(ApiKeyCheckTaskResult.task_id == task_id)
        .group_by(ApiKeyCheckTaskResult.status)
    )
    status_breakdown = {str(status or "pending"): int(count or 0) for status, count in result.all()}
    return ApiKeyCheckTaskStatsResponse(task=to_check_task_response(task), status_breakdown=status_breakdown)


@router.post("/keys/batch/check", response_model=ApiKeyBatchCheckResponse)
async def batch_check_key_endpoints(
    data: ApiKeyBatchCheckRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量检测 Key 请求地址与目标模型"""
    target_model = (data.target_model or "").strip()
    if not target_model:
        raise HTTPException(status_code=400, detail="检测模型不能为空")

    keys, models_filter = await list_target_keys_for_batch_check(db, data)
    concurrency = min(10, len(keys))
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def run_single_check(key: Any) -> tuple[Any, dict]:
        async with semaphore:
            try:
                model_plan = await pool_manager.build_model_match_plan(db, target_model, providers=[key.provider])
                upstream_model = pool_manager.resolve_upstream_model_for_key(key, target_model, model_plan)
                result = await proxy_service.check_key_connectivity_and_model(key, upstream_model or target_model)
                result["target_model"] = target_model
                result["upstream_model"] = upstream_model or target_model
            except Exception as exc:
                result = {
                    "status": "error",
                    "target_model": target_model,
                    "response_time_ms": 0,
                    "failure_category": proxy_service._classify_check_failure(None, str(exc) or exc.__class__.__name__),
                    "failure_detail": str(exc) or exc.__class__.__name__,
                    "address_check": {
                        "status": "error",
                        "status_code": None,
                        "error_message": str(exc) or exc.__class__.__name__,
                        "response_time_ms": 0,
                        "path": "runtime",
                        "url": "runtime",
                    },
                    "model_check": None,
                }
            return key, result

    completed_results = await asyncio.gather(
        *(run_single_check(key) for key in keys)
    )
    items = [
        build_api_key_check_item(key, result)
        for key, result in completed_results
    ]
    success_count = sum(1 for item in items if item.status == "success")

    return ApiKeyBatchCheckResponse(
        count=len(items),
        success_count=success_count,
        error_count=len(items) - success_count,
        scope=data.scope,
        provider=data.provider,
        providers=normalize_string_list(data.providers) or None,
        models=models_filter or None,
        target_model=target_model,
        items=items,
    )


@router.post("/keys/{key_id}/check", response_model=ApiKeyCheckItem)
async def check_single_key(
    key_id: int,
    data: ApiKeySingleCheckRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """检测单个 Key 的请求地址与目标模型"""
    target_model = data.target_model.strip()
    if not target_model:
        raise HTTPException(status_code=400, detail="检测模型不能为空")

    key = await pool_manager.get_key_by_id(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    model_plan = await pool_manager.build_model_match_plan(db, target_model, providers=[key.provider])
    upstream_model = pool_manager.resolve_upstream_model_for_key(key, target_model, model_plan)
    result = await proxy_service.check_key_connectivity_and_model(key, upstream_model or target_model)
    result["target_model"] = target_model
    result["upstream_model"] = upstream_model or target_model
    return build_api_key_check_item(key, result)


@router.post("/keys/batch/delete", response_model=ApiKeyBatchDeleteResponse)
async def batch_delete_keys(
    data: ApiKeyBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量删除 API Key"""
    from models import ApiKey

    key_ids = list(dict.fromkeys(data.key_ids or []))
    if not key_ids:
        raise HTTPException(status_code=400, detail="key_ids 不能为空")

    result = await db.execute(select(ApiKey).where(ApiKey.id.in_(key_ids)))
    keys = list(result.scalars().all())
    if not keys:
        raise HTTPException(status_code=404, detail="未找到可删除的 Key")

    touched_providers = {key.provider for key in keys}
    for key in keys:
        await db.delete(key)

    await db.commit()
    await prune_model_catalog_to_key_support(db)
    await db.commit()

    for provider in touched_providers:
        pool_manager.reset_index(provider)

    return ApiKeyBatchDeleteResponse(count=len(keys))


@router.post("/keys/batch/fake-ip", response_model=ApiKeyBatchFakeIpResponse)
async def batch_set_keys_fake_ip(
    data: ApiKeyBatchFakeIpRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量设置 Key 独立 fake IP"""
    from models import ApiKey

    key_ids = list(dict.fromkeys(data.key_ids or []))
    if not key_ids:
        raise HTTPException(status_code=400, detail="key_ids 不能为空")

    result = await db.execute(
        select(ApiKey)
        .where(ApiKey.id.in_(key_ids))
        .order_by(ApiKey.id.asc())
    )
    keys = list(result.scalars().all())
    if not keys:
        raise HTTPException(status_code=404, detail="未找到可更新的 Key")

    touched_providers = set()
    if data.enabled:
        generated_fake_ips = build_batch_fake_ips(len(keys))
        for key, fake_ip in zip(keys, generated_fake_ips):
            fake_ip_payload = build_fake_ip_fields(type("BatchFakeIpPayload", (), {
                "enable_fake_ip": True,
                "fake_ip": fake_ip,
            })())
            key.enable_fake_ip = fake_ip_payload["enable_fake_ip"]
            key.fake_ip = fake_ip_payload["fake_ip"]
            key.updated_at = datetime.utcnow()
            touched_providers.add(key.provider)
    else:
        for key in keys:
            key.enable_fake_ip = False
            key.fake_ip = None
            key.updated_at = datetime.utcnow()
            touched_providers.add(key.provider)

    await db.commit()
    for provider in touched_providers:
        pool_manager.reset_index(provider)

    return ApiKeyBatchFakeIpResponse(count=len(keys), enabled=data.enabled)


@router.get("/keys/{key_id}", response_model=ApiKeyResponse)
async def get_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取单个 API Key"""
    key = await pool_manager.get_key_by_id(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    return to_response(key)


@router.put("/keys/{key_id}", response_model=ApiKeyResponse)
async def update_key(
    key_id: int,
    data: ApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """更新 API Key"""
    key = await pool_manager.get_key_by_id(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    original_provider = key.provider

    # 更新字段
    update_data = data.model_dump(exclude_unset=True)
    proxy_fields_set = {"enable_proxy", "proxy_url", "proxy_username", "proxy_password"}
    if update_data.keys() & proxy_fields_set:
        proxy_payload = build_proxy_fields(data)
        for field in proxy_fields_set:
            update_data.pop(field, None)
        update_data.update(proxy_payload)

    fake_ip_fields_set = {"enable_fake_ip", "fake_ip"}
    if update_data.keys() & fake_ip_fields_set:
        fake_ip_payload = build_fake_ip_fields(data)
        for field in fake_ip_fields_set:
            update_data.pop(field, None)
        update_data.update(fake_ip_payload)

    should_prune_models = False
    for field, value in update_data.items():
        if field == "supported_models":
            normalized_models, _ = await ensure_models_exist(db, value)
            setattr(key, field, dumps_json_list(normalized_models))
            should_prune_models = True
            continue
        if field == "api_type":
            setattr(key, field, normalize_api_type(value))
            continue
        setattr(key, field, value)

    key.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(key)
    if should_prune_models:
        await prune_model_catalog_to_key_support(db)
        await db.commit()

    # 重置轮询索引
    pool_manager.reset_index(original_provider)
    if key.provider != original_provider:
        pool_manager.reset_index(key.provider)

    return to_response(key)


@router.delete("/keys/{key_id}")
async def delete_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """删除 API Key"""
    key = await pool_manager.get_key_by_id(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    provider = key.provider
    await db.delete(key)
    await db.commit()
    await prune_model_catalog_to_key_support(db)
    await db.commit()

    # 重置轮询索引
    pool_manager.reset_index(provider)

    return {"message": "删除成功"}


@router.post("/keys/batch/active", response_model=ApiKeyBatchSetActiveResponse)
async def batch_set_keys_active(
    data: ApiKeyBatchSetActiveRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量设置 API Key 启用状态"""
    from models import ApiKey

    key_ids = data.key_ids or []
    if not key_ids:
        raise HTTPException(status_code=400, detail="key_ids 不能为空")

    result = await db.execute(select(ApiKey).where(ApiKey.id.in_(key_ids)))
    keys = list(result.scalars().all())
    if not keys:
        raise HTTPException(status_code=404, detail="未找到可更新的 Key")

    touched_providers = set()
    for key in keys:
        key.is_active = data.is_active
        key.updated_at = datetime.utcnow()
        touched_providers.add(key.provider)

    await db.commit()
    for provider in touched_providers:
        pool_manager.reset_index(provider)

    return ApiKeyBatchSetActiveResponse(count=len(keys), is_active=data.is_active)


@router.post("/keys/batch/cooldown/clear", response_model=ApiKeyBatchClearCooldownResponse)
async def batch_clear_keys_cooldown(
    data: ApiKeyBatchClearCooldownRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量解除 Key 冷却"""
    from models import ApiKey

    key_ids = data.key_ids or []
    if not key_ids:
        raise HTTPException(status_code=400, detail="key_ids 不能为空")

    result = await db.execute(select(ApiKey).where(ApiKey.id.in_(key_ids)))
    keys = list(result.scalars().all())
    if not keys:
        raise HTTPException(status_code=404, detail="未找到可更新的 Key")

    for key in keys:
        pool_manager.clear_key_cooldown(key.id)

    return ApiKeyBatchClearCooldownResponse(count=len(keys))


@router.post("/keys/{key_id}/cooldown/clear", response_model=ApiKeyResponse)
async def clear_key_cooldown(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """手动解除 Key 冷却"""
    key = await pool_manager.get_key_by_id(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    pool_manager.clear_key_cooldown(key_id)
    return to_response(key)


@router.post("/keys/{key_id}/toggle")
async def toggle_key(
    key_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """切换 API Key 启用状态"""
    key = await pool_manager.get_key_by_id(db, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    key.is_active = not key.is_active
    key.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(key)

    pool_manager.reset_index(key.provider)

    return to_response(key)


@router.get("/providers", response_model=ProviderListResponse)
async def list_key_providers(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取 Key 已使用的提供商列表"""
    from models import ApiKey

    result = await db.execute(select(ApiKey.provider).distinct().order_by(ApiKey.provider.asc()))
    items = normalize_string_list(list(result.scalars().all()))
    return ProviderListResponse(items=items)


@router.get("/provider-model-mappings", response_model=ProviderModelMappingListResponse)
async def list_provider_model_mappings(
    provider: Optional[str] = Query(default=None),
    provider_model: Optional[str] = Query(default=None),
    real_model: Optional[str] = Query(default=None),
    enabled: Optional[bool] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询提供商模型映射"""
    from models import ProviderModelMapping

    conditions = []
    provider_value = normalize_optional_text(provider)
    provider_model_value = normalize_optional_text(provider_model)
    real_model_value = normalize_optional_text(real_model)
    if provider_value:
        conditions.append(ProviderModelMapping.provider == provider_value)
    if provider_model_value:
        conditions.append(ProviderModelMapping.provider_model.ilike(f"%{provider_model_value}%"))
    if real_model_value:
        conditions.append(ProviderModelMapping.real_model.ilike(f"%{real_model_value}%"))
    if enabled is not None:
        conditions.append(ProviderModelMapping.enabled == enabled)

    query = select(ProviderModelMapping)
    count_query = select(func.count()).select_from(ProviderModelMapping)
    if conditions:
        query = query.where(and_(*conditions))
        count_query = count_query.where(and_(*conditions))
    query = query.order_by(ProviderModelMapping.provider.asc(), ProviderModelMapping.provider_model_normalized.asc())

    result = await db.execute(query)
    total_result = await db.execute(count_query)
    return ProviderModelMappingListResponse(
        items=[to_provider_model_mapping_item(item) for item in result.scalars().all()],
        total=int(total_result.scalar() or 0),
    )


@router.get("/provider-model-mappings/export", response_model=ProviderModelMappingExportResponse)
async def export_provider_model_mappings(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """导出全部提供商模型映射"""
    from models import ProviderModelMapping

    result = await db.execute(
        select(ProviderModelMapping).order_by(
            ProviderModelMapping.provider.asc(),
            ProviderModelMapping.provider_model_normalized.asc(),
        )
    )
    items = [build_provider_model_mapping_import_item(item) for item in result.scalars().all()]
    return ProviderModelMappingExportResponse(count=len(items), items=items)


@router.post("/provider-model-mappings/import", response_model=ProviderModelMappingImportResponse)
async def import_provider_model_mappings(
    data: ProviderModelMappingImportRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量导入提供商模型映射"""
    from models import ProviderModelMapping

    created_count = 0
    updated_count = 0
    processed_items = []
    fields_list = []
    for item in data.items:
        fields_list.extend(expand_provider_model_mapping_import_item(item))
    provider_values = normalize_string_list([item["provider"] for item in fields_list])
    existing_map: dict[tuple[str, str], Any] = {}
    if provider_values:
        result = await db.execute(select(ProviderModelMapping).where(ProviderModelMapping.provider.in_(provider_values)))
        for item in result.scalars().all():
            existing_map[(item.provider.lower(), item.provider_model_normalized.lower())] = item

    for fields in fields_list:
        key = (fields["provider"].lower(), fields["provider_model_normalized"].lower())
        mapping = existing_map.get(key)
        if mapping is None:
            mapping = ProviderModelMapping(**fields)
            db.add(mapping)
            existing_map[key] = mapping
            created_count += 1
        else:
            for field_name, field_value in fields.items():
                setattr(mapping, field_name, field_value)
            updated_count += 1
        processed_items.append(mapping)

    await db.commit()
    for item in processed_items:
        await db.refresh(item)
    return ProviderModelMappingImportResponse(
        count=len(processed_items),
        created_count=created_count,
        updated_count=updated_count,
        items=[to_provider_model_mapping_item(item) for item in processed_items],
    )


@router.post("/provider-model-mappings", response_model=ProviderModelMappingMutationResponse)
async def create_provider_model_mapping(
    data: ProviderModelMappingCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """新增或更新提供商模型映射"""
    from models import ProviderModelMapping

    fields = build_provider_model_mapping_fields(data)
    result = await db.execute(
        select(ProviderModelMapping).where(
            ProviderModelMapping.provider == fields["provider"],
            ProviderModelMapping.provider_model_normalized == fields["provider_model_normalized"],
        )
    )
    mapping = result.scalar_one_or_none()
    if mapping is None:
        mapping = ProviderModelMapping(**fields)
        db.add(mapping)
    else:
        for key, value in fields.items():
            setattr(mapping, key, value)
    await db.commit()
    await db.refresh(mapping)
    return ProviderModelMappingMutationResponse(item=to_provider_model_mapping_item(mapping))


@router.put("/provider-model-mappings/{mapping_id}", response_model=ProviderModelMappingMutationResponse)
async def update_provider_model_mapping(
    mapping_id: int,
    data: ProviderModelMappingUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """更新提供商模型映射"""
    from models import ProviderModelMapping

    mapping = await db.get(ProviderModelMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="模型映射不存在")
    fields = build_provider_model_mapping_fields(data)
    duplicate_result = await db.execute(
        select(ProviderModelMapping).where(
            ProviderModelMapping.provider == fields["provider"],
            ProviderModelMapping.provider_model_normalized == fields["provider_model_normalized"],
            ProviderModelMapping.id != mapping_id,
        )
    )
    if duplicate_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="同一提供商下原始模型映射已存在")
    for key, value in fields.items():
        setattr(mapping, key, value)
    await db.commit()
    await db.refresh(mapping)
    return ProviderModelMappingMutationResponse(item=to_provider_model_mapping_item(mapping))


@router.delete("/provider-model-mappings/{mapping_id}", response_model=dict)
async def delete_provider_model_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """删除提供商模型映射"""
    from models import ProviderModelMapping

    mapping = await db.get(ProviderModelMapping, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="模型映射不存在")
    await db.delete(mapping)
    await db.commit()
    return {"success": True}


@router.get("/provider-model-priorities", response_model=ProviderModelPriorityListResponse)
async def list_provider_model_priorities(
    provider: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取指定 provider 的模型优先 Key 配置"""
    provider_value = provider.strip()
    if not provider_value:
        raise HTTPException(status_code=400, detail="provider 不能为空")

    items = await list_provider_priority_items(db, provider_value)
    return ProviderModelPriorityListResponse(provider=provider_value, items=items)


@router.get("/provider-model-priority-key-options", response_model=list[ProviderModelPriorityKeyOption])
async def list_provider_model_priority_key_options(
    provider: str = Query(...),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取指定 provider 的模型优先 Key 候选项"""
    provider_value = provider.strip()
    if not provider_value:
        raise HTTPException(status_code=400, detail="provider 不能为空")
    return await build_provider_priority_key_options(db, provider_value)


@router.put("/provider-model-priorities", response_model=ProviderModelPriorityMutationResponse)
async def save_provider_model_priority(
    data: ProviderModelPriorityUpsertRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """保存指定 provider-model 的优先 Key"""
    provider_value, model_value = await upsert_provider_priority_binding(
        db,
        provider=data.provider,
        model=data.model,
        key_id=data.key_id,
    )
    return ProviderModelPriorityMutationResponse(
        provider=provider_value,
        model=model_value,
        priority_key_id=data.key_id,
    )


@router.api_route("/provider-model-priorities", methods=["DELETE"], response_model=ProviderModelPriorityMutationResponse)
async def delete_provider_model_priority(
    data: ProviderModelPriorityClearRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """清空指定 provider-model 的优先 Key"""
    provider_value, model_value, _ = await clear_provider_priority_binding(
        db,
        provider=data.provider,
        model=data.model,
    )
    return ProviderModelPriorityMutationResponse(
        provider=provider_value,
        model=model_value,
        priority_key_id=None,
    )


@router.get("/model-providers", response_model=ProviderListResponse)
async def list_model_providers(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取模型已使用的提供商列表"""
    from models import ModelCatalog

    result = await db.execute(select(ModelCatalog.provider).distinct().order_by(ModelCatalog.provider.asc()))
    items = normalize_string_list(list(result.scalars().all()))
    return ProviderListResponse(items=items)


@router.get("/models", response_model=dict)
async def list_models(
    provider: Optional[str] = Query(default=None),
    page: Optional[int] = None,
    limit: int = 50,
    offset: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取模型广场列表"""
    from models import ModelCatalog

    existing_result = await db.execute(select(ModelCatalog))
    existing_models = {item.model_id: item for item in existing_result.scalars().all()}

    # 种子回填开关：一键还原后关闭，避免已删除的模型被种子数据重新插入
    seed_enabled = export_config.get("model_seed_enabled", True)
    changed = False
    if seed_enabled:
        for item in DEFAULT_MODELS:
            existing_model = existing_models.get(item["model_id"])
            if not existing_model:
                model = ModelCatalog(
                    model_id=item["model_id"],
                    display_name=item["display_name"],
                    provider=item["provider"],
                    protocol=item["protocol"],
                    input_price=item["input_price"],
                    output_price=item["output_price"],
                    is_active=item["is_active"],
                    is_recommended=item["is_recommended"],
                    supports_codex=item["supports_codex"],
                    supports_claudecode=item["supports_claudecode"],
                    supports_gemini=item.get("supports_gemini", False),
                    aliases=dumps_json_list(item.get("aliases")),
                    remark=item.get("remark"),
                )
                apply_rule_fields(model, model.model_id)
                db.add(model)
                changed = True
                continue

            existing_model.display_name = item["display_name"]
            existing_model.input_price = item["input_price"]
            existing_model.output_price = item["output_price"]
            existing_model.is_recommended = item["is_recommended"]
            existing_model.aliases = dumps_json_list(item.get("aliases"))
            existing_model.remark = item.get("remark")
            apply_rule_fields(existing_model, existing_model.model_id)
            existing_model.updated_at = datetime.utcnow()
            changed = True

    if changed:
        await db.commit()

    page_value, limit_value, offset_value = parse_pagination(page, limit, offset)

    count_query = select(func.count(ModelCatalog.id))
    if provider:
        count_query = count_query.where(ModelCatalog.provider == provider)
    count_result = await db.execute(count_query)
    total = int(count_result.scalar() or 0)

    query = select(ModelCatalog).order_by(ModelCatalog.is_recommended.desc(), ModelCatalog.model_id.asc())
    if provider:
        query = query.where(ModelCatalog.provider == provider)
    query = query.offset(offset_value).limit(limit_value)

    result = await db.execute(query)
    items = [to_model_response(item) for item in result.scalars().all()]

    return {
        "items": items,
        "total": total,
        "page": page_value,
        "limit": limit_value,
    }


@router.get("/models/export", response_model=ModelCatalogBatchExportResponse)
async def export_models(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """导出全部模型"""
    from models import ModelCatalog

    result = await db.execute(
        select(ModelCatalog).order_by(ModelCatalog.is_recommended.desc(), ModelCatalog.model_id.asc())
    )
    items = [build_model_import_item(item) for item in result.scalars().all()]
    return ModelCatalogBatchExportResponse(count=len(items), items=items)


@router.post("/models", response_model=ModelCatalogResponse)
async def create_model(
    data: ModelCatalogCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """创建模型"""
    from models import ModelCatalog

    exists = await db.execute(select(ModelCatalog).where(ModelCatalog.model_id == data.model_id))
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="模型 ID 已存在")

    model = ModelCatalog(
        model_id=data.model_id,
        display_name=data.display_name,
        provider=data.provider,
        protocol=data.protocol,
        input_price=data.input_price,
        output_price=data.output_price,
        is_active=data.is_active,
        is_recommended=data.is_recommended,
        supports_codex=data.supports_codex,
        supports_claudecode=data.supports_claudecode,
        supports_gemini=data.supports_gemini,
        aliases=dumps_json_list(normalize_string_list(data.aliases)),
        remark=data.remark,
    )
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return to_model_response(model)


@router.post("/models/import", response_model=ModelCatalogBatchImportResponse)
async def import_models(
    data: ModelCatalogBatchImportRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """批量导入模型"""
    from models import ModelCatalog

    created_items = []
    for item in data.items:
        exists = await db.execute(select(ModelCatalog).where(ModelCatalog.model_id == item.model_id))
        if exists.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"模型 ID 已存在: {item.model_id}")

        model = ModelCatalog(
            model_id=item.model_id,
            display_name=item.display_name,
            provider=item.provider,
            protocol=item.protocol,
            input_price=item.input_price,
            output_price=item.output_price,
            is_active=item.is_active,
            is_recommended=item.is_recommended,
            supports_codex=item.supports_codex,
            supports_claudecode=item.supports_claudecode,
            supports_gemini=item.supports_gemini,
            aliases=dumps_json_list(normalize_string_list(item.aliases)),
            remark=item.remark,
        )
        db.add(model)
        created_items.append(model)

    await db.commit()
    for item in created_items:
        await db.refresh(item)

    return ModelCatalogBatchImportResponse(
        count=len(created_items),
        items=[to_model_response(item) for item in created_items],
        created_count=len(created_items),
    )


@router.post("/models/quick-create", response_model=QuickCreateModelsResponse)
async def quick_create_models(
    data: QuickCreateModelsRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """快捷批量创建模型"""
    names, created_names = await ensure_models_exist(db, data.names)
    return QuickCreateModelsResponse(
        count=len(names),
        created_count=len(created_names),
        existing_count=len(names) - len(created_names),
        items=names,
        created_items=created_names,
    )


@router.put("/models/{model_id}", response_model=ModelCatalogResponse)
async def update_model(
    model_id: int,
    data: ModelCatalogUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """更新模型"""
    from models import ModelCatalog

    result = await db.execute(select(ModelCatalog).where(ModelCatalog.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "aliases":
            setattr(model, field, dumps_json_list(normalize_string_list(value)))
            continue
        setattr(model, field, value)

    model.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(model)
    return to_model_response(model)


@router.delete("/models/{model_id}")
async def delete_model(
    model_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """删除模型"""
    from models import ModelCatalog

    result = await db.execute(select(ModelCatalog).where(ModelCatalog.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="模型不存在")

    await db.delete(model)
    await db.commit()
    return {"message": "删除成功"}


@router.get("/export-config", response_model=ExportConfigResponse)
async def get_export_config(
    request: Request,
    model: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """导出 CC Switch 元信息"""
    from models import ModelCatalog

    selected_model = None
    if model:
        result = await db.execute(select(ModelCatalog).where(ModelCatalog.model_id == model))
        selected_model = result.scalar_one_or_none()

    if not selected_model:
        result = await db.execute(
            select(ModelCatalog)
            .where(ModelCatalog.is_active == True)
            .order_by(ModelCatalog.is_recommended.desc(), ModelCatalog.model_id.asc())
        )
        selected_model = result.scalars().first()

    default_model = selected_model.model_id if selected_model else "gpt-4o-mini"
    base_url = str(request.base_url).rstrip("/")
    endpoint = f"{base_url}/v1"
    auth_token = settings.master_key

    return ExportConfigResponse(
        api_key=auth_token,
        homepage=export_config["homepage"],
        claude_endpoint=base_url,
        codex_endpoint=endpoint,
        gemini_endpoint=endpoint,
        default_model=default_model,
        default_names={
            "claude": "local Claude",
            "codex": "local Codex",
            "gemini": "local Gemini",
        },
        usage_guide_default_content=export_config["usage_guide_default_content"],
    )


# ============ Provider 扩展配置 ============

class ProviderExtConfig(BaseModel):
    """单个 provider 的扩展配置"""
    password: Optional[str] = None


class ProviderExtConfigMap(BaseModel):
    """所有 provider 扩展配置"""
    providers: dict[str, ProviderExtConfig] = Field(default_factory=dict)


@router.get("/provider-ext-config", response_model=ProviderExtConfigMap)
async def get_provider_ext_config(
    _: bool = Depends(verify_admin_key),
):
    """获取 provider 扩展配置（密码脱敏返回）"""
    raw: dict = export_config.get("provider_ext") or {}
    result = {}
    for provider, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        pwd = cfg.get("password") or ""
        result[provider] = ProviderExtConfig(
            password="*" * min(len(pwd), 8) if pwd else "",
        )
    return ProviderExtConfigMap(providers=result)


@router.put("/provider-ext-config", response_model=ProviderExtConfigMap)
async def update_provider_ext_config(
    data: ProviderExtConfigMap,
    _: bool = Depends(verify_admin_key),
):
    """更新 provider 扩展配置"""
    current: dict = export_config.get("provider_ext") or {}
    for provider, cfg in data.providers.items():
        provider_key = provider.strip().lower()
        if not provider_key:
            continue
        existing = current.get(provider_key) or {}
        if not isinstance(existing, dict):
            existing = {}
        # 密码全是 * 表示未修改，保留原值
        new_pwd = cfg.password or ""
        if new_pwd and not all(c == "*" for c in new_pwd):
            existing["password"] = new_pwd
        elif not new_pwd:
            existing.pop("password", None)
        current[provider_key] = existing

    export_config["provider_ext"] = current
    persist_export_config()

    result = {}
    for provider, cfg in current.items():
        pwd = cfg.get("password") or ""
        result[provider] = ProviderExtConfig(
            password="*" * min(len(pwd), 8) if pwd else "",
        )
    return ProviderExtConfigMap(providers=result)


@router.get("/provider-balance")
async def get_provider_balance(
    key_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询指定 Key 的余额（通过 New API 登录接口，复用 Key 的代理和 fake IP 配置）"""
    import httpx as _httpx
    from models import ApiKey

    key = await db.get(ApiKey, key_id)
    if not key:
        raise HTTPException(status_code=404, detail="API Key 不存在")

    provider_key = (getattr(key, "provider", "") or "").strip().lower()
    provider_ext: dict = export_config.get("provider_ext") or {}
    cfg = provider_ext.get(provider_key) or {}

    # 优先用 Key 自身的密码，为空则取供应商默认密码
    password = (getattr(key, "password", None) or "").strip()
    if not password:
        password = (cfg.get("password") or "").strip()

    if not password:
        raise HTTPException(status_code=400, detail=f"未配置 {provider_key} 的登录密码，请在 Key 详情或系统设置中配置")

    key_name = (getattr(key, "name", "") or "").strip()
    base_url = (getattr(key, "base_url", "") or "").strip().rstrip("/")
    # 余额查询优先用网页网址 wz_url，为空则取 base_url
    web_url = (getattr(key, "wz_url", None) or "").strip().rstrip("/") or base_url
    if not web_url:
        raise HTTPException(status_code=400, detail="Key 未配置请求地址")

    origin = resolve_web_origin(web_url)
    if not origin:
        raise HTTPException(status_code=400, detail="Key 未配置有效的网页网址或请求地址")

    api_type = normalize_api_type(getattr(key, "api_type", None))
    if api_type == "other":
        raise HTTPException(status_code=400, detail="其他类型 Key 不支持余额查询")

    client_kwargs = proxy_service._build_client_kwargs(key, proxy_service._build_image_generation_timeout())

    try:
        async with _httpx.AsyncClient(**client_kwargs) as client:
            if api_type == "sub2api":
                login_url = f"{origin}/api/v1/auth/login"
                self_url = f"{origin}/api/v1/auth/me?timezone=Etc%2FGMT-8"
                login_headers = {"accept": "application/json, text/plain, */*", "content-type": "application/json"}
                proxy_service._apply_fake_ip_headers(key, login_headers)
                login_resp = await client.post(
                    login_url,
                    headers=login_headers,
                    json={"email": key_name, "password": password},
                )
                if login_resp.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"登录失败: HTTP {login_resp.status_code}")

                login_data = proxy_service._parse_response_body(login_resp)
                if not isinstance(login_data, dict) or login_data.get("code") not in (0, "0", None):
                    msg = proxy_service._extract_error_message(login_data, "登录失败")
                    raise HTTPException(status_code=502, detail=msg)

                access_token = parse_sub2api_token(login_data)
                if not access_token:
                    raise HTTPException(status_code=502, detail=f"登录成功但未返回 token，返回字段: {list(login_data.keys())}")
                login_user = parse_sub2api_user(login_data)

                self_headers = {"accept": "application/json, text/plain, */*", "authorization": f"Bearer {access_token}"}
                proxy_service._apply_fake_ip_headers(key, self_headers)
                self_resp = await client.get(self_url, headers=self_headers)
                if self_resp.status_code >= 400:
                    raise HTTPException(status_code=502, detail=f"查询余额失败: HTTP {self_resp.status_code}")
                self_data = proxy_service._parse_response_body(self_resp)
                if not isinstance(self_data, dict) or self_data.get("code") not in (0, "0", None):
                    msg = proxy_service._extract_error_message(self_data, "查询余额接口返回失败")
                    raise HTTPException(status_code=502, detail=msg)
                user = parse_sub2api_user(self_data)
                try:
                    balance_usd, used_usd = parse_sub2api_balance(user, login_user)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=502, detail=f"查询余额接口未返回有效余额，返回字段: {list(user.keys())}")
                return {
                    "balance_usd": balance_usd,
                    "used_usd": used_usd,
                    "display_name": user.get("username") or user.get("email") or login_user.get("username") or login_user.get("email") or key_name,
                    "api_type": "sub2api",
                }

            # 登录
            login_url = f"{origin}/api/user/login?turnstile="
            self_url = f"{origin}/api/user/self"
            login_headers = proxy_service._build_magic666_headers(api_key=key)
            login_headers["content-type"] = "application/json"
            login_resp = await client.post(
                login_url,
                headers=login_headers,
                json={"username": key_name, "password": password},
            )
            if login_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"登录失败: HTTP {login_resp.status_code}")

            login_data = proxy_service._parse_response_body(login_resp)
            if not isinstance(login_data, dict) or not login_data.get("success"):
                msg = proxy_service._extract_error_message(login_data, "登录失败")
                raise HTTPException(status_code=502, detail=msg)

            user_data = login_data.get("data") or {}
            user_id = user_data.get("id")

            # 查询用户信息
            self_headers = proxy_service._build_magic666_headers(user_id=user_id, api_key=key)
            self_resp = await client.get(self_url, headers=self_headers)
            if self_resp.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"查询余额失败: HTTP {self_resp.status_code}")

            self_data = proxy_service._parse_response_body(self_resp)
            if not isinstance(self_data, dict) or not self_data.get("success"):
                raise HTTPException(status_code=502, detail="查询余额接口返回失败")

            user = self_data.get("data") or {}
            quota = int(user.get("quota") or 0)
            used_quota = int(user.get("used_quota") or 0)
            # 1 美元 = 500,000 quota
            balance_usd = round(quota / 500000, 6)
            used_usd = round(used_quota / 500000, 6)

            return {
                "quota": quota,
                "used_quota": used_quota,
                "balance_usd": balance_usd,
                "used_usd": used_usd,
                "display_name": user.get("display_name") or user.get("username") or key_name,
                "api_type": "newapi",
            }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"查询余额失败: {e}")


# ============ 余额降权规则配置 ============

class BalanceDowngradeRule(BaseModel):
    min: Optional[float] = None
    max: Optional[float] = None
    action: str = "disable"   # none | weight | disable
    weight: Optional[int] = None
    providers: Optional[List[str]] = None  # 留空匹配所有提供商，填写后只对指定提供商生效


class BalanceDowngradeRulesResponse(BaseModel):
    rules: List[BalanceDowngradeRule]


class BalanceDowngradeRulesUpdate(BaseModel):
    rules: List[BalanceDowngradeRule]


@router.get("/balance-downgrade-rules", response_model=BalanceDowngradeRulesResponse)
async def get_balance_downgrade_rules(
    _: bool = Depends(verify_admin_key),
):
    """获取余额不足降权规则"""
    raw = export_config.get("balance_downgrade_rules") or []
    rules = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rules.append(BalanceDowngradeRule(
            min=item.get("min"),
            max=item.get("max"),
            action=item.get("action", "disable"),
            weight=item.get("weight"),
            providers=item.get("providers") or None,
        ))
    return BalanceDowngradeRulesResponse(rules=rules)


@router.put("/balance-downgrade-rules", response_model=BalanceDowngradeRulesResponse)
async def update_balance_downgrade_rules(
    data: BalanceDowngradeRulesUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新余额不足降权规则"""
    rules = []
    for rule in data.rules:
        item: dict = {"action": rule.action}
        if rule.min is not None:
            item["min"] = rule.min
        if rule.max is not None:
            item["max"] = rule.max
        if rule.action == "weight" and rule.weight is not None:
            item["weight"] = max(1, int(rule.weight))
        if rule.providers:
            item["providers"] = [p.strip().lower() for p in rule.providers if p.strip()]
        rules.append(item)

    export_config["balance_downgrade_rules"] = rules
    persist_export_config()

    return BalanceDowngradeRulesResponse(rules=[
        BalanceDowngradeRule(
            min=r.get("min"), max=r.get("max"),
            action=r.get("action", "disable"), weight=r.get("weight"),
            providers=r.get("providers") or None,
        ) for r in rules
    ])


# ============ 流式缓冲规则配置 ============

class StreamBufferRule(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None


class StreamBufferRulesResponse(BaseModel):
    rules: List[StreamBufferRule]


class StreamBufferRulesUpdate(BaseModel):
    rules: List[StreamBufferRule]


@router.get("/stream-buffer-rules", response_model=StreamBufferRulesResponse)
async def get_stream_buffer_rules(
    _: bool = Depends(verify_admin_key),
):
    """获取流式缓冲规则"""
    raw = export_config.get("stream_buffer_rules") or []
    rules = [StreamBufferRule(provider=r.get("provider"), model=r.get("model")) for r in raw if isinstance(r, dict)]
    return StreamBufferRulesResponse(rules=rules)


@router.put("/stream-buffer-rules", response_model=StreamBufferRulesResponse)
async def update_stream_buffer_rules(
    data: StreamBufferRulesUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新流式缓冲规则"""
    rules = []
    for item in data.rules:
        entry: dict = {}
        if item.provider and item.provider.strip():
            entry["provider"] = item.provider.strip()
        if item.model and item.model.strip():
            entry["model"] = item.model.strip()
        rules.append(entry)

    export_config["stream_buffer_rules"] = rules
    persist_export_config()
    return StreamBufferRulesResponse(rules=[StreamBufferRule(provider=r.get("provider"), model=r.get("model")) for r in rules])


# ============ 显示设置配置 ============

class ShowActualModelResponse(BaseModel):
    show_actual_model: bool


@router.get("/show-actual-model", response_model=ShowActualModelResponse)
async def get_show_actual_model(
    _: bool = Depends(verify_admin_key),
):
    """获取是否向管理员显示实际模型的配置"""
    return ShowActualModelResponse(show_actual_model=bool(export_config.get("show_actual_model", False)))


@router.put("/show-actual-model", response_model=ShowActualModelResponse)
async def update_show_actual_model(
    data: ShowActualModelResponse,
    _: bool = Depends(verify_admin_key),
):
    """更新是否向管理员显示实际模型的配置"""
    export_config["show_actual_model"] = bool(data.show_actual_model)
    persist_export_config()
    return ShowActualModelResponse(show_actual_model=bool(data.show_actual_model))


# ============ 用户额度用量查询与重置 ============

class UserQuotaUsageResponse(BaseModel):
    user_id: int
    daily_used: int
    weekly_used: int
    monthly_used: int
    daily_limit: Optional[int]
    weekly_limit: Optional[int]
    monthly_limit: Optional[int]
    quota_reset_at: Optional[datetime]


@router.get("/users/{user_id}/quota-usage", response_model=UserQuotaUsageResponse)
async def get_user_quota_usage(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """查询指定用户当前周期的 token 用量"""
    from models.admin_user import AdminUser
    from models import UsageLog
    from sqlalchemy import func
    from datetime import datetime, timedelta

    user = await db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    now = datetime.utcnow()
    quota_reset_at = getattr(user, "quota_reset_at", None)

    async def get_used(start: datetime) -> int:
        effective_start = start
        if quota_reset_at and quota_reset_at > start:
            effective_start = quota_reset_at
        result = await db.execute(
            select(func.coalesce(func.sum(UsageLog.total_tokens), 0)).where(
                UsageLog.user_id == user_id,
                UsageLog.request_time >= effective_start,
                UsageLog.status == "success",
            )
        )
        return int(result.scalar() or 0)

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    daily_used, weekly_used, monthly_used = 0, 0, 0
    if getattr(user, "daily_token_limit", None):
        daily_used = await get_used(day_start)
    if getattr(user, "weekly_token_limit", None):
        weekly_used = await get_used(week_start)
    if getattr(user, "monthly_token_limit", None):
        monthly_used = await get_used(month_start)

    return UserQuotaUsageResponse(
        user_id=user_id,
        daily_used=daily_used,
        weekly_used=weekly_used,
        monthly_used=monthly_used,
        daily_limit=getattr(user, "daily_token_limit", None),
        weekly_limit=getattr(user, "weekly_token_limit", None),
        monthly_limit=getattr(user, "monthly_token_limit", None),
        quota_reset_at=quota_reset_at,
    )


@router.post("/users/{user_id}/quota-reset")
async def reset_user_quota(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """重置用户额度（将 quota_reset_at 设为当前时间，之后的请求才计入用量）"""
    from models.admin_user import AdminUser
    from datetime import datetime

    user = await db.get(AdminUser, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.quota_reset_at = datetime.utcnow()
    await db.commit()
    return {"success": True, "quota_reset_at": user.quota_reset_at.isoformat()}


# ============ 供应商迁移规则配置 ============

class ProviderMigrationRule(BaseModel):
    from_provider: str
    to_provider: str
    min_balance: float = 0.0
    max_balance: Optional[float] = None
    supported_models: List[str] = Field(default_factory=list)


class ProviderMigrationRulesResponse(BaseModel):
    rules: List[ProviderMigrationRule]


class ProviderMigrationRulesUpdate(BaseModel):
    rules: List[ProviderMigrationRule]


@router.get("/provider-migration-rules", response_model=ProviderMigrationRulesResponse)
async def get_provider_migration_rules(
    _: bool = Depends(verify_admin_key),
):
    """获取供应商迁移规则"""
    raw = export_config.get("provider_migration_rules") or []
    rules = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rules.append(ProviderMigrationRule(
            from_provider=item.get("from_provider", ""),
            to_provider=item.get("to_provider", ""),
            min_balance=float(item.get("min_balance") or 0),
            max_balance=item.get("max_balance"),
            supported_models=item.get("supported_models") or [],
        ))
    return ProviderMigrationRulesResponse(rules=rules)


@router.put("/provider-migration-rules", response_model=ProviderMigrationRulesResponse)
async def update_provider_migration_rules(
    data: ProviderMigrationRulesUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新供应商迁移规则"""
    rules = []
    for rule in data.rules:
        item = {
            "from_provider": rule.from_provider.strip(),
            "to_provider": rule.to_provider.strip(),
            "min_balance": rule.min_balance,
            "supported_models": rule.supported_models,
        }
        if rule.max_balance is not None:
            item["max_balance"] = rule.max_balance
        rules.append(item)

    export_config["provider_migration_rules"] = rules
    persist_export_config()
    return ProviderMigrationRulesResponse(rules=data.rules)


# ============ 透传错误码配置 ============

class PassThroughErrorCodesResponse(BaseModel):
    pass_through_error_codes: List[int]


class PassThroughErrorCodesUpdate(BaseModel):
    pass_through_error_codes: List[int]


@router.get("/pass-through-error-codes", response_model=PassThroughErrorCodesResponse)
async def get_pass_through_error_codes(
    _: bool = Depends(verify_admin_key),
):
    """获取透传错误码配置"""
    codes = export_config.get("pass_through_error_codes") or []
    return PassThroughErrorCodesResponse(pass_through_error_codes=[int(c) for c in codes])


@router.put("/pass-through-error-codes", response_model=PassThroughErrorCodesResponse)
async def update_pass_through_error_codes(
    data: PassThroughErrorCodesUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新透传错误码配置"""
    valid_codes = [int(c) for c in data.pass_through_error_codes if 400 <= int(c) < 600]
    export_config["pass_through_error_codes"] = valid_codes
    persist_export_config()
    return PassThroughErrorCodesResponse(pass_through_error_codes=valid_codes)


# ============ 模型种子配置 ============

class ModelSeedConfigResponse(BaseModel):
    model_seed_enabled: bool


class ModelSeedConfigUpdate(BaseModel):
    model_seed_enabled: bool


@router.get("/model-seed-config", response_model=ModelSeedConfigResponse)
async def get_model_seed_config(
    _: bool = Depends(verify_admin_key),
):
    """获取模型种子回填配置"""
    return ModelSeedConfigResponse(model_seed_enabled=bool(export_config.get("model_seed_enabled", True)))


@router.put("/model-seed-config", response_model=ModelSeedConfigResponse)
async def update_model_seed_config(
    data: ModelSeedConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新模型种子回填配置"""
    export_config["model_seed_enabled"] = bool(data.model_seed_enabled)
    persist_export_config()
    return ModelSeedConfigResponse(model_seed_enabled=bool(data.model_seed_enabled))




# ============ 代理调试追踪配置 ============

class ProxyTraceConfigResponse(BaseModel):
    proxy_trace_enabled: bool
    proxy_trace_retention_hours: int
    proxy_trace_sample_rate: float
    proxy_trace_only_failures: bool
    proxy_trace_target_provider: str
    proxy_trace_target_model: str


class ProxyTraceConfigUpdate(BaseModel):
    proxy_trace_enabled: bool
    proxy_trace_retention_hours: int = Field(24, ge=1, le=168)
    proxy_trace_sample_rate: float = Field(1.0, ge=0.0, le=1.0)
    proxy_trace_only_failures: bool = False
    proxy_trace_target_provider: str = ""
    proxy_trace_target_model: str = ""


class ProxyTraceSummaryResponse(BaseModel):
    trace_id: str
    created_at: datetime
    user_id: Optional[int]
    api_key_id: Optional[int]
    provider: Optional[str]
    key_name: Optional[str]
    requested_model: Optional[str]
    actual_model: Optional[str]
    status_code: Optional[int]
    result_status: str
    latency_ms: int
    upstream_latency_ms: int
    error_summary: Optional[str]


class ProxyTraceListResponse(BaseModel):
    items: List[ProxyTraceSummaryResponse]


class ProxyTraceDetailResponse(ProxyTraceSummaryResponse):
    route_summary: Any
    attempts: Any


class ProxyTraceCleanupResponse(BaseModel):
    deleted_count: int


def _parse_trace_json(value: Optional[str]) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _to_trace_summary(item) -> ProxyTraceSummaryResponse:
    return ProxyTraceSummaryResponse(
        trace_id=item.trace_id,
        created_at=item.created_at,
        user_id=item.user_id,
        api_key_id=item.api_key_id,
        provider=item.provider,
        key_name=item.key_name,
        requested_model=item.requested_model,
        actual_model=item.actual_model,
        status_code=item.status_code,
        result_status=item.result_status,
        latency_ms=item.latency_ms,
        upstream_latency_ms=item.upstream_latency_ms,
        error_summary=item.error_summary,
    )


@router.get("/proxy-trace-config", response_model=ProxyTraceConfigResponse)
async def get_proxy_trace_config(
    _: bool = Depends(verify_admin_key),
):
    """获取代理调试追踪配置"""
    return ProxyTraceConfigResponse(**normalize_trace_config())


@router.put("/proxy-trace-config", response_model=ProxyTraceConfigResponse)
async def update_proxy_trace_config(
    data: ProxyTraceConfigUpdate,
    _: bool = Depends(verify_admin_key),
):
    """更新代理调试追踪配置"""
    normalized = normalize_trace_config(data.model_dump())
    export_config.update(normalized)
    persist_export_config()
    return ProxyTraceConfigResponse(**normalized)


@router.get("/proxy-traces", response_model=ProxyTraceListResponse)
async def list_proxy_traces(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取代理调试追踪列表"""
    items = await proxy_trace_service.list_traces(db, limit=limit, offset=offset)
    return ProxyTraceListResponse(items=[_to_trace_summary(item) for item in items])


@router.get("/proxy-traces/{trace_id}", response_model=ProxyTraceDetailResponse)
async def get_proxy_trace(
    trace_id: str,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """获取代理调试追踪详情"""
    item = await proxy_trace_service.get_trace(db, trace_id)
    if not item:
        raise HTTPException(status_code=404, detail="追踪记录不存在")
    summary = _to_trace_summary(item).model_dump()
    return ProxyTraceDetailResponse(
        **summary,
        route_summary=_parse_trace_json(item.route_summary),
        attempts=_parse_trace_json(item.attempts),
    )


@router.delete("/proxy-traces/cleanup", response_model=ProxyTraceCleanupResponse)
async def cleanup_proxy_traces(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """清理过期代理调试追踪"""
    deleted_count = await proxy_trace_service.cleanup_expired(db)
    return ProxyTraceCleanupResponse(deleted_count=deleted_count)


class FactoryResetRequest(BaseModel):
    keep_providers: List[str]
    confirmation: str


class FactoryResetResponse(BaseModel):
    deleted_keys: int
    deleted_models: int
    deleted_usage_logs: int
    deleted_usage_summaries: int
    deleted_image_tasks: int
    deleted_image_task_results: int
    deleted_image_key_model_stats: int
    deleted_content_guard_events: int
    deleted_provider_model_priorities: int
    deleted_provider_model_mappings: int
    message: str


@router.post("/factory-reset", response_model=FactoryResetResponse)
async def factory_reset(
    data: FactoryResetRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    """一键还原：清除非保留提供商的数据，保留用户信息和指定提供商"""
    if data.confirmation != "确认还原":
        raise HTTPException(status_code=400, detail="确认文本不匹配")

    # 规范化保留提供商列表
    keep_providers = {p.strip().lower() for p in data.keep_providers if p.strip()}

    # 收集要删除的 Key IDs
    from models import ApiKey
    if keep_providers:
        keys_result = await db.execute(
            select(ApiKey.id).where(ApiKey.provider.notin_(keep_providers))
        )
    else:
        keys_result = await db.execute(select(ApiKey.id))
    delete_key_ids = [row[0] for row in keys_result.all()]

    # 按外键依赖顺序删除关联数据
    counts = {
        "content_guard_events": 0,
        "provider_model_priorities": 0,
        "provider_model_mappings": 0,
        "image_key_model_stats": 0,
        "image_task_results": 0,
        "image_tasks": 0,
        "usage_summaries": 0,
        "usage_logs": 0,
        "keys": 0,
        "models": 0,
    }

    # 1. content_guard_events
    from models import ContentGuardEvent
    result = await db.execute(
        sql_delete(ContentGuardEvent).where(ContentGuardEvent.api_key_id.in_(delete_key_ids))
    )
    counts["content_guard_events"] = result.rowcount

    # 2. provider_model_priorities
    from models import ProviderModelPriority
    result = await db.execute(
        sql_delete(ProviderModelPriority).where(ProviderModelPriority.key_id.in_(delete_key_ids))
    )
    counts["provider_model_priorities"] = result.rowcount

    # 3. provider_model_mappings（按 provider 过滤）
    from models import ProviderModelMapping
    if keep_providers:
        result = await db.execute(
            sql_delete(ProviderModelMapping).where(ProviderModelMapping.provider.notin_(keep_providers))
        )
    else:
        result = await db.execute(sql_delete(ProviderModelMapping))
    counts["provider_model_mappings"] = result.rowcount

    # 4. image_key_model_stats
    from models import ImageKeyModelStats
    result = await db.execute(
        sql_delete(ImageKeyModelStats).where(ImageKeyModelStats.api_key_id.in_(delete_key_ids))
    )
    counts["image_key_model_stats"] = result.rowcount

    # 5. 查询要删除的图片任务 IDs
    from models import ImageGenerationTask, ImageGenerationTaskResult
    tasks_result = await db.execute(
        select(ImageGenerationTask.id).where(ImageGenerationTask.api_key_id.in_(delete_key_ids))
    )
    delete_task_ids = [row[0] for row in tasks_result.all()]

    # 6. image_generation_task_results
    if delete_task_ids:
        result = await db.execute(
            sql_delete(ImageGenerationTaskResult).where(ImageGenerationTaskResult.task_id.in_(delete_task_ids))
        )
        counts["image_task_results"] = result.rowcount

    # 7. image_generation_tasks
    result = await db.execute(
        sql_delete(ImageGenerationTask).where(ImageGenerationTask.api_key_id.in_(delete_key_ids))
    )
    counts["image_tasks"] = result.rowcount

    # 8. usage_daily_summaries
    from models import UsageDailySummary
    result = await db.execute(
        sql_delete(UsageDailySummary).where(UsageDailySummary.api_key_id.in_(delete_key_ids))
    )
    counts["usage_summaries"] = result.rowcount

    # 9. usage_logs
    from models import UsageLog
    result = await db.execute(
        sql_delete(UsageLog).where(UsageLog.api_key_id.in_(delete_key_ids))
    )
    counts["usage_logs"] = result.rowcount

    # 10. 删除非保留提供商的 Key
    result = await db.execute(
        sql_delete(ApiKey).where(ApiKey.id.in_(delete_key_ids))
    )
    counts["keys"] = result.rowcount

    # 11. 整理模型广场：只保留 keep_providers 对应的模型，其余全部删除
    from models import ModelCatalog
    if keep_providers:
        result = await db.execute(
            sql_delete(ModelCatalog).where(ModelCatalog.provider.notin_(keep_providers))
        )
    else:
        result = await db.execute(sql_delete(ModelCatalog))
    counts["models"] = result.rowcount

    # 关闭模型种子自动回填，避免 DEFAULT_MODELS 再次插入已删除的模型
    export_config["model_seed_enabled"] = False
    persist_export_config()

    # 12. 重置 pool_manager
    for key_id in delete_key_ids:
        pool_manager.clear_key_cooldown(key_id)
    pool_manager.reset_index()

    await db.commit()

    print(
        f"[CPA FACTORY RESET] deleted_keys={counts['keys']} "
        f"deleted_models={counts['models']} "
        f"deleted_usage_logs={counts['usage_logs']} "
        f"kept_providers={keep_providers}"
    )

    return FactoryResetResponse(
        deleted_keys=counts["keys"],
        deleted_models=counts["models"],
        deleted_usage_logs=counts["usage_logs"],
        deleted_usage_summaries=counts["usage_summaries"],
        deleted_image_tasks=counts["image_tasks"],
        deleted_image_task_results=counts["image_task_results"],
        deleted_image_key_model_stats=counts["image_key_model_stats"],
        deleted_content_guard_events=counts["content_guard_events"],
        deleted_provider_model_priorities=counts["provider_model_priorities"],
        deleted_provider_model_mappings=counts["provider_model_mappings"],
        message=f"还原完成：删除 {counts['keys']} 个 Key，{counts['models']} 个模型，{counts['usage_logs']} 条使用记录",
    )
