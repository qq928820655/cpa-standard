"""Video World plugin data conversion and input constraint tests."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


PLUGIN_ROOT = Path(__file__).resolve().parents[2] / "plugins" / "video-world" / "backend"
PLUGIN_MODULE_NAME = "video_world_plugin_tests"
PLUGIN_SPEC = importlib.util.spec_from_file_location(
    PLUGIN_MODULE_NAME,
    PLUGIN_ROOT / "video.py",
    submodule_search_locations=[str(PLUGIN_ROOT)],
)
if not PLUGIN_SPEC or not PLUGIN_SPEC.loader:
    raise RuntimeError("Video World plugin test module cannot be loaded")
PLUGIN_MODULE = importlib.util.module_from_spec(PLUGIN_SPEC)
sys.modules[PLUGIN_MODULE_NAME] = PLUGIN_MODULE
PLUGIN_SPEC.loader.exec_module(PLUGIN_MODULE)

VideoCreativeAgentRequest = PLUGIN_MODULE.VideoCreativeAgentRequest
VideoCreativeProjectRequest = PLUGIN_MODULE.VideoCreativeProjectRequest
ProjectImageRequest = PLUGIN_MODULE.ProjectImageRequest
WorkflowReviewRequest = PLUGIN_MODULE.WorkflowReviewRequest
VideoGenerateRequest = PLUGIN_MODULE.VideoGenerateRequest
_detect_asset_type = PLUGIN_MODULE._detect_asset_type
_extract_agent_json = PLUGIN_MODULE._extract_agent_json
_safe_asset_name = PLUGIN_MODULE._safe_asset_name
_segments_to_srt = PLUGIN_MODULE._segments_to_srt
_shot_input_hash = PLUGIN_MODULE._shot_input_hash
_normalize_director_shots = PLUGIN_MODULE._normalize_director_shots
DirectorAutoScheduleRequest = PLUGIN_MODULE.DirectorAutoScheduleRequest
def _load_plugin_module(name):
    spec = importlib.util.spec_from_file_location(
        f"{PLUGIN_MODULE_NAME}.{name}",
        PLUGIN_ROOT / f"{name}.py",
    )
    if not spec or not spec.loader:
        raise RuntimeError(f"Video World plugin module cannot be loaded: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


VideoService = _load_plugin_module("video_service").VideoService
VideoWorkflowQueueService = _load_plugin_module("video_workflow_queue_service").VideoWorkflowQueueService
VideoExportService = _load_plugin_module("video_export_service").VideoExportService


class VideoWorldUnitTests(unittest.TestCase):
    def test_agent_extracts_openai_message_json(self):
        result = _extract_agent_json({"choices": [{"message": {"content": '{"summary":"雨夜故事"}'}}]})
        self.assertEqual(result, {"summary": "雨夜故事"})

    def test_agent_extracts_fenced_json(self):
        result = _extract_agent_json("```json\n[{\"shot_no\":1}]\n```")
        self.assertEqual(result, [{"shot_no": 1}])

    def test_creative_project_requires_source_material(self):
        project = VideoCreativeProjectRequest(title="测试项目", source_text="创作素材" * 8)
        self.assertEqual(project.title, "测试项目")
        with self.assertRaises(ValueError):
            VideoCreativeProjectRequest(title="测试项目", source_text="太短")

    def test_creative_agent_stage_input(self):
        request = VideoCreativeAgentRequest(model="test-model", stage="storyboard")
        self.assertEqual(request.stage, "storyboard")

    def test_video_mode_media_constraints(self):
        VideoGenerateRequest(model="agnes-video-2.5-flash", prompt="雨夜城市", mode="text")
        VideoGenerateRequest(model="agnes-video-2.5-flash", prompt="人物转身", mode="keyframe", first_frame="https://example.com/first.png")
        VideoGenerateRequest(model="agnes-video-2.5-flash", prompt="参考角色", mode="reference", images=["https://example.com/ref.png"])
        with self.assertRaises(ValueError):
            VideoGenerateRequest(model="agnes-video-2.5-flash", prompt="错误", mode="text", images=["https://example.com/ref.png"])
        with self.assertRaises(ValueError):
            VideoGenerateRequest(model="agnes-video-2.5-flash", prompt="错误", mode="reference", first_frame="https://example.com/first.png", images=["https://example.com/ref.png"])

    def test_asset_type_and_filename_safety(self):
        self.assertEqual(_detect_asset_type("image/png"), "image")
        self.assertEqual(_detect_asset_type("audio/mpeg"), "audio")
        self.assertIsNone(_detect_asset_type("application/pdf"))
        self.assertEqual(_safe_asset_name("../../危险 文件?.png"), ".._.._.png")

    def test_video_response_normalization(self):
        self.assertEqual(
            VideoService.normalize_result({"status": "completed", "url": "https://example.com/video.mp4"}),
            ("completed", "https://example.com/video.mp4", None, None),
        )
        self.assertEqual(VideoService.normalize_result({"status": "failed", "error": "upstream failed"}), ("failed", None, None, "upstream failed"))

    def test_arcreel_minimax_h3_response_normalization(self):
        self.assertEqual(
            VideoService.normalize_result({"task": {"status": "succeeded", "content": {"url": "https://example.com/h3.mp4"}}}),
            ("completed", "https://example.com/h3.mp4", None, None),
        )
        self.assertEqual(
            VideoService.normalize_result({"task": {"status": "failed", "status_msg": "invalid source"}}),
            ("failed", None, None, "invalid source"),
        )

    def test_arcreel_v2_task_id_and_result_normalization(self):
        self.assertEqual(VideoService.extract_task_id({"generation_id": "generation-1"}), "generation-1")
        self.assertEqual(
            VideoService.normalize_result({"data": {"status": "completed", "task_result": {"videos": [{"url": "https://example.com/v2.mp4"}]}}}),
            ("completed", "https://example.com/v2.mp4", None, None),
        )

    def test_new_video_protocol_payload_contracts(self):
        service = VideoService()
        base_payload = {
            "model": "video-model", "prompt": "cinematic rain at night", "seconds": "5",
            "size": "720P", "aspect_ratio": "16:9", "seed": 7,
            "first_frame": "https://example.com/first.png", "last_frame": None,
            "images": ["https://example.com/reference.png"], "audios": [],
        }
        ark, _ = service._build_create_payload(SimpleNamespace(protocol="ark_seedance", protocol_options_json="{}"), base_payload)
        self.assertEqual(ark["content"][0], {"type": "text", "text": base_payload["prompt"]})
        self.assertEqual(ark["content"][1]["role"], "first_frame")
        self.assertEqual(ark["duration"], 5)

        dashscope, _ = service._build_create_payload(SimpleNamespace(protocol="dashscope_async_video", protocol_options_json="{\"prompt_extend\": true}"), base_payload)
        self.assertEqual(dashscope["input"]["img_url"], base_payload["first_frame"])
        self.assertTrue(dashscope["parameters"]["prompt_extend"])

        kling, _ = service._build_create_payload(SimpleNamespace(protocol="kling_video", protocol_options_json="{}"), base_payload)
        self.assertEqual(kling["model_name"], base_payload["model"])
        self.assertEqual(kling["duration"], "5")

        vidu, _ = service._build_create_payload(SimpleNamespace(protocol="vidu_video", protocol_options_json="{\"audio\": true}"), base_payload)
        self.assertEqual(vidu["resolution"], "720p")
        self.assertTrue(vidu["audio"])

        openai, request_type = service._build_create_payload(SimpleNamespace(protocol="openai_video", protocol_options_json="{}"), {**base_payload, "first_frame": None, "images": []})
        self.assertEqual(request_type, "form")
        self.assertEqual(openai["seconds"], "5")
        with self.assertRaises(ValueError):
            service._build_create_payload(SimpleNamespace(protocol="openai_video", protocol_options_json="{}"), base_payload)

    def test_new_protocol_task_and_result_normalization(self):
        self.assertEqual(VideoService.extract_task_id({"output": {"task_uuid": "task-1"}}), "task-1")
        self.assertEqual(
            VideoService.normalize_result({"output": {"task_status": "SUCCEEDED", "videos": [{"url": "https://example.com/provider.mp4"}]}}),
            ("completed", "https://example.com/provider.mp4", None, None),
        )
        self.assertEqual(
            VideoService.normalize_result({"data": {"status": "FAILED", "error": {"message": "provider rejected request"}}}),
            ("failed", None, None, "provider rejected request"),
        )
    def test_director_shot_normalization(self):
        shots = _normalize_director_shots({"shots": [{"title": "夜街", "visual_prompt": "霓虹雨夜", "duration_seconds": 20, "motion": "推镜"}]}, aspect_ratio="9:16")
        self.assertEqual(shots[0]["shot_index"], 0)
        self.assertEqual(shots[0]["duration_seconds"], 12)
        self.assertEqual(shots[0]["camera_motion"], "推镜")

    def test_director_shot_input_hash_changes_only_for_production_input(self):
        shot = {
            "scene_no": 1,
            "shot_no": 1,
            "duration_seconds": 5,
            "visual_prompt": "雨夜街道",
            "camera": "medium",
            "motion": "static",
            "aspect_ratio": "9:16",
            "narration": "旁白",
            "dialogue": "",
            "reference_asset_ids": [],
        }
        original = _shot_input_hash(shot)
        shot["production_status"] = "completed"
        self.assertEqual(_shot_input_hash(shot), original)
        shot["visual_prompt"] = "清晨街道"
        self.assertNotEqual(_shot_input_hash(shot), original)

    def test_director_scheduler_error_classification(self):
        self.assertTrue(VideoWorkflowQueueService._is_transient(RuntimeError("upstream HTTP 429")))
        self.assertTrue(VideoWorkflowQueueService._is_transient(RuntimeError("connect timeout")))
        self.assertFalse(VideoWorkflowQueueService._is_transient(RuntimeError("HTTP 401 invalid key")))
        self.assertFalse(VideoWorkflowQueueService._is_transient(RuntimeError("model not supported")))

    def test_director_schedule_options_validation(self):
        self.assertEqual(DirectorAutoScheduleRequest(audio_strategy="overlay").audio_strategy, "overlay")
        with self.assertRaises(ValueError):
            DirectorAutoScheduleRequest(audio_strategy="invalid")

    def test_workflow_review_action_validation(self):
        self.assertEqual(WorkflowReviewRequest(action="approve").action, "approve")
        with self.assertRaises(ValueError):
            WorkflowReviewRequest(action="run_everything")

    def test_project_image_asset_input(self):
        request = ProjectImageRequest(
            asset_type="storyboard_reference",
            title="雨夜街道镜头",
            prompt="雨夜霓虹街道，电影感构图",
            storyboard_shot_index=0,
        )
        self.assertEqual(request.asset_type, "storyboard_reference")
        with self.assertRaises(ValueError):
            ProjectImageRequest(asset_type="storyboard_reference", title="缺少镜头", prompt="测试")

    def test_project_subtitle_srt_generation(self):
        srt = _segments_to_srt([{ "start": 0, "end": 1.5, "text": "第一句" }, { "start": 1.5, "end": 3, "text": "第二句" }])
        self.assertIn("00:00:00,000 --> 00:00:01,500", srt)
        self.assertIn("第一句", srt)
        self.assertIn("00:00:01,500 --> 00:00:03,000", srt)

    def test_export_merges_subtitles_with_offsets(self):
        service = VideoExportService()
        merged = service._merge_subtitles([
            (1000, "1\n00:00:00,000 --> 00:00:01,500\n第一句"),
            (2500, "1\n00:00:00,500 --> 00:00:01,000\n第二句"),
        ])
        self.assertIn("00:00:01,000 --> 00:00:02,500", merged)
        self.assertIn("00:00:03,000 --> 00:00:03,500", merged)
        self.assertIn("第二句", merged)

    def test_export_resolves_linux_ffmpeg_and_ffprobe_independently(self):
        with patch(f"{VideoExportService.__module__}.sys.platform", "linux"), patch(
            f"{VideoExportService.__module__}.shutil.which",
            side_effect=lambda name: f"/usr/bin/{name}",
        ):
            service = VideoExportService()
            self.assertEqual(service.ffmpeg_path.as_posix(), "/usr/bin/ffmpeg")
            self.assertEqual(service.ffprobe_path.as_posix(), "/usr/bin/ffprobe")

    def test_export_rejects_unsafe_video_urls(self):
        self.assertFalse(VideoExportService._safe_url("file:///C:/secret.mp4"))
        self.assertFalse(VideoExportService._safe_url("https://user:pass@example.com/video.mp4"))
        self.assertTrue(VideoExportService._safe_url("https://example.com/video.mp4"))


if __name__ == "__main__":
    unittest.main()
