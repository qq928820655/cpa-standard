"""
OpenAI Plus account management and proxy routes
"""
import asyncio
import io
import json
import zipfile
from datetime import datetime, timedelta
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Integer, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker, get_db
from models import OpenAIPlusAccount, OpenAIPlusUsageLog
from config import export_config
from routers.admin import normalize_openai_plus_quota_refresh_config, verify_admin_key
from services import openai_plus_service

router = APIRouter()


class OpenAIPlusImportRequest(BaseModel):
    content: str


class OpenAIPlusUpdateRequest(BaseModel):
    name: Optional[str] = None
    disabled: Optional[bool] = None


class OpenAIPlusBatchUpdateRequest(BaseModel):
    account_ids: list[int]
    disabled: Optional[bool] = None


class OpenAIPlusBatchDeleteRequest(BaseModel):
    account_ids: list[int]


class OpenAIPlusExportRequest(BaseModel):
    account_ids: Optional[list[int]] = None
    format: str = "cpa"
    mode: str = "merged"


class OpenAIPlusImageProbeRequest(BaseModel):
    account_id: Optional[int] = None
    prompt: str = "生成一张简单的测试图片"
    model: str = "gpt-image-2"
    size: str = "1024x1024"
    path: Optional[str] = None


def _extract_proxy_key(authorization: Optional[str], x_api_key: Optional[str]) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (x_api_key or "").strip()


def _is_plus_usage_limit_response(status_code: int, data: Any) -> bool:
    if status_code != 429:
        return False
    text = str(data).lower()
    return "usage_limit_reached" in text or "usage limit" in text or "429" in text


def _is_deactivated_workspace_response(status_code: int, data: Any) -> bool:
    return status_code == 402 and "deactivated_workspace" in str(data).lower()


async def _mark_plus_account_unavailable(db: AsyncSession, account: OpenAIPlusAccount, message: str) -> None:
    account.disabled = True
    account.last_check_status = "failed"
    account.last_check_message = message[:1000]
    account.last_check_at = datetime.utcnow()
    account.updated_at = datetime.utcnow()
    await db.commit()


def _openai_plus_proxy_url() -> str:
    return str(export_config.get("openai_plus_proxy_url") or "").strip()


def _mask_proxy_url(proxy_url: str) -> str:
    if not proxy_url or "@" not in proxy_url:
        return proxy_url
    scheme, rest = proxy_url.split("://", 1) if "://" in proxy_url else ("", proxy_url)
    host = rest.rsplit("@", 1)[-1]
    return f"{scheme}://***@{host}" if scheme else f"***@{host}"


def _plus_exception_message(exc: Exception) -> str:
    parts = []
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        text = str(current).strip() or type(current).__name__
        label = f"{type(current).__name__}: {text}"
        if label not in parts:
            parts.append(label)
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    proxy_url = _openai_plus_proxy_url()
    proxy_state = f"proxy={_mask_proxy_url(proxy_url)}" if proxy_url else "proxy=disabled"
    return f"cpa_plus_connect_error: {proxy_state}; {' <- '.join(parts)}"


def _openai_plus_client_kwargs() -> dict:
    kwargs = {"timeout": httpx.Timeout(300)}
    proxy_url = _openai_plus_proxy_url()
    if proxy_url:
        kwargs["proxy"] = proxy_url
    return kwargs


def _openai_plus_cache_friendly() -> bool:
    return bool(export_config.get("openai_plus_cache_friendly", False))


def _apply_openai_plus_store_mode(body: dict) -> None:
    body["store"] = False


def _extract_plus_session_key(headers: dict, body: dict) -> Optional[str]:
    return openai_plus_service.extract_session_key(headers or {}, body)


def _apply_previous_response_id(body: dict, session_key: Optional[str], account: OpenAIPlusAccount) -> None:
    return


async def _get_proxy_account(
    db: AsyncSession,
    authorization: Optional[str],
    x_api_key: Optional[str],
    request_headers: Optional[dict] = None,
    request_body: Optional[dict] = None,
    excluded_account_ids: Optional[set[int]] = None,
) -> OpenAIPlusAccount:
    proxy_key = _extract_proxy_key(authorization, x_api_key)
    if not proxy_key:
        raise HTTPException(status_code=401, detail="缺少 Plus proxy key")
    if openai_plus_service.is_unified_proxy_key(proxy_key):
        session_key = openai_plus_service.extract_session_key(request_headers or {}, request_body)
        account = await openai_plus_service.get_next_available_account(db, session_key, excluded_account_ids)
    else:
        account = await openai_plus_service.get_account_by_proxy_key(db, proxy_key)
    if not account:
        raise HTTPException(status_code=401, detail="无可用 Plus 账号")
    account = await openai_plus_service.refresh_account_if_needed(db, account)
    if account.disabled:
        raise HTTPException(status_code=403, detail="Plus 账号已禁用")
    if account.expires_at and account.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=403, detail="Plus access token 已过期")
    return account


