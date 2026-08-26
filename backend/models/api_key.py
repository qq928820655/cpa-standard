"""
API Key 数据模型
"""
from datetime import datetime
from sqlalchemy import String, Boolean, Integer, DateTime, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ApiKey(Base):
    """API Key 模型"""
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_provider_is_active_id", "provider", "is_active", "id"),
        Index("ix_api_keys_provider_id", "provider", "id"),
        Index("ix_api_keys_name_provider", "name", "provider"),
        Index("ix_api_keys_is_active", "is_active"),
        Index("ix_api_keys_name", "name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 名称标识
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # 提供商类型：claude, openai, azure, custom
    provider: Mapped[str] = mapped_column(String(50), nullable=False)

    # API Key（加密存储更安全，此处简化处理）
    api_key: Mapped[str] = mapped_column(Text, nullable=False)

    # API 类型：newapi、sub2api、other；为空按 other 处理
    api_type: Mapped[str] = mapped_column(String(30), nullable=True, default="other")

    # 请求基础地址
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)

    # 是否启用
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # 权重（用于加权轮询，暂时保留）
    weight: Mapped[int] = mapped_column(Integer, default=1)

    # 是否启用独立出口代理
    enable_proxy: Mapped[bool] = mapped_column(Boolean, default=False)

    # 独立出口代理配置
    proxy_url: Mapped[str] = mapped_column(String(500), nullable=True)
    proxy_username: Mapped[str] = mapped_column(Text, nullable=True)
    proxy_password: Mapped[str] = mapped_column(Text, nullable=True)

    # 是否启用伪装 IP 头
    enable_fake_ip: Mapped[bool] = mapped_column(Boolean, default=False)

    # 伪装 IP 头配置
    fake_ip: Mapped[str] = mapped_column(String(64), nullable=True)

    # 支持的模型，JSON 数组；为空表示支持全部模型
    supported_models: Mapped[str] = mapped_column(Text, nullable=True)

    # 备注
    remark: Mapped[str] = mapped_column(Text, nullable=True)

    # 登录密码（用于查询余额等，为空则取系统设置的供应商默认密码）
    password: Mapped[str] = mapped_column(Text, nullable=True)

    # 网页网址（用于余额查询、图片回填等网页访问，为空则取 base_url）
    wz_url: Mapped[str] = mapped_column(String(500), nullable=True)

    # 内容安全违规计数
    security_violation_count: Mapped[int] = mapped_column(Integer, default=0)

    # 最近一次内容安全违规原因
    last_security_violation: Mapped[str] = mapped_column(Text, nullable=True)

    # 生命周期累计用量，不随明细日志清理回退
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_tokens: Mapped[int] = mapped_column(Integer, default=0)

    # 创建时间
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow
    )

    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
