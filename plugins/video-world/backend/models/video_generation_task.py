"""视频创作任务与模型配置数据模型"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base


class VideoModelConfig(Base):
    __tablename__ = "video_model_configs"
    __table_args__ = (Index("ix_video_model_configs_model", "model", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    protocol: Mapped[str] = mapped_column(String(50), default="agnes", nullable=False)
    create_path: Mapped[str] = mapped_column(String(300), default="/v1/videos", nullable=False)
    query_path: Mapped[str] = mapped_column(String(300), default="/agnesapi", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=True)
    protocol_options_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VideoGenerationTask(Base):
    __tablename__ = "video_generation_tasks"
    __table_args__ = (
        Index("ix_video_generation_tasks_created_at", "created_at"),
        Index("ix_video_generation_tasks_status", "status"),
        Index("ix_video_generation_tasks_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_creative_projects.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    seconds: Mapped[str] = mapped_column(String(10), nullable=False)
    request_params_json: Mapped[str] = mapped_column(Text, nullable=True)
    workflow_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_project_workflow_tasks.id"), nullable=True)
    audio_strategy: Mapped[str] = mapped_column(String(30), default="preserve_native", nullable=False)
    subtitle_strategy: Mapped[str] = mapped_column(String(40), default="asr_from_native_audio", nullable=False)
    has_native_audio: Mapped[bool] = mapped_column(Boolean, nullable=True)
    native_audio_checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    upstream_video_id: Mapped[str] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    video_url: Mapped[str] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)
    attempted_key_ids_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # 调用来源：panel=管理面板视频页；api=外部 API Key 调用（/v1/videos/*）
    source: Mapped[str] = mapped_column(String(20), default="panel", nullable=False)
