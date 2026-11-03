"""影视界音频与字幕任务数据模型。"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class VideoProjectAudioTask(Base):
    __tablename__ = "video_project_audio_tasks"
    __table_args__ = (
        Index("ix_video_project_audio_tasks_project_id", "project_id"),
        Index("ix_video_project_audio_tasks_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_creative_projects.id"), nullable=False)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    voice: Mapped[str] = mapped_column(String(100), nullable=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    audio_url: Mapped[str] = mapped_column(Text, nullable=True)
    local_path: Mapped[str] = mapped_column(String(500), nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)
    voice_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("video_project_voice_profiles.id"),
        nullable=True,
    )
    speaker_type: Mapped[str] = mapped_column(String(20), nullable=True)
    speaker_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=True)
    queue_position: Mapped[int] = mapped_column(Integer, nullable=True)
    storyboard_shot_index: Mapped[int] = mapped_column(Integer, nullable=True)
    director_shot_revision: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class VideoProjectVoiceProfile(Base):
    __tablename__ = "video_project_voice_profiles"
    __table_args__ = (
        Index("ix_video_project_voice_profiles_project_id", "project_id"),
        Index(
            "ix_video_project_voice_profiles_project_type",
            "project_id",
            "profile_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("video_creative_projects.id"),
        nullable=False,
    )
    profile_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    character_asset_id: Mapped[int] = mapped_column(Integer, nullable=True)
    character_name_snapshot: Mapped[str] = mapped_column(String(200), nullable=True)
    voice: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )


class VideoProjectSubtitleTask(Base):
    __tablename__ = "video_project_subtitle_tasks"
    __table_args__ = (
        Index("ix_video_project_subtitle_tasks_project_id", "project_id"),
        Index("ix_video_project_subtitle_tasks_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_creative_projects.id"), nullable=False)
    source_audio_task_id: Mapped[int] = mapped_column(Integer, ForeignKey("video_project_audio_tasks.id"), nullable=True)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(20), nullable=True)
    storyboard_shot_index: Mapped[int] = mapped_column(Integer, nullable=True)
    director_shot_revision: Mapped[int] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)
    transcript: Mapped[str] = mapped_column(Text, nullable=True)
    srt_content: Mapped[str] = mapped_column(Text, nullable=True)
    error_detail: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
