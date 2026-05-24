"""
Content guard event model.
"""
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ContentGuardEvent(Base):
    """Content safety event."""
    __tablename__ = "content_guard_events"
    __table_args__ = (
        Index("ix_content_guard_events_created_at", "created_at"),
        Index("ix_content_guard_events_api_key_id", "api_key_id"),
        Index("ix_content_guard_events_provider", "provider"),
        Index("ix_content_guard_events_category", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=False)
    key_name: Mapped[str] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=True)
    path: Mapped[str] = mapped_column(String(300), nullable=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=True)
    snippet: Mapped[str] = mapped_column(Text, nullable=True)
    explanation: Mapped[str] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False, default="recorded")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
