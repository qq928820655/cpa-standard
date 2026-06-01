"""
代理转发路由 - 兼容 OpenAI 和 Claude 接口
"""
from typing import Optional, Any
from datetime import datetime
import hashlib
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
# 永久失败（余额不足、Key 无效等）禁用 Key 后继续尝试的最大次数
# 设置较大值确保能遍历足够多的 Key
PERMANENT_FAILURE_DISABLE_LIMIT = 20
SESSION_KEY_HEADER = "x-cpa-session-key"
STICKY_SESSION_HEADERS = (
    SESSION_KEY_HEADER,
    "x-session-id",
    "x-conversation-id",
    "x-client-id",
)
CLAUDE_MESSAGES_NATIVE_PROVIDERS = {"claude", "cc"}
CLAUDE_MESSAGES_NATIVE_EXCLUDED_PROVIDERS = {"skk"}
CLAUDE_MESSAGES_NATIVE_PROTOCOL = "anthropic_messages"
CLAUDE_MODEL_KEYWORDS = ("claude", "sonnet", "opus", "haiku")


def log_proxy_hit(path: str, body: dict):
    model = body.get("model") if isinstance(body, dict) else None
    stream = body.get("stream") if isinstance(body, dict) else None
    print(f"[CPA HIT] path={path} model={model} stream={stream}")


def should_cooldown_key(status_code: int) -> bool:
    return status_code in {401, 403, 429} or status_code >= 500


def is_nginx_error_response(response_data: Any) -> bool:
    """判断是否是 nginx/代理层返回的错误页（非业务错误），这类错误应该换 Key 重试"""
    if not isinstance(response_data, dict):
        return False
    error = response_data.get("error")
    if not isinstance(error, dict):
        return False
    message = str(error.get("message") or "")
    # nginx/代理返回的 HTML 错误页特征
    return "<html" in message.lower() or "<body" in message.lower() or "badrequest" in message.lower().replace(" ", "")


def should_retry_on_status(status_code: int, response_data: Any) -> bool:
    """判断该状态码是否应该换 Key 重试（而不是直接返回）"""
    if status_code in {401, 403, 429} or status_code >= 500:
        return True
    # 4xx 中，如果是 nginx/代理层的错误页，也应该换 Key 重试
    if 400 <= status_code < 500 and is_nginx_error_response(response_data):
        return True
    return False


def is_cloudflare_524_response(status_code: int, response_data: Any) -> bool:
    if status_code != 524 or not isinstance(response_data, dict):
        return False
    return (
        bool(response_data.get("cloudflare_error"))
        or str(response_data.get("error_code") or "") == "524"
        or str(response_data.get("status") or "") == "524"
        or str(response_data.get("error_name") or "") == "origin_response_timeout"
    )


def append_continue_message(body: Optional[dict]) -> dict:
    next_body = dict(body or {})
    messages = list(next_body.get("messages") or [])
    messages.append({"role": "user", "content": "继续"})
    next_body["messages"] = messages
    return next_body


def get_sticky_session_key(headers: dict, model: Optional[str] = None) -> Optional[str]:
    if not settings.proxy_session_sticky_enabled:
        return None
    for header_name in STICKY_SESSION_HEADERS:
        header_value = headers.get(header_name)
        if header_value:
            return f"{header_name}:{header_value}"

    if not settings.proxy_session_sticky_fallback_enabled:
        return None

    auth = headers.get("authorization") or headers.get("x-api-key") or ""
    user_agent = headers.get("user-agent") or ""
    model_value = model or ""
    if not auth and not user_agent and not model_value:
        return None

    raw_key = f"{auth}\n{user_agent}\n{model_value}"
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"fallback:{digest}"


def _parse_model_directive(raw_model: str) -> tuple[str, list[str], Optional[str]]:
    """解析模型名中的 {供应商|key名} 指令。
    返回 (实际模型名, 供应商列表, key名称或None)

    格式：
      gpt-5.4              → ('gpt-5.4', [], None)
      {bb}gpt-5.4          → ('gpt-5.4', ['bb'], None)
      {bb,bbimg}gpt-5.4    → ('gpt-5.4', ['bb', 'bbimg'], None)
      {bb|etnoet}gpt-5.4   → ('gpt-5.4', ['bb'], 'etnoet')
    """
    import re
    if not raw_model or not raw_model.startswith('{'):
        return raw_model, [], None

    match = re.match(r'^\{([^}]+)\}(.*)$', raw_model)
    if not match:
        return raw_model, [], None

    directive = match.group(1).strip()
    actual_model = match.group(2).strip()

    key_name = None
    if '|' in directive:
        parts = directive.split('|', 1)
        provider_part = parts[0].strip()
        key_name = parts[1].strip() or None
    else:
        provider_part = directive

    providers = [p.strip() for p in provider_part.split(',') if p.strip()]
    return actual_model, providers, key_name


def _strip_model_suffix(model: str) -> tuple[str, str]:
    """去掉模型名中的 [...] 后缀，返回 (基础名, 后缀)。
    例：'gpt-5.5[1m]' → ('gpt-5.5', '[1m]')
        'gpt-5.5'     → ('gpt-5.5', '')
    """
    import re
    match = re.search(r'(\[.*?\])$', model)
    if match:
        suffix = match.group(1)
        base = model[:match.start()].strip()
        return base, suffix
    return model, ''


def _model_supports_suffix(model_name: str, suffix: str) -> bool:
    """判断模型是否支持指定后缀（简单判断：模型名本身不含该后缀时，认为不支持）。
    实际上这里保守处理：只要映射目标不含该后缀，就尝试加上后缀。
    """
    if not suffix:
        return True
    return suffix.lower() in model_name.lower()


PERMANENT_BALANCE_FAILURE_KEYWORDS = [
    "预扣费额度失败",
    "用户剩余额度",
    "需要预扣费额度",
    "余额不足",
    "额度不足",
    "insufficient_user_quota",
    "insufficient quota",
    "insufficient balance",
    "insufficient credits",
    "insufficient account balance",
    "insufficient_balance",
    "not enough credits",
    "balance not enough",
    "quota exceeded",
]
PERMANENT_KEY_FAILURE_KEYWORDS = [
    "无api",
    "无 api",
    "没有api",
    "没有 api",
    "没有可用api",
    "没有可用 api",
    "api不存在",
    "api 不存在",
    "key无效",
    "密钥无效",
    "no api",
    "api key not found",
    "invalid api key",
    "invalid_api_key",
    "incorrect api key",
]


