"""
管理员会话模型
"""
from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from .base import Base

# 会话有效期 7 天
SESSION_EXPIRE_DAYS = 7


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    token = Column(String(128), unique=True, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)

    @staticmethod
    def create_token() -> str:
        """生成随机 session token"""
        import secrets
        return secrets.token_urlsafe(48)

    @classmethod
    def new(cls, user_id: int) -> "AdminSession":
        """创建新会话"""
        return cls(
            token=cls.create_token(),
            user_id=user_id,
            expires_at=datetime.utcnow() + timedelta(days=SESSION_EXPIRE_DAYS),
        )

    def is_expired(self) -> bool:
        """判断会话是否过期"""
        return datetime.utcnow() > self.expires_at
