"""
号池管理器 - 轮询调度
"""
import json
import random
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession


class PoolManager:
    """
    号池管理器
    使用轮询（Round Robin）策略分配 API Key
    """
    _instance = None
    _lock = threading.Lock()
    DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 300
    DEFAULT_AUTH_FAILURE_COOLDOWN_SECONDS = 600
    DEFAULT_UPSTREAM_ERROR_COOLDOWN_SECONDS = 120

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        # 每个 provider 维护独立的轮询索引
        self._indexes: dict[str, int] = {}
        self._cooldowns: dict[int, datetime] = {}
        self._session_bindings: dict[str, dict[str, Any]] = {}
        self._cooldown_config = {
            "rate_limit_cooldown_seconds": self.DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS,
            "auth_failure_cooldown_seconds": self.DEFAULT_AUTH_FAILURE_COOLDOWN_SECONDS,
            "upstream_error_cooldown_seconds": self.DEFAULT_UPSTREAM_ERROR_COOLDOWN_SECONDS,
        }
        self._initialized = True

    def _get_index(self, provider: str) -> int:
        """获取指定 provider 的当前索引"""
        return self._indexes.get(provider, 0)

    def _prune_expired_cooldowns(self, now: Optional[datetime] = None):
        now = now or datetime.utcnow()
        expired_ids = [key_id for key_id, until in self._cooldowns.items() if until <= now]
        for key_id in expired_ids:
            self._cooldowns.pop(key_id, None)

    def _prune_expired_session_bindings(self, now: Optional[datetime] = None):
        now = now or datetime.utcnow()
        expired_keys = [
            session_key
            for session_key, binding in self._session_bindings.items()
            if binding.get("expires_at") and binding["expires_at"] <= now
        ]
        for session_key in expired_keys:
            self._session_bindings.pop(session_key, None)

    def is_key_cooled_down(self, key_id: int, *, now: Optional[datetime] = None) -> bool:
        now = now or datetime.utcnow()
        cooldown_until = self._cooldowns.get(key_id)
        if cooldown_until is None:
            return False
        if cooldown_until <= now:
            self._cooldowns.pop(key_id, None)
            return False
        return True

    def mark_key_cooldown(self, key_id: int, seconds: int):
        if seconds <= 0:
            return
        self._cooldowns[key_id] = datetime.utcnow() + timedelta(seconds=seconds)

    def get_key_cooldown_until(self, key_id: int) -> Optional[datetime]:
        if not self.is_key_cooled_down(key_id):
            return None
        return self._cooldowns.get(key_id)

    def get_key_cooldown_remaining_seconds(self, key_id: int) -> int:
        cooldown_until = self.get_key_cooldown_until(key_id)
        if cooldown_until is None:
            return 0
        remaining = int((cooldown_until - datetime.utcnow()).total_seconds())
        return max(remaining, 0)

    def get_cooldown_config(self) -> dict[str, int]:
        return dict(self._cooldown_config)

    def update_cooldown_config(
        self,
        *,
        rate_limit_cooldown_seconds: int,
        auth_failure_cooldown_seconds: int,
        upstream_error_cooldown_seconds: int,
    ):
        self._cooldown_config = {
            "rate_limit_cooldown_seconds": max(int(rate_limit_cooldown_seconds), 0),
            "auth_failure_cooldown_seconds": max(int(auth_failure_cooldown_seconds), 0),
            "upstream_error_cooldown_seconds": max(int(upstream_error_cooldown_seconds), 0),
        }

    def get_cooldown_seconds_for_status(self, status_code: Optional[int]) -> int:
        if status_code is None:
            return self._cooldown_config["upstream_error_cooldown_seconds"]
        if status_code == 429:
            return self._cooldown_config["rate_limit_cooldown_seconds"]
        if status_code in {401, 403}:
            return self._cooldown_config["auth_failure_cooldown_seconds"]
        if status_code >= 500:
            return self._cooldown_config["upstream_error_cooldown_seconds"]
        return 0

    def clear_key_cooldown(self, key_id: int):
        self._cooldowns.pop(key_id, None)

    def bind_session_to_key(
        self,
        session_key: str,
        api_key_id: int,
        ttl_seconds: int,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ):
        if not session_key or ttl_seconds <= 0:
            return
        self._session_bindings[session_key] = {
            "api_key_id": api_key_id,
            "provider": provider,
            "model": model,
            "expires_at": datetime.utcnow() + timedelta(seconds=ttl_seconds),
        }

    def clear_session_binding(self, session_key: str):
        if not session_key:
            return
        self._session_bindings.pop(session_key, None)

    def get_session_binding_count(self) -> int:
        self._prune_expired_session_bindings()
        return len(self._session_bindings)

    async def get_bound_key(
        self,
        db: AsyncSession,
        session_key: str,
        *,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        exclude_key_ids: Optional[List[int]] = None,
    ) -> Optional[Any]:
        if not session_key:
            return None

        self._prune_expired_session_bindings()
        binding = self._session_bindings.get(session_key)
        if not binding:
            return None

        key_id = binding.get("api_key_id")
        if key_id is None:
            self.clear_session_binding(session_key)
            return None

        key = await self.get_key_by_id(db, key_id)
        if not self.is_key_available_for_model(key, model, exclude_key_ids, provider=provider):
            self.clear_session_binding(session_key)
            return None

        return key

    def _set_index(self, provider: str, index: int):
        """设置指定 provider 的索引"""
        self._indexes[provider] = index

    def _normalize_model_names(self, values: Optional[List[Any]]) -> List[str]:
        if not values:
            return []

        normalized = []
        seen = set()
        for value in values:
            if not isinstance(value, str):
                continue
            item = value.strip()
            if not item:
                continue
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(item)
        return normalized

    def _parse_supported_models(self, raw_value: Optional[str]) -> Optional[list[str]]:
        """解析 Key 支持模型列表；空表示全部支持"""
        if not raw_value:
            return None
        try:
            data = json.loads(raw_value)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, list):
            return None
        models = self._normalize_model_names(data)
        return models or None

    def _get_key_weight(self, key: Any) -> int:
        try:
            weight = int(getattr(key, "weight", 1) or 0)
        except (TypeError, ValueError):
            return 0
        return max(weight, 0)

    def is_key_available_for_model(
        self,
        key: Any,
        model: Optional[str],
        exclude_key_ids: Optional[List[int]] = None,
        *,
        provider: Optional[str] = None,
    ) -> bool:
        excluded_ids = set(exclude_key_ids or [])
        if not key:
            return False
        if not getattr(key, "is_active", False):
            return False
        if provider and getattr(key, "provider", None) != provider:
            return False
        if key.id in excluded_ids:
            return False
        if self.is_key_cooled_down(key.id):
            return False
        if self._get_key_weight(key) <= 0:
            return False
        return self.key_supports_model(key, model)

    async def get_priority_binding(self, db: AsyncSession, provider: Optional[str], model: Optional[str]) -> Optional[Any]:
        normalized_models = self._normalize_model_names([model] if model else [])
        if not provider or not normalized_models:
            return None

        from models import ProviderModelPriority

        normalized_model = normalized_models[0].lower()
        result = await db.execute(
            select(ProviderModelPriority).where(
                ProviderModelPriority.provider == provider,
                ProviderModelPriority.model_normalized == normalized_model,
                ProviderModelPriority.enabled == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_priority_key(
        self,
        db: AsyncSession,
        provider: Optional[str],
        model: Optional[str],
        exclude_key_ids: Optional[List[int]] = None,
    ) -> Optional[Any]:
        binding = await self.get_priority_binding(db, provider, model)
        if not binding:
            return None

        key = await self.get_key_by_id(db, getattr(binding, "key_id", 0))
        if not self.is_key_available_for_model(key, model, exclude_key_ids, provider=provider):
            return None
        return key

    def key_supports_model(self, key: Any, model: Optional[str]) -> bool:
        """判断 Key 是否支持指定模型"""
        normalized_models = self._normalize_model_names([model] if model else [])
        if not normalized_models:
            return True

        supported_models = self._parse_supported_models(getattr(key, "supported_models", None))
        if not supported_models:
            return True

        supported_lookup = {item.lower() for item in supported_models}
        return normalized_models[0].lower() in supported_lookup

    def _select_weighted_key(self, cache_key: str, keys: List[Any], *, randomize_start: bool = False) -> Optional[Any]:
        weighted_keys = []
        total_weight = 0
        for key in keys:
            weight = self._get_key_weight(key)
            if weight <= 0:
                continue
            weighted_keys.append((key, weight))
            total_weight += weight

        if total_weight <= 0:
            return None

        raw_index = self._get_index(cache_key)
        if randomize_start:
            raw_index = (raw_index + random.randint(0, min(total_weight - 1, 49))) % total_weight
        current_index = raw_index % total_weight
        cumulative_weight = 0
        selected_key = None
        for key, weight in weighted_keys:
            cumulative_weight += weight
            if current_index < cumulative_weight:
                selected_key = key
                break

        self._set_index(cache_key, (current_index + 1) % total_weight)
        return selected_key

    async def get_next_key(
        self,
        db: AsyncSession,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        exclude_key_ids: Optional[List[int]] = None,
        sticky_session_key: Optional[str] = None,
        sticky_ttl_seconds: int = 0,
        prefer_bound_key: bool = True,
        randomize_start: bool = False,
    ) -> Optional[Any]:
        """
        获取下一个可用的 API Key（轮询策略）

        Args:
            db: 数据库会话
            provider: 可选，指定提供商类型
            model: 可选，指定模型
            exclude_key_ids: 可选，排除已尝试的 Key ID
            sticky_session_key: 可选，会话粘滞标识
            sticky_ttl_seconds: 可选，会话粘滞 TTL
            prefer_bound_key: 是否优先使用已绑定 Key
            randomize_start: 可选，首次轮询时随机起始位置，避免大量同权重 Key 粘滞

        Returns:
            ApiKey 对象，如果没有可用的 Key 则返回 None
        """
        from models import ApiKey

        excluded_ids = set(exclude_key_ids or [])
        self._prune_expired_cooldowns()
        self._prune_expired_session_bindings()

        if prefer_bound_key and sticky_session_key:
            bound_key = await self.get_bound_key(
                db,
                sticky_session_key,
                provider=provider,
                model=model,
                exclude_key_ids=list(excluded_ids),
            )
            if bound_key:
                return bound_key

        query = select(ApiKey).where(ApiKey.is_active == True)
        if provider:
            query = query.where(ApiKey.provider == provider)
        query = query.order_by(ApiKey.id)

        result = await db.execute(query)
        keys: List[Any] = [
            key for key in result.scalars().all()
            if self.is_key_available_for_model(key, model, list(excluded_ids), provider=provider)
        ]

        if not keys:
            return None

        cache_key = f"{provider or '__all__'}::{self._normalize_model_names([model])[0].lower() if self._normalize_model_names([model]) else '__all__'}"
        selected_key = self._select_weighted_key(cache_key, keys, randomize_start=randomize_start)
        if not selected_key:
            return None

        if sticky_session_key and sticky_ttl_seconds > 0:
            self.bind_session_to_key(
                sticky_session_key,
                selected_key.id,
                sticky_ttl_seconds,
                provider=getattr(selected_key, "provider", None),
                model=model,
            )

        return selected_key

    async def get_all_keys(
        self,
        db: AsyncSession,
        provider: Optional[str] = None,
        providers: Optional[List[str]] = None,
        models: Optional[List[str]] = None,
        active_only: bool = False
    ) -> List[Any]:
        """
        获取所有 API Key

        Args:
            db: 数据库会话
            provider: 可选，指定单个提供商类型
            providers: 可选，指定多个提供商类型
            models: 可选，指定多个模型，命中任一即可
            active_only: 是否只返回启用的 Key

        Returns:
            ApiKey 列表
        """
        from models import ApiKey

        query = select(ApiKey)
        provider_values = [item for item in (providers or []) if item]
        if not provider_values and provider:
            provider_values = [provider]
        if provider_values:
            query = query.where(ApiKey.provider.in_(provider_values))
        if active_only:
            query = query.where(ApiKey.is_active == True)
        query = query.order_by(ApiKey.id)

        result = await db.execute(query)
        keys = list(result.scalars().all())

        model_values = [item for item in (models or []) if item]
        if not model_values:
            return keys

        return [
            key for key in keys
            if any(self.key_supports_model(key, model) for model in model_values)
        ]

    async def get_key_by_id(self, db: AsyncSession, key_id: int) -> Optional[Any]:
        """根据 ID 获取 API Key"""
        from models import ApiKey

        result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
        return result.scalar_one_or_none()

    def reset_index(self, provider: Optional[str] = None):
        """重置轮询索引"""
        if provider:
            prefixes = [provider, f"{provider}::"]
            self._indexes = {
                key: value for key, value in self._indexes.items()
                if not any(key == prefix or key.startswith(prefix) for prefix in prefixes)
            }
            return
        self._indexes.clear()


# 全局单例
pool_manager = PoolManager()
