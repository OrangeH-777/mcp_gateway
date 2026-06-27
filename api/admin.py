"""管理端点 - 提供配置刷新和健康检查接口"""
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.dependencies import get_db, get_registry, verify_user_token
from core.logging import get_logger
from models.schemas import HealthStatus, RefreshResult
from services.registry import ToolRegistry

logger = get_logger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health", response_model=HealthStatus)
async def health_check(
    registry: Annotated[ToolRegistry, Depends(get_registry)],
    db: Annotated[AsyncIOMotorDatabase, Depends(get_db)],
) -> HealthStatus:
    """健康检查端点 (中间件会拦截它，测试用例会验证 401 拦截)"""
    mongodb_connected = True
    try:
        await db.command("ping")
    except Exception as e:
        logger.warning("MongoDB 连接检查失败: %s", e)
        mongodb_connected = False

    mcp_names = registry.get_all_mcp_names()

    return HealthStatus(
        status="healthy" if mongodb_connected else "degraded",
        mongodb_connected=mongodb_connected,
        registered_count=len(mcp_names),
        mcp_names=mcp_names,
    )
