"""
统计接口 - Token 用量统计
"""
from collections import defaultdict
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from services import usage_rollup_service
from services.pool_manager import pool_manager


router = APIRouter()


class UsageSummary(BaseModel):
    """用量汇总"""
    total_requests: int
    success_requests: int
    error_requests: int
    in_progress_requests: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cache_tokens: int
    avg_latency_ms: float
    avg_upstream_latency_ms: float
    avg_cpa_overhead_ms: float


class KeyUsageSummary(BaseModel):
    """单个 Key 的用量汇总"""
    api_key_id: int
    api_key_name: str
    provider: str
    supported_models: List[str] = Field(default_factory=list)
    total_requests: int
    success_requests: int
    error_requests: int
    in_progress_requests: int
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int
    cache_tokens: int
    avg_latency_ms: float
    avg_upstream_latency_ms: float
    avg_cpa_overhead_ms: float


class DailyUsage(BaseModel):
    """每日用量"""
    date: str
    total_requests: int
    total_tokens: int


class UsageLogResponse(BaseModel):
    """用量记录响应"""
    id: int
    api_key_id: int
    api_key_name: Optional[str] = None
    model: Optional[str]
    actual_model: Optional[str] = None
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cache_tokens: int
    latency_ms: int
    upstream_latency_ms: int
    cpa_overhead_ms: int
    status: str
    error_message: Optional[str]
    request_time: datetime

    class Config:
        from_attributes = True


class UsageLogPagedResponse(BaseModel):
    """用量记录分页响应"""
    items: List[UsageLogResponse]
    total: int
    page: int
    limit: int


def _empty_metrics() -> dict:
    return {
        "total_requests": 0,
        "success_requests": 0,
        "error_requests": 0,
        "in_progress_requests": 0,
        "total_tokens": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "cache_tokens": 0,
        "latency_sum_ms": 0,
        "latency_count": 0,
        "upstream_latency_sum_ms": 0,
        "upstream_latency_count": 0,
        "cpa_overhead_sum_ms": 0,
        "cpa_overhead_count": 0,
    }


def _merge_metrics(base: dict, extra: dict) -> dict:
    merged = dict(base)
    for key in _empty_metrics().keys():
        merged[key] = int(base.get(key, 0) or 0) + int(extra.get(key, 0) or 0)
    return merged


def _format_summary(metrics: dict) -> UsageSummary:
    latency_count = metrics["latency_count"] or 0
    upstream_count = metrics["upstream_latency_count"] or 0
    cpa_count = metrics["cpa_overhead_count"] or 0
    return UsageSummary(
        total_requests=metrics["total_requests"],
        success_requests=metrics["success_requests"],
        error_requests=metrics["error_requests"],
        in_progress_requests=metrics["in_progress_requests"],
        total_tokens=metrics["total_tokens"],
        prompt_tokens=metrics["prompt_tokens"],
        completion_tokens=metrics["completion_tokens"],
        cache_tokens=metrics.get("cache_tokens", 0),
        avg_latency_ms=round(metrics["latency_sum_ms"] / latency_count, 2) if latency_count else 0,
        avg_upstream_latency_ms=round(metrics["upstream_latency_sum_ms"] / upstream_count, 2) if upstream_count else 0,
        avg_cpa_overhead_ms=round(metrics["cpa_overhead_sum_ms"] / cpa_count, 2) if cpa_count else 0,
    )


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


def _resolve_user_id(auth_info: dict, user_id: Optional[int]) -> Optional[int]:
    """根据认证信息确定有效的 user_id：普通用户只能查自己"""
    if auth_info.get("is_admin"):
        return user_id
    return auth_info.get("user_id")


