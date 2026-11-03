"""影视界工作流后台调度。"""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from database import async_session_maker
from models import (
    ImageGenerationTask,
    VideoCreativeProject,
    VideoGenerationTask,
    VideoProjectRoleConfig,
    VideoProjectImageAsset,
    VideoProjectAudioTask,
    VideoProjectSubtitleTask,
    VideoProjectTimelineItem,
    VideoProjectExportTask,
    VideoProjectWorkflow,
    VideoProjectWorkflowTask,
)

logger = logging.getLogger(__name__)

STAGE_REVIEW_STATUS = {
    "analysis": "awaiting_analysis_review",
    "script": "awaiting_script_review",
    "storyboard": "awaiting_storyboard_review",
}
MEDIA_POLL_SECONDS = 5


class VideoWorkflowQueueService:
    def __init__(self):
        self._running_workflow_ids: set[int] = set()
        self._lock = asyncio.Lock()
        self._limits: dict[int, dict[str, asyncio.Semaphore]] = {}

    def configure(self, workflow_id: int, video: int = 2, audio: int = 2, subtitle: int = 1):
        self._limits[workflow_id] = {
            "video": asyncio.Semaphore(max(1, min(5, video))),
            "audio": asyncio.Semaphore(max(1, min(5, audio))),
            "subtitle": asyncio.Semaphore(max(1, min(3, subtitle))),
        }

    def _semaphore(self, workflow_id: int, stage: str) -> asyncio.Semaphore:
        if workflow_id not in self._limits:
            self.configure(workflow_id)
        return self._limits[workflow_id][stage]

    @staticmethod
    def _json(value, default):
        try:
            parsed = json.loads(value or "")
            return parsed if isinstance(parsed, type(default)) else default
        except json.JSONDecodeError:
            return default

    @classmethod
    def _task_input(cls, task):
        return cls._json(task.input_json, {})

    @classmethod
    def _task_output(cls, task):
        return cls._json(task.output_json, {})

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        text = str(exc).lower()
        return any(item in text for item in ("timeout", "timed out", "429", "502", "503", "504", "连接", "connect"))

    async def _fail_director_task(self, db, task, exc):
        output = self._task_output(task)
        if self._is_transient(exc) and task.retry_count < 2:
            task.retry_count += 1
            output["error_category"] = "transient"
            output["next_retry_at"] = (datetime.utcnow() + timedelta(seconds=2 ** task.retry_count)).isoformat()
            task.output_json = json.dumps(output, ensure_ascii=False)
            task.status = "pending"
            task.error_detail = str(exc)[:4000]
        else:
            output["error_category"] = "transient_exhausted" if self._is_transient(exc) else "permanent"
            task.output_json = json.dumps(output, ensure_ascii=False)
            task.status = "failed"
            task.error_detail = str(exc)[:4000]
            task.finished_at = datetime.utcnow()
        await db.commit()

    async def recover(self):
        async with async_session_maker() as db:
            result = await db.execute(select(VideoProjectWorkflow.id).where(
                VideoProjectWorkflow.status == "running",
                VideoProjectWorkflow.cancelled == False,
            ))
            workflow_ids = list(result.scalars().all())
        for workflow_id in workflow_ids:
            await self.start(workflow_id)

    async def start(self, workflow_id: int):
        async with self._lock:
            if workflow_id in self._running_workflow_ids:
                return
            self._running_workflow_ids.add(workflow_id)
        asyncio.create_task(self._run(workflow_id))

    @staticmethod
    def _auth(project: VideoCreativeProject):
        return {"is_admin": True, "user_id": project.user_id}

    @staticmethod
    def _task_output(task: VideoProjectWorkflowTask) -> dict:
        try:
            value = json.loads(task.output_json or "{}")
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}

    async def _complete_task(self, db, workflow, task, output: dict | None = None):
        task.status = "completed"
        task.progress = 100
        task.output_json = json.dumps(output or {}, ensure_ascii=False)
        task.finished_at = datetime.utcnow()
        workflow.error_detail = None
        if task.stage in STAGE_REVIEW_STATUS:
            workflow.status = STAGE_REVIEW_STATUS[task.stage]
            await db.commit()
            return
        next_task = await db.scalar(select(VideoProjectWorkflowTask).where(
            VideoProjectWorkflowTask.workflow_id == workflow.id,
            VideoProjectWorkflowTask.status == "blocked",
        ).order_by(VideoProjectWorkflowTask.sort_order, VideoProjectWorkflowTask.id))
        if next_task:
            next_task.status = "pending"
            workflow.current_stage = next_task.stage
            workflow.status = "running"
        else:
            workflow.status = "completed"
            workflow.current_stage = "export"
        await db.commit()

    async def _execute_text_task(self, db, workflow, task, project):
        plan = json.loads(workflow.plan_json or "{}")
        model = str(plan.get("director_model") or "").strip()
        if not model:
            raise ValueError("工作流计划缺少总控文本模型")
        from routers.video import VideoCreativeAgentRequest, _run_creative_agent

        result = await _run_creative_agent(
            db,
            project,
            VideoCreativeAgentRequest(model=model, source=plan.get("director_source"), stage=task.stage),
            project.user_id,
        )
        if task.stage == "analysis":
            project.analysis_json = json.dumps(result, ensure_ascii=False)
        elif task.stage == "script":
            project.script_json = json.dumps(result, ensure_ascii=False)
        else:
            project.storyboard_json = json.dumps(result, ensure_ascii=False)
        await self._complete_task(db, workflow, task, {"project_id": project.id, "stage": task.stage})

    async def _execute_assets_task(self, db, workflow, task, project):
        role = await db.scalar(select(VideoProjectRoleConfig).where(
            VideoProjectRoleConfig.project_id == project.id,
            VideoProjectRoleConfig.role == "image",
            VideoProjectRoleConfig.enabled == True,
        ))
        if not role or not role.model:
            await self._complete_task(db, workflow, task, {"skipped": True, "reason": "项目未启用图片生产职责"})
            return
        output = self._task_output(task)
        if output.get("asset_ids"):
            await self._complete_task(db, workflow, task, output)
            return
        existing_result = await db.execute(select(VideoProjectImageAsset).where(
            VideoProjectImageAsset.project_id == project.id,
        ))
        existing_assets = list(existing_result.scalars().all())
        if existing_assets:
            await self._complete_task(db, workflow, task, {"asset_ids": [item.id for item in existing_assets], "reused": True})
            return
        from routers.video import ProjectImageRequest, create_project_image

        plan = json.loads(workflow.plan_json or "{}")
        asset_ids: list[int] = []
        auth = self._auth(project)
        for item in (plan.get("characters") or [])[:8]:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            name = str(item["name"]).strip()
            prompt = str(item.get("appearance") or item.get("description") or name).strip()
            asset = await create_project_image(project.id, ProjectImageRequest(asset_type="character", title=name[:200], prompt=prompt[:4000]), db, auth)
            asset_ids.append(int(asset["id"]))
        for item in (plan.get("scenes") or [])[:8]:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            name = str(item["name"]).strip()
            prompt = str(item.get("description") or name).strip()
            asset = await create_project_image(project.id, ProjectImageRequest(asset_type="scene", title=name[:200], prompt=prompt[:4000]), db, auth)
            asset_ids.append(int(asset["id"]))
        await self._complete_task(db, workflow, task, {"asset_ids": asset_ids})

    async def _execute_video_task(self, db, workflow, task, project) -> bool:
        output = self._task_output(task)
        task_ids = [int(item) for item in output.get("video_task_ids") or []]
        if not task_ids:
            storyboard = json.loads(project.storyboard_json or "[]")
            if not storyboard:
                raise ValueError("分镜为空，无法创建视频任务")
            role = await db.scalar(select(VideoProjectRoleConfig).where(
                VideoProjectRoleConfig.project_id == project.id,
                VideoProjectRoleConfig.role == "video",
                VideoProjectRoleConfig.enabled == True,
            ))
            if not role or not role.model:
                raise ValueError("项目未启用视频生产职责")
            from routers.video import VideoGenerateRequest, generate_video

            auth = self._auth(project)
            for index, shot in enumerate(storyboard):
                prompt = str(shot.get("visual_prompt") or "").strip()
                if not prompt:
                    raise ValueError(f"分镜 {index + 1} 缺少视觉提示词")
                result = await generate_video(VideoGenerateRequest(
                    project_id=project.id,
                    storyboard_shot_index=index,
                    model=role.model,
                    prompt=prompt,
                    mode="text",
                    seconds=str(min(12, max(4, int(shot.get("duration_seconds") or 5)))),
                    aspect_ratio=str(shot.get("aspect_ratio") or "16:9"),
                ), db, auth)
                if result.get("id"):
                    created_task = await db.get(VideoGenerationTask, int(result["id"]))
                    if created_task:
                        created_task.workflow_task_id = task.id
                    task_ids.append(int(result["id"]))
            output = {"video_task_ids": task_ids}
            task.output_json = json.dumps(output, ensure_ascii=False)
            task.progress = 15
            await db.commit()
            return False

        result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.id.in_(task_ids)))
        video_tasks = {item.id: item for item in result.scalars().all()}
        if len(video_tasks) != len(task_ids):
            raise ValueError("工作流关联的视频任务缺失")
        from routers.video import refresh_video_task

        auth = self._auth(project)
        for video_task in video_tasks.values():
            if video_task.status in {"creating", "pending", "processing", "running"}:
                await refresh_video_task(video_task.id, db, auth)
        await db.refresh(task)
        result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.id.in_(task_ids)))
        refreshed = list(result.scalars().all())
        failed = [item for item in refreshed if item.status == "failed"]
        completed = [item for item in refreshed if item.status == "completed"]
        task.progress = int(len(completed) * 100 / len(task_ids)) if task_ids else 100
        if failed:
            raise ValueError("；".join(f"视频任务 #{item.id} 失败：{item.error_detail or '上游生成失败'}" for item in failed))
        if len(completed) == len(task_ids):
            await self._complete_task(db, workflow, task, {"video_task_ids": task_ids})
            return True
        await db.commit()
        return False

    @staticmethod
    def _script_text(project: VideoCreativeProject) -> str:
        try:
            script = json.loads(project.script_json or "{}")
        except json.JSONDecodeError:
            return ""
        episodes = script.get("episodes") if isinstance(script, dict) else None
        if not isinstance(episodes, list):
            return ""
        values: list[str] = []
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            for key in ("narration", "dialogue", "summary"):
                value = str(episode.get(key) or "").strip()
                if value:
                    values.append(value)
        return "\n".join(values)[:20000]

    async def _video_tasks_for_stage(self, db, workflow: VideoProjectWorkflow) -> list[VideoGenerationTask]:
        video_stage = await db.scalar(select(VideoProjectWorkflowTask).where(
            VideoProjectWorkflowTask.workflow_id == workflow.id,
            VideoProjectWorkflowTask.stage == "video",
        ))
        task_ids = [int(item) for item in self._task_output(video_stage).get("video_task_ids") or []] if video_stage else []
        if not task_ids:
            return []
        result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.id.in_(task_ids)))
        return list(result.scalars().all())

    async def _execute_audio_task(self, db, workflow, task, project):
        output = self._task_output(task)
        if output.get("native_audio_paths") is not None:
            await self._complete_task(db, workflow, task, output)
            return
        from services.video_export_service import video_export_service

        video_tasks = await self._video_tasks_for_stage(db, workflow)
        if not video_tasks or any(item.status != "completed" or not item.video_url for item in video_tasks):
            raise ValueError("视频阶段尚未全部完成")
        native_audio_paths: dict[str, str] = {}
        requires_tts = False
        for video_task in video_tasks:
            cache_dir = video_export_service.CACHE_ROOT / "workflow" / str(workflow.id)
            local_video = await video_export_service._download_video(video_task.video_url, cache_dir, video_task.id)
            has_native_audio = video_export_service.probe_audio_stream(local_video)
            video_task.has_native_audio = has_native_audio
            video_task.native_audio_checked_at = datetime.utcnow()
            strategy = video_task.audio_strategy or "preserve_native"
            if has_native_audio and strategy != "mute_native_tts":
                audio_path = await video_export_service.extract_audio(local_video, cache_dir / f"video-{video_task.id}.wav")
                native_audio_paths[str(video_task.id)] = str(audio_path)
            if not has_native_audio or strategy in {"overlay_narration", "mute_native_tts"}:
                requires_tts = True
        audio_task_ids: list[int] = []
        if requires_tts:
            role = await db.scalar(select(VideoProjectRoleConfig).where(
                VideoProjectRoleConfig.project_id == project.id,
                VideoProjectRoleConfig.role == "tts",
                VideoProjectRoleConfig.enabled == True,
            ))
            text = self._script_text(project)
            if role and role.model and text:
                existing = await db.scalar(select(VideoProjectAudioTask).where(
                    VideoProjectAudioTask.project_id == project.id,
                    VideoProjectAudioTask.input_text == text,
                ).order_by(VideoProjectAudioTask.id.desc()))
                if existing:
                    audio_task_ids.append(existing.id)
                else:
                    from routers.video import create_project_audio
                    result = await create_project_audio(project.id, SimpleNamespace(text=text, voice="alloy"), SimpleNamespace(base_url="http://workflow.local/"), db, self._auth(project))
                    if result.get("id"):
                        audio_task_ids.append(int(result["id"]))
        await db.commit()
        await self._complete_task(db, workflow, task, {
            "native_audio_paths": native_audio_paths,
            "audio_task_ids": audio_task_ids,
            "tts_skipped": requires_tts and not audio_task_ids,
        })

    async def _execute_subtitle_task(self, db, workflow, task, project):
        output = self._task_output(task)
        if output.get("subtitle_task_ids") is not None:
            await self._complete_task(db, workflow, task, output)
            return
        audio_stage = await db.scalar(select(VideoProjectWorkflowTask).where(
            VideoProjectWorkflowTask.workflow_id == workflow.id,
            VideoProjectWorkflowTask.stage == "audio",
        ))
        audio_output = self._task_output(audio_stage) if audio_stage else {}
        audio_paths = [item for item in (audio_output.get("native_audio_paths") or {}).values()]
        audio_task_ids = [int(item) for item in audio_output.get("audio_task_ids") or []]
        role = await db.scalar(select(VideoProjectRoleConfig).where(
            VideoProjectRoleConfig.project_id == project.id,
            VideoProjectRoleConfig.role == "asr",
            VideoProjectRoleConfig.enabled == True,
        ))
        if not role or not role.model:
            await self._complete_task(db, workflow, task, {"subtitle_task_ids": [], "skipped": True, "reason": "项目未启用 ASR 职责"})
            return
        from routers.video import _segments_to_srt, _get_project_role_key
        from services.project_audio_service import project_audio_service

        _, key = await _get_project_role_key(db, project.id, "asr")
        subtitle_task_ids: list[int] = []
        for path in audio_paths:
            existing = await db.scalar(select(VideoProjectSubtitleTask).where(
                VideoProjectSubtitleTask.project_id == project.id,
                VideoProjectSubtitleTask.transcript == f"native:{path}",
            ))
            if existing:
                subtitle_task_ids.append(existing.id)
                continue
            subtitle = VideoProjectSubtitleTask(project_id=project.id, api_key_id=key.id, provider=key.provider, model=role.model, language="zh", transcript=f"native:{path}", status="running")
            db.add(subtitle)
            await db.flush()
            try:
                result = await project_audio_service.transcribe(key, model=role.model, audio_path=path, language="zh")
                subtitle.transcript = str(result.get("text") or "")
                subtitle.srt_content = _segments_to_srt(result.get("segments") or [])
                subtitle.status = "completed"
                subtitle.finished_at = datetime.utcnow()
            except Exception as exc:
                subtitle.status = "failed"
                subtitle.error_detail = str(exc)[:4000]
                subtitle.finished_at = datetime.utcnow()
            subtitle_task_ids.append(subtitle.id)
        for audio_task_id in audio_task_ids:
            audio = await db.get(VideoProjectAudioTask, audio_task_id)
            if not audio or audio.status != "completed" or not audio.local_path:
                continue
            existing = await db.scalar(select(VideoProjectSubtitleTask).where(
                VideoProjectSubtitleTask.project_id == project.id,
                VideoProjectSubtitleTask.source_audio_task_id == audio.id,
            ))
            if existing:
                subtitle_task_ids.append(existing.id)
                continue
            subtitle = VideoProjectSubtitleTask(project_id=project.id, source_audio_task_id=audio.id, api_key_id=key.id, provider=key.provider, model=role.model, language="zh", status="running")
            db.add(subtitle)
            await db.flush()
            try:
                result = await project_audio_service.transcribe(key, model=role.model, audio_path=audio.local_path, language="zh")
                subtitle.transcript = str(result.get("text") or "")
                subtitle.srt_content = _segments_to_srt(result.get("segments") or [])
                subtitle.status = "completed"
                subtitle.finished_at = datetime.utcnow()
            except Exception as exc:
                subtitle.status = "failed"
                subtitle.error_detail = str(exc)[:4000]
                subtitle.finished_at = datetime.utcnow()
            subtitle_task_ids.append(subtitle.id)
        await self._complete_task(db, workflow, task, {"subtitle_task_ids": subtitle_task_ids})

    async def _execute_timeline_task(self, db, workflow, task, project):
        output = self._task_output(task)
        if output.get("timeline_item_ids"):
            await self._complete_task(db, workflow, task, output)
            return
        video_tasks = await self._video_tasks_for_stage(db, workflow)
        video_tasks.sort(key=lambda item: json.loads(item.request_params_json or "{}").get("storyboard_shot_index", 0))
        timeline_item_ids: list[int] = []
        offset_ms = 0
        for position, video_task in enumerate(video_tasks):
            existing = await db.scalar(select(VideoProjectTimelineItem).where(
                VideoProjectTimelineItem.project_id == project.id,
                VideoProjectTimelineItem.source_type == "video_task",
                VideoProjectTimelineItem.source_id == video_task.id,
            ))
            params = json.loads(video_task.request_params_json or "{}")
            duration_ms = int(float(params.get("seconds") or video_task.seconds or 0) * 1000) or None
            if not existing:
                existing = VideoProjectTimelineItem(project_id=project.id, track="video", source_type="video_task", source_id=video_task.id, position=position, offset_ms=offset_ms, duration_ms=duration_ms)
                db.add(existing)
                await db.flush()
            timeline_item_ids.append(existing.id)
            offset_ms += duration_ms or 0
        subtitle_stage = await db.scalar(select(VideoProjectWorkflowTask).where(
            VideoProjectWorkflowTask.workflow_id == workflow.id,
            VideoProjectWorkflowTask.stage == "subtitle",
        ))
        audio_stage = await db.scalar(select(VideoProjectWorkflowTask).where(
            VideoProjectWorkflowTask.workflow_id == workflow.id,
            VideoProjectWorkflowTask.stage == "audio",
        ))
        for position, audio_id in enumerate(self._task_output(audio_stage).get("audio_task_ids") or []):
            audio = await db.get(VideoProjectAudioTask, int(audio_id))
            if not audio or audio.status != "completed" or not audio.local_path:
                continue
            existing = await db.scalar(select(VideoProjectTimelineItem).where(
                VideoProjectTimelineItem.project_id == project.id,
                VideoProjectTimelineItem.source_type == "audio_task",
                VideoProjectTimelineItem.source_id == audio.id,
            ))
            if not existing:
                existing = VideoProjectTimelineItem(project_id=project.id, track="audio", source_type="audio_task", source_id=audio.id, position=position, offset_ms=0)
                db.add(existing)
                await db.flush()
            timeline_item_ids.append(existing.id)
        for position, subtitle_id in enumerate(self._task_output(subtitle_stage).get("subtitle_task_ids") or []):
            subtitle = await db.get(VideoProjectSubtitleTask, int(subtitle_id))
            if not subtitle or subtitle.status != "completed" or not subtitle.srt_content:
                continue
            existing = await db.scalar(select(VideoProjectTimelineItem).where(
                VideoProjectTimelineItem.project_id == project.id,
                VideoProjectTimelineItem.source_type == "subtitle_task",
                VideoProjectTimelineItem.source_id == subtitle.id,
            ))
            if not existing:
                existing = VideoProjectTimelineItem(project_id=project.id, track="subtitle", source_type="subtitle_task", source_id=subtitle.id, position=position, offset_ms=0)
                db.add(existing)
                await db.flush()
            timeline_item_ids.append(existing.id)
        await self._complete_task(db, workflow, task, {"timeline_item_ids": timeline_item_ids})

    async def _execute_export_task(self, db, workflow, task, project):
        output = self._task_output(task)
        export_id = output.get("export_task_id")
        export_task = await db.get(VideoProjectExportTask, int(export_id)) if export_id else None
        if not export_task:
            export_task = VideoProjectExportTask(project_id=project.id, workflow_id=workflow.id, status="pending")
            db.add(export_task)
            await db.commit()
            await db.refresh(export_task)
        if export_task.status == "pending":
            from services.video_export_service import video_export_service
            await video_export_service.export(db, export_task)
        if export_task.status == "failed":
            raise ValueError(export_task.error_detail or "成片导出失败")
        if export_task.status == "completed":
            await self._complete_task(db, workflow, task, {"export_task_id": export_task.id})
            return True
        task.output_json = json.dumps({"export_task_id": export_task.id}, ensure_ascii=False)
        await db.commit()
        return False

    async def _run_director(self, workflow_id: int):
        while True:
            async with async_session_maker() as db:
                workflow = await db.get(VideoProjectWorkflow, workflow_id)
                if not workflow or workflow.cancelled or workflow.status != "running":
                    return
                project = await db.get(VideoCreativeProject, workflow.project_id)
                result = await db.execute(select(VideoProjectWorkflowTask).where(
                    VideoProjectWorkflowTask.workflow_id == workflow_id,
                    VideoProjectWorkflowTask.task_type == "director_shot",
                    VideoProjectWorkflowTask.status.in_(["blocked", "pending", "running"]),
                ).order_by(VideoProjectWorkflowTask.sort_order, VideoProjectWorkflowTask.id))
                tasks = list(result.scalars().all())
                if not tasks:
                    all_result = await db.execute(select(VideoProjectWorkflowTask).where(VideoProjectWorkflowTask.workflow_id == workflow_id, VideoProjectWorkflowTask.task_type == "director_shot"))
                    all_tasks = list(all_result.scalars().all())
                    if all_tasks and all(item.status == "completed" for item in all_tasks):
                        workflow.status = "completed"
                        workflow.current_stage = "export"
                        await db.commit()
                    elif any(item.status == "failed" for item in all_tasks):
                        workflow.status = "failed"
                        workflow.error_detail = next((item.error_detail for item in all_tasks if item.status == "failed"), "导演镜头任务失败")
                        await db.commit()
                    return
                ready = []
                for task in tasks:
                    output = self._task_output(task)
                    retry_at = output.get("next_retry_at")
                    if retry_at:
                        try:
                            if datetime.fromisoformat(retry_at) > datetime.utcnow():
                                continue
                        except ValueError:
                            pass
                    dependency_ids = self._json(task.depends_on_json, [])
                    if dependency_ids:
                        dependency_result = await db.execute(select(VideoProjectWorkflowTask).where(VideoProjectWorkflowTask.id.in_([int(item) for item in dependency_ids])))
                        dependencies = list(dependency_result.scalars().all())
                        if any(item.status == "failed" for item in dependencies):
                            task.status = "failed"
                            task.error_detail = "前置任务失败"
                            task.finished_at = datetime.utcnow()
                            continue
                        if any(item.status != "completed" for item in dependencies):
                            task.error_detail = "等待前置任务完成"
                            continue
                    if task.status == "blocked":
                        task.status = "pending"
                        task.error_detail = None
                    if task.status == "pending":
                        task.status = "running"
                        task.error_detail = None
                        task.started_at = task.started_at or datetime.utcnow()
                        ready.append(task)
                    elif task.status == "running":
                        ready.append(task)
                await db.commit()
            if not ready:
                await asyncio.sleep(MEDIA_POLL_SECONDS)
                continue
            await asyncio.gather(*(self._run_director_task(workflow_id, item.id) for item in ready))

    async def _run_director_task(self, workflow_id: int, task_id: int):
        async with async_session_maker() as db:
            workflow = await db.get(VideoProjectWorkflow, workflow_id)
            if not workflow:
                return
            project = await db.get(VideoCreativeProject, workflow.project_id)
            task = await db.get(VideoProjectWorkflowTask, task_id)
            if not project or not task:
                return
            async with self._semaphore(workflow_id, task.stage):
                try:
                    await self._execute_director_task(db, workflow, task, project)
                except Exception as exc:
                    await self._fail_director_task(db, task, exc)

    async def _execute_director_task(self, db, workflow, task, project):
        from routers.video import ProjectTtsRequest, ProjectAsrRequest, VideoGenerateRequest, _get_project_role_key, create_project_audio, create_project_subtitle, generate_video, refresh_video_task
        info = self._task_input(task)
        shot_index, revision = int(info["shot_index"]), int(info["revision"])
        plan = self._json(workflow.plan_json, {})
        shot = next((item for item in plan.get("shots") or [] if int(item.get("shot_index", -1)) == shot_index), None)
        if not shot or int(shot.get("revision") or 1) != revision:
            raise ValueError("镜头修订已过期，请重新提交该镜头")
        auth = self._auth(project)
        if task.stage == "video":
            result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.project_id == project.id))
            media = None
            for item in result.scalars().all():
                params = self._json(item.request_params_json, {})
                if params.get("storyboard_shot_index") == shot_index and int(params.get("director_shot_revision") or 1) == revision and item.status != "failed":
                    media = item
                    break
            if not media:
                role, _ = await _get_project_role_key(db, project.id, "video")
                created = await generate_video(VideoGenerateRequest(project_id=project.id, storyboard_shot_index=shot_index, director_shot_revision=revision, director_shot_input_hash=str(info.get("input_hash") or ""), model=role.model, prompt=str(shot["visual_prompt"]), mode="text", seconds=str(shot.get("duration_seconds") or 5), aspect_ratio=str(shot.get("aspect_ratio") or "9:16")), db, auth)
                media = await db.get(VideoGenerationTask, int(created["id"]))
                media.workflow_task_id = task.id
                await db.commit()
            if media.status in {"creating", "pending", "processing", "running"}:
                await refresh_video_task(media.id, db, auth)
                await db.refresh(media)
            if media.status == "failed":
                raise RuntimeError(media.error_detail or "视频上游生成失败")
            if media.status == "completed":
                task.status, task.progress = "completed", 100
                task.output_json = json.dumps({"video_task_id": media.id}, ensure_ascii=False)
                task.finished_at = datetime.utcnow()
            else:
                task.progress = 50
            await db.commit()
            return
        if task.stage == "audio":
            text = "\n".join([str(shot.get("narration") or "").strip(), str(shot.get("dialogue") or "").strip()]).strip()
            if not text:
                task.status, task.progress = "completed", 100
                task.output_json = json.dumps({"skipped": True}, ensure_ascii=False)
                task.finished_at = datetime.utcnow()
                await db.commit()
                return
            result = await db.execute(select(VideoProjectAudioTask).where(VideoProjectAudioTask.project_id == project.id, VideoProjectAudioTask.storyboard_shot_index == shot_index, VideoProjectAudioTask.director_shot_revision == revision))
            audio = next((item for item in result.scalars().all() if item.status in {"pending", "running", "completed"}), None)
            if not audio:
                created = await create_project_audio(project.id, ProjectTtsRequest(text=text, storyboard_shot_index=shot_index, director_shot_revision=revision), SimpleNamespace(base_url="http://workflow.local/"), db, auth)
                audio = await db.get(VideoProjectAudioTask, int(created["id"]))
            if audio.status == "failed":
                raise RuntimeError(audio.error_detail or "TTS 上游生成失败")
            if audio.status == "completed":
                task.status, task.progress = "completed", 100
                task.output_json = json.dumps({"audio_task_id": audio.id}, ensure_ascii=False)
                task.finished_at = datetime.utcnow()
            else:
                task.progress = 50
            await db.commit()
            return
        if task.stage == "subtitle":
            dependencies = self._json(task.depends_on_json, [])
            audio_stage = await db.get(VideoProjectWorkflowTask, int(dependencies[0]))
            audio_id = self._task_output(audio_stage).get("audio_task_id")
            if not audio_id:
                task.status, task.progress = "completed", 100
                task.output_json = json.dumps({"skipped": True}, ensure_ascii=False)
                task.finished_at = datetime.utcnow()
                await db.commit()
                return
            created = await create_project_subtitle(project.id, ProjectAsrRequest(audio_task_id=int(audio_id), language="zh", storyboard_shot_index=shot_index), db, auth)
            if created.get("status") == "failed":
                raise RuntimeError(created.get("error_detail") or "ASR 上游生成失败")
            task.status, task.progress = "completed", 100
            task.output_json = json.dumps({"subtitle_task_id": int(created["id"])}, ensure_ascii=False)
            task.finished_at = datetime.utcnow()
            await db.commit()

    async def _run(self, workflow_id: int):
        try:
            async with async_session_maker() as db:
                result = await db.execute(select(VideoProjectWorkflowTask.id).where(VideoProjectWorkflowTask.workflow_id == workflow_id, VideoProjectWorkflowTask.task_type == "director_shot"))
                is_director = bool(result.scalars().first())
            if is_director:
                await self._run_director(workflow_id)
                return

            while True:
                async with async_session_maker() as db:
                    workflow = await db.get(VideoProjectWorkflow, workflow_id)
                    if not workflow or workflow.status != "running" or workflow.cancelled:
                        return
                    task = await db.scalar(select(VideoProjectWorkflowTask).where(
                        VideoProjectWorkflowTask.workflow_id == workflow_id,
                        VideoProjectWorkflowTask.status.in_(["pending", "running"]),
                    ).order_by(VideoProjectWorkflowTask.sort_order, VideoProjectWorkflowTask.id))
                    if not task:
                        return
                    project = await db.get(VideoCreativeProject, workflow.project_id)
                    if not project:
                        raise ValueError("工作流关联项目不存在")
                    if task.status == "pending":
                        task.status = "running"
                        task.progress = max(task.progress, 10)
                        task.started_at = task.started_at or datetime.utcnow()
                        workflow.current_stage = task.stage
                        await db.commit()
                    try:
                        if task.stage in {"analysis", "script", "storyboard"}:
                            await self._execute_text_task(db, workflow, task, project)
                        elif task.stage == "assets":
                            await self._execute_assets_task(db, workflow, task, project)
                        elif task.stage == "video":
                            if not await self._execute_video_task(db, workflow, task, project):
                                await asyncio.sleep(MEDIA_POLL_SECONDS)
                                continue
                        elif task.stage == "audio":
                            await self._execute_audio_task(db, workflow, task, project)
                        elif task.stage == "subtitle":
                            await self._execute_subtitle_task(db, workflow, task, project)
                        elif task.stage == "timeline":
                            await self._execute_timeline_task(db, workflow, task, project)
                        elif task.stage == "export":
                            if not await self._execute_export_task(db, workflow, task, project):
                                await asyncio.sleep(MEDIA_POLL_SECONDS)
                                continue
                        else:
                            raise ValueError(f"不支持的工作流阶段：{task.stage}")
                    except Exception as exc:
                        logger.exception("video_workflow_stage_failed workflow_id=%s task_id=%s", workflow_id, task.id)
                        task.status = "failed"
                        task.error_detail = str(exc)[:4000]
                        task.finished_at = datetime.utcnow()
                        workflow.status = "failed"
                        workflow.error_detail = task.error_detail
                        await db.commit()
                        return
        finally:
            async with self._lock:
                self._running_workflow_ids.discard(workflow_id)


video_workflow_queue_service = VideoWorkflowQueueService()
