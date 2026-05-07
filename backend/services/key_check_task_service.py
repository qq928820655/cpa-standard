"""
Key 检测任务服务
"""
import asyncio
import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select

from database import async_session_maker
from models import ApiKey, ApiKeyCheckTask, ApiKeyCheckTaskResult
from services.proxy_service import proxy_service


class KeyCheckTaskService:
    """Key 检测任务服务"""

    def __init__(self):
        self._running_task_ids: set[int] = set()
        self._lock = asyncio.Lock()

    def _build_runtime_error_result(self, target_model: str, error: Exception) -> dict:
        error_message = str(error) or error.__class__.__name__
        return {
            "status": "error",
            "target_model": target_model,
            "response_time_ms": 0,
            "failure_category": proxy_service._classify_check_failure(None, error_message),
            "failure_detail": error_message,
            "address_check": {
                "status": "error",
                "status_code": None,
                "error_message": error_message,
                "response_time_ms": 0,
                "path": "runtime",
                "url": "runtime",
            },
            "model_check": None,
        }

    def _json_dumps(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def _json_loads(self, value: Optional[str], default: Any):
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default

    def _build_error_summary(self, failure_category_stats: dict[str, int]) -> Optional[str]:
        if not failure_category_stats:
            return None
        parts = [f"{key}: {value}" for key, value in sorted(failure_category_stats.items())]
        return "；".join(parts)

    async def create_task(self, db, data, keys: list[Any], models_filter: list[str]) -> ApiKeyCheckTask:
        """创建检测任务与初始结果"""
        providers = []
        if getattr(data, "providers", None):
            providers = [item for item in data.providers if isinstance(item, str) and item.strip()]
        elif getattr(data, "provider", None):
            providers = [data.provider]

        key_ids = [int(key.id) for key in keys]
        target_model = (getattr(data, "target_model", "") or "").strip()
        task = ApiKeyCheckTask(
            scope=data.scope,
            provider=(getattr(data, "provider", None) or None),
            providers_json=self._json_dumps(providers or None),
            models_json=self._json_dumps(models_filter or None),
            is_active=getattr(data, "is_active", None),
            key_ids_json=self._json_dumps(key_ids),
            target_model=target_model,
            status="pending",
            total_count=len(keys),
            completed_count=0,
            success_count=0,
            error_count=0,
        )
        db.add(task)
        await db.flush()

        for key in keys:
            db.add(
                ApiKeyCheckTaskResult(
                    task_id=task.id,
                    api_key_id=int(key.id),
                    name=key.name,
                    provider=key.provider,
                    base_url=key.base_url,
                    target_model=target_model,
                    status="pending",
                    response_time_ms=0,
                )
            )

        await db.commit()
        await db.refresh(task)
        return task

    async def start_task(self, task_id: int):
        """启动后台任务"""
        async with self._lock:
            if task_id in self._running_task_ids:
                return
            self._running_task_ids.add(task_id)
        asyncio.create_task(self._run_task(task_id))

    async def _run_task(self, task_id: int):
        """执行后台检测任务"""
        try:
            async with async_session_maker() as db:
                task = await db.get(ApiKeyCheckTask, task_id)
                if not task:
                    return

                task.status = "running"
                task.started_at = datetime.utcnow()
                task.updated_at = datetime.utcnow()
                await db.commit()

                key_ids = self._json_loads(task.key_ids_json, [])
                if not key_ids:
                    await self._finalize_task(task_id, status="completed")
                    return

                result = await db.execute(
                    select(ApiKey)
                    .where(ApiKey.id.in_(key_ids))
                    .order_by(ApiKey.id.asc())
                )
                keys = list(result.scalars().all())
                target_model = task.target_model

            concurrency = min(10, len(keys))
            semaphore = asyncio.Semaphore(max(concurrency, 1))

            async def run_single_check(key: Any):
                async with semaphore:
                    try:
                        result = await proxy_service.check_key_connectivity_and_model(key, target_model)
                    except Exception as exc:
                        result = self._build_runtime_error_result(target_model, exc)
                    return int(key.id), result

            futures = [asyncio.create_task(run_single_check(key)) for key in keys]
            for future in asyncio.as_completed(futures):
                key_id, result = await future
                await self._save_task_result(task_id, key_id, result)

            await self._finalize_task(task_id, status="completed")
        except Exception as exc:
            await self._finalize_task(task_id, status="failed", runtime_error=str(exc))
        finally:
            async with self._lock:
                self._running_task_ids.discard(task_id)

    async def _save_task_result(self, task_id: int, key_id: int, result: dict):
        """保存单项检测结果并递增任务进度"""
        async with async_session_maker() as db:
            task_result_query = await db.execute(
                select(ApiKeyCheckTaskResult).where(
                    ApiKeyCheckTaskResult.task_id == task_id,
                    ApiKeyCheckTaskResult.api_key_id == key_id,
                )
            )
            task_result = task_result_query.scalar_one_or_none()
            task = await db.get(ApiKeyCheckTask, task_id)
            if not task_result or not task:
                return

            now = datetime.utcnow()
            task_result.status = result.get("status") or "error"
            task_result.response_time_ms = int(result.get("response_time_ms") or 0)
            task_result.failure_category = result.get("failure_category")
            task_result.failure_detail = result.get("failure_detail")
            task_result.address_check_json = self._json_dumps(result.get("address_check") or None)
            task_result.model_check_json = self._json_dumps(result.get("model_check") or None)
            task_result.target_model = result.get("target_model") or task.target_model
            task_result.started_at = task_result.started_at or now
            task_result.finished_at = now
            task_result.updated_at = now

            task.completed_count = int(task.completed_count or 0) + 1
            if task_result.status == "success":
                task.success_count = int(task.success_count or 0) + 1
            else:
                task.error_count = int(task.error_count or 0) + 1
            task.updated_at = now

            await db.commit()

    async def _finalize_task(self, task_id: int, *, status: str, runtime_error: Optional[str] = None):
        """汇总任务结果并更新任务状态"""
        async with async_session_maker() as db:
            task = await db.get(ApiKeyCheckTask, task_id)
            if not task:
                return

            result_query = await db.execute(
                select(ApiKeyCheckTaskResult)
                .where(ApiKeyCheckTaskResult.task_id == task_id)
                .order_by(ApiKeyCheckTaskResult.id.asc())
            )
            items = list(result_query.scalars().all())

            failure_category_stats: dict[str, int] = {}
            provider_stats: dict[str, dict[str, int]] = {}
            model_stats: dict[str, dict[str, int]] = {}
            success_count = 0
            error_count = 0

            for item in items:
                item_status = item.status or "pending"
                provider_key = (item.provider or "unknown").strip() or "unknown"
                model_key = (item.target_model or task.target_model or "unknown").strip() or "unknown"

                provider_bucket = provider_stats.setdefault(provider_key, {"total": 0, "success": 0, "error": 0})
                provider_bucket["total"] += 1
                model_bucket = model_stats.setdefault(model_key, {"total": 0, "success": 0, "error": 0})
                model_bucket["total"] += 1

                if item_status == "success":
                    success_count += 1
                    provider_bucket["success"] += 1
                    model_bucket["success"] += 1
                elif item_status == "error":
                    error_count += 1
                    provider_bucket["error"] += 1
                    model_bucket["error"] += 1
                    category = (item.failure_category or "unknown").strip() or "unknown"
                    failure_category_stats[category] = failure_category_stats.get(category, 0) + 1

            task.status = status
            task.completed_count = len([item for item in items if (item.status or "pending") in {"success", "error"}])
            task.total_count = len(items)
            task.success_count = success_count
            task.error_count = error_count
            task.failure_category_stats_json = self._json_dumps(failure_category_stats or None)
            task.provider_stats_json = self._json_dumps(provider_stats or None)
            task.model_stats_json = self._json_dumps(model_stats or None)
            task.error_summary = runtime_error or self._build_error_summary(failure_category_stats)
            task.finished_at = datetime.utcnow()
            task.updated_at = datetime.utcnow()

            await db.commit()


key_check_task_service = KeyCheckTaskService()
