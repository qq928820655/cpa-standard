"""
OpenAI Plus account service
"""
import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker
from models import OpenAIPlusAccount, OpenAIPlusUsageLog

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_WHAM_BASE_URL = "https://chatgpt.com/backend-api/wham"
CODEX_USER_AGENT = "codex_cli_rs/0.118.0 (Mac OS 26.3.1; arm64) iTerm.app/3.6.9"
CODEX_ORIGINATOR = "codex_cli_rs"
CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
DEFAULT_CODEX_INSTRUCTIONS = "You are ChatGPT, a helpful assistant."
PLUS_UNIFIED_API_KEY = "cpa-plus-unified"
IMPORT_COMMIT_BATCH_SIZE = 500
IMPORT_RETURN_ITEM_LIMIT = 1000
IMPORT_AUTH_CHECK_TIMEOUT_SECONDS = 12

PLUS_SESSION_STICKY_ENABLED = True
PLUS_SESSION_STICKY_TTL_SECONDS = 6 * 3600

_session_sticky_map: dict[str, tuple[int, float]] = {}


def extract_session_key(headers: dict, body: Optional[dict] = None) -> Optional[str]:
    for header_name in ["x-session-id", "x-conversation-id", "x-client-id", "x-stainless-retry-count"]:
        val = headers.get(header_name)
        if val:
            return f"h:{header_name}:{val}"
    if body and isinstance(body, dict):
        metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
        for field in ["session_id", "conversation_id", "user_id", "user"]:
            val = metadata.get(field) or body.get(field)
            if val:
                return f"b:{field}:{val}"
    return None


def get_sticky_account_id(session_key: str) -> Optional[int]:
    if not PLUS_SESSION_STICKY_ENABLED or not session_key:
        return None
    entry = _session_sticky_map.get(session_key)
    if not entry:
        return None
    account_id, ts = entry
    import time
    if time.time() - ts > PLUS_SESSION_STICKY_TTL_SECONDS:
        _session_sticky_map.pop(session_key, None)
        return None
    return account_id


def set_sticky_account(session_key: str, account_id: int):
    if not PLUS_SESSION_STICKY_ENABLED or not session_key:
        return
    import time
    _session_sticky_map[session_key] = (account_id, time.time())


def cleanup_expired_sticky():
    import time
    now = time.time()
    expired = [k for k, (_, ts) in _session_sticky_map.items() if now - ts > PLUS_SESSION_STICKY_TTL_SECONDS]
    for k in expired:
        _session_sticky_map.pop(k, None)


def mask_token(value: Optional[str]) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    if len(token) <= 16:
        return "*" * len(token)
    return f"{token[:8]}...{token[-6:]}"


def parse_json_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError:
        return None


def decode_jwt_payload(token: str) -> dict:
    parts = (token or "").split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(payload.encode("utf-8")))
    except Exception:
        return {}


def normalize_import_payload(raw: str) -> list[dict]:
    text = (raw or "").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def get_nested(data: dict, *paths: list[str]) -> Any:
    for path in paths:
        current: Any = data
        for part in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(part)
        if current not in (None, ""):
            return current
    return None


def token_fingerprint(value: Optional[str]) -> str:
    token = (value or "").strip()
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def build_import_identities(
    *,
    chatgpt_user_id: str,
    email: str,
    refresh_token: str,
    access_token: str,
    account_id: str,
) -> list[tuple[str, str]]:
    identities: list[tuple[str, str]] = []
    if chatgpt_user_id:
        identities.append(("chatgpt_user_id", chatgpt_user_id.lower()))
    if email:
        identities.append(("email", email.lower()))
    refresh_fp = token_fingerprint(refresh_token)
    if refresh_fp:
        identities.append(("refresh_token", refresh_fp))
    access_fp = token_fingerprint(access_token)
    if access_fp:
        identities.append(("access_token", access_fp))
    if account_id and not identities:
        identities.append(("account_id", account_id.lower()))
    return identities


