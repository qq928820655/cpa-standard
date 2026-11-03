"""影视界项目生产职责配置数据模型。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class VideoProjectRoleConfig(Base):
    __tablename__ = "video_project_role_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "role", name="uq_video_project_role_configs_project_role"),
        Index("ix_video_project_role_configs_project_id", "project_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_creative_projects.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=True)
    source_mode: Mapped[str] = mapped_column(String(20), default="auto", nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)
    endpoint_template_id: Mapped[str] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
