"""MCP 调用统计服务 - 按天聚合写入 MongoDB"""

from datetime import datetime, UTC, timezone, timedelta

from motor.motor_asyncio import AsyncIOMotorDatabase

from core.logging import get_logger

logger = get_logger(__name__)

_TZ_BEIJING = timezone(timedelta(hours=8))

COLLECTION_NAME = "mcp_invocation_daily"


def _beijing_date() -> str:
    """返回当前北京时间的 ISO 日期字符串，如 '2026-04-09'"""
    return datetime.now(_TZ_BEIJING).strftime("%Y-%m-%d")


async def record_invocation(
    db: AsyncIOMotorDatabase,
    tool_id: str,
    token_id: str,
    user_id: str,
    success: bool,
) -> None:
    """记录一次 MCP 工具调用，upsert + $inc 保证并发安全

    Args:
        db: MongoDB 数据库实例
        tool_id: 工具 ID
        token_id: 调用方 token ID
        user_id: 调用方用户 ID
        success: 本次调用是否成功
    """
    date = _beijing_date()

    # 以 (date, tool_id, token_id) 为唯一键
    filter_doc = {
        "date": date,
        "tool_id": tool_id,
        "token_id": token_id,
    }

    # $inc 原子递增，$set 更新时间和 user_id
    inc_fields: dict = {"total_calls": 1}
    if success:
        inc_fields["success_calls"] = 1
    else:
        inc_fields["failed_calls"] = 1

    update_doc = {
        "$inc": inc_fields,
        "$set": {
            "user_id": user_id,
            "updated_at": datetime.now(UTC),
        },
        # 首次插入时初始化所有字段
        "$setOnInsert": {
            "date": date,
            "tool_id": tool_id,
            "token_id": token_id,
        },
    }

    try:
        await db[COLLECTION_NAME].update_one(
            filter_doc,
            update_doc,
            upsert=True,
        )
    except Exception as e:
        # 统计写入失败不影响主流程
        logger.warning("调用统计写入失败: tool_id=%s, error=%s", tool_id, e)
