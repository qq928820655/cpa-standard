"""
提供商模型映射模型
"""
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, Text, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProviderModelMapping(Base):
    """提供商模型映射配置"""
    __tablename__ = "provider_model_mappings"
    __table_args__ = (
        UniqueConstraint("provider", "provider_model_normalized", name="uq_provider_model_mappings_provider_model"),
        Index("ix_provider_model_mappings_real_model_normalized", "real_model_normalized"),
        Index("ix_provider_model_mappings_provider_enabled", "provider", "enabled"),
        Index("ix_provider_model_mappings_provider_model_normalized", "provider_model_normalized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    provider_model: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_model_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    real_model: Mapped[str] = mapped_column(String(200), nullable=False)
    real_model_normalized: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    remark: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
