"""
Grok account pool service
"""
import base64
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import GrokAccount, GrokUsageLog

GROK_OAUTH_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
GROK_API_KEY_BASE_URL = "https://api.x.ai/v1"
GROK_CLI_VERSION = "0.2.93"
GROK_UPSTREAM_USER_AGENT = "cpa-grok/1.0"
GROK_UNIFIED_API_KEY = "cpa-grok-unified"
XAI_OAUTH_CLIENT_ID = os.environ.get("XAI_OAUTH_CLIENT_ID") or "b1a00492-073a-47ea-816f-4c329264a828"
XAI_OAUTH_SCOPE = os.environ.get("XAI_OAUTH_SCOPE") or "openid profile email offline_access grok-cli:access api:access"
XAI_OAUTH_REDIRECT_URI = os.environ.get("XAI_OAUTH_REDIRECT_URI") or "http://127.0.0.1:56121/callback"
XAI_OAUTH_AUTHORIZE_URL = os.environ.get("XAI_OAUTH_AUTHORIZE_URL") or "https://auth.x.ai/oauth2/authorize"
XAI_OAUTH_TOKEN_URL = os.environ.get("XAI_OAUTH_TOKEN_URL") or "https://auth.x.ai/oauth2/token"


class GrokAccountService:
    """独立 Grok / xAI 账户池服务"""

    def __init__(self):
        self._index = 0
        self._cooldowns: dict[int, datetime] = {}
        self._oauth_sessions: dict[str, dict[str, Any]] = {}

    def create_oauth_auth_url(self, *, redirect_uri: Optional[str] = None) -> dict[str, str]:
        state = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        effective_redirect_uri = (redirect_uri or XAI_OAUTH_REDIRECT_URI).strip()
        self._oauth_sessions[state] = {
            "code_verifier": verifier,
            "redirect_uri": effective_redirect_uri,
            "created_at": datetime.utcnow(),
        }
        from urllib.parse import urlencode
        query = urlencode({
            "response_type": "code",
            "client_id": XAI_OAUTH_CLIENT_ID,
            "redirect_uri": effective_redirect_uri,
            "scope": XAI_OAUTH_SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return {"auth_url": f"{XAI_OAUTH_AUTHORIZE_URL}?{query}", "state": state, "code_verifier": verifier, "redirect_uri": effective_redirect_uri}

    async def exchange_oauth_code(self, code_or_url: str, *, state: Optional[str] = None, redirect_uri: Optional[str] = None, code_verifier: Optional[str] = None) -> dict[str, Any]:
        raw = (code_or_url or "").strip()
        parsed_code = raw
        parsed_state = state
        if "?" in raw or raw.startswith("http"):
            parsed = urlparse(raw)
            params = parse_qs(parsed.query)
            parsed_code = (params.get("code") or [""])[0]
            parsed_state = parsed_state or (params.get("state") or [""])[0]
        if not parsed_code:
            raise ValueError("缺少 OAuth code")

        session = self._oauth_sessions.get(parsed_state or "") if parsed_state else None
        verifier = code_verifier or (session or {}).get("code_verifier")
        effective_redirect_uri = redirect_uri or (session or {}).get("redirect_uri") or XAI_OAUTH_REDIRECT_URI
        if not verifier:
            raise ValueError("缺少 code_verifier，请先生成授权链接或手工提供")

        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            response = await client.post(
                XAI_OAUTH_TOKEN_URL,
                headers={"User-Agent": "cpa-grok-oauth/1.0"},
                data={
                    "grant_type": "authorization_code",
                    "client_id": XAI_OAUTH_CLIENT_ID,
                    "code": parsed_code,
                    "redirect_uri": effective_redirect_uri,
                    "code_verifier": verifier,
                },
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ValueError(f"Grok OAuth code 交换失败 HTTP {response.status_code}: {response.text[:500]}")
        token_data = response.json()
        if parsed_state:
            self._oauth_sessions.pop(parsed_state, None)
        return token_data

    def parse_session_payload(self, content: str) -> dict[str, Any]:
        text = (content or "").strip()
        if not text:
            raise ValueError("session 内容不能为空")

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}
            for line in text.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                data[key.strip()] = value.strip()

        if not isinstance(data, dict):
            raise ValueError("session 格式无效")
        return data

    def build_account_payload(
        self,
        *,
        name: Optional[str],
        account_type: str,
        session_content: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> dict[str, Any]:
        account_type_value = (account_type or "oauth").strip().lower()
        if account_type_value not in {"oauth", "api_key"}:
            raise ValueError("账号类型仅支持 oauth 或 api_key")

        payload = {
            "name": (name or "").strip() or None,
            "account_type": account_type_value,
            "base_url": (base_url or "").strip() or (GROK_OAUTH_BASE_URL if account_type_value == "oauth" else GROK_API_KEY_BASE_URL),
            "proxy_key": f"grok-{secrets.token_urlsafe(18)}",
        }

        if account_type_value == "api_key":
            api_key_value = (api_key or "").strip()
            if not api_key_value:
                raise ValueError("API Key 账号必须填写 api_key")
            payload["api_key"] = api_key_value
            return payload

        session_data = self.parse_session_payload(session_content or "")
        access_token = session_data.get("access_token") or session_data.get("accessToken")
        refresh_token = session_data.get("refresh_token") or session_data.get("refreshToken")
        if not access_token and not refresh_token:
            raise ValueError("OAuth session 至少需要 access_token 或 refresh_token")

        expires_at = None
        raw_expired = session_data.get("expired")
        raw_expires_at = session_data.get("expires_at") or session_data.get("expiresAt")
        if raw_expires_at or (raw_expired and str(raw_expired).lower() not in {"true", "false"}):
            try:
                expires_at_value = raw_expires_at or raw_expired
                expires_at = datetime.fromisoformat(str(expires_at_value).replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                expires_at = None
        elif session_data.get("expires_in"):
            try:
                expires_in = int(session_data.get("expires_in"))
                last_refresh = session_data.get("last_refresh") or session_data.get("lastRefresh")
                if last_refresh:
                    try:
                        refreshed_at = datetime.fromisoformat(str(last_refresh).replace("Z", "+00:00")).replace(tzinfo=None)
                    except ValueError:
                        refreshed_at = datetime.fromtimestamp(float(last_refresh))
                    expires_at = refreshed_at + timedelta(seconds=expires_in)
                else:
                    expires_at = datetime.utcnow() + timedelta(seconds=expires_in)
            except (TypeError, ValueError):
                expires_at = None
        if raw_expired is True or str(raw_expired).lower() == "true":
            expires_at = datetime.utcnow() - timedelta(seconds=1)

        if not (base_url or "").strip() and session_data.get("base_url"):
            session_base_url = str(session_data.get("base_url")).strip()
            auth_kind = str(session_data.get("auth_kind") or "oauth").strip().lower()
            using_api = self._session_bool(session_data, "using_api")
            if account_type_value == "oauth" and auth_kind == "oauth" and not using_api and session_base_url.rstrip("/") == GROK_API_KEY_BASE_URL:
                payload["base_url"] = GROK_OAUTH_BASE_URL
            else:
                payload["base_url"] = session_base_url

        payload.update({
            "email": session_data.get("email"),
            "api_key": None,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": session_data.get("token_type") or session_data.get("tokenType") or "Bearer",
            "expires_at": expires_at,
            "raw_session": json.dumps(session_data, ensure_ascii=False),
            "subscription_tier": session_data.get("subscription_tier") or session_data.get("subscriptionTier"),
            "entitlement_status": session_data.get("entitlement_status") or session_data.get("entitlementStatus"),
        })
        return payload

    async def create_account(self, db: AsyncSession, payload: dict[str, Any]) -> GrokAccount:
        account = GrokAccount(**payload)
        db.add(account)
        await db.commit()
        await db.refresh(account)
        return account

    def _prune_cooldowns(self):
        now = datetime.utcnow()
        expired = [account_id for account_id, until in self._cooldowns.items() if until <= now]
        for account_id in expired:
            self._cooldowns.pop(account_id, None)

    def set_account_cooldown(self, account_id: int, seconds: int):
        if seconds > 0:
            self._cooldowns[account_id] = datetime.utcnow() + timedelta(seconds=seconds)

    def is_account_available(self, account: GrokAccount) -> bool:
        if not account or account.disabled:
            return False
        self._prune_cooldowns()
        return account.id not in self._cooldowns

    def is_unified_proxy_key(self, proxy_key: str) -> bool:
        return (proxy_key or "").strip() == GROK_UNIFIED_API_KEY

    def _raw_session_dict(self, account: GrokAccount) -> dict[str, Any]:
        try:
            data = json.loads(account.raw_session or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _session_bool(self, data: dict[str, Any], key: str, default: bool = False) -> bool:
        value = data.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    def _is_oauth_cli_chat(self, account: GrokAccount) -> bool:
        if account.account_type != "oauth":
            return False
        data = self._raw_session_dict(account)
        auth_kind = str(data.get("auth_kind") or "oauth").strip().lower()
        return auth_kind == "oauth" and not self._session_bool(data, "using_api")

    def _get_token_endpoint(self, account: GrokAccount) -> str:
        data = self._raw_session_dict(account)
        return str(data.get("token_endpoint") or XAI_OAUTH_TOKEN_URL).strip()

    async def get_account_by_proxy_key(self, db: AsyncSession, proxy_key: str) -> Optional[GrokAccount]:
        if not proxy_key:
            return None
        result = await db.execute(select(GrokAccount).where(GrokAccount.proxy_key == proxy_key))
        return result.scalar_one_or_none()

    async def get_next_available_account(self, db: AsyncSession, excluded_ids: Optional[set[int]] = None) -> Optional[GrokAccount]:
        excluded = excluded_ids or set()
        result = await db.execute(select(GrokAccount).where(GrokAccount.disabled == False).order_by(GrokAccount.id))
        accounts = [item for item in result.scalars().all() if item.id not in excluded and self.is_account_available(item)]
        if not accounts:
            return None
        index = self._index % len(accounts)
        self._index = (index + 1) % len(accounts)
        return accounts[index]

    def build_headers(
        self,
        account: GrokAccount,
        *,
        stream: bool = False,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "Connection": "Keep-Alive",
        }
        if account.account_type == "api_key":
            headers["Authorization"] = f"Bearer {account.api_key}"
        else:
            token = (account.access_token or "").strip()
            if not token:
                raise ValueError("Grok OAuth access_token 为空，请先刷新或重新导入账号")
            headers["Authorization"] = f"Bearer {token}"
            if self._is_oauth_cli_chat(account):
                headers["X-XAI-Token-Auth"] = "xai-grok-cli"
                headers["x-grok-client-version"] = GROK_CLI_VERSION
                headers["User-Agent"] = f"xai-grok-workspace/{GROK_CLI_VERSION}"
            else:
                headers["User-Agent"] = GROK_UPSTREAM_USER_AGENT
        raw_headers = self._raw_session_dict(account).get("headers") if account.account_type == "oauth" else None
        if isinstance(raw_headers, dict):
            for name, value in raw_headers.items():
                header_name = str(name or "").strip()
                header_value = str(value or "").strip()
                if header_name and header_value and header_name.lower() != "host":
                    headers[header_name] = header_value
        # 客户端透传的缓存亲和头优先于 session 内置头
        if isinstance(extra_headers, dict):
            for name, value in extra_headers.items():
                header_name = str(name or "").strip()
                header_value = str(value or "").strip()
                if header_name and header_value:
                    headers[header_name] = header_value
        return headers

    @staticmethod
    def extract_cache_affinity(request_headers: Optional[dict] = None, body: Optional[dict] = None) -> tuple[dict[str, str], dict[str, Any]]:
        """
        提取 Grok 缓存亲和参数：
        - Chat: x-grok-conv-id 请求头
        - Responses: prompt_cache_key 字段；缺失时用 x-grok-conv-id 回填
        """
        source_headers = request_headers or {}
        conv_id = ""
        for key, value in source_headers.items():
            if str(key or "").lower() == "x-grok-conv-id":
                conv_id = str(value or "").strip()
                break

        payload = dict(body or {})
        prompt_cache_key = str(payload.get("prompt_cache_key") or "").strip()
        if not prompt_cache_key and conv_id:
            payload["prompt_cache_key"] = conv_id

        extra_headers: dict[str, str] = {}
        if conv_id:
            extra_headers["x-grok-conv-id"] = conv_id
        return extra_headers, payload

    def get_base_url(self, account: GrokAccount) -> str:
        if account.account_type == "api_key":
            base_url = (account.base_url or GROK_API_KEY_BASE_URL).rstrip("/")
        elif self._is_oauth_cli_chat(account):
            configured_url = (account.base_url or "").strip().rstrip("/")
            base_url = GROK_OAUTH_BASE_URL if not configured_url or configured_url == GROK_API_KEY_BASE_URL else configured_url
        else:
            base_url = (account.base_url or GROK_API_KEY_BASE_URL).rstrip("/")
        parsed = urlparse(base_url)
        if parsed.scheme != "https" or parsed.hostname not in {"api.x.ai", "cli-chat-proxy.grok.com"}:
            raise ValueError("Grok 上游地址仅允许 api.x.ai 或 cli-chat-proxy.grok.com")
        return base_url

    async def refresh_account_if_needed(self, db: AsyncSession, account: GrokAccount, *, force: bool = False) -> GrokAccount:
        if account.account_type != "oauth":
            return account
        refresh_token = (account.refresh_token or "").strip()
        expires_at = account.expires_at
        needs_refresh = force or expires_at is None or expires_at <= datetime.utcnow() + timedelta(minutes=5)
        if not needs_refresh:
            return account
        if not refresh_token:
            if expires_at and expires_at > datetime.utcnow() and account.access_token:
                return account
            raise ValueError("Grok access_token 已过期且缺少 refresh_token")

        token_endpoint = self._get_token_endpoint(account)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30)) as client:
            response = await client.post(
                token_endpoint,
                headers={"User-Agent": "cpa-grok-oauth/1.0"},
                data={
                    "grant_type": "refresh_token",
                    "client_id": XAI_OAUTH_CLIENT_ID,
                    "refresh_token": refresh_token,
                },
            )
        if response.status_code < 200 or response.status_code >= 300:
            raise ValueError(f"Grok token 刷新失败 HTTP {response.status_code}: {response.text[:500]}")
        try:
            token_data = response.json()
        except ValueError as exc:
            raise ValueError("Grok token 刷新响应不是有效 JSON") from exc

        access_token = str(token_data.get("access_token") or "").strip()
        if not access_token:
            raise ValueError("Grok token 刷新响应缺少 access_token")
        account.access_token = access_token
        account.refresh_token = str(token_data.get("refresh_token") or refresh_token).strip()
        account.token_type = str(token_data.get("token_type") or account.token_type or "Bearer")
        try:
            expires_in = int(token_data.get("expires_in") or 3600)
        except (TypeError, ValueError):
            expires_in = 3600
        now = datetime.utcnow()
        account.expires_at = now + timedelta(seconds=max(expires_in, 60))
        session_data = self._raw_session_dict(account)
        session_data.update({
            "access_token": account.access_token,
            "refresh_token": account.refresh_token,
            "token_type": account.token_type,
            "expires_in": expires_in,
            "expired": account.expires_at.isoformat() + "Z",
            "last_refresh": now.isoformat() + "Z",
            "token_endpoint": token_endpoint,
        })
        if token_data.get("id_token"):
            session_data["id_token"] = token_data.get("id_token")
        account.raw_session = json.dumps(session_data, ensure_ascii=False)
        account.updated_at = now
        await db.commit()
        await db.refresh(account)
        return account

    def sanitize_responses_body(self, body: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(body or {})
        model = str(sanitized.get("model") or "grok-4.5")
        sanitized["model"] = model
        for field in ["prompt_cache_retention", "safety_identifier", "external_web_access"]:
            sanitized.pop(field, None)
        if model.lower().split("/")[-1] == "grok-4.5":
            for field in ["presence_penalty", "presencePenalty", "frequency_penalty", "frequencyPenalty", "stop"]:
                sanitized.pop(field, None)
        tools = sanitized.get("tools")
        if isinstance(tools, list):
            supported = {"code_execution", "code_interpreter", "collections_search", "file_search", "function", "mcp", "shell", "web_search", "x_search"}
            filtered_tools = [item for item in tools if isinstance(item, dict) and item.get("type") in supported]
            if filtered_tools:
                sanitized["tools"] = filtered_tools
            else:
                sanitized.pop("tools", None)
                sanitized.pop("tool_choice", None)
        return sanitized

    async def forward_responses(
        self,
        account: GrokAccount,
        body: dict[str, Any],
        *,
        stream: bool,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> tuple[int, dict, Any]:
        payload = self.sanitize_responses_body(body)
        url = f"{self.get_base_url(account)}/responses"
        headers = self.build_headers(account, stream=stream, extra_headers=extra_headers)
        if stream:
            client = httpx.AsyncClient(timeout=httpx.Timeout(300))
            response = None
            try:
                request = client.build_request("POST", url, headers=headers, json=payload)
                response = await client.send(request, stream=True)
                response_headers = {"content-type": response.headers.get("content-type", "text/event-stream")}

                async def generator() -> AsyncIterator[bytes]:
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
        async with httpx.AsyncClient(timeout=httpx.Timeout(300)) as client:
            response = await client.post(url, headers=headers, json=payload)
        try:
            data = response.json()
        except ValueError:
            data = {"error": {"message": response.text}}
        return response.status_code, {}, data

    async def tracked_responses_stream(
        self,
        stream,
        model: Optional[str],
        endpoint: str,
        db: AsyncSession,
        account: GrokAccount,
        success: bool,
        status_code: Optional[int] = None,
    ):
        from services import openai_plus_service
        start_time = time.monotonic()
        usage = {"prompt_tokens": 0, "cache_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        final_success = success
        error_message = None
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
                                usage = openai_plus_service.merge_usage_totals(usage, openai_plus_service.extract_usage_from_responses_payload(payload))
                                stream_error = openai_plus_service.extract_responses_stream_error(payload)
                                if stream_error:
                                    final_success = False
                                    error_message = stream_error
                            except json.JSONDecodeError:
                                pass
                    yield (block + "\n\n").encode("utf-8")
            if buffer:
                yield buffer.encode("utf-8")
        except Exception as exc:
            final_success = False
            error_message = openai_plus_service.format_stream_exception(exc)
            raise
        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            await self.add_account_usage(db, account, usage, final_success)
            await self.add_usage_log(db, account, usage, model=model, endpoint=endpoint, stream=True, status_code=status_code, success=final_success, error_message=error_message, latency_ms=latency_ms)

    async def responses_stream_to_chat_stream(
        self,
        stream,
        model: str,
        db: AsyncSession,
        account: GrokAccount,
        success: bool,
        status_code: Optional[int] = None,
        endpoint: str = "chat.completions",
    ):
        from services import openai_plus_service
        start_time = time.monotonic()
        chat_id = f"chatcmpl_{int(datetime.utcnow().timestamp() * 1000)}"
        created = int(datetime.utcnow().timestamp())
        buffer = ""
        usage = {"prompt_tokens": 0, "cache_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        final_success = success
        error_message = None
        completed_seen = False
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
                    usage = openai_plus_service.merge_usage_totals(usage, openai_plus_service.extract_usage_from_responses_payload(payload))
                    stream_error = openai_plus_service.extract_responses_stream_error(payload)
                    if stream_error:
                        final_success = False
                        error_message = stream_error
                        yield openai_plus_service.build_sse({"error": {"message": stream_error, "type": "upstream_stream_error"}})
                        yield b"data: [DONE]\n\n"
                        return
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
                        completed_seen = True
                        yield openai_plus_service.build_sse({"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}], "usage": usage or None})
                        yield b"data: [DONE]\n\n"
                        continue
                    if delta_text:
                        yield openai_plus_service.build_sse({"id": chat_id, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": None}]})
            if not completed_seen and final_success:
                final_success = False
                error_message = "stream closed before response.completed"
                yield openai_plus_service.build_sse({"error": {"message": error_message, "type": "incomplete_stream"}})
                yield b"data: [DONE]\n\n"
            elif buffer.strip():
                yield b"data: [DONE]\n\n"
        except Exception as exc:
            final_success = False
            error_message = openai_plus_service.format_stream_exception(exc)
            yield openai_plus_service.build_sse({"error": {"message": error_message, "type": "stream_error"}})
            yield b"data: [DONE]\n\n"
        finally:
            latency_ms = int((time.monotonic() - start_time) * 1000)
            await self.add_account_usage(db, account, usage, final_success)
            await self.add_usage_log(db, account, usage, model=model, endpoint=endpoint, stream=True, status_code=status_code, success=final_success, error_message=error_message, latency_ms=latency_ms)

    async def responses_stream_to_claude_stream(
        self,
        stream,
        model: str,
        db: AsyncSession,
        account: GrokAccount,
        success: bool,
        status_code: Optional[int] = None,
        endpoint: str = "messages",
    ):
        from services import openai_plus_service
        start_time = time.monotonic()
        message_id = f"msg_{int(datetime.utcnow().timestamp() * 1000)}"
        usage = {"prompt_tokens": 0, "cache_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        buffer = ""
        final_success = success
        error_message = None
        text_block_open = True
        content_index = 0
        tool_used = False

        if not success:
            error_parts = []
            try:
                async for chunk in stream:
                    text = chunk.decode("utf-8", "ignore")
                    error_parts.append(text)
                    for block in text.split("\n\n"):
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
                        usage = openai_plus_service.merge_usage_totals(usage, openai_plus_service.extract_usage_from_responses_payload(payload))
                        stream_error = openai_plus_service.extract_responses_stream_error(payload)
                        if stream_error:
                            error_message = stream_error
            except Exception as exc:
                error_message = openai_plus_service.format_stream_exception(exc)
            if not error_message:
                error_message = "".join(error_parts).strip()[:500] or f"upstream HTTP {status_code}"
            yield openai_plus_service.build_sse({"type": "error", "error": {"type": "upstream_error", "message": error_message}}, "error")
            latency_ms = int((time.monotonic() - start_time) * 1000)
            await self.add_account_usage(db, account, usage, False)
            await self.add_usage_log(db, account, usage, model=model, endpoint=endpoint, stream=True, status_code=status_code, success=False, error_message=error_message, latency_ms=latency_ms)
            return

        yield openai_plus_service.build_sse({"type": "message_start", "message": {"id": message_id, "type": "message", "role": "assistant", "model": model, "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}}, "message_start")
        yield openai_plus_service.build_sse({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}, "content_block_start")
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
                    usage = openai_plus_service.merge_usage_totals(usage, openai_plus_service.extract_usage_from_responses_payload(payload))
                    stream_error = openai_plus_service.extract_responses_stream_error(payload)
                    if stream_error:
                        final_success = False
                        error_message = stream_error
                        yield openai_plus_service.build_sse({"type": "error", "error": {"type": "upstream_stream_error", "message": stream_error}}, "error")
                        return
                    event_type = payload.get("type") if isinstance(payload, dict) else ""
                    if event_type in {"response.output_text.delta", "response.text.delta"} and payload.get("delta"):
                        yield openai_plus_service.build_sse({"type": "content_block_delta", "index": content_index, "delta": {"type": "text_delta", "text": payload["delta"]}}, "content_block_delta")
                    elif event_type == "response.output_item.done" and isinstance(payload.get("item"), dict):
                        item = payload["item"]
                        if item.get("type") == "function_call":
                            if text_block_open:
                                yield openai_plus_service.build_sse({"type": "content_block_stop", "index": content_index}, "content_block_stop")
                                text_block_open = False
                                content_index += 1
                            arguments = item.get("arguments") or "{}"
                            try:
                                tool_input = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
                            except json.JSONDecodeError:
                                tool_input = {"arguments": arguments}
                            yield openai_plus_service.build_sse({"type": "content_block_start", "index": content_index, "content_block": {"type": "tool_use", "id": item.get("call_id") or item.get("id") or f"toolu_{content_index}", "name": item.get("name") or "tool", "input": {}}}, "content_block_start")
                            yield openai_plus_service.build_sse({"type": "content_block_delta", "index": content_index, "delta": {"type": "input_json_delta", "partial_json": json.dumps(tool_input, ensure_ascii=False)}}, "content_block_delta")
                            yield openai_plus_service.build_sse({"type": "content_block_stop", "index": content_index}, "content_block_stop")
                            tool_used = True
                            content_index += 1
                    elif event_type == "response.completed":
                        if text_block_open:
                            yield openai_plus_service.build_sse({"type": "content_block_stop", "index": content_index}, "content_block_stop")
                            text_block_open = False
                        stop_reason = "tool_use" if tool_used else "end_turn"
                        yield openai_plus_service.build_sse({"type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None}, "usage": {"input_tokens": usage["prompt_tokens"], "output_tokens": usage["completion_tokens"]}}, "message_delta")
                        yield openai_plus_service.build_sse({"type": "message_stop"}, "message_stop")
        except Exception as exc:
            final_success = False
            error_message = openai_plus_service.format_stream_exception(exc)
            yield openai_plus_service.build_sse({"type": "error", "error": {"type": "stream_error", "message": error_message}}, "error")
        finally:
            if text_block_open:
                try:
                    yield openai_plus_service.build_sse({"type": "content_block_stop", "index": content_index}, "content_block_stop")
                    yield openai_plus_service.build_sse({"type": "message_stop"}, "message_stop")
                except Exception:
                    pass
            latency_ms = int((time.monotonic() - start_time) * 1000)
            await self.add_account_usage(db, account, usage, final_success)
            await self.add_usage_log(db, account, usage, model=model, endpoint=endpoint, stream=True, status_code=status_code, success=final_success, error_message=error_message, latency_ms=latency_ms)

    async def add_usage_log(
        self,
        db: AsyncSession,
        account: GrokAccount,
        usage: dict[str, int],
        *,
        model: Optional[str],
        endpoint: str,
        stream: bool,
        status_code: Optional[int],
        success: bool,
        error_message: Optional[str] = None,
        latency_ms: int = 0,
    ):
        log = GrokUsageLog(
            account_id=account.id if account else None,
            account_email=getattr(account, "email", None),
            account_type=getattr(account, "account_type", None),
            model=model,
            endpoint=endpoint,
            stream=stream,
            success=success,
            status_code=status_code,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            cache_tokens=int(usage.get("cache_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            total_tokens=int(usage.get("total_tokens") or 0),
            latency_ms=max(int(latency_ms or 0), 0),
            error_message=error_message,
        )
        db.add(log)
        await db.commit()

    async def add_account_usage(self, db: AsyncSession, account: GrokAccount, usage: dict[str, int], success: bool):
        account.request_count = int(account.request_count or 0) + 1
        if success:
            account.success_count = int(account.success_count or 0) + 1
        else:
            account.error_count = int(account.error_count or 0) + 1
        account.prompt_tokens = int(account.prompt_tokens or 0) + int(usage.get("prompt_tokens") or 0)
        account.cache_tokens = int(account.cache_tokens or 0) + int(usage.get("cache_tokens") or 0)
        account.completion_tokens = int(account.completion_tokens or 0) + int(usage.get("completion_tokens") or 0)
        account.total_tokens = int(account.total_tokens or 0) + int(usage.get("total_tokens") or 0)
        account.updated_at = datetime.utcnow()
        await db.commit()

    async def check_account(self, account: GrokAccount, model: str = "grok-4.5") -> tuple[str, str]:
        body = {"model": model, "input": "Reply with cpa-grok-ok", "stream": False}
        try:
            status_code, _, data = await self.forward_responses(account, body, stream=False)
            if 200 <= status_code < 300:
                return "ok", "连接测试成功"
            return "error", f"HTTP {status_code}: {str(data)[:500]}"
        except Exception as exc:
            return "error", str(exc)


grok_account_service = GrokAccountService()
