"""FastAPI 应用入口 - 生命周期管理与路由注册"""
from api.mcp import setup_mcp_routes
import contextlib
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator
from fastapi import FastAPI, Request, Response
from motor.motor_asyncio import AsyncIOMotorClient
from api.admin import router as admin_router
from core.config import settings
from core.logging import configure_logging, get_logger
from services.registry import ToolRegistry
from core.cache import TokenCache
from services.token_check import auth_middleware

configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # A. 初始化数据库
    logger.info("正在连接 MongoDB: %s", settings.mongodb_uri)
    client = AsyncIOMotorClient(settings.mongodb_uri)
    db = client[settings.database_name]

    try:
        await db.command("ping")
        logger.info("MongoDB 连接成功")
    except Exception as e:
        logger.error("MongoDB 连接失败：%s", e)
        sys.exit(1)

    # B. 初始化内存缓存
    token_cache = TokenCache(default_ttl=300)
    #  5 分钟过期时间，1分钟清理一次（已过期get到删除）
    time_limit_cache = TokenCache(default_ttl=60, cleanup_interval=300)
    # 1分钟过期时间，5分钟清理一从（已过期get到重置）
    await token_cache.start_background_cleanup()
    await time_limit_cache.start_background_cleanup()
    app.state.token_cache = token_cache
    app.state.time_limit_cache = time_limit_cache
    logger.info("内存缓存初始化完成")

    # C. 初始化业务逻辑
    registry = ToolRegistry()
    await registry.load_from_db(db)
    logger.info("当前已启用: %s", registry.get_all_mcp_names())

    async def on_config_change():
        """配置变更回调：刷新 registry 缓存，url/enabled 变更立即生效
        注意：新增或删除 MCP Server 需要重启网关才能生效
        """
        logger.info("配置发生变化，正在刷新注册中心缓存")
        await registry.load_from_db(db)
        logger.info("缓存刷新完成，当前已启用: %s", registry.get_all_mcp_names())

    registry.add_change_callback(on_config_change)

    # D. 注入 State
    app.state.registry = registry
    app.state.db = db
    app.state.client = client

    # E. 注册通配 MCP 路由（只需一次，热更新时无需重新注册）
    setup_mcp_routes(app, registry)

    await registry.start_change_stream(db)

    yield

    # 关闭逻辑
    logger.info("正在关闭网关，停止 Change Stream、缓存任务并断开 MongoDB 连接")

    # 1. 停止缓存清理任务
    if hasattr(app.state, 'token_cache'):
        await app.state.token_cache.stop()
    if hasattr(app.state, 'time_limit_cache'):
        await app.state.time_limit_cache.stop()
    # 2. 停止数据库监听
    await registry.stop_change_stream()

    # 3. 关闭数据库连接
    client.close()
    logger.info("资源释放完毕")


def create_app() -> FastAPI:
    app = FastAPI(
        title="MCP 统一调用网关",
        description="基于 FastAPI 的 MCP Server 代理服务",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(admin_router)

    # 注册鉴权中间件
    @app.middleware("http")
    async def auth_wrapper(request: Request, call_next):
        return await auth_middleware(request, call_next)

    # 注册日志中间件
    @app.middleware("http")
    async def log_requests(request: Request, call_next) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        elapsed = (time.monotonic() - start) * 1000
        logger.info("%s %s -> %d (%.1fms)", request.method,
                    request.url.path, response.status_code, elapsed)
        return response

    return app


app = create_app()
