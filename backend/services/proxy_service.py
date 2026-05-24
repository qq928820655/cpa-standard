"""
代理转发服务
"""
import asyncio
import base64
import binascii
import ipaddress
import json
import logging
import re
import time
from typing import Optional, Any, AsyncGenerator
from urllib.parse import quote, urlsplit, urlunsplit
import httpx
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings

logger = logging.getLogger("cpa.image")


class ProxyService:
    """代理转发服务"""

    @staticmethod
    def _safe_error_message(prefix: str, exc: BaseException) -> str:
        """安全构造异常错误消息，避免 str(exc) 为空时显示空白"""
        text = str(exc).strip()
        if not text:
            text = f"{type(exc).__name__}"
        return f"{prefix}{text}"

    @staticmethod
    def _extract_model_refusal_text(response_data: Any) -> Optional[str]:
        """从上游响应中提取模型的文本内容（当模型返回文本而非图片时）"""
        if not isinstance(response_data, dict):
            return None
        choices = response_data.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                text = content.strip()
                if len(text) > 300:
                    text = text[:300] + "..."
                return text
        return None

    def __init__(self):
        self.timeout = httpx.Timeout(settings.proxy_request_timeout_seconds)
        self.stream_timeout = httpx.Timeout(
            connect=settings.proxy_stream_connect_timeout_seconds,
            read=settings.proxy_stream_read_timeout_seconds,
            write=settings.proxy_stream_connect_timeout_seconds,
            pool=settings.proxy_stream_connect_timeout_seconds,
        )
        self.stream_first_byte_timeout_seconds = settings.proxy_stream_first_byte_timeout_seconds

    def _build_image_generation_timeout(self) -> httpx.Timeout:
        request_timeout_seconds = max(int(settings.proxy_request_timeout_seconds or 60), 1)
        image_read_timeout_seconds = max(request_timeout_seconds * 5, 300)
        return httpx.Timeout(
            connect=request_timeout_seconds,
            read=image_read_timeout_seconds,
            write=request_timeout_seconds,
            pool=request_timeout_seconds,
        )

    def _build_image_probe_timeout(self, timeout_seconds: int) -> httpx.Timeout:
        seconds = min(max(int(timeout_seconds or 25), 5), 120)
        return httpx.Timeout(
            connect=min(seconds, 15),
            read=seconds,
            write=seconds,
            pool=seconds,
        )

    def _build_headers(self, api_key: Any, original_headers: dict) -> dict:
        """
        构建转发请求的 Headers

        Args:
            api_key: API Key 对象
            original_headers: 原始请求头

        Returns:
            转发请求头
        """
        headers = {}

        allowed_headers = [
            "accept",
            "content-type",
            "user-agent",
            "openai-beta",
            "openai-organization",
            "openai-project",
            "anthropic-version",
            "anthropic-beta",
        ]
        for header_name in allowed_headers:
            header_value = original_headers.get(header_name)
            if header_value:
                headers[header_name] = header_value

        headers.setdefault("content-type", "application/json")

        # 根据不同的 provider 设置认证头
        if api_key.provider == "claude":
            headers["x-api-key"] = api_key.api_key
            headers["anthropic-version"] = original_headers.get(
                "anthropic-version", headers.get("anthropic-version", "2023-06-01")
            )
        else:
            # OpenAI 及其兼容接口
            headers["Authorization"] = f"Bearer {api_key.api_key}"
            if original_headers.get("accept"):
                headers["accept"] = original_headers["accept"]

        self._apply_fake_ip_headers(api_key, headers)
        return headers

    def _apply_fake_ip_headers(self, api_key: Any, headers: dict):
        if not bool(getattr(api_key, "enable_fake_ip", False)):
            return

        fake_ip = (getattr(api_key, "fake_ip", None) or "").strip()
        if not fake_ip:
            return

        try:
            ipaddress.ip_address(fake_ip)
        except ValueError:
            return

        headers["x-forwarded-for"] = fake_ip
        headers["x-real-ip"] = fake_ip

    def _build_url(self, api_key: Any, path: str) -> str:
        """
        构建转发请求的 URL

        Args:
            api_key: API Key 对象
            path: 请求路径

        Returns:
            完整 URL
        """
        base_url = api_key.base_url.rstrip("/")
        path = path.lstrip("/")

        if base_url.endswith("/v1") and path.startswith("v1/"):
            path = path[3:]

        return f"{base_url}/{path}"

    def _extract_error_message(self, response_data: Any, fallback: str) -> str:
        if isinstance(response_data, dict):
            error = response_data.get("error")
            if isinstance(error, dict) and error.get("message"):
                return str(error["message"])
            if isinstance(error, str) and error:
                return error
            if response_data.get("detail"):
                return str(response_data["detail"])
        if isinstance(response_data, str) and response_data:
            return response_data
        return fallback

    def _build_proxy_url(self, api_key: Any) -> Optional[str]:
        if not bool(getattr(api_key, "enable_proxy", False)):
            return None

        proxy_url = (getattr(api_key, "proxy_url", None) or "").strip()
        if not proxy_url:
            return None

        proxy_username = getattr(api_key, "proxy_username", None)
        proxy_password = getattr(api_key, "proxy_password", None)
        if not proxy_username and not proxy_password:
            return proxy_url

        parts = urlsplit(proxy_url)
        if not parts.scheme or not parts.netloc:
            return proxy_url

        username = quote(str(proxy_username or ""), safe="")
        password = quote(str(proxy_password or ""), safe="")
        auth_text = username
        if proxy_password is not None and proxy_password != "":
            auth_text = f"{auth_text}:{password}"

        hostname = parts.hostname or ""
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{auth_text}@{hostname}{port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

    def _build_client_kwargs(self, api_key: Any, timeout: httpx.Timeout) -> dict:
        client_kwargs = {"timeout": timeout}
        proxy_url = self._build_proxy_url(api_key)
        if proxy_url:
            client_kwargs["proxy"] = proxy_url
        return client_kwargs

    def _classify_check_failure(self, status_code: Optional[int], error_message: Optional[str]) -> str:
        if status_code in {401, 403}:
            return "401_403"
        if status_code == 404:
            return "404"
        if status_code == 429:
            return "429"
        if status_code == 502:
            return "502"
        if status_code == 503:
            return "503"
        if isinstance(status_code, int) and status_code >= 500:
            return "5xx_other"

        message = (error_message or "").lower()
        if any(marker in message for marker in ["timeout", "timed out", "超时"]):
            return "timeout"
        if any(marker in message for marker in ["request error", "请求错误", "connection", "connect", "network"]):
            return "request_error"
        if "上游返回文本而非图片" in (error_message or ""):
            return "model_refused"

        return "unknown"

    def _build_probe_result(
        self,
        *,
        status: str,
        status_code: Optional[int],
        error_message: Optional[str],
        response_time_ms: int,
        path: str,
        url: str,
    ) -> dict:
        return {
            "status": status,
            "status_code": status_code,
            "error_message": error_message,
            "response_time_ms": response_time_ms,
            "path": path,
            "url": url,
        }

    async def _send_probe_request(
        self,
        api_key: Any,
        *,
        method: str,
        path: str,
        headers: Optional[dict] = None,
        body: Optional[dict] = None,
    ) -> dict:
        url = self._build_url(api_key, path)
        request_headers = self._build_headers(api_key, headers or {})
        started_at = time.perf_counter()

        try:
            async with httpx.AsyncClient(**self._build_client_kwargs(api_key, httpx.Timeout(settings.proxy_request_timeout_seconds))) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=request_headers,
                    json=body if body else None,
                )
            response_time_ms = int((time.perf_counter() - started_at) * 1000)
            response_data = self._parse_response_body(response)
            error_message = None
            status = "success"
            if response.status_code >= 400:
                status = "error"
                error_message = self._extract_error_message(response_data, response.reason_phrase or "请求失败")

            return self._build_probe_result(
                status=status,
                status_code=response.status_code,
                error_message=error_message,
                response_time_ms=response_time_ms,
                path=path,
                url=url,
            )
        except httpx.TimeoutException as e:
            return self._build_probe_result(
                status="error",
                status_code=None,
                error_message=self._safe_error_message("请求超时: ", e),
                response_time_ms=int((time.perf_counter() - started_at) * 1000),
                path=path,
                url=url,
            )
        except httpx.RemoteProtocolError as e:
            error_text = str(e).lower()
            if "server disconnected" in error_text:
                msg = self._safe_error_message("上游服务断开连接: ", e)
            else:
                msg = self._safe_error_message("上游协议错误: ", e)
            return self._build_probe_result(
                status="error",
                status_code=None,
                error_message=msg,
                response_time_ms=int((time.perf_counter() - started_at) * 1000),
                path=path,
                url=url,
            )
        except httpx.RequestError as e:
            return self._build_probe_result(
                status="error",
                status_code=None,
                error_message=self._safe_error_message("请求错误: ", e),
                response_time_ms=int((time.perf_counter() - started_at) * 1000),
                path=path,
                url=url,
            )
        except Exception as e:
            return self._build_probe_result(
                status="error",
                status_code=None,
                error_message=self._safe_error_message("未知错误: ", e),
                response_time_ms=int((time.perf_counter() - started_at) * 1000),
                path=path,
                url=url,
            )

    async def check_key_endpoint(self, api_key: Any) -> dict:
        return await self._send_probe_request(
            api_key,
            method="GET",
            path="v1/models",
            headers={"accept": "application/json"},
        )

    async def check_key_model(self, api_key: Any, target_model: str) -> dict:
        normalized_model = (target_model or "").strip()
        if api_key.provider == "claude":
            return await self._send_probe_request(
                api_key,
                method="POST",
                path="v1/messages",
                headers={"accept": "application/json", "content-type": "application/json"},
                body={
                    "model": normalized_model,
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )

        return await self._send_probe_request(
            api_key,
            method="POST",
            path="v1/chat/completions",
            headers={"accept": "application/json", "content-type": "application/json"},
            body={
                "model": normalized_model,
                "stream": False,
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "ping"}],
            },
        )

    async def check_key_connectivity_and_model(self, api_key: Any, target_model: str) -> dict:
        address_check = await self.check_key_endpoint(api_key)
        model_check = None

        if address_check["status"] == "success":
            model_check = await self.check_key_model(api_key, target_model)

        failed_check = address_check if address_check["status"] != "success" else model_check
        status = "success" if failed_check is None or failed_check["status"] == "success" else "error"
        response_time_ms = int(address_check.get("response_time_ms") or 0)
        if model_check:
            response_time_ms += int(model_check.get("response_time_ms") or 0)

        failure_category = None
        failure_detail = None
        if failed_check and failed_check["status"] != "success":
            failure_detail = failed_check.get("error_message")
            failure_category = self._classify_check_failure(
                failed_check.get("status_code"),
                failure_detail,
            )

        return {
            "status": status,
            "target_model": target_model,
            "response_time_ms": response_time_ms,
            "failure_category": failure_category,
            "failure_detail": failure_detail,
            "address_check": address_check,
            "model_check": model_check,
        }

    def _extract_image_results(self, response_data: Any) -> list[dict]:
        images = []

        def add_image(item: Any):
            if not isinstance(item, dict):
                return
            image_url = item.get("url") or item.get("image_url")
            image_base64 = item.get("b64_json") or item.get("image_base64") or item.get("base64") or item.get("result")
            if not image_url and not image_base64:
                nested = item.get("image")
                if isinstance(nested, dict):
                    image_url = nested.get("url") or nested.get("image_url")
                    image_base64 = nested.get("b64_json") or nested.get("base64")
            if image_url or image_base64:
                images.append(
                    {
                        "image_url": image_url,
                        "image_base64": image_base64,
                        "mime_type": item.get("mime_type") or item.get("mime") or "image/png",
                        "width": item.get("width"),
                        "height": item.get("height"),
                        "meta": item,
                    }
                )

        def scan_value(value: Any, depth: int = 0):
            if depth > 6:
                return
            if isinstance(value, dict):
                add_image(value)
                for child in value.values():
                    scan_value(child, depth + 1)
            elif isinstance(value, list):
                for child in value:
                    scan_value(child, depth + 1)
            elif isinstance(value, str):
                for match in re.finditer(r"https?://[^\s`\"'<>，,;；。)）]+|data:image/[^\s`\"'<>，,;；。)）]+", value):
                    cleaned = match.group(0).strip('`\"\'，,;；。')
                    if cleaned.startswith("http://") or cleaned.startswith("https://"):
                        images.append(
                            {
                                "image_url": cleaned,
                                "image_base64": None,
                                "mime_type": "image/png",
                                "width": None,
                                "height": None,
                                "meta": {"source": "text"},
                            }
                        )
                    elif cleaned.startswith("data:image/"):
                        images.append(
                            {
                                "image_url": None,
                                "image_base64": cleaned,
                                "mime_type": cleaned.split(";", 1)[0].replace("data:", "", 1) or "image/png",
                                "width": None,
                                "height": None,
                                "meta": {"source": "data_url_text"},
                            }
                        )

        scan_value(response_data)
        unique_images = []
        seen = set()
        for image in images:
            marker = image.get("image_url") or image.get("image_base64")
            if not marker or marker in seen:
                continue
            seen.add(marker)
            unique_images.append(image)
        return unique_images

    def _extract_upstream_image_task(self, response_data: Any) -> dict:
        task_info: dict[str, Any] = {}

        def visit(value: Any, depth: int = 0):
            if depth > 5 or not isinstance(value, (dict, list)):
                return
            if isinstance(value, list):
                for item in value:
                    visit(item, depth + 1)
                return

            if not task_info.get("task_id"):
                task_info["task_id"] = (
                    value.get("task_id")
                    or value.get("taskId")
                    or value.get("generation_id")
                    or value.get("generationId")
                    or value.get("request_id")
                    or value.get("requestId")
                    or value.get("id")
                )
            if not task_info.get("status_url"):
                task_info["status_url"] = (
                    value.get("status_url")
                    or value.get("statusUrl")
                    or value.get("polling_url")
                    or value.get("pollingUrl")
                    or value.get("poll_url")
                    or value.get("pollUrl")
                )
            if not task_info.get("result_url"):
                task_info["result_url"] = (
                    value.get("result_url")
                    or value.get("resultUrl")
                    or value.get("output_url")
                    or value.get("outputUrl")
                )
            if not task_info.get("status"):
                task_info["status"] = value.get("status") or value.get("state")

            for child in value.values():
                visit(child, depth + 1)

        visit(response_data)
        return {key: value for key, value in task_info.items() if value}

    def _build_image_task_probe_urls(self, api_key: Any, upstream_task: dict) -> list[str]:
        """构造图片异步任务查询地址"""
        urls = []
        for key in ("result_url", "status_url"):
            value = upstream_task.get(key)
            if value:
                urls.append(str(value))

        task_id = upstream_task.get("task_id") or upstream_task.get("request_id") or upstream_task.get("generation_id") or upstream_task.get("id")
        if task_id:
            encoded_task_id = str(task_id).strip().strip("/")
            for path in (
                f"v1/images/generations/{encoded_task_id}",
                f"v1/images/generations/{encoded_task_id}/status",
                f"v1/images/generations/{encoded_task_id}/result",
                f"v1/images/tasks/{encoded_task_id}",
                f"v1/images/tasks/{encoded_task_id}/status",
                f"v1/images/tasks/{encoded_task_id}/result",
                f"v1/image/tasks/{encoded_task_id}",
                f"v1/tasks/{encoded_task_id}",
                f"v1/tasks/{encoded_task_id}/status",
                f"v1/tasks/{encoded_task_id}/result",
                f"v1/task/{encoded_task_id}",
                f"v1/generations/{encoded_task_id}",
            ):
                urls.append(self._build_url(api_key, path))

        unique_urls = []
        seen = set()
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique_urls.append(url)
        return unique_urls

    def _build_image_message_content(self, prompt: str, input_images: Optional[list[dict]]) -> list[dict]:
        content = [{"type": "text", "text": prompt}]
        for item in input_images or []:
            if not isinstance(item, dict):
                continue
            # 优先使用在线 URL，回退到 data URL
            image_url = item.get("image_url") or ""
            data_url = item.get("data_url") or ""
            url = image_url if image_url.startswith(("http://", "https://")) else data_url
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        return content

    def _get_input_image_data_urls(self, input_images: Optional[list[dict]]) -> list[str]:
        """获取图生图输入图片的可用 URL（优先在线 URL，回退 data URL）"""
        urls = []
        for item in input_images or []:
            if not isinstance(item, dict):
                continue
            image_url = item.get("image_url") or ""
            if image_url.startswith(("http://", "https://")):
                urls.append(image_url)
            elif item.get("data_url"):
                urls.append(item["data_url"])
        return urls

    def _guess_image_extension(self, mime_type: str) -> str:
        return {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
        }.get(mime_type, ".png")

    def _safe_image_filename(self, filename: Optional[str], mime_type: str, index: int) -> str:
        base_name = ""
        if filename:
            base_name = str(filename).replace("\\", "/").rsplit("/", 1)[-1].strip()
            base_name = "".join(char if char.isalnum() or char in {".", "-", "_"} else "_" for char in base_name)

        extension = self._guess_image_extension(mime_type)
        if not base_name:
            return f"input-{index}{extension}"
        if "." not in base_name:
            return f"{base_name}{extension}"
        return base_name

    def _decode_image_data_url(self, item: dict, index: int) -> tuple[str, bytes, str]:
        data_url = str(item.get("data_url") or "")
        header, separator, encoded = data_url.partition(",")
        if separator != "," or not encoded or not header.startswith("data:image/"):
            raise ValueError("参考图 data URL 格式不正确")

        meta_parts = header.split(";")
        mime_type = meta_parts[0].replace("data:", "", 1).lower()
        if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("参考图仅支持 PNG、JPEG、WebP")
        if "base64" not in [part.lower() for part in meta_parts[1:]]:
            raise ValueError("参考图必须使用 base64 编码")

        try:
            content = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("参考图 base64 内容不正确") from exc

        filename = self._safe_image_filename(item.get("name"), mime_type, index)
        return filename, content, mime_type

    def _download_image_from_url(self, item: dict, index: int) -> tuple[str, bytes, str]:
        """从在线 URL 下载图片，用于官方 edits 接口的 multipart 上传"""
        import urllib.request
        import ssl
        image_url = str(item.get("image_url") or "")
        if not image_url.startswith(("http://", "https://")):
            raise ValueError("参考图在线 URL 格式不正确")

        request = urllib.request.Request(image_url, headers={"User-Agent": "CPA/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read()
                content_type = response.headers.get("Content-Type", "image/png")
        except Exception as exc:
            # SSL 错误时使用忽略验证的方式重试
            error_text = str(exc).lower()
            if "ssl" in error_text or "eof" in error_text or "certificate" in error_text:
                try:
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    with urllib.request.urlopen(request, timeout=30, context=ctx) as response:
                        content = response.read()
                        content_type = response.headers.get("Content-Type", "image/png")
                except Exception as retry_exc:
                    raise ValueError(f"下载参考图失败（已尝试跳过 SSL 验证）：{retry_exc}") from retry_exc
            else:
                # 下载失败时尝试使用本地缓存文件
                local_content = self._try_load_local_image(item)
                if local_content is not None:
                    return local_content
                raise ValueError(f"下载参考图失败：{exc}") from exc

        # 从 Content-Type 推断 MIME 类型
        mime_type = content_type.split(";")[0].strip().lower()
        if mime_type not in {"image/png", "image/jpeg", "image/webp"}:
            mime_type = "image/png"

        filename = self._safe_image_filename(item.get("name"), mime_type, index)
        return filename, content, mime_type

    @staticmethod
    def _try_load_local_image(item: dict) -> Optional[tuple[str, bytes, str]]:
        """下载失败时尝试从本地缓存加载图片"""
        import os
        local_path = item.get("local_path") or ""
        if not local_path:
            return None
        if not os.path.isfile(local_path):
            return None
        try:
            with open(local_path, "rb") as f:
                content = f.read()
            if not content:
                return None
            ext = os.path.splitext(local_path)[1].lower()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
            mime_type = mime_map.get(ext, "image/png")
            filename = os.path.basename(local_path)
            logger.info("image_download_fallback_local local_path=%s size=%d", local_path, len(content))
            return filename, content, mime_type
        except Exception:
            return None

    def _build_official_image_edit_payload(
        self,
        *,
        model: str,
        prompt: str,
        size: Optional[str],
        quality: Optional[str],
        n: int,
        input_images: Optional[list[dict]],
    ) -> tuple[dict, list[tuple[str, tuple[str, bytes, str]]], dict]:
        data = {
            "model": model,
            "prompt": prompt,
            "n": str(n),
        }
        if size and size != "auto":
            data["size"] = size
        if quality and quality != "auto":
            data["quality"] = quality

        files = []
        for index, item in enumerate(input_images or [], start=1):
            if not isinstance(item, dict):
                continue
            # 优先使用 data_url，没有则从在线 URL 下载
            if item.get("data_url"):
                filename, content, mime_type = self._decode_image_data_url(item, index)
            elif item.get("image_url", "").startswith(("http://", "https://")):
                filename, content, mime_type = self._download_image_from_url(item, index)
            else:
                continue
            files.append(("image", (filename, content, mime_type)))

        request_body = {
            "model": model,
            "prompt": prompt,
            "n": n,
            "mode": "image_to_image",
            "request_format": "images",
            "input_images_count": len(files),
        }
        if size:
            request_body["size"] = size
        if quality and quality != "auto":
            request_body["quality"] = quality

        return data, files, request_body

    # 网络层瞬时错误：重试可能恢复
    _STREAMING_RETRYABLE_ERROR_KEYWORDS = (
        "connection reset",
        "connection was closed",
        "temporarily unavailable",
        "name resolution",
        "connect call failed",
    )

    def _is_streaming_error_retryable(
        self,
        response_status_code: Optional[int],
        response_data: dict,
        exc: Optional[BaseException] = None,
    ) -> bool:
        """判断流式请求失败是否值得重试。

        仅网络层瞬时错误可重试；上游生成失败、限流、超时等不重试。
        """
        if exc is not None:
            if isinstance(exc, httpx.TimeoutException):
                return False
            message = str(exc).lower()
            return any(kw in message for kw in self._STREAMING_RETRYABLE_ERROR_KEYWORDS)

        if response_status_code is not None:
            if response_status_code == 429:
                return False
            if response_status_code >= 500:
                return False
            if response_status_code >= 400:
                return False

        error_msg = self._extract_error_message(response_data, "").lower()
        if not error_msg:
            return True
        if any(kw in error_msg for kw in self._STREAMING_RETRYABLE_ERROR_KEYWORDS):
            return True
        if "server disconnected" in error_msg:
            return False
        if "too many requests" in error_msg or "rate limit" in error_msg:
            return False
        if "timeout" in error_msg:
            return False
        return False

    async def _generate_image_streaming(
        self,
        *,
        client_kwargs: dict,
        url: str,
        headers: dict,
        body: dict,
        model: str,
        api_key: Any,
    ) -> tuple[dict, Optional[int], Any, bool]:
        """流式发送图片生成请求（chat/responses 格式），通过 SSE 保活避免 Cloudflare 超时。

        返回 (response_data, status_code, response_obj, retryable)。
        retryable=True 表示该失败为网络层瞬时错误，重试可能恢复。
        """
        accumulated_content = ""
        last_chunk_data: dict = {}
        response_status_code: Optional[int] = None
        response_obj = None
        # 保活头：减少中间代理因空闲断连的概率
        streaming_headers = {
            **headers,
            "Connection": "keep-alive",
            "Keep-Alive": "timeout=600",
        }
        try:
            async with httpx.AsyncClient(**client_kwargs) as client:
                request = client.build_request("POST", url=url, headers=streaming_headers, json=body)
                response = await client.send(request, stream=True)
                response_obj = response
                response_status_code = response.status_code

                if response.status_code >= 400:
                    # 错误响应：读取完整 body
                    error_body = await response.aread()
                    try:
                        last_chunk_data = json.loads(error_body)
                    except (json.JSONDecodeError, ValueError):
                        last_chunk_data = {"error": {"message": error_body.decode("utf-8", errors="replace")}}
                    await response.aclose()
                    retryable = self._is_streaming_error_retryable(response_status_code, last_chunk_data)
                    return last_chunk_data, response_status_code, response_obj, retryable

                # 流式读取 SSE chunks
                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            last_chunk_data = chunk
                            # 提取 chat 格式的 content 片段
                            choices = chunk.get("choices") or []
                            for choice in choices:
                                delta = choice.get("delta") or {}
                                content_piece = delta.get("content") or ""
                                if content_piece:
                                    accumulated_content += content_piece
                        except (json.JSONDecodeError, ValueError):
                            continue
                await response.aclose()
        except httpx.TimeoutException as exc:
            data = {"error": {"message": "流式请求超时"}}
            return data, response_status_code, response_obj, False
        except httpx.RemoteProtocolError as exc:
            error_text = str(exc).lower()
            if "server disconnected" in error_text:
                data = {"error": {"message": self._safe_error_message("上游服务在生成过程中断开连接（约40秒时触发）: ", exc)}}
            else:
                data = {"error": {"message": self._safe_error_message("上游协议错误: ", exc)}}
            retryable = self._is_streaming_error_retryable(response_status_code, data, exc)
            return data, response_status_code, response_obj, retryable
        except httpx.RequestError as exc:
            data = {"error": {"message": self._safe_error_message("流式请求错误: ", exc)}}
            retryable = self._is_streaming_error_retryable(response_status_code, data, exc)
            return data, response_status_code, response_obj, retryable
        except Exception as exc:
            logger.exception("image_streaming_error key_id=%s model=%s", getattr(api_key, "id", None), model)
            data = {"error": {"message": self._safe_error_message("流式处理异常: ", exc)}}
            return data, response_status_code, response_obj, False

        # 从最后一个有效 chunk 或累积内容中组装完整响应
        if last_chunk_data and isinstance(last_chunk_data.get("choices"), list):
            # chat 格式：将累积的 content 放入最后一个 chunk 的 message 中
            choices = last_chunk_data.get("choices") or []
            for choice in choices:
                if "message" not in choice and accumulated_content:
                    choice["message"] = {"role": "assistant", "content": accumulated_content}
                elif "delta" in choice and accumulated_content:
                    choice["message"] = {"role": "assistant", "content": accumulated_content}
                    choice.pop("delta", None)
            return last_chunk_data, response_status_code, response_obj, False

        if accumulated_content:
            # 构造标准 chat 响应格式
            return {
                "id": last_chunk_data.get("id") or "",
                "object": "chat.completion",
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": accumulated_content}, "finish_reason": "stop"}],
            }, response_status_code, response_obj, False

        # 没有累积到内容，返回最后一个 chunk
        return last_chunk_data or {}, response_status_code, response_obj, False

    async def generate_image(
        self,
        api_key: Any,
        *,
        model: str,
        prompt: str,
        size: Optional[str] = None,
        quality: Optional[str] = None,
        n: int = 1,
        request_format: str = "images",
        mode: str = "text_to_image",
        input_images: Optional[list[dict]] = None,
        probe_timeout_seconds: Optional[int] = None,
        upstream_tracking_id: Optional[str] = None,
    ) -> dict:
        started_at = time.perf_counter()
        path = ""
        url = ""
        body: dict[str, Any] = {}
        try:
            normalized_format = request_format if request_format in {"images", "chat", "responses"} else "images"
            normalized_mode = mode if mode in {"text_to_image", "image_to_image"} else "text_to_image"
            use_streaming = False
            image_data_urls = self._get_input_image_data_urls(input_images)
            is_image_to_image = normalized_mode == "image_to_image" and bool(image_data_urls)
            use_official_image_edit = (
                normalized_format == "images"
                and is_image_to_image
                and model.strip().lower() in {"gpt-image-2", "gpt-image-2-pro"}
            )
            multipart_data = None
            multipart_files = None

            if use_official_image_edit:
                path = "v1/images/edits"
                multipart_data, multipart_files, body = self._build_official_image_edit_payload(
                    model=model,
                    prompt=prompt,
                    size=size,
                    quality=quality,
                    n=n,
                    input_images=input_images,
                )
                body["path"] = path
            elif normalized_format == "chat":
                path = "v1/chat/completions"
                use_streaming = True
                chat_content = self._build_image_message_content(prompt, input_images) if is_image_to_image else prompt
                # 将尺寸和质量要求附加到 prompt 中
                size_hint_parts = []
                if size:
                    size_hint_parts.append(f"size: {size}")
                if quality and quality != "auto":
                    size_hint_parts.append(f"quality: {quality}")
                if size_hint_parts:
                    chat_content = f"{chat_content}\n\n[{', '.join(size_hint_parts)}]"
                body = {
                    "model": model,
                    "stream": True,
                    "messages": [
                        {
                            "role": "user",
                            "content": chat_content,
                        }
                    ],
                }
            elif normalized_format == "responses":
                path = "v1/responses"
                use_streaming = True
                responses_content = self._build_image_message_content(prompt, input_images) if is_image_to_image else prompt
                size_hint_parts = []
                if size:
                    size_hint_parts.append(f"size: {size}")
                if quality and quality != "auto":
                    size_hint_parts.append(f"quality: {quality}")
                if size_hint_parts:
                    responses_content = f"{responses_content}\n\n[{', '.join(size_hint_parts)}]"
                body = {
                    "model": model,
                    "stream": True,
                    "input": [
                        {
                            "role": "user",
                            "content": responses_content,
                        }
                    ],
                }
            else:
                path = "v1/images/generations"
                body = {
                    "model": model,
                    "prompt": prompt,
                    "n": n,
                }
                if is_image_to_image:
                    body["image"] = image_data_urls[0]
                    body["images"] = image_data_urls
                    body["reference_images"] = image_data_urls
                if size:
                    body["size"] = size
                if quality and quality != "auto":
                    body["quality"] = quality

            if upstream_tracking_id:
                tracking_id = str(upstream_tracking_id).strip()
                if tracking_id:
                    body["user"] = tracking_id
                    if normalized_format in {"chat", "responses"}:
                        body["metadata"] = {"cpa_task_id": tracking_id}
                    if use_official_image_edit:
                        multipart_data = dict(multipart_data or {})
                        multipart_data["user"] = tracking_id

            url = self._build_url(api_key, path)
            headers = self._build_headers(api_key, {"accept": "application/json", "content-type": "application/json"})
            if upstream_tracking_id:
                headers["x-cpa-task-id"] = str(upstream_tracking_id)
                headers["x-request-id"] = str(upstream_tracking_id)
            if use_official_image_edit:
                headers = self._build_headers(api_key, {"accept": "application/json"})
                if upstream_tracking_id:
                    headers["x-cpa-task-id"] = str(upstream_tracking_id)
                    headers["x-request-id"] = str(upstream_tracking_id)
                headers.pop("content-type", None)

            image_timeout = self._build_image_probe_timeout(probe_timeout_seconds) if probe_timeout_seconds else self._build_image_generation_timeout()

            if use_streaming and not use_official_image_edit:
                # 流式请求：chat/responses 格式使用 stream:true 保持连接活跃，避免 Cloudflare 超时
                # 仅对网络层瞬时错误重试，上游生成失败等不可恢复错误不重试
                max_streaming_retries = 2
                response_data = {}
                response_status_code = None
                response = None
                retryable = False
                for attempt in range(max_streaming_retries + 1):
                    response_data, response_status_code, response, retryable = await self._generate_image_streaming(
                        client_kwargs=self._build_client_kwargs(api_key, image_timeout),
                        url=url,
                        headers=headers,
                        body=body,
                        model=model,
                        api_key=api_key,
                    )
                    images = self._extract_image_results(response_data)
                    if images:
                        break
                    if not retryable or attempt >= max_streaming_retries:
                        break
                    logger.info(
                        "image_streaming_retry key_id=%s model=%s attempt=%d/%d status_code=%s error=%s",
                        getattr(api_key, "id", None), model, attempt + 1, max_streaming_retries,
                        response_status_code, self._extract_error_message(response_data, ""),
                    )
                    await asyncio.sleep(1)

                response_time_ms = int((time.perf_counter() - started_at) * 1000)
                images = self._extract_image_results(response_data)
                upstream_task = self._extract_upstream_image_task(response_data)
                if upstream_tracking_id and not upstream_task.get("cpa_task_id"):
                    upstream_task["cpa_task_id"] = str(upstream_tracking_id)
                request_id = None
                if response is not None:
                    request_id = (
                        response.headers.get("x-request-id")
                        or response.headers.get("request-id")
                        or response.headers.get("openai-request-id")
                        or response.headers.get("anthropic-request-id")
                        or response.headers.get("x-oneapi-request-id")
                    )
                if request_id and not upstream_task.get("request_id"):
                    upstream_task["request_id"] = request_id

                error_message = None
                status = "success"
                if response_status_code and response_status_code >= 400:
                    status = "error"
                    error_message = self._extract_error_message(response_data, "图片生成失败")
                elif not images:
                    status = "error"
                    refusal_text = self._extract_model_refusal_text(response_data)
                    if refusal_text:
                        error_message = f"上游返回文本而非图片: {refusal_text}"
                    else:
                        error_message = "上游未返回可展示的图片结果"
                    logger.warning(
                        "image_generation_no_images key_id=%s provider=%s model=%s status_code=%s path=%s response_keys=%s response_preview=%s",
                        getattr(api_key, "id", None),
                        getattr(api_key, "provider", None),
                        model,
                        response_status_code,
                        path,
                        list(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__,
                        str(response_data)[:1000],
                    )
                else:
                    logger.info(
                        "image_generation_upstream_success key_id=%s provider=%s model=%s status_code=%s path=%s images=%s elapsed_ms=%s",
                        getattr(api_key, "id", None),
                        getattr(api_key, "provider", None),
                        model,
                        response_status_code,
                        path,
                        len(images),
                        response_time_ms,
                    )

                return {
                    "status": status,
                    "status_code": response_status_code,
                    "response_time_ms": response_time_ms,
                    "path": path,
                    "url": url,
                    "request_body": body,
                    "response_data": response_data,
                    "images": images,
                    "upstream_task": upstream_task,
                    "error_message": error_message,
                    "failure_category": self._classify_check_failure(response_status_code if status == "error" else None, error_message),
                }
            else:
                # 非流式请求：images 格式使用普通请求
                async with httpx.AsyncClient(**self._build_client_kwargs(api_key, image_timeout)) as client:
                    if use_official_image_edit:
                        response = await client.post(url=url, headers=headers, data=multipart_data, files=multipart_files)
                    else:
                        response = await client.post(url=url, headers=headers, json=body)
                response_time_ms = int((time.perf_counter() - started_at) * 1000)
                response_data = self._parse_response_body(response)
                images = self._extract_image_results(response_data)
                upstream_task = self._extract_upstream_image_task(response_data)
                if upstream_tracking_id and not upstream_task.get("cpa_task_id"):
                    upstream_task["cpa_task_id"] = str(upstream_tracking_id)
                request_id = (
                    response.headers.get("x-request-id")
                    or response.headers.get("request-id")
                    or response.headers.get("openai-request-id")
                    or response.headers.get("anthropic-request-id")
                    or response.headers.get("x-oneapi-request-id")
                )
                if request_id and not upstream_task.get("request_id"):
                    upstream_task["request_id"] = request_id

                error_message = None
                status = "success"
                if response.status_code >= 400:
                    status = "error"
                    error_message = self._extract_error_message(response_data, response.reason_phrase or "图片生成失败")
                elif not images:
                    status = "error"
                    refusal_text = self._extract_model_refusal_text(response_data)
                    if refusal_text:
                        error_message = f"上游返回文本而非图片: {refusal_text}"
                    else:
                        error_message = "上游未返回可展示的图片结果"
                    logger.warning(
                        "image_generation_no_images key_id=%s provider=%s model=%s status_code=%s path=%s response_keys=%s response_preview=%s",
                        getattr(api_key, "id", None),
                        getattr(api_key, "provider", None),
                        model,
                        response.status_code,
                        path,
                        list(response_data.keys()) if isinstance(response_data, dict) else type(response_data).__name__,
                        str(response_data)[:1000],
                    )
                else:
                    logger.info(
                        "image_generation_upstream_success key_id=%s provider=%s model=%s status_code=%s path=%s images=%s elapsed_ms=%s",
                        getattr(api_key, "id", None),
                        getattr(api_key, "provider", None),
                        model,
                        response.status_code,
                        path,
                        len(images),
                        response_time_ms,
                    )

                return {
                    "status": status,
                    "status_code": response.status_code,
                    "response_time_ms": response_time_ms,
                    "path": path,
                    "url": url,
                    "request_body": body,
                    "response_data": response_data,
                    "images": images,
                    "upstream_task": upstream_task,
                    "error_message": error_message,
                    "failure_category": self._classify_check_failure(response.status_code if status == "error" else None, error_message),
                }
        except asyncio.CancelledError:
            logger.warning(
                "image_generation_proxy_cancelled key_id=%s provider=%s model=%s path=%s url=%s elapsed_ms=%s",
                getattr(api_key, "id", None),
                getattr(api_key, "provider", None),
                model,
                path,
                url,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise
        except httpx.TimeoutException as e:
            error_message = self._safe_error_message("请求超时: ", e)
        except httpx.RemoteProtocolError as e:
            error_text = str(e).lower()
            if "server disconnected" in error_text:
                error_message = self._safe_error_message("上游服务在生成过程中断开连接（约40秒时触发）: ", e)
            else:
                error_message = self._safe_error_message("上游协议错误: ", e)
        except httpx.RequestError as e:
            error_message = self._safe_error_message("请求错误: ", e)
        except Exception as e:
            error_message = self._safe_error_message("未知错误: ", e)
            logger.exception(
                "image_generation_proxy_exception key_id=%s provider=%s model=%s path=%s url=%s",
                getattr(api_key, "id", None),
                getattr(api_key, "provider", None),
                model,
                path,
                url,
            )

        logger.warning(
            "image_generation_proxy_error key_id=%s provider=%s model=%s path=%s url=%s error=%s",
            getattr(api_key, "id", None),
            getattr(api_key, "provider", None),
            model,
            path,
            url,
            error_message,
        )

        return {
            "status": "error",
            "status_code": None,
            "response_time_ms": int((time.perf_counter() - started_at) * 1000),
            "path": path,
            "url": url,
            "request_body": body,
            "response_data": {"error": {"message": error_message}},
            "images": [],
            "upstream_task": {},
            "error_message": error_message,
            "failure_category": self._classify_check_failure(None, error_message),
        }

    def _build_magic666_headers(self, user_id: Optional[int] = None, api_key: Any = None) -> dict:
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-store",
            "new-api-user": str(user_id if user_id is not None else -1),
        }
        if api_key:
            self._apply_fake_ip_headers(api_key, headers)
        return headers

    def _is_magic666_key(self, api_key: Any) -> bool:
        """判断 Key 是否支持 New API 任务日志回填（有密码配置即可，不限制域名）"""
        api_type = (getattr(api_key, "api_type", None) or "newapi").strip().lower()
        if api_type and api_type != "newapi":
            return False
        # 优先检查 Key 自身密码
        key_password = (getattr(api_key, "password", None) or "").strip()
        if key_password:
            return True
        # 再检查供应商默认密码
        from config import export_config as _ec
        provider = (getattr(api_key, "provider", "") or "").strip().lower()
        provider_ext = _ec.get("provider_ext") or {}
        cfg = provider_ext.get(provider) or {}
        return bool((cfg.get("password") or "").strip())

    def _normalize_match_text(self, value: Any) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value).strip())

    def _prompt_match_score(self, source: Any, target: Any) -> Optional[int]:
        source_text = self._normalize_match_text(source)
        target_text = self._normalize_match_text(target)
        if not source_text or not target_text:
            return None
        if source_text == target_text:
            return 0
        if source_text in target_text or target_text in source_text:
            return abs(len(source_text) - len(target_text))
        min_len = min(len(source_text), len(target_text))
        common_prefix = 0
        for left, right in zip(source_text, target_text):
            if left != right:
                break
            common_prefix += 1
        if min_len >= 10 and common_prefix / min_len >= 0.8:
            return min_len - common_prefix + abs(len(source_text) - len(target_text))
        return None

    def _task_log_item_match_score(self, item: dict, *, prompt: str, model: str, target_timestamp: int) -> Optional[int]:
        properties = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        item_prompt = item.get("prompt") or properties.get("prompt") or properties.get("input")
        item_model = item.get("upstream_model_name") or item.get("origin_model_name") or properties.get("upstream_model_name") or properties.get("origin_model_name")
        if model and item_model and str(item_model).strip() != str(model).strip():
            return None
        prompt_score = self._prompt_match_score(item_prompt, prompt)
        if prompt_score is None:
            return None
        item_timestamp = item.get("created_at") or item.get("submit_time") or item.get("start_time") or item.get("updated_at") or 0
        try:
            time_score = abs(int(item_timestamp) - int(target_timestamp))
        except (TypeError, ValueError):
            time_score = 0
        return time_score * 1000 + prompt_score

    async def fetch_magic666_task_log_result(
        self,
        api_key: Any,
        *,
        prompt: str,
        model: str,
        start_timestamp: int,
        end_timestamp: int,
        target_timestamp: Optional[int] = None,
        use_time_window: bool = True,
        upstream_task_id: Optional[str] = None,
    ) -> dict:
        started_at = time.perf_counter()
        if not self._is_magic666_key(api_key):
            message = "当前 Key 未配置登录密码，无法使用任务日志回填"
            return {
                "status": "error",
                "status_code": None,
                "response_time_ms": 0,
                "response_data": {"error": {"message": message}},
                "images": [],
                "upstream_task": {},
                "error_message": message,
                "failure_category": "unknown",
            }

        username = str(getattr(api_key, "name", "") or "").strip()
        if not username:
            message = "Key 名称为空，无法作为上游用户名登录"
            return {
                "status": "error",
                "status_code": None,
                "response_time_ms": 0,
                "response_data": {"error": {"message": message}},
                "images": [],
                "upstream_task": {},
                "error_message": message,
                "failure_category": "unknown",
            }

        base_url = str(getattr(api_key, "base_url", "") or "").strip().rstrip("/")
        # 图片回填优先用网页网址 wz_url，为空则取 base_url
        web_url = str(getattr(api_key, "wz_url", None) or "").strip().rstrip("/") or base_url
        origin = f"{urlsplit(web_url).scheme or 'https'}://{urlsplit(web_url).netloc}"
        login_url = f"{origin}/api/user/login?turnstile="
        task_url = f"{origin}/api/task/self"

        # 取密码：优先 Key 自身，其次供应商默认
        key_password = (getattr(api_key, "password", None) or "").strip()
        if not key_password:
            from config import export_config as _ec
            provider = (getattr(api_key, "provider", "") or "").strip().lower()
            provider_ext = _ec.get("provider_ext") or {}
            cfg = provider_ext.get(provider) or {}
            key_password = (cfg.get("password") or "").strip()
        if not key_password:
            message = "未配置登录密码，请在 Key 详情或系统设置中配置"
            return {
                "status": "error",
                "status_code": None,
                "response_time_ms": 0,
                "response_data": {"error": {"message": message}},
                "images": [],
                "upstream_task": {},
                "error_message": message,
                "failure_category": "unknown",
            }
        response_data: Any = {}
        status_code: Optional[int] = None
        try:
            async with httpx.AsyncClient(**self._build_client_kwargs(api_key, self._build_image_generation_timeout())) as client:
                login_response = await client.post(
                    login_url,
                    headers={**self._build_magic666_headers(api_key=api_key), "content-type": "application/json"},
                    json={"username": username, "password": key_password},
                )
                status_code = login_response.status_code
                login_data = self._parse_response_body(login_response)
                response_data = {"login": login_data}
                if login_response.status_code >= 400 or not isinstance(login_data, dict) or not login_data.get("success"):
                    message = self._extract_error_message(login_data, "上游登录失败")
                    return {
                        "status": "error",
                        "status_code": login_response.status_code,
                        "response_time_ms": int((time.perf_counter() - started_at) * 1000),
                        "response_data": response_data,
                        "images": [],
                        "upstream_task": {},
                        "error_message": message,
                        "failure_category": self._classify_check_failure(login_response.status_code, message),
                    }

                user_data = login_data.get("data") if isinstance(login_data.get("data"), dict) else {}
                user_id = user_data.get("id")
                if user_id is None:
                    message = "上游登录成功但未返回用户 ID"
                    return {
                        "status": "error",
                        "status_code": login_response.status_code,
                        "response_time_ms": int((time.perf_counter() - started_at) * 1000),
                        "response_data": response_data,
                        "images": [],
                        "upstream_task": {},
                        "error_message": message,
                        "failure_category": "unknown",
                    }

                task_params = {
                    "p": 1,
                    "page_size": 50,
                    "task_id": upstream_task_id or "",
                    "model": "",
                    "status": "",
                }
                if use_time_window:
                    task_params["start_timestamp"] = max(int(start_timestamp), 0)
                    task_params["end_timestamp"] = max(int(end_timestamp), int(start_timestamp))
                task_response = await client.get(
                    task_url,
                    headers=self._build_magic666_headers(int(user_id), api_key=api_key),
                    params=task_params,
                )
                status_code = task_response.status_code
                task_data = self._parse_response_body(task_response)
                response_data = {"login": login_data, "task_log": task_data}
                if task_response.status_code >= 400 or not isinstance(task_data, dict) or not task_data.get("success"):
                    message = self._extract_error_message(task_data, "上游任务日志查询失败")
                    return {
                        "status": "error",
                        "status_code": task_response.status_code,
                        "response_time_ms": int((time.perf_counter() - started_at) * 1000),
                        "response_data": response_data,
                        "images": [],
                        "upstream_task": {},
                        "error_message": message,
                        "failure_category": self._classify_check_failure(task_response.status_code, message),
                    }

                data = task_data.get("data") if isinstance(task_data.get("data"), dict) else {}
                items = data.get("items") if isinstance(data.get("items"), list) else []
                target_time = int(target_timestamp if target_timestamp is not None else start_timestamp)
                matched_items = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("status") or "").upper() != "SUCCESS":
                        continue
                    score = self._task_log_item_match_score(item, prompt=prompt, model=model, target_timestamp=target_time)
                    if score is None:
                        continue
                    matched_items.append((score, item))

                for _, item in sorted(matched_items, key=lambda value: value[0]):
                    images = self._extract_image_results(item)
                    if images:
                        upstream_task = {
                            "task_id": item.get("task_id") or item.get("id"),
                            "id": item.get("id"),
                            "status": item.get("status"),
                            "result_url": item.get("result_url"),
                            "source": "magic666_task_log",
                        }
                        return {
                            "status": "success",
                            "status_code": task_response.status_code,
                            "response_time_ms": int((time.perf_counter() - started_at) * 1000),
                            "response_data": response_data,
                            "images": images,
                            "upstream_task": upstream_task,
                            "error_message": None,
                            "failure_category": None,
                        }

                message = "上游任务日志未找到匹配的成功图片结果"
                return {
                    "status": "pending",
                    "status_code": task_response.status_code,
                    "response_time_ms": int((time.perf_counter() - started_at) * 1000),
                    "response_data": response_data,
                    "images": [],
                    "upstream_task": {"source": "magic666_task_log"},
                    "error_message": message,
                    "failure_category": None,
                }
        except httpx.TimeoutException as exc:
            error_message = self._safe_error_message("请求超时: ", exc)
        except httpx.RemoteProtocolError as exc:
            error_text = str(exc).lower()
            if "server disconnected" in error_text:
                error_message = self._safe_error_message("上游服务断开连接: ", exc)
            else:
                error_message = self._safe_error_message("上游协议错误: ", exc)
        except httpx.RequestError as exc:
            error_message = self._safe_error_message("请求错误: ", exc)
        except Exception as exc:
            error_message = self._safe_error_message("未知错误: ", exc)
            logger.exception("magic666_task_log_refresh_exception key_id=%s", getattr(api_key, "id", None))

        return {
            "status": "error",
            "status_code": status_code,
            "response_time_ms": int((time.perf_counter() - started_at) * 1000),
            "response_data": response_data or {"error": {"message": error_message}},
            "images": [],
            "upstream_task": {"source": "magic666_task_log"},
            "error_message": error_message,
            "failure_category": self._classify_check_failure(status_code, error_message),
        }

    async def fetch_image_task_result(self, api_key: Any, upstream_task: dict) -> dict:
        started_at = time.perf_counter()
        api_type = (getattr(api_key, "api_type", None) or "newapi").strip().lower()
        if api_type and api_type != "newapi":
            message = "当前 Key 类型不支持图片回填查询"
            return {
                "status": "error",
                "status_code": None,
                "response_time_ms": 0,
                "response_data": {"error": {"message": message}},
                "images": [],
                "upstream_task": upstream_task,
                "error_message": message,
                "failure_category": "unknown",
            }
        target_urls = self._build_image_task_probe_urls(api_key, upstream_task)
        if not target_urls:
            message = "上游未提供可重抓取的任务 ID 或查询地址"
            return {
                "status": "error",
                "status_code": None,
                "response_time_ms": 0,
                "response_data": {"error": {"message": message}},
                "images": [],
                "upstream_task": upstream_task,
                "error_message": message,
                "failure_category": "unknown",
            }

        last_response_data: Any = {}
        last_error_message = "上游暂未返回可展示的图片结果"
        last_status_code: Optional[int] = None
        refreshed_task = dict(upstream_task or {})
        headers = self._build_headers(api_key, {"accept": "application/json"})

        try:
            async with httpx.AsyncClient(**self._build_client_kwargs(api_key, self._build_image_generation_timeout())) as client:
                for target_url in target_urls:
                    response = await client.get(target_url, headers=headers)
                    last_status_code = response.status_code
                    response_data = self._parse_response_body(response)
                    last_response_data = response_data
                    refreshed_task = {**refreshed_task, **self._extract_upstream_image_task(response_data)}
                    images = self._extract_image_results(response_data)
                    if response.status_code < 400 and images:
                        return {
                            "status": "success",
                            "status_code": response.status_code,
                            "response_time_ms": int((time.perf_counter() - started_at) * 1000),
                            "response_data": response_data,
                            "images": images,
                            "upstream_task": refreshed_task,
                            "error_message": None,
                            "failure_category": None,
                        }
                    if response.status_code >= 400:
                        last_error_message = self._extract_error_message(response_data, response.reason_phrase or "重抓取失败")
                        if response.status_code == 404:
                            continue
                        break
                    last_error_message = "上游暂未返回可展示的图片结果"

            status = "error" if last_status_code and last_status_code >= 400 else "pending"
            return {
                "status": status,
                "status_code": last_status_code,
                "response_time_ms": int((time.perf_counter() - started_at) * 1000),
                "response_data": last_response_data,
                "images": [],
                "upstream_task": refreshed_task,
                "error_message": last_error_message,
                "failure_category": self._classify_check_failure(last_status_code if status == "error" else None, last_error_message),
            }
        except httpx.TimeoutException as exc:
            error_message = self._safe_error_message("请求超时: ", exc)
        except httpx.RemoteProtocolError as exc:
            error_text = str(exc).lower()
            if "server disconnected" in error_text:
                error_message = self._safe_error_message("上游服务断开连接: ", exc)
            else:
                error_message = self._safe_error_message("上游协议错误: ", exc)
        except httpx.RequestError as exc:
            error_message = self._safe_error_message("请求错误: ", exc)
        except Exception as exc:
            error_message = self._safe_error_message("未知错误: ", exc)
            logger.exception("image_task_refresh_exception urls=%s", target_urls)

        return {
            "status": "error",
            "status_code": None,
            "response_time_ms": int((time.perf_counter() - started_at) * 1000),
            "response_data": {"error": {"message": error_message}},
            "images": [],
            "upstream_task": upstream_task,
            "error_message": error_message,
            "failure_category": self._classify_check_failure(None, error_message),
        }

    def _log_stream_event(self, stage: str, **kwargs):
        details = " ".join(f"{key}={value}" for key, value in kwargs.items() if value is not None)
        print(f"[CPA STREAM] stage={stage} {details}".strip())

    def _parse_response_body(self, response: httpx.Response) -> Any:
        content_type = response.headers.get("content-type", "")
        response_text = response.text
        if "application/json" in content_type:
            try:
                return response.json()
            except ValueError:
                return {"error": {"message": response_text or response.reason_phrase}}

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            return {"error": {"message": response_text or response.reason_phrase}}

    def _filter_stream_response_headers(self, response_headers: httpx.Headers) -> dict:
        allowed_headers = [
            "content-type",
            "cache-control",
            "x-request-id",
            "request-id",
            "openai-processing-ms",
            "anthropic-request-id",
            "x-oneapi-request-id",
            "retry-after",
        ]
        filtered_headers = {}
        for header_name in allowed_headers:
            header_value = response_headers.get(header_name)
            if header_value:
                filtered_headers[header_name] = header_value
        return filtered_headers

    def _has_terminal_event(self, event_text: str) -> bool:
        event_name = None
        data_lines = []
        for line in event_text.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

        terminal_events = {
            "response.completed",
            "response.failed",
            "response.incomplete",
            "message_stop",
            "done",
            "completion",
        }
        if event_name in terminal_events:
            return True

        data_text = "\n".join(data_lines)
        if data_text == "[DONE]":
            return True

        if not data_text:
            return False

        try:
            payload = json.loads(data_text)
        except json.JSONDecodeError:
            return False

        if not isinstance(payload, dict):
            return False

        payload_type = payload.get("type")
        if payload_type in terminal_events:
            return True

        response_obj = payload.get("response")
        if isinstance(response_obj, dict) and response_obj.get("status") in {"completed", "failed", "incomplete", "cancelled"}:
            return True

        if payload.get("status") in {"completed", "failed", "incomplete", "cancelled"}:
            return True

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0] if isinstance(choices[0], dict) else {}
            if first_choice.get("finish_reason"):
                return True

        delta = payload.get("delta")
        if isinstance(delta, dict) and delta.get("finish_reason"):
            return True

        return False

    def _is_retryable_stream_failure(self, status_code: int, error_body: Any) -> bool:
        if status_code >= 500:
            return True
        if status_code in {502, 503, 504}:
            return True

        # nginx/代理层返回的 HTML 错误页，换 Key 可能恢复
        if 400 <= status_code < 500 and isinstance(error_body, dict):
            error = error_body.get("error") or {}
            msg = str(error.get("message") or "") if isinstance(error, dict) else ""
            if "<html" in msg.lower() or "<body" in msg.lower():
                return True

        if not isinstance(error_body, dict):
            return False

        error = error_body.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else None
        if not isinstance(message, str):
            return False

        retryable_markers = [
            "empty_stream",
            "stream closed before first payload",
            "upstream stream closed before first payload",
            "request timeout",
            "connection error",
            "首包超时",
            "读取超时",
            "请求错误",
            "请求超时",
        ]
        message_lower = message.lower()
        return any(marker in message_lower for marker in retryable_markers)

    def _build_stream_error_event(self, message: str) -> bytes:
        error_payload = json.dumps({"message": message, "type": "stream_error"}, ensure_ascii=False)
        return f"event: error\ndata: {error_payload}\n\n".encode("utf-8")

    def _extract_usage_tokens(self, response_data: Any) -> tuple[int, int, int, int]:
        """提取真实 token 用量，返回 (prompt, completion, total, cache)"""
        if not isinstance(response_data, dict):
            return 0, 0, 0, 0

        usage = response_data.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}

        if not usage and isinstance(response_data.get("response"), dict):
            nested_usage = response_data["response"].get("usage") or {}
            if isinstance(nested_usage, dict):
                usage = nested_usage

        if not isinstance(usage, dict) or not usage:
            return 0, 0, 0, 0

        prompt_tokens = usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0
        completion_tokens = usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0

        output_tokens_details = usage.get("output_tokens_details") or {}
        if isinstance(output_tokens_details, dict):
            completion_tokens = max(
                completion_tokens,
                (output_tokens_details.get("reasoning_tokens") or 0) + (output_tokens_details.get("text_tokens") or 0),
            )

        total_tokens = usage.get("total_tokens") or (prompt_tokens + completion_tokens)

        # 缓存 token：OpenAI 格式在 prompt_tokens_details.cached_tokens
        # Claude 格式在 cache_read_input_tokens
        cache_tokens = 0
        prompt_tokens_details = usage.get("prompt_tokens_details") or {}
        if isinstance(prompt_tokens_details, dict):
            cache_tokens = int(prompt_tokens_details.get("cached_tokens") or 0)
        if not cache_tokens:
            cache_tokens = int(
                usage.get("cache_read_input_tokens")
                or usage.get("cached_tokens")
                or usage.get("cache_tokens")
                or 0
            )

        return int(prompt_tokens), int(completion_tokens), int(total_tokens), int(cache_tokens)

    def _extract_stream_usage_from_sse(self, event_text: str) -> tuple[int, int, int, int]:
        """从流式 SSE 事件中提取真实 token 用量，返回 (prompt, completion, total, cache)"""
        event_name = None
        data_lines = []
        for line in event_text.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

        if not data_lines:
            return 0, 0, 0, 0

        data_text = "\n".join(data_lines)
        if data_text == "[DONE]":
            return 0, 0, 0, 0

        try:
            payload = json.loads(data_text)
        except json.JSONDecodeError:
            return 0, 0, 0, 0

        if event_name == "response.completed" and isinstance(payload.get("response"), dict):
            return self._extract_usage_tokens(payload["response"])

        # Claude 原生格式：message_start 事件的 usage 在 payload["message"]["usage"]
        if event_name == "message_start" and isinstance(payload.get("message"), dict):
            return self._extract_usage_tokens(payload["message"])

        return self._extract_usage_tokens(payload)

    def _extract_text_segments(self, content: Any) -> list[str]:
        if isinstance(content, str):
            return [content]

        if isinstance(content, dict):
            item_type = content.get("type")
            if item_type in {"input_text", "output_text", "text"} and content.get("text"):
                return [content["text"]]
            if item_type == "message":
                nested_segments = self._extract_text_segments(content.get("content"))
                if nested_segments:
                    return nested_segments
            if content.get("content") is not None:
                nested_segments = self._extract_text_segments(content.get("content"))
                if nested_segments:
                    return nested_segments
            return []

        if isinstance(content, list):
            segments = []
            for item in content:
                segments.extend(self._extract_text_segments(item))
            return segments

        return []

    def _responses_input_to_messages(self, input_data: Any) -> list[dict]:
        if input_data is None:
            return []

        if isinstance(input_data, str):
            return [{"role": "user", "content": input_data}]

        if isinstance(input_data, dict):
            input_data = [input_data]

        if isinstance(input_data, list):
            messages = []
            for item in input_data:
                if isinstance(item, str):
                    messages.append({"role": "user", "content": item})
                    continue

                if not isinstance(item, dict):
                    continue

                item_type = item.get("type")
                if item_type == "message":
                    role = item.get("role", "user")
                    text_segments = self._extract_text_segments(item.get("content"))
                    if text_segments:
                        messages.append({"role": role, "content": "\n".join(text_segments)})
                    elif item.get("content") is not None:
                        messages.append({"role": role, "content": str(item.get("content"))})
                    continue

                if item_type == "function_call":
                    call_id = item.get("call_id") or item.get("id") or f"call_{int(time.time() * 1000)}"
                    arguments = item.get("arguments")
                    if not isinstance(arguments, str):
                        arguments = json.dumps(arguments or {}, ensure_ascii=False)
                    messages.append(
                        {
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": call_id,
                                    "type": "function",
                                    "function": {
                                        "name": item.get("name") or "tool",
                                        "arguments": arguments,
                                    },
                                }
                            ],
                        }
                    )
                    continue

                if item_type == "function_call_output":
                    output = item.get("output")
                    if not isinstance(output, str):
                        output = json.dumps(output if output is not None else "", ensure_ascii=False)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": item.get("call_id") or item.get("id") or f"call_{int(time.time() * 1000)}",
                            "content": output,
                        }
                    )
                    continue

                role = item.get("role", "user")
                content = item.get("content", item)
                text_segments = self._extract_text_segments(content)
                if text_segments:
                    messages.append({"role": role, "content": "\n".join(text_segments)})
                elif content is not None:
                    messages.append({"role": role, "content": str(content)})

            return messages

        raise ValueError("unsupported input type")

    def _adapt_responses_tools_for_chat(self, tools: Any) -> list[dict]:
        if not isinstance(tools, list):
            return []

        adapted_tools = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue

            tool_type = tool.get("type")
            function_payload = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            name = function_payload.get("name")
            if tool_type not in {None, "function"} or not name:
                continue

            adapted_tool = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": function_payload.get("description") or "",
                    "parameters": function_payload.get("parameters") or {"type": "object", "properties": {}},
                },
            }

            if "strict" in function_payload:
                adapted_tool["function"]["strict"] = function_payload.get("strict")

            adapted_tools.append(adapted_tool)

        return adapted_tools

    def _adapt_responses_tool_choice_for_chat(self, tool_choice: Any, tools: list[dict]) -> Any:
        if not tools:
            return None

        if isinstance(tool_choice, str):
            return tool_choice

        if not isinstance(tool_choice, dict):
            return None

        tool_choice_type = tool_choice.get("type")
        if tool_choice_type in {"auto", "none", "required"}:
            return tool_choice_type

        if tool_choice_type in {"function", "tool"}:
            function_payload = tool_choice.get("function") if isinstance(tool_choice.get("function"), dict) else tool_choice
            name = function_payload.get("name")
            if not name:
                return None
            return {
                "type": "function",
                "function": {
                    "name": name,
                },
            }

        return None

    def adapt_responses_request_to_chat(self, body: dict) -> dict:
        chat_body = {}

        for source_key, target_key in [
            ("model", "model"),
            ("stream", "stream"),
            ("temperature", "temperature"),
            ("top_p", "top_p"),
            ("stop", "stop"),
            ("user", "user"),
            ("parallel_tool_calls", "parallel_tool_calls"),
            ("presence_penalty", "presence_penalty"),
            ("frequency_penalty", "frequency_penalty"),
        ]:
            if source_key in body:
                chat_body[target_key] = body[source_key]

        adapted_tools = self._adapt_responses_tools_for_chat(body.get("tools"))
        if adapted_tools:
            chat_body["tools"] = adapted_tools

        adapted_tool_choice = self._adapt_responses_tool_choice_for_chat(body.get("tool_choice"), adapted_tools)
        if adapted_tool_choice is not None:
            chat_body["tool_choice"] = adapted_tool_choice

        if "max_output_tokens" in body:
            chat_body["max_tokens"] = body["max_output_tokens"]

        messages = []
        if body.get("instructions"):
            messages.append({"role": "system", "content": body["instructions"]})

        messages.extend(self._responses_input_to_messages(body.get("input")))
        if not messages:
            raise ValueError("responses input is required")

        chat_body["messages"] = messages
        return chat_body

    def _extract_chat_message_text(self, message: dict) -> str:
        if not isinstance(message, dict):
            return ""

        content = message.get("content")
        if isinstance(content, str):
            return content

        text_segments = self._extract_text_segments(content)
        if text_segments:
            return "".join(text_segments)

        return ""

    def _normalize_tool_call_arguments(self, arguments: Any) -> str:
        if isinstance(arguments, str):
            return arguments
        return json.dumps(arguments or {}, ensure_ascii=False)

    def _build_response_message_item(self, message: dict, status: str, item_id: Optional[str] = None, output_text: Optional[str] = None) -> dict:
        item_id = item_id or f"msg_{int(time.time() * 1000)}"
        text = self._extract_chat_message_text(message) if output_text is None else output_text
        return {
            "id": item_id,
            "type": "message",
            "status": status,
            "role": message.get("role", "assistant"),
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                }
            ],
        }

    def _build_response_function_call_item(self, tool_call: dict, status: str) -> Optional[dict]:
        if not isinstance(tool_call, dict):
            return None

        function_payload = tool_call.get("function") or {}
        name = function_payload.get("name")
        if not name:
            return None

        call_id = tool_call.get("id") or f"call_{int(time.time() * 1000)}"
        return {
            "id": call_id,
            "type": "function_call",
            "status": status,
            "call_id": call_id,
            "name": name,
            "arguments": self._normalize_tool_call_arguments(function_payload.get("arguments")),
        }

    def _build_response_output_items(self, message: dict, status: str, item_id: Optional[str] = None, output_text: Optional[str] = None) -> list[dict]:
        output_items = [self._build_response_message_item(message, status, item_id=item_id, output_text=output_text)]
        for tool_call in message.get("tool_calls") or []:
            function_call_item = self._build_response_function_call_item(tool_call, status)
            if function_call_item:
                output_items.append(function_call_item)
        return output_items

    def adapt_chat_response_to_responses(self, response_data: Any) -> Any:
        if not isinstance(response_data, dict) or response_data.get("object") != "chat.completion":
            return response_data

        choice = (response_data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        output_text = self._extract_chat_message_text(message)
        usage = response_data.get("usage") or {}

        return {
            "id": response_data.get("id", f"resp_{int(time.time() * 1000)}"),
            "object": "response",
            "created_at": response_data.get("created", int(time.time())),
            "status": "completed",
            "model": response_data.get("model"),
            "output": self._build_response_output_items(message, "completed", output_text=output_text),
            "output_text": output_text,
            "usage": {
                "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
                "total_tokens": usage.get("total_tokens", 0),
            },
        }

    def _build_sse_event(self, event_name: str, data: dict) -> bytes:
        payload = json.dumps(data, ensure_ascii=False)
        return f"event: {event_name}\ndata: {payload}\n\n".encode("utf-8")

    def _with_event_id(self, event_type: str, data: dict) -> dict:
        return {
            "event_id": f"evt_{int(time.time() * 1000)}",
            "type": event_type,
            **data,
        }

    def _build_response_object(
        self,
        response_id: str,
        created_at: int,
        model: Optional[str],
        status: str,
        item_id: str,
        output_text: str,
        tool_calls: Optional[list[dict]] = None,
    ) -> dict:
        message = {
            "role": "assistant",
            "content": output_text,
            "tool_calls": tool_calls or [],
        }
        return {
            "id": response_id,
            "object": "response",
            "created_at": created_at,
            "model": model,
            "status": status,
            "output": self._build_response_output_items(message, status, item_id=item_id, output_text=output_text),
            "output_text": output_text,
        }

    async def adapt_chat_stream_to_responses(
        self,
        stream_response: AsyncGenerator[bytes, None],
        model: Optional[str],
    ) -> AsyncGenerator[bytes, None]:
        response_id = f"resp_{int(time.time() * 1000)}"
        item_id = f"msg_{int(time.time() * 1000)}"
        created_at = int(time.time())
        output_text = ""
        created_sent = False
        completed_sent = False
        saw_payload = False
        buffer = ""
        tool_calls_state: dict[int, dict] = {}

        def current_tool_calls() -> list[dict]:
            ordered_indexes = sorted(tool_calls_state.keys())
            return [tool_calls_state[index] for index in ordered_indexes]

        def ensure_tool_call(index: int) -> dict:
            tool_call = tool_calls_state.get(index)
            if tool_call is None:
                tool_call = {
                    "id": f"call_{response_id}_{index}",
                    "type": "function",
                    "function": {
                        "name": "",
                        "arguments": "",
                    },
                }
                tool_calls_state[index] = tool_call
            return tool_call

        async def emit_created() -> AsyncGenerator[bytes, None]:
            nonlocal created_sent
            if created_sent:
                return
            created_sent = True
            response = self._build_response_object(
                response_id,
                created_at,
                model,
                "in_progress",
                item_id,
                output_text,
                tool_calls=current_tool_calls(),
            )
            yield self._build_sse_event(
                "response.created",
                self._with_event_id(
                    "response.created",
                    {
                        "response": response,
                    },
                ),
            )
            if response["output"]:
                yield self._build_sse_event(
                    "response.output_item.added",
                    self._with_event_id(
                        "response.output_item.added",
                        {
                            "response_id": response_id,
                            "output_index": 0,
                            "item": response["output"][0],
                        },
                    ),
                )
                yield self._build_sse_event(
                    "response.content_part.added",
                    self._with_event_id(
                        "response.content_part.added",
                        {
                            "response_id": response_id,
                            "item_id": item_id,
                            "output_index": 0,
                            "content_index": 0,
                            "part": {
                                "type": "output_text",
                                "text": "",
                            },
                        },
                    ),
                )

        async def emit_tool_call_added(index: int, tool_call: dict) -> AsyncGenerator[bytes, None]:
            yield self._build_sse_event(
                "response.output_item.added",
                self._with_event_id(
                    "response.output_item.added",
                    {
                        "response_id": response_id,
                        "output_index": index + 1,
                        "item": self._build_response_function_call_item(tool_call, "in_progress"),
                    },
                ),
            )

        async def emit_tool_call_done(index: int, tool_call: dict) -> AsyncGenerator[bytes, None]:
            yield self._build_sse_event(
                "response.output_item.done",
                self._with_event_id(
                    "response.output_item.done",
                    {
                        "response_id": response_id,
                        "output_index": index + 1,
                        "item": self._build_response_function_call_item(tool_call, "completed"),
                    },
                ),
            )

        async def emit_completed() -> AsyncGenerator[bytes, None]:
            nonlocal completed_sent
            if completed_sent:
                return
            completed_sent = True
            response = self._build_response_object(
                response_id,
                created_at,
                model,
                "completed",
                item_id,
                output_text,
                tool_calls=current_tool_calls(),
            )
            yield self._build_sse_event(
                "response.output_text.done",
                self._with_event_id(
                    "response.output_text.done",
                    {
                        "response_id": response_id,
                        "item_id": item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "text": output_text,
                    },
                ),
            )
            yield self._build_sse_event(
                "response.content_part.done",
                self._with_event_id(
                    "response.content_part.done",
                    {
                        "response_id": response_id,
                        "item_id": item_id,
                        "output_index": 0,
                        "content_index": 0,
                        "part": {
                            "type": "output_text",
                            "text": output_text,
                        },
                    },
                ),
            )
            if response["output"]:
                yield self._build_sse_event(
                    "response.output_item.done",
                    self._with_event_id(
                        "response.output_item.done",
                        {
                            "response_id": response_id,
                            "output_index": 0,
                            "item": response["output"][0],
                        },
                    ),
                )
                for index, tool_call in enumerate(current_tool_calls()):
                    async for event in emit_tool_call_done(index, tool_call):
                        yield event
            yield self._build_sse_event(
                "response.completed",
                self._with_event_id(
                    "response.completed",
                    {
                        "response": response,
                    },
                ),
            )

        try:
            async for chunk in stream_response:
                buffer += chunk.decode("utf-8")
                while "\n\n" in buffer:
                    event_block, buffer = buffer.split("\n\n", 1)
                    if not event_block:
                        continue

                    data_lines = []
                    for line in event_block.splitlines():
                        if line.startswith("data:"):
                            data_lines.append(line[5:].strip())

                    if not data_lines:
                        continue

                    data_text = "\n".join(data_lines)
                    if data_text == "[DONE]":
                        async for event in emit_created():
                            yield event
                        async for event in emit_completed():
                            yield event
                        continue

                    try:
                        payload = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue

                    saw_payload = True
                    async for event in emit_created():
                        yield event

                    choices = payload.get("choices") or []
                    if not choices:
                        continue

                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    delta_text = delta.get("content")
                    if isinstance(delta_text, list):
                        delta_text = "".join(self._extract_text_segments(delta_text))
                    if delta_text:
                        output_text += delta_text
                        yield self._build_sse_event(
                            "response.output_text.delta",
                            self._with_event_id(
                                "response.output_text.delta",
                                {
                                    "response_id": response_id,
                                    "item_id": item_id,
                                    "output_index": 0,
                                    "content_index": 0,
                                    "delta": delta_text,
                                },
                            ),
                        )

                    for tool_call_delta in delta.get("tool_calls") or []:
                        if not isinstance(tool_call_delta, dict):
                            continue
                        tool_index = tool_call_delta.get("index", 0)
                        tool_call = ensure_tool_call(tool_index)
                        is_new_tool_call = tool_call.get("function", {}).get("name", "") == "" and tool_call.get("function", {}).get("arguments", "") == ""

                        if tool_call_delta.get("id"):
                            tool_call["id"] = tool_call_delta["id"]
                        if tool_call_delta.get("type"):
                            tool_call["type"] = tool_call_delta["type"]

                        function_delta = tool_call_delta.get("function") or {}
                        if function_delta.get("name"):
                            tool_call["function"]["name"] += function_delta["name"]
                        if function_delta.get("arguments"):
                            arguments_delta = function_delta["arguments"]
                            if not isinstance(arguments_delta, str):
                                arguments_delta = json.dumps(arguments_delta, ensure_ascii=False)
                            tool_call["function"]["arguments"] += arguments_delta

                        if is_new_tool_call:
                            async for event in emit_tool_call_added(tool_index, tool_call):
                                yield event

                        yield self._build_sse_event(
                            "response.function_call_arguments.delta",
                            self._with_event_id(
                                "response.function_call_arguments.delta",
                                {
                                    "response_id": response_id,
                                    "item_id": tool_call["id"],
                                    "output_index": tool_index + 1,
                                    "delta": function_delta.get("arguments") or "",
                                },
                            ),
                        )

                    if choice.get("finish_reason"):
                        async for event in emit_completed():
                            yield event

            if not completed_sent:
                if saw_payload or output_text or tool_calls_state:
                    async for event in emit_created():
                        yield event
                    async for event in emit_completed():
                        yield event
                else:
                    yield self._build_sse_event(
                        "response.failed",
                        self._with_event_id(
                            "response.failed",
                            {
                                "response": self._build_response_object(response_id, created_at, model, "failed", item_id, output_text),
                                "error": {
                                    "message": "stream ended before completion",
                                    "type": "stream_error",
                                },
                            },
                        ),
                    )
        except Exception as e:
            if not completed_sent:
                yield self._build_sse_event(
                    "response.failed",
                    self._with_event_id(
                        "response.failed",
                        {
                            "response": self._build_response_object(
                                response_id,
                                created_at,
                                model,
                                "failed",
                                item_id,
                                output_text,
                                tool_calls=current_tool_calls(),
                            ),
                            "error": {
                                "message": self._safe_error_message("", e),
                                "type": "stream_error",
                            },
                        },
                    ),
                )

    async def forward_request(
        self,
        db: AsyncSession,
        api_key: Any,
        method: str,
        path: str,
        headers: dict,
        body: Optional[dict] = None,
        user_id: Optional[int] = None,
        original_model: Optional[str] = None,
    ) -> tuple[int, dict, Any]:
        """
        转发请求到目标 API

        Args:
            db: 数据库会话
            api_key: API Key 对象
            method: HTTP 方法
            path: 请求路径
            headers: 原始请求头
            body: 请求体

        Returns:
            (状态码, 响应头, 响应体)
        """
        from .usage_tracker import usage_tracker

        url = self._build_url(api_key, path)
        forward_headers = self._build_headers(api_key, headers)

        total_start = time.perf_counter()
        upstream_wait_seconds = 0.0
        status = "success"
        error_message = None
        response_data = None
        status_code = 500

        upstream_wait_start = None
        try:
            async with httpx.AsyncClient(**self._build_client_kwargs(api_key, self.timeout)) as client:
                upstream_wait_start = time.perf_counter()
                response = await client.request(
                    method=method,
                    url=url,
                    headers=forward_headers,
                    json=body if body else None,
                )
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                upstream_wait_start = None

                status_code = response.status_code
                response_data = self._parse_response_body(response)

                if status_code >= 400:
                    status = "error"
                    error_message = str(response_data)

        except httpx.TimeoutException as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status = "error"
            error_message = self._safe_error_message("请求超时: ", e)
            response_data = {"error": {"message": error_message}}
        except httpx.RemoteProtocolError as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status = "error"
            error_text = str(e).lower()
            if "server disconnected" in error_text:
                error_message = self._safe_error_message("上游服务断开连接: ", e)
            else:
                error_message = self._safe_error_message("上游协议错误: ", e)
            response_data = {"error": {"message": error_message}}
        except httpx.RequestError as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status = "error"
            error_message = self._safe_error_message("请求错误: ", e)
            response_data = {"error": {"message": error_message}}
        except Exception as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status = "error"
            error_message = self._safe_error_message("未知错误: ", e)
            response_data = {"error": {"message": error_message}}

        # 计算耗时
        latency_ms = int((time.perf_counter() - total_start) * 1000)
        upstream_latency_ms = int(upstream_wait_seconds * 1000)
        cpa_overhead_ms = max(latency_ms - upstream_latency_ms, 0)

        # 提取 Token 用量
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cache_tokens = 0
        model = body.get("model") if body else None
        # actual_model 是实际转发的模型（body 里的），original_model 是用户请求的原始模型
        actual_model_value = model
        # display_model 用基础名（去掉 {provider} 前缀和 [...] 后缀），用于用量统计
        from routers.proxy import _strip_model_suffix as _strip_sfx
        _om_base, _ = _strip_sfx(original_model or model or "")
        _am_base, _ = _strip_sfx(actual_model_value or "")
        display_model = _om_base or model

        if response_data and status == "success":
            prompt_tokens, completion_tokens, total_tokens, cache_tokens = self._extract_usage_tokens(response_data)

        # 记录用量：model=原始请求模型基础名，actual_model=实际转发模型基础名
        await usage_tracker.record(
            db=db,
            api_key_id=api_key.id,
            model=display_model,
            actual_model=_am_base or actual_model_value,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cache_tokens=cache_tokens,
            latency_ms=latency_ms,
            upstream_latency_ms=upstream_latency_ms,
            cpa_overhead_ms=cpa_overhead_ms,
            status=status,
            error_message=error_message,
            user_id=user_id,
        )

        return status_code, {}, response_data

    async def forward_image_request(
        self,
        db: AsyncSession,
        api_key: Any,
        method: str,
        path: str,
        headers: dict,
        body: Optional[dict] = None,
        data: Optional[dict] = None,
        files: Optional[list[tuple[str, tuple[str, bytes, str]]]] = None,
        user_id: Optional[int] = None,
    ) -> tuple[int, dict, Any]:
        """转发公开图片请求，支持 JSON 文生图和 multipart 图生图"""
        from .usage_tracker import usage_tracker

        url = self._build_url(api_key, path)
        forward_headers = self._build_headers(api_key, headers)
        if files:
            forward_headers.pop("content-type", None)

        total_start = time.perf_counter()
        upstream_wait_seconds = 0.0
        status = "success"
        error_message = None
        response_data = None
        status_code = 500
        model = body.get("model") if body else None
        if model is None and data:
            model_value = data.get("model")
            if isinstance(model_value, list):
                model = model_value[0] if model_value else None
            else:
                model = model_value

        upstream_wait_start = None
        try:
            async with httpx.AsyncClient(**self._build_client_kwargs(api_key, self._build_image_generation_timeout())) as client:
                upstream_wait_start = time.perf_counter()
                if files:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=forward_headers,
                        data=data,
                        files=files,
                    )
                else:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=forward_headers,
                        json=body if body else None,
                    )
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                upstream_wait_start = None

                status_code = response.status_code
                response_data = self._parse_response_body(response)

                if status_code >= 400:
                    status = "error"
                    error_message = self._extract_error_message(response_data, str(response_data))

        except httpx.TimeoutException as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status_code = 504
            status = "error"
            error_message = self._safe_error_message("请求超时: ", e)
            response_data = {"error": {"message": error_message}}
        except httpx.RemoteProtocolError as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status_code = 502
            status = "error"
            error_text = str(e).lower()
            if "server disconnected" in error_text:
                error_message = self._safe_error_message("上游服务断开连接: ", e)
            else:
                error_message = self._safe_error_message("上游协议错误: ", e)
            response_data = {"error": {"message": error_message}}
        except httpx.RequestError as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status_code = 502
            status = "error"
            error_message = self._safe_error_message("请求错误: ", e)
            response_data = {"error": {"message": error_message}}
        except Exception as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            status_code = 500
            status = "error"
            error_message = self._safe_error_message("未知错误: ", e)
            response_data = {"error": {"message": error_message}}

        latency_ms = int((time.perf_counter() - total_start) * 1000)
        upstream_latency_ms = int(upstream_wait_seconds * 1000)
        cpa_overhead_ms = max(latency_ms - upstream_latency_ms, 0)

        await usage_tracker.record(
            db=db,
            api_key_id=api_key.id,
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=latency_ms,
            upstream_latency_ms=upstream_latency_ms,
            cpa_overhead_ms=cpa_overhead_ms,
            status=status,
            error_message=error_message,
            user_id=user_id,
        )

        return status_code, {}, response_data

    # ── 流式缓冲规则匹配 ──────────────────────────────────────────────────────

    @staticmethod
    def _match_stream_buffer_rule(api_key: Any, model: Optional[str]) -> bool:
        """
        判断当前请求是否命中流式缓冲规则。
        规则来自 export_config.stream_buffer_rules，支持 provider / model 通配（* 匹配任意）。
        只要命中任意一条规则就返回 True，不影响未命中的请求。
        """
        import fnmatch
        from config import export_config as _ec
        rules = _ec.get("stream_buffer_rules") or []
        if not rules:
            return False

        provider = (getattr(api_key, "provider", "") or "").strip().lower()
        model_str = (model or "").strip().lower()

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_provider = (rule.get("provider") or "").strip().lower()
            rule_model = (rule.get("model") or "").strip().lower()

            # provider 匹配：空或 * 表示匹配所有
            if rule_provider and rule_provider != "*":
                if not fnmatch.fnmatch(provider, rule_provider):
                    continue

            # model 匹配：空或 * 表示匹配所有
            if rule_model and rule_model != "*":
                if not fnmatch.fnmatch(model_str, rule_model):
                    continue

            return True

        return False

    async def forward_stream_buffered(
        self,
        db: AsyncSession,
        api_key: Any,
        method: str,
        path: str,
        headers: dict,
        body: Optional[dict] = None,
        client_request: Optional[Request] = None,
        user_id: Optional[int] = None,
        original_model: Optional[str] = None,
    ) -> tuple[int, dict, Any, bool]:
        """
        完整缓冲模式的流式转发：先把上游 SSE 流完整收到内存，
        确认收到终止事件（[DONE] / finish_reason）后再以生成器形式输出给客户端。
        中途断流（未收到终止事件）返回 retryable=True，由调用方换 Key 重试。
        命中规则时替代 forward_stream 使用，不影响其他请求。
        """
        from .usage_tracker import usage_tracker

        url = self._build_url(api_key, path)
        forward_headers = self._build_headers(api_key, headers)
        model = body.get("model") if body else None

        request_meta = {
            "api_key_id": getattr(api_key, "id", None),
            "provider": getattr(api_key, "provider", None),
            "base_url": getattr(api_key, "base_url", None),
            "path": path,
            "model": model,
        }
        self._log_stream_event("buffered_start", **request_meta)

        total_start = time.perf_counter()
        upstream_wait_seconds = 0.0

        # 缓冲模式用更长的 read timeout，避免大请求在稳定窗口期内超时
        buffered_timeout = httpx.Timeout(
            connect=settings.proxy_stream_connect_timeout_seconds,
            read=max(int(settings.proxy_timeout or 300), 300),
            write=settings.proxy_stream_connect_timeout_seconds,
            pool=settings.proxy_stream_connect_timeout_seconds,
        )
        client = httpx.AsyncClient(**self._build_client_kwargs(api_key, buffered_timeout))
        request_obj = client.build_request(
            method=method,
            url=url,
            headers=forward_headers,
            json=body if body else None,
        )

        upstream_wait_start = None
        try:
            upstream_wait_start = time.perf_counter()
            response = await client.send(request_obj, stream=True)
            upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            upstream_wait_start = None
        except httpx.TimeoutException as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            await client.aclose()
            error_message = self._safe_error_message("请求超时: ", e)
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db, api_key_id=api_key.id, model=original_model or model,
                latency_ms=latency_ms, upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error", error_message=error_message, user_id=user_id,
            )
            return 504, {}, {"error": {"message": error_message}}, True
        except (httpx.RemoteProtocolError, httpx.RequestError) as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            await client.aclose()
            error_message = self._safe_error_message("连接失败: ", e)
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db, api_key_id=api_key.id, model=original_model or model,
                latency_ms=latency_ms, upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error", error_message=error_message, user_id=user_id,
            )
            return 502, {}, {"error": {"message": error_message}}, True
        except Exception as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            await client.aclose()
            error_message = self._safe_error_message("未知错误: ", e)
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db, api_key_id=api_key.id, model=original_model or model,
                latency_ms=latency_ms, upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error", error_message=error_message, user_id=user_id,
            )
            return 500, {}, {"error": {"message": error_message}}, True

        content_type = response.headers.get("content-type", "")

        # 非流式响应或错误响应，直接走原有逻辑
        if response.status_code >= 400 or "text/event-stream" not in content_type.lower():
            try:
                upstream_wait_start = time.perf_counter()
                raw_body = await response.aread()
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                body_text = raw_body.decode("utf-8", "ignore")
                try:
                    error_body = json.loads(body_text)
                except json.JSONDecodeError:
                    error_body = {"error": {"message": body_text or response.reason_phrase}}
            finally:
                await response.aclose()
                await client.aclose()
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db, api_key_id=api_key.id, model=original_model or model,
                latency_ms=latency_ms, upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error", error_message=str(error_body), user_id=user_id,
            )
            status_code = response.status_code if response.status_code >= 400 else 502
            retryable = self._is_retryable_stream_failure(status_code, error_body)
            return status_code, self._filter_stream_response_headers(response.headers), error_body, retryable

        # ── 稳定窗口缓冲 + 透传 ──────────────────────────────────────────────
        # 前 STABLE_WINDOW_SECONDS 秒内完整缓冲，期间断流视为截流可重试换 Key。
        # 窗口结束后确认上游稳定，切换为直接透传（行为与普通 forward_stream 一致）。
        STABLE_WINDOW_SECONDS = 10.0

        response_headers = self._filter_stream_response_headers(response.headers)
        from routers.proxy import _strip_model_suffix as _strip_sfx_buf
        _om_base_buf, _ = _strip_sfx_buf(original_model or model or "")
        _am_base_buf, _ = _strip_sfx_buf(model or "")
        pending_log = await usage_tracker.create_pending_record(
            db=db,
            api_key_id=api_key.id,
            model=_om_base_buf or model,
            actual_model=_am_base_buf or model,
            user_id=user_id,
        )

        # 阶段一：缓冲窗口内收集事件，同时检测截流
        window_events: list[bytes] = []
        window_done = False        # 窗口内已收到终止事件（短响应直接结束）
        window_cut = False         # 窗口内发生截流
        window_error: Optional[str] = None
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cache_tokens = 0
        buffer = ""
        window_start = time.perf_counter()

        def _update_tokens_from_event(ep, ec, et, eca):
            nonlocal prompt_tokens, completion_tokens, total_tokens, cache_tokens
            if ep: prompt_tokens = ep
            if ec: completion_tokens = ec
            if et: total_tokens = et
            if eca: cache_tokens = eca
            if not total_tokens and (prompt_tokens or completion_tokens):
                total_tokens = prompt_tokens + completion_tokens

        stream_iter = response.aiter_text()
        window_exited = False

        try:
            upstream_wait_start = time.perf_counter()
            async for chunk in stream_iter:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                upstream_wait_start = time.perf_counter()
                buffer += chunk
                while "\n\n" in buffer:
                    event_block, buffer = buffer.split("\n\n", 1)
                    if not event_block:
                        continue
                    event_text = f"{event_block}\n\n"
                    ep, ec, et, eca = self._extract_stream_usage_from_sse(event_text)
                    if ep or ec or et or eca:
                        _update_tokens_from_event(ep, ec, et, eca)
                    if self._has_terminal_event(event_text):
                        window_done = True
                    window_events.append(event_text.encode("utf-8"))

                # 窗口时间到，切换为透传阶段
                if not window_done and time.perf_counter() - window_start >= STABLE_WINDOW_SECONDS:
                    window_exited = True
                    break

                if window_done:
                    break

            upstream_wait_seconds += time.perf_counter() - upstream_wait_start

            # 处理窗口内残留 buffer
            if buffer and not window_exited:
                ep, ec, et, eca = self._extract_stream_usage_from_sse(buffer)
                if ep or ec or et or eca:
                    _update_tokens_from_event(ep, ec, et, eca)
                if self._has_terminal_event(buffer):
                    window_done = True
                window_events.append(buffer.encode("utf-8"))
                buffer = ""

        except Exception as e:
            window_error = self._safe_error_message("缓冲窗口读取失败: ", e)
            window_cut = True

        # 窗口内断流（未到时间就结束且没有终止事件）
        if not window_exited and not window_done and not window_error:
            window_cut = True
            window_error = "stream closed in stability window (buffered mode)"

        if window_cut:
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            self._log_stream_event("buffered_window_cut", **request_meta, error=window_error)
            await response.aclose()
            await client.aclose()
            await usage_tracker.record(
                db=db, api_key_id=api_key.id, model=original_model or model,
                latency_ms=latency_ms, upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error", error_message=window_error, user_id=user_id,
            )
            return 502, {}, {"error": {"message": window_error}}, True

        # 窗口内已完成（短响应）→ 直接重放，不需要透传
        if window_done:
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            upstream_latency_ms = int(upstream_wait_seconds * 1000)
            self._log_stream_event("buffered_window_complete", **request_meta,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                total_tokens=total_tokens, latency_ms=latency_ms)
            await response.aclose()
            await client.aclose()
            await usage_tracker.update_record(
                db=db, log=pending_log,
                prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                total_tokens=total_tokens, cache_tokens=cache_tokens,
                latency_ms=latency_ms, upstream_latency_ms=upstream_latency_ms,
                cpa_overhead_ms=max(latency_ms - upstream_latency_ms, 0),
                status="success",
            )

            async def replay_short() -> AsyncGenerator[bytes, None]:
                for ev in window_events:
                    yield ev

            return 200, response_headers, replay_short(), False

        # 窗口结束，上游稳定 → 先重放窗口内容，再透传剩余流
        self._log_stream_event("buffered_window_passed", **request_meta)

        async def passthrough_generator() -> AsyncGenerator[bytes, None]:
            nonlocal upstream_wait_seconds, prompt_tokens, completion_tokens, total_tokens, cache_tokens, buffer

            # 先输出窗口内已缓冲的事件
            for ev in window_events:
                yield ev

            # 继续透传剩余流
            terminal_seen = window_done
            client_disconnected = False
            error_message_pt: Optional[str] = None
            last_synced_tokens = (prompt_tokens, completion_tokens, total_tokens, cache_tokens)

            try:
                upstream_wait_start_pt = time.perf_counter()
                async for chunk in stream_iter:
                    upstream_wait_seconds += time.perf_counter() - upstream_wait_start_pt
                    upstream_wait_start_pt = time.perf_counter()

                    if client_request and await client_request.is_disconnected():
                        client_disconnected = True
                        break

                    buffer += chunk
                    while "\n\n" in buffer:
                        event_block, buffer = buffer.split("\n\n", 1)
                        if not event_block:
                            continue
                        event_text = f"{event_block}\n\n"
                        ep, ec, et, eca = self._extract_stream_usage_from_sse(event_text)
                        if ep or ec or et or eca:
                            _update_tokens_from_event(ep, ec, et, eca)
                            current_tokens = (prompt_tokens, completion_tokens, total_tokens, cache_tokens)
                            if current_tokens != last_synced_tokens:
                                cur_lat = int((time.perf_counter() - total_start) * 1000)
                                cur_up = int(upstream_wait_seconds * 1000)
                                await usage_tracker.update_tokens(
                                    db=db, log=pending_log,
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens,
                                    total_tokens=total_tokens,
                                    latency_ms=cur_lat,
                                    upstream_latency_ms=cur_up,
                                    cpa_overhead_ms=max(cur_lat - cur_up, 0),
                                )
                                last_synced_tokens = current_tokens
                        if self._has_terminal_event(event_text):
                            terminal_seen = True
                        yield event_text.encode("utf-8")

                upstream_wait_seconds += time.perf_counter() - upstream_wait_start_pt

                if buffer and not client_disconnected:
                    ep, ec, et, eca = self._extract_stream_usage_from_sse(buffer)
                    if ep or ec or et or eca:
                        _update_tokens_from_event(ep, ec, et, eca)
                    if self._has_terminal_event(buffer):
                        terminal_seen = True
                    yield buffer.encode("utf-8")

            except Exception as e:
                error_message_pt = self._safe_error_message("透传阶段异常: ", e)
                if not terminal_seen and not client_disconnected:
                    yield self._build_stream_error_event(error_message_pt)
            finally:
                latency_ms_f = int((time.perf_counter() - total_start) * 1000)
                upstream_latency_ms_f = int(upstream_wait_seconds * 1000)
                final_status = "success" if terminal_seen or (prompt_tokens or completion_tokens) else "error"
                if client_disconnected and not terminal_seen:
                    final_status = "error"
                    error_message_pt = error_message_pt or "client disconnected"
                await usage_tracker.update_record(
                    db=db, log=pending_log,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    total_tokens=total_tokens, cache_tokens=cache_tokens,
                    latency_ms=latency_ms_f, upstream_latency_ms=upstream_latency_ms_f,
                    cpa_overhead_ms=max(latency_ms_f - upstream_latency_ms_f, 0),
                    status=final_status, error_message=error_message_pt,
                )
                await response.aclose()
                await client.aclose()

        return 200, response_headers, passthrough_generator(), False

    # ── 原始流式转发 ──────────────────────────────────────────────────────────

    async def forward_stream(
        self,
        db: AsyncSession,
        api_key: Any,
        method: str,
        path: str,
        headers: dict,
        body: Optional[dict] = None,
        client_request: Optional[Request] = None,
        user_id: Optional[int] = None,
        original_model: Optional[str] = None,
    ) -> tuple[int, dict, Any, bool]:
        """
        流式转发请求

        Args:
            db: 数据库会话
            api_key: API Key 对象
            method: HTTP 方法
            path: 请求路径
            headers: 原始请求头
            body: 请求体

        Returns:
            (状态码, 响应头, 流生成器或错误体, 是否可重试)
        """
        from .usage_tracker import usage_tracker

        url = self._build_url(api_key, path)
        forward_headers = self._build_headers(api_key, headers)

        total_start = time.perf_counter()
        upstream_wait_seconds = 0.0
        model = body.get("model") if body else None
        request_meta = {
            "api_key_id": getattr(api_key, "id", None),
            "provider": getattr(api_key, "provider", None),
            "base_url": getattr(api_key, "base_url", None),
            "path": path,
            "model": model,
        }

        self._log_stream_event("start", **request_meta)

        client = httpx.AsyncClient(**self._build_client_kwargs(api_key, self.stream_timeout))
        request = client.build_request(
            method=method,
            url=url,
            headers=forward_headers,
            json=body if body else None,
        )

        upstream_wait_start = None
        try:
            upstream_wait_start = time.perf_counter()
            response = await client.send(request, stream=True)
            upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            upstream_wait_start = None
            self._log_stream_event(
                "upstream_connected",
                **request_meta,
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
                request_id=response.headers.get("request-id") or response.headers.get("x-request-id") or response.headers.get("anthropic-request-id") or response.headers.get("x-oneapi-request-id"),
            )
        except httpx.TimeoutException as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            await client.aclose()
            error_message = self._safe_error_message("请求超时: ", e)
            self._log_stream_event("connect_timeout", **request_meta, error=error_message)
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db,
                api_key_id=api_key.id,
                model=original_model or model,
                latency_ms=latency_ms,
                upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error",
                error_message=error_message,
                user_id=user_id,
            )
            return 504, {}, {"error": {"message": error_message}}, True
        except httpx.RemoteProtocolError as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            await client.aclose()
            error_text = str(e).lower()
            if "server disconnected" in error_text:
                error_message = self._safe_error_message("上游服务断开连接: ", e)
            else:
                error_message = self._safe_error_message("上游协议错误: ", e)
            self._log_stream_event("connect_error", **request_meta, error=error_message)
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db,
                api_key_id=api_key.id,
                model=original_model or model,
                latency_ms=latency_ms,
                upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error",
                error_message=error_message,
                user_id=user_id,
            )
            return 502, {}, {"error": {"message": error_message}}, True
        except httpx.RequestError as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            await client.aclose()
            error_message = self._safe_error_message("请求错误: ", e)
            self._log_stream_event("connect_error", **request_meta, error=error_message)
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db,
                api_key_id=api_key.id,
                model=original_model or model,
                latency_ms=latency_ms,
                upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error",
                error_message=error_message,
                user_id=user_id,
            )
            return 502, {}, {"error": {"message": error_message}}, True
        except Exception as e:
            if upstream_wait_start is not None:
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
            await client.aclose()
            error_message = self._safe_error_message("未知错误: ", e)
            self._log_stream_event("connect_exception", **request_meta, error=error_message)
            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db,
                api_key_id=api_key.id,
                model=original_model or model,
                latency_ms=latency_ms,
                upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error",
                error_message=error_message,
                user_id=user_id,
            )
            return 500, {}, {"error": {"message": error_message}}, True

        content_type = response.headers.get("content-type", "")

        if response.status_code >= 400 or "text/event-stream" not in content_type.lower():
            try:
                upstream_wait_start = time.perf_counter()
                raw_body = await response.aread()
                upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                body_text = raw_body.decode("utf-8", "ignore")
                if "application/json" in content_type.lower():
                    try:
                        error_body = json.loads(body_text)
                    except json.JSONDecodeError:
                        error_body = {"error": {"message": body_text or response.reason_phrase}}
                else:
                    error_body = {"error": {"message": body_text or response.reason_phrase}}
            finally:
                await response.aclose()
                await client.aclose()

            if response.status_code < 400 and "text/event-stream" not in content_type.lower():
                error_body = {
                    "error": {
                        "message": f"上游流式响应不是 text/event-stream，而是 {content_type or 'unknown'}",
                        "upstream_response": error_body,
                    }
                }

            self._log_stream_event(
                "upstream_rejected",
                **request_meta,
                status_code=response.status_code,
                content_type=content_type,
                error=error_body,
            )

            latency_ms = int((time.perf_counter() - total_start) * 1000)
            await usage_tracker.record(
                db=db,
                api_key_id=api_key.id,
                model=original_model or model,
                latency_ms=latency_ms,
                upstream_latency_ms=int(upstream_wait_seconds * 1000),
                status="error",
                error_message=str(error_body),
                user_id=user_id,
            )
            status_code = response.status_code if response.status_code >= 400 else 502
            retryable = self._is_retryable_stream_failure(status_code, error_body)
            return status_code, self._filter_stream_response_headers(response.headers), error_body, retryable

        response_headers = self._filter_stream_response_headers(response.headers)
        from routers.proxy import _strip_model_suffix as _strip_sfx2
        _om_base2, _ = _strip_sfx2(original_model or model or "")
        _am_base2, _ = _strip_sfx2(model or "")
        pending_log = await usage_tracker.create_pending_record(
            db=db,
            api_key_id=api_key.id,
            model=_om_base2 or model,
            actual_model=_am_base2 or model,
            user_id=user_id,
        )

        async def stream_generator() -> AsyncGenerator[bytes, None]:
            nonlocal upstream_wait_seconds
            terminal_seen = False
            client_disconnected = False
            first_chunk_received = False
            saw_stream_payload = False
            buffer = ""
            error_message = None
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0
            cache_tokens = 0
            last_synced_tokens = (0, 0, 0, 0)

            try:
                stream_iterator = response.aiter_text()
                while True:
                    if client_request and await client_request.is_disconnected():
                        client_disconnected = True
                        error_message = "client disconnected"
                        self._log_stream_event("client_disconnected", **request_meta)
                        break

                    upstream_wait_start = time.perf_counter()
                    try:
                        next_chunk = stream_iterator.__anext__()
                        if not first_chunk_received:
                            chunk = await asyncio.wait_for(next_chunk, timeout=self.stream_first_byte_timeout_seconds)
                        else:
                            chunk = await next_chunk
                    except StopAsyncIteration:
                        upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                        if not first_chunk_received:
                            self._log_stream_event("upstream_closed_before_first_chunk", **request_meta)
                        break
                    except asyncio.TimeoutError:
                        upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                        if not first_chunk_received:
                            error_message = f"首包超时: {self.stream_first_byte_timeout_seconds}s 内未收到上游数据"
                            self._log_stream_event("first_chunk_timeout", **request_meta, error=error_message)
                        else:
                            error_message = "流式读取超时"
                            self._log_stream_event("stream_read_timeout", **request_meta, error=error_message)
                        break
                    except httpx.TimeoutException as e:
                        upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                        error_message = self._safe_error_message("请求超时: ", e)
                        self._log_stream_event("stream_timeout", **request_meta, error=error_message)
                        break
                    upstream_wait_seconds += time.perf_counter() - upstream_wait_start
                    first_chunk_received = True
                    buffer += chunk
                    while "\n\n" in buffer:
                        event_block, buffer = buffer.split("\n\n", 1)
                        if not event_block:
                            continue
                        event_text = f"{event_block}\n\n"
                        saw_stream_payload = True
                        event_prompt_tokens, event_completion_tokens, event_total_tokens, event_cache_tokens = self._extract_stream_usage_from_sse(event_text)
                        if event_prompt_tokens or event_completion_tokens or event_total_tokens or event_cache_tokens:
                            # 按字段覆盖：避免 Claude 原生格式 message_start/message_delta 分散导致互相清零
                            if event_prompt_tokens:
                                prompt_tokens = event_prompt_tokens
                            if event_completion_tokens:
                                completion_tokens = event_completion_tokens
                            if event_total_tokens:
                                total_tokens = event_total_tokens
                            if event_cache_tokens:
                                cache_tokens = event_cache_tokens
                            if not total_tokens and (prompt_tokens or completion_tokens):
                                total_tokens = prompt_tokens + completion_tokens
                            current_tokens = (prompt_tokens, completion_tokens, total_tokens, cache_tokens)
                            if current_tokens != last_synced_tokens:
                                current_latency_ms = int((time.perf_counter() - total_start) * 1000)
                                current_upstream_latency_ms = int(upstream_wait_seconds * 1000)
                                await usage_tracker.update_tokens(
                                    db=db,
                                    log=pending_log,
                                    prompt_tokens=prompt_tokens,
                                    completion_tokens=completion_tokens,
                                    total_tokens=total_tokens,
                                    latency_ms=current_latency_ms,
                                    upstream_latency_ms=current_upstream_latency_ms,
                                    cpa_overhead_ms=max(current_latency_ms - current_upstream_latency_ms, 0),
                                )
                                last_synced_tokens = current_tokens
                        if self._has_terminal_event(event_text):
                            terminal_seen = True
                        yield event_text.encode("utf-8")

                if buffer and not client_disconnected:
                    saw_stream_payload = True
                    event_prompt_tokens, event_completion_tokens, event_total_tokens, event_cache_tokens = self._extract_stream_usage_from_sse(buffer)
                    if event_prompt_tokens or event_completion_tokens or event_total_tokens or event_cache_tokens:
                        if event_prompt_tokens:
                            prompt_tokens = event_prompt_tokens
                        if event_completion_tokens:
                            completion_tokens = event_completion_tokens
                        if event_total_tokens:
                            total_tokens = event_total_tokens
                        if event_cache_tokens:
                            cache_tokens = event_cache_tokens
                        if not total_tokens and (prompt_tokens or completion_tokens):
                            total_tokens = prompt_tokens + completion_tokens
                        current_tokens = (prompt_tokens, completion_tokens, total_tokens, cache_tokens)
                        if current_tokens != last_synced_tokens:
                            current_latency_ms = int((time.perf_counter() - total_start) * 1000)
                            current_upstream_latency_ms = int(upstream_wait_seconds * 1000)
                            await usage_tracker.update_tokens(
                                db=db,
                                log=pending_log,
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                total_tokens=total_tokens,
                                latency_ms=current_latency_ms,
                                upstream_latency_ms=current_upstream_latency_ms,
                                cpa_overhead_ms=max(current_latency_ms - current_upstream_latency_ms, 0),
                            )
                            last_synced_tokens = current_tokens
                    if self._has_terminal_event(buffer):
                        terminal_seen = True
                    yield buffer.encode("utf-8")

                if not terminal_seen and not error_message and first_chunk_received and saw_stream_payload:
                    terminal_seen = True
                    self._log_stream_event("stream_closed_without_terminal_event", **request_meta)
                elif not terminal_seen and not error_message:
                    error_message = "stream closed before completion event"
                    if not client_disconnected:
                        yield self._build_stream_error_event(error_message)
            except Exception as e:
                if not terminal_seen:
                    error_message = self._safe_error_message("stream interrupted: ", e)
                    self._log_stream_event("stream_exception", **request_meta, first_chunk_received=first_chunk_received, error=error_message)
                    if not client_disconnected:
                        yield self._build_stream_error_event(error_message)
            finally:
                latency_ms = int((time.perf_counter() - total_start) * 1000)
                upstream_latency_ms = int(upstream_wait_seconds * 1000)
                cpa_overhead_ms = max(latency_ms - upstream_latency_ms, 0)
                has_usage = any(value > 0 for value in [prompt_tokens, completion_tokens, total_tokens])
                if error_message and not client_disconnected:
                    final_status = "error"
                else:
                    final_status = "success" if terminal_seen or has_usage or saw_stream_payload else "error"
                final_error_message = error_message
                if client_disconnected and not terminal_seen and not has_usage:
                    final_status = "error"
                    final_error_message = "client disconnected"
                self._log_stream_event(
                    "finalize",
                    **request_meta,
                    first_chunk_received=first_chunk_received,
                    terminal_seen=terminal_seen,
                    status=final_status,
                    latency_ms=latency_ms,
                    upstream_latency_ms=upstream_latency_ms,
                    cpa_overhead_ms=cpa_overhead_ms,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    error=final_error_message,
                )
                await usage_tracker.update_record(
                    db=db,
                    log=pending_log,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    cache_tokens=cache_tokens,
                    latency_ms=latency_ms,
                    upstream_latency_ms=upstream_latency_ms,
                    cpa_overhead_ms=cpa_overhead_ms,
                    status=final_status,
                    error_message=final_error_message,
                )
                await response.aclose()
                await client.aclose()

        return response.status_code, response_headers, stream_generator(), False

    # ============ Claude Messages <-> OpenAI Chat 兼容层 ============

    def _adapt_claude_content_to_chat_content(self, content: Any) -> Any:
        """Claude content blocks → OpenAI Chat content，保留图片输入"""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return "" if content is None else str(content)

        chat_parts = []
        for item in content:
            if isinstance(item, str):
                chat_parts.append({"type": "text", "text": item})
                continue
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "text" and item.get("text"):
                chat_parts.append({"type": "text", "text": str(item["text"])})
            elif item_type == "image":
                source = item.get("source") if isinstance(item.get("source"), dict) else {}
                media_type = source.get("media_type") or "image/png"
                if source.get("type") == "base64" and source.get("data"):
                    chat_parts.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{source['data']}"}})
                elif source.get("type") == "url" and source.get("url"):
                    chat_parts.append({"type": "image_url", "image_url": {"url": source["url"]}})
            elif item_type == "image_url":
                image_url = item.get("image_url")
                if isinstance(image_url, dict) and image_url.get("url"):
                    chat_parts.append({"type": "image_url", "image_url": {"url": image_url["url"]}})
                elif isinstance(image_url, str):
                    chat_parts.append({"type": "image_url", "image_url": {"url": image_url}})
        if not chat_parts:
            return ""
        if all(part.get("type") == "text" for part in chat_parts):
            return "\n".join(str(part.get("text") or "") for part in chat_parts)
        return chat_parts

    def _adapt_claude_content_to_chat_text(self, content: Any) -> str:
        """提取 Claude content block 中的纯文本"""
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return "" if content is None else str(content)
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if item.get("type") == "text" and item.get("text"):
                    parts.append(str(item["text"]))
        return "\n".join(parts)

    def _adapt_claude_tools_for_chat(self, tools: Any) -> list[dict]:
        """Claude 工具定义 → OpenAI function tools"""
        if not isinstance(tools, list):
            return []
        adapted = []
        for tool in tools:
            if not isinstance(tool, dict):
                continue
            tool_type = tool.get("type")
            if tool_type not in (None, "custom", "tool"):
                continue
            name = tool.get("name")
            if not name:
                continue
            adapted.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.get("description") or "",
                    "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
                },
            })
        return adapted

    def _adapt_claude_tool_choice_for_chat(self, tool_choice: Any) -> Any:
        """Claude tool_choice → OpenAI tool_choice"""
        if isinstance(tool_choice, str):
            if tool_choice == "any":
                return "required"
            return tool_choice
        if not isinstance(tool_choice, dict):
            return None
        choice_type = tool_choice.get("type")
        if choice_type == "any":
            return "required"
        if choice_type in ("auto", "none", "required"):
            return choice_type
        if choice_type == "tool" and tool_choice.get("name"):
            return {"type": "function", "function": {"name": tool_choice["name"]}}
        return None

    def adapt_claude_messages_request_to_chat(self, body: dict) -> dict:
        """Claude Messages 请求 → OpenAI Chat Completions 请求"""
        chat_body: dict[str, Any] = {}

        # 通用字段
        for src, dst in [("model", "model"), ("stream", "stream"), ("temperature", "temperature"), ("top_p", "top_p")]:
            if src in body:
                chat_body[dst] = body[src]
        if "max_tokens" in body:
            chat_body["max_tokens"] = body["max_tokens"]
        if "stop_sequences" in body:
            chat_body["stop"] = body["stop_sequences"]

        # 消息转换
        messages: list[dict] = []

        # system
        system_content = body.get("system")
        if system_content:
            messages.append({"role": "system", "content": self._adapt_claude_content_to_chat_text(system_content)})

        # messages
        for msg in body.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role") or "user"
            content = msg.get("content")

            if role == "assistant":
                # assistant: text + tool_use
                text_parts: list[str] = []
                tool_calls: list[dict] = []
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type")
                        if block_type == "text" and block.get("text"):
                            text_parts.append(str(block["text"]))
                        elif block_type == "tool_use":
                            tool_calls.append({
                                "id": block.get("id") or f"call_{int(time.time() * 1000)}",
                                "type": "function",
                                "function": {
                                    "name": block.get("name") or "tool",
                                    "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                                },
                            })
                elif isinstance(content, str):
                    text_parts.append(content)

                chat_msg: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts)}
                if tool_calls:
                    chat_msg["tool_calls"] = tool_calls
                messages.append(chat_msg)

            else:
                # user: text + tool_result（拆分为独立消息）
                if isinstance(content, list):
                    text_parts_u: list[str] = []
                    image_parts_u: list[dict] = []
                    tool_results: list[dict] = []
                    for block in content:
                        if isinstance(block, str):
                            text_parts_u.append(block)
                            continue
                        if not isinstance(block, dict):
                            continue
                        block_type = block.get("type")
                        if block_type == "text" and block.get("text"):
                            text_parts_u.append(str(block["text"]))
                        elif block_type in ("image", "image_url"):
                            adapted_image = self._adapt_claude_content_to_chat_content([block])
                            if isinstance(adapted_image, list):
                                image_parts_u.extend(adapted_image)
                        elif block_type == "tool_result":
                            tool_use_id = block.get("tool_use_id") or block.get("id")
                            if tool_use_id:
                                result_text = self._adapt_claude_content_to_chat_text(block.get("content"))
                                tool_results.append({
                                    "role": "tool",
                                    "tool_call_id": str(tool_use_id),
                                    "content": result_text,
                                })
                    # tool results 必须紧跟 assistant tool_calls
                    messages.extend(tool_results)
                    user_parts = []
                    if text_parts_u:
                        user_parts.append({"type": "text", "text": "\n".join(text_parts_u)})
                    user_parts.extend(image_parts_u)
                    if user_parts:
                        if all(part.get("type") == "text" for part in user_parts):
                            messages.append({"role": "user", "content": "\n".join(str(part.get("text") or "") for part in user_parts)})
                        else:
                            messages.append({"role": "user", "content": user_parts})
                    elif not tool_results:
                        messages.append({"role": "user", "content": ""})
                else:
                    messages.append({"role": "user", "content": self._adapt_claude_content_to_chat_content(content)})

        chat_body["messages"] = messages or [{"role": "user", "content": ""}]

        # 工具
        tools = self._adapt_claude_tools_for_chat(body.get("tools"))
        if tools:
            chat_body["tools"] = tools
        tool_choice = self._adapt_claude_tool_choice_for_chat(body.get("tool_choice"))
        if tool_choice is not None:
            chat_body["tool_choice"] = tool_choice

        # 流式请求注入 stream_options 确保上游返回 usage
        if body.get("stream") is True:
            chat_body["stream_options"] = {"include_usage": True}

        return chat_body

    def _normalize_claude_usage_from_chat_usage(self, usage: Any) -> dict:
        """OpenAI usage → Claude usage 字段"""
        if not isinstance(usage, dict):
            usage = {}
        prompt_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        completion_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        cache_tokens = 0
        details = usage.get("prompt_tokens_details") or {}
        if isinstance(details, dict):
            cache_tokens = int(details.get("cached_tokens") or 0)
        if not cache_tokens:
            cache_tokens = int(usage.get("cache_read_input_tokens") or usage.get("cached_tokens") or 0)
        uncached_input_tokens = max(prompt_tokens - cache_tokens, 0) if cache_tokens else prompt_tokens
        return {
            "input_tokens": uncached_input_tokens,
            "output_tokens": completion_tokens,
            "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
            "cache_read_input_tokens": cache_tokens,
        }

    def _merge_claude_usage(self, current: dict, incoming: dict) -> dict:
        """合并 usage：正数真实值覆盖估算"""
        merged = dict(current or {})
        for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            val = incoming.get(key)
            if isinstance(val, int) and val > 0:
                merged[key] = val
            elif key not in merged:
                merged[key] = int(val or 0)
        return merged

    def _estimate_claude_compat_input_tokens(self, body: Any) -> int:
        """粗估 input token，仅用于 message_start 初始阶段"""
        if not isinstance(body, dict):
            return 0
        total = 0
        for key in ("system", "messages", "tools"):
            val = body.get(key)
            if val is None:
                continue
            try:
                text = json.dumps(val, ensure_ascii=False, sort_keys=True)
            except (TypeError, ValueError):
                text = str(val)
            total += max(len(text) // 4, 0)
        return total

    def is_claudecode_token_compat_enabled(self, provider: Optional[str]) -> bool:
        """判断 provider 是否启用 Claude Code token 兼容"""
        if not provider:
            return False
        provider_lower = str(provider).strip().lower()
        if not provider_lower:
            return False
        try:
            from config import export_config
            providers_list = export_config.get("claudecode_token_compat_providers") or []
        except Exception:
            providers_list = []
        if not isinstance(providers_list, list):
            return False
        enabled = {str(p).strip().lower() for p in providers_list if str(p or "").strip()}
        return provider_lower in enabled

    def adapt_chat_response_to_claude_message(self, response_data: Any, fallback_model: Optional[str] = None) -> Any:
        """OpenAI Chat 非流式响应 → Claude Messages 响应"""
        if not isinstance(response_data, dict):
            return response_data
        choice = (response_data.get("choices") or [{}])[0]
        message = choice.get("message") or {}

        content_blocks: list[dict] = []
        text = self._extract_chat_message_text(message)
        if text:
            content_blocks.append({"type": "text", "text": text})
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args_str = fn.get("arguments") or "{}"
            try:
                parsed_args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                parsed_args = {"raw": args_str}
            content_blocks.append({
                "type": "tool_use",
                "id": tc.get("id") or f"call_{int(time.time() * 1000)}",
                "name": fn.get("name") or "tool",
                "input": parsed_args or {},
            })

        usage = self._normalize_claude_usage_from_chat_usage(response_data.get("usage") or {})
        has_tool_use = any(b.get("type") == "tool_use" for b in content_blocks)

        return {
            "id": response_data.get("id", f"msg_{int(time.time() * 1000)}"),
            "type": "message",
            "role": "assistant",
            "model": response_data.get("model") or fallback_model,
            "content": content_blocks,
            "stop_reason": "tool_use" if has_tool_use else "end_turn",
            "stop_sequence": None,
            "usage": usage,
        }

    async def adapt_chat_stream_to_claude_messages(
        self,
        stream_response: AsyncGenerator[bytes, None],
        model: Optional[str],
        input_tokens_estimate: int = 0,
    ) -> AsyncGenerator[bytes, None]:
        """OpenAI Chat SSE 流 → Claude Messages SSE 流"""
        message_id = f"msg_{int(time.time() * 1000)}"
        index = 0
        started = False
        text_started = False
        buffer = ""
        tool_states: dict[int, dict] = {}
        finish_reason: Optional[str] = None
        message_usage = {
            "input_tokens": max(int(input_tokens_estimate or 0), 0),
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }

        def sse(name: str, data: dict) -> bytes:
            return self._build_sse_event(name, data)

        async def ensure_started():
            nonlocal started
            if not started:
                started = True
                yield sse("message_start", {
                    "type": "message_start",
                    "message": {
                        "id": message_id,
                        "type": "message",
                        "role": "assistant",
                        "model": model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": dict(message_usage),
                    },
                })

        async def ensure_text_started():
            nonlocal text_started, index
            async for item in ensure_started():
                yield item
            if not text_started:
                text_started = True
                yield sse("content_block_start", {"type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""}})

        async def close_text_block():
            nonlocal text_started, index
            if text_started:
                yield sse("content_block_stop", {"type": "content_block_stop", "index": index})
                text_started = False
                index += 1

        # 主循环：解析上游 Chat SSE
        async for chunk in stream_response:
            buffer += chunk.decode("utf-8", "ignore")
            while "\n\n" in buffer:
                event_block, buffer = buffer.split("\n\n", 1)
                data_lines = [ln[5:].strip() for ln in event_block.splitlines() if ln.startswith("data:")]
                if not data_lines:
                    continue
                data_text = "\n".join(data_lines)
                if data_text == "[DONE]":
                    continue
                try:
                    payload = json.loads(data_text)
                except json.JSONDecodeError:
                    continue

                # 持续合并 usage
                if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
                    message_usage = self._merge_claude_usage(
                        message_usage,
                        self._normalize_claude_usage_from_chat_usage(payload["usage"]),
                    )

                choice = ((payload.get("choices") or [{}])[0] if isinstance(payload, dict) else {})
                delta = choice.get("delta") or {}

                # 文本 delta
                delta_content = delta.get("content")
                if isinstance(delta_content, str) and delta_content:
                    async for item in ensure_text_started():
                        yield item
                    yield sse("content_block_delta", {
                        "type": "content_block_delta",
                        "index": index,
                        "delta": {"type": "text_delta", "text": delta_content},
                    })

                # 工具调用 delta
                for tc_delta in delta.get("tool_calls") or []:
                    async for item in close_text_block():
                        yield item
                    tc_index = int(tc_delta.get("index", 0) or 0)
                    state = tool_states.setdefault(tc_index, {
                        "id": tc_delta.get("id") or f"call_{message_id}_{tc_index}",
                        "name": "",
                        "arguments": "",
                        "started": False,
                        "block_index": None,
                    })
                    fn_delta = tc_delta.get("function") or {}
                    if tc_delta.get("id"):
                        state["id"] = tc_delta["id"]
                    if fn_delta.get("name"):
                        state["name"] += fn_delta["name"]
                    # 开始 tool_use block
                    if not state["started"] and state["name"]:
                        async for item in ensure_started():
                            yield item
                        state["started"] = True
                        state["block_index"] = index
                        yield sse("content_block_start", {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": {"type": "tool_use", "id": state["id"], "name": state["name"], "input": {}},
                        })
                    # arguments delta
                    args_chunk = fn_delta.get("arguments") or ""
                    if args_chunk and state["started"]:
                        state["arguments"] += args_chunk
                        yield sse("content_block_delta", {
                            "type": "content_block_delta",
                            "index": state["block_index"],
                            "delta": {"type": "input_json_delta", "partial_json": args_chunk},
                        })

                # 记录 finish_reason 但不 break（等后续 usage 事件）
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

        # 流结束：关闭所有 block
        async for item in close_text_block():
            yield item
        for state in sorted(tool_states.values(), key=lambda s: s.get("block_index") or 0):
            if state.get("started"):
                yield sse("content_block_stop", {"type": "content_block_stop", "index": state["block_index"]})
                index += 1

        # 确保至少发过 message_start
        async for item in ensure_started():
            yield item

        # 确定 stop_reason
        has_tools = any(s.get("started") for s in tool_states.values())
        stop_reason = "tool_use" if has_tools or finish_reason == "tool_calls" else "end_turn"

        # message_delta + message_stop
        yield sse("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": dict(message_usage),
        })
        yield sse("message_stop", {"type": "message_stop"})


# 全局实例
proxy_service = ProxyService()
