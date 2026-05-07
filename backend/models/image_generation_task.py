"""
图片生成任务数据模型
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ImageGenerationTask(Base):
    """图片生成任务主表"""
    __tablename__ = "image_generation_tasks"
    __table_args__ = (
        Index("ix_image_generation_tasks_status", "status"),
        Index("ix_image_generation_tasks_created_at", "created_at"),
        Index("ix_image_generation_tasks_api_key_id", "api_key_id"),
        Index("ix_image_generation_tasks_model", "model"),
        Index("ix_image_generation_tasks_is_deleted_created_at", "is_deleted", "created_at"),
        Index("ix_image_generation_tasks_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 创建任务的用户 ID（null 表示通过 master key 调用）
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)
    api_key_name: Mapped[str] = mapped_column(String(100), nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    request_params_json: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    failure_category_stats_json: Mapped[str] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str] = mapped_column(Text, nullable=True)
    retry_of_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("image_generation_tasks.id"), nullable=True)
    report_file_path: Mapped[str] = mapped_column(String(500), nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    pending_refresh: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImageKeyModelStats(Base):
    """图片 Key 模型统计"""
    __tablename__ = "image_key_model_stats"
    __table_args__ = (
        UniqueConstraint("api_key_id", "model_normalized", name="uq_image_key_model_stats_key_model"),
        Index("ix_image_key_model_stats_api_key_id", "api_key_id"),
        Index("ix_image_key_model_stats_model_normalized", "model_normalized"),
        Index("ix_image_key_model_stats_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=False)
    api_key_name: Mapped[str] = mapped_column(String(100), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    model_normalized: Mapped[str] = mapped_column(String(200), nullable=False)

    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    spent_units: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    remaining_units: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    last_generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImageGenerationTaskResult(Base):
    """图片生成任务结果表"""
    __tablename__ = "image_generation_task_results"
    __table_args__ = (
        Index("ix_image_generation_task_results_task_id", "task_id"),
        Index("ix_image_generation_task_results_status", "status"),
        Index("ix_image_generation_task_results_task_status", "task_id", "status"),
        Index("ix_image_generation_task_results_api_key_id", "api_key_id"),
        Index("ix_image_generation_task_results_task_index", "task_id", "image_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("image_generation_tasks.id"), nullable=False)
    image_index: Mapped[int] = mapped_column(Integer, default=0)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)

    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    api_key_name: Mapped[str] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=True)
    image_base64: Mapped[str] = mapped_column(Text, nullable=True)
    local_path: Mapped[str] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=True)
    width: Mapped[int] = mapped_column(Integer, nullable=True)
    height: Mapped[int] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    result_meta_json: Mapped[str] = mapped_column(Text, nullable=True)
    error_category: Mapped[str] = mapped_column(String(50), nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
