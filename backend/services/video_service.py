"""独立视频生成服务，适配异步视频任务协议。"""
import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from services.proxy_service import proxy_service


class VideoService:
    def _base_url(self, api_key: Any) -> str:
        return (getattr(api_key, "base_url", "") or "").rstrip("/")

    def _url(self, api_key: Any, path: str) -> str:
        base = urlsplit(self._base_url(api_key))
        if not base.scheme or not base.netloc:
            raise ValueError("视频 Key 缺少有效的上游地址")
        base_parts = [part for part in base.path.split("/") if part]
        path_parts = [part for part in (path or "").split("/") if part]
        while base_parts and path_parts and base_parts[-1] == path_parts[0]:
            path_parts.pop(0)
        return urlunsplit((base.scheme, base.netloc, "/" + "/".join(base_parts + path_parts), base.query, ""))

    def _headers(self, api_key: Any) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        proxy_service._apply_fake_ip_headers(api_key, headers)
        return headers

    async def create_task(self, api_key: Any, config: Any, payload: dict) -> dict:
        if config.protocol == "agnes":
            payload = {
                "model": payload["model"],
                "prompt": payload["prompt"],
                "mode": payload.get("mode") or "text",
                "seconds": str(payload.get("seconds") or "5"),
                "aspect_ratio": payload.get("aspect_ratio") or "16:9",
                "size": payload.get("size") or "720P",
                "first_frame": payload.get("first_frame"),
                "last_frame": payload.get("last_frame"),
                "images": payload.get("images") or [],
                "audios": payload.get("audios") or [],
                "n": 1,
            }
            payload = {key: value for key, value in payload.items() if value is not None}
        elif config.protocol == "arcreel_newapi_video":
            payload = {
                "model": payload["model"],
                "prompt": payload["prompt"],
                "width": payload.get("width") or 1280,
                "height": payload.get("height") or 720,
                "duration": int(payload.get("seconds") or 5),
                "n": 1,
                "seed": payload.get("seed"),
                "image": payload.get("first_frame"),
            }
            payload = {key: value for key, value in payload.items() if value is not None}
        elif config.protocol == "arcreel_minimax_h3":
            content = [{"type": "text", "text": payload["prompt"]}]
            if payload.get("first_frame"):
                content.append({"type": "image_url", "image_url": {"url": payload["first_frame"]}, "role": "first_frame"})
            if payload.get("last_frame"):
                content.append({"type": "image_url", "image_url": {"url": payload["last_frame"]}, "role": "last_frame"})
            for image in payload.get("images") or []:
                content.append({"type": "image_url", "image_url": {"url": image}, "role": "reference_image"})
            for audio in payload.get("audios") or []:
                content.append({"type": "audio_url", "audio_url": {"url": audio}, "role": "reference_audio"})
            payload = {
                "model": payload["model"],
                "content": content,
                "resolution": payload.get("resolution") or "768P",
                "duration": int(payload.get("seconds") or 5),
                "ratio": payload.get("aspect_ratio") or "16:9",
            }
        elif config.protocol in {"arcreel_minimax_hailuo", "arcreel_minimax_s2v"}:
            if config.protocol == "arcreel_minimax_s2v":
                references = payload.get("images") or []
                payload = {
                    "model": payload["model"],
                    "prompt": payload["prompt"],
                    "subject_reference": [{"type": "character", "image": references}],
                }
            else:
                payload = {
                    "model": payload["model"],
                    "prompt": payload["prompt"],
                    "duration": int(payload.get("seconds") or 5),
                    "resolution": payload.get("resolution") or "768P",
                    "first_frame_image": payload.get("first_frame"),
                }
                payload = {key: value for key, value in payload.items() if value is not None}
        elif config.protocol == "arcreel_v2_video":
            payload = {
                "model": payload["model"],
                "prompt": payload["prompt"],
                "duration": int(payload.get("seconds") or 5),
                "aspect_ratio": payload.get("aspect_ratio") or "16:9",
                "resolution": payload.get("resolution") or "720P",
                "seed": payload.get("seed"),
                "image_url": payload.get("first_frame"),
                "last_image_url": payload.get("last_frame"),
                "image_urls": payload.get("images") or [],
            }
            payload = {key: value for key, value in payload.items() if value is not None}
        async with httpx.AsyncClient(
            **proxy_service._build_client_kwargs(api_key, httpx.Timeout(connect=30, read=120, write=30, pool=30))
        ) as client:
            response = await client.post(self._url(api_key, config.create_path), headers=self._headers(api_key), json=payload)
            response.raise_for_status()
            return response.json()

    async def query_task(self, api_key: Any, config: Any, upstream_video_id: str) -> dict:
        if config.protocol == "agnes":
            params = {"video_id": upstream_video_id, "model_name": config.model}
            method = "agnes"
        elif config.protocol in {"arcreel_newapi_video", "arcreel_minimax_h3"}:
            params = None
            method = "path_task_id"
        elif config.protocol in {"arcreel_minimax_hailuo", "arcreel_minimax_s2v"}:
            params = {"task_id": upstream_video_id}
            method = "hailuo"
        elif config.protocol == "arcreel_v2_video":
            params = {"generation_id": upstream_video_id}
            method = "v2"
        else:
            params = {"video_id": upstream_video_id}
            method = "generic"
        async with httpx.AsyncClient(
            **proxy_service._build_client_kwargs(api_key, httpx.Timeout(connect=30, read=90, write=30, pool=30))
        ) as client:
            if method == "path_task_id":
                response = await client.get(self._url(api_key, f"{config.query_path.rstrip('/')}/{upstream_video_id}"), headers=self._headers(api_key))
            else:
                response = await client.get(self._url(api_key, config.query_path), headers=self._headers(api_key), params=params)
            response.raise_for_status()
            result = response.json()
            if method == "hailuo" and str(result.get("status") or "").lower() == "success" and result.get("file_id"):
                file_response = await client.get(self._url(api_key, "/v1/files/retrieve"), headers=self._headers(api_key), params={"file_id": result["file_id"]})
                file_response.raise_for_status()
                file_data = file_response.json()
                result["url"] = ((file_data.get("file") or {}).get("download_url"))
            return result

    @staticmethod
    def extract_task_id(data: dict) -> str:
        for name in ("video_id", "task_id", "generation_id", "id", "request_id"):
            value = data.get(name)
            if value:
                return str(value)
        nested = data.get("data")
        if isinstance(nested, dict):
            return VideoService.extract_task_id(nested)
        raise ValueError("上游响应未包含视频任务标识")

    @staticmethod
    def normalize_result(data: dict) -> tuple[str, str | None, str | None, str | None]:
        source = data.get("data") if isinstance(data.get("data"), dict) else data
        if isinstance(data.get("task"), dict):
            source = data["task"]
        status = str(source.get("status") or data.get("status") or "pending").lower()
        if status in {"success", "succeeded", "completed", "done"}:
            status = "completed"
        elif status in {"queued", "pending", "in_progress", "processing", "running", "preparing", "queueing"}:
            status = "running"
        elif status in {"fail", "failed", "error", "cancelled", "expired"}:
            status = "failed"
        else:
            status = "running"
        content = source.get("content") if isinstance(source.get("content"), dict) else {}
        task_result = source.get("task_result") if isinstance(source.get("task_result"), dict) else {}
        video_url = source.get("video_url") or source.get("url") or source.get("output_url") or content.get("url") or task_result.get("video_url")
        if not video_url and isinstance(task_result.get("videos"), list) and task_result["videos"]:
            first = task_result["videos"][0]
            video_url = first.get("url") if isinstance(first, dict) else first
        if not video_url and isinstance(source.get("video"), dict):
            video_url = source["video"].get("url")
        cover_url = source.get("cover_url") or source.get("thumbnail_url")
        error = source.get("error") or source.get("status_msg") or data.get("error") or data.get("message") if status == "failed" else None
        if isinstance(error, dict):
            error = error.get("message") or error.get("name") or json.dumps(error, ensure_ascii=False)
        return status, str(video_url) if video_url else None, str(cover_url) if cover_url else None, str(error) if error else None


video_service = VideoService()
