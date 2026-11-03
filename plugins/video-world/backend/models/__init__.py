"""Video World plugin models registered on CPA's shared metadata."""
from .video_generation_task import VideoGenerationTask, VideoModelConfig
from .video_creative_project import VideoCreativeProject
from .video_project_role_config import VideoProjectRoleConfig
from .video_project_audio import VideoProjectAudioTask, VideoProjectSubtitleTask, VideoProjectVoiceProfile
from .video_project_timeline import VideoProjectTimelineItem
from .video_project_image_asset import VideoProjectImageAsset
from .video_project_workflow import VideoProjectWorkflow, VideoProjectWorkflowTask, VideoProjectExportTask
from .video_project_attachment import VideoProjectAttachment

__all__ = [
    "VideoGenerationTask",
    "VideoModelConfig",
    "VideoCreativeProject",
    "VideoProjectRoleConfig",
    "VideoProjectAudioTask",
    "VideoProjectSubtitleTask",
    "VideoProjectVoiceProfile",
    "VideoProjectTimelineItem",
    "VideoProjectImageAsset",
    "VideoProjectWorkflow",
    "VideoProjectWorkflowTask",
    "VideoProjectExportTask",
    "VideoProjectAttachment",
]
