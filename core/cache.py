import time
import asyncio
from typing import Optional, Dict, Any
import logging
from core.config import settings
from core.logging import get_logger
from fastapi import Request

logger = get_logger(__name__)


class TokenCache:
    def __init__(self, default_ttl: int, cleanup_interval: int = 60):
        """
        初始化内存缓存
        :param default_ttl: 默认缓存存活时间（秒），默认 5 分钟
        :param cleanup_interval: 后台清理线程的运行间隔（秒）
        """
        self._cache: Dict[str, tuple] = {
        }  # 结构: { key: (value, expire_timestamp, use_times) }
        self._default_ttl = default_ttl
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task] = None
        # self.use_times = 0 # 记录使用次数
        self._key_locks: Dict[str, asyncio.Lock] = {}  # 每个 key 一把锁
        self._locks_lock = asyncio.Lock()  # 保护锁字典本身

    async def _get_key_lock(self, key: str) -> asyncio.Lock:
        """获取指定 key 的锁（懒加载）"""
        async with self._locks_lock:
            if key not in self._key_locks:
                self._key_locks[key] = asyncio.Lock()
            return self._key_locks[key]

    def _get_key(self, token: str, tool_id: str) -> str:
        """生成缓存键名"""
        return f"auth:{token}:{tool_id}"

    async def get(self, token: str, tool_id: str, request: Request):
        """获取缓存（如果存在且未过期）"""
        key = self._get_key(token, tool_id)
        key_lock = await self._get_key_lock(key)

        async with key_lock:
            data = self._cache.get(key)  # 获取缓存数据

            if data is None:
                db = getattr(request.app.state, "db", None)
                if db is None:
                    return None, 1

                try:
                    token_doc = await db[settings.token_collection_name].find_one({
                        "token": token,
                        "tool_id": tool_id,
                        "banned": False
                    })
                    if not token_doc:
                        return None, 2

                    self._cache[key] = (token_doc, time.time() +
                                        self._default_ttl, 1)
                    return None, 3

                except Exception as e:
                    return None, e

            value, expire_time, use_times = data  # 获取值、过期时间和使用次数

            # 惰性检查：如果过期了，删除并返回 None
            if time.time() > expire_time:
                del self._cache[key]
                return None

            self._cache[key] = (value, expire_time, use_times)
            return value, use_times

    # 获取调用频率限制缓存（如果存在且未过期）
    async def limit_cache_get(self, token: str, tool_id: str, request: Request):
        """获取缓存（如果存在且未过期）"""
        key = self._get_key(token, tool_id)
        key_lock = await self._get_key_lock(key)

        async with key_lock:
            data = self._cache.get(key)  # 获取缓存数据

            if data is None:
                db = getattr(request.app.state, "db", None)
                limit_doc = await db[settings.token_collection_name].find_one(
                    {"token": token, "tool_id": tool_id})
                self._cache[key] = (limit_doc, time.time() +
                                    self._default_ttl, 1)
                return None, limit_doc

            value, expire_time, use_times = data  # 获取值、过期时间和使用次数

            # 惰性检查：如果过期了，删除并返回 None
            if time.time() > expire_time:
                self._cache[key] = (value, time.time() +
                                    self._default_ttl, 1)  # 重置使用次数
                return value, 1

            use_times += 1
            self._cache[key] = (value, expire_time, use_times)
            return value, use_times

    def delete(self, token: str, tool_id: str):
        """主动删除缓存（用于管理员强制禁用 Token 时）"""
        key = self._get_key(token, tool_id)
        if key in self._cache:
            del self._cache[key]
            logger.info(f"Cache invalidated for key: {key}")

    def clear(self):
        """清空所有缓存"""
        self._cache.clear()

    async def start_background_cleanup(self):
        """启动后台清理任务"""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            logger.info("TokenCache background cleanup task started.")

    async def stop(self):
        """停止后台清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    async def _cleanup_loop(self):
        """定期清理过期的键"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval)
                now = time.time()
                # 找出所有过期的键
                expired_keys = [
                    k for k, (_, exp, _) in self._cache.items() if now > exp]
                for k in expired_keys:
                    key_lock = await self._get_key_lock(k)
                    async with key_lock:
                        del self._cache[k]

                if expired_keys:
                    logger.debug(
                        f"Cleaned up {len(expired_keys)} expired cache entries.")
            except asyncio.CancelledError:
                logger.info("TokenCache cleanup task stopped.")
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup loop: {e}")
