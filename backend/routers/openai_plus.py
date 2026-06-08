"""
OpenAI Plus account management and proxy routes
"""
import asyncio
from datetime import datetime
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker, get_db
from models import OpenAIPlusAccount, OpenAIPlusUsageLog
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


def _extract_proxy_key(authorization: Optional[str], x_api_key: Optional[str]) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (x_api_key or "").strip()


async def _get_proxy_account(
    db: AsyncSession,
    authorization: Optional[str],
    x_api_key: Optional[str],
    request_headers: Optional[dict] = None,
    request_body: Optional[dict] = None,
) -> OpenAIPlusAccount:
    proxy_key = _extract_proxy_key(authorization, x_api_key)
    if not proxy_key:
        raise HTTPException(status_code=401, detail="缺少 Plus proxy key")
    if openai_plus_service.is_unified_proxy_key(proxy_key):
        session_key = openai_plus_service.extract_session_key(request_headers or {}, request_body)
        account = await openai_plus_service.get_next_available_account(db, session_key)
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
    account.last_check_status = status
    account.last_check_message = message
    account.last_check_at = datetime.utcnow()
    await db.commit()
    await db.refresh(account)
    return openai_plus_service.serialize_account(account)


@router.get("/api/admin/openai-plus/usage-logs")
async def list_usage_logs(
    account_id: Optional[int] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    query = select(OpenAIPlusUsageLog).order_by(OpenAIPlusUsageLog.id.desc())
    if account_id:
        query = query.where(OpenAIPlusUsageLog.account_id == account_id)
    result = await db.execute(query.limit(max(1, min(limit, 500))))
    items = []
    for item in result.scalars().all():
        items.append({
            "id": item.id,
            "account_id": item.account_id,
            "account_email": item.account_email,
            "model": item.model,
            "endpoint": item.endpoint,
            "stream": bool(item.stream),
            "success": bool(item.success),
            "status_code": item.status_code,
            "prompt_tokens": int(item.prompt_tokens or 0),
            "completion_tokens": int(item.completion_tokens or 0),
            "total_tokens": int(item.total_tokens or 0),
            "error_message": item.error_message,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })
    return {"items": items}


@router.get("/plus/v1/models")
async def plus_models(
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    await _get_proxy_account(db, authorization, x_api_key, dict(request.headers), None)
    return {
        "object": "list",
        "data": [
            {"id": "gpt-5.5", "object": "model", "created": 1776873600, "owned_by": "openai"},
            {"id": "gpt-5.4", "object": "model", "created": 1738368000, "owned_by": "openai"},
            {"id": "gpt-5.3-codex", "object": "model", "created": 1735689600, "owned_by": "openai"},
        ],
    }


async def _forward_plus_response(account: OpenAIPlusAccount, body: dict, stream: bool) -> tuple[int, dict, Any]:
    url = f"{openai_plus_service.CODEX_BASE_URL}/responses"
    headers = openai_plus_service.build_headers(account, stream=stream)
    async with httpx.AsyncClient(timeout=httpx.Timeout(300)) as client:
        if stream:
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
    account = await _get_proxy_account(db, authorization, x_api_key, dict(request.headers))
    body = await request.json()
    body = dict(body)
    body["stream"] = True
    body["store"] = False
    stream = True
    if "instructions" not in body or not body.get("instructions"):
        body["instructions"] = openai_plus_service.DEFAULT_CODEX_INSTRUCTIONS
    status_code, headers, data = await _forward_plus_response(account, body, stream)
    tracked_stream = openai_plus_service.tracked_responses_stream(data, account.id, status_code < 400, body.get("model"), "responses", status_code)
    return StreamingResponse(tracked_stream, status_code=status_code, media_type=headers.get("content-type", "text/event-stream"))


@router.post("/plus/v1/chat/completions")
async def plus_chat_completions(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    account = await _get_proxy_account(db, authorization, x_api_key, dict(request.headers))
    body = await request.json()
    messages = body.get("messages") or []
    input_items = openai_plus_service.chat_messages_to_responses_input(messages)
    responses_body = {
        "model": body.get("model") or "gpt-5.5",
        "stream": True,
        "store": False,
        "instructions": body.get("instructions") or openai_plus_service.DEFAULT_CODEX_INSTRUCTIONS,
        "input": input_items,
    }
    status_code, headers, data = await _forward_plus_response(account, responses_body, True)
    if body.get("stream", False):
        converted_stream = openai_plus_service.responses_stream_to_chat_stream(data, responses_body["model"], db, account, status_code < 400)
        return StreamingResponse(converted_stream, status_code=status_code, media_type="text/event-stream")
    response_data = await openai_plus_service.collect_responses_stream(data)
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
    account = await _get_proxy_account(db, authorization, x_api_key, dict(request.headers))
    body = await request.json()
    model = body.get("model") or "gpt-5.5"
    system_text = openai_plus_service.claude_content_to_text(body.get("system"))
    responses_body = {
        "model": model,
        "stream": True,
        "store": False,
        "instructions": system_text or openai_plus_service.DEFAULT_CODEX_INSTRUCTIONS,
        "input": openai_plus_service.claude_messages_to_responses_input(body.get("messages") or []),
    }
    status_code, headers, data = await _forward_plus_response(account, responses_body, True)
    if body.get("stream", False):
        converted_stream = openai_plus_service.responses_stream_to_claude_stream(data, model, account.id, status_code < 400, status_code)
        return StreamingResponse(converted_stream, status_code=status_code, media_type="text/event-stream")
    response_data = await openai_plus_service.collect_responses_stream(data)
    usage = openai_plus_service.extract_usage_from_responses_payload(response_data)
    await openai_plus_service.add_account_usage(db, account, usage, status_code < 400)
    await openai_plus_service.add_usage_log_by_id(account.id, model, "messages", False, status_code, usage, status_code < 400)
    claude_data = openai_plus_service.responses_to_claude_message(response_data, model) if status_code < 400 else response_data
    return JSONResponse(content=claude_data, status_code=status_code)


@router.post("/plus/v1/messages")
async def plus_messages_v1(
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