async def find_existing_import_account(
    db: AsyncSession,
    *,
    identities: list[tuple[str, str]],
    account_id: str,
) -> Optional[OpenAIPlusAccount]:
    for kind, value in identities:
        if kind == "chatgpt_user_id":
            result = await db.execute(select(OpenAIPlusAccount).where(func.lower(OpenAIPlusAccount.chatgpt_user_id) == value))
            account = result.scalars().first()
            if account:
                return account
        elif kind == "email":
            result = await db.execute(select(OpenAIPlusAccount).where(func.lower(OpenAIPlusAccount.email) == value))
            account = result.scalars().first()
            if account:
                return account
        elif kind in {"refresh_token", "access_token"}:
            result = await db.execute(select(OpenAIPlusAccount))
            for account in result.scalars().all():
                token_value = account.refresh_token if kind == "refresh_token" else account.access_token
                if token_fingerprint(token_value) == value:
                    return account
        elif kind == "account_id" and account_id:
            result = await db.execute(select(OpenAIPlusAccount).where(OpenAIPlusAccount.account_id == account_id))
            account = result.scalars().first()
            if account:
                return account
    return None


def build_headers(account: OpenAIPlusAccount, stream: bool = False) -> dict:
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {account.access_token}",
        "user-agent": CODEX_USER_AGENT,
        "originator": CODEX_ORIGINATOR,
        "connection": "Keep-Alive",
        "accept": "text/event-stream" if stream else "application/json",
    }
    if account.account_id:
        headers["chatgpt-account-id"] = account.account_id
    return headers


def serialize_account(account: OpenAIPlusAccount, include_token: bool = False) -> dict:
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "account_id": account.account_id,
        "chatgpt_user_id": account.chatgpt_user_id,
        "plan_type": account.plan_type,
        "access_token": account.access_token if include_token else mask_token(account.access_token),
        "refresh_token": account.refresh_token if include_token else mask_token(account.refresh_token),
        "id_token": account.id_token if include_token else mask_token(account.id_token),
        "expires_at": account.expires_at.isoformat() if account.expires_at else None,
        "disabled": bool(account.disabled),
        "websockets": bool(account.websockets),
        "proxy_key": account.proxy_key,
        "last_check_status": account.last_check_status,
        "last_check_message": account.last_check_message,
        "last_check_at": account.last_check_at.isoformat() if account.last_check_at else None,
        "request_count": int(account.request_count or 0),
        "success_count": int(account.success_count or 0),
        "error_count": int(account.error_count or 0),
        "prompt_tokens": int(account.prompt_tokens or 0),
        "completion_tokens": int(account.completion_tokens or 0),
        "total_tokens": int(account.total_tokens or 0),
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }


async def get_account_by_proxy_key(db: AsyncSession, proxy_key: str) -> Optional[OpenAIPlusAccount]:
    result = await db.execute(select(OpenAIPlusAccount).where(OpenAIPlusAccount.proxy_key == proxy_key))
    return result.scalar_one_or_none()


async def get_next_available_account(db: AsyncSession, session_key: Optional[str] = None) -> Optional[OpenAIPlusAccount]:
    now = datetime.utcnow()
    if session_key:
        sticky_id = get_sticky_account_id(session_key)
        if sticky_id:
            account = await db.get(OpenAIPlusAccount, sticky_id)
            if account and not account.disabled and (not account.expires_at or account.expires_at > now):
                return account
    result = await db.execute(
        select(OpenAIPlusAccount)
        .where(OpenAIPlusAccount.disabled == False)
        .where((OpenAIPlusAccount.expires_at == None) | (OpenAIPlusAccount.expires_at > now))
        .order_by(OpenAIPlusAccount.request_count.asc(), OpenAIPlusAccount.updated_at.asc(), OpenAIPlusAccount.id.asc())
        .limit(1)
    )
    account = result.scalar_one_or_none()
    if account and session_key:
        set_sticky_account(session_key, account.id)
    return account


def is_unified_proxy_key(proxy_key: str) -> bool:
    return (proxy_key or "").strip() == PLUS_UNIFIED_API_KEY


