"""
代理调试追踪服务
"""
import json
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import export_config
from models import ProxyTrace

MAX_TEXT_LENGTH = 500
MAX_JSON_TEXT_LENGTH = 12000


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _coerce_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return min(maximum, max(minimum, parsed))


def _trim_text(value: Any, limit: int = MAX_TEXT_LENGTH) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _json_dumps(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= MAX_JSON_TEXT_LENGTH:
        return text
    return text[:MAX_JSON_TEXT_LENGTH] + "..."


def normalize_trace_config(data: Optional[dict] = None) -> dict:
    raw = data if isinstance(data, dict) else export_config
    return {
        "proxy_trace_enabled": _coerce_bool(raw.get("proxy_trace_enabled"), False),
        "proxy_trace_retention_hours": _coerce_int(raw.get("proxy_trace_retention_hours"), 24, 1, 168),
        "proxy_trace_sample_rate": _coerce_float(raw.get("proxy_trace_sample_rate"), 1.0, 0.0, 1.0),
        "proxy_trace_only_failures": _coerce_bool(raw.get("proxy_trace_only_failures"), False),
        "proxy_trace_target_provider": _trim_text(raw.get("proxy_trace_target_provider"), 100) or "",
        "proxy_trace_target_model": _trim_text(raw.get("proxy_trace_target_model"), 100) or "",
    }


@dataclass
class ProxyTraceContext:
    trace_id: str
    requested_model: Optional[str] = None
    actual_model: Optional[str] = None
    provider: Optional[str] = None
    key_name: Optional[str] = None
    user_id: Optional[int] = None
    route_summary: dict[str, Any] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)

    def set_route(self, key: str, value: Any) -> None:
        self.route_summary[key] = value

    def add_event(self, event: str, **kwargs: Any) -> None:
        events = self.route_summary.setdefault("events", [])
        events.append({"event": event, **kwargs})

    def add_attempt(self, **kwargs: Any) -> None:
        safe = {key: _trim_text(value) if isinstance(value, str) else value for key, value in kwargs.items()}
        self.attempts.append(safe)


class ProxyTraceService:
    def is_enabled(self) -> bool:
        return normalize_trace_config()["proxy_trace_enabled"]

    def create_context(
        self,
        *,
        requested_model: Optional[str] = None,
        actual_model: Optional[str] = None,
        provider: Optional[str] = None,
        providers: Optional[list[str]] = None,
        key_name: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Optional[ProxyTraceContext]:
        config = normalize_trace_config()
        if not config["proxy_trace_enabled"]:
            return None

        target_provider = config["proxy_trace_target_provider"].lower()
        provider_values = [item.lower() for item in ([provider] if provider else providers or []) if item]
        if target_provider and target_provider not in provider_values:
            return None

        target_model = config["proxy_trace_target_model"].lower()
        model_values = [item.lower() for item in (requested_model, actual_model) if item]
        if target_model and all(target_model not in item for item in model_values):
            return None

        sample_rate = config["proxy_trace_sample_rate"]
        if sample_rate <= 0 or random.random() > sample_rate:
            return None

        ctx = ProxyTraceContext(
            trace_id=uuid.uuid4().hex,
            requested_model=_trim_text(requested_model, 100),
            actual_model=_trim_text(actual_model, 100),
            provider=_trim_text(provider, 100),
            key_name=_trim_text(key_name, 100),
            user_id=user_id,
        )
        ctx.set_route("requested_model", ctx.requested_model)
        ctx.set_route("actual_model", ctx.actual_model)
        ctx.set_route("provider", ctx.provider)
        ctx.set_route("providers", providers or [])
        ctx.set_route("key_name", ctx.key_name)
        return ctx

    async def save(
        self,
        db: AsyncSession,
        ctx: Optional[ProxyTraceContext],
        *,
        api_key: Any = None,
        status_code: Optional[int] = None,
        result_status: str = "success",
        latency_ms: int = 0,
        upstream_latency_ms: int = 0,
        error_summary: Any = None,
    ) -> None:
        if ctx is None:
            return
        config = normalize_trace_config()
        if config["proxy_trace_only_failures"] and result_status == "success":
            return

        provider = _trim_text(getattr(api_key, "provider", None) or ctx.provider, 100)
        key_name = _trim_text(getattr(api_key, "name", None) or ctx.key_name, 100)
        api_key_id = getattr(api_key, "id", None)

        item = ProxyTrace(
            trace_id=ctx.trace_id,
            created_at=ctx.started_at,
            user_id=ctx.user_id,
            api_key_id=api_key_id,
            provider=provider,
            key_name=key_name,
            requested_model=ctx.requested_model,
            actual_model=ctx.actual_model,
            status_code=status_code,
            result_status=result_status,
            latency_ms=max(0, int(latency_ms or 0)),
            upstream_latency_ms=max(0, int(upstream_latency_ms or 0)),
            route_summary=_json_dumps(ctx.route_summary),
            attempts=_json_dumps(ctx.attempts),
            error_summary=_trim_text(error_summary),
        )
        db.add(item)
        await db.commit()

    async def cleanup_expired(self, db: AsyncSession) -> int:
        config = normalize_trace_config()
        cutoff = datetime.utcnow() - timedelta(hours=config["proxy_trace_retention_hours"])
        result = await db.execute(delete(ProxyTrace).where(ProxyTrace.created_at < cutoff))
        await db.commit()
        return int(result.rowcount or 0)

    async def list_traces(self, db: AsyncSession, *, limit: int = 50, offset: int = 0) -> list[ProxyTrace]:
        result = await db.execute(
            select(ProxyTrace)
            .order_by(ProxyTrace.created_at.desc())
            .offset(max(0, offset))
            .limit(min(200, max(1, limit)))
        )
        return list(result.scalars().all())

    async def get_trace(self, db: AsyncSession, trace_id: str) -> Optional[ProxyTrace]:
        result = await db.execute(select(ProxyTrace).where(ProxyTrace.trace_id == trace_id))
        return result.scalar_one_or_none()


proxy_trace_service = ProxyTraceService()
