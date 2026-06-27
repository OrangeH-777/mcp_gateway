"""
Demo MCP Server - 使用 fastmcp + Streamable HTTP 协议

启动方式：
uv run python mcp_gateway/tests/demo_mcp_server.py

默认监听 http://127.0.0.1:9000/mcp
需要在 MongoDB 中注册对应的 ToolRegistration：
{
"_id": "demo",
"mcp_name": "demo",
"description": "Demo MCP Server",
"enabled": true,
"timeout_seconds": 30,
"mcp_endpoint": { "url": "http://127.0.0.1:9000/mcp" }
}
"""

from fastmcp import FastMCP

mcp = FastMCP("demo")

@mcp.tool()
def echo(message: str) -> str:
    """原样返回输入的消息"""
    return f"echo: {message}"

@mcp.tool()
def add(a: float, b: float) -> float:
    """计算两个数字之和"""
    return a + b

@mcp.tool()
def get_info() -> dict:
    """返回 demo server 的基本信息"""
    return {"name": "demo", "version": "0.1.0", "protocol": "streamable-http"}

if __name__ == "__main__":
    # 使用新版 Streamable HTTP 协议启动
    mcp.run(transport="streamable-http", host="127.0.0.1", port=9000)