async def _get_summary_metrics(
    db: AsyncSession,
    days: int,
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    api_key_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> dict:
    from models import UsageDailySummary, UsageLog

    window = usage_rollup_service.split_time_range(days, start_time, end_time)
    metrics = _empty_metrics()

    if window.summary_start and window.summary_end:
        summary_query = select(
            func.coalesce(func.sum(UsageDailySummary.total_requests), 0).label("total_requests"),
            func.coalesce(func.sum(UsageDailySummary.success_requests), 0).label("success_requests"),
            func.coalesce(func.sum(UsageDailySummary.error_requests), 0).label("error_requests"),
            func.coalesce(func.sum(UsageDailySummary.in_progress_requests), 0).label("in_progress_requests"),
            func.coalesce(func.sum(UsageDailySummary.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(UsageDailySummary.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageDailySummary.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(UsageDailySummary.cache_tokens), 0).label("cache_tokens"),
            func.coalesce(func.sum(UsageDailySummary.latency_sum_ms), 0).label("latency_sum_ms"),
            func.coalesce(func.sum(UsageDailySummary.latency_count), 0).label("latency_count"),
            func.coalesce(func.sum(UsageDailySummary.upstream_latency_sum_ms), 0).label("upstream_latency_sum_ms"),
            func.coalesce(func.sum(UsageDailySummary.upstream_latency_count), 0).label("upstream_latency_count"),
            func.coalesce(func.sum(UsageDailySummary.cpa_overhead_sum_ms), 0).label("cpa_overhead_sum_ms"),
            func.coalesce(func.sum(UsageDailySummary.cpa_overhead_count), 0).label("cpa_overhead_count"),
        ).where(
            UsageDailySummary.summary_date >= window.summary_start.date(),
            UsageDailySummary.summary_date <= window.summary_end.date(),
        )
        if api_key_id:
            summary_query = summary_query.where(UsageDailySummary.api_key_id == api_key_id)
        if user_id:
            summary_query = summary_query.where(UsageDailySummary.user_id == user_id)
        summary_row = (await db.execute(summary_query)).one()
        metrics = _merge_metrics(metrics, dict(summary_row._mapping))

    if window.realtime_start and window.realtime_end:
        realtime_query = select(
            func.count(UsageLog.id).label("total_requests"),
            func.sum(case((UsageLog.status == "success", 1), else_=0)).label("success_requests"),
            func.sum(case((UsageLog.status == "error", 1), else_=0)).label("error_requests"),
            func.sum(case((UsageLog.status == "in_progress", 1), else_=0)).label("in_progress_requests"),
            func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(UsageLog.cache_tokens), 0).label("cache_tokens"),
            func.coalesce(func.sum(UsageLog.latency_ms), 0).label("latency_sum_ms"),
            func.coalesce(func.sum(case((UsageLog.latency_ms > 0, 1), else_=0)), 0).label("latency_count"),
            func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, UsageLog.upstream_latency_ms), else_=0)), 0).label("upstream_latency_sum_ms"),
            func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, 1), else_=0)), 0).label("upstream_latency_count"),
            func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, UsageLog.cpa_overhead_ms), else_=0)), 0).label("cpa_overhead_sum_ms"),
            func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, 1), else_=0)), 0).label("cpa_overhead_count"),
        ).where(
            UsageLog.request_time >= window.realtime_start,
            UsageLog.request_time <= window.realtime_end,
        )
        if api_key_id:
            realtime_query = realtime_query.where(UsageLog.api_key_id == api_key_id)
        if user_id:
            realtime_query = realtime_query.where(UsageLog.user_id == user_id)
        realtime_row = (await db.execute(realtime_query)).one()
        metrics = _merge_metrics(metrics, dict(realtime_row._mapping))

    return metrics