def parse_import_account_payload(payload: dict, index: int) -> dict:
    access_token = str(get_nested(payload, ["tokens", "access_token"], ["tokens", "accessToken"], ["access_token"], ["accessToken"], ["token"]) or "").strip()
    if not access_token:
        raise ValueError("缺少 access_token")
    refresh_token = str(get_nested(payload, ["tokens", "refresh_token"], ["tokens", "refreshToken"], ["refresh_token"], ["refreshToken"]) or "").strip()
    id_token = str(get_nested(payload, ["tokens", "id_token"], ["tokens", "idToken"], ["id_token"], ["idToken"]) or "").strip()
    jwt_payload = decode_jwt_payload(access_token)
    openai_auth = jwt_payload.get("https://api.openai.com/auth") if isinstance(jwt_payload.get("https://api.openai.com/auth"), dict) else {}
    profile = jwt_payload.get("https://api.openai.com/profile") if isinstance(jwt_payload.get("https://api.openai.com/profile"), dict) else {}
    account_id = str(get_nested(payload, ["account_id"], ["accountId"], ["chatgpt_account_id"]) or openai_auth.get("chatgpt_account_id") or "").strip()
    email = str(get_nested(payload, ["email"], ["user", "email"]) or profile.get("email") or "").strip()
    chatgpt_user_id = str(get_nested(payload, ["chatgpt_user_id"], ["user_id"], ["user", "id"]) or openai_auth.get("chatgpt_user_id") or openai_auth.get("user_id") or "").strip()
    plan_type = str(get_nested(payload, ["plan_type"], ["planType"], ["account", "plan_type"]) or openai_auth.get("chatgpt_plan_type") or "").strip()
    expires_at = parse_json_datetime(get_nested(payload, ["expired"], ["expires_at"], ["expiresAt"]))
    if not expires_at and jwt_payload.get("exp"):
        expires_at = datetime.fromtimestamp(int(jwt_payload["exp"]), tz=timezone.utc).replace(tzinfo=None)
    identities = build_import_identities(
        chatgpt_user_id=chatgpt_user_id,
        email=email,
        refresh_token=refresh_token,
        access_token=access_token,
        account_id=account_id,
    )
    if not identities:
        raise ValueError("缺少可识别账号身份")
    return {
        "index": index,
        "name": str(payload.get("name") or email or account_id or f"Plus-{index}"),
        "email": email,
        "account_id": account_id,
        "chatgpt_user_id": chatgpt_user_id,
        "plan_type": plan_type,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "id_token": id_token,
        "expires_at": expires_at,
        "disabled": bool(payload.get("disabled", False)),
        "websockets": bool(payload.get("websockets", False)),
        "identities": identities,
    }


async def build_existing_account_indexes(db: AsyncSession) -> dict[str, dict[str, OpenAIPlusAccount]]:
    indexes: dict[str, dict[str, OpenAIPlusAccount]] = {
        "chatgpt_user_id": {},
        "email": {},
        "refresh_token": {},
        "access_token": {},
        "account_id": {},
    }
    result = await db.execute(select(OpenAIPlusAccount))
    for account in result.scalars().all():
        if account.chatgpt_user_id:
            indexes["chatgpt_user_id"][account.chatgpt_user_id.lower()] = account
        if account.email:
            indexes["email"][account.email.lower()] = account
        refresh_fp = token_fingerprint(account.refresh_token)
        if refresh_fp:
            indexes["refresh_token"][refresh_fp] = account
        access_fp = token_fingerprint(account.access_token)
        if access_fp:
            indexes["access_token"][access_fp] = account
        if account.account_id:
            indexes["account_id"][account.account_id.lower()] = account
    return indexes


def find_indexed_import_account(indexes: dict[str, dict[str, OpenAIPlusAccount]], identities: list[tuple[str, str]]) -> Optional[OpenAIPlusAccount]:
    for kind, value in identities:
        account = indexes.get(kind, {}).get(value)
        if account:
            return account
    return None


def put_account_indexes(indexes: dict[str, dict[str, OpenAIPlusAccount]], account: OpenAIPlusAccount, identities: list[tuple[str, str]]):
    for kind, value in identities:
        indexes.setdefault(kind, {})[value] = account


