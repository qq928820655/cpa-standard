"""
代理转发路由 - 兼容 OpenAI 和 Claude 接口
"""
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from services.pool_manager import pool_manager
from services.proxy_service import proxy_service


router = APIRouter()
STREAM_RETRY_LIMIT = 3
REQUEST_RETRY_LIMIT = 3
SESSION_KEY_HEADER = "x-cpa-session-key"


def log_proxy_hit(path: str, body: dict):
    model = body.get("model") if isinstance(body, dict) else None
    stream = body.get("stream") if isinstance(body, dict) else None
    print(f"[CPA HIT] path={path} model={model} stream={stream}")


def should_cooldown_key(status_code: int) -> bool:
    return status_code in {401, 403, 429} or status_code >= 500


def get_sticky_session_key(headers: dict) -> Optional[str]:
    if not settings.proxy_session_sticky_enabled:
        return None
    return headers.get(SESSION_KEY_HEADER)


async def select_api_key(
    db: AsyncSession,
    *,
    model: Optional[str],
    sticky_session_key: Optional[str],
    tried_key_ids: list[int],
):
    sticky_ttl_seconds = settings.proxy_session_sticky_ttl_seconds if sticky_session_key else 0
    return await pool_manager.get_next_key(
        db,
        model=model,
        exclude_key_ids=tried_key_ids,
        sticky_session_key=sticky_session_key,
        sticky_ttl_seconds=sticky_ttl_seconds,
        prefer_bound_key=True,
    )


async def forward_stream_with_retry(
    db: AsyncSession,
    method: str,
    path: str,
    headers: dict,
    body: dict,
    request: Request,
    user_id: Optional[int] = None,
):
    model = body.get("model") if isinstance(body, dict) else None
    sticky_session_key = get_sticky_session_key(headers)
    tried_key_ids = []
    last_status_code = 503
    last_response_headers = {}
    last_response_body = {"error": {"message": "没有可用的 API Key"}}

    for attempt in range(STREAM_RETRY_LIMIT):
        api_key = await select_api_key(
            db,
            model=model,
            sticky_session_key=sticky_session_key,
            tried_key_ids=tried_key_ids,
        )
        if not api_key:
            break

        tried_key_ids.append(api_key.id)
        print(f"[CPA STREAM RETRY] attempt={attempt + 1} api_key_id={api_key.id} model={model} path={path}")
        status_code, response_headers, stream_response, retryable = await proxy_service.forward_stream(
            db=db,
            api_key=api_key,
            method=method,
            path=path,
            headers=headers,
            body=body,
            client_request=request,
            user_id=user_id,
        )
        if status_code < 400:
            pool_manager.clear_key_cooldown(api_key.id)
            if sticky_session_key:
                pool_manager.bind_session_to_key(
                    sticky_session_key,
                    api_key.id,
                    settings.proxy_session_sticky_ttl_seconds,
                    provider=getattr(api_key, "provider", None),
                    model=model,
                )
            return status_code, response_headers, stream_response

        if sticky_session_key:
            pool_manager.clear_session_binding(sticky_session_key)

        if should_cooldown_key(status_code):
            cooldown_seconds = pool_manager.get_cooldown_seconds_for_status(status_code)
            pool_manager.mark_key_cooldown(api_key.id, cooldown_seconds)
            print(f"[CPA KEY COOLDOWN] api_key_id={api_key.id} status={status_code} seconds={cooldown_seconds} path={path}")

        last_status_code = status_code
        last_response_headers = response_headers
        last_response_body = stream_response
        if not retryable:
            break

    return last_status_code, last_response_headers, last_response_body


