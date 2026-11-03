"""Video World plugin backend entry."""
from fastapi import FastAPI
from sqlalchemy import inspect


def register_models() -> None:
    from .models import (
        VideoCreativeProject,
        VideoGenerationTask,
        VideoModelConfig,
        VideoProjectAttachment,
        VideoProjectAudioTask,
        VideoProjectExportTask,
        VideoProjectImageAsset,
        VideoProjectRoleConfig,
        VideoProjectSubtitleTask,
        VideoProjectTimelineItem,
        VideoProjectVoiceProfile,
        VideoProjectWorkflow,
        VideoProjectWorkflowTask,
    )


def register(app: FastAPI) -> None:
    from .video import router

    app.include_router(router, prefix="/api/admin", tags=["video-world"])


async def migrate() -> None:
    from database import engine

    async with engine.begin() as conn:
        def has_column(table_name: str, column_name: str):
            def checker(sync_conn):
                inspector = inspect(sync_conn)
                return inspector.has_table(table_name) and any(
                    column["name"] == column_name
                    for column in inspector.get_columns(table_name)
                )
            return checker

        if not await conn.run_sync(has_column("video_generation_tasks", "project_id")):
            await conn.exec_driver_sql("ALTER TABLE video_generation_tasks ADD COLUMN project_id INTEGER")
        if not await conn.run_sync(has_column("video_model_configs", "protocol_options_json")):
            await conn.exec_driver_sql("ALTER TABLE video_model_configs ADD COLUMN protocol_options_json TEXT")
        for name, definition in {
            "workflow_task_id": "INTEGER",
            "audio_strategy": "VARCHAR(30) DEFAULT 'preserve_native'",
            "subtitle_strategy": "VARCHAR(40) DEFAULT 'asr_from_native_audio'",
            "has_native_audio": "BOOLEAN",
            "native_audio_checked_at": "DATETIME",
        }.items():
            if not await conn.run_sync(has_column("video_generation_tasks", name)):
                await conn.exec_driver_sql(f"ALTER TABLE video_generation_tasks ADD COLUMN {name} {definition}")
        if not await conn.run_sync(has_column("video_creative_projects", "default_aspect_ratio")):
            await conn.exec_driver_sql("ALTER TABLE video_creative_projects ADD COLUMN default_aspect_ratio VARCHAR(10) DEFAULT '9:16'")
        if not await conn.run_sync(has_column("video_project_timeline_items", "storyboard_shot_index")):
            await conn.exec_driver_sql("ALTER TABLE video_project_timeline_items ADD COLUMN storyboard_shot_index INTEGER")
        if not await conn.run_sync(has_column("video_project_export_tasks", "audio_strategy")):
            await conn.exec_driver_sql("ALTER TABLE video_project_export_tasks ADD COLUMN audio_strategy VARCHAR(20) DEFAULT 'preserve'")
            await conn.exec_driver_sql("UPDATE video_project_export_tasks SET audio_strategy = 'preserve' WHERE audio_strategy IS NULL")
        for name, definition in {
            "voice_profile_id": "INTEGER",
            "speaker_type": "VARCHAR(20)",
            "speaker_name_snapshot": "VARCHAR(200)",
            "queue_position": "INTEGER",
            "storyboard_shot_index": "INTEGER",
            "director_shot_revision": "INTEGER",
            "started_at": "DATETIME",
            "updated_at": "DATETIME",
        }.items():
            if not await conn.run_sync(has_column("video_project_audio_tasks", name)):
                await conn.exec_driver_sql(f"ALTER TABLE video_project_audio_tasks ADD COLUMN {name} {definition}")
        for name in ("storyboard_shot_index", "director_shot_revision"):
            if not await conn.run_sync(has_column("video_project_subtitle_tasks", name)):
                await conn.exec_driver_sql(f"ALTER TABLE video_project_subtitle_tasks ADD COLUMN {name} INTEGER")
        for statement in (
            "CREATE INDEX IF NOT EXISTS ix_video_project_audio_tasks_project_queue ON video_project_audio_tasks(project_id, queue_position)",
            "CREATE INDEX IF NOT EXISTS ix_video_project_audio_tasks_project_shot ON video_project_audio_tasks(project_id, storyboard_shot_index)",
            "CREATE INDEX IF NOT EXISTS ix_video_project_audio_tasks_project_shot_revision ON video_project_audio_tasks(project_id, storyboard_shot_index, director_shot_revision)",
            "CREATE INDEX IF NOT EXISTS ix_video_project_subtitle_tasks_project_shot_revision ON video_project_subtitle_tasks(project_id, storyboard_shot_index, director_shot_revision)",
            "CREATE INDEX IF NOT EXISTS ix_video_project_subtitle_tasks_project_shot ON video_project_subtitle_tasks(project_id, storyboard_shot_index)",
        ):
            await conn.exec_driver_sql(statement)
