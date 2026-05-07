"""
提供商模型优先 Key 绑定模型
"""
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ProviderModelPriority(Base):
    """提供商模型优先 Key 配置"""
    __tablename__ = "provider_model_priorities"
    __table_args__ = (
        UniqueConstraint("provider", "model_normalized", name="uq_provider_model_priorities_provider_model"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    model_normalized: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    key_id: Mapped[int] = mapped_column(ForeignKey("api_keys.id"), nullable=False, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
