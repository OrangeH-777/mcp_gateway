"""Pydantic 数据模型 - 定义网关核心数据结构"""
from typing import Annotated, List, Optional
from bson import ObjectId
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _validate_object_id(v: str | ObjectId) -> str:
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, str):
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId format")
        return v
    raise ValueError("ObjectId must be string or ObjectId")


ObjectIdStr = Annotated[str, BeforeValidator(_validate_object_id)]


class McpEndpointConfig(BaseModel):
    """MCP Server 的远端端点配置"""
    # 兼容历史字段 'server_url' (作为别名)，对外使用 'url'
    url: str = Field(alias="server_url")
    tool_name: str
    rate_limit: int | None = None
    model_config = ConfigDict(populate_by_name=True)


class ToolRegistration(BaseModel):
    """MCP Server 注册记录 - MongoDB 文档模型"""
    model_config = ConfigDict(populate_by_name=True)
    tool_id: str
    mcp_name: str = Field(alias="name")
    mcp_endpoint: McpEndpointConfig
    enabled: bool = True
    timeout_seconds: int = 30


class RefreshResult(BaseModel):
    """刷新操作结果"""
    total_loaded: int
    enabled_count: int
    disabled_count: int
    mcp_names: List[str]


class HealthStatus(BaseModel):
    """健康检查响应"""
    status: str
    mongodb_connected: bool
    registered_count: int
    mcp_names: List[str]