def build_temp_import_account(parsed: dict) -> OpenAIPlusAccount:
    account = OpenAIPlusAccount(proxy_key="import-check")
    account.name = parsed["name"]
    account.email = parsed["email"] or None
    account.account_id = parsed["account_id"] or None
    account.chatgpt_user_id = parsed["chatgpt_user_id"] or None
    account.plan_type = parsed["plan_type"] or None
    account.access_token = parsed["access_token"]
    account.refresh_token = parsed["refresh_token"] or None
    account.id_token = parsed["id_token"] or None
    account.expires_at = parsed["expires_at"]
    return account


async def is_import_account_unauthorized(parsed: dict) -> tuple[bool, str]:
    account = build_temp_import_account(parsed)
    url = f"{CODEX_WHAM_BASE_URL}/usage"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(IMPORT_AUTH_CHECK_TIMEOUT_SECONDS)) as client:
            response = await client.get(url, headers=build_headers(account))
        if response.status_code == 401:
            return True, f"HTTP 401: {response.text[:200]}"
        return False, f"HTTP {response.status_code}"
    except Exception as exc:
        return False, str(exc)


async def import_accounts(db: AsyncSession, content: str) -> dict:
    payloads = normalize_import_payload(content)
    created = 0
    updated = 0
    failed = 0
    skipped = 0
    items = []
    omitted_items = 0
    batch_seen: set[tuple[str, str]] = set()
    indexes = await build_existing_account_indexes(db)

    def add_item(item: dict):
        nonlocal omitted_items
        if len(items) < IMPORT_RETURN_ITEM_LIMIT:
            items.append(item)
        else:
            omitted_items += 1

    for index, payload in enumerate(payloads, start=1):
        try:
            parsed = parse_import_account_payload(payload, index)
            identities = parsed["identities"]
            duplicate_identity = next((identity for identity in identities if identity in batch_seen), None)
            if duplicate_identity:
                skipped += 1
                add_item({"index": index, "action": "skipped", "email": parsed["email"], "account_id": parsed["account_id"], "message": "本批次重复账号"})
                continue
            batch_seen.update(identities)

            unauthorized, auth_message = await is_import_account_unauthorized(parsed)
            if unauthorized:
                skipped += 1
                add_item({"index": index, "action": "skipped", "email": parsed["email"], "account_id": parsed["account_id"], "message": "检测为 401，已跳过导入"})
                continue

            account = find_indexed_import_account(indexes, identities)
            if account:
                updated += 1
                action = "updated"
            else:
                account = OpenAIPlusAccount(proxy_key=f"cpa-plus-{secrets.token_urlsafe(24)}")
                db.add(account)
                created += 1
                action = "created"

            account.name = parsed["name"]
            account.email = parsed["email"] or None
            account.account_id = parsed["account_id"] or None
            account.chatgpt_user_id = parsed["chatgpt_user_id"] or None
            account.plan_type = parsed["plan_type"] or None
            account.access_token = parsed["access_token"]
            account.refresh_token = parsed["refresh_token"] or None
            account.id_token = parsed["id_token"] or None
            account.expires_at = parsed["expires_at"]
            account.disabled = parsed["disabled"]
            account.websockets = parsed["websockets"]
            account.updated_at = datetime.utcnow()
            put_account_indexes(indexes, account, identities)
            add_item({"index": index, "action": action, "email": parsed["email"], "account_id": parsed["account_id"]})

            if (created + updated) % IMPORT_COMMIT_BATCH_SIZE == 0:
                await db.commit()
        except Exception as exc:
            failed += 1
            add_item({"index": index, "action": "failed", "message": str(exc)})

    await db.commit()
    return {
        "total": len(payloads),
        "created": created,
        "updated": updated,
        "failed": failed,
        "skipped": skipped,
        "items": items,
        "omitted_items": omitted_items,
        "batch_size": IMPORT_COMMIT_BATCH_SIZE,
    }




def _normalize_rate_limit_window(window: Any) -> Optional[dict]:
    if not isinstance(window, dict):
        return None
    reset_at = window.get("reset_at") or window.get("resets_at")
    return {
        "used_percent": window.get("used_percent"),
        "limit_window_seconds": window.get("limit_window_seconds"),
        "window_minutes": int(window.get("limit_window_seconds") or 0) // 60 if window.get("limit_window_seconds") else window.get("window_minutes"),
        "reset_at": reset_at,
    }


