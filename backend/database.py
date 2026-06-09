"""
数据库连接和会话管理
"""
from sqlalchemy import event, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

IMAGE_KEY_INITIAL_AMOUNT_UNITS = 1
IMAGE_MODEL_PRICE_UNITS = {
    "gpt-image-2": 0.04,
    "gpt-image-2-pro": 0.08,
    "gpt-image-1-vip": 0.04,
    "gpt-image-1": 0.04,
    "nano-banana-pro": 0.06,
    "nano-banana-pro-4k": 0.08,
}


def normalize_image_model_name(model: str | None) -> str:
    """归一化图片模型名称"""
    return (model or "").strip().lower()


engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"timeout": 120},
)


@event.listens_for(engine.sync_engine, "connect")
def configure_sqlite_connection(dbapi_connection, _connection_record):
    if not settings.database_url.startswith("sqlite"):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=120000")
    cursor.close()


async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db():
    """获取数据库会话"""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    """初始化数据库表"""
    from models import (
        Base,
        ApiKey,
        ApiKeyCheckTask,
        ApiKeyCheckTaskResult,
        ImageGenerationTask,
        ImageGenerationTaskResult,
        ImageKeyModelStats,
        ModelCatalog,
        ProviderModelPriority,
        ProviderModelMapping,
        UsageDailySummary,
        UsageLog,
        AdminUser,
        AdminSession,
        ContentGuardEvent,
        OpenAIPlusAccount,
        OpenAIPlusUsageLog,
        ProxyTrace,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def has_supported_models(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "supported_models" for column in columns)

        def has_enable_proxy(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "enable_proxy" for column in columns)

        def has_proxy_url(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "proxy_url" for column in columns)

        def has_proxy_username(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "proxy_username" for column in columns)

        def has_proxy_password(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "proxy_password" for column in columns)

        def has_enable_fake_ip(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "enable_fake_ip" for column in columns)

        def has_fake_ip(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "fake_ip" for column in columns)

        def has_api_key_api_type(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "api_type" for column in columns)

        def has_provider_model_priority_model_normalized(sync_conn):
            columns = inspect(sync_conn).get_columns("provider_model_priorities")
            return any(column["name"] == "model_normalized" for column in columns)

        def has_supports_gemini(sync_conn):
            columns = inspect(sync_conn).get_columns("model_catalog")
            return any(column["name"] == "supports_gemini" for column in columns)

        def has_upstream_latency_ms(sync_conn):
            columns = inspect(sync_conn).get_columns("usage_logs")
            return any(column["name"] == "upstream_latency_ms" for column in columns)

        def has_cpa_overhead_ms(sync_conn):
            columns = inspect(sync_conn).get_columns("usage_logs")
            return any(column["name"] == "cpa_overhead_ms" for column in columns)

        def has_image_generation_task_is_deleted(sync_conn):
            columns = inspect(sync_conn).get_columns("image_generation_tasks")
            return any(column["name"] == "is_deleted" for column in columns)

        def has_image_generation_task_duration_ms(sync_conn):
            columns = inspect(sync_conn).get_columns("image_generation_tasks")
            return any(column["name"] == "duration_ms" for column in columns)

        def has_image_generation_task_result_duration_ms(sync_conn):
            columns = inspect(sync_conn).get_columns("image_generation_task_results")
            return any(column["name"] == "duration_ms" for column in columns)

        def has_image_generation_task_pending_refresh(sync_conn):
            columns = inspect(sync_conn).get_columns("image_generation_tasks")
            return any(column["name"] == "pending_refresh" for column in columns)

        def has_admin_user_role(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "role" for column in columns)

        def has_admin_user_api_key(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "api_key" for column in columns)

        def has_admin_user_supported_models(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "supported_models" for column in columns)

        def has_usage_log_user_id(sync_conn):
            columns = inspect(sync_conn).get_columns("usage_logs")
            return any(column["name"] == "user_id" for column in columns)

        def has_image_generation_task_user_id(sync_conn):
            columns = inspect(sync_conn).get_columns("image_generation_tasks")
            return any(column["name"] == "user_id" for column in columns)

        def has_usage_daily_summary_user_id(sync_conn):
            columns = inspect(sync_conn).get_columns("usage_daily_summaries")
            return any(column["name"] == "user_id" for column in columns)

        def has_image_key_model_stats_rows(sync_conn):
            result = sync_conn.execute(text("SELECT COUNT(1) FROM image_key_model_stats"))
            return int(result.scalar() or 0) > 0

        def has_image_key_model_stats_float_units(sync_conn):
            """检查 spent_units 列是否已为 REAL/FLOAT 类型"""
            result = sync_conn.execute(text("PRAGMA table_info(image_key_model_stats)"))
            for row in result.fetchall():
                if row[1] == "spent_units":
                    return (row[2] or "").upper() in {"REAL", "FLOAT", "DOUBLE"}
            return True  # 列不存在时由 create_all 处理

        if not await conn.run_sync(has_supported_models):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN supported_models TEXT")

        if not await conn.run_sync(has_enable_proxy):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN enable_proxy BOOLEAN DEFAULT 0")

        if not await conn.run_sync(has_proxy_url):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN proxy_url VARCHAR(500)")

        if not await conn.run_sync(has_proxy_username):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN proxy_username TEXT")

        if not await conn.run_sync(has_proxy_password):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN proxy_password TEXT")

        if not await conn.run_sync(has_enable_fake_ip):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN enable_fake_ip BOOLEAN DEFAULT 0")

        if not await conn.run_sync(has_fake_ip):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN fake_ip VARCHAR(64)")

        if not await conn.run_sync(has_api_key_api_type):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN api_type VARCHAR(30) DEFAULT 'other'")

        if not await conn.run_sync(has_provider_model_priority_model_normalized):
            await conn.exec_driver_sql(
                "ALTER TABLE provider_model_priorities ADD COLUMN model_normalized VARCHAR(200) DEFAULT ''"
            )
            await conn.exec_driver_sql(
                "UPDATE provider_model_priorities SET model_normalized = lower(trim(model)) WHERE model_normalized = ''"
            )

        if not await conn.run_sync(has_supports_gemini):
            await conn.exec_driver_sql("ALTER TABLE model_catalog ADD COLUMN supports_gemini BOOLEAN DEFAULT 0")

        if not await conn.run_sync(has_upstream_latency_ms):
            await conn.exec_driver_sql("ALTER TABLE usage_logs ADD COLUMN upstream_latency_ms INTEGER DEFAULT 0")

        if not await conn.run_sync(has_cpa_overhead_ms):
            await conn.exec_driver_sql("ALTER TABLE usage_logs ADD COLUMN cpa_overhead_ms INTEGER DEFAULT 0")

        def has_cache_tokens_log(sync_conn):
            columns = inspect(sync_conn).get_columns("usage_logs")
            return any(column["name"] == "cache_tokens" for column in columns)

        def has_cache_tokens_summary(sync_conn):
            columns = inspect(sync_conn).get_columns("usage_daily_summaries")
            return any(column["name"] == "cache_tokens" for column in columns)

        if not await conn.run_sync(has_cache_tokens_log):
            await conn.exec_driver_sql("ALTER TABLE usage_logs ADD COLUMN cache_tokens INTEGER DEFAULT 0")

        def has_api_key_password(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "password" for column in columns)

        if not await conn.run_sync(has_api_key_password):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN password TEXT")

        def has_api_key_wz_url(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "wz_url" for column in columns)

        if not await conn.run_sync(has_api_key_wz_url):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN wz_url VARCHAR(500)")

        def has_api_key_security_violation_count(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "security_violation_count" for column in columns)

        if not await conn.run_sync(has_api_key_security_violation_count):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN security_violation_count INTEGER DEFAULT 0")

        def has_api_key_last_security_violation(sync_conn):
            columns = inspect(sync_conn).get_columns("api_keys")
            return any(column["name"] == "last_security_violation" for column in columns)

        if not await conn.run_sync(has_api_key_last_security_violation):
            await conn.exec_driver_sql("ALTER TABLE api_keys ADD COLUMN last_security_violation TEXT")

        def has_actual_model(sync_conn):
            columns = inspect(sync_conn).get_columns("usage_logs")
            return any(column["name"] == "actual_model" for column in columns)

        if not await conn.run_sync(has_actual_model):
            await conn.exec_driver_sql("ALTER TABLE usage_logs ADD COLUMN actual_model VARCHAR(100)")

        if not await conn.run_sync(has_cache_tokens_summary):
            await conn.exec_driver_sql("ALTER TABLE usage_daily_summaries ADD COLUMN cache_tokens INTEGER DEFAULT 0")

        if not await conn.run_sync(has_image_generation_task_is_deleted):
            await conn.exec_driver_sql("ALTER TABLE image_generation_tasks ADD COLUMN is_deleted BOOLEAN DEFAULT 0")

        if not await conn.run_sync(has_image_generation_task_duration_ms):
            await conn.exec_driver_sql("ALTER TABLE image_generation_tasks ADD COLUMN duration_ms INTEGER DEFAULT 0")

        if not await conn.run_sync(has_image_generation_task_result_duration_ms):
            await conn.exec_driver_sql("ALTER TABLE image_generation_task_results ADD COLUMN duration_ms INTEGER DEFAULT 0")

        if not await conn.run_sync(has_image_generation_task_pending_refresh):
            await conn.exec_driver_sql("ALTER TABLE image_generation_tasks ADD COLUMN pending_refresh BOOLEAN DEFAULT 0")

        await conn.exec_driver_sql(
            """
            UPDATE image_generation_tasks
            SET duration_ms = CAST((julianday(finished_at) - julianday(started_at)) * 86400000 AS INTEGER)
            WHERE duration_ms = 0 AND started_at IS NOT NULL AND finished_at IS NOT NULL
            """
        )
        await conn.exec_driver_sql(
            """
            UPDATE image_generation_task_results
            SET duration_ms = CAST((julianday(finished_at) - julianday(started_at)) * 86400000 AS INTEGER)
            WHERE duration_ms = 0 AND started_at IS NOT NULL AND finished_at IS NOT NULL
            """
        )

        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_api_keys_provider_is_active_id ON api_keys(provider, is_active, id)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_api_keys_provider_id ON api_keys(provider, id)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_api_keys_name_provider ON api_keys(name, provider)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_usage_logs_api_key_id_request_time ON usage_logs(api_key_id, request_time)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_usage_logs_request_time_api_key_id ON usage_logs(request_time, api_key_id)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_usage_logs_api_key_id_status_request_time ON usage_logs(api_key_id, status, request_time)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_image_generation_tasks_is_deleted_created_at ON image_generation_tasks(is_deleted, created_at)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_proxy_traces_trace_id ON proxy_traces(trace_id)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_proxy_traces_created_at ON proxy_traces(created_at)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_proxy_traces_api_key_id_created_at ON proxy_traces(api_key_id, created_at)")
        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_proxy_traces_provider_created_at ON proxy_traces(provider, created_at)")

        # 用户角色与 API Key 字段迁移
        if not await conn.run_sync(has_admin_user_role):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN role VARCHAR(20) DEFAULT 'user'")
            # 已有用户均为系统初始用户，全部升级为 admin
            await conn.exec_driver_sql("UPDATE admin_users SET role = 'admin'")

        if not await conn.run_sync(has_admin_user_api_key):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN api_key VARCHAR(128)")

        if not await conn.run_sync(has_admin_user_supported_models):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN supported_models TEXT")

        def has_admin_user_daily_token_limit(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "daily_token_limit" for column in columns)

        def has_admin_user_weekly_token_limit(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "weekly_token_limit" for column in columns)

        def has_admin_user_monthly_token_limit(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "monthly_token_limit" for column in columns)

        if not await conn.run_sync(has_admin_user_daily_token_limit):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN daily_token_limit INTEGER")

        if not await conn.run_sync(has_admin_user_weekly_token_limit):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN weekly_token_limit INTEGER")

        if not await conn.run_sync(has_admin_user_monthly_token_limit):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN monthly_token_limit INTEGER")

        def has_admin_user_quota_exceeded_mode(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "quota_exceeded_mode" for column in columns)

        def has_admin_user_quota_exceeded_message(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "quota_exceeded_message" for column in columns)

        if not await conn.run_sync(has_admin_user_quota_exceeded_mode):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN quota_exceeded_mode VARCHAR(20) DEFAULT 'normal'")

        if not await conn.run_sync(has_admin_user_quota_exceeded_message):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN quota_exceeded_message TEXT")

        def has_admin_user_model_mapping(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "model_mapping" for column in columns)

        if not await conn.run_sync(has_admin_user_model_mapping):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN model_mapping TEXT")

        def has_admin_user_show_quota(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "show_quota_to_user" for column in columns)

        def has_admin_user_quota_reset_at(sync_conn):
            columns = inspect(sync_conn).get_columns("admin_users")
            return any(column["name"] == "quota_reset_at" for column in columns)

        if not await conn.run_sync(has_admin_user_show_quota):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN show_quota_to_user INTEGER DEFAULT 0")

        if not await conn.run_sync(has_admin_user_quota_reset_at):
            await conn.exec_driver_sql("ALTER TABLE admin_users ADD COLUMN quota_reset_at DATETIME")

        # 为已有 admin 用户生成 api_key（如果还没有）
        await conn.exec_driver_sql(
            "UPDATE admin_users SET api_key = 'pending' WHERE api_key IS NULL AND role = 'admin'"
        )

        # usage_logs / image_generation_tasks 增加 user_id 字段
        if not await conn.run_sync(has_usage_log_user_id):
            await conn.exec_driver_sql("ALTER TABLE usage_logs ADD COLUMN user_id INTEGER")

        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_usage_logs_user_id ON usage_logs(user_id)")

        if not await conn.run_sync(has_image_generation_task_user_id):
            await conn.exec_driver_sql("ALTER TABLE image_generation_tasks ADD COLUMN user_id INTEGER")

        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_image_generation_tasks_user_id ON image_generation_tasks(user_id)")

        # usage_daily_summaries 增加 user_id 字段
        if not await conn.run_sync(has_usage_daily_summary_user_id):
            await conn.exec_driver_sql("ALTER TABLE usage_daily_summaries ADD COLUMN user_id INTEGER")

        await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_usage_daily_summaries_user_id ON usage_daily_summaries(user_id)")

        if not await conn.run_sync(has_image_key_model_stats_float_units):
            # 将 image_key_model_stats 的 spent_units/remaining_units 从 INTEGER 迁移为 REAL
            await conn.exec_driver_sql("""
                CREATE TABLE IF NOT EXISTS image_key_model_stats_migrated (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_key_id INTEGER NOT NULL,
                    api_key_name VARCHAR(100),
                    provider VARCHAR(100),
                    model VARCHAR(200) NOT NULL,
                    model_normalized VARCHAR(200) NOT NULL,
                    total_count INTEGER DEFAULT 0 NOT NULL,
                    success_count INTEGER DEFAULT 0 NOT NULL,
                    error_count INTEGER DEFAULT 0 NOT NULL,
                    spent_units REAL DEFAULT 0.0 NOT NULL,
                    remaining_units REAL DEFAULT 1.0 NOT NULL,
                    last_generated_at DATETIME,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE(api_key_id, model_normalized)
                )
            """)
            await conn.exec_driver_sql("""
                INSERT OR IGNORE INTO image_key_model_stats_migrated
                SELECT * FROM image_key_model_stats
            """)
            await conn.exec_driver_sql("DROP TABLE IF EXISTS image_key_model_stats")
            await conn.exec_driver_sql("ALTER TABLE image_key_model_stats_migrated RENAME TO image_key_model_stats")
            await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_image_key_model_stats_api_key_id ON image_key_model_stats(api_key_id)")
            await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_image_key_model_stats_model_normalized ON image_key_model_stats(model_normalized)")
            await conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_image_key_model_stats_updated_at ON image_key_model_stats(updated_at)")

        if not await conn.run_sync(has_image_key_model_stats_rows):
            history_result = await conn.execute(text(
                """
                SELECT api_key_id,
                       MAX(api_key_name) AS api_key_name,
                       MAX(provider) AS provider,
                       MIN(model) AS model,
                       lower(trim(model)) AS model_normalized,
                       SUM(COALESCE(total_count, 0)) AS total_count,
                       SUM(COALESCE(success_count, 0)) AS success_count,
                       SUM(COALESCE(error_count, 0)) AS error_count,
                       MAX(COALESCE(finished_at, updated_at, created_at)) AS last_generated_at
                FROM image_generation_tasks
                WHERE api_key_id IS NOT NULL
                GROUP BY api_key_id, lower(trim(model))
                """
            ))
            now = None
            for row in history_result.mappings().all():
                model_normalized = normalize_image_model_name(row["model_normalized"])
                price_units = IMAGE_MODEL_PRICE_UNITS.get(model_normalized)
                success_count = int(row["success_count"] or 0)
                spent_units = success_count * price_units if price_units else 0
                remaining_units = max(0, IMAGE_KEY_INITIAL_AMOUNT_UNITS - spent_units)
                if now is None:
                    from datetime import datetime
                    now = datetime.utcnow()
                await conn.execute(
                    text(
                        """
                        INSERT INTO image_key_model_stats (
                            api_key_id, api_key_name, provider, model, model_normalized,
                            total_count, success_count, error_count, spent_units, remaining_units,
                            last_generated_at, created_at, updated_at
                        ) VALUES (
                            :api_key_id, :api_key_name, :provider, :model, :model_normalized,
                            :total_count, :success_count, :error_count, :spent_units, :remaining_units,
                            :last_generated_at, :created_at, :updated_at
                        )
                        """
                    ),
                    {
                        "api_key_id": row["api_key_id"],
                        "api_key_name": row["api_key_name"],
                        "provider": row["provider"],
                        "model": row["model"],
                        "model_normalized": model_normalized,
                        "total_count": int(row["total_count"] or 0),
                        "success_count": success_count,
                        "error_count": int(row["error_count"] or 0),
                        "spent_units": spent_units,
                        "remaining_units": remaining_units,
                        "last_generated_at": row["last_generated_at"],
                        "created_at": now,
                        "updated_at": now,
                    },
                )