@router.get("/summary", response_model=UsageSummary)
async def get_usage_summary(
    days: int = Query(default=7, ge=1, le=365),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    api_key_id: Optional[int] = None,
    user_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    effective_user_id = _resolve_user_id(auth_info, user_id)
    metrics = await _get_summary_metrics(db, days, start_time, end_time, api_key_id, effective_user_id)
    return _format_summary(metrics)


@router.get("/by-key", response_model=List[KeyUsageSummary])
async def get_usage_by_key(
    days: int = Query(default=7, ge=1, le=365),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    providers: Optional[List[str]] = Query(default=None),
    models: Optional[List[str]] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    from models import ApiKey, UsageDailySummary, UsageLog

    effective_user_id = _resolve_user_id(auth_info, user_id)
    window = usage_rollup_service.split_time_range(days, start_time, end_time)
    merged_by_key: dict[int, dict] = defaultdict(_empty_metrics)
    provider_values = [value.strip().lower() for value in (providers or []) if isinstance(value, str) and value.strip()]
    model_values = [value.strip().lower() for value in (models or []) if isinstance(value, str) and value.strip()]

    if window.summary_start and window.summary_end:
        summary_query = (
            select(
                UsageDailySummary.api_key_id.label("api_key_id"),
                func.coalesce(func.sum(UsageDailySummary.total_requests), 0).label("total_requests"),
                func.coalesce(func.sum(UsageDailySummary.success_requests), 0).label("success_requests"),
                func.coalesce(func.sum(UsageDailySummary.error_requests), 0).label("error_requests"),
                func.coalesce(func.sum(UsageDailySummary.in_progress_requests), 0).label("in_progress_requests"),
                func.coalesce(func.sum(UsageDailySummary.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(UsageDailySummary.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(UsageDailySummary.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(UsageDailySummary.cache_tokens), 0).label("cache_tokens"),
                func.coalesce(func.sum(UsageDailySummary.latency_sum_ms), 0).label("latency_sum_ms"),
                func.coalesce(func.sum(UsageDailySummary.latency_count), 0).label("latency_count"),
                func.coalesce(func.sum(UsageDailySummary.upstream_latency_sum_ms), 0).label("upstream_latency_sum_ms"),
                func.coalesce(func.sum(UsageDailySummary.upstream_latency_count), 0).label("upstream_latency_count"),
                func.coalesce(func.sum(UsageDailySummary.cpa_overhead_sum_ms), 0).label("cpa_overhead_sum_ms"),
                func.coalesce(func.sum(UsageDailySummary.cpa_overhead_count), 0).label("cpa_overhead_count"),
            )
            .where(
                UsageDailySummary.summary_date >= window.summary_start.date(),
                UsageDailySummary.summary_date <= window.summary_end.date(),
            )
            .group_by(UsageDailySummary.api_key_id)
        )
        if effective_user_id:
            summary_query = summary_query.where(UsageDailySummary.user_id == effective_user_id)
        for row in (await db.execute(summary_query)).all():
            merged_by_key[row.api_key_id] = _merge_metrics(merged_by_key[row.api_key_id], dict(row._mapping))

    if window.realtime_start and window.realtime_end:
        realtime_query = (
            select(
                UsageLog.api_key_id.label("api_key_id"),
                func.count(UsageLog.id).label("total_requests"),
                func.sum(case((UsageLog.status == "success", 1), else_=0)).label("success_requests"),
                func.sum(case((UsageLog.status == "error", 1), else_=0)).label("error_requests"),
                func.sum(case((UsageLog.status == "in_progress", 1), else_=0)).label("in_progress_requests"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(UsageLog.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(UsageLog.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(UsageLog.cache_tokens), 0).label("cache_tokens"),
                func.coalesce(func.sum(UsageLog.latency_ms), 0).label("latency_sum_ms"),
                func.coalesce(func.sum(case((UsageLog.latency_ms > 0, 1), else_=0)), 0).label("latency_count"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, UsageLog.upstream_latency_ms), else_=0)), 0).label("upstream_latency_sum_ms"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, 1), else_=0)), 0).label("upstream_latency_count"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, UsageLog.cpa_overhead_ms), else_=0)), 0).label("cpa_overhead_sum_ms"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, 1), else_=0)), 0).label("cpa_overhead_count"),
            )
            .where(
                UsageLog.request_time >= window.realtime_start,
                UsageLog.request_time <= window.realtime_end,
            )
            .group_by(UsageLog.api_key_id)
        )
        if effective_user_id:
            realtime_query = realtime_query.where(UsageLog.user_id == effective_user_id)
        for row in (await db.execute(realtime_query)).all():
            merged_by_key[row.api_key_id] = _merge_metrics(merged_by_key[row.api_key_id], dict(row._mapping))

    if not merged_by_key:
        return []

    api_key_result = await db.execute(select(ApiKey).where(ApiKey.id.in_(list(merged_by_key.keys()))))
    key_map = {item.id: item for item in api_key_result.scalars().all()}

    items = []
    for api_key_id, metrics in sorted(merged_by_key.items(), key=lambda item: item[0]):
        key = key_map.get(api_key_id)
        if key is None:
            continue
        provider = getattr(key, "provider", "-")
        supported_models = pool_manager._parse_supported_models(getattr(key, "supported_models", None)) or []

        if provider_values and provider.strip().lower() not in provider_values:
            continue
        if model_values and supported_models:
            supported_lookup = {item.strip().lower() for item in supported_models if isinstance(item, str) and item.strip()}
            if supported_lookup and not any(model in supported_lookup for model in model_values):
                continue

        latency_count = metrics["latency_count"] or 0
        upstream_count = metrics["upstream_latency_count"] or 0
        cpa_count = metrics["cpa_overhead_count"] or 0
        items.append(
            KeyUsageSummary(
                api_key_id=api_key_id,
                api_key_name=getattr(key, "name", f"Key {api_key_id}"),
                provider=provider,
                supported_models=supported_models,
                total_requests=metrics["total_requests"],
                success_requests=metrics["success_requests"],
                error_requests=metrics["error_requests"],
                in_progress_requests=metrics["in_progress_requests"],
                total_tokens=metrics["total_tokens"],
                prompt_tokens=metrics["prompt_tokens"],
                completion_tokens=metrics["completion_tokens"],
                cache_tokens=metrics.get("cache_tokens", 0),
                avg_latency_ms=round(metrics["latency_sum_ms"] / latency_count, 2) if latency_count else 0,
                avg_upstream_latency_ms=round(metrics["upstream_latency_sum_ms"] / upstream_count, 2) if upstream_count else 0,
                avg_cpa_overhead_ms=round(metrics["cpa_overhead_sum_ms"] / cpa_count, 2) if cpa_count else 0,
            )
        )

    return items