def normalize_quota_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {"available": False, "message": "invalid quota payload"}
    error_payload = payload.get("error") if isinstance(payload.get("error"), dict) else None
    if error_payload:
        reset_at = error_payload.get("reset_at") or error_payload.get("resets_at")
        return {
            "available": False,
            "message": error_payload.get("message") or error_payload.get("type") or "quota unavailable",
            "plan_type": error_payload.get("plan_type"),
            "primary": _normalize_rate_limit_window({
                "used_percent": 100,
                "resets_at": reset_at,
            }) if reset_at else None,
            "secondary": None,
            "credits": None,
            "additional_rate_limits": [],
            "rate_limit_reached_type": error_payload.get("type"),
        }
    rate_limit = payload.get("rate_limit") if isinstance(payload.get("rate_limit"), dict) else {}
    credits = payload.get("credits") if isinstance(payload.get("credits"), dict) else None
    additional = payload.get("additional_rate_limits") if isinstance(payload.get("additional_rate_limits"), list) else []
    return {
        "available": True,
        "plan_type": payload.get("plan_type"),
        "primary": _normalize_rate_limit_window(rate_limit.get("primary_window")),
        "secondary": _normalize_rate_limit_window(rate_limit.get("secondary_window")),
        "credits": credits,
        "additional_rate_limits": additional,
        "rate_limit_reached_type": payload.get("rate_limit_reached_type"),
    }


async def fetch_account_quota(account: OpenAIPlusAccount, timeout_seconds: int = 30) -> dict:
    url = f"{CODEX_WHAM_BASE_URL}/usage"
    try:
        timeout_seconds = max(5, min(int(timeout_seconds or 30), 300))
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
            response = await client.get(url, headers=build_headers(account))
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                quota = normalize_quota_payload(payload)
                quota["message"] = f"HTTP {response.status_code}: {quota.get('message') or response.text[:300]}"
                return quota
            return {"available": False, "message": f"HTTP {response.status_code}: {response.text[:300]}"}
        return normalize_quota_payload(response.json())
    except Exception as exc:
        return {"available": False, "message": str(exc)}


async def check_account(account: OpenAIPlusAccount) -> tuple[str, str]:
    url = f"{CODEX_BASE_URL}/responses"
    body = {
        "model": "gpt-5.5",
        "stream": True,
        "store": False,
        "instructions": DEFAULT_CODEX_INSTRUCTIONS,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "ping"}]}],
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=30)) as client:
            async with client.stream("POST", url, headers=build_headers(account, stream=True), json=body) as response:
                if response.status_code >= 400:
                    text = await response.aread()
                    return "error", f"HTTP {response.status_code}: {text.decode('utf-8', 'ignore')[:300]}"
                async for chunk in response.aiter_bytes():
                    if chunk:
                        return "success", "Connection OK"
                return "success", "Connection OK"
    except Exception as exc:
        return "error", str(exc)




