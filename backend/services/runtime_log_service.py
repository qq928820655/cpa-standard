"""进程运行日志内存循环缓冲。"""

import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

from config import export_config


BEIJING_TZ = timezone(timedelta(hours=8))
DEFAULT_MAX_BYTES = 3 * 1024 * 1024
DEFAULT_LINE_LIMIT = 500
MAX_LINE_LIMIT = 5000

# uvicorn.access 记录中，只有真正的业务代理访问才有保留价值（如 /v1/messages）。
# 后台自身的管理接口、鉴权轮询、静态资源、探活、SPA 页面路由等都是高频噪声，
# 因此改用白名单：仅保留命中这些业务前缀的 access 记录，其余一律丢弃。
_ACCESS_LOG_BUSINESS_PREFIXES = (
    "/v1/",
    "/proxy/",
    "/grok/",
)


class RuntimeLogBuffer:
    """按 UTF-8 字节数限制容量的线程安全日志缓冲。"""

    def __init__(self, max_bytes: int = DEFAULT_MAX_BYTES):
        self.max_bytes = max_bytes
        self._entries: deque[dict[str, Any]] = deque()
        self._total_bytes = 0
        self._sequence = 0
        self._lock = threading.RLock()

    def append(self, level: str, logger_name: str, message: str) -> None:
        if not bool(export_config.get("runtime_log_enabled", False)):
            return

        timestamp = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d %H:%M:%S")
        lines = str(message).splitlines() or [""]
        with self._lock:
            for line in lines:
                self._sequence += 1
                entry = {
                    "id": self._sequence,
                    "timestamp": timestamp,
                    "level": level,
                    "logger": logger_name,
                    "message": line,
                }
                entry_bytes = len(
                    f"{timestamp}\t{level}\t{logger_name}\t{line}\n".encode("utf-8", errors="replace")
                )
                entry["bytes"] = entry_bytes
                self._entries.append(entry)
                self._total_bytes += entry_bytes
                while self._entries and self._total_bytes > self.max_bytes:
                    removed = self._entries.popleft()
                    self._total_bytes -= int(removed["bytes"])

    def list(self, limit: int = DEFAULT_LINE_LIMIT, keyword: str = "", after_id: int = 0) -> dict[str, Any]:
        safe_limit = max(1, min(int(limit), MAX_LINE_LIMIT))
        normalized_keyword = keyword.strip().lower()
        with self._lock:
            entries = list(self._entries)
            total_bytes = self._total_bytes
            latest_id = self._sequence

        if after_id > 0:
            entries = [item for item in entries if int(item["id"]) > after_id]
        if normalized_keyword:
            entries = [
                item
                for item in entries
                if normalized_keyword
                in f"{item['level']} {item['logger']} {item['message']}".lower()
            ]
        entries = entries[-safe_limit:]
        return {
            "items": [{key: value for key, value in item.items() if key != "bytes"} for item in entries],
            "latest_id": latest_id,
            "total_bytes": total_bytes,
            "max_bytes": self.max_bytes,
        }

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0


class RuntimeLogHandler(logging.Handler):
    """将标准 logging 记录写入运行日志缓冲。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            # uvicorn.access 改用白名单：仅保留命中业务代理前缀的访问记录，
            # 其余（管理接口、鉴权轮询、静态资源、探活、SPA 路由等）一律丢弃。
            if record.name == "uvicorn.access" and not any(
                prefix in message for prefix in _ACCESS_LOG_BUSINESS_PREFIXES
            ):
                return
            runtime_log_buffer.append(record.levelname, record.name, message)
        except Exception:
            self.handleError(record)


runtime_log_buffer = RuntimeLogBuffer()
_handler: RuntimeLogHandler | None = None


def install_runtime_log_handler() -> None:
    """安装日志处理器，并确保 Uvicorn 重置配置后仍保持挂载。"""
    global _handler
    if _handler is None:
        _handler = RuntimeLogHandler()
        _handler.setFormatter(logging.Formatter("%(message)s"))

    # 根 logger 捕获应用日志；Uvicorn 的非传播 logger 单独挂载，避免同一记录重复。
    for logger_name in ("", "uvicorn", "uvicorn.access"):
        target = logging.getLogger(logger_name)
        if _handler not in target.handlers:
            target.addHandler(_handler)
    for logger_name in ("main", "cpa.proxy", "cpa.proxy_service"):
        logging.getLogger(logger_name).setLevel(logging.INFO)
    logging.captureWarnings(True)