@router.get("/api/admin/openai-plus/accounts")
async def list_accounts(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    result = await db.execute(select(OpenAIPlusAccount).order_by(OpenAIPlusAccount.id.desc()))
    accounts = result.scalars().all()
    items = [openai_plus_service.serialize_account(item) for item in accounts]
    return {
        "items": items,
        "unified_api_key": openai_plus_service.PLUS_UNIFIED_API_KEY,
        "summary": {
            "account_count": len(accounts),
            "enabled_count": sum(1 for item in accounts if not item.disabled),
            "request_count": sum(int(item.request_count or 0) for item in accounts),
            "success_count": sum(int(item.success_count or 0) for item in accounts),
            "error_count": sum(int(item.error_count or 0) for item in accounts),
            "prompt_tokens": sum(int(item.prompt_tokens or 0) for item in accounts),
            "completion_tokens": sum(int(item.completion_tokens or 0) for item in accounts),
            "total_tokens": sum(int(item.total_tokens or 0) for item in accounts),
        },
    }


@router.post("/api/admin/openai-plus/accounts/import")
async def import_accounts(
    data: OpenAIPlusImportRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    return await openai_plus_service.import_accounts(db, data.content)


def _normalize_account_ids(account_ids: list[int]) -> list[int]:
    ids = sorted({int(item) for item in account_ids if int(item) > 0})
    if not ids:
        raise HTTPException(status_code=400, detail="请选择账号")
    if len(ids) > 500:
        raise HTTPException(status_code=400, detail="单次最多操作 500 个账号")
    return ids


@router.put("/api/admin/openai-plus/accounts/batch")
async def batch_update_accounts(
    data: OpenAIPlusBatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account_ids = _normalize_account_ids(data.account_ids)
    if data.disabled is None:
        raise HTTPException(status_code=400, detail="缺少批量修改内容")
    result = await db.execute(select(OpenAIPlusAccount).where(OpenAIPlusAccount.id.in_(account_ids)))
    accounts = result.scalars().all()
    now = datetime.utcnow()
    for account in accounts:
        account.disabled = bool(data.disabled)
        account.updated_at = now
    await db.commit()
    return {"updated": len(accounts), "requested": len(account_ids)}


@router.delete("/api/admin/openai-plus/accounts/batch")
async def batch_delete_accounts(
    data: OpenAIPlusBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account_ids = _normalize_account_ids(data.account_ids)
    result = await db.execute(select(OpenAIPlusAccount).where(OpenAIPlusAccount.id.in_(account_ids)))
    accounts = result.scalars().all()
    found_ids = [account.id for account in accounts]
    if found_ids:
        await db.execute(delete(OpenAIPlusUsageLog).where(OpenAIPlusUsageLog.account_id.in_(found_ids)))
        for account in accounts:
            await db.delete(account)
    await db.commit()
    return {"deleted": len(found_ids), "requested": len(account_ids)}


def _account_to_cpa_export(account: OpenAIPlusAccount) -> dict:
    expires_at = account.expires_at.isoformat() + "Z" if account.expires_at else None
    return {
        "type": "codex",
        "account_id": account.account_id,
        "chatgpt_account_id": account.account_id,
        "email": account.email,
        "name": account.name or account.email or account.account_id,
        "plan_type": account.plan_type,
        "chatgpt_plan_type": account.plan_type,
        "id_token": account.id_token or "",
        "access_token": account.access_token,
        "refresh_token": account.refresh_token or "",
        "session_token": "",
        "last_refresh": account.updated_at.isoformat() + "Z" if account.updated_at else None,
        "expired": expires_at,
    }


def _account_to_sub2api_export(account: OpenAIPlusAccount) -> dict:
    expires_at = account.expires_at.isoformat() + "Z" if account.expires_at else None
    email = account.email or ""
    email_key = "_".join(part for part in "".join(ch if ch.isalnum() else "_" for ch in email).lower().split("_") if part)
    expires_in = max(int((account.expires_at - datetime.utcnow()).total_seconds()), 0) if account.expires_at else 0
    return {
        "name": account.name or email or account.account_id,
        "platform": "openai",
        "type": "oauth",
        "concurrency": 10,
        "priority": 1,
        "credentials": {
            "access_token": account.access_token,
            "chatgpt_account_id": account.account_id,
            "chatgpt_user_id": account.chatgpt_user_id or "",
            "email": email,
            "expires_at": expires_at,
            "expires_in": expires_in,
            "id_token": account.id_token or "",
            "plan_type": account.plan_type or "",
        },
        "extra": {
            "email": email,
            "email_key": email_key,
            "last_refresh": account.updated_at.isoformat() + "Z" if account.updated_at else datetime.utcnow().isoformat() + "Z",
        },
    }


@router.post("/api/admin/openai-plus/accounts/export")
async def export_accounts(
    data: OpenAIPlusExportRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    query = select(OpenAIPlusAccount).order_by(OpenAIPlusAccount.id.asc())
    if data.account_ids:
        account_ids = _normalize_account_ids(data.account_ids)
        query = query.where(OpenAIPlusAccount.id.in_(account_ids))
    result = await db.execute(query)
    accounts = result.scalars().all()
    export_format = (data.format or "cpa").strip().lower()
    export_mode = (data.mode or "merged").strip().lower()
    exported_at = datetime.utcnow().isoformat() + "Z"

    if export_format == "sub2api":
        merged_payload = {
            "exported_at": exported_at,
            "proxies": [],
            "accounts": [_account_to_sub2api_export(account) for account in accounts],
        }
        single_payload = lambda account: {
            "exported_at": exported_at,
            "proxies": [],
            "accounts": [_account_to_sub2api_export(account)],
        }
        prefix = "sub2api-openai"
    elif export_format == "cpa":
        merged_payload = {
            "exported_at": exported_at,
            "accounts": [_account_to_cpa_export(account) for account in accounts],
        }
        single_payload = lambda account: _account_to_cpa_export(account)
        prefix = "openai-cpa"
    else:
        raise HTTPException(status_code=400, detail="不支持的导出格式")

    if export_mode == "merged":
        return merged_payload
    if export_mode != "separate":
        raise HTTPException(status_code=400, detail="不支持的导出方式")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for account in accounts:
            safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (account.email or account.account_id or str(account.id))).strip("_")
            filename = f"{prefix}-{safe_name or account.id}-{account.account_id or account.id}.json"
            archive.writestr(filename, json.dumps(single_payload(account), ensure_ascii=False, indent=2))
    buffer.seek(0)
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={prefix}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.zip"},
    )


async def _select_probe_account(db: AsyncSession, account_id: Optional[int]) -> OpenAIPlusAccount:
    if account_id:
        account = await db.get(OpenAIPlusAccount, account_id)
    else:
        account = await openai_plus_service.get_next_available_account(db)
    if not account:
        raise HTTPException(status_code=404, detail="Plus 账号不存在或无可用 Plus 账号")
    account = await openai_plus_service.refresh_account_if_needed(db, account)
    if account.disabled:
        raise HTTPException(status_code=403, detail="Plus 账号已禁用")
    return account


@router.post("/api/admin/openai-plus/image-probe")
async def probe_plus_native_image(
    data: OpenAIPlusImageProbeRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await _select_probe_account(db, data.account_id)
    candidate_paths = [data.path] if data.path else [
        "/codex/responses",
        "/conversation",
        "/conversation/gen_title",
        "/images/generations",
        "/gizmos/discovery",
        "/wham/images/generations",
    ]
    payloads = {
        "/codex/responses": {
            "model": data.model,
            "stream": False,
            "instructions": openai_plus_service.DEFAULT_CODEX_INSTRUCTIONS,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": data.prompt}]}],
        },
        "/conversation": {
            "action": "next",
            "messages": [{"author": {"role": "user"}, "content": {"content_type": "text", "parts": [data.prompt]}}],
            "model": data.model,
            "timezone_offset_min": -480,
        },
        "/images/generations": {"model": data.model, "prompt": data.prompt, "size": data.size, "n": 1},
        "/wham/images/generations": {"model": data.model, "prompt": data.prompt, "size": data.size, "n": 1},
    }
    results = []
    async with httpx.AsyncClient(**_openai_plus_client_kwargs()) as client:
        for path in candidate_paths:
            if not path:
                continue
            path = path if path.startswith("/") else f"/{path}"
            url = f"https://chatgpt.com/backend-api{path}"
            payload = payloads.get(path, {"model": data.model, "prompt": data.prompt, "size": data.size})
            headers = openai_plus_service.build_headers(account, stream=False)
            try:
                response = await client.post(url, headers=headers, json=payload)
                content_type = response.headers.get("content-type", "")
                text = response.text[:2000]
                parsed = None
                if "json" in content_type.lower():
                    try:
                        parsed = response.json()
                    except ValueError:
                        parsed = None
                results.append({
                    "path": path,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "json_keys": list(parsed.keys()) if isinstance(parsed, dict) else None,
                    "preview": text,
                })
            except Exception as exc:
                results.append({"path": path, "error": _plus_exception_message(exc)})
    return {
        "account_id": account.id,
        "chatgpt_account_id": account.account_id,
        "results": results,
    }


@router.put("/api/admin/openai-plus/accounts/{account_id}")
async def update_account(
    account_id: int,
    data: OpenAIPlusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(OpenAIPlusAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Plus 账号不存在")
    if data.name is not None:
        account.name = data.name.strip() or account.name
    if data.disabled is not None:
        account.disabled = bool(data.disabled)
    account.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(account)
    return openai_plus_service.serialize_account(account)


@router.delete("/api/admin/openai-plus/accounts/{account_id}")
async def delete_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(OpenAIPlusAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Plus 账号不存在")
    await db.delete(account)
    await db.commit()
    return {"message": "删除成功"}


@router.get("/api/admin/openai-plus/accounts/{account_id}/quota")
async def get_account_quota(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(OpenAIPlusAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Plus 账号不存在")
    account = await openai_plus_service.refresh_account_if_needed(db, account)
    return await openai_plus_service.fetch_account_quota(account)


@router.get("/api/admin/openai-plus/quotas")
async def list_account_quotas(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    result = await db.execute(select(OpenAIPlusAccount.id).order_by(OpenAIPlusAccount.id.desc()))
    account_ids = [int(item) for item in result.scalars().all()]
    config = normalize_openai_plus_quota_refresh_config()
    semaphore = asyncio.Semaphore(config["openai_plus_quota_refresh_concurrency"])

    async def load_quota(account_id: int):
        async with semaphore:
            try:
                async with async_session_maker() as account_db:
                    account = await account_db.get(OpenAIPlusAccount, account_id)
                    if not account:
                        return {"account_id": account_id, "available": False, "message": "account not found"}
                    if account.disabled:
                        return {"account_id": account.id, "available": False, "message": "account disabled"}
                    refreshed = await openai_plus_service.refresh_account_if_needed(
                        account_db,
                        account,
                        config["openai_plus_quota_token_refresh_timeout_seconds"],
                    )
                    quota = await openai_plus_service.fetch_account_quota(
                        refreshed,
                        config["openai_plus_quota_refresh_timeout_seconds"],
                    )
                    if quota.get("plan_type") and quota.get("plan_type") != refreshed.plan_type:
                        refreshed.plan_type = str(quota["plan_type"])
                        refreshed.updated_at = datetime.utcnow()
                        await account_db.commit()
                    quota["account_id"] = refreshed.id
                    return quota
            except Exception as exc:
                return {"account_id": account_id, "available": False, "message": str(exc)}

    quotas = await asyncio.gather(*(load_quota(account_id) for account_id in account_ids))
    return {"items": quotas}


def _is_unauthorized_check(status: str, message: str) -> bool:
    text = f"{status or ''} {message or ''}".lower()
    return "http 401" in text or "unauthorized" in text or "invalid token" in text or "invalid api key" in text


@router.post("/api/admin/openai-plus/accounts/{account_id}/check")
async def check_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(OpenAIPlusAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Plus 账号不存在")
    status, message = await openai_plus_service.check_account(account)
    if _is_unauthorized_check(status, message):
        email = account.email
        await db.execute(delete(OpenAIPlusUsageLog).where(OpenAIPlusUsageLog.account_id == account.id))
        await db.delete(account)
        await db.commit()
        return {
            "id": account_id,
            "email": email,
            "deleted": True,
            "last_check_status": status,
            "last_check_message": message,
            "message": "检测到 401，账号已删除",
        }
    account.last_check_status = status
    account.last_check_message = message
    account.last_check_at = datetime.utcnow()
    await db.commit()
    await db.refresh(account)
    return openai_plus_service.serialize_account(account)


@router.get("/api/admin/openai-plus/usage-logs")
async def list_usage_logs(
    account_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 60,
    limit: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    cutoff_time = datetime.utcnow() - timedelta(days=7)
    await db.execute(delete(OpenAIPlusUsageLog).where(OpenAIPlusUsageLog.created_at < cutoff_time))
    await db.commit()

    base_conditions = []
    if account_id:
        base_conditions.append(OpenAIPlusUsageLog.account_id == account_id)

    page = max(1, int(page or 1))
    requested_size = limit if limit is not None else page_size
    page_size = max(1, min(int(requested_size or 60), 60))
    offset = (page - 1) * page_size

    query = select(OpenAIPlusUsageLog).order_by(OpenAIPlusUsageLog.id.desc())
    count_query = select(func.count(OpenAIPlusUsageLog.id))
    if base_conditions:
        query = query.where(*base_conditions)
        count_query = count_query.where(*base_conditions)
    total = int((await db.execute(count_query)).scalar() or 0)
    result = await db.execute(query.offset(offset).limit(page_size))
    logs = result.scalars().all()
    account_ids = [item.account_id for item in logs if item.account_id]
    account_map = {}
    if account_ids:
        account_result_for_logs = await db.execute(select(OpenAIPlusAccount).where(OpenAIPlusAccount.id.in_(account_ids)))
        account_map = {account.id: account for account in account_result_for_logs.scalars().all()}
    items = []
    for item in logs:
        log_account = account_map.get(item.account_id)
        items.append({
            "id": item.id,
            "account_id": item.account_id,
            "account_email": item.account_email,
            "account_openai_id": log_account.account_id if log_account else None,
            "model": item.model,
            "endpoint": item.endpoint,
            "stream": bool(item.stream),
            "success": bool(item.success),
            "status_code": item.status_code,
            "prompt_tokens": int(item.prompt_tokens or 0),
            "cache_tokens": int(getattr(item, "cache_tokens", 0) or 0),
            "completion_tokens": int(item.completion_tokens or 0),
            "total_tokens": int(item.total_tokens or 0),
            "latency_ms": int(getattr(item, "latency_ms", 0) or 0),
            "error_message": item.error_message,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    summary_query = select(
        func.count(OpenAIPlusUsageLog.id),
        func.sum(OpenAIPlusUsageLog.success.cast(Integer)),
        func.sum(OpenAIPlusUsageLog.prompt_tokens),
        func.sum(OpenAIPlusUsageLog.cache_tokens),
        func.sum(OpenAIPlusUsageLog.completion_tokens),
        func.sum(OpenAIPlusUsageLog.total_tokens),
        func.avg(OpenAIPlusUsageLog.latency_ms),
    )
    if base_conditions:
        summary_query = summary_query.where(*base_conditions)
    summary_row = (await db.execute(summary_query)).one()

    account_query = select(OpenAIPlusAccount).order_by(OpenAIPlusAccount.id.asc())
    if account_id:
        account_query = account_query.where(OpenAIPlusAccount.id == account_id)
    account_result = await db.execute(account_query)
    account_summaries = [openai_plus_service.serialize_account(account) for account in account_result.scalars().all()]

    request_count = int(summary_row[0] or 0)
    success_count = int(summary_row[1] or 0)
    return {
        "items": items,
        "summary": {
            "request_count": request_count,
            "success_count": success_count,
            "error_count": max(request_count - success_count, 0),
            "prompt_tokens": int(summary_row[2] or 0),
            "cache_tokens": int(summary_row[3] or 0),
            "completion_tokens": int(summary_row[4] or 0),
            "total_tokens": int(summary_row[5] or 0),
            "avg_latency_ms": int(summary_row[6] or 0),
        },
        "account_summaries": account_summaries,
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


def plus_models_payload() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": "gpt-5.5", "object": "model", "created": 1776873600, "owned_by": "openai"},
            {"id": "gpt-5.4", "object": "model", "created": 1738368000, "owned_by": "openai"},
            {"id": "gpt-5.3-codex", "object": "model", "created": 1735689600, "owned_by": "openai"},
        ],
    }


def _estimate_text_tokens(text: str) -> int:
    text = text or ""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, (ascii_chars + 3) // 4 + non_ascii_chars)


def _estimate_claude_count_tokens(body: dict) -> int:
    total = 0
    total += _estimate_text_tokens(openai_plus_service.claude_content_to_text(body.get("system")))
    for message in body.get("messages") or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            total += _estimate_text_tokens(content)
            continue
        for item in content or []:
            if isinstance(item, str):
                total += _estimate_text_tokens(item)
            elif isinstance(item, dict):
                if item.get("type") == "text":
                    total += _estimate_text_tokens(str(item.get("text") or ""))
                elif item.get("type") == "tool_result":
                    total += _estimate_text_tokens(openai_plus_service.claude_content_to_text(item.get("content")))
                elif item.get("type") == "image":
                    total += 1200
    for tool in body.get("tools") or []:
        if isinstance(tool, dict):
            total += _estimate_text_tokens(json.dumps(tool, ensure_ascii=False))
    return max(total, 1)


async def plus_count_tokens_handler(request: Request):
    body = await request.json()
    return {"input_tokens": _estimate_claude_count_tokens(body if isinstance(body, dict) else {})}


@router.get("/plus/v1/models")
async def plus_models(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _get_proxy_account(db, authorization, x_api_key, dict(request.headers), None)
    return plus_models_payload()


@router.post("/plus/v1/models")
async def plus_models_post(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _get_proxy_account(db, authorization, x_api_key, dict(request.headers), None)
    return plus_models_payload()


async def _forward_plus_response(account: OpenAIPlusAccount, body: dict, stream: bool) -> tuple[int, dict, Any]:
    url = f"{openai_plus_service.CODEX_BASE_URL}/responses"
    headers = openai_plus_service.build_headers(account, stream=stream)
    if stream:
        client = httpx.AsyncClient(**_openai_plus_client_kwargs())
        response = None
        try:
            request = client.build_request("POST", url, headers=headers, json=body)
            response = await client.send(request, stream=True)
            response_headers = {"content-type": response.headers.get("content-type", "text/event-stream")}

            async def generator():
                try:
                    async for chunk in response.aiter_bytes():
                        yield chunk
                finally:
                    await response.aclose()
                    await client.aclose()

            return response.status_code, response_headers, generator()
        except Exception:
            if response is not None:
                await response.aclose()
            await client.aclose()
            raise
    async with httpx.AsyncClient(**_openai_plus_client_kwargs()) as client:
        response = await client.post(url, headers=headers, json=body)
        try:
            data = response.json()
        except ValueError:
            data = {"error": {"message": response.text}}
        return response.status_code, {}, data


@router.post("/plus/v1/responses")
async def plus_responses(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    body = dict(body)
    body["stream"] = True
    _apply_openai_plus_store_mode(body)
    stream = True
    if "instructions" not in body or not body.get("instructions"):
        body["instructions"] = openai_plus_service.DEFAULT_CODEX_INSTRUCTIONS
    request_headers = dict(request.headers)
    session_key = _extract_plus_session_key(request_headers, body)
    client_previous_response_id = body.get("previous_response_id")
    proxy_key = _extract_proxy_key(authorization, x_api_key)
    can_retry_account = openai_plus_service.is_unified_proxy_key(proxy_key)
    excluded_account_ids: set[int] = set()
    last_error_message = None
    for _ in range(5):
        account = await _get_proxy_account(db, authorization, x_api_key, request_headers, body, excluded_account_ids)
        if not client_previous_response_id:
            body.pop("previous_response_id", None)
        _apply_previous_response_id(body, session_key, account)
        try:
            status_code, headers, data = await _forward_plus_response(account, body, stream)
        except httpx.HTTPError as exc:
            last_error_message = _plus_exception_message(exc)
            usage = openai_plus_service.extract_usage_from_responses_payload({})
            await openai_plus_service.add_account_usage(db, account, usage, False)
            await openai_plus_service.add_usage_log_by_id(account.id, body.get("model"), "responses", True, 502, usage, False, last_error_message)
            if can_retry_account:
                excluded_account_ids.add(account.id)
                continue
            return JSONResponse(content={"error": {"message": last_error_message, "type": "upstream_connect_error"}}, status_code=502)
        if can_retry_account and status_code in {402, 429}:
            error_data = await openai_plus_service.collect_responses_stream(data)
            error_message = str(error_data.get("error") or error_data)[:1000]
            usage = openai_plus_service.extract_usage_from_responses_payload(error_data)
            await openai_plus_service.add_account_usage(db, account, usage, False)
            await openai_plus_service.add_usage_log_by_id(account.id, body.get("model"), "responses", True, status_code, usage, False, error_message)
            if status_code == 429:
                openai_plus_service.set_account_cooldown(account.id, 300)
            elif _is_deactivated_workspace_response(status_code, error_data):
                await _mark_plus_account_unavailable(db, account, error_message)
            excluded_account_ids.add(account.id)
            continue
        tracked_stream = openai_plus_service.tracked_responses_stream(data, account.id, status_code < 400, body.get("model"), "responses", status_code, session_key)
        return StreamingResponse(tracked_stream, status_code=status_code, media_type=headers.get("content-type", "text/event-stream"))
    if last_error_message:
        raise HTTPException(status_code=502, detail=last_error_message)
    raise HTTPException(status_code=429, detail="所有 Plus 账号均达到用量限制")


@router.post("/plus/v1/images/generations")
async def plus_image_generations(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    account = await _get_proxy_account(db, authorization, x_api_key, dict(request.headers), body)
    return JSONResponse(
        content={
            "error": {
                "message": "Plus native image upstream is not connected yet. This endpoint selected a Plus account but did not fall back to CPA image key pool.",
                "type": "plus_native_image_upstream_not_configured",
                "account_id": account.id,
                "chatgpt_account_id": account.account_id,
            }
        },
        status_code=501,
    )


@router.post("/plus/v1/chat/completions")
async def plus_chat_completions(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    request_headers = dict(request.headers)
    session_key = _extract_plus_session_key(request_headers, body)
    account = await _get_proxy_account(db, authorization, x_api_key, request_headers, body)
    messages = body.get("messages") or []
    input_items = openai_plus_service.chat_messages_to_responses_input(messages)
    responses_body = {
        "model": body.get("model") or "gpt-5.5",
        "stream": True,
        "instructions": body.get("instructions") or openai_plus_service.DEFAULT_CODEX_INSTRUCTIONS,
        "input": input_items,
    }
    if "store" in body:
        responses_body["store"] = body.get("store")
    if body.get("previous_response_id"):
        responses_body["previous_response_id"] = body.get("previous_response_id")
    _apply_openai_plus_store_mode(responses_body)
    _apply_previous_response_id(responses_body, session_key, account)
    status_code, headers, data = await _forward_plus_response(account, responses_body, True)
    if body.get("stream", False):
        converted_stream = openai_plus_service.responses_stream_to_chat_stream(data, responses_body["model"], db, account, status_code < 400, session_key)
        return StreamingResponse(converted_stream, status_code=status_code, media_type="text/event-stream")
    response_data = await openai_plus_service.collect_responses_stream(data)
    response_id = openai_plus_service.extract_response_id(response_data)
    if status_code < 400 and response_id:
        openai_plus_service.set_previous_response_id(session_key, account.id, response_id)
    usage = openai_plus_service.extract_usage_from_responses_payload(response_data)
    await openai_plus_service.add_account_usage(db, account, usage, status_code < 400)
    await openai_plus_service.add_usage_log_by_id(account.id, responses_body["model"], "chat.completions", False, status_code, usage, status_code < 400)
    chat_data = openai_plus_service.responses_to_chat_completion(response_data, responses_body["model"]) if status_code < 400 else response_data
    return JSONResponse(content=chat_data, status_code=status_code)


async def plus_messages_handler(
    request: Request,
    authorization: Optional[str],
    x_api_key: Optional[str],
    db: AsyncSession,
):
    body = await request.json()
    request_headers = dict(request.headers)
    session_key = _extract_plus_session_key(request_headers, body)
    client_previous_response_id = body.get("previous_response_id")
    model = body.get("model") or "gpt-5.5"
    system_text = openai_plus_service.claude_content_to_text(body.get("system"))
    responses_body = {
        "model": model,
        "stream": True,
        "instructions": system_text or openai_plus_service.DEFAULT_CODEX_INSTRUCTIONS,
        "input": openai_plus_service.claude_messages_to_responses_input(body.get("messages") or []),
    }
    if "store" in body:
        responses_body["store"] = body.get("store")
    if body.get("previous_response_id"):
        responses_body["previous_response_id"] = body.get("previous_response_id")
    _apply_openai_plus_store_mode(responses_body)
    tools = openai_plus_service.claude_tools_to_responses_tools(body.get("tools"))
    if tools:
        responses_body["tools"] = tools
    if body.get("tool_choice"):
        responses_body["tool_choice"] = "auto"
    proxy_key = _extract_proxy_key(authorization, x_api_key)
    can_retry_account = openai_plus_service.is_unified_proxy_key(proxy_key)
    excluded_account_ids: set[int] = set()
    last_error_message = None
    for _ in range(5):
        account = await _get_proxy_account(db, authorization, x_api_key, request_headers, body, excluded_account_ids)
        if not client_previous_response_id:
            responses_body.pop("previous_response_id", None)
        _apply_previous_response_id(responses_body, session_key, account)
        try:
            status_code, headers, data = await _forward_plus_response(account, responses_body, True)
        except httpx.HTTPError as exc:
            last_error_message = _plus_exception_message(exc)
            usage = openai_plus_service.extract_usage_from_responses_payload({})
            await openai_plus_service.add_account_usage(db, account, usage, False)
            await openai_plus_service.add_usage_log_by_id(account.id, model, "messages", True, 502, usage, False, last_error_message)
            if can_retry_account:
                excluded_account_ids.add(account.id)
                continue
            return JSONResponse(content={"error": {"message": last_error_message, "type": "upstream_connect_error"}}, status_code=502)
        if can_retry_account and status_code in {402, 429}:
            error_data = await openai_plus_service.collect_responses_stream(data)
            error_message = str(error_data.get("error") or error_data)[:1000]
            usage = openai_plus_service.extract_usage_from_responses_payload(error_data)
            await openai_plus_service.add_account_usage(db, account, usage, False)
            await openai_plus_service.add_usage_log_by_id(account.id, model, "messages", True, status_code, usage, False, error_message)
            if status_code == 429:
                openai_plus_service.set_account_cooldown(account.id, 300)
            elif _is_deactivated_workspace_response(status_code, error_data):
                await _mark_plus_account_unavailable(db, account, error_message)
            excluded_account_ids.add(account.id)
            continue
        if body.get("stream", False):
            converted_stream = openai_plus_service.responses_stream_to_claude_stream(data, model, account.id, status_code < 400, status_code, session_key)
            return StreamingResponse(converted_stream, status_code=200, media_type="text/event-stream")
        response_data = await openai_plus_service.collect_responses_stream(data)
        response_id = openai_plus_service.extract_response_id(response_data)
        if status_code < 400 and response_id:
            openai_plus_service.set_previous_response_id(session_key, account.id, response_id)
        usage = openai_plus_service.extract_usage_from_responses_payload(response_data)
        await openai_plus_service.add_account_usage(db, account, usage, status_code < 400)
        await openai_plus_service.add_usage_log_by_id(account.id, model, "messages", False, status_code, usage, status_code < 400)
        claude_data = openai_plus_service.responses_to_claude_message(response_data, model) if status_code < 400 else response_data
        return JSONResponse(content=claude_data, status_code=status_code)
    if last_error_message:
        raise HTTPException(status_code=502, detail=last_error_message)
    raise HTTPException(status_code=429, detail="所有 Plus 账号均达到用量限制")


@router.post("/plus/v1")
async def plus_messages_v1_root(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await plus_messages_handler(request, authorization, x_api_key, db)


@router.post("/plus/v1/messages")
async def plus_messages_v1(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await plus_messages_handler(request, authorization, x_api_key, db)


@router.post("/plus/v1/messages/messages")
async def plus_messages_v1_double_messages(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await plus_messages_handler(request, authorization, x_api_key, db)


@router.post("/plus/v1/v1/messages")
async def plus_messages_double_v1(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await plus_messages_handler(request, authorization, x_api_key, db)


@router.post("/plus/v1/messages/count_tokens")
async def plus_messages_count_tokens(request: Request):
    return await plus_count_tokens_handler(request)


@router.post("/plus/v1/v1/messages/count_tokens")
async def plus_messages_double_v1_count_tokens(request: Request):
    return await plus_count_tokens_handler(request)


@router.post("/plus/messages/count_tokens")
async def plus_messages_no_v1_count_tokens(request: Request):
    return await plus_count_tokens_handler(request)


@router.post("/plus/v1/v1/messages/messages")
async def plus_messages_double_v1_double_messages(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await plus_messages_handler(request, authorization, x_api_key, db)


@router.post("/plus/messages")
async def plus_messages_no_v1(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    return await plus_messages_handler(request, authorization, x_api_key, db)
