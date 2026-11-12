"""外部 API 图片调用记录（record_external_image_call）测试。

内存 SQLite + 全量模型建表，验证：
- 成功调用落 source=api 任务与 URL 结果
- 只保存上游在线地址，b64 不入库
- 失败调用落 failed 任务与错误摘要
- 命中 Key 摘要随任务落库
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))


async def _make_session():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    import models  # noqa: F401 注册全部模型
    from models.base import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    return engine, maker


def _run(main_coro_factory):
    async def runner():
        engine, maker = await _make_session()
        try:
            async with maker() as session:
                await main_coro_factory(session)
        finally:
            await engine.dispose()
    asyncio.run(runner())


def test_records_api_success_with_urls():
    from routers.proxy import record_external_image_call

    async def main(session):
        started = time.perf_counter()
        await record_external_image_call(
            session,
            {"auth_type": "master", "user_id": None, "supported_models": None},
            source_path="/v1/images/generations",
            model="gpt-image-2",
            prompt="一只在月球上骑车的猫",
            request_params={"model": "gpt-image-2", "size": "1024x1024", "n": 2},
            status_code=200,
            response_data={
                "data": [
                    {"url": "https://r2.example.com/a.png"},
                    {"url": "https://r2.example.com/b.png"},
                ]
            },
            started_at=started,
            key_info={"id": 7, "name": "图片Key", "provider": "openai", "base_url": "https://up.example.com"},
        )
        from sqlalchemy import select
        from models import ImageGenerationTask, ImageGenerationTaskResult

        tasks = (await session.execute(select(ImageGenerationTask))).scalars().all()
        assert len(tasks) == 1
        task = tasks[0]
        assert task.source == "api"
        assert task.status == "success"
        assert task.model == "gpt-image-2"
        assert task.prompt == "一只在月球上骑车的猫"
        assert task.api_key_id == 7
        assert task.api_key_name == "图片Key"
        assert task.provider == "openai"
        assert task.base_url == "https://up.example.com"
        assert task.total_count == 2 and task.success_count == 2
        assert task.error_summary is None
        results = (
            (await session.execute(select(ImageGenerationTaskResult)))
            .scalars().all()
        )
        assert len(results) == 2
        assert all(result.image_url for result in results)
        assert all(not result.image_base64 for result in results)
        assert {result.image_url for result in results} == {
            "https://r2.example.com/a.png",
            "https://r2.example.com/b.png",
        }

    _run(main)


def test_skips_b64_only_results():
    from routers.proxy import record_external_image_call

    async def main(session):
        await record_external_image_call(
            session,
            {"auth_type": "master", "user_id": None, "supported_models": None},
            source_path="/v1/images/generations",
            model="gpt-image-2",
            prompt="p",
            request_params={},
            status_code=200,
            response_data={"data": [{"b64_json": "aGVsbG8="}]},
            started_at=time.perf_counter(),
            key_info={"id": 1, "name": "k", "provider": "", "base_url": ""},
        )
        from sqlalchemy import select
        from models import ImageGenerationTask, ImageGenerationTaskResult

        task = (await session.execute(select(ImageGenerationTask))).scalars().one()
        assert task.status == "success"
        # 只返回 b64 时没有在线地址可记录，结果为空
        results = (await session.execute(select(ImageGenerationTaskResult))).scalars().all()
        assert results == []

    _run(main)


def test_records_failure_with_summary():
    from routers.proxy import record_external_image_call

    async def main(session):
        await record_external_image_call(
            session,
            {"auth_type": "master", "user_id": None, "supported_models": None},
            source_path="/v1/images/generations",
            model="gpt-image-2",
            prompt="p",
            request_params={},
            status_code=500,
            response_data={"error": {"message": "upstream exploded"}},
            started_at=time.perf_counter(),
            key_info=None,
        )
        from sqlalchemy import select
        from models import ImageGenerationTask

        task = (await session.execute(select(ImageGenerationTask))).scalars().one()
        assert task.status == "failed"
        assert task.source == "api"
        assert task.error_count == 1
        assert task.error_summary == "upstream exploded"

    _run(main)