@router.get("/daily", response_model=List[DailyUsage])
async def get_daily_usage(
    days: int = Query(default=7, ge=1, le=365),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    api_key_id: Optional[int] = None,
    user_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    from models import UsageDailySummary, UsageLog

    effective_user_id = _resolve_user_id(auth_info, user_id)
    window = usage_rollup_service.split_time_range(days, start_time, end_time)
    daily_map: dict[str, dict] = {}

    if window.summary_start and window.summary_end:
        summary_query = (
            select(
                UsageDailySummary.summary_date.label("date"),
                func.coalesce(func.sum(UsageDailySummary.total_requests), 0).label("total_requests"),
                func.coalesce(func.sum(UsageDailySummary.total_tokens), 0).label("total_tokens"),
            )
            .where(
                UsageDailySummary.summary_date >= window.summary_start.date(),
                UsageDailySummary.summary_date <= window.summary_end.date(),
            )
            .group_by(UsageDailySummary.summary_date)
            .order_by(UsageDailySummary.summary_date)
        )
        if api_key_id:
            summary_query = summary_query.where(UsageDailySummary.api_key_id == api_key_id)
        if effective_user_id:
            summary_query = summary_query.where(UsageDailySummary.user_id == effective_user_id)
        for row in (await db.execute(summary_query)).all():
            daily_map[str(row.date)] = {
                "date": str(row.date),
                "total_requests": int(row.total_requests or 0),
                "total_tokens": int(row.total_tokens or 0),
            }

    if window.realtime_start and window.realtime_end:
        realtime_query = (
            select(
                func.date(UsageLog.request_time).label("date"),
                func.count(UsageLog.id).label("total_requests"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
            )
            .where(
                UsageLog.request_time >= window.realtime_start,
                UsageLog.request_time <= window.realtime_end,
            )
            .group_by(func.date(UsageLog.request_time))
            .order_by(func.date(UsageLog.request_time))
        )
        if api_key_id:
            realtime_query = realtime_query.where(UsageLog.api_key_id == api_key_id)
        if effective_user_id:
            realtime_query = realtime_query.where(UsageLog.user_id == effective_user_id)
        for row in (await db.execute(realtime_query)).all():
            daily_map[str(row.date)] = {
                "date": str(row.date),
                "total_requests": int(row.total_requests or 0),
                "total_tokens": int(row.total_tokens or 0),
            }

    return [DailyUsage(**daily_map[key]) for key in sorted(daily_map.keys())]


@router.get("/logs", response_model=UsageLogPagedResponse)
async def get_usage_logs(
    page: Optional[int] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: Optional[int] = Query(default=None, ge=0),
    days: int = Query(default=7, ge=1, le=365),
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    api_key_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None),
    user_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_admin_key),
):
    """获取用量记录列表，仅返回最近 7 天实时明细"""
    from models import ApiKey, UsageLog

    effective_user_id = _resolve_user_id(auth_info, user_id)
    normalized_start, normalized_end = usage_rollup_service.normalize_time_range(days, start_time, end_time)
    clamped_start = usage_rollup_service.clamp_logs_start(normalized_start)
    page_value, limit_value, offset_value = parse_pagination(page, limit, offset)

    count_query = select(func.count(UsageLog.id)).where(
        UsageLog.request_time >= clamped_start,
        UsageLog.request_time <= normalized_end,
    )
    if api_key_id:
        count_query = count_query.where(UsageLog.api_key_id == api_key_id)
    if status:
        count_query = count_query.where(UsageLog.status == status)
    if effective_user_id:
        count_query = count_query.where(UsageLog.user_id == effective_user_id)

    total = int((await db.execute(count_query)).scalar() or 0)

    query = select(UsageLog).where(
        UsageLog.request_time >= clamped_start,
        UsageLog.request_time <= normalized_end,
    )
    if api_key_id:
        query = query.where(UsageLog.api_key_id == api_key_id)
    if status:
        query = query.where(UsageLog.status == status)
    if effective_user_id:
        query = query.where(UsageLog.user_id == effective_user_id)

    query = query.order_by(UsageLog.request_time.desc()).offset(offset_value).limit(limit_value)
    logs = (await db.execute(query)).scalars().all()

    key_ids = sorted({int(log.api_key_id) for log in logs if log.api_key_id})
    key_name_map = {}
    if key_ids:
        key_result = await db.execute(select(ApiKey.id, ApiKey.name).where(ApiKey.id.in_(key_ids)))
        key_name_map = {int(row.id): row.name for row in key_result.all()}

    items = []
    from config import export_config as _export_config
    show_actual = bool(_export_config.get("show_actual_model", False))
    is_admin_request = auth_info.get("is_admin", False)

    for log in logs:
        item = UsageLogResponse.model_validate(log)
        item.api_key_name = key_name_map.get(int(log.api_key_id)) or f"Key {log.api_key_id}"
        actual = getattr(log, "actual_model", None) or item.model
        if is_admin_request and show_actual and actual and actual != item.model:
            # 管理员且开启显示：格式为 请求模型/映射模型
            item.actual_model = actual
        else:
            # 其他情况：model 显示原始请求模型，actual_model 不暴露
            item.actual_model = None
        items.append(item)

    return {
        "items": items,
        "total": total,
        "page": page_value,
        "limit": limit_value,
    }
