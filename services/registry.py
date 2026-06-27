"""配置注册中心 - 管理从 MongoDB 加载的 MCP Server 配置缓存"""
import asyncio
import logging
from typing import Callable, Dict, List, Optional, Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from core.config import settings
from core.logging import get_logger
from models.schemas import RefreshResult, ToolRegistration

logger = get_logger(__name__)


class ToolRegistry:
    """配置注册中心 - 管理从 MongoDB 加载的 MCP Server 配置缓存

    内部使用 dict[str, ToolRegistration] 按 mcp_name 分组缓存所有记录，
    对外查询接口仅暴露 enabled=True 的配置。
    """

    def __init__(self) -> None:
        self._cache: Dict[str, ToolRegistration] = {}
        self._change_stream_task: Optional[asyncio.Task] = None
        self._change_callbacks: List[Callable[[], Any]] = []

    def add_change_callback(self, callback: Callable[[], Any]) -> None:
        """添加配置变化回调函数"""
        self._change_callbacks.append(callback)

    async def _notify_change_callbacks(self) -> None:
        """通知所有回调函数配置已变化"""
        for callback in self._change_callbacks:
            try:
                res = callback()
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error("配置变化回调执行失败: %s", e)

    async def start_change_stream(self, db: AsyncIOMotorDatabase) -> None:
        """启动 MongoDB Change Stream 监听配置变化"""
        if self._change_stream_task is not None:
            logger.warning("Change Stream 已在运行")
            return

        collection = db[settings.collection_name]

        async def watch_changes():
            try:
                async with collection.watch() as change_stream:
                    logger.info("开始监听 MongoDB 配置变化")
                    async for change in change_stream:
                        logger.info("检测到配置变化: %s", change.get("operationType"))
                        await self.load_from_db(db)
                        await self._notify_change_callbacks()
            except Exception as e:
                # MongoDB 没开 ReplicaSet 时，watch() 会报错，这里 catch 住以免挂起应用
                logger.warning("Change Stream 监听失败 (若未开启副本集可能不支持): %s", e)

        self._change_stream_task = asyncio.create_task(watch_changes())

    async def stop_change_stream(self) -> None:
        """停止 Change Stream 监听"""
        if self._change_stream_task is not None:
            self._change_stream_task.cancel()
            try:
                await self._change_stream_task
            except asyncio.CancelledError:
                pass
            self._change_stream_task = None
            logger.info("Change Stream 已停止")

    async def load_from_db(self, db: AsyncIOMotorDatabase) -> None:
        """从 MongoDB 加载所有 ToolRegistration 并缓存到内存"""
        collection = db[settings.collection_name]
        new_cache: Dict[str, ToolRegistration] = {}

        async for doc in collection.find():
            registration = ToolRegistration(**doc)
            new_cache[registration.mcp_name] = registration

        self._cache = new_cache
        logger.info("配置加载完成：共 %d 条记录，已启用 %d 条",
                    len(self._cache),
                    sum(1 for r in self._cache.values() if r.enabled))

    def get_config_by_mcp_name(self, mcp_name: str) -> Optional[ToolRegistration]:
        registration = self._cache.get(mcp_name)
        if registration is None or not registration.enabled:
            return None
        return registration

    def is_enabled(self, mcp_name: str) -> bool:
        registration = self._cache.get(mcp_name)
        return registration is not None and registration.enabled

    def get_all_mcp_names(self) -> List[str]:
        return [name for name, reg in self._cache.items() if reg.enabled]

    async def refresh(self, db: AsyncIOMotorDatabase) -> RefreshResult:
        """重新加载配置，替换内存缓存，返回刷新结果"""
        await self.load_from_db(db)

        enabled = [r for r in self._cache.values() if r.enabled]
        disabled_count = len(self._cache) - len(enabled)

        return RefreshResult(
            total_loaded=len(self._cache),
            enabled_count=len(enabled),
            disabled_count=disabled_count,
            mcp_names=[r.mcp_name for r in enabled]
        )
