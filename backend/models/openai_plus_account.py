"""
OpenAI Plus account model
"""
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class OpenAIPlusAccount(Base):
    """OpenAI Plus OAuth account"""
    __tablename__ = "openai_plus_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    account_id: Mapped[str] = mapped_column(String(100), nullable=True, index=True)
    chatgpt_user_id: Mapped[str] = mapped_column(String(150), nullable=True)
    plan_type: Mapped[str] = mapped_column(String(50), nullable=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=True)
    id_token: Mapped[str] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    websockets: Mapped[bool] = mapped_column(Boolean, default=False)
    proxy_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    last_check_status: Mapped[str] = mapped_column(String(20), nullable=True)
    last_check_message: Mapped[str] = mapped_column(Text, nullable=True)
    last_check_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
