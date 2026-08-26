"""客户端智能协议路由与协议能力查询。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import urlsplit, urlunsplit

from config import export_config

OPENAI_CHAT = "openai_chat"
OPENAI_RESPONSES = "openai_responses"
ANTHROPIC_MESSAGES = "anthropic_messages"

DEFAULT_PROTOCOL_ORDER = {
    "claude_code": [ANTHROPIC_MESSAGES, OPENAI_RESPONSES, OPENAI_CHAT],
    "codex": [OPENAI_RESPONSES, OPENAI_CHAT, ANTHROPIC_MESSAGES],
    "deepseek_harness": [OPENAI_RESPONSES, OPENAI_CHAT, ANTHROPIC_MESSAGES],
    "workbuddy": [OPENAI_RESPONSES, OPENAI_CHAT, ANTHROPIC_MESSAGES],
    "unknown": [OPENAI_CHAT, OPENAI_RESPONSES, ANTHROPIC_MESSAGES],
}


class ProtocolRoutingService:
    def config(self) -> dict[str, Any]:
        value = export_config.get("intelligent_protocol_routing") or {}
        return value if isinstance(value, dict) else {}

    def enabled(self) -> bool:
        return bool(self.config().get("enabled", False))

    def identify_client(self, headers: dict[str, Any] | None) -> str:
        source = headers or {}
        user_agent = next((str(value or "") for key, value in source.items() if key.lower() == "user-agent"), "").lower()
        if "claude-code" in user_agent or "claude code" in user_agent:
            return "claude_code"
        if "codex" in user_agent:
            return "codex"
        if "deepseek" in user_agent and "harness" in user_agent:
            return "deepseek_harness"
        if "workbuddy" in user_agent:
            return "workbuddy"
        for rule in self.config().get("client_rules") or []:
            if not isinstance(rule, dict):
                continue
            marker = str(rule.get("user_agent_contains") or "").strip().lower()
            name = str(rule.get("client") or "").strip().lower()
            if marker and name and marker in user_agent:
                return name
        return "unknown"

    def protocol_chain(self, client_type: str) -> list[str]:
        return list(DEFAULT_PROTOCOL_ORDER.get(client_type, DEFAULT_PROTOCOL_ORDER["unknown"]))

    @staticmethod
    def normalize_base_url(base_url: str | None) -> str:
        value = str(base_url or "").strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            return value.lower()
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", ""))

    @staticmethod
    def normalize_model(model: str | None) -> str:
        return str(model or "").strip().lower()

    def override_protocols(self, provider: str, model: str) -> list[str]:
        provider = str(provider or "").strip().lower()
        model = self.normalize_model(model)
        for rule in self.config().get("provider_model_overrides") or []:
            if not isinstance(rule, dict):
                continue
            rule_provider = str(rule.get("provider") or "").strip().lower()
            rule_model = self.normalize_model(rule.get("model") or rule.get("model_id"))
            protocols = rule.get("protocols") or rule.get("protocol") or []
            if isinstance(protocols, str):
                protocols = [protocols]
            if (not rule_provider or rule_provider == provider) and (not rule_model or rule_model == model):
                return [str(item).strip() for item in protocols if str(item).strip()]
        return []

    async def supported_protocols(
        self,
        db: AsyncSession,
        *,
        provider: str,
        base_url: str,
        model: str,
        request_profile: str = "default",
    ) -> tuple[set[str], str]:
        from models import ProviderModelProtocolCapability

        now = datetime.utcnow()
        provider = str(provider or "").strip().lower()
        base_url = self.normalize_base_url(base_url)
        model = self.normalize_model(model)
        request_profile = str(request_profile or "default").strip().lower()
        query = select(ProviderModelProtocolCapability).where(
            ProviderModelProtocolCapability.provider == provider,
            ProviderModelProtocolCapability.base_url == base_url,
            ProviderModelProtocolCapability.model_id == model,
            ProviderModelProtocolCapability.request_profile == request_profile,
            ProviderModelProtocolCapability.supported == True,
        )
        rows = (await db.execute(query)).scalars().all()
        active = {row.protocol for row in rows if row.expires_at is None or row.expires_at > now}
        return active, "probe" if active else "unknown"

    async def record_capability(
        self,
        db: AsyncSession,
        *,
        provider: str,
        base_url: str,
        model: str,
        protocol: str,
        request_profile: str = "default",
        supported: bool = True,
        source: str = "probe",
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        from models import ProviderModelProtocolCapability

        ttl = max(1, int(self.config().get("capability_ttl_hours", 240) or 240))
        provider = str(provider or "").strip().lower()
        base_url = self.normalize_base_url(base_url)
        model = self.normalize_model(model)
        protocol = str(protocol or "").strip().lower()
        request_profile = str(request_profile or "default").strip().lower()
        from database import async_session_maker

        query = select(ProviderModelProtocolCapability).where(
            ProviderModelProtocolCapability.provider == provider,
            ProviderModelProtocolCapability.base_url == base_url,
            ProviderModelProtocolCapability.model_id == model,
            ProviderModelProtocolCapability.protocol == protocol,
            ProviderModelProtocolCapability.request_profile == request_profile,
        )
        values = {
            "supported": supported,
            "source": source,
            "status_code": status_code,
            "detail": detail,
            "checked_at": datetime.utcnow(),
            "expires_at": datetime.utcnow() + timedelta(hours=ttl),
        }
        async with async_session_maker() as write_db:
            row = (await write_db.execute(query)).scalar_one_or_none()
            if row is None:
                row = ProviderModelProtocolCapability(provider=provider or "", base_url=base_url or "", model_id=model, protocol=protocol, request_profile=request_profile, **values)
                write_db.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            await write_db.commit()

    async def list_capabilities(
        self,
        db: AsyncSession,
        *,
        provider: str = "",
        model: str = "",
        protocol: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Any], int]:
        from models import ProviderModelProtocolCapability

        filters = []
        if provider:
            filters.append(ProviderModelProtocolCapability.provider == provider.strip().lower())
        if model:
            filters.append(ProviderModelProtocolCapability.model_id == self.normalize_model(model))
        if protocol:
            filters.append(ProviderModelProtocolCapability.protocol == protocol.strip().lower())
        query = select(ProviderModelProtocolCapability).where(*filters).order_by(
            ProviderModelProtocolCapability.updated_at.desc(),
            ProviderModelProtocolCapability.id.desc(),
        )
        rows = (await db.execute(query.offset(offset).limit(limit))).scalars().all()
        count_query = select(func.count()).select_from(ProviderModelProtocolCapability).where(*filters)
        total = int((await db.execute(count_query)).scalar() or 0)
        return rows, total

    async def clear_capabilities(self, db: AsyncSession, *, ids: list[int] | None = None) -> int:
        from models import ProviderModelProtocolCapability

        query = delete(ProviderModelProtocolCapability)
        if ids:
            query = query.where(ProviderModelProtocolCapability.id.in_(ids))
        result = await db.execute(query)
        await db.commit()
        return int(result.rowcount or 0)


protocol_routing_service = ProtocolRoutingService()
