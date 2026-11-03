"""影视界项目工作流数据模型。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VideoProjectWorkflow(Base):
    __tablename__ = "video_project_workflows"
    __table_args__ = (Index("ix_video_project_workflows_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_creative_projects.id"), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(40), default="draft", nullable=False)
    current_stage: Mapped[str] = mapped_column(String(30), default="plan", nullable=False)
    auto_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=True)
    review_history_json: Mapped[str] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VideoProjectWorkflowTask(Base):
    __tablename__ = "video_project_workflow_tasks"
    __table_args__ = (
        Index("ix_video_project_workflow_tasks_workflow_stage_order", "workflow_id", "stage", "sort_order"),
        Index("ix_video_project_workflow_tasks_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_project_workflows.id"), nullable=False)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    depends_on_json: Mapped[str] = mapped_column(Text, nullable=True)
    input_json: Mapped[str] = mapped_column(Text, nullable=True)
    output_json: Mapped[str] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VideoProjectExportTask(Base):
    __tablename__ = "video_project_export_tasks"
    __table_args__ = (Index("ix_video_project_export_tasks_project_status", "project_id", "status"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_creative_projects.id"), nullable=False)
    workflow_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_project_workflows.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    audio_strategy: Mapped[str] = mapped_column(String(20), default="preserve", nullable=False)
    output_path: Mapped[str] = mapped_column(Text, nullable=True)
    subtitle_path: Mapped[str] = mapped_column(Text, nullable=True)
    manifest_path: Mapped[str] = mapped_column(Text, nullable=True)
    command_summary: Mapped[str] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
