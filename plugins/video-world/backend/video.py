"""影世界视频创作管理接口。"""
import asyncio
import hashlib
import json
import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker, get_db
from config import DATA_DIR
from models import ImageGenerationTask, ImageGenerationTaskResult
from .models import VideoCreativeProject, VideoGenerationTask, VideoModelConfig, VideoProjectAttachment, VideoProjectExportTask, VideoProjectImageAsset, VideoProjectRoleConfig, VideoProjectWorkflow, VideoProjectWorkflowTask, VideoProjectAudioTask, VideoProjectSubtitleTask, VideoProjectTimelineItem, VideoProjectVoiceProfile
from routers.admin import require_image_square_access, verify_admin_key
from routers.proxy import build_upstream_body_for_key, forward_request_with_retry, verify_api_key
from services.pool_manager import pool_manager
from .project_audio_service import project_audio_service
from services.proxy_service import proxy_service
from .video_service import video_service
from .video_export_service import video_export_service
from .video_style_preset_service import apply_style_preset, get_style_preset, list_style_presets

router = APIRouter()
VIDEO_ASSET_DIR = DATA_DIR / "video_assets"
PROJECT_ATTACHMENT_DIR = DATA_DIR / "video_project_attachments"
MAX_VIDEO_ASSET_SIZE = 25 * 1024 * 1024
MAX_PROJECT_ATTACHMENT_SIZE = 20 * 1024 * 1024
ALLOWED_PROJECT_ATTACHMENT_SUFFIXES = {".txt", ".md", ".docx", ".pdf"}
ALLOWED_VIDEO_ASSET_TYPES = {"image": {"image/jpeg", "image/png", "image/webp"}, "audio": {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/ogg", "audio/mp4"}}
PROJECT_AUDIO_QUEUE_LOCKS: dict[int, asyncio.Lock] = {}


def _extract_project_attachment_text(suffix: str, content: bytes) -> str:
    if suffix in {".txt", ".md"}:
        return content.decode("utf-8-sig", errors="replace").strip()
    if suffix == ".docx":
        from docx import Document
        from io import BytesIO

        return "\n".join(paragraph.text for paragraph in Document(BytesIO(content)).paragraphs).strip()
    if suffix == ".pdf":
        from io import BytesIO
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(content)).pages).strip()
    raise ValueError("不支持的附件类型")


def _serialize_project_attachment(item: VideoProjectAttachment, request: Request | None = None) -> dict:
    base_url = str(request.base_url).rstrip("/") if request else ""
    return {
        "id": item.id,
        "original_name": item.original_name,
        "content_type": item.content_type,
        "file_size_bytes": item.file_size_bytes,
        "text_length": len(item.extracted_text or ""),
        "extraction_error": item.extraction_error,
        "download_url": f"{base_url}/api/admin/video/creative-projects/{item.project_id}/attachments/{item.id}/file",
        "created_at": item.created_at,
    }

def _safe_asset_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", name or "asset")[:100]


def _detect_asset_type(content_type: str) -> Optional[str]:
    for asset_type, allowed_types in ALLOWED_VIDEO_ASSET_TYPES.items():
        if content_type in allowed_types:
            return asset_type
    return None

DEFAULT_AGNES_CAPABILITIES = {
    "modes": ["text", "keyframe", "reference"],
    "seconds": ["4", "5", "6", "7", "8", "9", "10", "11", "12"],
    "sizes": ["720P"],
    "aspect_ratios": ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
}


