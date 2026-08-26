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
    "openai_plus_proxy_url": "",
    # provider 扩展配置：{ "bb": { "password": "xxx" }, ... }
    "provider_ext": {},
    # 是否向管理员显示实际使用的模型（格式：请求模型/映射模型），默认关闭
    "show_actual_model": False,
    # 供应商迁移规则：余额不足时自动切换供应商
    "provider_migration_rules": [
        {
            "from_provider": "bb",
            "to_provider": "bbimg",
            "min_balance": 0.04,
            "max_balance": 0.18,
            "supported_models": [
                "gpt-image-1",
                "gpt-image-2",
                "gpt-image-2-pro",
                "nano-banana-pro",
                "nano-banana-pro-4k",
            ],
        }
    ],
    # 流式缓冲规则：命中规则的请求先完整缓冲上游响应再输出，断流可重试
    # provider/model 支持 * 通配，均为空则匹配所有
    # 示例：{"provider": "lumora", "model": "kiro*"} 或 {"provider": "lumora"}
    "stream_buffer_rules": [],
    # ClaudeCode 通过 OpenAI Chat 兼容上游时，部分 provider 需要提前返回 input_tokens
    "claudecode_token_compat_providers": ["skk"],
    # 余额不足降权规则（按 min 降序，第一个匹配生效）
    # action: none=不处理, weight=降权, disable=关闭
    "balance_downgrade_rules": [
        {"min": 0.5,  "max": None, "action": "none"},
        {"min": 0.35, "max": 0.5,  "action": "weight", "weight": 3},
        {"min": 0.25, "max": 0.35, "action": "weight", "weight": 2},
        {"min": 0.18, "max": 0.25, "action": "weight", "weight": 1},
        {"min": 0.0,  "max": 0.18, "action": "disable"},
    ],
    # provider/model 兼容覆盖规则：默认自动判断，仅对异常上游配置例外
    # 示例：{"provider": "skk", "model_pattern": "claude-*", "protocol": "openai_chat"}
    "provider_model_compat_overrides": [],
    # 透传错误码：命中这些状态码时直接返回上游响应，不切换 Key、不冷却、不重试
    "pass_through_error_codes": [],
    # 用量实时明细保留天数：超过后 usage_logs 明细清理，默认 7 天，可配置
    "usage_log_retention_days": 7,
    # 用量按天汇总保留天数：超过后 usage_daily_summaries 清理，默认 90 天，可配置
    "usage_summary_retention_days": 90,
    "model_price_display_currency": "USD",
    "model_price_exchange_rate_mode": "fixed",
    "model_price_usd_cny_rate": 7.2,
    # 模型种子回填开关：关闭后 list_models 不再用 DEFAULT_MODELS 种子自动插入/更新模型
    "model_seed_enabled": True,
    # 代理调试追踪：默认关闭，只记录轻量决策信息
    "proxy_trace_enabled": False,
    "proxy_trace_retention_hours": 24,
    "proxy_trace_sample_rate": 1.0,
    "proxy_trace_only_failures": False,
    "proxy_trace_target_provider": "",
    "proxy_trace_target_model": "",
    # 运行日志页面：默认关闭，开启后使用 3MB 内存循环缓冲
    "runtime_log_enabled": False,
    # 运行日志滚动信息：默认关闭，开启后按页面宽度自动换行显示
    "runtime_log_wrap": False,
    # 上游内容安全防护：默认关闭，开启后扫描广告与危险代码片段
    "content_guard": {
        "enabled": False,
        "check_ads": True,
        "check_dangerous_code": True,
        "block_on_violation": True,
        "ad_action": "record",
        "auto_disable_key": False,
        "disable_threshold": 3,
        "downgrade_weight": 1,
        "ad_patterns": ["powered by", "buy now", "推广", "广告", "优惠码", "邀请码", "加群"],
        "ad_regex_patterns": [],
        "dangerous_patterns": [],
    },
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
    debug: bool = False

    # 数据库配置
    database_url: str = f"sqlite+aiosqlite:///{DEFAULT_DATABASE_PATH.as_posix()}"

    # 本地 Master Key（首次启动时自动生成）
    master_key: str = ""

    # 服务配置
    host: str = "0.0.0.0"
    port: int = 8000

    # 代理超时配置（秒）
    proxy_timeout: int = 300
    proxy_request_timeout_seconds: int = 180
    proxy_stream_connect_timeout_seconds: int = 15
    proxy_stream_first_byte_timeout_seconds: int = 15
    proxy_stream_read_timeout_seconds: int = 180

    # 会话粘滞配置
    proxy_session_sticky_enabled: bool = True
    proxy_session_sticky_ttl_seconds: int = 3600
    proxy_session_sticky_fallback_enabled: bool = False

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
