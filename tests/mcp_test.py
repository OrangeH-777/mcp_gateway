"""
Gateway 集成测试 - 通过 gateway 调用 demo MCP Server

测试前准备：

启动 demo MCP server：
uv run python tests/demo_mcp_server.py

在 MongoDB 中插入注册记录：
db.tool_registrations.insertOne({
"_id": "demo",
"mcp_name": "demo",
"description": "Demo MCP Server",
"enabled": true,
"timeout_seconds": 30,
"mcp_endpoint": { "url": "http://127.0.0.1:9000/mcp" }
})

启动 gateway：
uv run uvicorn main:app --host 0.0.0.0 --port 8000

运行本测试：
uv run python tests/mcp_test.py
"""
import asyncio

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

GATEWAY_URL = "http://127.0.0.1:8000/mcp/mcp-demo/mcp"
AUTH_HEADERS = {
    "token": "39c7743a-2922-4478-a005-c8459a2428d5",
    "tool_id": "mcp-demo",
}
AUTH_HEADERS1 = {
    "token": "aa17d741-bfc8-435f-a90f-d3261475622a",
    "tool_id": "mcp-demo",
}


async def main(header) -> None:
    print(f"正在通过 gateway 连接 demo MCP Server：{GATEWAY_URL}")

    # 使用 StreamableHttpTransport 传入自定义请求头
    transport = StreamableHttpTransport(url=GATEWAY_URL, headers=header)
    client = Client(transport)
    try:
        async with client:
            # 1. 列出工具
            print("\n" + "=" * 50)
            print("可用工具列表:")
            print("=" * 50)
            tools = await client.list_tools()
            for tool in tools:
                print(f"  - {tool.name}: {tool.description}")
            for i in range(1):
                # 2. 调用 echo 工具
                print("\n" + "=" * 50)
                print("调用 echo 工具:")
                print("=" * 50)
                result = await client.call_tool("echo", {"message": "hello gateway"})
                print(f"  结果: {result}")

                # 3. 调用 add 工具
                print("\n" + "=" * 50)
                print("调用 add 工具:")
                print("=" * 50)
                result = await client.call_tool("add", {"a": 3.14, "b": 2.72})

                print(f"  结果: {result}")
                print("\n" + "=" * 50)
                
                if i == 6:
                    print("\n正在测试速率限制（超过 20 次后应该被限制）...")
            # 4. 调用 get_info 工具
            print("\n" + "=" * 50)
            print("调用 get_info 工具:")
            print("=" * 50)
            result = await client.call_tool("get_info", {})
            print(f"  结果: {result}")

    except ConnectionError as e:
        print(f"\n❌ 连接失败：{e}")
        print("请确认 demo_mcp_server.py 和 gateway 均已启动")
    except Exception as e:
        print(f"\n❌ 发生错误：{e}")
        import traceback
        traceback.print_exc()
async def run_all():
    await main(AUTH_HEADERS1)
    await main(AUTH_HEADERS)

if __name__ == "__main__":
    asyncio.run(run_all())
