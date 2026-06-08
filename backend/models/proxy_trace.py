"""
代理调试追踪数据模型
"""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProxyTrace(Base):
    """代理调试追踪记录"""
    __tablename__ = "proxy_traces"
    __table_args__ = (
        Index("ix_proxy_traces_trace_id", "trace_id", unique=True),
        Index("ix_proxy_traces_created_at", "created_at"),
        Index("ix_proxy_traces_api_key_id_created_at", "api_key_id", "created_at"),
        Index("ix_proxy_traces_provider_created_at", "provider", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)

    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    key_name: Mapped[str] = mapped_column(String(100), nullable=True)
    requested_model: Mapped[str] = mapped_column(String(100), nullable=True)
    actual_model: Mapped[str] = mapped_column(String(100), nullable=True)

    status_code: Mapped[int] = mapped_column(Integer, nullable=True)
    result_status: Mapped[str] = mapped_column(String(20), default="success")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    upstream_latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    route_summary: Mapped[str] = mapped_column(Text, nullable=True)
    attempts: Mapped[str] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str] = mapped_column(Text, nullable=True)
