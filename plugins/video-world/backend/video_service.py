"""Video generation service for asynchronous upstream protocols."""
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
            raise ValueError("Video Key requires a valid upstream address")
        base_parts = [part for part in base.path.split("/") if part]
        path_parts = [part for part in (path or "").split("/") if part]
        while base_parts and path_parts and base_parts[-1] == path_parts[0]:
            path_parts.pop(0)
        return urlunsplit((base.scheme, base.netloc, "/" + "/".join(base_parts + path_parts), base.query, ""))

    @staticmethod
    def _options(config: Any) -> dict:
        try:
            value = json.loads(getattr(config, "protocol_options_json", "") or "{}")
        except json.JSONDecodeError:
            value = {}
        return value if isinstance(value, dict) else {}

    def _headers(self, api_key: Any, protocol: str = "") -> dict[str, str]:
        authorization = f"Bearer {api_key.api_key}"
        if protocol == "vidu_video":
            authorization = f"Token {api_key.api_key}"
        headers = {
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if protocol == "dashscope_async_video":
            headers["X-DashScope-Async"] = "enable"
        proxy_service._apply_fake_ip_headers(api_key, headers)
        return headers

    @staticmethod
    def _compact(payload: dict) -> dict:
        return {key: value for key, value in payload.items() if value is not None}

    def _build_create_payload(self, config: Any, payload: dict) -> tuple[dict, str | None]:
        protocol = config.protocol
        options = self._options(config)
        if protocol == "agnes":
            return self._compact({
                "model": payload["model"], "prompt": payload["prompt"], "mode": payload.get("mode") or "text",
                "seconds": str(payload.get("seconds") or "5"), "aspect_ratio": payload.get("aspect_ratio") or "16:9",
                "size": payload.get("size") or "720P", "first_frame": payload.get("first_frame"),
                "last_frame": payload.get("last_frame"), "images": payload.get("images") or [],
                "audios": payload.get("audios") or [], "n": 1,
            }), None
        if protocol == "arcreel_newapi_video":
            return self._compact({
                "model": payload["model"], "prompt": payload["prompt"], "width": payload.get("width") or 1280,
                "height": payload.get("height") or 720, "duration": int(payload.get("seconds") or 5),
                "n": 1, "seed": payload.get("seed"), "image": payload.get("first_frame"),
            }), None
        if protocol == "arcreel_minimax_h3":
            content = [{"type": "text", "text": payload["prompt"]}]
            if payload.get("first_frame"):
                content.append({"type": "image_url", "image_url": {"url": payload["first_frame"]}, "role": "first_frame"})
            if payload.get("last_frame"):
                content.append({"type": "image_url", "image_url": {"url": payload["last_frame"]}, "role": "last_frame"})
            for image in payload.get("images") or []:
                content.append({"type": "image_url", "image_url": {"url": image}, "role": "reference_image"})
            for audio in payload.get("audios") or []:
                content.append({"type": "audio_url", "audio_url": {"url": audio}, "role": "reference_audio"})
            return {"model": payload["model"], "content": content, "resolution": payload.get("resolution") or "768P", "duration": int(payload.get("seconds") or 5), "ratio": payload.get("aspect_ratio") or "16:9"}, None
        if protocol in {"arcreel_minimax_hailuo", "arcreel_minimax_s2v"}:
            if protocol == "arcreel_minimax_s2v":
                return {"model": payload["model"], "prompt": payload["prompt"], "subject_reference": [{"type": "character", "image": payload.get("images") or []}]}, None
            return self._compact({
                "model": payload["model"], "prompt": payload["prompt"], "duration": int(payload.get("seconds") or 5),
                "resolution": payload.get("resolution") or "768P", "first_frame_image": payload.get("first_frame"),
            }), None
        if protocol == "arcreel_v2_video":
            return self._compact({
                "model": payload["model"], "prompt": payload["prompt"], "duration": int(payload.get("seconds") or 5),
                "aspect_ratio": payload.get("aspect_ratio") or "16:9", "resolution": payload.get("resolution") or "720P",
                "seed": payload.get("seed"), "image_url": payload.get("first_frame"),
                "last_image_url": payload.get("last_frame"), "image_urls": payload.get("images") or [],
            }), None
        if protocol == "openai_video":
            if payload.get("first_frame") or payload.get("last_frame") or payload.get("images"):
                raise ValueError("OpenAI Video reference images require an uploaded file workflow; configure this model for text generation only")
            return {"model": payload["model"], "prompt": payload["prompt"], "seconds": str(payload.get("seconds") or "4"), "size": payload.get("size") or "1280x720"}, "form"
        if protocol == "ark_seedance":
            content = [{"type": "text", "text": payload["prompt"]}]
            if payload.get("first_frame"):
                content.append({"type": "image_url", "image_url": {"url": payload["first_frame"]}, "role": "first_frame"})
            if payload.get("last_frame"):
                content.append({"type": "image_url", "image_url": {"url": payload["last_frame"]}, "role": "last_frame"})
            for image in payload.get("images") or []:
                content.append({"type": "image_url", "image_url": {"url": image}, "role": "reference_image"})
            for audio in payload.get("audios") or []:
                content.append({"type": "audio_url", "audio_url": {"url": audio}, "role": "reference_audio"})
            return self._compact({
                "model": payload["model"], "content": content, "resolution": payload.get("size") or "720P",
                "ratio": payload.get("aspect_ratio") or "16:9", "duration": int(payload.get("seconds") or 5),
                "seed": payload.get("seed"), "generate_audio": options.get("generate_audio"),
            }), None
        if protocol == "dashscope_async_video":
            input_payload = {"prompt": payload["prompt"]}
            if payload.get("first_frame"):
                input_payload["img_url"] = payload["first_frame"]
            elif payload.get("images"):
                input_payload["media"] = payload["images"]
            return {
                "model": payload["model"], "input": input_payload,
                "parameters": self._compact({
                    "resolution": payload.get("size") or "720P", "ratio": payload.get("aspect_ratio") or "16:9",
                    "duration": int(payload.get("seconds") or 5), "seed": payload.get("seed"),
                    "prompt_extend": options.get("prompt_extend"), "watermark": options.get("watermark"),
                }),
            }, None
        if protocol == "kling_video":
            return self._compact({
                "model_name": payload["model"], "prompt": payload["prompt"], "duration": str(payload.get("seconds") or 5),
                "mode": options.get("mode") or "pro", "sound": options.get("sound") or "on",
                "aspect_ratio": payload.get("aspect_ratio") or "16:9", "negative_prompt": options.get("negative_prompt"),
            }), None
        if protocol == "vidu_video":
            return self._compact({
                "model": payload["model"], "prompt": payload["prompt"], "duration": int(payload.get("seconds") or 5),
                "aspect_ratio": payload.get("aspect_ratio") or "16:9", "resolution": (payload.get("size") or "720P").lower(),
                "seed": payload.get("seed"), "audio": options.get("audio"), "style": options.get("style"),
            }), None
        raise ValueError("Unsupported video protocol")

    async def create_task(self, api_key: Any, config: Any, payload: dict) -> dict:
        request_payload, request_type = self._build_create_payload(config, payload)
        headers = self._headers(api_key, config.protocol)
        if request_type == "form":
            headers.pop("Content-Type", None)
        async with httpx.AsyncClient(**proxy_service._build_client_kwargs(api_key, httpx.Timeout(connect=30, read=120, write=30, pool=30))) as client:
            request_kwargs = {"headers": headers}
            if request_type == "form":
                request_kwargs["files"] = {key: (None, str(value)) for key, value in request_payload.items()}
            else:
                request_kwargs["json"] = request_payload
            response = await client.post(self._url(api_key, config.create_path), **request_kwargs)
            response.raise_for_status()
            return response.json()

    async def query_task(self, api_key: Any, config: Any, upstream_video_id: str) -> dict:
        protocol = config.protocol
        options = self._options(config)
        headers = self._headers(api_key, protocol)
        method = "generic"
        params = {"video_id": upstream_video_id}
        query_path = config.query_path
        if protocol == "agnes":
            params = {"video_id": upstream_video_id, "model_name": config.model}
        elif protocol in {"arcreel_newapi_video", "arcreel_minimax_h3", "openai_video", "kling_video"}:
            method = "path_task_id"
        elif protocol in {"arcreel_minimax_hailuo", "arcreel_minimax_s2v"}:
            method, params = "hailuo", {"task_id": upstream_video_id}
        elif protocol == "arcreel_v2_video":
            method, params = "v2", {"generation_id": upstream_video_id}
        elif protocol == "ark_seedance":
            method = "path_task_id"
        elif protocol == "dashscope_async_video":
            method = "path_task_id"
        elif protocol == "vidu_video":
            method = "path_task_id"
            query_path = options.get("query_path_template") or query_path
        async with httpx.AsyncClient(**proxy_service._build_client_kwargs(api_key, httpx.Timeout(connect=30, read=90, write=30, pool=30)), follow_redirects=False) as client:
            if method == "path_task_id":
                if "{task_id}" in query_path:
                    target_path = query_path.replace("{task_id}", upstream_video_id)
                else:
                    target_path = f"{query_path.rstrip('/')}/{upstream_video_id}"
                response = await client.get(self._url(api_key, target_path), headers=headers)
            else:
                response = await client.get(self._url(api_key, query_path), headers=headers, params=params)
            response.raise_for_status()
            result = response.json()
            if method == "hailuo" and str(result.get("status") or "").lower() == "success" and result.get("file_id"):
                file_response = await client.get(self._url(api_key, "/v1/files/retrieve"), headers=headers, params={"file_id": result["file_id"]})
                file_response.raise_for_status()
                result["url"] = ((file_response.json().get("file") or {}).get("download_url"))
            if protocol == "openai_video" and str(result.get("status") or "").lower() == "completed" and not result.get("url"):
                task_path = config.query_path.replace("{task_id}", upstream_video_id) if "{task_id}" in config.query_path else f"{config.query_path.rstrip('/')}/{upstream_video_id}"
                content_response = await client.get(self._url(api_key, f"{task_path.rstrip('/')}/content"), headers={**headers, "Accept": "application/binary"})
                if content_response.is_redirect:
                    result["url"] = content_response.headers.get("location")
            return result

    @staticmethod
    def extract_task_id(data: dict) -> str:
        for name in ("video_id", "task_id", "generation_id", "id", "request_id", "task_uuid"):
            value = data.get(name)
            if value:
                return str(value)
        for name in ("data", "task", "output"):
            nested = data.get(name)
            if isinstance(nested, dict):
                try:
                    return VideoService.extract_task_id(nested)
                except ValueError:
                    continue
        raise ValueError("Upstream response did not include a video task identifier")

    @staticmethod
    def normalize_result(data: dict) -> tuple[str, str | None, str | None, str | None]:
        source = data.get("data") if isinstance(data.get("data"), dict) else data
        if isinstance(data.get("task"), dict):
            source = data["task"]
        if isinstance(data.get("output"), dict):
            source = data["output"]
        status = str(source.get("status") or source.get("task_status") or data.get("status") or "pending").lower()
        if status in {"success", "succeeded", "completed", "done", "finished"}:
            status = "completed"
        elif status in {"queued", "pending", "in_progress", "processing", "running", "preparing", "queueing", "submitted"}:
            status = "running"
        elif status in {"fail", "failed", "error", "cancelled", "canceled", "expired", "rejected"}:
            status = "failed"
        else:
            status = "running"
        content = source.get("content") if isinstance(source.get("content"), dict) else {}
        task_result = source.get("task_result") if isinstance(source.get("task_result"), dict) else {}
        output = source.get("output") if isinstance(source.get("output"), dict) else {}
        video_url = source.get("video_url") or source.get("url") or source.get("output_url") or content.get("url") or task_result.get("video_url") or output.get("video_url") or output.get("url")
        if not video_url and isinstance(source.get("video"), dict):
            video_url = source["video"].get("url")
        for container in (source.get("videos"), task_result.get("videos"), output.get("videos")):
            if not video_url and isinstance(container, list) and container:
                first = container[0]
                video_url = first.get("url") if isinstance(first, dict) else first
        cover_url = source.get("cover_url") or source.get("thumbnail_url") or output.get("thumbnail_url")
        error = source.get("error") or source.get("status_msg") or data.get("error") or data.get("message") if status == "failed" else None
        if isinstance(error, dict):
            error = error.get("message") or error.get("name") or json.dumps(error, ensure_ascii=False)
        return status, str(video_url) if video_url else None, str(cover_url) if cover_url else None, str(error) if error else None


video_service = VideoService()
