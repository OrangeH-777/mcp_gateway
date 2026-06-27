"""依赖注入 - 统一管理 FastAPI 依赖项"""
import logging
from typing import Any, Dict

from fastapi import HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from core.logging import get_logger
from services.registry import ToolRegistry

logger = get_logger(__name__)


def get_registry(request: Request) -> ToolRegistry:
    """获取工具注册中心实例（从 app.state 注入）"""
    return request.app.state.registry


def get_db(request: Request) -> AsyncIOMotorDatabase:
    """获取 MongoDB 数据库实例（从 app.state 注入）"""
    return request.app.state.db


async def verify_user_token(request: Request) -> Dict[str, Any]:
    """从 request.state 提取鉴权信息（auth_middleware 已完成验证）"""
    token_doc = getattr(request.state, "token_doc", None)
    if not token_doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authentication credentials",
        )
    return token_doc
