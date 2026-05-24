"""
Content safety guard for upstream responses.
"""
import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from config import export_config
from services.pool_manager import pool_manager


DEFAULT_AD_PATTERNS = [
    "powered by",
    "buy now",
    "limited time offer",
    "推广",
    "广告",
    "优惠码",
    "邀请码",
    "加群",
]

DEFAULT_DANGEROUS_PATTERNS = [
    r"curl\s+[^\n|;]+\|\s*(?:sh|bash)",
    r"wget\s+[^\n|;]+\|\s*(?:sh|bash)",
    r"Invoke-WebRequest[\s\S]{0,120}\|\s*iex",
    r"iwr[\s\S]{0,120}\|\s*iex",
    r"powershell(?:\.exe)?\s+[^\n]*(?:-enc|-encodedcommand)",
    r"rm\s+-rf\s+(?:/|~|\$HOME)",
    r"chmod\s+\+x\s+[^\n]+&&\s*[^\n]+",
    r"(?:process\.env|os\.environ|getenv)\s*\[[^\]]*(?:KEY|TOKEN|SECRET|PASSWORD)",
    r"(?:api[_-]?key|token|secret|password)[\s\S]{0,80}(?:requests\.post|fetch\(|axios\.post|curl)",
    r"(?:crontab|schtasks|systemctl)\s+[^\n]*(?:http|curl|wget)",
]

TEXT_KEYS = {
    "content",
    "text",
    "message",
    "completion",
    "delta",
    "output_text",
    "response",
    "reasoning",
}


@dataclass
class GuardResult:
    safe: bool
    category: Optional[str] = None
    rule: Optional[str] = None
    snippet: Optional[str] = None
    match_start: Optional[int] = None
    match_end: Optional[int] = None