DEFAULT_VIDEO_ENDPOINT_TEMPLATES = [
    {"id": "agnes-video-2.5-flash", "name": "Agnes Video 2.5 Flash", "protocol": "agnes", "create_path": "/v1/videos", "query_path": "/agnesapi", "capabilities": DEFAULT_AGNES_CAPABILITIES},
    {"id": "arcreel-newapi-video", "name": "ArcReel NewAPI Video", "protocol": "arcreel_newapi_video", "create_path": "/v1/video/generations", "query_path": "/v1/video/generations", "capabilities": {"modes": ["text", "keyframe"], "seconds": ["4", "5", "6", "7", "8", "9", "10", "11", "12"], "sizes": ["720P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "arcreel-minimax-h3", "name": "ArcReel MiniMax H3", "protocol": "arcreel_minimax_h3", "create_path": "/v2/video_generation", "query_path": "/v2/query/video_generation", "capabilities": {"modes": ["text", "keyframe", "reference"], "seconds": ["4", "5", "6", "7", "8", "9", "10", "11", "12"], "sizes": ["768P", "2K"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "arcreel-minimax-hailuo", "name": "ArcReel MiniMax Hailuo", "protocol": "arcreel_minimax_hailuo", "create_path": "/v1/video_generation", "query_path": "/v1/query/video_generation", "capabilities": {"modes": ["text", "keyframe"], "seconds": ["4", "5", "6", "7", "8", "9", "10", "11", "12"], "sizes": ["768P", "1080P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "arcreel-minimax-s2v", "name": "ArcReel MiniMax S2V-01", "protocol": "arcreel_minimax_s2v", "create_path": "/v1/video_generation", "query_path": "/v1/query/video_generation", "capabilities": {"modes": ["reference"], "seconds": ["4", "5", "6", "7", "8", "9", "10", "11", "12"], "sizes": ["720P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "arcreel-v2-video", "name": "ArcReel V2 Video Generations", "protocol": "arcreel_v2_video", "create_path": "/v2/video/generations", "query_path": "/v2/video/generations", "capabilities": {"modes": ["text", "keyframe", "reference"], "seconds": ["4", "5", "6", "7", "8", "9", "10", "11", "12"], "sizes": ["720P", "1080P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "openai-video", "name": "OpenAI Video / Sora", "protocol": "openai_video", "create_path": "/v1/videos", "query_path": "/v1/videos/{task_id}", "capabilities": {"modes": ["text"], "seconds": ["4", "8", "12"], "sizes": ["720x1280", "1280x720", "1080x1920", "1920x1080"], "aspect_ratios": ["16:9", "9:16"]}},
    {"id": "ark-seedance", "name": "Ark Seedance", "protocol": "ark_seedance", "create_path": "/api/v3/contents/generations/tasks", "query_path": "/api/v3/contents/generations/tasks/{task_id}", "capabilities": {"modes": ["text", "keyframe", "reference"], "seconds": ["4", "5", "6", "7", "8", "9", "10", "11", "12"], "sizes": ["480P", "720P", "1080P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "dashscope-async-video", "name": "DashScope Async Video", "protocol": "dashscope_async_video", "create_path": "/api/v1/services/aigc/video-generation/video-synthesis", "query_path": "/api/v1/tasks/{task_id}", "capabilities": {"modes": ["text", "keyframe", "reference"], "seconds": ["4", "5", "6", "7", "8", "9", "10"], "sizes": ["480P", "720P", "1080P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "kling-video", "name": "Kling Video", "protocol": "kling_video", "create_path": "/v1/videos/text2video", "query_path": "/v1/videos/{task_id}", "capabilities": {"modes": ["text"], "seconds": ["5", "10"], "sizes": ["720P", "1080P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
    {"id": "vidu-video", "name": "Vidu Video", "protocol": "vidu_video", "create_path": "/ent/v2/text2video", "query_path": "/ent/v2/tasks/{task_id}/creations", "capabilities": {"modes": ["text"], "seconds": ["4", "5", "8"], "sizes": ["720P", "1080P"], "aspect_ratios": ["16:9", "9:16", "1:1"]}},
]


class VideoModelRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    provider: Optional[str] = None
    protocol: str = "agnes"
    create_path: str = "/v1/videos"
    query_path: str = "/agnesapi"
    enabled: bool = True
    capabilities: dict = Field(default_factory=lambda: dict(DEFAULT_AGNES_CAPABILITIES))
    protocol_options: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_protocol_paths(self):
        if self.protocol not in {"agnes", "arcreel_newapi_video", "arcreel_minimax_h3", "arcreel_minimax_hailuo", "arcreel_minimax_s2v", "arcreel_v2_video", "minimax", "openai_video", "ark_seedance", "dashscope_async_video", "kling_video", "vidu_video"}:
            raise ValueError("不支持的视频协议")
        if not self.create_path.startswith("/") or not self.query_path.startswith("/"):
            raise ValueError("接口路径必须以 / 开头")
        return self


class VideoCreativeProjectRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source_text: str = Field(default="", min_length=8, max_length=100000)
    default_aspect_ratio: str = "9:16"

    @model_validator(mode="after")
    def validate_aspect_ratio(self):
        if self.default_aspect_ratio not in {"9:16", "16:9", "1:1"}:
            raise ValueError("不支持的默认画幅")
        return self


class VideoCreativeAgentRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    source: Optional[str] = None
    stage: str


class VideoCreativeProjectUpdate(BaseModel):
    analysis: Optional[dict] = None
    script: Optional[dict] = None
    storyboard: Optional[list[dict]] = None
    default_aspect_ratio: Optional[str] = None

    @model_validator(mode="after")
    def validate_aspect_ratio(self):
        if self.default_aspect_ratio is not None and self.default_aspect_ratio not in {"9:16", "16:9", "1:1"}:
            raise ValueError("不支持的默认画幅")
        return self


class VideoProjectRoleConfigRequest(BaseModel):
    role: str
    model: Optional[str] = None
    source_mode: str = "auto"
    provider: Optional[str] = None
    api_key_id: Optional[int] = None
    endpoint_template_id: Optional[str] = None
    enabled: bool = True

    @model_validator(mode="after")
    def validate_source(self):
        if self.role not in {"text", "image", "video", "tts", "asr"}:
            raise ValueError("不支持的生产职责")
        if self.source_mode not in {"auto", "provider", "key"}:
            raise ValueError("不支持的来源模式")
        if self.source_mode == "provider" and not self.provider:
            raise ValueError("提供商模式必须填写 provider")
        if self.source_mode == "key" and not self.api_key_id:
            raise ValueError("指定 Key 模式必须填写 api_key_id")
        return self


class ProjectImageRequest(BaseModel):
    asset_type: str
    title: str = Field(min_length=1, max_length=200)
    prompt: str = Field(min_length=1, max_length=4000)
    storyboard_shot_index: Optional[int] = None
    size: Optional[str] = None

    @model_validator(mode="after")
    def validate_project_image(self):
        if self.asset_type not in {"character", "scene", "storyboard_reference"}:
            raise ValueError("不支持的图片资产类型")
        if self.asset_type == "storyboard_reference" and self.storyboard_shot_index is None:
            raise ValueError("分镜参考图必须指定分镜序号")
        return self


class ProjectVoiceProfileRequest(BaseModel):
    profile_type: str
    name: str = Field(min_length=1, max_length=100)
    character_asset_id: Optional[int] = None
    voice: str = Field(default="alloy", min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_profile(self):
        if self.profile_type not in {"narrator", "character"}:
            raise ValueError("不支持的音色设定类型")
        if self.profile_type == "narrator" and self.character_asset_id is not None:
            raise ValueError("旁白音色不能绑定角色资产")
        if self.profile_type == "character" and self.character_asset_id is None:
            raise ValueError("角色音色必须绑定角色资产")
        return self


class ProjectVoiceProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    character_asset_id: Optional[int] = None
    voice: str = Field(min_length=1, max_length=100)


class ProjectTtsRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    storyboard_shot_index: Optional[int] = Field(default=None, ge=0)
    director_shot_revision: Optional[int] = Field(default=None, ge=1)
    voice: str = "alloy"
    voice_profile_id: Optional[int] = None
    speaker_type: str = "narrator"
    character_asset_id: Optional[int] = None
    speaker_name: Optional[str] = Field(default=None, max_length=200)


class ProjectAudioTaskUpdateRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    voice: str = Field(min_length=1, max_length=100)
    voice_profile_id: Optional[int] = None
    speaker_type: str = "narrator"
    character_asset_id: Optional[int] = None
    speaker_name: Optional[str] = Field(default=None, max_length=200)


class ProjectAsrRequest(BaseModel):
    audio_task_id: int
    language: Optional[str] = "zh"
    storyboard_shot_index: Optional[int] = Field(default=None, ge=0)


class WorkflowPlanRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    source: Optional[str] = None
    auto_run: bool = False


class DirectorStoryboardRequest(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    source: Optional[str] = None
    target_duration_seconds: int = Field(default=30, ge=5, le=600)
    shot_count: int = Field(default=6, ge=1, le=50)
    aspect_ratio: Optional[str] = None
    style_preset_id: Optional[str] = None
    regenerate: bool = False

    @model_validator(mode="after")
    def validate_director_options(self):
        if self.aspect_ratio is not None and self.aspect_ratio not in {"9:16", "16:9", "1:1"}:
            raise ValueError("不支持的默认画幅")
        return self


class DirectorProduceRequest(BaseModel):
    shot_indexes: list[int] = Field(default_factory=list)
    regenerate_failed: bool = False
    force: bool = False
    video_concurrency: int = Field(default=2, ge=1, le=5)
    audio_concurrency: int = Field(default=2, ge=1, le=5)
    subtitle_concurrency: int = Field(default=1, ge=1, le=3)


class DirectorShotUpdateRequest(BaseModel):
    scene_no: int = Field(default=1, ge=1, le=9999)
    shot_no: int = Field(default=1, ge=1, le=9999)
    duration_seconds: int = Field(default=5, ge=4, le=12)
    visual_prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str = Field(default="", max_length=1000)
    camera: str = Field(default="medium", max_length=100)
    motion: str = Field(default="static", max_length=100)
    aspect_ratio: str = "9:16"
    narration: str = Field(default="", max_length=4000)
    dialogue: str | list[dict] = ""
    sound_cue: str = Field(default="", max_length=1000)
    reference_asset_ids: list[int] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_shot(self):
        if self.aspect_ratio not in {"9:16", "16:9", "1:1"}:
            raise ValueError("不支持的分镜画幅")
        if len(self.reference_asset_ids) != len(set(self.reference_asset_ids)):
            raise ValueError("分镜参考资产不能重复")
        return self


class DirectorAutoScheduleRequest(BaseModel):
    audio_strategy: str = "overlay"
    include_audio: bool = True
    include_subtitles: bool = True
    clear_existing_director_items: bool = False

    @model_validator(mode="after")
    def validate_audio_strategy(self):
        if self.audio_strategy not in {"preserve", "mute", "overlay"}:
            raise ValueError("不支持的音频策略")
        return self


class WorkflowReviewRequest(BaseModel):
    action: str
    note: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_action(self):
        if self.action not in {"approve", "pause", "resume", "cancel"}:
            raise ValueError("不支持的工作流操作")
        return self


class ProjectSubtitleUpdateRequest(BaseModel):
    srt_content: str = Field(min_length=1, max_length=200000)


class ProjectTimelineItemRequest(BaseModel):
    track: str
    source_type: str
    source_id: int
    position: Optional[int] = Field(default=None, ge=0)
    offset_ms: int = Field(default=0, ge=0)
    duration_ms: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_timeline_item(self):
        valid_sources = {
            "video": "video_task",
            "audio": "audio_task",
            "subtitle": "subtitle_task",
        }
        if valid_sources.get(self.track) != self.source_type:
            raise ValueError("时间线轨道与来源类型不匹配")
        return self


class StoryboardBatchGenerateRequest(BaseModel):
    selected_shot_indexes: list[int] = Field(min_length=1, max_length=50)
    concurrency: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def validate_shot_indexes(self):
        if len(set(self.selected_shot_indexes)) != len(self.selected_shot_indexes) or any(index < 0 for index in self.selected_shot_indexes):
            raise ValueError("分镜序号必须为不重复的非负整数")
        return self


class ProjectTimelineItemUpdateRequest(BaseModel):
    position: int = Field(ge=0)
    offset_ms: int = Field(ge=0)
    duration_ms: Optional[int] = Field(default=None, ge=1)


class ProjectExportRequest(BaseModel):
    audio_strategy: str = "preserve"

    @model_validator(mode="after")
    def validate_audio_strategy(self):
        if self.audio_strategy not in {"preserve", "mute", "overlay"}:
            raise ValueError("不支持的音频策略")
        return self


class VideoGenerateRequest(BaseModel):
    project_id: Optional[int] = None
    storyboard_shot_index: Optional[int] = None
    director_shot_revision: Optional[int] = Field(default=None, ge=1)
    director_shot_input_hash: Optional[str] = Field(default=None, max_length=64)
    model: str
    prompt: str = Field(min_length=1)
    mode: str
    seconds: str = "5"
    aspect_ratio: str = "16:9"
    size: str = "720P"
    seed: Optional[int] = None
    source: Optional[str] = None
    first_frame: Optional[str] = None
    last_frame: Optional[str] = None
    images: list[str] = Field(default_factory=list)
    audios: list[str] = Field(default_factory=list)
    style_preset_id: Optional[str] = None
    reference_asset_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_media(self):
        if self.mode not in {"text", "keyframe", "reference"}:
            raise ValueError("不支持的视频生成模式")
        if self.mode == "keyframe" and not (self.first_frame or self.last_frame):
            raise ValueError("首尾帧模式至少需要一张图片")
        if self.mode == "reference" and not (self.images or self.audios):
            raise ValueError("参考模式至少需要图片或音频")
        if self.mode == "reference" and len(self.images) > 5:
            raise ValueError("参考图片最多 5 张")
        if self.mode == "reference" and len(self.audios) > 3:
            raise ValueError("参考音频最多 3 段")
        if self.mode == "text" and (self.first_frame or self.last_frame or self.images or self.audios):
            raise ValueError("文生视频不能携带参考素材")
        if self.mode == "keyframe" and (self.images or self.audios):
            raise ValueError("首尾帧模式不能携带参考素材")
        if self.mode == "reference" and (self.first_frame or self.last_frame):
            raise ValueError("参考模式不能携带首尾帧")
        return self


def serialize_model(item: VideoModelConfig) -> dict:
    return {
        "id": item.id, "model": item.model, "display_name": item.display_name,
        "provider": item.provider, "protocol": item.protocol, "create_path": item.create_path,
        "query_path": item.query_path, "enabled": item.enabled,
        "capabilities": json.loads(item.capabilities_json or "{}"),
        "protocol_options": json.loads(item.protocol_options_json or "{}"),
    }


def serialize_task(item: VideoGenerationTask) -> dict:
    request_params = json.loads(item.request_params_json or "{}")
    style_preset = get_style_preset(request_params.get("style_preset_id"))
    return {
        "id": item.id, "project_id": item.project_id, "storyboard_shot_index": request_params.get("storyboard_shot_index"), "api_key_id": item.api_key_id, "provider": item.provider,
        "model": item.model, "prompt": item.prompt, "mode": item.mode, "seconds": item.seconds,
        "request_params": request_params, "style_preset_id": request_params.get("style_preset_id"), "style_preset_name": style_preset["name"] if style_preset else None, "upstream_video_id": item.upstream_video_id,
        "status": item.status, "video_url": item.video_url, "cover_url": item.cover_url,
        "workflow_task_id": item.workflow_task_id, "audio_strategy": item.audio_strategy,
        "subtitle_strategy": item.subtitle_strategy, "has_native_audio": item.has_native_audio,
        "native_audio_checked_at": item.native_audio_checked_at,
        "error_detail": item.error_detail, "created_at": item.created_at, "updated_at": item.updated_at,
        "finished_at": item.finished_at,
        "source": getattr(item, "source", "panel") or "panel",
    }


async def ensure_agnes_model(db: AsyncSession):
    existing = await db.scalar(select(VideoModelConfig).where(VideoModelConfig.model == "agnes-video-2.5-flash"))
    if not existing:
        db.add(VideoModelConfig(
            model="agnes-video-2.5-flash", display_name="Agnes Video 2.5 Flash",
            provider="agnes", protocol="agnes", capabilities_json=json.dumps(DEFAULT_AGNES_CAPABILITIES),
        ))
        await db.commit()


def _serialize_creative_project(project: VideoCreativeProject) -> dict:
    return {
        "id": project.id,
        "title": project.title,
        "source_text": project.source_text,
        "analysis": json.loads(project.analysis_json or "{}"),
        "script": json.loads(project.script_json or "{}"),
        "storyboard": json.loads(project.storyboard_json or "[]"),
        "default_aspect_ratio": project.default_aspect_ratio or "9:16",
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }


def _extract_agent_json(response_data: object) -> object:
    if isinstance(response_data, dict):
        choices = response_data.get("choices") or []
        if choices and isinstance(choices[0], dict):
            content = (choices[0].get("message") or {}).get("content")
            if isinstance(content, str):
                response_data = content
        elif isinstance(response_data.get("content"), str):
            response_data = response_data["content"]
    if isinstance(response_data, str):
        text = response_data.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        return json.loads(text)
    raise ValueError("创作 Agent 未返回可解析的 JSON")


async def _run_creative_agent(db: AsyncSession, project: VideoCreativeProject, data: VideoCreativeAgentRequest, user_id: Optional[int]):
    prompts = {
        "analysis": "分析以下小说或创作素材，输出严格 JSON 对象：summary、themes、characters（数组，含 name、description、appearance）、scenes（数组，含 name、description）、story_beats（数组）。不要 Markdown。",
        "script": "根据以下项目素材和已有分析，输出严格 JSON 对象：title、logline、episodes（数组）。每集含 title、summary、scenes（数组）；每场含 heading、characters、action、dialogue、estimated_seconds。不要 Markdown。",
        "storyboard": "根据以下项目素材、分析和剧本，输出严格 JSON 数组。每项含 scene_no、shot_no、title、duration_seconds、visual_prompt、camera、motion、characters、dialogue、aspect_ratio。duration_seconds 必须为 4 到 12 的整数。不要 Markdown。",
    }
    instruction = prompts.get(data.stage)
    if not instruction:
        raise HTTPException(status_code=400, detail="不支持的创作阶段")
    attachments_result = await db.execute(select(VideoProjectAttachment).where(
        VideoProjectAttachment.project_id == project.id,
    ).order_by(VideoProjectAttachment.id))
    attachment_context = [
        {"name": item.original_name, "text": (item.extracted_text or "")[:30000]}
        for item in attachments_result.scalars().all()
    ]
    context = {"title": project.title, "source_text": project.source_text, "attachments": attachment_context, "analysis": json.loads(project.analysis_json or "{}"), "script": json.loads(project.script_json or "{}")}
    body = {"model": data.model, "messages": [{"role": "system", "content": "你是影视创作 Agent。输出必须是可解析 JSON，保持角色、场景和剧情连续一致。"}, {"role": "user", "content": f"{instruction}\n\n项目资料：\n{json.dumps(context, ensure_ascii=False)}"}], "temperature": 0.7}
    force_providers = None
    force_key_name = None
    if data.source:
        prefix, _, value = data.source.partition(":")
        if prefix == "provider":
            force_providers = [value]
        elif prefix == "key":
            key = await pool_manager.get_key_by_id(db, int(value))
            if not key or not pool_manager.is_key_available_for_model(key, data.model):
                raise HTTPException(status_code=400, detail="指定 Key 不可用于创作 Agent 模型")
            force_key_name = key.name
    if force_key_name:
        upstream_body, _ = await build_upstream_body_for_key(db, key, body, data.model)
        status_code, _, response_data = await proxy_service.forward_request(
            db=db,
            api_key=key,
            method="POST",
            path="v1/chat/completions",
            headers={"content-type": "application/json"},
            body=upstream_body,
            user_id=user_id,
            original_model=data.model,
        )
    else:
        status_code, _, response_data, _ = await forward_request_with_retry(db, "POST", "v1/chat/completions", {"content-type": "application/json"}, body, user_id=user_id, original_model=data.model, force_providers=force_providers)
    if status_code < 200 or status_code >= 300:
        raise HTTPException(status_code=502, detail="创作 Agent 调用失败")
    return _extract_agent_json(response_data)

def _serialize_project_role_config(item: VideoProjectRoleConfig) -> dict:
    return {
        "role": item.role,
        "model": item.model,
        "source_mode": item.source_mode,
        "provider": item.provider,
        "api_key_id": item.api_key_id,
        "endpoint_template_id": item.endpoint_template_id,
        "enabled": item.enabled,
    }


@router.get("/video/creative-projects/{project_id}/roles")
async def list_creative_project_roles(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    result = await db.execute(select(VideoProjectRoleConfig).where(VideoProjectRoleConfig.project_id == project_id))
    return [_serialize_project_role_config(item) for item in result.scalars().all()]


@router.put("/video/creative-projects/{project_id}/roles/{role}")
async def save_creative_project_role(project_id: int, role: str, data: VideoProjectRoleConfigRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    if role != data.role:
        raise HTTPException(status_code=400, detail="职责路径与请求不一致")
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    if data.source_mode == "key":
        key = await pool_manager.get_key_by_id(db, data.api_key_id)
        if not key or not data.model or not pool_manager.is_key_available_for_model(key, data.model):
            raise HTTPException(status_code=400, detail="指定 Key 不支持该模型")
    existing = await db.scalar(select(VideoProjectRoleConfig).where(VideoProjectRoleConfig.project_id == project_id, VideoProjectRoleConfig.role == role))
    if not existing:
        existing = VideoProjectRoleConfig(project_id=project_id, role=role)
        db.add(existing)
    for field, value in data.model_dump().items():
        setattr(existing, field, value)
    await db.commit()
    await db.refresh(existing)
    return _serialize_project_role_config(existing)


def _format_srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(seconds * 1000))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def _segments_to_srt(segments: list[dict]) -> str:
    lines = []
    for index, segment in enumerate(segments, start=1):
        lines.extend([str(index), f"{_format_srt_timestamp(float(segment.get('start', 0)))} --> {_format_srt_timestamp(float(segment.get('end', 0)))}", str(segment.get("text") or "").strip(), ""])
    return "\n".join(lines).strip()


async def _get_project_role_key(db: AsyncSession, project_id: int, role: str):
    role_config = await db.scalar(select(VideoProjectRoleConfig).where(
        VideoProjectRoleConfig.project_id == project_id,
        VideoProjectRoleConfig.role == role,
        VideoProjectRoleConfig.enabled == True,
    ))
    if not role_config or not role_config.model:
        raise HTTPException(status_code=400, detail=f"请先在项目生产职责中配置启用的 {role} 模型")
    if role_config.source_mode == "key":
        key = await pool_manager.get_key_by_id(db, role_config.api_key_id)
        if not key or not pool_manager.is_key_available_for_model(key, role_config.model):
            raise HTTPException(status_code=400, detail="指定 Key 不支持该职责模型")
    else:
        key = await pool_manager.get_next_key(db, provider=role_config.provider if role_config.source_mode == "provider" else None, model=role_config.model)
    if not key:
        raise HTTPException(status_code=400, detail="没有支持该职责模型的可用 Key")
    return role_config, key


def _serialize_project_image_asset(asset: VideoProjectImageAsset, task: Optional[ImageGenerationTask], results: list[ImageGenerationTaskResult]) -> dict:
    from routers.admin import image_result_file_url

    return {
        "id": asset.id,
        "image_task_id": asset.image_task_id,
        "asset_type": asset.asset_type,
        "title": asset.title,
        "storyboard_shot_index": asset.storyboard_shot_index,
        "prompt": asset.prompt,
        "status": task.status if task else "missing",
        "model": task.model if task else None,
        "error_detail": task.error_summary if task else "图片任务不存在",
        "results": [
            {
                "id": item.id,
                "status": item.status,
                "image_url": item.image_url,
                "local_url": image_result_file_url(item.id, item.local_path),
                "mime_type": item.mime_type,
                "error_detail": item.error_detail,
            }
            for item in results
        ],
        "created_at": asset.created_at,
    }




def _serialize_workflow(workflow: VideoProjectWorkflow, tasks: list[VideoProjectWorkflowTask]) -> dict:
    plan = json.loads(workflow.plan_json or "{}")
    review_history = json.loads(workflow.review_history_json or "[]")
    return {
        "id": workflow.id,
        "project_id": workflow.project_id,
        "status": workflow.status,
        "current_stage": workflow.current_stage,
        "auto_run": workflow.auto_run,
        "plan": plan,
        "review_history": review_history,
        "error_detail": workflow.error_detail,
        "tasks": [
            {
                "id": item.id, "task_type": item.task_type, "stage": item.stage,
                "status": item.status, "progress": item.progress, "sort_order": item.sort_order,
                "depends_on": json.loads(item.depends_on_json or "[]"),
                "input": json.loads(item.input_json or "{}"),
                "output": json.loads(item.output_json or "{}"),
                "retry_count": item.retry_count, "error_detail": item.error_detail,
            }
            for item in tasks
        ],
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
    }


async def _get_project_workflow(db: AsyncSession, project_id: int) -> tuple[Optional[VideoProjectWorkflow], list[VideoProjectWorkflowTask]]:
    workflow = await db.scalar(select(VideoProjectWorkflow).where(VideoProjectWorkflow.project_id == project_id))
    if not workflow:
        return None, []
    result = await db.execute(select(VideoProjectWorkflowTask).where(
        VideoProjectWorkflowTask.workflow_id == workflow.id,
    ).order_by(VideoProjectWorkflowTask.sort_order, VideoProjectWorkflowTask.id))
    return workflow, list(result.scalars().all())


def _project_input_hash(project: VideoCreativeProject, extra: dict | None = None) -> str:
    payload = {
        "title": project.title,
        "source_text": project.source_text,
        "analysis": project.analysis_json,
        "script": project.script_json,
        "storyboard": project.storyboard_json,
        "extra": extra or {},
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _load_project_storyboard(project: VideoCreativeProject) -> list[dict]:
    try:
        value = json.loads(project.storyboard_json or "[]")
        return value if isinstance(value, list) else []
    except json.JSONDecodeError:
        return []


def _normalize_director_shots(raw_shots: object, *, aspect_ratio: str, shot_count: int | None = None) -> list[dict]:
    if isinstance(raw_shots, dict):
        raw_shots = raw_shots.get("shots") or raw_shots.get("storyboard") or []
    if not isinstance(raw_shots, list):
        raise HTTPException(status_code=502, detail="导演 Agent 未返回镜头数组")
    shots: list[dict] = []
    for index, item in enumerate(raw_shots[:shot_count or len(raw_shots)]):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("visual_prompt") or item.get("prompt") or item.get("description") or "").strip()
        if not prompt:
            raise HTTPException(status_code=502, detail=f"分镜 {index + 1} 缺少视觉提示词")
        duration = int(float(item.get("duration_seconds") or item.get("seconds") or 5))
        duration = min(12, max(4, duration))
        scene = str(item.get("scene") or item.get("title") or f"镜头 {index + 1}")[:200]
        shot_type = str(item.get("shot_type") or item.get("camera") or "medium")[:100]
        camera_motion = str(item.get("camera_motion") or item.get("motion") or "static")[:100]
        shots.append({
            "shot_index": index,
            "scene": scene,
            "scene_no": item.get("scene_no") or 1,
            "shot_no": item.get("shot_no") or index + 1,
            "title": scene,
            "duration_seconds": duration,
            "shot_type": shot_type,
            "camera": shot_type,
            "camera_motion": camera_motion,
            "motion": camera_motion,
            "visual_prompt": prompt[:4000],
            "negative_prompt": str(item.get("negative_prompt") or "")[:1000],
            "narration": str(item.get("narration") or item.get("voiceover") or "")[:4000],
            "dialogue": str(item.get("dialogue") or "")[:4000],
            "sound_cue": str(item.get("sound_cue") or item.get("sfx") or "")[:1000],
            "asset_refs": item.get("asset_refs") if isinstance(item.get("asset_refs"), list) else [],
            "transition": str(item.get("transition") or "cut")[:100],
            "aspect_ratio": str(item.get("aspect_ratio") or aspect_ratio),
            "production_status": "planned",
            "revision": 1,
        })
    if not shots:
        raise HTTPException(status_code=502, detail="导演 Agent 未返回有效分镜")
    for shot in shots:
        _ensure_shot_revision(shot)
    return shots


def _json_object(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _workflow_plan(workflow: VideoProjectWorkflow | None) -> dict:
    if not workflow:
        return {}
    try:
        value = json.loads(workflow.plan_json or "{}")
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        return {}


def _director_plan_version(plan: dict) -> str:
    return str(plan.get("plan_version") or "manual-1")


def _shot_revision_input(shot: dict) -> dict:
    return {
        "scene_no": shot.get("scene_no"),
        "shot_no": shot.get("shot_no"),
        "duration_seconds": shot.get("duration_seconds"),
        "visual_prompt": shot.get("visual_prompt"),
        "negative_prompt": shot.get("negative_prompt", ""),
        "camera": shot.get("camera", shot.get("shot_type", "medium")),
        "motion": shot.get("motion", shot.get("camera_motion", "static")),
        "aspect_ratio": shot.get("aspect_ratio"),
        "narration": shot.get("narration", ""),
        "dialogue": shot.get("dialogue", ""),
        "sound_cue": shot.get("sound_cue", ""),
        "reference_asset_ids": shot.get("reference_asset_ids", []),
    }


def _shot_input_hash(shot: dict) -> str:
    return hashlib.sha256(json.dumps(_shot_revision_input(shot), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _ensure_shot_revision(shot: dict) -> dict:
    if not shot.get("revision"):
        shot["revision"] = 1
    shot.setdefault("input_hash", _shot_input_hash(shot))
    return shot


def _video_task_shot_revision(item: VideoGenerationTask) -> int:
    try:
        value = json.loads(item.request_params_json or "{}").get("director_shot_revision")
        return int(value or 1)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 1



def _shot_audio_text(shot: dict) -> str:
    values = [str(shot.get("narration") or "").strip()]
    dialogue = shot.get("dialogue")
    if isinstance(dialogue, list):
        values.extend(str(item.get("line") or item.get("text") or "").strip() for item in dialogue if isinstance(item, dict))
    else:
        values.append(str(dialogue or "").strip())
    return "\n".join(value for value in values if value)


async def _get_or_create_director_workflow_task(db: AsyncSession, workflow_id: int, stage: str, shot_index: int, revision: int, *, depends_on: list[int] | None = None, input_hash: str = "") -> tuple[VideoProjectWorkflowTask, bool]:
    result = await db.execute(select(VideoProjectWorkflowTask).where(
        VideoProjectWorkflowTask.workflow_id == workflow_id,
        VideoProjectWorkflowTask.task_type == "director_shot",
        VideoProjectWorkflowTask.stage == stage,
    ))
    for item in result.scalars().all():
        try:
            value = json.loads(item.input_json or "{}")
        except json.JSONDecodeError:
            value = {}
        if value.get("shot_index") == shot_index and value.get("revision") == revision:
            return item, False
    task = VideoProjectWorkflowTask(
        workflow_id=workflow_id,
        task_type="director_shot",
        stage=stage,
        status="blocked" if depends_on else "pending",
        sort_order=1000 + shot_index * 10 + {"video": 0, "audio": 1, "subtitle": 2}[stage],
        depends_on_json=json.dumps(depends_on or []),
        input_json=json.dumps({"shot_index": shot_index, "revision": revision, "input_hash": input_hash}, ensure_ascii=False),
    )
    db.add(task)
    await db.flush()
    return task, True


async def _get_or_create_project_workflow(db: AsyncSession, project_id: int) -> tuple[VideoProjectWorkflow, list[VideoProjectWorkflowTask]]:
    workflow, tasks = await _get_project_workflow(db, project_id)
    if workflow:
        return workflow, tasks
    workflow = VideoProjectWorkflow(project_id=project_id, status="draft", current_stage="director")
    db.add(workflow)
    await db.flush()
    return workflow, []


async def _director_status(db: AsyncSession, project: VideoCreativeProject, request: Request | None = None) -> dict:
    workflow, tasks = await _get_project_workflow(db, project.id)
    plan = _workflow_plan(workflow)
    shots = plan.get("shots") if isinstance(plan.get("shots"), list) else _load_project_storyboard(project)
    video_result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.project_id == project.id))
    video_tasks = list(video_result.scalars().all())
    audio_result = await db.execute(select(VideoProjectAudioTask).where(VideoProjectAudioTask.project_id == project.id))
    audio_tasks = list(audio_result.scalars().all())
    subtitle_result = await db.execute(select(VideoProjectSubtitleTask).where(VideoProjectSubtitleTask.project_id == project.id))
    subtitle_tasks = list(subtitle_result.scalars().all())
    workflow_director_tasks = [item for item in tasks if item.task_type == "director_shot"]
    director_task_by_key = {}
    for item in workflow_director_tasks:
        info = _json_object(item.input_json)
        director_task_by_key[(item.stage, info.get("shot_index"), info.get("revision"))] = item
    timeline_result = await db.execute(select(VideoProjectTimelineItem).where(VideoProjectTimelineItem.project_id == project.id))
    timeline_items = list(timeline_result.scalars().all())
    video_by_shot: dict[int, list[VideoGenerationTask]] = {}
    for item in video_tasks:
        try:
            params = json.loads(item.request_params_json or "{}")
        except json.JSONDecodeError:
            params = {}
        shot_index = params.get("storyboard_shot_index")
        if shot_index is not None:
            video_by_shot.setdefault(int(shot_index), []).append(item)
    shot_statuses = []
    for index, shot in enumerate(shots):
        if isinstance(shot, dict):
            _ensure_shot_revision(shot)
        shot_index = int(shot.get("shot_index", index)) if isinstance(shot, dict) else index
        revision = int(shot.get("revision") or 1) if isinstance(shot, dict) else 1
        current_related = [item for item in video_by_shot.get(shot_index, []) if _video_task_shot_revision(item) == revision]
        historical_related = [item for item in video_by_shot.get(shot_index, []) if _video_task_shot_revision(item) not in {None, revision}]
        completed_video = next((item for item in current_related if item.status == "completed"), None)
        failed_video = next((item for item in current_related if item.status == "failed"), None)
        running_video = next((item for item in current_related if item.status in {"creating", "pending", "processing", "running"}), None)
        status = "completed" if completed_video else "failed" if failed_video else "running" if running_video else "planned"
        task_info = {}
        for stage in ("video", "audio", "subtitle"):
            workflow_task = director_task_by_key.get((stage, shot_index, revision))
            if workflow_task:
                task_info[stage] = {
                    "task_id": workflow_task.id,
                    "status": workflow_task.status,
                    "progress": workflow_task.progress,
                    "retry_count": workflow_task.retry_count,
                    "error_detail": workflow_task.error_detail,
                    "output": _json_object(workflow_task.output_json),
                }
            else:
                task_info[stage] = {"status": "skipped" if stage != "video" and not _shot_audio_text(shot) else "not_created"}
        audio_current = next((item for item in audio_tasks if item.storyboard_shot_index == shot_index and int(item.director_shot_revision or 1) == revision), None)
        subtitle_current = next((item for item in subtitle_tasks if item.storyboard_shot_index == shot_index and int(item.director_shot_revision or 1) == revision), None)
        task_info["audio_artifact"] = {"id": audio_current.id, "status": audio_current.status} if audio_current else None
        task_info["subtitle_artifact"] = {"id": subtitle_current.id, "status": subtitle_current.status} if subtitle_current else None
        shot_statuses.append({
            "shot_index": shot_index,
            "revision": revision,
            "scene": shot.get("scene") if isinstance(shot, dict) else f"镜头 {shot_index + 1}",
            "status": status,
            "has_historical_artifacts": bool(historical_related),
            "video_task_id": completed_video.id if completed_video else running_video.id if running_video else failed_video.id if failed_video else None,
            "error_detail": failed_video.error_detail if failed_video else None,
            "tasks": task_info,
        })

    return {
        "workflow": _serialize_workflow(workflow, tasks) if workflow else None,
        "plan_version": _director_plan_version(plan),
        "input_hash": plan.get("input_hash"),
        "review_status": plan.get("review_status") or (workflow.status if workflow else "draft"),
        "shots": shots,
        "shot_statuses": shot_statuses,
        "video_count": len(video_tasks),
        "audio_count": len(audio_tasks),
        "timeline_count": len(timeline_items),
    }


async def _create_workflow_plan(db: AsyncSession, project: VideoCreativeProject, data: WorkflowPlanRequest, user_id: Optional[int]) -> dict:
    request = VideoCreativeAgentRequest(model=data.model, source=data.source, stage="analysis")
    attachments_result = await db.execute(select(VideoProjectAttachment).where(
        VideoProjectAttachment.project_id == project.id,
    ).order_by(VideoProjectAttachment.id))
    attachment_context = [
        {"name": item.original_name, "text": (item.extracted_text or "")[:30000]}
        for item in attachments_result.scalars().all()
    ]
    context = {"title": project.title, "source_text": project.source_text, "attachments": attachment_context}
    instruction = f"你是影视制作总控 Agent。项目默认画幅为 {project.default_aspect_ratio or '9:16'}；移动端竖屏项目需主体居中、保留上下安全区。根据项目资料输出严格 JSON 对象：total_duration_seconds、aspect_ratio、visual_style、characters（数组）、scenes（数组）、shot_count、stages（数组，元素含 stage、task_type、description、requires_review）、audio_policy（默认 preserve_native）、subtitle_policy（默认 asr_from_native_audio）、budget_summary（对象）。计划必须按 analysis、script、storyboard、assets、video、audio、subtitle、timeline、export 顺序安排，不要 Markdown。"
    original_prompts = {
        "analysis": "分析以下小说或创作素材，输出严格 JSON 对象：summary、themes、characters（数组，含 name、description、appearance）、scenes（数组，含 name、description）、story_beats（数组）。不要 Markdown。",
    }
    # 复用创作 Agent 的模型/来源路由，仅替换用于总控计划的指令。
    prompts = original_prompts
    _ = prompts
    body = {"model": request.model, "messages": [{"role": "system", "content": "你是影视制作总控 Agent。输出必须是可解析 JSON。"}, {"role": "user", "content": f"{instruction}\n\n项目资料：\n{json.dumps(context, ensure_ascii=False)}"}], "temperature": 0.4}
    force_providers, key = None, None
    if request.source:
        prefix, _, value = request.source.partition(":")
        if prefix == "provider":
            force_providers = [value]
        elif prefix == "key":
            key = await pool_manager.get_key_by_id(db, int(value))
            if not key or not pool_manager.is_key_available_for_model(key, request.model):
                raise HTTPException(status_code=400, detail="指定 Key 不可用于总控 Agent 模型")
    if key:
        upstream_body, _ = await build_upstream_body_for_key(db, key, body, request.model)
        status_code, _, response_data = await proxy_service.forward_request(db=db, api_key=key, method="POST", path="v1/chat/completions", headers={"content-type": "application/json"}, body=upstream_body, user_id=user_id, original_model=request.model)
    else:
        status_code, _, response_data, _ = await forward_request_with_retry(db, "POST", "v1/chat/completions", {"content-type": "application/json"}, body, user_id=user_id, original_model=request.model, force_providers=force_providers)
    if status_code < 200 or status_code >= 300:
        raise HTTPException(status_code=502, detail="总控 Agent 调用失败")
    return _extract_agent_json(response_data)


@router.post("/video/creative-projects/{project_id}/director/storyboard")
async def create_director_storyboard(project_id: int, data: DirectorStoryboardRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    existing = _load_project_storyboard(project)
    if existing and not data.regenerate:
        workflow, _ = await _get_project_workflow(db, project_id)
        plan = _workflow_plan(workflow)
        return {"project_id": project_id, "reused": True, "plan_version": _director_plan_version(plan), "review_status": plan.get("review_status") or "awaiting_storyboard_review", "shots": _normalize_director_shots(existing, aspect_ratio=data.aspect_ratio or project.default_aspect_ratio or "9:16")}
    result = await _run_creative_agent(
        db,
        project,
        VideoCreativeAgentRequest(model=data.model, source=data.source, stage="storyboard"),
        auth.get("user_id"),
    )
    shots = _normalize_director_shots(
        result,
        aspect_ratio=data.aspect_ratio or project.default_aspect_ratio or "9:16",
        shot_count=data.shot_count,
    )
    total_duration_ms = sum(item["duration_seconds"] for item in shots) * 1000
    plan_version = f"director-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    workflow, tasks = await _get_or_create_project_workflow(db, project_id)
    plan = _workflow_plan(workflow)
    plan.update({
        "plan_version": plan_version,
        "input_hash": _project_input_hash(project, {"target_duration_seconds": data.target_duration_seconds, "shot_count": data.shot_count}),
        "director_model": data.model,
        "director_source": data.source,
        "aspect_ratio": data.aspect_ratio or project.default_aspect_ratio or "9:16",
        "target_duration_ms": data.target_duration_seconds * 1000,
        "shots": shots,
        "shot_count": len(shots),
        "total_duration_ms": total_duration_ms,
        "style_preset_id": data.style_preset_id,
        "review_status": "awaiting_storyboard_review",
    })
    project.storyboard_json = json.dumps(shots, ensure_ascii=False)
    workflow.status = "awaiting_storyboard_review"
    workflow.current_stage = "storyboard"
    workflow.plan_json = json.dumps(plan, ensure_ascii=False)
    workflow.error_detail = None
    storyboard_task = next((item for item in tasks if item.stage == "storyboard"), None)
    if storyboard_task:
        storyboard_task.status = "completed"
        storyboard_task.progress = 100
        storyboard_task.output_json = json.dumps({"plan_version": plan_version, "shots": shots}, ensure_ascii=False)
    await db.commit()
    return {"project_id": project_id, "reused": False, "plan_version": plan_version, "review_status": plan["review_status"], "shots": shots, "total_duration_ms": total_duration_ms}


@router.put("/video/creative-projects/{project_id}/director/shots/{shot_index}")
async def update_director_shot(project_id: int, shot_index: int, data: DirectorShotUpdateRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    workflow, _ = await _get_or_create_project_workflow(db, project_id)
    plan = _workflow_plan(workflow)
    shots = plan.get("shots") if isinstance(plan.get("shots"), list) else _load_project_storyboard(project)
    shot = next((item for index, item in enumerate(shots) if isinstance(item, dict) and int(item.get("shot_index", index)) == shot_index), None)
    if not shot:
        raise HTTPException(status_code=404, detail="分镜不存在")
    _ensure_shot_revision(shot)
    previous_input = _shot_revision_input(shot)
    update = data.model_dump()
    shot.update({
        "scene_no": update["scene_no"], "shot_no": update["shot_no"], "duration_seconds": update["duration_seconds"],
        "visual_prompt": update["visual_prompt"].strip(), "negative_prompt": update["negative_prompt"].strip(),
        "camera": update["camera"].strip(), "shot_type": update["camera"].strip(),
        "motion": update["motion"].strip(), "camera_motion": update["motion"].strip(),
        "aspect_ratio": update["aspect_ratio"], "narration": update["narration"].strip(),
        "dialogue": update["dialogue"], "sound_cue": update["sound_cue"].strip(),
        "reference_asset_ids": update["reference_asset_ids"],
    })
    changed = previous_input != _shot_revision_input(shot)
    removed_timeline_items = 0
    if changed:
        shot["revision"] = int(shot["revision"]) + 1
        shot["input_hash"] = _shot_input_hash(shot)
        shot["production_status"] = "stale"
        deleted = await db.execute(delete(VideoProjectTimelineItem).where(
            VideoProjectTimelineItem.project_id == project_id,
            VideoProjectTimelineItem.storyboard_shot_index == shot_index,
        ))
        removed_timeline_items = int(deleted.rowcount or 0)
    plan["shots"] = shots
    workflow.plan_json = json.dumps(plan, ensure_ascii=False)
    project.storyboard_json = json.dumps(shots, ensure_ascii=False)
    await db.commit()
    return {"project_id": project_id, "shot": shot, "changed": changed, "removed_timeline_items": removed_timeline_items}


@router.get("/video/creative-projects/{project_id}/director/status")
async def get_director_status(project_id: int, request: Request, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    return await _director_status(db, project, request)


@router.post("/video/creative-projects/{project_id}/director/produce")
async def produce_director_shots(project_id: int, data: DirectorProduceRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    workflow, tasks = await _get_or_create_project_workflow(db, project_id)
    plan = _workflow_plan(workflow)
    shots = plan.get("shots") if isinstance(plan.get("shots"), list) else _load_project_storyboard(project)
    if not shots:
        raise HTTPException(status_code=409, detail="请先生成导演分镜")
    if plan.get("review_status") == "awaiting_storyboard_review" and not data.force:
        raise HTTPException(status_code=409, detail="请先审核导演分镜")
    requested = set(data.shot_indexes)
    invalid = requested - {int(item.get("shot_index", index)) for index, item in enumerate(shots) if isinstance(item, dict)}
    if invalid:
        raise HTTPException(status_code=422, detail=f"不存在的镜头编号：{sorted(invalid)}")
    director_tasks = []
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        _ensure_shot_revision(shot)
        shot_index = int(shot.get("shot_index", index))
        if requested and shot_index not in requested:
            continue
        revision = int(shot["revision"])
        input_hash = str(shot.get("input_hash") or "")
        video_task, video_created = await _get_or_create_director_workflow_task(db, workflow.id, "video", shot_index, revision, input_hash=input_hash)
        audio_task = subtitle_task = None
        audio_created = subtitle_created = False
        if _shot_audio_text(shot):
            audio_task, audio_created = await _get_or_create_director_workflow_task(db, workflow.id, "audio", shot_index, revision, input_hash=input_hash)
            subtitle_task, subtitle_created = await _get_or_create_director_workflow_task(db, workflow.id, "subtitle", shot_index, revision, depends_on=[audio_task.id], input_hash=input_hash)
        for workflow_task in (video_task, audio_task, subtitle_task):
            if workflow_task and workflow_task.status == "failed" and (data.regenerate_failed or data.force):
                workflow_task.status = "pending"
                workflow_task.error_detail = None
                workflow_task.finished_at = None
        director_tasks.append({"shot_index": shot_index, "revision": revision, "video_task_id": video_task.id, "audio_task_id": audio_task.id if audio_task else None, "subtitle_task_id": subtitle_task.id if subtitle_task else None, "created": video_created or audio_created or subtitle_created})
    plan["director_scheduler"] = {"video_concurrency": data.video_concurrency, "audio_concurrency": data.audio_concurrency, "subtitle_concurrency": data.subtitle_concurrency}
    workflow.plan_json = json.dumps(plan, ensure_ascii=False)
    workflow.status = "running"
    workflow.current_stage = "video"
    await db.commit()
    from .video_workflow_queue_service import video_workflow_queue_service
    video_workflow_queue_service.configure(workflow.id, data.video_concurrency, data.audio_concurrency, data.subtitle_concurrency)
    await video_workflow_queue_service.start(workflow.id)
    return {"project_id": project_id, "plan_version": _director_plan_version(plan), "created_task_ids": [item["video_task_id"] for item in director_tasks if item["created"]], "reused_task_ids": [item["video_task_id"] for item in director_tasks if not item["created"]], "blocked_failed_task_ids": [], "audio_task_ids": [item["audio_task_id"] for item in director_tasks if item["audio_task_id"]], "subtitle_task_ids": [item["subtitle_task_id"] for item in director_tasks if item["subtitle_task_id"]], "director_tasks": director_tasks, "video_concurrency": data.video_concurrency, "audio_concurrency": data.audio_concurrency, "subtitle_concurrency": data.subtitle_concurrency, "requested_shot_indexes": sorted(requested) if requested else [item["shot_index"] for item in director_tasks]}

    role, key = await _get_project_role_key(db, project_id, "video")
    result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.project_id == project_id))
    existing_tasks = list(result.scalars().all())
    created_ids: list[int] = []
    reused_ids: list[int] = []
    failed_ids: list[int] = []
    from .video import VideoGenerateRequest as _VideoGenerateRequest
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        shot_index = int(shot.get("shot_index", index))
        _ensure_shot_revision(shot)
        revision = int(shot["revision"])
        if requested and shot_index not in requested:
            continue
        related = []
        for item in existing_tasks:
            try:
                params = json.loads(item.request_params_json or "{}")
            except json.JSONDecodeError:
                params = {}
            if params.get("storyboard_shot_index") == shot_index and int(params.get("director_shot_revision") or 1) == revision:
                related.append(item)
        completed = next((item for item in related if item.status == "completed"), None)
        if completed and not data.force:
            reused_ids.append(completed.id)
            continue
        failed = next((item for item in related if item.status == "failed"), None)
        if failed and not (data.regenerate_failed or data.force):
            failed_ids.append(failed.id)
            continue
        generated = await generate_video(_VideoGenerateRequest(
            project_id=project_id,
            storyboard_shot_index=shot_index,
            director_shot_revision=revision,
            director_shot_input_hash=str(shot["input_hash"]),
            model=role.model,
            prompt=str(shot["visual_prompt"]),
            mode="text",
            seconds=str(shot.get("duration_seconds") or 5),
            aspect_ratio=str(shot.get("aspect_ratio") or plan.get("aspect_ratio") or project.default_aspect_ratio or "9:16"),
        ), db, auth)
        if generated.get("id"):
            created_ids.append(int(generated["id"]))
    audio_task_ids: list[int] = []
    subtitle_task_ids: list[int] = []
    audio_blockers: list[dict] = []
    existing_audio_result = await db.execute(select(VideoProjectAudioTask).where(VideoProjectAudioTask.project_id == project_id))
    existing_audio = list(existing_audio_result.scalars().all())
    for index, shot in enumerate(shots):
        if not isinstance(shot, dict):
            continue
        shot_index = int(shot.get("shot_index", index))
        _ensure_shot_revision(shot)
        revision = int(shot["revision"])
        if requested and shot_index not in requested:
            continue
        text_parts = [str(shot.get("narration") or "").strip()]
        dialogue = shot.get("dialogue")
        if isinstance(dialogue, list):
            text_parts.extend(
                str(item.get("line") or item.get("text") or "").strip()
                for item in dialogue
                if isinstance(item, dict)
            )
        else:
            text_parts.append(str(dialogue or "").strip())
        audio_text = "\n".join(item for item in text_parts if item)
        if not audio_text:
            continue
        existing_audio_task = next(
            (item for item in existing_audio if item.storyboard_shot_index == shot_index and item.director_shot_revision == revision and item.status in {"pending", "running", "completed"}),
            None,
        )
        if existing_audio_task:
            audio_task_ids.append(existing_audio_task.id)
            continue
        try:
            audio_request = SimpleNamespace(base_url="http://workflow.local/")
            audio_result_item = await create_project_audio(
                project_id,
                ProjectTtsRequest(text=audio_text, storyboard_shot_index=shot_index, director_shot_revision=revision),
                audio_request,
                db,
                auth,
            )
            audio_task_id = int(audio_result_item["id"])
            audio_task_ids.append(audio_task_id)
            if audio_result_item.get("status") != "completed":
                audio_blockers.append({"shot_index": shot_index, "reason": audio_result_item.get("error_detail") or "配音尚未完成"})
                continue
            try:
                subtitle_result_item = await create_project_subtitle(
                    project_id,
                    ProjectAsrRequest(audio_task_id=audio_task_id, language="zh", storyboard_shot_index=shot_index),
                    db,
                    auth,
                )
                if subtitle_result_item.get("id"):
                    subtitle_task_ids.append(int(subtitle_result_item["id"]))
            except HTTPException as exc:
                audio_blockers.append({"shot_index": shot_index, "reason": f"字幕未生成：{exc.detail}"})
        except HTTPException as exc:
            audio_blockers.append({"shot_index": shot_index, "reason": str(exc.detail)})

    plan["production_status"] = "running" if created_ids else "ready"
    plan["production_plan_version"] = _director_plan_version(plan)
    workflow.plan_json = json.dumps(plan, ensure_ascii=False)
    await db.commit()
    return {"project_id": project_id, "plan_version": _director_plan_version(plan), "created_task_ids": created_ids, "reused_task_ids": reused_ids, "blocked_failed_task_ids": failed_ids, "audio_task_ids": audio_task_ids, "subtitle_task_ids": subtitle_task_ids, "audio_blockers": audio_blockers, "requested_shot_indexes": sorted(requested) if requested else [int(item.get("shot_index", index)) for index, item in enumerate(shots) if isinstance(item, dict)]}


@router.post("/video/creative-projects/{project_id}/director/auto-schedule")
async def auto_schedule_director_project(project_id: int, data: DirectorAutoScheduleRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    workflow, _ = await _get_project_workflow(db, project_id)
    plan = _workflow_plan(workflow)
    shots = plan.get("shots") if isinstance(plan.get("shots"), list) else _load_project_storyboard(project)
    if not shots:
        raise HTTPException(status_code=409, detail="请先生成导演分镜")
    result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.project_id == project_id))
    video_tasks = list(result.scalars().all())
    by_shot: dict[tuple[int, int], VideoGenerationTask] = {}
    for item in video_tasks:
        try:
            params = json.loads(item.request_params_json or "{}")
        except json.JSONDecodeError:
            params = {}
        shot_index = params.get("storyboard_shot_index")
        revision = params.get("director_shot_revision")
        if shot_index is not None and item.status == "completed":
            by_shot[(int(shot_index), int(revision or 1))] = item
    blockers = []
    ordered = []
    for index, shot in enumerate(shots):
        _ensure_shot_revision(shot)
        shot_index = int(shot.get("shot_index", index))
        video_task = by_shot.get((shot_index, int(shot["revision"])))
        if not video_task:
            blockers.append({"shot_index": shot_index, "reason": "视频尚未完成"})
        else:
            ordered.append((shot_index, video_task, shot))
    if blockers:
        return {"project_id": project_id, "plan_version": _director_plan_version(plan), "scheduled": False, "blockers": blockers, "video_count": len(ordered)}
    if data.include_audio or data.include_subtitles:
        pending_audio_result = await db.execute(select(VideoProjectAudioTask).where(
            VideoProjectAudioTask.project_id == project_id,
            VideoProjectAudioTask.storyboard_shot_index.is_not(None),
            VideoProjectAudioTask.status != "completed",
        ))
        pending_audio = list(pending_audio_result.scalars().all())
        if data.include_audio and pending_audio:
            return {"project_id": project_id, "plan_version": _director_plan_version(plan), "scheduled": False, "blockers": [{"shot_index": item.storyboard_shot_index, "reason": "配音尚未完成"} for item in pending_audio], "video_count": len(ordered)}
    if data.clear_existing_director_items:
        await db.execute(delete(VideoProjectTimelineItem).where(
            VideoProjectTimelineItem.project_id == project_id,
            VideoProjectTimelineItem.storyboard_shot_index.is_not(None),
        ))
        await db.flush()

    audio_result = await db.execute(select(VideoProjectAudioTask).where(
        VideoProjectAudioTask.project_id == project_id,
        VideoProjectAudioTask.status == "completed",
    ))
    audio_by_shot = {
        (int(item.storyboard_shot_index), int(item.director_shot_revision or 1)): item
        for item in audio_result.scalars().all()
        if item.storyboard_shot_index is not None
    }
    subtitle_result = await db.execute(select(VideoProjectSubtitleTask).where(
        VideoProjectSubtitleTask.project_id == project_id,
        VideoProjectSubtitleTask.status == "completed",
    ))
    subtitle_by_shot = {
        (int(item.storyboard_shot_index), int(item.director_shot_revision or 1)): item
        for item in subtitle_result.scalars().all()
        if item.storyboard_shot_index is not None
    }

    timeline_ids: list[int] = []
    audio_count = 0
    subtitle_count = 0
    offset_ms = 0
    for position, (shot_index, video_task, shot) in enumerate(ordered):
        revision = int(shot.get("revision") or 1)
        existing = await db.scalar(select(VideoProjectTimelineItem).where(VideoProjectTimelineItem.project_id == project_id, VideoProjectTimelineItem.source_type == "video_task", VideoProjectTimelineItem.source_id == video_task.id))
        duration_ms = int(float(shot.get("duration_seconds") or video_task.seconds or 5) * 1000)
        if not existing:
            existing = VideoProjectTimelineItem(project_id=project_id, track="video", source_type="video_task", source_id=video_task.id, position=position, offset_ms=offset_ms, duration_ms=duration_ms, storyboard_shot_index=shot_index)
            db.add(existing)
            await db.flush()
        else:
            existing.position = position
            existing.offset_ms = offset_ms
            existing.duration_ms = duration_ms
            existing.storyboard_shot_index = shot_index
        timeline_ids.append(existing.id)

        if data.include_audio and (shot_index, revision) in audio_by_shot:
            audio_task = audio_by_shot[(shot_index, revision)]
            audio_item = await db.scalar(select(VideoProjectTimelineItem).where(
                VideoProjectTimelineItem.project_id == project_id,
                VideoProjectTimelineItem.track == "audio",
                VideoProjectTimelineItem.source_type == "audio_task",
                VideoProjectTimelineItem.source_id == audio_task.id,
            ))
            if not audio_item:
                audio_item = VideoProjectTimelineItem(project_id=project_id, track="audio", source_type="audio_task", source_id=audio_task.id, position=position, offset_ms=offset_ms, duration_ms=duration_ms, storyboard_shot_index=shot_index)
                db.add(audio_item)
                await db.flush()
            else:
                audio_item.position = position
                audio_item.offset_ms = offset_ms
                audio_item.duration_ms = duration_ms
                audio_item.storyboard_shot_index = shot_index
            timeline_ids.append(audio_item.id)
            audio_count += 1

        if data.include_subtitles and (shot_index, revision) in subtitle_by_shot:
            subtitle_task = subtitle_by_shot[(shot_index, revision)]
            subtitle_item = await db.scalar(select(VideoProjectTimelineItem).where(
                VideoProjectTimelineItem.project_id == project_id,
                VideoProjectTimelineItem.track == "subtitle",
                VideoProjectTimelineItem.source_type == "subtitle_task",
                VideoProjectTimelineItem.source_id == subtitle_task.id,
            ))
            if not subtitle_item:
                subtitle_item = VideoProjectTimelineItem(project_id=project_id, track="subtitle", source_type="subtitle_task", source_id=subtitle_task.id, position=position, offset_ms=offset_ms, duration_ms=duration_ms, storyboard_shot_index=shot_index)
                db.add(subtitle_item)
                await db.flush()
            else:
                subtitle_item.position = position
                subtitle_item.offset_ms = offset_ms
                subtitle_item.duration_ms = duration_ms
                subtitle_item.storyboard_shot_index = shot_index
            timeline_ids.append(subtitle_item.id)
            subtitle_count += 1

        offset_ms += duration_ms
    plan["timeline_version"] = f"{_director_plan_version(plan)}-timeline"
    plan["timeline_duration_ms"] = offset_ms
    plan["audio_strategy"] = data.audio_strategy
    workflow.plan_json = json.dumps(plan, ensure_ascii=False)
    await db.commit()
    return {"project_id": project_id, "plan_version": _director_plan_version(plan), "timeline_version": plan["timeline_version"], "scheduled": True, "blockers": [], "timeline_item_ids": timeline_ids, "video_count": len(ordered), "audio_count": audio_count, "subtitle_count": subtitle_count, "timeline_duration_ms": offset_ms, "audio_strategy": data.audio_strategy}


@router.get("/video/creative-projects/{project_id}/workflow")
async def get_project_workflow(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    workflow, tasks = await _get_project_workflow(db, project_id)
    return _serialize_workflow(workflow, tasks) if workflow else None


@router.post("/video/creative-projects/{project_id}/workflow/plan")
async def create_project_workflow_plan(project_id: int, data: WorkflowPlanRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    plan = await _create_workflow_plan(db, project, data, auth.get("user_id"))
    if not isinstance(plan, dict):
        raise HTTPException(status_code=502, detail="总控 Agent 未返回对象计划")
    plan["director_model"] = data.model
    plan["director_source"] = data.source
    workflow, existing_tasks = await _get_project_workflow(db, project_id)
    if not workflow:
        workflow = VideoProjectWorkflow(project_id=project_id)
        db.add(workflow)
        await db.flush()
    for item in existing_tasks:
        await db.delete(item)
    workflow.status = "awaiting_plan_review"
    workflow.current_stage = "plan"
    workflow.auto_run = data.auto_run
    workflow.plan_json = json.dumps(plan, ensure_ascii=False)
    workflow.error_detail = None
    workflow.review_history_json = json.dumps([], ensure_ascii=False)
    stages = plan.get("stages") if isinstance(plan, dict) else None
    allowed_stages = ["analysis", "script", "storyboard", "assets", "video", "audio", "subtitle", "timeline", "export"]
    requested_stage_names = [str(item.get("stage")) for item in stages if isinstance(item, dict) and item.get("stage")] if isinstance(stages, list) else []
    stage_names = [stage for stage in allowed_stages if stage in requested_stage_names] or allowed_stages
    for order, stage in enumerate(stage_names):
        db.add(VideoProjectWorkflowTask(workflow_id=workflow.id, task_type=f"{stage}_stage", stage=stage, status="blocked", sort_order=order, input_json=json.dumps({"requires_review": stage in {"analysis", "script", "storyboard"}}, ensure_ascii=False)))
    await db.commit()
    workflow, tasks = await _get_project_workflow(db, project_id)
    return _serialize_workflow(workflow, tasks)


@router.post("/video/creative-projects/{project_id}/workflow/review")
async def review_project_workflow(project_id: int, data: WorkflowReviewRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    workflow, tasks = await _get_project_workflow(db, project_id)
    if not project or not workflow or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目或工作流不存在")
    history = json.loads(workflow.review_history_json or "[]")
    history.append({"action": data.action, "stage": workflow.current_stage, "note": data.note or "", "at": datetime.utcnow().isoformat()})
    workflow.review_history_json = json.dumps(history, ensure_ascii=False)
    if data.action == "cancel":
        workflow.status, workflow.cancelled = "cancelled", True
        for item in tasks:
            if item.status in {"pending", "blocked"}:
                item.status = "cancelled"
    elif data.action == "pause":
        workflow.status = "paused"
    elif data.action == "resume":
        workflow.status = "running"
    elif data.action == "approve":
        workflow.status = "running"
        plan = _workflow_plan(workflow)
        if workflow.current_stage == "storyboard" and plan.get("shots"):
            plan["review_status"] = "approved"
            workflow.plan_json = json.dumps(plan, ensure_ascii=False)
        next_task = next((item for item in tasks if item.status == "blocked"), None)
        if next_task:
            next_task.status = "pending"
            workflow.current_stage = next_task.stage
    await db.commit()
    if data.action in {"approve", "resume"}:
        from .video_workflow_queue_service import video_workflow_queue_service

        await video_workflow_queue_service.start(workflow.id)
    workflow, tasks = await _get_project_workflow(db, project_id)
    return _serialize_workflow(workflow, tasks)


@router.post("/video/creative-projects/{project_id}/attachments")
async def upload_project_attachment(project_id: int, request: Request, file: UploadFile = File(...), db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_PROJECT_ATTACHMENT_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 TXT、Markdown、DOCX、PDF 附件")
    content = await file.read(MAX_PROJECT_ATTACHMENT_SIZE + 1)
    if not content or len(content) > MAX_PROJECT_ATTACHMENT_SIZE:
        raise HTTPException(status_code=400, detail="附件不能为空且不能超过 20MB")
    try:
        extracted_text = _extract_project_attachment_text(suffix, content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"附件文本提取失败：{exc}") from exc
    if not extracted_text:
        raise HTTPException(status_code=400, detail="附件未提取到可用文本，扫描版 PDF 暂不支持")
    PROJECT_ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)
    stored_path = PROJECT_ATTACHMENT_DIR / f"{uuid.uuid4().hex}{suffix}"
    stored_path.write_bytes(content)
    attachment = VideoProjectAttachment(project_id=project_id, original_name=_safe_asset_name(file.filename or f"attachment{suffix}"), stored_path=str(stored_path), content_type=file.content_type, file_size_bytes=len(content), extracted_text=extracted_text)
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return _serialize_project_attachment(attachment, request)


@router.get("/video/creative-projects/{project_id}/attachments")
async def list_project_attachments(project_id: int, request: Request, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    result = await db.execute(select(VideoProjectAttachment).where(VideoProjectAttachment.project_id == project_id).order_by(VideoProjectAttachment.id.desc()))
    return [_serialize_project_attachment(item, request) for item in result.scalars().all()]


@router.get("/video/creative-projects/{project_id}/attachments/{attachment_id}/file")
async def download_project_attachment(project_id: int, attachment_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    attachment = await db.get(VideoProjectAttachment, attachment_id)
    if not attachment or attachment.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目附件不存在")
    path = Path(attachment.stored_path)
    if not path.is_file() or path.parent.resolve() != PROJECT_ATTACHMENT_DIR.resolve():
        raise HTTPException(status_code=404, detail="附件文件不存在")
    return FileResponse(path, filename=attachment.original_name)


@router.delete("/video/creative-projects/{project_id}/attachments/{attachment_id}")
async def delete_project_attachment(project_id: int, attachment_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    attachment = await db.get(VideoProjectAttachment, attachment_id)
    if not attachment or attachment.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目附件不存在")
    path = Path(attachment.stored_path)
    if path.parent.resolve() == PROJECT_ATTACHMENT_DIR.resolve() and path.is_file():
        path.unlink()
    await db.delete(attachment)
    await db.commit()
    return {"id": attachment_id, "deleted": True}


@router.post("/video/creative-projects/{project_id}/images")
async def create_project_image(project_id: int, data: ProjectImageRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    if data.asset_type == "storyboard_reference":
        storyboard = json.loads(project.storyboard_json or "[]")
        if data.storyboard_shot_index is None or data.storyboard_shot_index >= len(storyboard):
            raise HTTPException(status_code=400, detail="分镜序号不存在")

    from routers.admin import (
        build_api_key_snapshot,
        get_image_model_config,
        key_supports_image_model,
        normalize_image_request_format,
        run_image_generation_task,
    )

    role_config, key = await _get_project_role_key(db, project_id, "image")
    if not key_supports_image_model(key, role_config.model):
        raise HTTPException(status_code=400, detail="项目图片职责指定 Key 不支持该模型")
    model_config = get_image_model_config(role_config.model)
    request_format = normalize_image_request_format(model_config, None)
    snapshot = build_api_key_snapshot(key)
    now = datetime.utcnow()
    task = ImageGenerationTask(
        provider=snapshot["provider"],
        api_key_id=snapshot["id"],
        api_key_name=snapshot["name"],
        base_url=snapshot["base_url"],
        model=role_config.model,
        prompt=data.prompt.strip(),
        request_params_json=json.dumps({
            "size": data.size,
            "quality": "auto",
            "count": 1,
            "request_format": request_format,
            "mode": "text_to_image",
            "project_id": project_id,
            "project_asset_type": data.asset_type,
            "storyboard_shot_index": data.storyboard_shot_index,
        }, ensure_ascii=False),
        status="running",
        total_count=1,
        started_at=now,
        updated_at=now,
        user_id=auth.get("user_id"),
    )
    db.add(task)
    await db.flush()
    asset = VideoProjectImageAsset(
        project_id=project_id,
        image_task_id=task.id,
        asset_type=data.asset_type,
        title=data.title.strip(),
        storyboard_shot_index=data.storyboard_shot_index,
        prompt=data.prompt.strip(),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    asyncio.create_task(run_image_generation_task(
        int(task.id),
        int(key.id),
        model=role_config.model,
        prompt=data.prompt.strip(),
        size=data.size,
        quality="auto",
        resolution=None,
        count=1,
        request_format=request_format,
        mode="text_to_image",
        input_images=[],
        provider_filter=key.provider if role_config.source_mode == "provider" else None,
        lock_key=role_config.source_mode == "key",
    ))
    return _serialize_project_image_asset(asset, task, [])


@router.get("/video/creative-projects/{project_id}/images")
async def list_project_images(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    result = await db.execute(select(VideoProjectImageAsset).where(
        VideoProjectImageAsset.project_id == project_id,
    ).order_by(VideoProjectImageAsset.id.desc()))
    assets = result.scalars().all()
    if not assets:
        return []
    task_ids = [item.image_task_id for item in assets]
    tasks_result = await db.execute(select(ImageGenerationTask).where(ImageGenerationTask.id.in_(task_ids)))
    tasks = {item.id: item for item in tasks_result.scalars().all()}
    results_result = await db.execute(select(ImageGenerationTaskResult).where(
        ImageGenerationTaskResult.task_id.in_(task_ids),
    ).order_by(ImageGenerationTaskResult.image_index, ImageGenerationTaskResult.id))
    results_by_task = {}
    for image_result in results_result.scalars().all():
        results_by_task.setdefault(image_result.task_id, []).append(image_result)
    return [
        _serialize_project_image_asset(item, tasks.get(item.image_task_id), results_by_task.get(item.image_task_id, []))
        for item in assets
    ]



def _serialize_voice_profile(item: VideoProjectVoiceProfile) -> dict:
    return {
        "id": item.id,
        "project_id": item.project_id,
        "profile_type": item.profile_type,
        "name": item.name,
        "character_asset_id": item.character_asset_id,
        "character_name_snapshot": item.character_name_snapshot,
        "voice": item.voice,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _serialize_project_audio(item: VideoProjectAudioTask, request: Request | None = None) -> dict:
    base_url = str(request.base_url).rstrip("/") if request else ""
    return {
        "id": item.id,
        "project_id": item.project_id,
        "provider": item.provider,
        "model": item.model,
        "voice": item.voice,
        "voice_profile_id": item.voice_profile_id,
        "speaker_type": item.speaker_type,
        "speaker_name_snapshot": item.speaker_name_snapshot,
        "input_text": item.input_text,
        "status": item.status,
        "queue_position": item.queue_position,
        "storyboard_shot_index": item.storyboard_shot_index,
        "director_shot_revision": item.director_shot_revision,
        "audio_url": item.audio_url or (f"{base_url}/api/admin/video/project-audio/{item.id}/file" if item.local_path else None),
        "error_detail": item.error_detail,
        "created_at": item.created_at,
        "started_at": item.started_at,
        "finished_at": item.finished_at,
    }


async def _run_project_audio_task(task_id: int, base_url: str) -> None:
    async with async_session_maker() as task_db:
        task = await task_db.get(VideoProjectAudioTask, task_id)
        if not task or task.status != "pending":
            return
        project_id = task.project_id
    lock = PROJECT_AUDIO_QUEUE_LOCKS.setdefault(project_id, asyncio.Lock())
    async with lock:
        async with async_session_maker() as task_db:
            task = await task_db.get(VideoProjectAudioTask, task_id)
            if not task or task.status != "pending":
                return
            project = await task_db.get(VideoCreativeProject, task.project_id)
            if not project:
                task.status = "failed"
                task.error_detail = "创作项目不存在"
                await task_db.commit()
                return
            key = await pool_manager.get_key_by_id(task_db, task.api_key_id) if task.api_key_id else None
            if not key:
                task.status = "failed"
                task.error_detail = "配音任务的 API Key 不可用"
                task.finished_at = datetime.utcnow()
                await task_db.commit()
                return
            task.status = "running"
            task.started_at = datetime.utcnow()
            await task_db.commit()
            try:
                local_path = await project_audio_service.synthesize(
                    key,
                    model=task.model,
                    voice=task.voice or "alloy",
                    text=task.input_text,
                    task_id=task.id,
                )
                task.local_path = local_path
                task.audio_url = f"{base_url}/api/admin/video/project-audio/{task.id}/file"
                task.status = "completed"
            except Exception as exc:
                task.status = "failed"
                detail = str(exc).strip() or type(exc).__name__
                cause = getattr(exc, "__cause__", None)
                if cause and str(cause).strip() and str(cause).strip() not in detail:
                    detail = f"{detail} ({type(cause).__name__}: {str(cause).strip()})"
                task.error_detail = detail[:4000]
            task.finished_at = datetime.utcnow()
            await task_db.commit()


async def _resolve_voice_profile(
    db: AsyncSession,
    project_id: int,
    data: ProjectTtsRequest | ProjectAudioTaskUpdateRequest,
) -> tuple[Optional[int], str, Optional[str], str]:
    speaker_type_value = getattr(data, "speaker_type", "narrator") or "narrator"
    if speaker_type_value not in {"narrator", "character"}:
        raise HTTPException(status_code=422, detail="不支持的配音身份")
    profile = None
    if getattr(data, "voice_profile_id", None) is not None:
        profile = await db.scalar(select(VideoProjectVoiceProfile).where(
            VideoProjectVoiceProfile.id == getattr(data, "voice_profile_id", None),
            VideoProjectVoiceProfile.project_id == project_id,
        ))
        if not profile:
            raise HTTPException(status_code=404, detail="项目音色设定不存在")
        speaker_type = profile.profile_type
        voice = profile.voice
        speaker_name = profile.character_name_snapshot if speaker_type == "character" else profile.name
        return profile.id, speaker_type, speaker_name, voice
    voice = data.voice or "alloy"
    if speaker_type_value == "narrator":
        if getattr(data, "character_asset_id", None) is not None:
            raise HTTPException(status_code=422, detail="旁白不能绑定角色资产")
        return None, "narrator", getattr(data, "speaker_name", None) or "旁白", voice
    if getattr(data, "character_asset_id", None) is not None:
        asset = await db.scalar(select(VideoProjectImageAsset).where(
            VideoProjectImageAsset.id == getattr(data, "character_asset_id", None),
            VideoProjectImageAsset.project_id == project_id,
            VideoProjectImageAsset.asset_type == "character",
        ))
        if not asset:
            raise HTTPException(status_code=404, detail="项目角色资产不存在")
        return None, "character", asset.title, voice
    if not getattr(data, "speaker_name", None):
        raise HTTPException(status_code=422, detail="角色配音必须选择角色资产或填写角色名称")
    return None, "character", data.speaker_name.strip(), voice


@router.get("/video/creative-projects/{project_id}/voice-profiles")
async def list_project_voice_profiles(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    result = await db.execute(select(VideoProjectVoiceProfile).where(VideoProjectVoiceProfile.project_id == project_id).order_by(VideoProjectVoiceProfile.id))
    return [_serialize_voice_profile(item) for item in result.scalars().all()]


@router.post("/video/creative-projects/{project_id}/voice-profiles")
async def create_project_voice_profile(project_id: int, data: ProjectVoiceProfileRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    character_name = None
    if data.character_asset_id is not None:
        asset = await db.scalar(select(VideoProjectImageAsset).where(VideoProjectImageAsset.id == data.character_asset_id, VideoProjectImageAsset.project_id == project_id, VideoProjectImageAsset.asset_type == "character"))
        if not asset:
            raise HTTPException(status_code=404, detail="项目角色资产不存在")
        character_name = asset.title
    item = VideoProjectVoiceProfile(project_id=project_id, profile_type=data.profile_type, name=data.name.strip(), character_asset_id=data.character_asset_id, character_name_snapshot=character_name, voice=data.voice.strip())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return _serialize_voice_profile(item)


@router.put("/video/creative-projects/{project_id}/voice-profiles/{profile_id}")
async def update_project_voice_profile(project_id: int, profile_id: int, data: ProjectVoiceProfileUpdateRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    item = await db.get(VideoProjectVoiceProfile, profile_id)
    if not project or not item or item.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目音色设定不存在")
    if item.profile_type == "narrator" and data.character_asset_id is not None:
        raise HTTPException(status_code=422, detail="旁白音色不能绑定角色资产")
    character_name = None
    if item.profile_type == "character":
        if data.character_asset_id is None:
            raise HTTPException(status_code=422, detail="角色音色必须绑定角色资产")
        asset = await db.scalar(select(VideoProjectImageAsset).where(VideoProjectImageAsset.id == data.character_asset_id, VideoProjectImageAsset.project_id == project_id, VideoProjectImageAsset.asset_type == "character"))
        if not asset:
            raise HTTPException(status_code=404, detail="项目角色资产不存在")
        character_name = asset.title
    item.name = data.name.strip()
    item.voice = data.voice.strip()
    item.character_asset_id = data.character_asset_id
    item.character_name_snapshot = character_name
    await db.commit()
    await db.refresh(item)
    return _serialize_voice_profile(item)


@router.delete("/video/creative-projects/{project_id}/voice-profiles/{profile_id}")
async def delete_project_voice_profile(project_id: int, profile_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    item = await db.get(VideoProjectVoiceProfile, profile_id)
    if not project or not item or item.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目音色设定不存在")
    await db.delete(item)
    await db.commit()
    return {"id": profile_id, "deleted": True}


@router.post("/video/creative-projects/{project_id}/audio")
async def create_project_audio(project_id: int, data: ProjectTtsRequest, request: Request, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    profile_id, speaker_type, speaker_name, voice = await _resolve_voice_profile(db, project_id, data)
    role_config, key = await _get_project_role_key(db, project_id, "tts")
    queue_position = int((await db.scalar(select(func.max(VideoProjectAudioTask.queue_position)).where(VideoProjectAudioTask.project_id == project_id))) or -1) + 1
    task = VideoProjectAudioTask(project_id=project_id, api_key_id=key.id, provider=key.provider, model=role_config.model, voice=voice, input_text=data.text.strip(), status="pending", voice_profile_id=profile_id, speaker_type=speaker_type, speaker_name_snapshot=speaker_name, queue_position=queue_position, storyboard_shot_index=data.storyboard_shot_index, director_shot_revision=data.director_shot_revision)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    base_url = str(request.base_url).rstrip("/")
    if base_url == "http://workflow.local":
        task.status = "running"
        task.started_at = datetime.utcnow()
        await db.commit()
        try:
            local_path = await project_audio_service.synthesize(key, model=task.model, voice=task.voice, text=task.input_text, task_id=task.id)
            task.local_path = local_path
            task.audio_url = f"{base_url}/api/admin/video/project-audio/{task.id}/file"
            task.status = "completed"
        except Exception as exc:
            task.status = "failed"
            detail = str(exc).strip() or type(exc).__name__
            cause = getattr(exc, "__cause__", None)
            if cause and str(cause).strip() and str(cause).strip() not in detail:
                detail = f"{detail} ({type(cause).__name__}: {str(cause).strip()})"
            task.error_detail = detail[:4000]
        task.finished_at = datetime.utcnow()
        await db.commit()
    else:
        asyncio.create_task(_run_project_audio_task(task.id, base_url))
    return _serialize_project_audio(task, request)


@router.put("/video/creative-projects/{project_id}/audio/{task_id}")
async def update_project_audio(project_id: int, task_id: int, data: ProjectAudioTaskUpdateRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    task = await db.get(VideoProjectAudioTask, task_id)
    if not project or not task or task.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目音频任务不存在")
    if task.status != "pending":
        raise HTTPException(status_code=409, detail="任务已开始合成，不能编辑")
    profile_id, speaker_type, speaker_name, voice = await _resolve_voice_profile(db, project_id, data)
    task.input_text = data.text.strip()
    task.voice = voice
    task.voice_profile_id = profile_id
    task.speaker_type = speaker_type
    task.speaker_name_snapshot = speaker_name
    await db.commit()
    await db.refresh(task)
    return _serialize_project_audio(task)


@router.post("/video/creative-projects/{project_id}/audio/{task_id}/retry")
async def retry_project_audio(project_id: int, task_id: int, request: Request, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    source = await db.get(VideoProjectAudioTask, task_id)
    if not project or not source or source.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目音频任务不存在")
    if source.status != "failed":
        raise HTTPException(status_code=409, detail="只有失败任务可以重试")
    queue_position = int((await db.scalar(select(func.max(VideoProjectAudioTask.queue_position)).where(VideoProjectAudioTask.project_id == project_id))) or -1) + 1
    task = VideoProjectAudioTask(project_id=project_id, api_key_id=source.api_key_id, provider=source.provider, model=source.model, voice=source.voice, input_text=source.input_text, status="pending", voice_profile_id=source.voice_profile_id, speaker_type=source.speaker_type, speaker_name_snapshot=source.speaker_name_snapshot, queue_position=queue_position)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    asyncio.create_task(_run_project_audio_task(task.id, str(request.base_url).rstrip("/")))
    return _serialize_project_audio(task, request)


@router.delete("/video/creative-projects/{project_id}/audio/{task_id}")
async def delete_project_audio(project_id: int, task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    task = await db.get(VideoProjectAudioTask, task_id)
    if not project or not task or task.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目音频任务不存在")
    if task.status != "pending":
        raise HTTPException(status_code=409, detail="只有待合成任务可以删除")
    await db.delete(task)
    await db.commit()
    return {"id": task_id, "deleted": True}


@router.get("/video/project-audio/{task_id}/file")
async def get_project_audio_file(task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    task = await db.get(VideoProjectAudioTask, task_id)
    if not task or not task.local_path or not Path(task.local_path).is_file():
        raise HTTPException(status_code=404, detail="音频不存在")
    return FileResponse(task.local_path, media_type="audio/mpeg")


@router.post("/video/creative-projects/{project_id}/subtitles")
async def create_project_subtitle(project_id: int, data: ProjectAsrRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    audio_task = await db.get(VideoProjectAudioTask, data.audio_task_id)
    if not project or not audio_task or audio_task.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目或音频任务不存在")
    if audio_task.status != "completed" or not audio_task.local_path:
        raise HTTPException(status_code=400, detail="音频任务尚未完成")
    role_config, key = await _get_project_role_key(db, project_id, "asr")
    task = VideoProjectSubtitleTask(project_id=project_id, source_audio_task_id=audio_task.id, api_key_id=key.id, provider=key.provider, model=role_config.model, language=data.language, storyboard_shot_index=data.storyboard_shot_index if data.storyboard_shot_index is not None else audio_task.storyboard_shot_index, director_shot_revision=audio_task.director_shot_revision, status="running")
    db.add(task)
    await db.commit()
    try:
        result = await project_audio_service.transcribe(key, model=role_config.model, audio_path=audio_task.local_path, language=data.language)
        task.transcript = str(result.get("text") or "")
        task.srt_content = _segments_to_srt(result.get("segments") or [])
        task.status = "completed"
        task.finished_at = datetime.utcnow()
    except Exception as exc:
        task.status = "failed"
        task.error_detail = str(exc)
        task.finished_at = datetime.utcnow()
    await db.commit()
    return {"id": task.id, "status": task.status, "transcript": task.transcript, "srt_content": task.srt_content, "error_detail": task.error_detail}


@router.put("/video/creative-projects/{project_id}/subtitles/{task_id}")
async def update_project_subtitle(project_id: int, task_id: int, data: ProjectSubtitleUpdateRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    task = await db.get(VideoProjectSubtitleTask, task_id)
    if not project or not task or task.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目字幕不存在")
    if task.status != "completed":
        raise HTTPException(status_code=400, detail="只能编辑已完成的字幕")
    task.srt_content = data.srt_content.strip()
    await db.commit()
    return {"id": task.id, "srt_content": task.srt_content}


@router.get("/video/creative-projects/{project_id}/subtitles/{task_id}/file")
async def download_project_subtitle(project_id: int, task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    task = await db.get(VideoProjectSubtitleTask, task_id)
    if not project or not task or task.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目字幕不存在")
    if not task.srt_content:
        raise HTTPException(status_code=404, detail="字幕内容不存在")
    return Response(
        content=task.srt_content,
        media_type="application/x-subrip; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="project-{project_id}-subtitle-{task_id}.srt"'},
    )


@router.put("/video/creative-projects/{project_id}/audio/{task_id}/queue-position")
async def update_project_audio_queue_position(project_id: int, task_id: int, position: int = Query(ge=0), db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    task = await db.get(VideoProjectAudioTask, task_id)
    if not project or not task or task.project_id != project_id or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="项目音频任务不存在")
    if task.status != "pending":
        raise HTTPException(status_code=409, detail="只有待合成任务可以调整顺序")
    pending_result = await db.execute(select(VideoProjectAudioTask).where(
        VideoProjectAudioTask.project_id == project_id,
        VideoProjectAudioTask.status == "pending",
    ).order_by(VideoProjectAudioTask.queue_position, VideoProjectAudioTask.id))
    pending = list(pending_result.scalars().all())
    pending = [item for item in pending if item.id != task.id]
    pending.insert(min(position, len(pending)), task)
    for index, item in enumerate(pending):
        item.queue_position = index
    await db.commit()
    await db.refresh(task)
    return _serialize_project_audio(task)


@router.get("/video/creative-projects/{project_id}/audio")
async def list_project_audio(project_id: int, request: Request, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    result = await db.execute(select(VideoProjectAudioTask).where(
        VideoProjectAudioTask.project_id == project_id,
    ).order_by(VideoProjectAudioTask.queue_position.is_(None), VideoProjectAudioTask.queue_position, VideoProjectAudioTask.id.desc()))
    return [_serialize_project_audio(item, request) for item in result.scalars().all()]


@router.get("/video/creative-projects/{project_id}/subtitles")
async def list_project_subtitles(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    result = await db.execute(select(VideoProjectSubtitleTask).where(VideoProjectSubtitleTask.project_id == project_id).order_by(VideoProjectSubtitleTask.id.desc()))
    return [{"id": item.id, "audio_task_id": item.source_audio_task_id, "model": item.model, "language": item.language, "status": item.status, "transcript": item.transcript, "srt_content": item.srt_content, "error_detail": item.error_detail, "created_at": item.created_at, "finished_at": item.finished_at} for item in result.scalars().all()]


async def _assert_project_asset(db: AsyncSession, project_id: int, source_type: str, source_id: int):
    model_map = {"audio_task": VideoProjectAudioTask, "subtitle_task": VideoProjectSubtitleTask}
    if source_type == "video_task":
        item = await db.get(VideoGenerationTask, source_id)
        if not item or item.project_id != project_id:
            raise HTTPException(status_code=404, detail="项目视频任务不存在")
        return item
    item = await db.get(model_map[source_type], source_id)
    if not item or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="项目资产不存在")
    return item


@router.get("/video/creative-projects/{project_id}/timeline")
async def list_project_timeline(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    result = await db.execute(select(VideoProjectTimelineItem).where(VideoProjectTimelineItem.project_id == project_id).order_by(VideoProjectTimelineItem.track, VideoProjectTimelineItem.position, VideoProjectTimelineItem.id))
    return [{"id": item.id, "track": item.track, "source_type": item.source_type, "source_id": item.source_id, "position": item.position, "offset_ms": item.offset_ms, "duration_ms": item.duration_ms, "storyboard_shot_index": item.storyboard_shot_index} for item in result.scalars().all()]


@router.post("/video/creative-projects/{project_id}/storyboard/{shot_index}/select/{task_id}")
async def select_storyboard_video_candidate(project_id: int, shot_index: int, task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    task = await db.get(VideoGenerationTask, task_id)
    task_params = json.loads(task.request_params_json or "{}") if task else {}
    if not task or task.project_id != project_id or task.status != "completed" or task_params.get("storyboard_shot_index") != shot_index:
        raise HTTPException(status_code=400, detail="只能选择该分镜已完成的视频候选")
    existing = await db.execute(select(VideoProjectTimelineItem).where(
        VideoProjectTimelineItem.project_id == project_id,
        VideoProjectTimelineItem.track == "video",
        VideoProjectTimelineItem.storyboard_shot_index == shot_index,
    ))
    for item in existing.scalars().all():
        await db.delete(item)
    position = int((await db.scalar(select(func.max(VideoProjectTimelineItem.position)).where(
        VideoProjectTimelineItem.project_id == project_id,
        VideoProjectTimelineItem.track == "video",
    ))) or -1) + 1
    item = VideoProjectTimelineItem(
        project_id=project_id,
        track="video",
        source_type="video_task",
        source_id=task.id,
        position=position,
        storyboard_shot_index=shot_index,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"id": item.id, "track": item.track, "source_type": item.source_type, "source_id": item.source_id, "position": item.position, "offset_ms": item.offset_ms, "duration_ms": item.duration_ms, "storyboard_shot_index": item.storyboard_shot_index}

@router.post("/video/creative-projects/{project_id}/timeline")
async def add_project_timeline_item(project_id: int, data: ProjectTimelineItemRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    await _assert_project_asset(db, project_id, data.source_type, data.source_id)
    position = data.position
    if position is None:
        position = int((await db.scalar(select(func.max(VideoProjectTimelineItem.position)).where(VideoProjectTimelineItem.project_id == project_id, VideoProjectTimelineItem.track == data.track))) or -1) + 1
    item = VideoProjectTimelineItem(project_id=project_id, track=data.track, source_type=data.source_type, source_id=data.source_id, position=position, offset_ms=max(data.offset_ms, 0), duration_ms=data.duration_ms)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return {"id": item.id, "track": item.track, "source_type": item.source_type, "source_id": item.source_id, "position": item.position, "offset_ms": item.offset_ms, "duration_ms": item.duration_ms}


@router.put("/video/creative-projects/{project_id}/timeline/{item_id}")
async def update_project_timeline_item(project_id: int, item_id: int, data: ProjectTimelineItemUpdateRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    item = await db.get(VideoProjectTimelineItem, item_id)
    if not item or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="时间线项目不存在")
    item.position = data.position
    item.offset_ms = data.offset_ms
    item.duration_ms = data.duration_ms
    await db.commit()
    return {"id": item.id, "track": item.track, "source_type": item.source_type, "source_id": item.source_id, "position": item.position, "offset_ms": item.offset_ms, "duration_ms": item.duration_ms}


@router.delete("/video/creative-projects/{project_id}/timeline/{item_id}")
async def delete_project_timeline_item(project_id: int, item_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    item = await db.get(VideoProjectTimelineItem, item_id)
    if not item or item.project_id != project_id:
        raise HTTPException(status_code=404, detail="时间线项目不存在")
    await db.delete(item)
    await db.commit()
    return {"id": item_id, "deleted": True}


def _serialize_project_export_task(task: VideoProjectExportTask, request: Request | None = None) -> dict:
    base_url = str(request.base_url).rstrip("/") if request else ""
    download_url = f"{base_url}/api/admin/video/creative-projects/{task.project_id}/exports/{task.id}/file" if task.output_path else None
    subtitle_url = f"{base_url}/api/admin/video/creative-projects/{task.project_id}/exports/{task.id}/subtitle" if task.subtitle_path else None
    return {
        "id": task.id,
        "project_id": task.project_id,
        "workflow_id": task.workflow_id,
        "status": task.status,
        "audio_strategy": task.audio_strategy or "preserve",
        "duration_ms": task.duration_ms,
        "command_summary": task.command_summary,
        "error_detail": task.error_detail,
        "download_url": download_url,
        "subtitle_url": subtitle_url,
        "manifest_url": f"{base_url}/api/admin/video/creative-projects/{task.project_id}/exports/{task.id}/manifest" if task.manifest_path else None,
        "created_at": task.created_at,
        "started_at": task.started_at,
        "finished_at": task.finished_at,
    }


async def _run_project_export_task(task_id: int) -> None:
    async with async_session_maker() as task_db:
        task = await task_db.get(VideoProjectExportTask, task_id)
        if task and task.status == "pending":
            await video_export_service.export(task_db, task)


@router.get("/video/ffmpeg/preflight")
async def get_video_ffmpeg_preflight(auth=Depends(verify_admin_key)):
    return video_export_service.preflight()


@router.get("/video/creative-projects/{project_id}/exports")
async def list_project_exports(project_id: int, request: Request, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    result = await db.execute(select(VideoProjectExportTask).where(
        VideoProjectExportTask.project_id == project_id,
    ).order_by(VideoProjectExportTask.id.desc()))
    return [_serialize_project_export_task(item, request) for item in result.scalars().all()]


@router.post("/video/creative-projects/{project_id}/exports")
async def create_project_export(project_id: int, data: ProjectExportRequest, request: Request, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    storyboard = json.loads(project.storyboard_json or "[]")
    if storyboard:
        completed_result = await db.execute(select(VideoGenerationTask).where(
            VideoGenerationTask.project_id == project_id,
            VideoGenerationTask.status == "completed",
        ))
        completed_indexes = {
            json.loads(item.request_params_json or "{}").get("storyboard_shot_index")
            for item in completed_result.scalars().all()
        }
        completed_indexes.discard(None)
        selected_result = await db.execute(select(VideoProjectTimelineItem).where(
            VideoProjectTimelineItem.project_id == project_id,
            VideoProjectTimelineItem.track == "video",
            VideoProjectTimelineItem.storyboard_shot_index.is_not(None),
        ))
        selected_indexes = {item.storyboard_shot_index for item in selected_result.scalars().all()}
        missing_indexes = sorted(completed_indexes - selected_indexes)
        if missing_indexes:
            labels = "、".join(str(index + 1) for index in missing_indexes)
            raise HTTPException(status_code=400, detail=f"请先为镜头 {labels} 选择定稿视频")
    preflight = video_export_service.preflight()
    if not preflight["available"]:
        raise HTTPException(status_code=503, detail=preflight["error"])
    workflow = await db.scalar(select(VideoProjectWorkflow).where(VideoProjectWorkflow.project_id == project_id))
    task = VideoProjectExportTask(project_id=project_id, workflow_id=workflow.id if workflow else None, status="pending", audio_strategy=data.audio_strategy)
    db.add(task)
    await db.commit()
    await db.refresh(task)
    background_tasks.add_task(_run_project_export_task, task.id)
    return _serialize_project_export_task(task, request)


@router.get("/video/creative-projects/{project_id}/exports/{task_id}/file")
async def download_project_export(project_id: int, task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    task = await db.get(VideoProjectExportTask, task_id)
    if not task or task.project_id != project_id or task.status != "completed" or not task.output_path:
        raise HTTPException(status_code=404, detail="成片不存在")
    path = Path(task.output_path)
    export_root = video_export_service.EXPORT_ROOT.resolve()
    if not path.is_file() or export_root not in path.resolve().parents:
        raise HTTPException(status_code=404, detail="成片文件不存在")
    return FileResponse(path, media_type="video/mp4", filename=f"project-{project_id}-export-{task.id}.mp4")


@router.get("/video/creative-projects/{project_id}/exports/{task_id}/manifest")
async def download_project_export_manifest(project_id: int, task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    task = await db.get(VideoProjectExportTask, task_id)
    if not task or task.project_id != project_id or task.status != "completed" or not task.manifest_path:
        raise HTTPException(status_code=404, detail="成片清单不存在")
    path = Path(task.manifest_path)
    export_root = video_export_service.EXPORT_ROOT.resolve()
    if not path.is_file() or export_root not in path.resolve().parents:
        raise HTTPException(status_code=404, detail="成片清单文件不存在")
    return FileResponse(path, media_type="application/json", filename=f"project-{project_id}-export-{task.id}.json")


@router.get("/video/creative-projects/{project_id}/exports/{task_id}/subtitle")
async def download_project_export_subtitle(project_id: int, task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    task = await db.get(VideoProjectExportTask, task_id)
    if not task or task.project_id != project_id or task.status != "completed" or not task.subtitle_path:
        raise HTTPException(status_code=404, detail="成片字幕不存在")
    path = Path(task.subtitle_path)
    export_root = video_export_service.EXPORT_ROOT.resolve()
    if not path.is_file() or export_root not in path.resolve().parents:
        raise HTTPException(status_code=404, detail="成片字幕文件不存在")
    return FileResponse(path, media_type="application/x-subrip; charset=utf-8", filename=f"project-{project_id}-export-{task.id}.srt")


@router.post("/video/assets")
async def upload_video_asset(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    auth=Depends(verify_admin_key),
):
    await require_image_square_access(db, auth)
    content_type = (file.content_type or "").lower()
    asset_type = _detect_asset_type(content_type)
    if not asset_type:
        raise HTTPException(status_code=400, detail="仅支持 JPEG、PNG、WebP 图片和 MP3、WAV、OGG、M4A 音频")
    suffix = Path(file.filename or "").suffix.lower()
    if not suffix:
        suffix = mimetypes.guess_extension(content_type) or (".png" if asset_type == "image" else ".mp3")
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".mp3", ".wav", ".ogg", ".m4a"}:
        raise HTTPException(status_code=400, detail="文件扩展名不受支持")
    content = await file.read(MAX_VIDEO_ASSET_SIZE + 1)
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > MAX_VIDEO_ASSET_SIZE:
        raise HTTPException(status_code=400, detail="素材文件不能超过 25MB")
    VIDEO_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    asset_id = uuid.uuid4().hex
    path = VIDEO_ASSET_DIR / f"{asset_id}{suffix}"
    path.write_bytes(content)
    base_url = str(request.base_url).rstrip("/")
    return {
        "id": asset_id,
        "name": _safe_asset_name(Path(file.filename or "asset").stem),
        "type": asset_type,
        "url": f"{base_url}/api/admin/video/assets/{asset_id}{suffix}",
        "content_type": content_type,
        "size": len(content),
    }


@router.get("/video/assets/{asset_file}")
async def get_video_asset(asset_file: str):
    safe_name = Path(asset_file).name
    if safe_name != asset_file or not re.fullmatch(r"[a-f0-9]{32}\.(jpg|jpeg|png|webp|mp3|wav|ogg|m4a)", safe_name):
        raise HTTPException(status_code=404, detail="素材不存在")
    path = VIDEO_ASSET_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="素材不存在")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


@router.get("/video/creative-projects")
async def list_creative_projects(db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    query = select(VideoCreativeProject)
    if not auth.get("is_admin"):
        query = query.where(VideoCreativeProject.user_id == auth.get("user_id"))
    result = await db.execute(query.order_by(VideoCreativeProject.id.desc()))
    return [_serialize_creative_project(item) for item in result.scalars().all()]


@router.post("/video/creative-projects")
async def create_creative_project(data: VideoCreativeProjectRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = VideoCreativeProject(
        user_id=auth.get("user_id"),
        title=data.title.strip(),
        source_text=data.source_text.strip(),
        default_aspect_ratio=data.default_aspect_ratio,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return _serialize_creative_project(project)


@router.get("/video/creative-projects/{project_id}")
async def get_creative_project(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    return _serialize_creative_project(project)


@router.put("/video/creative-projects/{project_id}")
async def update_creative_project(project_id: int, data: VideoCreativeProjectUpdate, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    if data.analysis is not None:
        project.analysis_json = json.dumps(data.analysis, ensure_ascii=False)
    if data.script is not None:
        project.script_json = json.dumps(data.script, ensure_ascii=False)
    if data.storyboard is not None:
        project.storyboard_json = json.dumps(data.storyboard, ensure_ascii=False)
    if data.default_aspect_ratio is not None:
        project.default_aspect_ratio = data.default_aspect_ratio
    await db.commit()
    await db.refresh(project)
    return _serialize_creative_project(project)


@router.get("/video/agent-sources")
async def list_creative_agent_sources(model: str = Query(min_length=1, max_length=200), db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    keys = await pool_manager.get_all_keys(db, models=[model], active_only=True)
    providers = sorted({str(key.provider or "").strip() for key in keys if str(key.provider or "").strip()})
    return {
        "model": model,
        "providers": providers,
        "keys": [{"id": key.id, "name": key.name, "provider": key.provider} for key in keys],
    }

async def run_creative_agent(project_id: int, data: VideoCreativeAgentRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    role_config = await db.scalar(select(VideoProjectRoleConfig).where(VideoProjectRoleConfig.project_id == project.id, VideoProjectRoleConfig.role == "text", VideoProjectRoleConfig.enabled == True))
    if role_config and role_config.model:
        data = data.model_copy(update={
            "model": role_config.model,
            "source": (
                f"key:{role_config.api_key_id}" if role_config.source_mode == "key" and role_config.api_key_id
                else f"provider:{role_config.provider}" if role_config.source_mode == "provider" and role_config.provider
                else None
            ),
        })
    result = await _run_creative_agent(db, project, data, auth.get("user_id"))
    if data.stage == "analysis":
        project.analysis_json = json.dumps(result, ensure_ascii=False)
    elif data.stage == "script":
        project.script_json = json.dumps(result, ensure_ascii=False)
    else:
        project.storyboard_json = json.dumps(result, ensure_ascii=False)
    await db.commit()
    await db.refresh(project)
    return _serialize_creative_project(project)


@router.delete("/video/creative-projects/{project_id}")
async def delete_creative_project(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    await db.delete(project)
    await db.commit()
    return {"id": project_id, "deleted": True}


@router.get("/video/endpoint-templates")
async def list_video_endpoint_templates(auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return DEFAULT_VIDEO_ENDPOINT_TEMPLATES


@router.get("/video/models")
async def list_video_models(db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    await ensure_agnes_model(db)
    result = await db.execute(select(VideoModelConfig).order_by(VideoModelConfig.id))
    models = list(result.scalars().all())
    response = []
    model_counts = {}
    for item in models:
        model_counts[item.model] = model_counts.get(item.model, 0) + 1
    for item in models:
        data = serialize_model(item)
        data["duplicate_count"] = model_counts[item.model]
        data["is_duplicate"] = model_counts[item.model] > 1
        keys = await pool_manager.get_all_keys(db, provider=item.provider or None, models=[item.model], active_only=True)
        data["available_key_count"] = len(keys)
        data["available_keys"] = [{"id": key.id, "name": key.name, "provider": key.provider} for key in keys]
        response.append(data)
    return response


@router.post("/video/models")
async def create_video_model(data: VideoModelRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    exists = await db.scalar(select(VideoModelConfig).where(VideoModelConfig.model == data.model.strip()))
    if exists:
        raise HTTPException(status_code=409, detail="视频模型已存在")
    item = VideoModelConfig(
        **data.model_dump(exclude={"capabilities", "protocol_options"}),
        capabilities_json=json.dumps(data.capabilities, ensure_ascii=False),
        protocol_options_json=json.dumps(data.protocol_options, ensure_ascii=False),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return serialize_model(item)


@router.put("/video/models/{model_id}")
async def update_video_model(model_id: int, data: VideoModelRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    item = await db.get(VideoModelConfig, model_id)
    if not item:
        raise HTTPException(status_code=404, detail="视频模型不存在")
    if data.model.strip() != item.model:
        raise HTTPException(status_code=400, detail="模型 ID 不可修改，请新建模型配置")
    for field, value in data.model_dump(exclude={"capabilities", "protocol_options", "model"}).items():
        setattr(item, field, value)
    item.capabilities_json = json.dumps(data.capabilities, ensure_ascii=False)
    item.protocol_options_json = json.dumps(data.protocol_options, ensure_ascii=False)
    await db.commit()
    return serialize_model(item)


async def _resolve_storyboard_reference_images(db: AsyncSession, project_id: int, shot_index: int, shot: dict) -> tuple[list[str], list[int]]:
    requested_ids = shot.get("reference_asset_ids") or []
    if not isinstance(requested_ids, list) or any(not isinstance(item, int) for item in requested_ids):
        raise ValueError("分镜参考资产格式不正确")
    result = await db.execute(select(VideoProjectImageAsset).where(
        VideoProjectImageAsset.project_id == project_id,
    ))
    assets = list(result.scalars().all())
    selected_ids = set(requested_ids)
    selected_ids.update(item.id for item in assets if item.asset_type == "storyboard_reference" and item.storyboard_shot_index == shot_index)
    if len(selected_ids) > 5:
        raise ValueError("单个分镜最多绑定 5 张一致性参考图")
    selected = [item for item in assets if item.id in selected_ids]
    task_ids = [item.image_task_id for item in selected]
    if not task_ids:
        return [], []
    results = await db.execute(select(ImageGenerationTaskResult).where(
        ImageGenerationTaskResult.task_id.in_(task_ids),
        ImageGenerationTaskResult.status == "success",
    ).order_by(ImageGenerationTaskResult.id))
    urls = []
    for item in results.scalars().all():
        if item.image_url and item.image_url not in urls:
            urls.append(item.image_url)
    return urls[:5], [item.id for item in selected]

async def generate_storyboard_videos(project_id: int, data: StoryboardBatchGenerateRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    role = await db.scalar(select(VideoProjectRoleConfig).where(
        VideoProjectRoleConfig.project_id == project_id,
        VideoProjectRoleConfig.role == "video",
        VideoProjectRoleConfig.enabled == True,
    ))
    if not role or not role.model:
        raise HTTPException(status_code=400, detail="请先在项目生产职责中配置启用的视频模型")
    storyboard = json.loads(project.storyboard_json or "[]")
    if not storyboard:
        raise HTTPException(status_code=400, detail="项目尚未生成分镜")
    if any(index >= len(storyboard) for index in data.selected_shot_indexes):
        raise HTTPException(status_code=400, detail="存在无效的分镜序号")

    existing_result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.project_id == project_id))
    submitted_indexes = {
        json.loads(item.request_params_json or "{}").get("storyboard_shot_index")
        for item in existing_result.scalars().all()
        if item.status in {"creating", "pending", "processing", "completed", "running"}
    }
    skipped_indexes = [index for index in data.selected_shot_indexes if index in submitted_indexes]
    pending_indexes = [index for index in data.selected_shot_indexes if index not in submitted_indexes]
    semaphore = asyncio.Semaphore(data.concurrency)

    async def submit_one(index: int):
        shot = storyboard[index]
        prompt = str(shot.get("visual_prompt") or "").strip()
        try:
            duration = min(12, max(4, int(shot.get("duration_seconds") or 5)))
            if not prompt:
                raise ValueError("分镜缺少视觉提示词")
            async with semaphore:
                async with async_session_maker() as task_db:
                    reference_images, reference_asset_ids = await _resolve_storyboard_reference_images(task_db, project_id, index, shot)
                    mode = "reference" if reference_images else "text"
                    request_data = VideoGenerateRequest(
                        project_id=project_id,
                        storyboard_shot_index=index,
                        model=role.model,
                        prompt=prompt,
                        mode=mode,
                        images=reference_images,
                        reference_asset_ids=reference_asset_ids,
                        seconds=str(duration),
                        aspect_ratio=str(shot.get("aspect_ratio") or project.default_aspect_ratio or "9:16"),
                    )
                    return await generate_video(request_data, task_db, auth)
        except HTTPException as exc:
            return {
                "id": None,
                "project_id": project_id,
                "storyboard_shot_index": index,
                "model": role.model,
                "prompt": prompt,
                "mode": "text",
                "seconds": str(shot.get("duration_seconds") or 5),
                "status": "failed",
                "error_detail": str(exc.detail),
            }
        except Exception as exc:
            return {
                "id": None,
                "project_id": project_id,
                "storyboard_shot_index": index,
                "model": role.model,
                "prompt": prompt,
                "mode": "text",
                "seconds": str(shot.get("duration_seconds") or 5),
                "status": "failed",
                "error_detail": str(exc),
            }

    tasks = await asyncio.gather(*(submit_one(index) for index in pending_indexes))
    return {
        "items": list(tasks),
        "submitted_indexes": pending_indexes,
        "skipped_indexes": skipped_indexes,
        "concurrency": data.concurrency,
    }


@router.get("/video/creative-projects/{project_id}/tasks")
async def list_project_video_tasks(project_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project = await db.get(VideoCreativeProject, project_id)
    if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="创作项目不存在")
    result = await db.execute(select(VideoGenerationTask).where(VideoGenerationTask.project_id == project_id).order_by(VideoGenerationTask.id.desc()))
    return [serialize_task(item) for item in result.scalars().all()]


@router.get("/video/style-presets")
async def list_video_style_presets(db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    return list_style_presets()


@router.post("/video/generations")
async def generate_video(data: VideoGenerateRequest, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    project_video_role = None
    if data.project_id:
        project = await db.get(VideoCreativeProject, data.project_id)
        if not project or (not auth.get("is_admin") and project.user_id != auth.get("user_id")):
            raise HTTPException(status_code=404, detail="创作项目不存在")
        project_video_role = await db.scalar(select(VideoProjectRoleConfig).where(
            VideoProjectRoleConfig.project_id == project.id,
            VideoProjectRoleConfig.role == "video",
            VideoProjectRoleConfig.enabled == True,
        ))
        if not project_video_role or not project_video_role.model:
            raise HTTPException(status_code=400, detail="请先在项目生产职责中配置启用的视频模型")
        source = (
            f"key:{project_video_role.api_key_id}" if project_video_role.source_mode == "key" and project_video_role.api_key_id
            else f"provider:{project_video_role.provider}" if project_video_role.source_mode == "provider" and project_video_role.provider
            else None
        )
        data = data.model_copy(update={"model": project_video_role.model, "source": source})

    if data.style_preset_id:
        if not get_style_preset(data.style_preset_id):
            raise HTTPException(status_code=400, detail="视频风格预设不存在")
        data = data.model_copy(update={"prompt": apply_style_preset(data.prompt, data.style_preset_id)})

    config = await db.scalar(select(VideoModelConfig).where(VideoModelConfig.model == data.model, VideoModelConfig.enabled == True))
    if not config:
        raise HTTPException(status_code=404, detail="视频模型不可用")
    if project_video_role and project_video_role.endpoint_template_id:
        template = next((item for item in DEFAULT_VIDEO_ENDPOINT_TEMPLATES if item["id"] == project_video_role.endpoint_template_id), None)
        if not template:
            raise HTTPException(status_code=400, detail="项目视频端点模板不存在")
        if config.protocol != template["protocol"]:
            raise HTTPException(status_code=400, detail="视频模型与项目端点模板协议不一致，请在模型配置中使用对应端点模板")
    capabilities = json.loads(config.capabilities_json or "{}")
    if data.mode not in set(capabilities.get("modes") or []):
        raise HTTPException(status_code=400, detail="当前视频模型不支持该生成模式")
    if str(data.seconds) not in {str(item) for item in capabilities.get("seconds") or []}:
        raise HTTPException(status_code=400, detail="当前视频模型不支持该视频时长")
    if data.aspect_ratio not in set(capabilities.get("aspect_ratios") or []):
        raise HTTPException(status_code=400, detail="当前视频模型不支持该画幅")
    if data.size not in set(capabilities.get("sizes") or []):
        raise HTTPException(status_code=400, detail="当前视频模型不支持该分辨率")
    if config.protocol == "agnes" and (data.size != "720P" or data.seconds not in DEFAULT_AGNES_CAPABILITIES["seconds"]):
        raise HTTPException(status_code=400, detail="Agnes Flash 仅支持 720P 和 4-12 秒")
    provider, key_id = None, None
    if data.source:
        prefix, _, value = data.source.partition(":")
        if prefix == "provider": provider = value
        if prefix == "key": key_id = int(value)
    if key_id:
        key = await pool_manager.get_key_by_id(db, key_id)
        if not pool_manager.is_key_available_for_model(key, data.model, provider=provider):
            raise HTTPException(status_code=400, detail="指定 Key 不可用于该视频模型")
    else:
        key = await pool_manager.get_next_key(db, provider=provider or config.provider or None, model=data.model)
    if not key:
        raise HTTPException(status_code=400, detail="没有支持该视频模型的可用 Key")
    payload = data.model_dump(exclude={"source"}, exclude_none=True)
    payload["n"] = 1
    task = VideoGenerationTask(project_id=data.project_id, user_id=auth.get("user_id"), api_key_id=key.id, provider=key.provider, model=data.model, prompt=data.prompt, mode=data.mode, seconds=data.seconds, request_params_json=json.dumps(payload, ensure_ascii=False), status="creating", attempted_key_ids_json=json.dumps([key.id]), source="panel")
    db.add(task)
    await db.commit()
    try:
        upstream = await video_service.create_task(key, config, payload)
        task.upstream_video_id = video_service.extract_task_id(upstream)
        task.status = "pending"
        await db.commit()
    except Exception as exc:
        task.status = "failed"
        task.error_detail = str(exc)
        task.finished_at = datetime.utcnow()
        await db.commit()
    await db.refresh(task)
    return serialize_task(task)


@router.get("/video/tasks")
async def list_video_tasks(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    query = select(VideoGenerationTask)
    count_query = select(func.count()).select_from(VideoGenerationTask)
    if not auth.get("is_admin"):
        query = query.where(VideoGenerationTask.user_id == auth.get("user_id"))
        count_query = count_query.where(VideoGenerationTask.user_id == auth.get("user_id"))
    total = await db.scalar(count_query)
    result = await db.execute(query.order_by(VideoGenerationTask.id.desc()).offset((page - 1) * limit).limit(limit))
    return {"items": [serialize_task(item) for item in result.scalars().all()], "total": total or 0, "page": page, "limit": limit}


async def _add_completed_video_to_timeline(db: AsyncSession, task: VideoGenerationTask):
    if not task.project_id or task.status != "completed":
        return
    request_params = json.loads(task.request_params_json or "{}")
    if request_params.get("storyboard_shot_index") is not None:
        return
    existing = await db.scalar(select(VideoProjectTimelineItem).where(
        VideoProjectTimelineItem.project_id == task.project_id,
        VideoProjectTimelineItem.source_type == "video_task",
        VideoProjectTimelineItem.source_id == task.id,
    ))
    if existing:
        return
    position = int((await db.scalar(select(func.max(VideoProjectTimelineItem.position)).where(
        VideoProjectTimelineItem.project_id == task.project_id,
        VideoProjectTimelineItem.track == "video",
    ))) or -1) + 1
    request_params = json.loads(task.request_params_json or "{}")
    duration_ms = int(float(request_params.get("seconds") or task.seconds or 0) * 1000) or None
    db.add(VideoProjectTimelineItem(
        project_id=task.project_id,
        track="video",
        source_type="video_task",
        source_id=task.id,
        position=position,
        duration_ms=duration_ms,
    ))


@router.post("/video/tasks/{task_id}/refresh")
async def refresh_video_task(task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    task = await db.get(VideoGenerationTask, task_id)
    if not task or (not auth.get("is_admin") and task.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="视频任务不存在")
    if not task.upstream_video_id:
        return serialize_task(task)
    config = await db.scalar(select(VideoModelConfig).where(VideoModelConfig.model == task.model))
    key = await pool_manager.get_key_by_id(db, task.api_key_id) if task.api_key_id else None
    tried = json.loads(task.attempted_key_ids_json or "[]")
    if not key or not key.is_active:
        key = await pool_manager.get_next_key(db, provider=task.provider, model=task.model, exclude_key_ids=tried)
    if not key or not config:
        raise HTTPException(status_code=400, detail="没有可用于查询任务的 Key")
    try:
        result = await video_service.query_task(key, config, task.upstream_video_id)
        task.status, task.video_url, task.cover_url, task.error_detail = video_service.normalize_result(result)
        task.api_key_id = key.id
        if task.status in {"completed", "failed"}:
            task.finished_at = datetime.utcnow()
        await _add_completed_video_to_timeline(db, task)
        await db.commit()
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            retry_after = exc.response.headers.get("retry-after")
            headers = {"Retry-After": retry_after} if retry_after else None
            raise HTTPException(status_code=429, detail="上游视频任务查询受限，请稍后重试", headers=headers) from exc
        task.error_detail = str(exc)
        task.attempted_key_ids_json = json.dumps(sorted(set(tried + [key.id])))
        fallback_key = await pool_manager.get_next_key(db, provider=task.provider, model=task.model, exclude_key_ids=tried + [key.id])
        if fallback_key:
            task.api_key_id = fallback_key.id
        await db.commit()
    except Exception as exc:
        task.error_detail = str(exc)
        task.attempted_key_ids_json = json.dumps(sorted(set(tried + [key.id])))
        fallback_key = await pool_manager.get_next_key(db, provider=task.provider, model=task.model, exclude_key_ids=tried + [key.id])
        if fallback_key:
            task.api_key_id = fallback_key.id
        await db.commit()
    return serialize_task(task)


@router.delete("/video/tasks/{task_id}")
async def delete_video_task(task_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    await require_image_square_access(db, auth)
    task = await db.get(VideoGenerationTask, task_id)
    if not task or (not auth.get("is_admin") and task.user_id != auth.get("user_id")):
        raise HTTPException(status_code=404, detail="视频任务不存在")
    await db.delete(task)
    await db.commit()
    return {"id": task_id, "deleted": True}


@router.delete("/video/models/{model_id}")
async def delete_video_model(model_id: int, db: AsyncSession = Depends(get_db), auth=Depends(verify_admin_key)):
    if not auth.get("is_admin"):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    item = await db.get(VideoModelConfig, model_id)
    if not item:
        raise HTTPException(status_code=404, detail="视频模型不存在")
    if item.model == "agnes-video-2.5-flash":
        raise HTTPException(status_code=400, detail="内置 Agnes 视频模型不能删除，可在配置中停用")
    await db.delete(item)
    await db.commit()
    return {"id": model_id, "deleted": True}


# ============ 外部 API Key 视频调用（OpenAI 风格 /v1/videos/*） ============

v1_router = APIRouter()


@v1_router.post("/videos/generations")
async def v1_video_generations(
    request: Request,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """外部 API Key 视频生成：与面板生成共用任务表（source=api），历史可查。

    POST /v1/videos/generations
    {"model": "...", "prompt": "...", "mode": "text", "seconds": "5", "size": "720P", "aspect_ratio": "16:9"}
    """
    body = await request.json()
    model = str(body.get("model") or "").strip()
    prompt = str(body.get("prompt") or "").strip()
    if not model or not prompt:
        raise HTTPException(status_code=400, detail="缺少 model 或 prompt")
    config = await db.scalar(
        select(VideoModelConfig).where(VideoModelConfig.model == model, VideoModelConfig.enabled == True)
    )
    if not config:
        raise HTTPException(status_code=404, detail="视频模型不可用")
    capabilities = json.loads(config.capabilities_json or "{}")
    allowed_modes = set(capabilities.get("modes") or [])
    allowed_seconds = {str(item) for item in capabilities.get("seconds") or []}
    allowed_sizes = set(capabilities.get("sizes") or [])
    allowed_ratios = set(capabilities.get("aspect_ratios") or [])
    mode = str(body.get("mode") or (sorted(allowed_modes)[0] if allowed_modes else "text"))
    seconds = str(body.get("seconds") or (sorted(allowed_seconds)[0] if allowed_seconds else "5"))
    size = str(body.get("size") or (sorted(allowed_sizes)[0] if allowed_sizes else "720P"))
    aspect_ratio = str(body.get("aspect_ratio") or (sorted(allowed_ratios)[0] if allowed_ratios else "16:9"))
    if allowed_modes and mode not in allowed_modes:
        raise HTTPException(status_code=400, detail=f"当前视频模型不支持该生成模式，可选：{sorted(allowed_modes)}")
    if allowed_seconds and seconds not in allowed_seconds:
        raise HTTPException(status_code=400, detail=f"当前视频模型不支持该时长，可选：{sorted(allowed_seconds)}")
    if allowed_sizes and size not in allowed_sizes:
        raise HTTPException(status_code=400, detail=f"当前视频模型不支持该分辨率，可选：{sorted(allowed_sizes)}")
    if allowed_ratios and aspect_ratio not in allowed_ratios:
        raise HTTPException(status_code=400, detail=f"当前视频模型不支持该画幅，可选：{sorted(allowed_ratios)}")

    provider = str(body.get("provider") or "").strip() or (config.provider or None)
    key = await pool_manager.get_next_key(db, provider=provider, model=model)
    if not key:
        raise HTTPException(status_code=400, detail="没有支持该视频模型的可用 Key")

    payload = {
        "model": model, "prompt": prompt, "mode": mode, "seconds": seconds,
        "size": size, "aspect_ratio": aspect_ratio, "n": 1,
    }
    now = datetime.utcnow()
    task = VideoGenerationTask(
        user_id=auth_info.get("user_id"),
        api_key_id=key.id,
        provider=key.provider,
        model=model,
        prompt=prompt,
        mode=mode,
        seconds=seconds,
        request_params_json=json.dumps(payload, ensure_ascii=False),
        status="creating",
        attempted_key_ids_json=json.dumps([key.id]),
        source="api",
        created_at=now,
        updated_at=now,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    try:
        upstream = await video_service.create_task(key, config, payload)
        task.upstream_video_id = video_service.extract_task_id(upstream)
        task.status = "pending"
        await db.commit()
    except Exception as exc:
        task.status = "failed"
        task.error_detail = str(exc)
        task.finished_at = datetime.utcnow()
        await db.commit()
    await db.refresh(task)
    return serialize_task(task)


@v1_router.get("/videos/tasks/{task_id}")
async def v1_video_task_detail(
    task_id: int,
    refresh: bool = True,
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """查询外部视频任务详情；未完成任务可带 refresh=1 拉一次上游结果。"""
    task = await db.get(VideoGenerationTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="视频任务不存在")
    if refresh and task.status in {"pending", "creating"} and task.upstream_video_id:
        config = await db.scalar(select(VideoModelConfig).where(VideoModelConfig.model == task.model))
        key = await pool_manager.get_key_by_id(db, task.api_key_id) if task.api_key_id else None
        if key and key.is_active and config:
            try:
                result = await video_service.query_task(key, config, task.upstream_video_id)
                task.status, task.video_url, task.cover_url, task.error_detail = video_service.normalize_result(result)
                if task.status in {"completed", "failed"}:
                    task.finished_at = datetime.utcnow()
                await db.commit()
                await db.refresh(task)
            except Exception as exc:
                task.error_detail = str(exc)
                await db.commit()
                await db.refresh(task)
    return serialize_task(task)


@v1_router.get("/videos/models")
async def v1_video_models(
    db: AsyncSession = Depends(get_db),
    auth_info: dict = Depends(verify_api_key),
):
    """列出当前可用的视频模型（含能力参数），便于外部调用方选择。"""
    items = (
        (await db.execute(select(VideoModelConfig).where(VideoModelConfig.enabled == True)))
        .scalars()
        .all()
    )
    return {
        "object": "list",
        "data": [
            {
                "id": item.model,
                "provider": item.provider,
                "capabilities": json.loads(item.capabilities_json or "{}"),
            }
            for item in items
        ],
    }
