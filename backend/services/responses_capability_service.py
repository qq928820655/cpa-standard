"""
OpenAI Responses capability detection by upstream base URL.
"""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

from config import DATA_DIR

RESPONSES_CAPABILITY_PATH = DATA_DIR / "responses_capabilities.json"
RESPONSES_CAPABILITY_TTL_DAYS = 10


class ResponsesCapabilityService:
    def __init__(self):
        self._lock = asyncio.Lock()

    @staticmethod
    def normalize_base_url(base_url: Optional[str]) -> str:
        value = str(base_url or "").strip().rstrip("/")
        if not value:
            return ""
        parsed = urlsplit(value)
        if not parsed.scheme or not parsed.netloc:
            return value.lower()
        normalized_path = parsed.path.rstrip("/")
        return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), normalized_path, "", ""))

    def _load(self) -> dict[str, dict[str, Any]]:
        if not RESPONSES_CAPABILITY_PATH.exists():
            return {}
        try:
            data = json.loads(RESPONSES_CAPABILITY_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data: dict[str, dict[str, Any]]) -> None:
        RESPONSES_CAPABILITY_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = Path(f"{RESPONSES_CAPABILITY_PATH}.tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(RESPONSES_CAPABILITY_PATH)

    @staticmethod
    def _parse_checked_at(value: Any) -> Optional[datetime]:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None

    def get_fresh_entry(self, base_url: Optional[str]) -> tuple[bool, Optional[bool]]:
        normalized = self.normalize_base_url(base_url)
        if not normalized:
            return False, None
        item = self._load().get(normalized)
        if not isinstance(item, dict):
            return False, None
        checked_at = self._parse_checked_at(item.get("checked_at"))
        if checked_at is None or datetime.utcnow() - checked_at > timedelta(days=RESPONSES_CAPABILITY_TTL_DAYS):
            return False, None
        supported = item.get("supported")
        return True, supported if isinstance(supported, bool) else None

    def get_fresh_result(self, base_url: Optional[str]) -> Optional[bool]:
        _, result = self.get_fresh_entry(base_url)
        return result

    async def resolve(self, api_key: Any, model: str, probe) -> Optional[bool]:
        base_url = self.normalize_base_url(getattr(api_key, "base_url", None))
        if not base_url:
            return None

        is_fresh, cached = self.get_fresh_entry(base_url)
        if is_fresh:
            return cached

        async with self._lock:
            is_fresh, cached = self.get_fresh_entry(base_url)
            if is_fresh:
                return cached

            result = await probe(api_key, model)
            supported = result.get("supported") if isinstance(result, dict) else None
            if not isinstance(supported, bool):
                supported = None

            data = self._load()
            data[base_url] = {
                "supported": supported,
                "checked_at": datetime.utcnow().isoformat() + "Z",
                "probe_model": model,
                "status_code": result.get("status_code") if isinstance(result, dict) else None,
                "response_object": result.get("response_object") if isinstance(result, dict) else None,
            }
            self._save(data)
            return supported


responses_capability_service = ResponsesCapabilityService()
