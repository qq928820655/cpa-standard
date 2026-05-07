"""
用量汇总与保留期服务
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy import case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession


REALTIME_RETENTION_DAYS = 7
SUMMARY_RETENTION_DAYS = 90


@dataclass
class TimeRangeWindow:
    summary_start: Optional[datetime]
    summary_end: Optional[datetime]
    realtime_start: Optional[datetime]
    realtime_end: Optional[datetime]


class UsageRollupService:
    """用量汇总与清理服务"""

    @staticmethod
    def get_realtime_boundary(now: Optional[datetime] = None) -> datetime:
        now = now or datetime.utcnow()
        boundary_date = (now - timedelta(days=REALTIME_RETENTION_DAYS)).date()
        return datetime.combine(boundary_date, time.min)

    @staticmethod
    def get_summary_boundary(now: Optional[datetime] = None) -> datetime:
        now = now or datetime.utcnow()
        boundary_date = (now - timedelta(days=SUMMARY_RETENTION_DAYS)).date()
        return datetime.combine(boundary_date, time.min)

    @staticmethod
    def normalize_time_range(
        days: int,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        *,
        now: Optional[datetime] = None,
    ) -> tuple[datetime, datetime]:
        now = now or datetime.utcnow()
        normalized_end = end_time or now
        normalized_start = start_time or (normalized_end - timedelta(days=days))
        if normalized_start > normalized_end:
            normalized_start, normalized_end = normalized_end, normalized_start
        return normalized_start, normalized_end

    @classmethod
    def split_time_range(
        cls,
        days: int,
        start_time: Optional[datetime],
        end_time: Optional[datetime],
        *,
        now: Optional[datetime] = None,
    ) -> TimeRangeWindow:
        normalized_start, normalized_end = cls.normalize_time_range(days, start_time, end_time, now=now)
        realtime_boundary = cls.get_realtime_boundary(now)
        summary_boundary = cls.get_summary_boundary(now)

        summary_start = None
        summary_end = None
        if normalized_start < realtime_boundary:
            summary_start = max(normalized_start, summary_boundary)
            summary_end = min(normalized_end, realtime_boundary)
            if summary_start >= summary_end:
                summary_start = None
                summary_end = None

        realtime_start = None
        realtime_end = None
        if normalized_end > realtime_boundary:
            realtime_start = max(normalized_start, realtime_boundary)
            realtime_end = normalized_end
            if realtime_start >= realtime_end:
                realtime_start = None
                realtime_end = None

        return TimeRangeWindow(
            summary_start=summary_start,
            summary_end=summary_end,
            realtime_start=realtime_start,
            realtime_end=realtime_end,
        )

    @staticmethod
    def clamp_logs_start(start_time: Optional[datetime], *, now: Optional[datetime] = None) -> datetime:
        boundary = UsageRollupService.get_realtime_boundary(now)
        if start_time is None:
            return boundary
        return max(start_time, boundary)

    @classmethod
    async def rebuild_recent_summaries(cls, db: AsyncSession, *, now: Optional[datetime] = None):
        from models import UsageDailySummary, UsageLog

        now = now or datetime.utcnow()
        summary_start = cls.get_summary_boundary(now).date()
        summary_end = cls.get_realtime_boundary(now).date()

        await db.execute(
            delete(UsageDailySummary).where(
                UsageDailySummary.summary_date >= summary_start,
                UsageDailySummary.summary_date <= summary_end,
            )
        )

        query = (
            select(
                func.date(UsageLog.request_time).label("summary_date"),
                UsageLog.api_key_id.label("api_key_id"),
                UsageLog.user_id.label("user_id"),
                func.count(UsageLog.id).label("total_requests"),
                func.sum(case((UsageLog.status == "success", 1), else_=0)).label("success_requests"),
                func.sum(case((UsageLog.status == "error", 1), else_=0)).label("error_requests"),
                func.sum(case((UsageLog.status == "in_progress", 1), else_=0)).label("in_progress_requests"),
                func.coalesce(func.sum(UsageLog.total_tokens), 0).label("total_tokens"),
                func.coalesce(func.sum(UsageLog.prompt_tokens), 0).label("prompt_tokens"),
                func.coalesce(func.sum(UsageLog.completion_tokens), 0).label("completion_tokens"),
                func.coalesce(func.sum(UsageLog.latency_ms), 0).label("latency_sum_ms"),
                func.coalesce(func.sum(case((UsageLog.latency_ms > 0, 1), else_=0)), 0).label("latency_count"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, UsageLog.upstream_latency_ms), else_=0)), 0).label("upstream_latency_sum_ms"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, 1), else_=0)), 0).label("upstream_latency_count"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, UsageLog.cpa_overhead_ms), else_=0)), 0).label("cpa_overhead_sum_ms"),
                func.coalesce(func.sum(case((UsageLog.upstream_latency_ms > 0, 1), else_=0)), 0).label("cpa_overhead_count"),
            )
            .where(UsageLog.request_time < cls.get_realtime_boundary(now))
            .where(UsageLog.request_time >= cls.get_summary_boundary(now))
            .group_by(func.date(UsageLog.request_time), UsageLog.api_key_id, UsageLog.user_id)
        )

        result = await db.execute(query)
        rows = result.all()
        if rows:
            db.add_all([
                UsageDailySummary(
                    summary_date=datetime.strptime(str(row.summary_date), "%Y-%m-%d").date(),
                    api_key_id=row.api_key_id,
                    user_id=getattr(row, "user_id", None),
                    total_requests=row.total_requests or 0,
                    success_requests=row.success_requests or 0,
                    error_requests=row.error_requests or 0,
                    in_progress_requests=row.in_progress_requests or 0,
                    total_tokens=row.total_tokens or 0,
                    prompt_tokens=row.prompt_tokens or 0,
                    completion_tokens=row.completion_tokens or 0,
                    latency_sum_ms=row.latency_sum_ms or 0,
                    latency_count=row.latency_count or 0,
                    upstream_latency_sum_ms=row.upstream_latency_sum_ms or 0,
                    upstream_latency_count=row.upstream_latency_count or 0,
                    cpa_overhead_sum_ms=row.cpa_overhead_sum_ms or 0,
                    cpa_overhead_count=row.cpa_overhead_count or 0,
                )
                for row in rows
            ])

        await db.commit()

    @staticmethod
    async def cleanup_old_data(db: AsyncSession, *, now: Optional[datetime] = None):
        from models import UsageDailySummary, UsageLog

        now = now or datetime.utcnow()
        await db.execute(
            delete(UsageLog).where(UsageLog.request_time < UsageRollupService.get_realtime_boundary(now))
        )
        await db.execute(
            delete(UsageDailySummary).where(UsageDailySummary.summary_date < UsageRollupService.get_summary_boundary(now).date())
        )
        await db.commit()

    @classmethod
    async def maintain(cls, db: AsyncSession, *, now: Optional[datetime] = None):
        now = now or datetime.utcnow()
        await cls.rebuild_recent_summaries(db, now=now)
        await cls.cleanup_old_data(db, now=now)


usage_rollup_service = UsageRollupService()
