"""影视界项目图片资产数据模型。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class VideoProjectImageAsset(Base):
    __tablename__ = "video_project_image_assets"
    __table_args__ = (
        Index("ix_video_project_image_assets_project_created", "project_id", "created_at"),
        Index("ix_video_project_image_assets_image_task", "image_task_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_creative_projects.id"), nullable=False)
    image_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("image_generation_tasks.id"), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    storyboard_shot_index: Mapped[int] = mapped_column(Integer, nullable=True)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
