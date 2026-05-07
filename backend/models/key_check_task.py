"""
Key 检测任务数据模型
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ApiKeyCheckTask(Base):
    """Key 检测任务主表"""
    __tablename__ = "api_key_check_tasks"
    __table_args__ = (
        Index("ix_api_key_check_tasks_status", "status"),
        Index("ix_api_key_check_tasks_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    providers_json: Mapped[str] = mapped_column(Text, nullable=True)
    models_json: Mapped[str] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=True)
    key_ids_json: Mapped[str] = mapped_column(Text, nullable=True)
    target_model: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)

    total_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)

    failure_category_stats_json: Mapped[str] = mapped_column(Text, nullable=True)
    provider_stats_json: Mapped[str] = mapped_column(Text, nullable=True)
    model_stats_json: Mapped[str] = mapped_column(Text, nullable=True)
    error_summary: Mapped[str] = mapped_column(Text, nullable=True)
    retry_of_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_key_check_tasks.id"), nullable=True)
    report_file_path: Mapped[str] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiKeyCheckTaskResult(Base):
    """Key 检测任务结果表"""
    __tablename__ = "api_key_check_task_results"
    __table_args__ = (
        Index("ix_api_key_check_task_results_task_id", "task_id"),
        Index("ix_api_key_check_task_results_status", "status"),
        Index("ix_api_key_check_task_results_task_status", "task_id", "status"),
        Index("ix_api_key_check_task_results_api_key_id", "api_key_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_key_check_tasks.id"), nullable=False)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=False)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    target_model: Mapped[str] = mapped_column(String(200), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    response_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    failure_category: Mapped[str] = mapped_column(String(50), nullable=True)
    failure_detail: Mapped[str] = mapped_column(Text, nullable=True)
    address_check_json: Mapped[str] = mapped_column(Text, nullable=True)
    model_check_json: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
