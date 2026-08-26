"""提供商模型协议能力记录。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProviderModelProtocolCapability(Base):
    """按提供商、地址和模型记录协议能力与来源。"""
    __tablename__ = "provider_model_protocol_capabilities"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "base_url",
            "model_id",
            "protocol",
            "request_profile",
            name="uq_provider_model_protocol_capability",
        ),
        Index("ix_provider_model_protocol_capability_lookup", "provider", "model_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    protocol: Mapped[str] = mapped_column(String(50), nullable=False)
    request_profile: Mapped[str] = mapped_column(String(30), nullable=False, default="default")
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="probe")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