async def refresh_account_if_needed(db: AsyncSession, account: OpenAIPlusAccount, timeout_seconds: int = 60) -> OpenAIPlusAccount:
    """有 refresh_token 时在过期前刷新 access token"""
    if not account.refresh_token or not account.expires_at:
        return account
    if account.expires_at > datetime.utcnow() + timedelta(minutes=5):
        return account

    data = {
        "grant_type": "refresh_token",
        "refresh_token": account.refresh_token,
        "client_id": CODEX_CLIENT_ID,
        "scope": "openid profile email",
    }
    timeout_seconds = max(5, min(int(timeout_seconds or 60), 300))
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
        response = await client.post(OPENAI_TOKEN_URL, data=data, headers={"content-type": "application/x-www-form-urlencoded"})
    if response.status_code >= 400:
        account.last_check_status = "error"
        account.last_check_message = f"刷新 token 失败: HTTP {response.status_code}"
        account.last_check_at = datetime.utcnow()
        await db.commit()
        return account

    payload = response.json()
    access_token = payload.get("access_token")
    if not access_token:
        return account
    account.access_token = access_token
    if payload.get("refresh_token"):
        account.refresh_token = payload["refresh_token"]
    if payload.get("id_token"):
        account.id_token = payload["id_token"]
    expires_in = int(payload.get("expires_in") or 0)
    if expires_in > 0:
        account.expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
    jwt_payload = decode_jwt_payload(access_token)
    openai_auth = jwt_payload.get("https://api.openai.com/auth") if isinstance(jwt_payload.get("https://api.openai.com/auth"), dict) else {}
    profile = jwt_payload.get("https://api.openai.com/profile") if isinstance(jwt_payload.get("https://api.openai.com/profile"), dict) else {}
    account.account_id = openai_auth.get("chatgpt_account_id") or account.account_id
    account.chatgpt_user_id = openai_auth.get("chatgpt_user_id") or openai_auth.get("user_id") or account.chatgpt_user_id
    account.plan_type = openai_auth.get("chatgpt_plan_type") or account.plan_type
    account.email = profile.get("email") or account.email
    account.last_check_status = "success"
    account.last_check_message = "token 已刷新"
    account.last_check_at = datetime.utcnow()
    account.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(account)
    return account




def extract_response_text(response_data: Any) -> str:
    if not isinstance(response_data, dict):
        return ""
    if isinstance(response_data.get("output_text"), str):
        return response_data["output_text"]
    parts = []
    for item in response_data.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("text"):
                parts.append(str(content["text"]))
    return "".join(parts)


def responses_to_chat_completion(response_data: Any, requested_model: str) -> Any:
    if not isinstance(response_data, dict):
        return response_data
    usage = response_data.get("usage") or {}
    return {
        "id": response_data.get("id", f"chatcmpl_{int(datetime.utcnow().timestamp() * 1000)}"),
        "object": "chat.completion",
        "created": int(datetime.utcnow().timestamp()),
        "model": response_data.get("model") or requested_model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": extract_response_text(response_data)},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("input_tokens", usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0,
            "completion_tokens": usage.get("output_tokens", usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0,
            "total_tokens": usage.get("total_tokens", 0) if isinstance(usage, dict) else 0,
        },
    }


def chat_messages_to_responses_input(messages: list) -> list:
    input_items = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role") or "user"
        if role == "system":
            role = "developer"
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "input_text", "text": content}]
        elif isinstance(content, list):
            converted = []
            for item in content:
                if isinstance(item, str):
                    converted.append({"type": "input_text", "text": item})
                elif isinstance(item, dict):
                    if item.get("type") == "text":
                        converted.append({"type": "input_text", "text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        image_url = item.get("image_url")
                        url = image_url.get("url") if isinstance(image_url, dict) else image_url
                        if url:
                            converted.append({"type": "input_image", "image_url": url})
                    else:
                        converted.append(item)
            content = converted
        else:
            content = []
        input_items.append({"role": role, "content": content})
    return input_items


def build_sse(data: Any, event: Optional[str] = None) -> bytes:
    payload = json.dumps(data, ensure_ascii=False)
    if event:
        return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")
    return f"data: {payload}\n\n".encode("utf-8")


async def responses_stream_to_chat_stream(stream, model: str, db: Optional[AsyncSession] = None, account: Optional[OpenAIPlusAccount] = None, success: bool = True):
    chat_id = f"chatcmpl_{int(datetime.utcnow().timestamp() * 1000)}"
    created = int(datetime.utcnow().timestamp())
    buffer = ""
    usage_totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        async for chunk in stream:
            buffer += chunk.decode("utf-8", "ignore")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
                if not data_lines:
                    continue
                data_text = "\n".join(data_lines)
                if data_text == "[DONE]":
                    continue
                try:
                    payload = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                usage_totals = merge_usage_totals(usage_totals, extract_usage_from_responses_payload(payload))
                event_type = payload.get("type") if isinstance(payload, dict) else ""
                delta_text = None
                if event_type in {"response.output_text.delta", "response.text.delta"}:
                    delta_text = payload.get("delta")
                elif event_type == "response.output_item.done" and isinstance(payload.get("item"), dict):
                    item = payload["item"]
                    if item.get("type") == "message":
                        for content in item.get("content") or []:
                            if isinstance(content, dict) and content.get("text"):
                                delta_text = content["text"]
                elif event_type == "response.completed":
                    yield build_sse({
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        "usage": usage_totals or None,
                    })
                    yield b"data: [DONE]\n\n"
                    continue
                if delta_text:
                    yield build_sse({
                        "id": chat_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}],
                    })
        if buffer.strip():
            yield b"data: [DONE]\n\n"
    finally:
        if account is not None:
            if db is not None:
                await add_account_usage(db, account, usage_totals, success)
                await add_usage_log_by_id(account.id, model, "chat.completions", True, None, usage_totals, success)
            else:
                await add_account_usage_by_id(account.id, usage_totals, success)
                await add_usage_log_by_id(account.id, model, "chat.completions", True, None, usage_totals, success)


