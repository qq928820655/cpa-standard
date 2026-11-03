"""影世界创作项目数据模型"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VideoCreativeProject(Base):
    __tablename__ = "video_creative_projects"
    __table_args__ = (Index("ix_video_creative_projects_created_at", "created_at"), Index("ix_video_creative_projects_user_id", "user_id"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_json: Mapped[str] = mapped_column(Text, nullable=True)
    script_json: Mapped[str] = mapped_column(Text, nullable=True)
    storyboard_json: Mapped[str] = mapped_column(Text, nullable=True)
    default_aspect_ratio: Mapped[str] = mapped_column(String(10), default="9:16", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
