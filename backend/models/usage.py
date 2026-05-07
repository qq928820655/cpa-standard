"""
用量记录数据模型
"""
from datetime import date, datetime
from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class UsageLog(Base):
    """用量记录模型"""
    __tablename__ = "usage_logs"
    __table_args__ = (
        Index("ix_usage_logs_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 关联的 API Key ID
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=False)

    # 发起请求的用户 ID（null 表示通过 master key 直接调用）
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)

    # 使用的模型名称
    model: Mapped[str] = mapped_column(String(100), nullable=True)

    # Token 用量
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # 请求耗时（毫秒）
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    upstream_latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cpa_overhead_ms: Mapped[int] = mapped_column(Integer, default=0)

    # 请求状态：success, error, in_progress
    status: Mapped[str] = mapped_column(String(20), default="success")

    # 错误信息（如果有）
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    # 请求时间
    request_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UsageDailySummary(Base):
    """按天按 Key 的用量汇总模型"""
    __tablename__ = "usage_daily_summaries"
    __table_args__ = (
        UniqueConstraint("summary_date", "api_key_id", name="uq_usage_daily_summaries_date_key"),
        Index("ix_usage_daily_summaries_summary_date", "summary_date"),
        Index("ix_usage_daily_summaries_api_key_id", "api_key_id"),
        Index("ix_usage_daily_summaries_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    api_key_id: Mapped[int] = mapped_column(Integer, ForeignKey("api_keys.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("admin_users.id"), nullable=True)

    total_requests: Mapped[int] = mapped_column(Integer, default=0)
    success_requests: Mapped[int] = mapped_column(Integer, default=0)
    error_requests: Mapped[int] = mapped_column(Integer, default=0)
    in_progress_requests: Mapped[int] = mapped_column(Integer, default=0)

    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)

    latency_sum_ms: Mapped[int] = mapped_column(Integer, default=0)
    latency_count: Mapped[int] = mapped_column(Integer, default=0)
    upstream_latency_sum_ms: Mapped[int] = mapped_column(Integer, default=0)
    upstream_latency_count: Mapped[int] = mapped_column(Integer, default=0)
    cpa_overhead_sum_ms: Mapped[int] = mapped_column(Integer, default=0)
    cpa_overhead_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