def extract_usage_from_responses_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    usage = payload.get("usage")
    if not isinstance(usage, dict) and isinstance(payload.get("response"), dict):
        usage = payload["response"].get("usage")
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    prompt = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    completion = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def merge_usage_totals(current: dict, incoming: dict) -> dict:
    return {
        "prompt_tokens": max(int(current.get("prompt_tokens") or 0), int(incoming.get("prompt_tokens") or 0)),
        "completion_tokens": max(int(current.get("completion_tokens") or 0), int(incoming.get("completion_tokens") or 0)),
        "total_tokens": max(int(current.get("total_tokens") or 0), int(incoming.get("total_tokens") or 0)),
    }


async def collect_responses_stream(stream) -> dict:
    response_data = None
    output_text_parts = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    buffer = ""
    async for chunk in stream:
        buffer += chunk.decode("utf-8", "ignore")
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
            if not data_lines:
                continue
            data_text = "\n".join(data_lines)
            if data_text == "[DONE]":
                continue
            try:
                payload = json.loads(data_text)
            except json.JSONDecodeError:
                continue
            usage = merge_usage_totals(usage, extract_usage_from_responses_payload(payload))
            event_type = payload.get("type") if isinstance(payload, dict) else ""
            if event_type in {"response.output_text.delta", "response.text.delta"} and payload.get("delta"):
                output_text_parts.append(str(payload["delta"]))
            if event_type == "response.completed" and isinstance(payload.get("response"), dict):
                response_data = payload["response"]
    if response_data is None:
        response_data = {"id": f"resp_{int(datetime.utcnow().timestamp() * 1000)}", "output_text": "".join(output_text_parts), "usage": usage}
    elif "output_text" not in response_data and output_text_parts:
        response_data = dict(response_data)
        response_data["output_text"] = "".join(output_text_parts)
    if usage.get("total_tokens"):
        response_data = dict(response_data)
        response_data["usage"] = {
            "input_tokens": usage["prompt_tokens"],
            "output_tokens": usage["completion_tokens"],
            "total_tokens": usage["total_tokens"],
        }
    return response_data


async def add_account_usage(db: AsyncSession, account: OpenAIPlusAccount, usage: dict, success: bool):
    account.request_count = int(account.request_count or 0) + 1
    if success:
        account.success_count = int(account.success_count or 0) + 1
    else:
        account.error_count = int(account.error_count or 0) + 1
    account.prompt_tokens = int(account.prompt_tokens or 0) + int(usage.get("prompt_tokens") or 0)
    account.completion_tokens = int(account.completion_tokens or 0) + int(usage.get("completion_tokens") or 0)
    account.total_tokens = int(account.total_tokens or 0) + int(usage.get("total_tokens") or 0)
    account.updated_at = datetime.utcnow()
    await db.commit()


async def add_usage_log_by_id(
    account_id: int,
    model: Optional[str],
    endpoint: str,
    stream: bool,
    status_code: Optional[int],
    usage: dict,
    success: bool,
    error_message: Optional[str] = None,
):
    async with async_session_maker() as db:
        account = await db.get(OpenAIPlusAccount, account_id)
        log = OpenAIPlusUsageLog(
            account_id=account_id,
            account_email=account.email if account else None,
            model=model,
            endpoint=endpoint,
            stream=stream,
            success=success,
            status_code=status_code,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            error_message=error_message,
        )
        db.add(log)
        await db.commit()


