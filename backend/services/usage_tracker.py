"""
用量追踪服务
"""
from datetime import datetime
from typing import Optional, Any
from sqlalchemy.ext.asyncio import AsyncSession


class UsageTracker:
    """用量追踪器"""

    @staticmethod
    async def create_pending_record(
        db: AsyncSession,
        api_key_id: int,
        model: Optional[str] = None,
        actual_model: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Any:
        """创建进行中的用量记录"""
        from models import UsageLog

        log = UsageLog(
            api_key_id=api_key_id,
            user_id=user_id,
            model=model,
            actual_model=actual_model or model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency_ms=0,
            upstream_latency_ms=0,
            cpa_overhead_ms=0,
            status="in_progress",
            error_message=None,
            request_time=datetime.utcnow(),
        )

        db.add(log)
        await db.commit()
        await db.refresh(log)
        return log

    @staticmethod
    async def update_tokens(
        db: AsyncSession,
        log: Any,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        latency_ms: Optional[int] = None,
        upstream_latency_ms: Optional[int] = None,
        cpa_overhead_ms: Optional[int] = None,
    ) -> Any:
        """实时更新 token 用量"""
        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens

        persistent_log = await db.merge(log)
        persistent_log.prompt_tokens = prompt_tokens
        persistent_log.completion_tokens = completion_tokens
        persistent_log.total_tokens = total_tokens
        if latency_ms is not None:
            persistent_log.latency_ms = latency_ms
        if upstream_latency_ms is not None:
            persistent_log.upstream_latency_ms = upstream_latency_ms
        if cpa_overhead_ms is not None:
            persistent_log.cpa_overhead_ms = cpa_overhead_ms

        await db.commit()
        return persistent_log

    @staticmethod
    async def finalize_record(
        db: AsyncSession,
        log_id: int,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cache_tokens: int = 0,
        latency_ms: int = 0,
        upstream_latency_ms: int = 0,
        cpa_overhead_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> Any:
        """按主键完成用量记录更新"""
        from models import UsageLog

        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        if cpa_overhead_ms is None:
            cpa_overhead_ms = max(latency_ms - upstream_latency_ms, 0)

        persistent_log = await db.get(UsageLog, log_id)
        if persistent_log is None:
            return None

        persistent_log.prompt_tokens = prompt_tokens
        persistent_log.completion_tokens = completion_tokens
        persistent_log.total_tokens = total_tokens
        persistent_log.cache_tokens = cache_tokens
        persistent_log.latency_ms = latency_ms
        persistent_log.upstream_latency_ms = upstream_latency_ms
        persistent_log.cpa_overhead_ms = cpa_overhead_ms
        persistent_log.status = status
        persistent_log.error_message = error_message

        await db.commit()
        return persistent_log

    @staticmethod
    async def update_record(
        db: AsyncSession,
        log: Any,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cache_tokens: int = 0,
        latency_ms: int = 0,
        upstream_latency_ms: int = 0,
        cpa_overhead_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
    ) -> Any:
        """更新已有用量记录"""
        log_id = getattr(log, "id", None)
        if log_id is not None:
            return await UsageTracker.finalize_record(
                db=db,
                log_id=log_id,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cache_tokens=cache_tokens,
                latency_ms=latency_ms,
                upstream_latency_ms=upstream_latency_ms,
                cpa_overhead_ms=cpa_overhead_ms,
                status=status,
                error_message=error_message,
            )

        if total_tokens == 0:
            total_tokens = prompt_tokens + completion_tokens
        if cpa_overhead_ms is None:
            cpa_overhead_ms = max(latency_ms - upstream_latency_ms, 0)

        persistent_log = await db.merge(log)
        persistent_log.prompt_tokens = prompt_tokens
        persistent_log.completion_tokens = completion_tokens
        persistent_log.total_tokens = total_tokens
        persistent_log.cache_tokens = cache_tokens
        persistent_log.latency_ms = latency_ms
        persistent_log.upstream_latency_ms = upstream_latency_ms
        persistent_log.cpa_overhead_ms = cpa_overhead_ms
        persistent_log.status = status
        persistent_log.error_message = error_message

        await db.commit()
        return persistent_log

    @staticmethod
    async def record(
        db: AsyncSession,
        api_key_id: int,
        model: Optional[str] = None,
        actual_model: Optional[str] = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int = 0,
        cache_tokens: int = 0,
        latency_ms: int = 0,
        upstream_latency_ms: int = 0,
        cpa_overhead_ms: Optional[int] = None,
        status: str = "success",
        error_message: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Any:
        """
        记录一次 API 调用的用量

        Args:
            db: 数据库会话
            api_key_id: API Key ID
            model: 模型名称
            prompt_tokens: 输入 Token 数
            completion_tokens: 输出 Token 数
            total_tokens: 总 Token 数
            cache_tokens: 缓存命中 Token 数
            latency_ms: 请求耗时（毫秒）
            upstream_latency_ms: 上游耗时（毫秒）
            cpa_overhead_ms: CPA 自身增加的耗时（毫秒）
            status: 状态（success/error/in_progress）
            error_message: 错误信息
            user_id: 发起请求的用户 ID

        Returns:
            UsageLog 记录
        """
        pending_log = await UsageTracker.create_pending_record(db, api_key_id=api_key_id, model=model, actual_model=actual_model, user_id=user_id)
        return await UsageTracker.update_record(
            db=db,
            log=pending_log,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cache_tokens=cache_tokens,
            latency_ms=latency_ms,
            upstream_latency_ms=upstream_latency_ms,
            cpa_overhead_ms=cpa_overhead_ms,
            status=status,
            error_message=error_message,
        )


# 全局实例
usage_tracker = UsageTracker()