async def forward_request_with_retry(
    db: AsyncSession,
    method: str,
    path: str,
    headers: dict,
    body: Optional[dict] = None,
    user_id: Optional[int] = None,
):
    model = body.get("model") if isinstance(body, dict) else None
    sticky_session_key = get_sticky_session_key(headers)
    tried_key_ids = []
    last_status_code = 503
    last_response_headers = {}
    last_response_body = {"error": {"message": "没有可用的 API Key"}}

    for attempt in range(REQUEST_RETRY_LIMIT):
        api_key = await select_api_key(
            db,
            model=model,
            sticky_session_key=sticky_session_key,
            tried_key_ids=tried_key_ids,
        )
        if not api_key:
            break

        tried_key_ids.append(api_key.id)
        print(f"[CPA REQUEST RETRY] attempt={attempt + 1} api_key_id={api_key.id} model={model} path={path}")
        status_code, response_headers, response_data = await proxy_service.forward_request(
            db=db,
            api_key=api_key,
            method=method,
            path=path,
            headers=headers,
            body=body,
            user_id=user_id,
        )
        if status_code < 400:
            pool_manager.clear_key_cooldown(api_key.id)
            if sticky_session_key:
                pool_manager.bind_session_to_key(
                    sticky_session_key,
                    api_key.id,
                    settings.proxy_session_sticky_ttl_seconds,
                    provider=getattr(api_key, "provider", None),
                    model=model,
                )
            return status_code, response_headers, response_data

        if sticky_session_key:
            pool_manager.clear_session_binding(sticky_session_key)

        if should_cooldown_key(status_code):
            cooldown_seconds = pool_manager.get_cooldown_seconds_for_status(status_code)
            pool_manager.mark_key_cooldown(api_key.id, cooldown_seconds)
            print(f"[CPA KEY COOLDOWN] api_key_id={api_key.id} status={status_code} seconds={cooldown_seconds} path={path}")
        if status_code not in {401, 403, 429} and status_code < 500:
            return status_code, response_headers, response_data

        last_status_code = status_code
        last_response_headers = response_headers
        last_response_body = response_data

    return last_status_code, last_response_headers, last_response_body


# ============ 认证依赖 ============

async def verify_api_key(
    authorization: str = Header(None),
    x_api_key: str = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """
    验证 API Key
    支持 Bearer token 和 x-api-key 两种方式
    接受 master key 或用户专属 API Key

    返回: {"auth_type": "master"|"user", "user_id": int|None, "supported_models": list|None}
    """
    token = None

    if authorization:
        token = authorization.replace("Bearer ", "").strip()
    elif x_api_key:
        token = x_api_key

    if not token:
        raise HTTPException(status_code=401, detail="缺少认证信息")

    # 优先检查 master key
    if token == settings.master_key:
        return {"auth_type": "master", "user_id": None, "supported_models": None}

    # 检查用户 API Key
    from models.admin_user import AdminUser
    result = await db.execute(
        select(AdminUser).where(AdminUser.api_key == token)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=403, detail="无效的 API Key")

    return {
        "auth_type": "user",
        "user_id": user.id,
        "supported_models": user.get_supported_models(),
    }


def _check_model_permission(auth_info: dict, model: str):
    """检查用户是否有权限使用指定模型"""
    allowed = auth_info.get("supported_models")
    if allowed is not None and model not in allowed:
        raise HTTPException(status_code=403, detail=f"您没有权限使用模型: {model}")


# ============ OpenAI 兼容接口 ============

@router.post("/v1/chat/completions")
async def openai_chat_completions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    OpenAI Chat Completions 兼容接口
    POST /v1/chat/completions
    """
    body = await request.json()
    log_proxy_hit("/v1/chat/completions", body)
    headers = dict(request.headers)

    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _check_model_permission(auth_info, model)

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    if is_stream:
        status_code, response_headers, stream_response = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=body,
            request=request,
            user_id=user_id,
        )
        if status_code >= 400:
            return JSONResponse(content=stream_response, status_code=status_code)
        return StreamingResponse(
            stream_response,
            status_code=status_code,
            media_type=response_headers.get("content-type", "text/event-stream"),
            headers=response_headers,
        )
    else:
        status_code, _, response_data = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=body,
            user_id=user_id,
        )
        return JSONResponse(content=response_data, status_code=status_code)


@router.post("/v1/completions")
async def openai_completions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    OpenAI Completions 兼容接口
    POST /v1/completions
    """
    body = await request.json()
    headers = dict(request.headers)

    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _check_model_permission(auth_info, model)

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    if is_stream:
        status_code, response_headers, stream_response = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/completions",
            headers=headers,
            body=body,
            request=request,
            user_id=user_id,
        )
        if status_code >= 400:
            return JSONResponse(content=stream_response, status_code=status_code)
        return StreamingResponse(
            stream_response,
            status_code=status_code,
            media_type=response_headers.get("content-type", "text/event-stream"),
            headers=response_headers,
        )
    else:
        status_code, _, response_data = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/completions",
            headers=headers,
            body=body,
            user_id=user_id,
        )
        return JSONResponse(content=response_data, status_code=status_code)