async def add_account_usage_by_id(account_id: int, usage: dict, success: bool):
    async with async_session_maker() as db:
        account = await db.get(OpenAIPlusAccount, account_id)
        if account:
            await add_account_usage(db, account, usage, success)


async def tracked_responses_stream(stream, account_id: int, success: bool, model: Optional[str] = None, endpoint: str = "responses", status_code: Optional[int] = None):
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    buffer = ""
    try:
        async for chunk in stream:
            text = chunk.decode("utf-8", "ignore")
            buffer += text
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
                if data_lines:
                    data_text = "\n".join(data_lines)
                    if data_text != "[DONE]":
                        try:
                            payload = json.loads(data_text)
                            usage = merge_usage_totals(usage, extract_usage_from_responses_payload(payload))
                        except json.JSONDecodeError:
                            pass
            yield chunk
    finally:
        await add_account_usage_by_id(account_id, usage, success)
        await add_usage_log_by_id(account_id, model, endpoint, True, status_code, usage, success)


def claude_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
        elif isinstance(item, str):
            parts.append(item)
    return "\n".join(part for part in parts if part)


def claude_messages_to_responses_input(messages: list) -> list:
    input_items = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role") or "user"
        role = "assistant" if role == "assistant" else "user"
        content = message.get("content")
        if isinstance(content, str):
            content_items = [{"type": "input_text", "text": content}]
        else:
            content_items = []
            for item in content or []:
                if isinstance(item, dict) and item.get("type") == "text":
                    content_items.append({"type": "input_text", "text": item.get("text", "")})
                elif isinstance(item, dict) and item.get("type") == "image":
                    source = item.get("source") if isinstance(item.get("source"), dict) else {}
                    if source.get("type") == "base64" and source.get("data"):
                        media_type = source.get("media_type") or "image/png"
                        content_items.append({"type": "input_image", "image_url": f"data:{media_type};base64,{source['data']}"})
                    elif source.get("type") == "url" and source.get("url"):
                        content_items.append({"type": "input_image", "image_url": source["url"]})
        input_items.append({"role": role, "content": content_items})
    return input_items


def responses_to_claude_message(response_data: Any, model: str) -> Any:
    usage = extract_usage_from_responses_payload(response_data)
    message_id = response_data.get("id") if isinstance(response_data, dict) else None
    return {
        "id": message_id or f"msg_{int(datetime.utcnow().timestamp() * 1000)}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": extract_response_text(response_data)}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]},
    }


async def responses_stream_to_claude_stream(stream, model: str, account_id: int, success: bool, status_code: Optional[int] = None):
    message_id = f"msg_{int(datetime.utcnow().timestamp() * 1000)}"
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    buffer = ""
    yield build_sse({"type": "message_start", "message": {"id": message_id, "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}}, "message_start")
    yield build_sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}, "content_block_start")
    try:
        async for chunk in stream:
            buffer += chunk.decode("utf-8", "ignore")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                data_lines = [line[5:].strip() for line in block.splitlines() if line.startswith("data:")]
                if not data_lines:
                    continue
                data_text = "\n".join(data_lines)
                if data_text == "[DONE]":
                    continue
                try:
                    payload = json.loads(data_text)
                except json.JSONDecodeError:
                    continue
                usage = merge_usage_totals(usage, extract_usage_from_responses_payload(payload))
                event_type = payload.get("type") if isinstance(payload, dict) else ""
                if event_type in {"response.output_text.delta", "response.text.delta"} and payload.get("delta"):
                    yield build_sse({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": payload["delta"]}}, "content_block_delta")
                elif event_type == "response.completed":
                    yield build_sse({"type": "content_block_stop", "index": 0}, "content_block_stop")
                    yield build_sse({"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]}}, "message_delta")
                    yield build_sse({"type": "message_stop"}, "message_stop")
    finally:
        await add_account_usage_by_id(account_id, usage, success)
        await add_usage_log_by_id(account_id, model, "messages", True, status_code, usage, success)


