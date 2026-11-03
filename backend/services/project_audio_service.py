"""影视界 OpenAI 兼容 TTS 与 ASR 服务。"""
import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

import httpx

from config import DATA_DIR
from services.proxy_service import proxy_service


class ProjectAudioService:
    OUTPUT_DIR = DATA_DIR / "video_audio"

    def _url(self, api_key: Any, path: str) -> str:
        base = str(api_key.base_url or "").rstrip("/")
        normalized_path = "/" + path.lstrip("/")
        if base.endswith("/v1") and normalized_path.startswith("/v1/"):
            normalized_path = normalized_path[3:]
        return f"{base}{normalized_path}"

    def _headers(self, api_key: Any) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {api_key.api_key}"}
        proxy_service._apply_fake_ip_headers(api_key, headers)
        return headers

    async def synthesize(self, api_key: Any, *, model: str, voice: str, text: str, task_id: int) -> str:
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        is_mimo_tts = str(model).lower().startswith("mimo-v2.5-tts")
        endpoint = "/v1/chat/completions" if is_mimo_tts else "/v1/audio/speech"
        payload = (
            {
                "model": model,
                "messages": [
                    {"role": "user", "content": text},
                    {"role": "assistant", "content": ""},
                ],
                "stream": False,
            }
            if is_mimo_tts
            else {"model": model, "voice": voice, "input": text, "response_format": "mp3"}
        )
        async with httpx.AsyncClient(**proxy_service._build_client_kwargs(api_key, httpx.Timeout(connect=30, read=180, write=30, pool=30))) as client:
            response = await client.post(
                self._url(api_key, endpoint),
                headers={**self._headers(api_key), "Content-Type": "application/json"},
                json=payload,
            )
            if response.is_error:
                detail = response.text.strip()
                if len(detail) > 500:
                    detail = detail[:500] + "..."
                raise RuntimeError(
                    f"TTS 上游返回 HTTP {response.status_code}"
                    + (f": {detail}" if detail else "")
                )
            if is_mimo_tts:
                try:
                    data = response.json()
                    audio_data = data["choices"][0]["message"]["audio"]["data"]
                    audio_bytes = base64.b64decode(audio_data, validate=True)
                except (KeyError, IndexError, TypeError, ValueError, base64.binascii.Error) as exc:
                    raise RuntimeError("小米 TTS 响应缺少有效音频数据") from exc
                path = self.OUTPUT_DIR / f"tts-{task_id}.wav"
                path.write_bytes(audio_bytes)
            else:
                path = self.OUTPUT_DIR / f"tts-{task_id}.mp3"
                path.write_bytes(response.content)
            return str(path)

    async def transcribe(self, api_key: Any, *, model: str, audio_path: str, language: str | None = None) -> dict:
        path = Path(audio_path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with open(path, "rb") as source:
            files = {"file": (path.name, source, content_type)}
            data = {"model": model, "response_format": "verbose_json"}
            if language:
                data["language"] = language
            async with httpx.AsyncClient(**proxy_service._build_client_kwargs(api_key, httpx.Timeout(connect=30, read=300, write=30, pool=30))) as client:
                response = await client.post(self._url(api_key, "/v1/audio/transcriptions"), headers=self._headers(api_key), data=data, files=files)
                if response.is_error:
                    detail = response.text.strip()
                    if len(detail) > 500:
                        detail = detail[:500] + "..."
                    raise RuntimeError(f"ASR 上游返回 HTTP {response.status_code}" + (f": {detail}" if detail else ""))
                content_type = (response.headers.get("content-type") or "").lower()
                if "application/json" in content_type:
                    return response.json()
                text = response.text.strip()
                try:
                    parsed = json.loads(text)
                    return parsed if isinstance(parsed, dict) else {"text": text}
                except json.JSONDecodeError:
                    return {"text": text}


project_audio_service = ProjectAudioService()
