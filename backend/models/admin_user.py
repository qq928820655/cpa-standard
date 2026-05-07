"""
用户模型（管理员 + 普通用户）
"""
import hashlib
import json
import secrets
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from .base import Base


class AdminUser(Base):
    __tablename__ = "admin_users"
    __table_args__ = (
        Index("ix_admin_users_role", "role"),
        Index("ix_admin_users_api_key", "api_key", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    salt = Column(String(64), nullable=False)
    # 用户角色：admin / user
    role = Column(String(20), default="user", nullable=False)
    # 用户专属代理 API Key
    api_key = Column(String(128), unique=True, nullable=True)
    # 该用户可用的模型列表（JSON 数组，null 表示不限制）
    supported_models = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def hash_password(password: str, salt: str) -> str:
        """使用 PBKDF2 哈希密码"""
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            100_000,
        ).hex()

    @staticmethod
    def generate_salt() -> str:
        """生成随机盐"""
        return secrets.token_hex(32)

    def check_password(self, password: str) -> bool:
        """校验密码"""
        return self.hash_password(password, self.salt) == self.password_hash

    def set_password(self, password: str):
        """设置新密码"""
        self.salt = self.generate_salt()
        self.password_hash = self.hash_password(password, self.salt)
        self.updated_at = datetime.utcnow()

    @staticmethod
    def generate_api_key() -> str:
        """生成用户专属代理 API Key"""
        return f"sk-{secrets.token_urlsafe(32)}"

    def get_supported_models(self) -> Optional[list]:
        """解析 supported_models JSON 字段"""
        if not self.supported_models:
            return None
        try:
            models = json.loads(self.supported_models)
            if isinstance(models, list) and models:
                return models
        except (json.JSONDecodeError, TypeError):
            pass
        return None

    @property
    def is_admin(self) -> bool:
        """是否为管理员"""
        return self.role == "admin"
