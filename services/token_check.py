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


async def auth_middleware(request: Request, call_next) -> Response:
    """
    鉴权中间件：
    1. 白名单放行
    2. 优先查内存缓存
    3. 缓存未命中则查数据库
    4. 查库成功后回写缓存
    """

    # 白名单放行 (文档)
    if request.url.path.startswith(("/docs", "/openapi.json", "/redoc")):
        return await call_next(request)

    # 校验凭证 (非 OPTIONS 请求)
    if request.method != "OPTIONS":
        token = request.headers.get(
            "token") or request.query_params.get("token")
        tool_id = request.headers.get(
            "tool_id") or request.query_params.get("tool_id")

        if not token or not tool_id:
            logger.warning(
                "Auth Failed [Missing]: Path=%s, Method=%s, ToolID=%s, TokenPresent=%s",
                request.url.path,
                request.method,
                tool_id or "None",
                "Yes" if token else "No"
            )
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing token_id or tool_id"}
            )

        # 获取缓存实例
        cache = getattr(request.app.state, "token_cache", None)

        token_doc = None

        # --- Step 1: 尝试从缓存获取 ---
        if cache:
            tt = await cache.get(token, tool_id, request)
            token_doc = tt[0] if tt else None
            if token_doc:
                logger.info(
                    "Auth Success [Cache Hit]: Path=%s, ToolID=%s, Token=%s",
                    request.url.path,
                    tool_id,
                    mask_sensitive_data(token)
                )

        # --- Step 2: 缓存未命中，查询数据库 ---
        if not token_doc:
            if tt[1] == 1:  # 数据库连接失败
                logger.error(
                    "Auth Failed [System]: Database connection not available in app.state. Path=%s",
                    request.url.path
                )
                return JSONResponse(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    content={"detail": "Database connection unavailable"}
                )

            if tt[1] == 2:  # 鉴权失败
                logger.warning(
                    "Auth Failed [Invalid]: Path=%s, Method=%s, ToolID=%s, Token=%s",
                    request.url.path,
                    request.method,
                    tool_id,
                    mask_sensitive_data(token)
                )
                return JSONResponse(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    content={"detail": "Invalid token_id or tool_id"}
                )

            if tt[1] == 3:  # 成功
                logger.info(
                    "Auth Success [DB Hit]: Path=%s, Method=%s, ToolID=%s, Token=%s",
                    request.url.path,
                    request.method,
                    tool_id,
                    mask_sensitive_data(token)
                )

            else:
                logger.error(
                    "Auth Failed [Error]: Database query exception. Path=%s, Error=%s",
                    request.url.path,
                    str(tt[1]),
                    exc_info=True
                )
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={"detail": "Internal authentication error"}
                )
        request.state.token_doc = token_doc
        # 存入 state，供后续 dependencies 使用

    return await call_next(request)
