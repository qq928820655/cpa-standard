"""
模型广场数据模型
"""
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, Float, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModelCatalog(Base):
    """模型目录"""
    __tablename__ = "model_catalog"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    protocol: Mapped[str] = mapped_column(String(50), nullable=False, default="openai_chat")
    input_price: Mapped[float] = mapped_column(Float, default=0)
    output_price: Mapped[float] = mapped_column(Float, default=0)
    cache_read_price: Mapped[float] = mapped_column(Float, default=0)
    cache_write_price: Mapped[float] = mapped_column(Float, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_codex: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_claudecode: Mapped[bool] = mapped_column(Boolean, default=False)
    supports_gemini: Mapped[bool] = mapped_column(Boolean, default=False)
    aliases: Mapped[str] = mapped_column(Text, nullable=True)
    remark: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
