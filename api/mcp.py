"""MCP 协议路由层 - HTTP 反向代理，完整透传所有请求和响应"""

import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
import asyncio
from services.invocation_stats import record_invocation
from core.logging import get_logger
from services.rate_limit import limit_check
from services.registry import ToolRegistry

logger = get_logger(__name__)


def setup_mcp_routes(app: FastAPI, registry: ToolRegistry) -> None:
    """注册通配 MCP 路由
    直接将 /mcp/{mcp_name}/mcp 的请求反向代理到远端 MCP Server，
    完整透传 headers、body 和 streaming response，不解析任何 MCP 协议内容。
    从 registry 动态读取目标地址，天然支持热更新。
    """

    @app.api_route("/mcp/{mcp_name}/mcp", methods=["GET", "POST", "DELETE"])
    async def mcp_reverse_proxy(mcp_name: str, request: Request):
        """MCP 反向代理端点 - 完整透传到远端 MCP Server"""
        # 从注册中心获取最新配置（热更新后立即生效）
        config = registry.get_config_by_mcp_name(mcp_name)
        if config is None:
            return JSONResponse(
                {"error": f"MCP Server '{mcp_name}' 不存在或未启用"},
                status_code=404,
            )

        target_url = config.mcp_endpoint.url
        timeout = config.timeout_seconds

        # 读取请求 body
        body = await request.body()

        # 透传请求 headers，去掉 host 避免冲突
        headers = {
            k: v for k, v in request.headers.items()
            if k.lower() not in ("host", "content-length")
        }

        logger.info("代理请求: %s %s -> %s", request.method,
                    request.url.path, target_url)

        # 解析 JSON-RPC 方法名，用于统计 tools/call 调用次数
        rpc_method = ""
        tool_name = ""
        if request.method == "POST" and body:

            try:
                import json
                rpc = json.loads(body)
                rpc_method = rpc.get("method", "")
                if rpc_method == "tools/call":
                    tool_name = (rpc.get("params") or {}).get(
                        "name", "unknown")
                    logger.info("tools/call: mcp_name=%s, tool=%s",
                                mcp_name, tool_name)
            except Exception:
                pass

        # 创建持久 client，生命周期覆盖整个流式响应
        client = httpx.AsyncClient(timeout=timeout)

        upstream_request = client.build_request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            params=dict(request.query_params),
        )

        upstream_response = await client.send(upstream_request, stream=True)
        content_type = upstream_response.headers.get("content-type", "")
        is_success = upstream_response.status_code < 400

        # tools/call 调用统计：在响应返回后异步写入 MongoDB
        if rpc_method == "tools/call":
            is_limit = await limit_check(request)
            if is_limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded. Please try again later."}
                )
            else:
                pass

            token_doc = getattr(request.state, "token_doc", None)
            token_id = str(token_doc.get("token_id", "anonymous")
                           ) if token_doc else "anonymous"
            user_id = str(token_doc.get("user_id", "anonymous")
                          ) if token_doc else "anonymous"
            db = request.app.state.db

            asyncio.ensure_future(
                record_invocation(
                    db=db,
                    tool_id=config.mcp_endpoint.tool_name,
                    token_id=token_id,
                    user_id=user_id,
                    success=is_success,
                )
            )

        async def stream_response():
            """流式透传响应，结束后关闭连接和 client"""
            try:
                async for chunk in upstream_response.aiter_bytes():
                    yield chunk
            finally:
                await upstream_response.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_response(),
            status_code=upstream_response.status_code,
            headers={
                k: v for k, v in upstream_response.headers.items()
                if k.lower() not in ("transfer-encoding",)
            },
            media_type=content_type or None,
        )
