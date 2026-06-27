'''针对token使用工具调用的频率进行限制'''

import logging
from fastapi import Request, Response, status
from fastapi.responses import JSONResponse

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)


def mask_sensitive_data(data: str) -> str:
    """简单的脱敏函数"""
    if not data or len(data) <= 8:
        return "***"
    return f"{data[:4]}...{data[-4:]}"


async def limit_check(request: Request):
    """
    鉴权中间件：
    1. 白名单放行
    2. 优先查内存缓存
    3. 缓存未命中则查数据库
    4. 查库成功后回写缓存
    """

    # 校验凭证 (非 OPTIONS 请求)
    token = request.headers.get(
        "token") or request.query_params.get("token")
    tool_id = request.headers.get(
        "tool_id") or request.query_params.get("tool_id")
    # 获取缓存实例
    cache = getattr(request.app.state, "time_limit_cache", None)

    limit_doc = None
    # --- Step 1: 尝试从缓存获取 ---
    if cache:
        tt = await cache.limit_cache_get(token, tool_id, request)
        limit_doc = tt[0] if tt else None
        if limit_doc:
            max_limit = limit_doc.get("rate_limit_override")
            if max_limit == -1:
                logger.info(
                    "No Rate Limit [Cache Hit]: Path=%s, ToolID=%s, Token=%s",
                    request.url.path,
                    tool_id,
                    mask_sensitive_data(token)
                )
                return 0
            if max_limit == None:

                db = getattr(request.app.state, "db", None)
                doc = await db[settings.collection_name].find_one(
                    {"tool_id": tool_id}
                )
                max_limit = doc.get("mcp_endpoint", {}).get("rate_limit")

                if max_limit == None:
                    logger.info(
                        "No Rate Limit [DB Hit]: Path=%s, ToolID=%s, Token=%s",
                        request.url.path,
                        tool_id,
                        mask_sensitive_data(token)
                    )
                    return 0

                else:
                    await db[settings.token_collection_name].update_one(
                        {"token": token, "tool_id": tool_id},
                        {"$set": {"rate_limit_override": max_limit}}
                    )

            if tt[1] > max_limit:
                logger.warning(
                    "Rate Limit Exceeded [Cache Hit]: Path=%s, ToolID=%s, Token=%s",
                    request.url.path,
                    tool_id,
                    mask_sensitive_data(token)
                )
                return 1
            else:
                logger.info("Rate limit check passed[Cache Hit]: %s/%s",
                            # 调用次数占比
                            tt[1], max_limit if max_limit > 0 else 0)
                return 0
        else:
            if not tt or len(tt) < 2:
                return 1
            max_limit = tt[1].get(
                "rate_limit_override")
            if max_limit == -1:
                logger.info(
                    "No Rate Limit [DB Hit]: Path=%s, ToolID=%s, Token=%s",
                    request.url.path,
                    tool_id,
                    mask_sensitive_data(token)
                )
                return 0
            if max_limit == None:

                db = getattr(request.app.state, "db", None)
                doc = await db[settings.collection_name].find_one(
                    {"tool_id": tool_id}
                )
                max_limit = doc.get("mcp_endpoint", {}).get("rate_limit")
                # mcp_endpoint.rate_limit

                if max_limit == None:
                    logger.info(
                        "No Rate Limit [DB Hit]: Path=%s, ToolID=%s, Token=%s",
                        request.url.path,
                        tool_id,
                        mask_sensitive_data(token)
                    )
                    return 0

                else:
                    await db[settings.token_collection_name].update_one(
                        {"token": token, "tool_id": tool_id},
                        {"$set": {"rate_limit_override": max_limit}}
                    )

            logger.info("Rate limit check passed[DB Hit]: %s/%s",
                        # 调用次数占比
                        1, max_limit if max_limit > 0 else 0)

            return 0

    return 1
