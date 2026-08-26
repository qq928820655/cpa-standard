"""
Grok / xAI account pool routes
"""
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import GrokAccount, GrokUsageLog
from routers.admin import verify_admin_key
from services.grok_account_service import grok_account_service, GROK_UNIFIED_API_KEY

admin_router = APIRouter()
proxy_router = APIRouter()


class GrokAccountCreate(BaseModel):
    name: Optional[str] = None
    account_type: str = "oauth"
    session_content: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None


class GrokUsageLogResponse(BaseModel):
    id: int
    account_id: Optional[int]
    account_email: Optional[str]
    account_type: Optional[str]
    model: Optional[str]
    endpoint: Optional[str]
    stream: bool
    success: bool
    status_code: Optional[int]
    prompt_tokens: int
    cache_tokens: int
    completion_tokens: int
    total_tokens: int
    latency_ms: int
    error_message: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class GrokUsageLogListResponse(BaseModel):
    items: List[GrokUsageLogResponse]
    total: int


class GrokAccountResponse(BaseModel):
    id: int
    name: Optional[str]
    email: Optional[str]
    account_type: str
    base_url: Optional[str]
    disabled: bool
    subscription_tier: Optional[str]
    entitlement_status: Optional[str]
    expires_at: Optional[datetime]
    last_check_status: Optional[str]
    last_check_message: Optional[str]
    last_check_at: Optional[datetime]
    request_count: int
    success_count: int
    error_count: int
    prompt_tokens: int
    cache_tokens: int
    completion_tokens: int
    total_tokens: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GrokAccountListResponse(BaseModel):
    items: List[GrokAccountResponse]
    unified_api_key: str


class GrokAccountStatusUpdate(BaseModel):
    disabled: bool


class GrokAccountBatchDeleteRequest(BaseModel):
    account_ids: List[int]


class GrokAccountCheckRequest(BaseModel):
    model: str = "grok-4.5"


class GrokAccountCheckResponse(BaseModel):
    status: str
    message: str


class GrokOAuthAuthUrlRequest(BaseModel):
    redirect_uri: Optional[str] = None


class GrokOAuthExchangeCodeRequest(BaseModel):
    code: str
    state: Optional[str] = None
    redirect_uri: Optional[str] = None
    code_verifier: Optional[str] = None
    name: Optional[str] = None


@admin_router.post("/oauth/auth-url")
async def create_grok_oauth_auth_url(
    data: GrokOAuthAuthUrlRequest,
    _: bool = Depends(verify_admin_key),
):
    return grok_account_service.create_oauth_auth_url(redirect_uri=data.redirect_uri)


