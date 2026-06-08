"""
号池管理器 - 轮询调度
"""
import json
import random
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Any
from sqlalchemy import select, func, or_
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
            "cloudflare_524_auto_continue_providers": [],
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
        cloudflare_524_auto_continue_providers: Optional[list[str]] = None,
    ):
        providers = []
        if isinstance(cloudflare_524_auto_continue_providers, list):
            seen = set()
            for provider in cloudflare_524_auto_continue_providers:
                provider_value = str(provider or "").strip()
                if provider_value and provider_value not in seen:
                    seen.add(provider_value)
                    providers.append(provider_value)

        self._cooldown_config = {
            "rate_limit_cooldown_seconds": max(int(rate_limit_cooldown_seconds), 0),
            "auth_failure_cooldown_seconds": max(int(auth_failure_cooldown_seconds), 0),
            "upstream_error_cooldown_seconds": max(int(upstream_error_cooldown_seconds), 0),
            "cloudflare_524_auto_continue_providers": providers,
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

    def is_cloudflare_524_auto_continue_enabled(self, provider: Optional[str]) -> bool:
        provider_value = str(provider or "").strip()
        if not provider_value:
            return False
        return provider_value in set(self._cooldown_config.get("cloudflare_524_auto_continue_providers") or [])

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
        providers: Optional[List[str]] = None,
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
        plan = await self.build_model_match_plan(db, model, providers=providers or ([provider] if provider else None))
        if not self.is_key_available_for_model_plan(
            key,
            model,
            plan,
            exclude_key_ids,
            provider=provider or (providers[0] if providers and len(providers) == 1 else None),
        ):
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

    async def build_model_match_plan(
        self,
        db: AsyncSession,
        model: Optional[str],
        providers: Optional[List[str]] = None,
    ) -> dict[str, Any]:
        """构建系统模型映射匹配计划"""
        normalized_models = self._normalize_model_names([model] if model else [])
        request_model = normalized_models[0] if normalized_models else None
        request_normalized = request_model.lower() if request_model else ""
        provider_values = self._normalize_model_names(providers)

        plan = {
            "request_model": request_model,
            "request_normalized": request_normalized,
            "mode": "plain",
            "direct_model": request_model,
            "provider_models": {},
        }
        if not request_normalized:
            return plan

        from models import ProviderModelMapping

        query = select(ProviderModelMapping).where(
            ProviderModelMapping.enabled == True,
            or_(
                ProviderModelMapping.provider_model_normalized == request_normalized,
                ProviderModelMapping.real_model_normalized == request_normalized,
            ),
        )
        if provider_values:
            query = query.where(ProviderModelMapping.provider.in_(provider_values))

        result = await db.execute(query)
        mappings = list(result.scalars().all())
        provider_hits = [
            item for item in mappings
            if (item.provider_model_normalized or "").lower() == request_normalized
        ]
        if provider_hits:
            plan["mode"] = "provider_model"
            plan["direct_model"] = None
            for item in provider_hits:
                plan["provider_models"].setdefault(item.provider, set()).add(item.provider_model)
            return plan

        real_hits = [
            item for item in mappings
            if (item.real_model_normalized or "").lower() == request_normalized
        ]
        if real_hits:
            plan["mode"] = "real_model"
            for item in real_hits:
                plan["provider_models"].setdefault(item.provider, set()).add(item.provider_model)
        return plan

    def key_matches_model_plan(self, key: Any, model: Optional[str], plan: Optional[dict[str, Any]]) -> bool:
        """判断 Key 是否匹配系统模型映射计划"""
        if not plan:
            return self.key_supports_model(key, model)
        provider = getattr(key, "provider", None)
        provider_models = plan.get("provider_models") or {}
        for provider_model in provider_models.get(provider, set()):
            if self.key_supports_model(key, provider_model):
                return True
        direct_model = plan.get("direct_model")
        if direct_model:
            return self.key_supports_model(key, direct_model)
        return False

    def resolve_upstream_model_for_key(self, key: Any, model: Optional[str], plan: Optional[dict[str, Any]]) -> Optional[str]:
        """根据匹配计划解析选中 Key 的上游模型"""
        if not plan:
            return model
        provider = getattr(key, "provider", None)
        provider_models = plan.get("provider_models") or {}
        for provider_model in provider_models.get(provider, set()):
            if self.key_supports_model(key, provider_model):
                return self.resolve_model_for_key(key, provider_model)
        return self.resolve_model_for_key(key, plan.get("direct_model") or model)

    def resolve_model_for_key(self, key: Any, model: Optional[str]) -> Optional[str]:
        """若 Key 仅支持基础模型，则去掉请求模型中的 [...] 后缀后转发。"""
        normalized_models = self._normalize_model_names([model] if model else [])
        if not normalized_models:
            return model
        supported_models = self._parse_supported_models(getattr(key, "supported_models", None))
        if not supported_models:
            return model
        request_model = normalized_models[0]
        request_lower = request_model.lower()
        base_model = self._strip_model_suffix(request_model) or request_model
        base_lower = base_model.lower()
        supported_lookup = {item.lower(): item for item in supported_models}
        if request_lower in supported_lookup:
            return request_model
        if base_lower in supported_lookup:
            return supported_lookup[base_lower]
        return model

    def is_key_available_for_model_plan(
        self,
        key: Any,
        model: Optional[str],
        plan: Optional[dict[str, Any]],
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
        return self.key_matches_model_plan(key, model, plan)

    def build_model_plan_cache_key(
        self,
        provider: Optional[str],
        providers: Optional[List[str]],
        model: Optional[str],
        plan: Optional[dict[str, Any]],
    ) -> str:
        """构建模型映射轮询缓存键"""
        provider_part = provider or ",".join(self._normalize_model_names(providers)) or "__all__"
        model_part = self._normalize_model_names([model])[0].lower() if self._normalize_model_names([model]) else "__all__"
        plan_mode = (plan or {}).get("mode", "plain")
        mapped = []
        for item_provider, item_models in sorted(((plan or {}).get("provider_models") or {}).items()):
            mapped.append(f"{item_provider}:{','.join(sorted(m.lower() for m in item_models))}")
        mapped_part = "|".join(mapped)
        return f"{provider_part}::{model_part}::{plan_mode}::{mapped_part}"

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
        plan = await self.build_model_match_plan(db, model, providers=[provider] if provider else None)
        if not self.is_key_available_for_model_plan(key, model, plan, exclude_key_ids, provider=provider):
            return None
        return key

    def _strip_model_suffix(self, model: Optional[str]) -> Optional[str]:
        if not isinstance(model, str):
            return model
        import re as _re
        return _re.sub(r'\[.*?\]', '', model).strip()

    def key_supports_model(self, key: Any, model: Optional[str]) -> bool:
        """判断 Key 是否支持指定模型。
        匹配时会去掉模型名中的 [...] 后缀（如 [1m]、[128k]），
        使 Key 只需配置基础模型名即可匹配带后缀的请求。
        """
        normalized_models = self._normalize_model_names([model] if model else [])
        if not normalized_models:
            return True

        supported_models = self._parse_supported_models(getattr(key, "supported_models", None))
        if not supported_models:
            return True

        request_model = normalized_models[0].lower()
        request_model_base = (self._strip_model_suffix(request_model) or "").lower()

        supported_lookup = {item.lower() for item in supported_models}
        # 先精确匹配，再匹配去掉后缀的基础名
        return request_model in supported_lookup or request_model_base in supported_lookup

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
        providers: Optional[List[str]] = None,
        key_name: Optional[str] = None,
        exclude_providers: Optional[List[str]] = None,
        trace_context: Optional[Any] = None,
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
        provider_values = self._normalize_model_names(providers)
        excluded_provider_values = set(self._normalize_model_names(exclude_providers))
        single_filter_provider = provider or (provider_values[0] if provider_values and len(provider_values) == 1 else None)
        self._prune_expired_cooldowns()
        self._prune_expired_session_bindings()

        if trace_context:
            trace_context.set_route("key_selection", {
                "provider": provider,
                "providers": provider_values,
                "key_name": key_name,
                "model": model,
                "exclude_key_ids": sorted(excluded_ids),
                "exclude_providers": sorted(excluded_provider_values),
                "candidate_count": 0,
                "eligible_count": 0,
                "skipped": [],
                "selected": None,
                "selected_reason": None,
            })

        if prefer_bound_key and sticky_session_key:
            bound_key = await self.get_bound_key(
                db,
                sticky_session_key,
                provider=provider,
                model=model,
                exclude_key_ids=list(excluded_ids),
                providers=providers,
            )
            if bound_key:
                if trace_context:
                    trace_context.route_summary.setdefault("key_selection", {})["selected"] = {
                        "api_key_id": getattr(bound_key, "id", None),
                        "provider": getattr(bound_key, "provider", None),
                        "key_name": getattr(bound_key, "name", None),
                    }
                    trace_context.route_summary.setdefault("key_selection", {})["selected_reason"] = "sticky_binding"
                return bound_key

        query = select(ApiKey).where(ApiKey.is_active == True)
        if provider:
            query = query.where(ApiKey.provider == provider)
        elif providers:
            query = query.where(ApiKey.provider.in_(providers))
        if exclude_providers:
            query = query.where(ApiKey.provider.notin_(exclude_providers))
        if key_name:
            query = query.where(ApiKey.name == key_name)
        query = query.order_by(ApiKey.id)

        plan = await self.build_model_match_plan(db, model, providers=provider_values or ([provider] if provider else None))
        if trace_context:
            explain_query = select(ApiKey).order_by(ApiKey.id)
            explain_result = await db.execute(explain_query)
            explain_items = []
            eligible_ids = set()
            for key in explain_result.scalars().all():
                reason = None
                key_provider = getattr(key, "provider", None)
                if not getattr(key, "is_active", False):
                    reason = "inactive"
                elif provider and key_provider != provider:
                    reason = "provider_mismatch"
                elif provider_values and key_provider not in provider_values:
                    reason = "provider_mismatch"
                elif excluded_provider_values and key_provider in excluded_provider_values:
                    reason = "excluded_provider"
                elif key_name and getattr(key, "name", None) != key_name:
                    reason = "key_name_mismatch"
                elif key.id in excluded_ids:
                    reason = "excluded_key"
                elif self.is_key_cooled_down(key.id):
                    reason = "cooldown"
                elif self._get_key_weight(key) <= 0:
                    reason = "zero_weight"
                elif not self.key_matches_model_plan(key, model, plan):
                    reason = "model_not_supported"
                else:
                    eligible_ids.add(key.id)

                if reason:
                    explain_items.append({
                        "api_key_id": getattr(key, "id", None),
                        "provider": key_provider,
                        "key_name": getattr(key, "name", None),
                        "reason": reason,
                    })

            key_selection = trace_context.route_summary.setdefault("key_selection", {})
            key_selection["candidate_count"] = len(eligible_ids) + len(explain_items)
            key_selection["eligible_count"] = len(eligible_ids)
            key_selection["skipped"] = explain_items[:80]
            key_selection["skipped_truncated"] = len(explain_items) > 80
        result = await db.execute(query)
        keys: List[Any] = [
            key for key in result.scalars().all()
            if self.is_key_available_for_model_plan(
                key,
                model,
                plan,
                list(excluded_ids),
                provider=single_filter_provider,
            )
        ]

        if trace_context:
            key_selection = trace_context.route_summary.setdefault("key_selection", {})
            key_selection["eligible_count"] = len(keys)

        if not keys:
            return None

        cache_key = self.build_model_plan_cache_key(provider, providers, model, plan)
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

        if trace_context:
            key_selection = trace_context.route_summary.setdefault("key_selection", {})
            key_selection["selected"] = {
                "api_key_id": getattr(selected_key, "id", None),
                "provider": getattr(selected_key, "provider", None),
                "key_name": getattr(selected_key, "name", None),
            }
            key_selection["selected_reason"] = "weighted_round_robin"

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