def collect_upstream_error_texts(response_data: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(response_data, str):
        texts.append(response_data)
        return texts
    if not isinstance(response_data, dict):
        return texts

    error_data = response_data.get("error")
    if isinstance(error_data, dict):
        for key in ("message", "code", "type", "param"):
            value = error_data.get(key)
            if value:
                texts.append(str(value))
    elif isinstance(error_data, str):
        texts.append(error_data)

    for key in ("message", "code", "type", "detail"):
        value = response_data.get(key)
        if value:
            texts.append(str(value))

    return texts


def is_permanent_key_failure(status_code: Optional[int], response_data: Any) -> bool:
    message = "\n".join(collect_upstream_error_texts(response_data)).lower()
    if not message:
        return False
    if any(keyword in message for keyword in PERMANENT_BALANCE_FAILURE_KEYWORDS):
        return True
    if status_code in {401, 403, 404} and any(keyword in message for keyword in PERMANENT_KEY_FAILURE_KEYWORDS):
        return True
    return False


def _extract_remaining_quota(message: str) -> Optional[float]:
    """从余额不足错误信息中提取用户剩余额度数值（⚡单位）"""
    import re
    patterns = [
        r"用户剩余额度[：:]\s*[⚡$]?\s*([\d.]+)",
        r"remaining[_\s]?quota[：:\s]+[⚡$]?\s*([\d.]+)",
        r"balance[：:\s]+[⚡$]?\s*([\d.]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, message, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
    return None


def _get_weight_for_remaining_quota(remaining: float, provider: Optional[str] = None) -> Optional[int]:
    """根据剩余额度和配置规则返回降权值或处理动作。
    返回值：
      - 正整数：降权到该权重
      - 0：关闭 Key（disable）
      - -1：不处理（none）
      - None：无匹配规则，默认关闭
    provider: 当前 Key 的提供商，用于过滤规则的 providers 字段（留空匹配所有）
    """
    from config import export_config
    rules = export_config.get("balance_downgrade_rules") or []
    current_provider = (provider or "").strip().lower()

    for rule in rules:
        if not isinstance(rule, dict):
            continue

        # 提供商过滤：规则有 providers 字段时，只对指定提供商生效
        rule_providers = rule.get("providers")
        if rule_providers and isinstance(rule_providers, list):
            allowed = [p.strip().lower() for p in rule_providers if p.strip()]
            if allowed and current_provider not in allowed:
                continue

        min_val = rule.get("min")
        max_val = rule.get("max")
        action = rule.get("action", "disable")

        in_range = True
        if min_val is not None:
            try:
                if remaining < float(min_val):
                    in_range = False
            except (TypeError, ValueError):
                in_range = False
        if max_val is not None:
            try:
                if remaining >= float(max_val):
                    in_range = False
            except (TypeError, ValueError):
                in_range = False

        if not in_range:
            continue

        if action == "none":
            return -1
        if action == "disable":
            return 0
        if action == "weight":
            try:
                w = int(rule.get("weight", 1))
                return max(1, w)
            except (TypeError, ValueError):
                return 1

    return None


def is_balance_insufficient_failure(response_data: Any) -> bool:
    """判断是否是余额不足错误（需要特殊处理降权逻辑）"""
    message = "\n".join(collect_upstream_error_texts(response_data)).lower()
    if not message:
        return False
    return any(keyword in message for keyword in PERMANENT_BALANCE_FAILURE_KEYWORDS)


def is_service_unavailable_error(response_data: Any) -> bool:
    """判断是否为服务暂不可用错误（应切换到其他提供商的 Key 重试）"""
    if not isinstance(response_data, dict):
        return False
    error = response_data.get("error")
    if isinstance(error, dict):
        msg = str(error.get("message") or "").lower()
        err_type = str(error.get("type") or "").lower()
        if "temporarily unavailable" in msg and err_type == "api_error":
            return True
    return False


async def disable_failed_api_key(db: AsyncSession, api_key: Any, reason: str):
    api_key.is_active = False
    api_key.updated_at = datetime.utcnow()
    await db.commit()
    pool_manager.clear_key_cooldown(api_key.id)
    provider = getattr(api_key, "provider", None)
    if provider:
        pool_manager.reset_index(provider)
    reason_preview = str(reason or "").replace("\n", " ")[:180]
    print(f"[CPA KEY DISABLED] api_key_id={api_key.id} provider={provider} reason={reason_preview}")


import json as _json_module

BB_IMAGE_MODELS = [
    "gpt-image-1",
    "gpt-image-2",
    "gpt-image-2-pro",
    "nano-banana-pro",
    "nano-banana-pro-4k",
]
BB_TO_BBIMG_THRESHOLD = 0.18   # 低于此值且 >= 0.04 时转为 bbimg
BB_DISABLE_THRESHOLD = 0.04    # 低于此值时关闭 Key


async def migrate_bb_key_to_bbimg(db: AsyncSession, api_key: Any, reason: str):
    """将 bb Key 迁移为 bbimg，支持模型改为图片模型"""
    import json as _j
    api_key.provider = "bbimg"
    api_key.supported_models = _j.dumps(BB_IMAGE_MODELS, ensure_ascii=False)
    api_key.updated_at = datetime.utcnow()
    await db.commit()
    pool_manager.clear_key_cooldown(api_key.id)
    pool_manager.reset_index("bb")
    pool_manager.reset_index("bbimg")
    reason_preview = str(reason or "").replace("\n", " ")[:180]
    print(f"[CPA KEY BB->BBIMG] api_key_id={api_key.id} reason={reason_preview}")


async def downgrade_key_weight(db: AsyncSession, api_key: Any, new_weight: int, reason: str):
    """降低 Key 权重"""
    api_key.weight = new_weight
    api_key.updated_at = datetime.utcnow()
    await db.commit()
    provider = getattr(api_key, "provider", None)
    if provider:
        pool_manager.reset_index(provider)
    reason_preview = str(reason or "").replace("\n", " ")[:180]
    print(f"[CPA KEY DOWNGRADED] api_key_id={api_key.id} provider={provider} new_weight={new_weight} reason={reason_preview}")


async def handle_permanent_key_failure(
    db: AsyncSession,
    api_key: Any,
    *,
    status_code: Optional[int],
    response_data: Any,
    sticky_session_key: Optional[str],
) -> bool:
    """处理永久性 Key 失败。返回 True 表示已处理（调用方应 continue 换 Key）"""
    if is_balance_insufficient_failure(response_data):
        if sticky_session_key:
            pool_manager.clear_session_binding(sticky_session_key)
        reason = " | ".join(collect_upstream_error_texts(response_data))
        full_message = "\n".join(collect_upstream_error_texts(response_data))
        remaining = _extract_remaining_quota(full_message)

        # 检查供应商迁移规则（如 bb → bbimg）
        if remaining is not None:
            from config import export_config as _ec
            migration_rules = _ec.get("provider_migration_rules") or []
            current_provider = (getattr(api_key, "provider", "") or "").strip().lower()
            for rule in migration_rules:
                if not isinstance(rule, dict):
                    continue
                if (rule.get("from_provider") or "").strip().lower() != current_provider:
                    continue
                min_bal = float(rule.get("min_balance") or 0)
                max_bal = rule.get("max_balance")
                if remaining < min_bal:
                    # 低于最小值，走后续关闭逻辑
                    break
                if max_bal is not None and remaining >= float(max_bal):
                    # 超出此规则范围，继续检查下一条规则
                    continue
                # 命中规则：迁移供应商
                import json as _j
                to_provider = (rule.get("to_provider") or "").strip()
                new_models = rule.get("supported_models") or []
                if to_provider:
                    api_key.provider = to_provider
                if new_models:
                    api_key.supported_models = _j.dumps(new_models, ensure_ascii=False)
                api_key.updated_at = datetime.utcnow()
                await db.commit()
                pool_manager.clear_key_cooldown(api_key.id)
                pool_manager.reset_index(current_provider)
                if to_provider:
                    pool_manager.reset_index(to_provider)
                print(f"[CPA KEY MIGRATED] api_key_id={api_key.id} {current_provider}->{to_provider} remaining={remaining}")
                return True

        # 通用降权/关闭规则
        if remaining is not None:
            current_provider = (getattr(api_key, "provider", "") or "").strip().lower()
            result = _get_weight_for_remaining_quota(remaining, provider=current_provider)
            if result == -1:
                return True
            if result is not None and result > 0:
                await downgrade_key_weight(db, api_key, result, reason)
                return True
        await disable_failed_api_key(db, api_key, reason)
        return True

    message = "\n".join(collect_upstream_error_texts(response_data)).lower()
    if not message:
        return False
    if status_code in {401, 403, 404} and any(keyword in message for keyword in PERMANENT_KEY_FAILURE_KEYWORDS):
        if sticky_session_key:
            pool_manager.clear_session_binding(sticky_session_key)
        reason = " | ".join(collect_upstream_error_texts(response_data))
        await disable_failed_api_key(db, api_key, reason)
        return True

    return False


async def select_api_key(
    db: AsyncSession,
    *,
    model: Optional[str],
    sticky_session_key: Optional[str],
    tried_key_ids: list[int],
    filter_providers: Optional[list[str]] = None,
    filter_key_name: Optional[str] = None,
    exclude_providers: Optional[list[str]] = None,
):
    sticky_ttl_seconds = settings.proxy_session_sticky_ttl_seconds if sticky_session_key else 0
    return await pool_manager.get_next_key(
        db,
        model=model,
        exclude_key_ids=tried_key_ids,
        sticky_session_key=sticky_session_key,
        sticky_ttl_seconds=sticky_ttl_seconds,
        prefer_bound_key=True,
        providers=filter_providers or None,
        key_name=filter_key_name,
        exclude_providers=exclude_providers or None,
    )


async def build_upstream_body_for_key(
    db: AsyncSession,
    api_key,
    body: Optional[dict],
    request_model: Optional[str],
    filter_providers: Optional[list[str]] = None,
):
    """根据系统模型映射构建上游请求体"""
    if not isinstance(body, dict) or not request_model:
        return body, request_model
    plan = await pool_manager.build_model_match_plan(db, request_model, providers=filter_providers)
    upstream_model = pool_manager.resolve_upstream_model_for_key(api_key, request_model, plan)
    if not upstream_model or upstream_model == body.get("model"):
        return body, upstream_model
    upstream_body = dict(body)
    upstream_body["model"] = upstream_model
    return upstream_body, upstream_model


async def forward_stream_with_retry(
    db: AsyncSession,
    method: str,
    path: str,
    headers: dict,
    body: dict,
    request: Request,
    user_id: Optional[int] = None,
    original_model: Optional[str] = None,
    force_providers: Optional[list] = None,
    force_key_name: Optional[str] = None,
):
    raw_model = body.get("model") if isinstance(body, dict) else None
    actual_model, filter_providers, filter_key_name = _parse_model_directive(raw_model or "")
    # 接口层传入的 force_providers 优先级更高（已在接口层解析过）
    if force_providers is not None:
        filter_providers = force_providers
    if force_key_name is not None:
        filter_key_name = force_key_name
    # 如果有指令，替换 body 里的模型为实际模型
    if filter_providers or filter_key_name:
        body = dict(body)
        body["model"] = actual_model
        # original_model 用去掉前缀的实际模型名（对用户透明，不暴露 {bb} 前缀）
        if not original_model:
            original_model = actual_model
    model = body.get("model") if isinstance(body, dict) else None
    sticky_session_key = get_sticky_session_key(headers, model)
    tried_key_ids = []
    last_status_code = 503
    last_response_headers = {}
    last_response_body = {"error": {"message": "没有可用的 API Key"}}

    retry_count = 0
    disable_count = 0
    service_unavailable_providers: list[str] = []
    SERVICE_UNAVAILABLE_BYPASS_LIMIT = 10

    while retry_count < STREAM_RETRY_LIMIT and disable_count < PERMANENT_FAILURE_DISABLE_LIMIT:
        api_key = await select_api_key(
            db,
            model=model,
            sticky_session_key=sticky_session_key,
            tried_key_ids=tried_key_ids,
            filter_providers=filter_providers or None,
            filter_key_name=filter_key_name,
            exclude_providers=service_unavailable_providers or None,
        )
        if not api_key:
            break

        tried_key_ids.append(api_key.id)
        print(f"[CPA STREAM RETRY] retry={retry_count} disable={disable_count} api_key_id={api_key.id} model={model} path={path}")

        upstream_body, upstream_model = await build_upstream_body_for_key(db, api_key, body, model, filter_providers or None)

        # 判断是否命中流式缓冲规则（针对特定提供商/模型，完整缓冲后再输出，断流可重试）
        use_buffer = proxy_service._match_stream_buffer_rule(api_key, upstream_model)
        if use_buffer:
            stream_fn = proxy_service.forward_stream_buffered
        else:
            stream_fn = proxy_service.forward_stream

        status_code, response_headers, stream_response, retryable = await stream_fn(
            db=db,
            api_key=api_key,
            method=method,
            path=path,
            headers=headers,
            body=upstream_body,
            client_request=request,
            user_id=user_id,
            original_model=original_model,
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
            return status_code, response_headers, stream_response, api_key

        last_status_code = status_code
        last_response_headers = response_headers
        last_response_body = stream_response

        # 服务暂不可用：切换到其他提供商的 Key，不计入重试次数，对客户端透明
        if is_service_unavailable_error(stream_response):
            provider = getattr(api_key, "provider", None) or ""
            if provider and provider not in service_unavailable_providers:
                service_unavailable_providers.append(provider)
            pool_manager.mark_key_cooldown(api_key.id, pool_manager.get_cooldown_seconds_for_status(503))
            if sticky_session_key:
                pool_manager.clear_session_binding(sticky_session_key)
            print(f"[CPA SERVICE UNAVAILABLE SWITCH] api_key_id={api_key.id} provider={provider} excluded_providers={service_unavailable_providers}")
            if len(service_unavailable_providers) >= SERVICE_UNAVAILABLE_BYPASS_LIMIT:
                break
            continue

        if await handle_permanent_key_failure(
            db,
            api_key,
            status_code=status_code,
            response_data=stream_response,
            sticky_session_key=sticky_session_key,
        ):
            # 永久失败：禁用 Key，不消耗 retry_count，继续尝试下一个
            disable_count += 1
            continue

        if sticky_session_key:
            pool_manager.clear_session_binding(sticky_session_key)

        if should_cooldown_key(status_code):
            cooldown_seconds = pool_manager.get_cooldown_seconds_for_status(status_code)
            pool_manager.mark_key_cooldown(api_key.id, cooldown_seconds)
            print(f"[CPA KEY COOLDOWN] api_key_id={api_key.id} status={status_code} seconds={cooldown_seconds} path={path}")

        if not retryable:
            break

        retry_count += 1

    return last_status_code, last_response_headers, last_response_body, None


async def forward_request_with_retry(
    db: AsyncSession,
    method: str,
    path: str,
    headers: dict,
    body: Optional[dict] = None,
    user_id: Optional[int] = None,
    original_model: Optional[str] = None,
    force_providers: Optional[list] = None,
    force_key_name: Optional[str] = None,
):
    raw_model = body.get("model") if isinstance(body, dict) else None
    actual_model, filter_providers, filter_key_name = _parse_model_directive(raw_model or "")
    if force_providers is not None:
        filter_providers = force_providers
    if force_key_name is not None:
        filter_key_name = force_key_name
    if filter_providers or filter_key_name:
        body = dict(body) if body else {}
        body["model"] = actual_model
        # original_model 用去掉前缀的实际模型名（对用户透明，不暴露 {bb} 前缀）
        if not original_model:
            original_model = actual_model
    model = body.get("model") if isinstance(body, dict) else None
    sticky_session_key = get_sticky_session_key(headers, model)
    tried_key_ids = []
    last_status_code = 503
    last_response_headers = {}
    last_response_body = {"error": {"message": "没有可用的 API Key"}}

    retry_count = 0          # 非永久失败的重试次数
    disable_count = 0        # 永久失败禁用 Key 的次数
    auto_continue_used = False
    service_unavailable_providers: list[str] = []
    SERVICE_UNAVAILABLE_BYPASS_LIMIT = 10

    while retry_count < REQUEST_RETRY_LIMIT and disable_count < PERMANENT_FAILURE_DISABLE_LIMIT:
        api_key = await select_api_key(
            db,
            model=model,
            sticky_session_key=sticky_session_key,
            tried_key_ids=tried_key_ids,
            filter_providers=filter_providers or None,
            filter_key_name=filter_key_name,
            exclude_providers=service_unavailable_providers or None,
        )
        if not api_key:
            break

        tried_key_ids.append(api_key.id)
        print(f"[CPA REQUEST RETRY] retry={retry_count} disable={disable_count} api_key_id={api_key.id} model={model} path={path}")
        upstream_body, upstream_model = await build_upstream_body_for_key(db, api_key, body, model, filter_providers or None)
        status_code, response_headers, response_data = await proxy_service.forward_request(
            db=db,
            api_key=api_key,
            method=method,
            path=path,
            headers=headers,
            body=upstream_body,
            user_id=user_id,
            original_model=original_model,
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
            return status_code, response_headers, response_data, api_key

        last_status_code = status_code
        last_response_headers = response_headers
        last_response_body = response_data

        # 服务暂不可用：切换到其他提供商的 Key，不计入重试次数，对客户端透明
        if is_service_unavailable_error(response_data):
            provider = getattr(api_key, "provider", None) or ""
            if provider and provider not in service_unavailable_providers:
                service_unavailable_providers.append(provider)
            pool_manager.mark_key_cooldown(api_key.id, pool_manager.get_cooldown_seconds_for_status(503))
            if sticky_session_key:
                pool_manager.clear_session_binding(sticky_session_key)
            print(f"[CPA SERVICE UNAVAILABLE SWITCH] api_key_id={api_key.id} provider={provider} excluded_providers={service_unavailable_providers}")
            if len(service_unavailable_providers) >= SERVICE_UNAVAILABLE_BYPASS_LIMIT:
                break
            continue

        if await handle_permanent_key_failure(
            db,
            api_key,
            status_code=status_code,
            response_data=response_data,
            sticky_session_key=sticky_session_key,
        ):
            # 永久失败：禁用 Key，不消耗 retry_count，继续尝试下一个
            disable_count += 1
            continue

        if sticky_session_key:
            pool_manager.clear_session_binding(sticky_session_key)

        if (
            not auto_continue_used
            and is_cloudflare_524_response(status_code, response_data)
            and pool_manager.is_cloudflare_524_auto_continue_enabled(getattr(api_key, "provider", None))
        ):
            auto_continue_body = append_continue_message(body)
            auto_continue_upstream_body, _auto_continue_upstream_model = await build_upstream_body_for_key(
                db,
                api_key,
                auto_continue_body,
                model,
                filter_providers or None,
            )
            auto_continue_used = True
            print(f"[CPA CLOUDFLARE 524 AUTO CONTINUE] api_key_id={api_key.id} provider={getattr(api_key, 'provider', None)} model={model} path={path}")
            status_code, response_headers, response_data = await proxy_service.forward_request(
                db=db,
                api_key=api_key,
                method=method,
                path=path,
                headers=headers,
                body=auto_continue_upstream_body,
                user_id=user_id,
                original_model=original_model,
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
                return status_code, response_headers, response_data, api_key
            last_status_code = status_code
            last_response_headers = response_headers
            last_response_body = response_data

        if should_cooldown_key(status_code):
            cooldown_seconds = pool_manager.get_cooldown_seconds_for_status(status_code)
            pool_manager.mark_key_cooldown(api_key.id, cooldown_seconds)
            print(f"[CPA KEY COOLDOWN] api_key_id={api_key.id} status={status_code} seconds={cooldown_seconds} path={path}")

        if not should_retry_on_status(status_code, response_data):
            return status_code, response_headers, response_data, api_key

        retry_count += 1

    return last_status_code, last_response_headers, last_response_body, None


async def forward_image_request_with_retry(
    db: AsyncSession,
    method: str,
    path: str,
    headers: dict,
    body: Optional[dict] = None,
    data: Optional[dict] = None,
    files: Optional[list[tuple[str, tuple[str, bytes, str]]]] = None,
    user_id: Optional[int] = None,
):
    model = None
    if isinstance(body, dict):
        model = body.get("model")
    if model is None and isinstance(data, dict):
        model_value = data.get("model")
        if isinstance(model_value, list):
            model = model_value[0] if model_value else None
        else:
            model = model_value

    sticky_session_key = get_sticky_session_key(headers, model)
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
        print(f"[CPA IMAGE RETRY] attempt={attempt + 1} api_key_id={api_key.id} model={model} path={path}")
        status_code, response_headers, response_data = await proxy_service.forward_image_request(
            db=db,
            api_key=api_key,
            method=method,
            path=path,
            headers=headers,
            body=body,
            data=data,
            files=files,
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

        last_status_code = status_code
        last_response_headers = response_headers
        last_response_body = response_data

        if await handle_permanent_key_failure(
            db,
            api_key,
            status_code=status_code,
            response_data=response_data,
            sticky_session_key=sticky_session_key,
        ):
            continue

        if sticky_session_key:
            pool_manager.clear_session_binding(sticky_session_key)

        if should_cooldown_key(status_code):
            cooldown_seconds = pool_manager.get_cooldown_seconds_for_status(status_code)
            pool_manager.mark_key_cooldown(api_key.id, cooldown_seconds)
            print(f"[CPA KEY COOLDOWN] api_key_id={api_key.id} status={status_code} seconds={cooldown_seconds} path={path}")
        if status_code not in {401, 403, 429} and status_code < 500:
            return status_code, response_headers, response_data

    return last_status_code, last_response_headers, last_response_body


async def read_multipart_image_request(request: Request) -> tuple[dict, list[tuple[str, tuple[str, bytes, str]]]]:
    form = await request.form()
    data: dict[str, list[str] | str] = {}
    files: list[tuple[str, tuple[str, bytes, str]]] = []

    for field_name, value in form.multi_items():
        if hasattr(value, "filename") and hasattr(value, "read"):
            content = await value.read()
            files.append(
                (
                    field_name,
                    (
                        value.filename or field_name,
                        content,
                        value.content_type or "application/octet-stream",
                    ),
                )
            )
            continue

        text_value = str(value)
        existing = data.get(field_name)
        if existing is None:
            data[field_name] = text_value
        elif isinstance(existing, list):
            existing.append(text_value)
        else:
            data[field_name] = [existing, text_value]

    return data, files


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
        "daily_token_limit": getattr(user, "daily_token_limit", None),
        "weekly_token_limit": getattr(user, "weekly_token_limit", None),
        "monthly_token_limit": getattr(user, "monthly_token_limit", None),
        "quota_exceeded_mode": getattr(user, "quota_exceeded_mode", None) or "normal",
        "quota_exceeded_message": getattr(user, "quota_exceeded_message", None),
        "model_mapping": _parse_user_model_mapping(getattr(user, "model_mapping", None)),
        "quota_reset_at": getattr(user, "quota_reset_at", None),
    }


def _check_model_permission(auth_info: dict, model: str):
    """检查用户是否有权限使用指定模型。
    检查时去掉 [...] 后缀，使 gpt-5.5[1m] 能匹配 supported_models 里的 gpt-5.5。
    """
    allowed = auth_info.get("supported_models")
    if allowed is None:
        return
    # 去掉后缀后再检查
    model_base, _ = _strip_model_suffix(model)
    if model not in allowed and model_base not in allowed:
        raise HTTPException(status_code=403, detail=f"您没有权限使用模型: {model}")


def _parse_user_model_mapping(raw) -> dict:
    """解析用户模型映射 JSON"""
    if not raw:
        return {}
    import json as _json
    try:
        mapping = _json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(mapping, dict):
            # value 可以是字符串（直接映射）或列表（阶梯映射），保留原始类型
            return {str(k): v for k, v in mapping.items() if k and v is not None}
    except Exception:
        pass
    return {}


def _apply_model_mapping(body: dict, auth_info: dict) -> tuple[dict, str]:
    """将请求 body 中的 model 替换为映射后的模型。
    返回 (新 body, 原始模型名)，原始模型名用于响应还原。
    注意：阶梯映射需要异步查用量，此函数只处理简单映射；阶梯映射由 _apply_model_mapping_async 处理。
    """
    original_model = body.get("model") or ""
    mapping = auth_info.get("model_mapping") or {}
    if not mapping or not original_model:
        return body, original_model
    rule = mapping.get(original_model)
    if rule is None:
        return body, original_model
    # 简单映射（字符串）
    if isinstance(rule, str):
        if rule == original_model:
            return body, original_model
        new_body = dict(body)
        new_body["model"] = rule
        return new_body, original_model
    # 阶梯映射（列表）由 _apply_model_mapping_async 处理，此处返回原始
    return body, original_model


async def _apply_model_mapping_async(body: dict, auth_info: dict, db) -> tuple[dict, str, list, Optional[str]]:
    """支持阶梯映射的异步版本，同时支持 {provider} 前缀和 [...] 后缀的智能匹配。

    返回 (新body, original_model, 映射目标的provider过滤列表, 映射目标的key_name)
    - 如果触发了映射，provider过滤来自映射目标的 {provider} 前缀
    - 如果没有触发映射，返回空列表（调用方决定是否用原始请求的 {provider} 过滤）
    """
    original_model = body.get("model") or ""
    mapping = auth_info.get("model_mapping") or {}
    if not mapping or not original_model:
        return body, original_model, [], None

    # 分离后缀
    model_base, model_suffix = _strip_model_suffix(original_model)

    # 构建大小写不敏感的查找字典
    mapping_lower = {k.lower(): k for k in mapping}

    def _get_rule(key: str):
        """大小写不敏感地查找映射规则"""
        if key in mapping:
            return mapping[key]
        orig_key = mapping_lower.get(key.lower())
        if orig_key:
            return mapping[orig_key]
        return None

    async def _get_used_tokens():
        user_id = auth_info.get("user_id")
        if not user_id:
            return 0
        from models import UsageLog
        from sqlalchemy import func, select as _sel
        from datetime import datetime
        now = datetime.utcnow()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        quota_reset_at = auth_info.get("quota_reset_at")
        effective_start = day_start
        if quota_reset_at and quota_reset_at > day_start:
            effective_start = quota_reset_at
        result = await db.execute(
            _sel(func.coalesce(func.sum(UsageLog.total_tokens), 0)).where(
                UsageLog.user_id == user_id,
                UsageLog.request_time >= effective_start,
                UsageLog.status == "success",
            )
        )
        return int(result.scalar() or 0)

    async def _apply_rule(rule, inherit_suffix: bool):
        """应用映射规则，返回 新body 或 None"""
        if isinstance(rule, str):
            target = rule
            if inherit_suffix and model_suffix:
                _, target_suffix = _strip_model_suffix(target)
                if not target_suffix:
                    target = target + model_suffix
            if target == original_model:
                return None
            new_body = dict(body)
            new_body["model"] = target
            return new_body
        if isinstance(rule, list) and rule:
            used_tokens = await _get_used_tokens()
            for tier in rule:
                if not isinstance(tier, dict):
                    continue
                from_val = tier.get("from", 0) or 0
                to_val = tier.get("to")
                tier_model = tier.get("model") or original_model
                if used_tokens >= from_val and (to_val is None or used_tokens < to_val):
                    if inherit_suffix and model_suffix:
                        _, target_suffix = _strip_model_suffix(tier_model)
                        if not target_suffix:
                            tier_model = tier_model + model_suffix
                    if tier_model != original_model:
                        new_body = dict(body)
                        new_body["model"] = tier_model
                        return new_body
                    break
        return None

    # 1. 精确匹配（含后缀）
    rule = _get_rule(original_model)
    if rule is not None:
        result = await _apply_rule(rule, inherit_suffix=False)
        if result is not None:
            # 解析映射目标的 {provider} 前缀
            target_model = result.get("model") or ""
            _, target_providers, target_key = _parse_model_directive(target_model)
            if target_providers or target_key:
                # 去掉目标 body 里的 {provider} 前缀
                clean_target, _, _ = _parse_model_directive(target_model)
                result = dict(result)
                result["model"] = clean_target
            return result, model_base, target_providers, target_key

    # 2. 去掉后缀后匹配基础名
    if model_suffix and model_base != original_model:
        rule_base = _get_rule(model_base)
        if rule_base is not None:
            result = await _apply_rule(rule_base, inherit_suffix=True)
            if result is not None:
                target_model = result.get("model") or ""
                _, target_providers, target_key = _parse_model_directive(target_model)
                if target_providers or target_key:
                    clean_target, _, _ = _parse_model_directive(target_model)
                    result = dict(result)
                    result["model"] = clean_target
                return result, model_base, target_providers, target_key

    # 无映射，original_model 也用基础名
    return body, model_base, [], None


def _restore_model_in_response(response_data: Any, original_model: str) -> Any:
    """将响应体中的 model 字段还原为用户请求的原始模型（对用户透明）。"""
    if not original_model or not isinstance(response_data, dict):
        return response_data
    if response_data.get("model") and response_data["model"] != original_model:
        response_data = dict(response_data)
        response_data["model"] = original_model
    return response_data


def is_claude_family_model(model: str) -> bool:
    """自动识别 Claude 家族模型名。"""
    model_base, _ = _strip_model_suffix(model or "")
    normalized = model_base.lower()
    return any(keyword in normalized for keyword in CLAUDE_MODEL_KEYWORDS)


def is_claude_messages_native_unsupported(status_code: int, response_data: Any) -> bool:
    """判断上游是否不支持原生 Claude Messages 路径。"""
    if status_code in {404, 405, 501}:
        return True
    if status_code != 400:
        return False
    message = " ".join(collect_upstream_error_texts(response_data)).lower()
    return any(keyword in message for keyword in ("not found", "unsupported", "no route", "unknown endpoint", "invalid path"))


async def resolve_claude_messages_native_providers(
    db: AsyncSession,
    model: str,
    force_providers: Optional[list[str]] = None,
) -> list[str]:
    """根据模型协议配置和模型名自动解析可原生处理 Claude Messages 的 provider。"""
    model_base, _ = _strip_model_suffix(model or "")
    candidates = [item for item in [model, model_base] if item]
    if not candidates:
        return []

    from models import ApiKey, ModelCatalog

    providers: list[str] = []
    seen: set[str] = set()

    def add_provider(provider: Optional[str]):
        value = (provider or "").strip()
        if not value or value in seen or value in CLAUDE_MESSAGES_NATIVE_EXCLUDED_PROVIDERS:
            return
        seen.add(value)
        providers.append(value)

    catalog_query = select(ModelCatalog).where(
        ModelCatalog.is_active == True,
        ModelCatalog.protocol == CLAUDE_MESSAGES_NATIVE_PROTOCOL,
        ModelCatalog.model_id.in_(candidates),
    )
    if force_providers:
        catalog_query = catalog_query.where(ModelCatalog.provider.in_(force_providers))
    catalog_result = await db.execute(catalog_query)
    for item in catalog_result.scalars().all():
        add_provider(getattr(item, "provider", None))

    if providers:
        return providers

    if force_providers:
        for provider in force_providers:
            if provider in CLAUDE_MESSAGES_NATIVE_PROVIDERS:
                add_provider(provider)
        if providers or not is_claude_family_model(model):
            return providers

    if not is_claude_family_model(model):
        return []

    key_query = select(ApiKey.provider).where(ApiKey.is_active == True)
    if force_providers:
        key_query = key_query.where(ApiKey.provider.in_(force_providers))
    key_result = await db.execute(key_query.distinct())
    for provider in key_result.scalars().all():
        provider_value = (provider or "").strip()
        if provider_value and provider_value not in CLAUDE_MESSAGES_NATIVE_EXCLUDED_PROVIDERS:
            add_provider(provider_value)
    return providers


async def _check_user_quota(auth_info: dict, db: AsyncSession):
    """检查用户是否超出 token 用量限额"""
    user_id = auth_info.get("user_id")
    if not user_id:
        return  # master key 不限制

    daily_limit = auth_info.get("daily_token_limit")
    weekly_limit = auth_info.get("weekly_token_limit")
    monthly_limit = auth_info.get("monthly_token_limit")

    if daily_limit is None and weekly_limit is None and monthly_limit is None:
        return  # 无限制

    mode = auth_info.get("quota_exceeded_mode") or "normal"
    custom_message = (auth_info.get("quota_exceeded_message") or "").strip()

    import secrets as _secrets

    def _raise_exceeded(period: str, used: int, limit: int):
        if mode == "disguise":
            # 伪装成 New API 的 Invalid token 错误
            request_id = _secrets.token_hex(16)
            msg = custom_message or f"Invalid token (request id: {request_id})"
            raise HTTPException(
                status_code=401,
                detail={"error": {"code": "", "message": msg, "type": "new_api_error"}},
            )
        else:
            msg = custom_message or f"已超出{period}用量限额（{used:,} / {limit:,} tokens）"
            raise HTTPException(status_code=429, detail=msg)

    from models import UsageLog
    from sqlalchemy import func
    from datetime import datetime, timedelta

    now = datetime.utcnow()
    quota_reset_at = auth_info.get("quota_reset_at")

    async def get_usage(start: datetime) -> int:
        # 如果有重置时间点，取 max(start, quota_reset_at) 作为实际起始
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

    if daily_limit is not None:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        used = await get_usage(day_start)
        if used >= daily_limit:
            _raise_exceeded("日", used, daily_limit)

    if weekly_limit is not None:
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        used = await get_usage(week_start)
        if used >= weekly_limit:
            _raise_exceeded("周", used, weekly_limit)

    if monthly_limit is not None:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = await get_usage(month_start)
        if used >= monthly_limit:
            _raise_exceeded("月", used, monthly_limit)


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

    _actual_model_for_check, _, _ = _parse_model_directive(model or "")
    _check_model_permission(auth_info, _actual_model_for_check)
    await _check_user_quota(auth_info, db)

    # 应用模型映射（对用户透明，实际转发不同模型）
    # 去掉 {provider} 指令前缀，确保 original_model 是干净的模型名
    _clean_model, _dir_providers, _dir_key = _parse_model_directive(body.get("model") or "")
    if _dir_providers or _dir_key:
        body = dict(body)
        body["model"] = _clean_model
    body, original_model, _mapped_providers, _mapped_key = await _apply_model_mapping_async(body, auth_info, db)

    # 确定最终的 provider/key 过滤：
    # - 触发了映射且映射目标有 {provider} 前缀 → 用映射目标的过滤
    # - 触发了映射但目标无前缀 → 清空过滤（在所有供应商里找）
    # - 未触发映射 → 用原始请求的 {provider} 过滤
    if _mapped_providers or _mapped_key:
        _dir_providers = _mapped_providers
        _dir_key = _mapped_key
    elif body.get("model") != _clean_model:
        # 触发了映射（body 里的 model 已变化），清空原始 provider 过滤
        _dir_providers = []
        _dir_key = None
    # 否则未触发映射，保留 _dir_providers 和 _dir_key

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    if is_stream:
        status_code, response_headers, stream_response, _selected_api_key = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=body,
            request=request,
            user_id=user_id,
            original_model=original_model,
            force_providers=_dir_providers if _dir_providers else None,
            force_key_name=_dir_key,
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
        status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=body,
            user_id=user_id,
            original_model=original_model,
            force_providers=_dir_providers if _dir_providers else None,
            force_key_name=_dir_key,
        )
        return JSONResponse(content=_restore_model_in_response(response_data, original_model), status_code=status_code)


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

    # 解析 {provider} 指令，权限检查用实际模型名
    _actual_model_for_check, _, _ = _parse_model_directive(model)
    _check_model_permission(auth_info, _actual_model_for_check)
    await _check_user_quota(auth_info, db)

    # 去掉 {provider} 指令前缀，确保 original_model 是干净的模型名
    _clean_model, _dir_providers, _dir_key = _parse_model_directive(body.get("model") or "")
    if _dir_providers or _dir_key:
        body = dict(body)
        body["model"] = _clean_model
    body, original_model, _mapped_providers, _mapped_key = await _apply_model_mapping_async(body, auth_info, db)
    if _mapped_providers or _mapped_key:
        _dir_providers = _mapped_providers
        _dir_key = _mapped_key
    elif body.get("model") != _clean_model:
        _dir_providers = []
        _dir_key = None

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    if is_stream:
        status_code, response_headers, stream_response, _selected_api_key = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/completions",
            headers=headers,
            body=body,
            request=request,
            user_id=user_id,
            original_model=original_model,
            force_providers=_dir_providers if _dir_providers else None,
            force_key_name=_dir_key,
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
        status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/completions",
            headers=headers,
            body=body,
            user_id=user_id,
            original_model=original_model,
            force_providers=_dir_providers if _dir_providers else None,
            force_key_name=_dir_key,
        )
        return JSONResponse(content=_restore_model_in_response(response_data, original_model), status_code=status_code)


@router.post("/v1/images/generations")
async def openai_images_generations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    OpenAI Images Generations 兼容接口
    POST /v1/images/generations
    """
    body = await request.json()
    headers = dict(request.headers)

    model = body.get("model") if isinstance(body, dict) else None
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _actual_model_for_check, _, _ = _parse_model_directive(model or "")
    _check_model_permission(auth_info, _actual_model_for_check)
    await _check_user_quota(auth_info, db)

    status_code, _, response_data = await forward_image_request_with_retry(
        db=db,
        method="POST",
        path="/v1/images/generations",
        headers=headers,
        body=body,
        user_id=auth_info.get("user_id"),
    )
    return JSONResponse(content=response_data, status_code=status_code)


@router.post("/v1/images/edits")
async def openai_images_edits(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """
    OpenAI Images Edits 兼容接口
    POST /v1/images/edits
    """
    headers = dict(request.headers)
    data, files = await read_multipart_image_request(request)

    model = data.get("model")
    if isinstance(model, list):
        model = model[0] if model else None
    if not model:
        raise HTTPException(status_code=400, detail="缺少 model")

    _check_model_permission(auth_info, str(model))
    await _check_user_quota(auth_info, db)

    status_code, _, response_data = await forward_image_request_with_retry(
        db=db,
        method="POST",
        path="/v1/images/edits",
        headers=headers,
        data=data,
        files=files,
        user_id=auth_info.get("user_id"),
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

    # 解析 {provider} 指令，权限检查用实际模型名
    _actual_model_for_check, _, _ = _parse_model_directive(model)
    _check_model_permission(auth_info, _actual_model_for_check)
    await _check_user_quota(auth_info, db)

    # 去掉 {provider} 指令前缀，确保 original_model 是干净的模型名
    _clean_model, _dir_providers, _dir_key = _parse_model_directive(body.get("model") or "")
    if _dir_providers or _dir_key:
        body = dict(body)
        body["model"] = _clean_model
    body, original_model, _mapped_providers, _mapped_key = await _apply_model_mapping_async(body, auth_info, db)
    if _mapped_providers or _mapped_key:
        _dir_providers = _mapped_providers
        _dir_key = _mapped_key
    elif body.get("model") != _clean_model:
        _dir_providers = []
        _dir_key = None

    status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
        db=db,
        method="POST",
        path="/v1/embeddings",
        headers=headers,
        body=body,
        user_id=auth_info.get("user_id"),
        original_model=original_model,
        force_providers=_dir_providers if _dir_providers else None,
        force_key_name=_dir_key,
    )
    return JSONResponse(content=_restore_model_in_response(response_data, original_model), status_code=status_code)


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

    # 解析 {provider} 指令，权限检查用实际模型名
    _actual_model_for_check, _, _ = _parse_model_directive(model)
    _check_model_permission(auth_info, _actual_model_for_check)
    await _check_user_quota(auth_info, db)

    # 去掉 {provider} 指令前缀，确保 original_model 是干净的模型名
    _clean_model, _dir_providers, _dir_key = _parse_model_directive(body.get("model") or "")
    if _dir_providers or _dir_key:
        body = dict(body)
        body["model"] = _clean_model
    body, original_model, _mapped_providers, _mapped_key = await _apply_model_mapping_async(body, auth_info, db)
    if _mapped_providers or _mapped_key:
        _dir_providers = _mapped_providers
        _dir_key = _mapped_key
    elif body.get("model") != _clean_model:
        _dir_providers = []
        _dir_key = None

    try:
        chat_body = proxy_service.adapt_responses_request_to_chat(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    if is_stream:
        status_code, response_headers, stream_response, _selected_api_key = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=chat_body,
            request=request,
            user_id=user_id,
            original_model=original_model,
            force_providers=_dir_providers if _dir_providers else None,
            force_key_name=_dir_key,
        )
        if status_code >= 400:
            return JSONResponse(content=stream_response, status_code=status_code)
        return StreamingResponse(
            proxy_service.adapt_chat_stream_to_responses(stream_response, original_model or model),
            status_code=status_code,
            media_type="text/event-stream",
            headers=response_headers,
        )
    else:
        status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/chat/completions",
            headers=headers,
            body=chat_body,
            user_id=user_id,
            original_model=original_model,
            force_providers=_dir_providers if _dir_providers else None,
            force_key_name=_dir_key,
        )
        if status_code >= 400:
            return JSONResponse(content=response_data, status_code=status_code)
        adapted = proxy_service.adapt_chat_response_to_responses(response_data)
        return JSONResponse(content=_restore_model_in_response(adapted, original_model), status_code=status_code)


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

    # 解析 {provider} 指令，权限检查用实际模型名
    _actual_model_for_check, _, _ = _parse_model_directive(model)
    _check_model_permission(auth_info, _actual_model_for_check)
    await _check_user_quota(auth_info, db)

    # 去掉 {provider} 指令前缀，确保 original_model 是干净的模型名
    _clean_model, _dir_providers, _dir_key = _parse_model_directive(body.get("model") or "")
    if _dir_providers or _dir_key:
        body = dict(body)
        body["model"] = _clean_model
    body, original_model, _mapped_providers, _mapped_key = await _apply_model_mapping_async(body, auth_info, db)
    if _mapped_providers or _mapped_key:
        _dir_providers = _mapped_providers
        _dir_key = _mapped_key
    elif body.get("model") != _clean_model:
        _dir_providers = []
        _dir_key = None

    is_stream = body.get("stream", False)
    user_id = auth_info.get("user_id")

    native_providers = await resolve_claude_messages_native_providers(db, body.get("model") or "", _dir_providers or None)
    if not native_providers and _dir_providers:
        native_providers = [provider for provider in _dir_providers if provider in CLAUDE_MESSAGES_NATIVE_PROVIDERS]
    should_convert_to_chat = not bool(native_providers)

    if is_stream:
        if should_convert_to_chat:
            chat_body = proxy_service.adapt_claude_messages_request_to_chat(body)
            status_code, response_headers, stream_response, selected_api_key = await forward_stream_with_retry(
                db=db,
                method="POST",
                path="/v1/chat/completions",
                headers=headers,
                body=chat_body,
                request=request,
                user_id=user_id,
                original_model=original_model,
                force_providers=_dir_providers if _dir_providers else None,
                force_key_name=_dir_key,
            )
            if status_code >= 400:
                return JSONResponse(content=stream_response, status_code=status_code)
            token_compat_provider = getattr(selected_api_key, "provider", None)
            input_tokens_estimate = (
                proxy_service._estimate_claude_compat_input_tokens(body)
                if proxy_service.is_claudecode_token_compat_enabled(token_compat_provider)
                else 0
            )
            return StreamingResponse(
                proxy_service.adapt_chat_stream_to_claude_messages(
                    stream_response,
                    original_model or model,
                    input_tokens_estimate,
                ),
                status_code=status_code,
                media_type="text/event-stream",
                headers=response_headers,
            )

        status_code, response_headers, stream_response, _selected_api_key = await forward_stream_with_retry(
            db=db,
            method="POST",
            path="/v1/messages",
            headers=headers,
            body=body,
            request=request,
            user_id=user_id,
            original_model=original_model,
            force_providers=native_providers,
            force_key_name=_dir_key,
        )
        if status_code >= 400:
            if is_claude_messages_native_unsupported(status_code, stream_response):
                chat_body = proxy_service.adapt_claude_messages_request_to_chat(body)
                status_code, response_headers, stream_response, selected_api_key = await forward_stream_with_retry(
                    db=db,
                    method="POST",
                    path="/v1/chat/completions",
                    headers=headers,
                    body=chat_body,
                    request=request,
                    user_id=user_id,
                    original_model=original_model,
                    force_providers=_dir_providers if _dir_providers else None,
                    force_key_name=_dir_key,
                )
                if status_code < 400:
                    token_compat_provider = getattr(selected_api_key, "provider", None)
                    input_tokens_estimate = (
                        proxy_service._estimate_claude_compat_input_tokens(body)
                        if proxy_service.is_claudecode_token_compat_enabled(token_compat_provider)
                        else 0
                    )
                    return StreamingResponse(
                        proxy_service.adapt_chat_stream_to_claude_messages(
                            stream_response,
                            original_model or model,
                            input_tokens_estimate,
                        ),
                        status_code=status_code,
                        media_type="text/event-stream",
                        headers=response_headers,
                    )
            return JSONResponse(content=stream_response, status_code=status_code)
        return StreamingResponse(
            stream_response,
            status_code=status_code,
            media_type=response_headers.get("content-type", "text/event-stream"),
            headers=response_headers,
        )
    else:
        if should_convert_to_chat:
            chat_body = proxy_service.adapt_claude_messages_request_to_chat(body)
            status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
                db=db,
                method="POST",
                path="/v1/chat/completions",
                headers=headers,
                body=chat_body,
                user_id=user_id,
                original_model=original_model,
                force_providers=_dir_providers if _dir_providers else None,
                force_key_name=_dir_key,
            )
            if status_code < 400:
                response_data = proxy_service.adapt_chat_response_to_claude_message(response_data, original_model or model)
            return JSONResponse(content=_restore_model_in_response(response_data, original_model), status_code=status_code)

        status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
            db=db,
            method="POST",
            path="/v1/messages",
            headers=headers,
            body=body,
            user_id=user_id,
            original_model=original_model,
            force_providers=native_providers,
            force_key_name=_dir_key,
        )
        if status_code >= 400 and is_claude_messages_native_unsupported(status_code, response_data):
            chat_body = proxy_service.adapt_claude_messages_request_to_chat(body)
            status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
                db=db,
                method="POST",
                path="/v1/chat/completions",
                headers=headers,
                body=chat_body,
                user_id=user_id,
                original_model=original_model,
                force_providers=_dir_providers if _dir_providers else None,
                force_key_name=_dir_key,
            )
            if status_code < 400:
                response_data = proxy_service.adapt_chat_response_to_claude_message(response_data, original_model or model)
        return JSONResponse(content=_restore_model_in_response(response_data, original_model), status_code=status_code)


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

    _actual_model_for_check, _, _ = _parse_model_directive(model or "")
    _check_model_permission(auth_info, _actual_model_for_check)
    await _check_user_quota(auth_info, db)

    status_code, _, response_data, _selected_api_key = await forward_request_with_retry(
        db=db,
        method=request.method,
        path=f"/{path}",
        headers=headers,
        body=body,
        user_id=auth_info.get("user_id"),
    )
    return JSONResponse(content=response_data, status_code=status_code)