@admin_router.post("/oauth/exchange-code", response_model=GrokAccountResponse)
async def exchange_grok_oauth_code(
    data: GrokOAuthExchangeCodeRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    try:
        token_data = await grok_account_service.exchange_oauth_code(
            data.code,
            state=data.state,
            redirect_uri=data.redirect_uri,
            code_verifier=data.code_verifier,
        )
        payload = grok_account_service.build_account_payload(
            name=data.name,
            account_type="oauth",
            session_content=json_dumps(token_data),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await grok_account_service.create_account(db, payload)


def json_dumps(data) -> str:
    import json
    return json.dumps(data, ensure_ascii=False)


@admin_router.get("/usage-logs", response_model=GrokUsageLogListResponse)
async def list_grok_usage_logs(
    account_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    from sqlalchemy import func
    page = max(int(page or 1), 1)
    page_size = min(max(int(page_size or 50), 1), 200)
    query = select(GrokUsageLog)
    count_query = select(func.count()).select_from(GrokUsageLog)
    if account_id:
        query = query.where(GrokUsageLog.account_id == account_id)
        count_query = count_query.where(GrokUsageLog.account_id == account_id)
    total = int((await db.execute(count_query)).scalar() or 0)
    result = await db.execute(query.order_by(GrokUsageLog.id.desc()).offset((page - 1) * page_size).limit(page_size))
    return GrokUsageLogListResponse(items=list(result.scalars().all()), total=total)


@admin_router.get("/accounts", response_model=GrokAccountListResponse)
async def list_grok_accounts(
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    result = await db.execute(select(GrokAccount).order_by(GrokAccount.id.desc()))
    return GrokAccountListResponse(items=list(result.scalars().all()), unified_api_key=GROK_UNIFIED_API_KEY)


@admin_router.post("/accounts", response_model=GrokAccountResponse)
async def create_grok_account(
    data: GrokAccountCreate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    try:
        payload = grok_account_service.build_account_payload(
            name=data.name,
            account_type=data.account_type,
            session_content=data.session_content,
            api_key=data.api_key,
            base_url=data.base_url,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return await grok_account_service.create_account(db, payload)


@admin_router.delete("/accounts/batch")
async def batch_delete_grok_accounts(
    data: GrokAccountBatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account_ids = list(dict.fromkeys(int(item) for item in data.account_ids if int(item) > 0))
    if not account_ids:
        raise HTTPException(status_code=400, detail="请选择要删除的 Grok 账号")
    result = await db.execute(select(GrokAccount).where(GrokAccount.id.in_(account_ids)))
    accounts = list(result.scalars().all())
    for account in accounts:
        await db.delete(account)
    await db.commit()
    return {"message": "已批量删除", "deleted": len(accounts)}


@admin_router.put("/accounts/{account_id}/status", response_model=GrokAccountResponse)
async def update_grok_account_status(
    account_id: int,
    data: GrokAccountStatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(GrokAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Grok 账号不存在")
    account.disabled = bool(data.disabled)
    account.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(account)
    return account


@admin_router.post("/accounts/{account_id}/check", response_model=GrokAccountCheckResponse)
async def check_grok_account(
    account_id: int,
    data: GrokAccountCheckRequest,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(GrokAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Grok 账号不存在")
    try:
        account = await grok_account_service.refresh_account_if_needed(db, account)
    except ValueError as exc:
        account.last_check_status = "error"
        account.last_check_message = str(exc)[:1000]
        account.last_check_at = datetime.utcnow()
        account.updated_at = datetime.utcnow()
        await db.commit()
        return GrokAccountCheckResponse(status="error", message=str(exc))
    status, message = await grok_account_service.check_account(account, data.model)
    account.last_check_status = status
    account.last_check_message = message
    account.last_check_at = datetime.utcnow()
    account.updated_at = datetime.utcnow()
    await db.commit()
    return GrokAccountCheckResponse(status=status, message=message)




@admin_router.post("/accounts/{account_id}/refresh", response_model=GrokAccountResponse)
async def refresh_grok_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(GrokAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Grok 账号不存在")
    try:
        account = await grok_account_service.refresh_account_if_needed(db, account, force=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return account


@admin_router.delete("/accounts/{account_id}")
async def delete_grok_account(
    account_id: int,
    db: AsyncSession = Depends(get_db),
    _: bool = Depends(verify_admin_key),
):
    account = await db.get(GrokAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Grok 账号不存在")
    await db.delete(account)
    await db.commit()
    return {"message": "已删除"}


def _extract_proxy_key(authorization: Optional[str], x_api_key: Optional[str]) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return (x_api_key or "").strip()


async def _get_proxy_account(
    db: AsyncSession,
    authorization: Optional[str],
    x_api_key: Optional[str],
    excluded_ids: Optional[set[int]] = None,
) -> GrokAccount:
    proxy_key = _extract_proxy_key(authorization, x_api_key)
    if not proxy_key:
        raise HTTPException(status_code=401, detail="缺少 Grok proxy key")
    if grok_account_service.is_unified_proxy_key(proxy_key):
        account = await grok_account_service.get_next_available_account(db, excluded_ids)
    else:
        account = await grok_account_service.get_account_by_proxy_key(db, proxy_key)
    if not account:
        raise HTTPException(status_code=401, detail="无可用 Grok 账号")
    if account.disabled:
        raise HTTPException(status_code=403, detail="Grok 账号已禁用")
    try:
        return await grok_account_service.refresh_account_if_needed(db, account)
    except ValueError as exc:
        account.last_check_status = "error"
        account.last_check_message = str(exc)[:1000]
        account.last_check_at = datetime.utcnow()
        account.updated_at = datetime.utcnow()
        await db.commit()
        raise HTTPException(status_code=403, detail=str(exc))


async def _forward_with_account_retry(
    db: AsyncSession,
    authorization: Optional[str],
    x_api_key: Optional[str],
    body: dict,
    stream: bool,
    extra_headers: Optional[dict] = None,
):
    proxy_key = _extract_proxy_key(authorization, x_api_key)
    can_retry = grok_account_service.is_unified_proxy_key(proxy_key)
    excluded_ids: set[int] = set()
    last_error = None
    for _ in range(5):
        account = await _get_proxy_account(db, authorization, x_api_key, excluded_ids)
        try:
            status_code, headers, data = await grok_account_service.forward_responses(
                account,
                body,
                stream=stream,
                extra_headers=extra_headers,
            )
        except httpx.HTTPError as exc:
            last_error = str(exc)
            await grok_account_service.add_account_usage(db, account, {}, False)
            if can_retry:
                excluded_ids.add(account.id)
                continue
            raise HTTPException(status_code=502, detail=last_error)
        if can_retry and status_code in {401, 403}:
            account.disabled = True
            account.last_check_status = "error"
            account.last_check_message = f"HTTP {status_code}"
            account.updated_at = datetime.utcnow()
            await grok_account_service.add_account_usage(db, account, {}, False)
            excluded_ids.add(account.id)
            continue
        if can_retry and status_code == 429:
            grok_account_service.set_account_cooldown(account.id, 120)
            await grok_account_service.add_account_usage(db, account, {}, False)
            excluded_ids.add(account.id)
            continue
        return account, status_code, headers, data
    if last_error:
        raise HTTPException(status_code=502, detail=last_error)
    raise HTTPException(status_code=429, detail="所有 Grok 账号均不可用")


@proxy_router.get("/v1/models")
async def grok_models():
    return {
        "object": "list",
        "data": [
            {"id": "grok-4.5", "object": "model", "owned_by": "grok"},
            {"id": "grok-4.3", "object": "model", "owned_by": "grok"},
            {"id": "grok-build-0.1", "object": "model", "owned_by": "grok"},
        ],
    }


@proxy_router.post("/responses")
@proxy_router.post("/v1/responses")
@proxy_router.post("/backend-api/codex/responses")
async def grok_responses(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    body = dict(await request.json() or {})
    cache_headers, body = grok_account_service.extract_cache_affinity(dict(request.headers), body)
    stream = bool(body.get("stream", False))
    account, status_code, headers, data = await _forward_with_account_retry(
        db, authorization, x_api_key, body, stream, extra_headers=cache_headers
    )
    if stream:
        tracked = grok_account_service.tracked_responses_stream(data, body.get("model"), "responses", db, account, status_code < 400, status_code)
        return StreamingResponse(tracked, status_code=status_code, media_type=headers.get("content-type", "text/event-stream"))
    from services import openai_plus_service
    usage = openai_plus_service.extract_usage_from_responses_payload(data)
    await grok_account_service.add_account_usage(db, account, usage, status_code < 400)
    await grok_account_service.add_usage_log(db, account, usage, model=body.get("model"), endpoint="responses", stream=False, status_code=status_code, success=status_code < 400, error_message=None if status_code < 400 else str(data)[:1000])
    return JSONResponse(content=data, status_code=status_code)


@proxy_router.post("/v1/chat/completions")
@proxy_router.post("/chat/completions")
async def grok_chat_completions(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    body = dict(await request.json() or {})
    cache_headers, _ = grok_account_service.extract_cache_affinity(dict(request.headers), body)
    from services import openai_plus_service
    responses_body = {
        "model": body.get("model") or "grok-4.5",
        "stream": bool(body.get("stream", False)),
        "input": openai_plus_service.chat_messages_to_responses_input(body.get("messages") or []),
    }
    if body.get("instructions"):
        responses_body["instructions"] = body.get("instructions")
    if body.get("tools"):
        responses_body["tools"] = body.get("tools")
    if body.get("tool_choice"):
        responses_body["tool_choice"] = body.get("tool_choice")
    # Chat 转 Responses 时同步 prompt_cache_key，保证独立 Grok 池也能走缓存亲和
    if body.get("prompt_cache_key"):
        responses_body["prompt_cache_key"] = body.get("prompt_cache_key")
    elif cache_headers.get("x-grok-conv-id"):
        responses_body["prompt_cache_key"] = cache_headers["x-grok-conv-id"]
    account, status_code, headers, data = await _forward_with_account_retry(
        db, authorization, x_api_key, responses_body, bool(responses_body["stream"]), extra_headers=cache_headers
    )
    if responses_body["stream"]:
        converted = grok_account_service.responses_stream_to_chat_stream(data, responses_body["model"], db, account, status_code < 400, status_code)
        return StreamingResponse(converted, status_code=status_code, media_type="text/event-stream")
    usage = openai_plus_service.extract_usage_from_responses_payload(data)
    await grok_account_service.add_account_usage(db, account, usage, status_code < 400)
    await grok_account_service.add_usage_log(db, account, usage, model=responses_body["model"], endpoint="chat.completions", stream=False, status_code=status_code, success=status_code < 400, error_message=None if status_code < 400 else str(data)[:1000])
    payload = openai_plus_service.responses_to_chat_completion(data, responses_body["model"]) if status_code < 400 else data
    return JSONResponse(content=payload, status_code=status_code)


@proxy_router.post("/v1/messages")
async def grok_messages(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    body = dict(await request.json() or {})
    cache_headers, _ = grok_account_service.extract_cache_affinity(dict(request.headers), body)
    from services import openai_plus_service
    system_text = openai_plus_service.claude_content_to_text(body.get("system"))
    responses_body = {
        "model": body.get("model") or "grok-4.5",
        "stream": bool(body.get("stream", False)),
        "instructions": system_text,
        "input": openai_plus_service.claude_messages_to_responses_input(body.get("messages") or []),
    }
    tools = openai_plus_service.claude_tools_to_responses_tools(body.get("tools"))
    if tools:
        responses_body["tools"] = tools
    if body.get("tool_choice"):
        responses_body["tool_choice"] = "auto"
    if body.get("prompt_cache_key"):
        responses_body["prompt_cache_key"] = body.get("prompt_cache_key")
    elif cache_headers.get("x-grok-conv-id"):
        responses_body["prompt_cache_key"] = cache_headers["x-grok-conv-id"]
    account, status_code, headers, data = await _forward_with_account_retry(
        db, authorization, x_api_key, responses_body, bool(responses_body["stream"]), extra_headers=cache_headers
    )
    if responses_body["stream"]:
        converted = grok_account_service.responses_stream_to_claude_stream(data, responses_body["model"], db, account, status_code < 400, status_code)
        return StreamingResponse(converted, status_code=status_code, media_type="text/event-stream")
    usage = openai_plus_service.extract_usage_from_responses_payload(data)
    await grok_account_service.add_account_usage(db, account, usage, status_code < 400)
    await grok_account_service.add_usage_log(db, account, usage, model=responses_body["model"], endpoint="messages", stream=False, status_code=status_code, success=status_code < 400, error_message=None if status_code < 400 else str(data)[:1000])
    payload = openai_plus_service.responses_to_claude_message(data, responses_body["model"]) if status_code < 400 else data
    return JSONResponse(content=payload, status_code=status_code)
