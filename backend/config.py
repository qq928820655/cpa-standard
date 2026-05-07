"""
配置管理模块
"""
import json
import secrets
from pathlib import Path
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DEFAULT_DATABASE_PATH = DATA_DIR / "cpa.db"
EXPORT_CONFIG_PATH = DATA_DIR / "export_config.json"
DEFAULT_EXPORT_CONFIG = {
    "usage_guide_default_content": "hello!",
    "homepage": "https://www.wishyouhappy.hahaha",
    "default_key_check_model": "",
    "default_key_check_models": ["", "gpt-4o-mini", "claude-3-5-sonnet-20241022", "", "", ""],
    "image_auto_refresh_delay_seconds": 60,
    "image_auto_refresh_interval_seconds": 30,
    "image_auto_refresh_max_attempts": 10,
    "image_stale_task_cleanup_interval_seconds": 60,
}


def load_export_config() -> dict:
    """加载导出配置文件，不存在时自动写入默认配置。"""
    EXPORT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if not EXPORT_CONFIG_PATH.exists():
        EXPORT_CONFIG_PATH.write_text(
            json.dumps(DEFAULT_EXPORT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return DEFAULT_EXPORT_CONFIG.copy()

    try:
        raw_text = EXPORT_CONFIG_PATH.read_text(encoding="utf-8").strip()
        data = json.loads(raw_text) if raw_text else {}
    except (OSError, json.JSONDecodeError):
        data = {}

    merged = DEFAULT_EXPORT_CONFIG.copy()
    if isinstance(data, dict):
        merged.update({key: value for key, value in data.items() if value not in (None, "")})

    if merged != data:
        EXPORT_CONFIG_PATH.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return merged


class Settings(BaseSettings):
    # 应用配置
    app_name: str = "CPA - API Key 中转系统"
    debug: bool = True

    # 数据库配置
    database_url: str = f"sqlite+aiosqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"

    # 本地 Master Key（首次启动时自动生成）
    master_key: str = ""

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000

    # 代理超时配置（秒）
    proxy_timeout: int = 300
    proxy_request_timeout_seconds: int = 60
    proxy_stream_connect_timeout_seconds: int = 15
    proxy_stream_first_byte_timeout_seconds: int = 15
    proxy_stream_read_timeout_seconds: int = 45

    # 会话粘滞配置
    proxy_session_sticky_enabled: bool = True
    proxy_session_sticky_ttl_seconds: int = 3600

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
export_config = load_export_config()

# 如果没有配置 Master Key，自动生成一个
if not settings.master_key:
    master_key_file = DATA_DIR / "master_key.txt"
    if master_key_file.exists():
        settings.master_key = master_key_file.read_text().strip()
    else:
        settings.master_key = f"cpa-{secrets.token_urlsafe(32)}"
        master_key_file.parent.mkdir(parents=True, exist_ok=True)
        master_key_file.write_text(settings.master_key)