class ContentGuardService:
    def get_config(self) -> dict:
        raw = export_config.get("content_guard") or {}
        return {
            "enabled": bool(raw.get("enabled", False)),
            "check_ads": bool(raw.get("check_ads", True)),
            "check_dangerous_code": bool(raw.get("check_dangerous_code", True)),
            "block_on_violation": bool(raw.get("block_on_violation", True)),
            "ad_action": self._coerce_choice(raw.get("ad_action"), "record", {"record", "sanitize", "block"}),
            "auto_disable_key": bool(raw.get("auto_disable_key", False)),
            "disable_threshold": self._coerce_int(raw.get("disable_threshold"), 3, 1, 100),
            "downgrade_weight": self._coerce_int(raw.get("downgrade_weight"), 1, 0, 100),
            "ad_patterns": self._coerce_patterns(raw.get("ad_patterns"), DEFAULT_AD_PATTERNS),
            "ad_regex_patterns": self._coerce_patterns(raw.get("ad_regex_patterns"), []),
            "dangerous_patterns": self._coerce_patterns(raw.get("dangerous_patterns"), DEFAULT_DANGEROUS_PATTERNS),
        }

    def scan_response(self, response_data: Any) -> GuardResult:
        config = self.get_config()
        if not config["enabled"]:
            return GuardResult(safe=True)

        text = self.extract_text(response_data)
        if not text.strip():
            return GuardResult(safe=True)

        if config["check_dangerous_code"]:
            result = self._scan_regex_patterns(text, config["dangerous_patterns"], "dangerous_code")
            if not result.safe:
                return result

        if config["check_ads"]:
            result = self._scan_text_patterns(text, config["ad_patterns"], "advertisement")
            if not result.safe:
                return result
            result = self._scan_regex_patterns(text, config["ad_regex_patterns"], "advertisement")
            if not result.safe:
                return result

        return GuardResult(safe=True)

    async def handle_violation(
        self,
        db: AsyncSession,
        api_key: Any,
        result: GuardResult,
        *,
        model: Optional[str] = None,
        path: Optional[str] = None,
    ) -> None:
        from models import ContentGuardEvent

        current_count = int(getattr(api_key, "security_violation_count", 0) or 0) + 1
        api_key.security_violation_count = current_count
        api_key.last_security_violation = self.build_violation_message(result)

        config = self.get_config()
        action = "recorded"
        downgrade_weight = int(config.get("downgrade_weight") or 0)
        if downgrade_weight > 0:
            current_weight = int(getattr(api_key, "weight", 1) or 1)
            api_key.weight = min(current_weight, downgrade_weight)
            action = "downgraded"

        if result.category == "advertisement":
            ad_action = config.get("ad_action") or "record"
            if ad_action == "sanitize":
                action = "sanitized"
            elif ad_action == "block":
                action = "blocked"
        elif config.get("block_on_violation", True):
            action = "blocked"

        if config.get("auto_disable_key") and current_count >= int(config.get("disable_threshold") or 3):
            api_key.is_active = False
            action = "disabled"

        db.add(ContentGuardEvent(
            api_key_id=getattr(api_key, "id", None),
            key_name=getattr(api_key, "name", None),
            provider=getattr(api_key, "provider", None),
            base_url=getattr(api_key, "base_url", None),
            model=model,
            path=path,
            category=result.category or "unknown",
            rule=result.rule,
            snippet=result.snippet,
            explanation=self.build_explanation(result),
            action=action,
        ))

        await db.commit()
        provider = getattr(api_key, "provider", None)
        if provider:
            pool_manager.reset_index(provider)
        pool_manager.clear_key_cooldown(getattr(api_key, "id", 0))

    def build_block_response(self, result: GuardResult) -> dict:
        return {
            "error": {
                "message": "CPA 内容安全防护已阻断上游响应",
                "type": "content_guard_violation",
                "category": result.category,
                "rule": result.rule,
                "snippet": result.snippet,
            }
        }

    def should_block(self, result: GuardResult) -> bool:
        config = self.get_config()
        if result.category == "advertisement":
            return config.get("ad_action") == "block"
        return bool(config.get("block_on_violation", True))

    def should_sanitize(self, result: GuardResult) -> bool:
        return result.category == "advertisement" and self.get_config().get("ad_action") == "sanitize"

    def sanitize_response(self, response_data: Any, result: GuardResult) -> Any:
        if not self.should_sanitize(result):
            return response_data
        return self._sanitize_value(response_data, result)

    def _sanitize_value(self, value: Any, result: GuardResult) -> Any:
        if isinstance(value, str):
            return self._sanitize_text(value, result)
        if isinstance(value, list):
            return [self._sanitize_value(item, result) for item in value]
        if isinstance(value, dict):
            return {key: self._sanitize_value(item, result) for key, item in value.items()}
        return value

    def _sanitize_text(self, text: str, result: GuardResult) -> str:
        if not text:
            return text
        if result.rule:
            try:
                cleaned = re.sub(result.rule, "", text, flags=re.IGNORECASE)
                if cleaned != text:
                    return self._cleanup_sanitized_text(cleaned)
            except re.error:
                pass
            cleaned = re.sub(re.escape(result.rule), "", text, flags=re.IGNORECASE)
            if cleaned != text:
                return self._cleanup_sanitized_text(cleaned)
        if result.snippet and result.snippet in text:
            return self._cleanup_sanitized_text(text.replace(result.snippet, ""))
        return text

    def _cleanup_sanitized_text(self, text: str) -> str:
        lines = [line.rstrip() for line in text.splitlines()]
        cleaned_lines = [line for line in lines if line.strip()]
        return "\n".join(cleaned_lines).strip()

    def build_violation_message(self, result: GuardResult) -> str:
        parts = [result.category or "unknown"]
        if result.rule:
            parts.append(f"rule={result.rule}")
        if result.snippet:
            parts.append(f"snippet={result.snippet}")
        return " | ".join(parts)

    def build_explanation(self, result: GuardResult) -> str:
        if result.category == "dangerous_code":
            return "上游响应命中危险代码/命令规则，可能诱导用户执行远程脚本、窃取凭据或写入持久化后门。"
        if result.category == "advertisement":
            return "上游响应命中广告或推广关键词，可能存在模型回答污染、夹带推广内容或品牌水印。"
        return "上游响应命中内容安全规则，建议复核该 Key 与供应商返回内容。"

    def extract_text(self, value: Any) -> str:
        chunks: list[str] = []

        def visit(item: Any, key: Optional[str] = None):
            if item is None:
                return
            if isinstance(item, str):
                if key is None or key in TEXT_KEYS or len(item) > 20:
                    chunks.append(item)
                return
            if isinstance(item, (int, float, bool)):
                return
            if isinstance(item, list):
                for child in item:
                    visit(child, key)
                return
            if isinstance(item, dict):
                for child_key, child_value in item.items():
                    visit(child_value, str(child_key))
                return
            chunks.append(str(item))

        visit(value)
        return "\n".join(chunks)

    def _scan_text_patterns(self, text: str, patterns: list[str], category: str) -> GuardResult:
        lower_text = text.lower()
        for pattern in patterns:
            needle = pattern.strip()
            if not needle:
                continue
            index = lower_text.find(needle.lower())
            if index >= 0:
                return GuardResult(False, category, needle, self._snippet(text, index, len(needle)), index, index + len(needle))
        return GuardResult(True)

    def _scan_regex_patterns(self, text: str, patterns: list[str], category: str) -> GuardResult:
        for pattern in patterns:
            if not pattern.strip():
                continue
            try:
                match = re.search(pattern, text, re.IGNORECASE)
            except re.error:
                continue
            if match:
                return GuardResult(False, category, pattern, self._snippet(text, match.start(), match.end() - match.start()), match.start(), match.end())
        return GuardResult(True)

    def _snippet(self, text: str, start: int, length: int) -> str:
        left = max(start - 80, 0)
        right = min(start + length + 80, len(text))
        snippet = text[left:right].replace("\r", " ").replace("\n", " ")
        return snippet[:260]

    def _coerce_int(self, value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            current = int(value)
        except (TypeError, ValueError):
            current = default
        return min(max(current, minimum), maximum)

    def _coerce_patterns(self, value: Any, default: list[str]) -> list[str]:
        if not isinstance(value, list):
            return list(default)
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or list(default)

    def _coerce_choice(self, value: Any, default: str, choices: set[str]) -> str:
        text = str(value or "").strip().lower()
        return text if text in choices else default


content_guard_service = ContentGuardService()