@router.get("/v1/models")
async def openai_models(
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    OpenAI Models 兼容接口
    GET /v1/models
    返回当前真实可用模型
    """
    from models import ModelCatalog

    result = await db.execute(select(ModelCatalog).where(ModelCatalog.is_active == True).order_by(ModelCatalog.model_id.asc()))
    catalog_models = result.scalars().all()

    keys = await pool_manager.get_all_keys(db, active_only=True)
    user_allowed = auth_info.get("supported_models")
    models = []
    for item in catalog_models:
        # 普通用户只返回其有权使用的模型
        if user_allowed is not None and item.model_id not in user_allowed:
            continue
        if not any(pool_manager.key_supports_model(key, item.model_id) for key in keys):
            continue
        models.append(
            {
                "id": item.model_id,
                "object": "model",
                "owned_by": item.provider,
                "pricing": {
                    "input": item.input_price,
                    "output": item.output_price,
                },
                "capabilities": {
                    "codex": item.supports_codex,
                    "claudecode": item.supports_claudecode,
                    "protocol": item.protocol,
                },
            }
        )

    return {"object": "list", "data": models}


@router.post("/v1/embeddings")
async def openai_embeddings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    OpenAI Embeddings 兼容接口
    POST /v1/embeddings
    """
    body = await request.json()
    headers = dict(request.headers)

    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _check_model_permission(auth_info, model)

    status_code, _, response_data = await forward_request_with_retry(
        db=db,
        method="POST",
        path="/v1/embeddings",
        headers=headers,
        body=body,
        user_id=auth_info.get("user_id"),
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.post("/v1/responses")
async def openai_responses(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    OpenAI Responses 兼容接口
    POST /v1/responses
    """
    body = await request.json()
    log_proxy_hit("/v1/responses", body)
    headers = dict(request.headers)

    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _check_model_permission(auth_info, model)

    try:
        chat_body = proxy_service.adapt_responses_request_to_chat(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    if is_stream:
        status_code, response_headers, stream_response = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=chat_body,
            request=request,
            user_id=user_id,
        )
        if status_code >= 400:
            return JSONResponse(content=stream_response, status_code=status_code)
        return StreamingResponse(
            proxy_service.adapt_chat_stream_to_responses(stream_response, model),
            status_code=status_code,
            media_type="text/event-stream",
            headers=response_headers,
        )
    else:
        status_code, _, response_data = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=chat_body,
            user_id=user_id,
        )
        if status_code >= 400:
            return JSONResponse(content=response_data, status_code=status_code)
        return JSONResponse(content=proxy_service.adapt_chat_response_to_responses(response_data), status_code=status_code)


# ============ Claude 兼容接口 ============

@router.post("/v1/messages")
async def claude_messages(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    Claude Messages 兼容接口
    POST /v1/messages
    """
    body = await request.json()
    log_proxy_hit("/v1/messages", body)
    headers = dict(request.headers)

    model = body.get("model")
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _check_model_permission(auth_info, model)

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    if is_stream:
        status_code, response_headers, stream_response = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/messages",
            headers=headers,
            body=body,
            request=request,
            user_id=user_id,
        )
        if status_code >= 400:
            return JSONResponse(content=stream_response, status_code=status_code)
        return StreamingResponse(
            stream_response,
            status_code=status_code,
            media_type=response_headers.get("content-type", "text/event-stream"),
            headers=response_headers,
        )
    else:
        status_code, _, response_data = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/messages",
            headers=headers,
            body=body,
            user_id=user_id,
        )
        return JSONResponse(content=response_data, status_code=status_code)


# ============ 通用代理接口 ============

@router.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def generic_proxy(
    path: str,
    request: Request,
    provider: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    通用代理接口
    可以通过 provider 参数指定使用哪个提供商的 Key
    """
    body = None
    if request.method in ["POST", "PUT"]:
        body = await request.json()

    headers = dict(request.headers)

    model = body.get("model") if body else None
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _check_model_permission(auth_info, model)

    status_code, _, response_data = await forward_request_with_retry(
        db=db,
        method=request.method,
        path=f"/{path}",
        headers=headers,
        body=body,
        user_id=auth_info.get("user_id"),
    )
    return JSONResponse(content=response_data, status_code=status_code)
