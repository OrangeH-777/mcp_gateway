# MCP 统一调用网关

基于 FastAPI 的 MCP Server 反向代理网关的一个demo示例，将多个分散的 MCP Server 聚合为统一入口，提供鉴权、限流、调用统计和热更新能力。

## 架构概览

```
客户端（浏览器 / CLI / AI Agent）
        │
        ▼
┌─────────────────────────────────────────┐
│              MCP Gateway                │
│                                         │
│  鉴权中间件 → 日志中间件 → 路由匹配     │
│       │                      │          │
│  TokenCache              限流检查       │
│  (MongoDB)              (TokenCache)    │
│                           │              │
│                   ┌───────┴───────┐     │
│                   ▼               ▼     │
│             HTTP 反向代理    调用统计    │
│             (httpx 流式)    (MongoDB)   │
└──────────┬──────────────────────┬───────┘
           │                      │
           ▼                      ▼
    MCP Server 1           MCP Server 2
    (127.0.0.1:9000)       (192.168.1.10:9000)
```

## 核心功能

| 功能 | 说明 |
|------|------|
| **动态路由** | 根据 MongoDB 中的注册配置，按 `mcp_name` 自动暴露 `/mcp/{mcp_name}/mcp` |
| **协议透传** | 完整透传请求/响应的 headers、body，支持流式（Chunked）响应 |
| **Token 鉴权** | 基于 `token` + `tool_id` 的请求鉴权，支持内存缓存加速 |
| **速率限制** | 按 Token + Tool 维度的调用频率限制，支持单 Token 无限速 |
| **调用统计** | 按天聚合工具调用次数，异步写入 MongoDB |
| **热更新** | 监听 MongoDB Change Stream，配置变更实时生效（新增/删除 Server 需重启） |
| **健康检查** | `/admin/health` 端点返回 MongoDB 连通性和已注册服务列表 |

## 项目结构

```
mcp_gateway/
├── main.py                      # 应用入口，生命周期管理
├── demo.py                      # MCP 客户端调试脚本
├── api/
│   ├── mcp.py                   # MCP 反向代理路由（核心）
│   └── admin.py                 # 管理端点（健康检查）
├── core/
│   ├── config.py                # 配置管理（pydantic-settings）
│   ├── cache.py                 # TokenCache 内存缓存实现
│   ├── dependencies.py          # FastAPI 依赖注入
│   └── logging.py               # 日志配置（控制台 + 文件轮转）
├── models/
│   └── schemas.py               # Pydantic 数据模型
├── services/
│   ├── registry.py              # MCP Server 配置注册中心
│   ├── token_check.py           # Token 鉴权中间件
│   ├── rate_limit.py            # 速率限制检查
│   └── invocation_stats.py      # 调用统计写入
└── tests/
    ├── demo_mcp_server.py       # 演示用 MCP Server
    └── mcp_test.py              # 集成测试脚本
```

## 快速开始

### 1. 环境要求

- Python 3.10+
- MongoDB 5.0+（需开启 Replica Set 以支持 Change Stream）

### 2. 安装依赖

采用uv创建.venv环境：
```bash
pip install uv
```

同步环境：
```bash
uv sync
```

### 3. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
# MongoDB 连接地址（必填）
MCP_GATEWAY_MONGODB_URI=mongodb://localhost:27017

# 数据库名称（默认 mcp_gateway）
MCP_GATEWAY_DATABASE_NAME=mcp_gateway

# 配置集合名称（默认 tool_registry）
MCP_GATEWAY_COLLECTION_NAME=tool_registry

# 网关监听端口（默认 8000）
MCP_GATEWAY_PORT=8000

# Token 鉴权集合名称（默认 mcp_tokens）
MCP_GATEWAY_TOKEN_COLLECTION_NAME=mcp_tokens

# 日志级别（默认 INFO）
MCP_GATEWAY_LOG_LEVEL=INFO
```

### 4. 注册 MCP Server

在 MongoDB 中插入 MCP Server 注册记录：

```javascript
db.tool_registry.insertOne({
    "tool_id": "mcp-demo",
    "name": "mcp-demo",
    "enabled": true,
    "timeout_seconds": 30,
    "mcp_endpoint": {
        "server_url": "http://127.0.0.1:9000/mcp",
        "tool_name": "mcp-demo",
        "rate_limit": 30
    }
}

})
```

插入 Token 鉴权记录：

```javascript
db.mcp_tokens.insertOne({
    "token": "39c7743a-2922-4478-a005-c8459a2428d5",
    "tool_id": "mcp-demo",
    "user_id": "user001",
    "banned": false
})
```

```javascript
db.mcp_tokens.insertOne({
  "token": "aa17d741-bfc8-435f-a90f-d3261475622a",
    "tool_id": "mcp-demo",
    "user_id": "user002",
    "banned": false
})
```

### 5. 启动网关

```bash
# 开发模式（热重载）
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 生产模式
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

启动成功日志：
```
INFO | MongoDB 连接成功
INFO | 内存缓存初始化完成
INFO | 当前已启用: ['mcp-demo']
INFO | 开始监听 MongoDB 配置变化
INFO | Application startup complete.
```

## 使用方式

### API 端点

| 路径 | 方法 | 说明 | 鉴权 |
|------|------|------|------|
| `/mcp/{mcp_name}/mcp` | GET/POST/DELETE | MCP 代理入口 | 需要 `token` + `tool_id` |
| `/admin/health` | GET | 健康检查 | 需要 `token` + `tool_id` |
| `/docs` | GET | Swagger 文档 | 无需鉴权 |

### 调用示例（Postman可直接复制）

#### 1. 列出可用工具（tools/list）

```bash
curl -X POST http://localhost:8000/mcp/mcp-demo/mcp \
  -H "token: your-token-id" \
  -H "tool_id: mcp-demo" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream,application/json" \
  -H "mcp-session-id: {{mcp-session-id}}" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

#### 2. 调用具体工具（tools/call）

```bash
curl -X POST http://localhost:8000/mcp/mcp-demo/mcp \
  -H "token: your-token-id" \
  -H "tool_id: mcp-demo" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream,application/json" \
  -H "mcp-session-id: {{mcp-session-id}}" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"echo","arguments":{"message":"hello"}}}'
```

#### 3. 初始化会话（initialize）

```bash
curl -X POST http://localhost:8000/mcp/mcp-demo/mcp \
  -H "token: your-token-id" \
  -H "tool_id: mcp-demo" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream,application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test-client","version":"1.0.0"}}}'
```

##### 设置环境变量：
```bash
  export mcp-session-id=$(grep -i "mcp-session-id" /tmp/headers.txt | awk '{print $2}' | tr -d '\r')
```
##### OR

##### Scripts:
```bash
var sessionId = pm.response.headers.get("Mcp-Session-Id");
if (sessionId) {
    pm.environment.set("mcp_session_id", sessionId);
    console.log("Session ID saved: " + sessionId);
}
```

#### 4. Ping 探活

```bash
curl -X POST http://localhost:8000/mcp/mcp-demo/mcp \
  -H "token: your-token-id" \
  -H "tool_id: mcp-demo" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream,application/json" \
  -H "mcp-session-id: {{mcp-session-id}}" \
  -d '{"jsonrpc":"2.0","id":4,"method":"ping"}'
```

#### 5. 健康检查

```bash
curl http://localhost:8000/admin/health \
  -H "token: your-token-id" \
  -H "tool_id: mcp-demo"
```

返回示例：

```json
{
  "status": "healthy",
  "mongodb_connected": true,
  "registered_count": 1,
  "mcp_names": ["mcp-demo"]
}
```

#### 6. 访问 Swagger 文档

浏览器打开，无需鉴权：

```
http://localhost:8000/docs
```

#### 7. 错误响应示例

**缺少凭证（401）**：

```bash
curl http://localhost:8000/mcp/mcp-demo/mcp
```

```json
{"detail": "Missing token_id or tool_id"}
```

**凭证无效（401）**：

```json
{"detail": "Invalid token_id or tool_id"}
```

**MCP Server 不存在（404）**：

```json
{"error": "MCP Server 'xxx' 不存在或未启用"}
```

**触发限流（429）**：

```json
{"detail": "Rate limit exceeded. Please try again later."}
```

### Python 客户端调用

```python
import asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

async def main():
    transport = StreamableHttpTransport(
        url="http://localhost:8000/mcp/mcp-demo/mcp",
        headers={"token": "your-token-id", "tool_id": "mcp-demo"}
    )
    async with Client(transport) as client:
        # 列出所有工具
        tools = await client.list_tools()
        for tool in tools:
            print(f"  - {tool.name}: {tool.description}")

        # 调用工具
        result = await client.call_tool("echo", {"message": "hello"})
        print(result)

        # 调用计算工具
        result = await client.call_tool("add", {"a": 3.14, "b": 2.72})
        print(result)

asyncio.run(main())
```

## 运行测试

```bash
# 终端 1：启动演示 MCP Server
python tests/demo_mcp_server.py

# 终端 2：启动网关（需先在 MongoDB 注册配置）
uvicorn main:app --host 0.0.0.0 --port 8000

# 终端 3：运行集成测试
python tests/mcp_test.py
```

## MongoDB 集合说明

| 集合名 | 用途 | 关键字段 |
|--------|------|----------|
| `tool_registry` | MCP Server 注册配置 | `name`, `enabled`, `mcp_endpoint.server_url` |
| `mcp_tokens` | Token 鉴权信息 | `token`, `tool_id`, `banned`, `rate_limit_override` |
| `mcp_invocation_daily` | 调用统计（按天聚合） | `date`, `tool_id`, `total_calls`, `success_calls` |

## 请求处理流程

```
客户端请求 POST /mcp/{mcp_name}/mcp
    │
    ▼
① 鉴权中间件（token_check.py）
    ├── 白名单放行（/docs, /openapi.json）
    ├── 校验 token + tool_id 是否存在
    ├── 查询 TokenCache → 未命中则查 MongoDB
    └── 验证失败返回 401
    │
    ▼
② 日志中间件（main.py）
    └── 记录请求方法、路径、状态码、耗时
    │
    ▼
③ MCP 反向代理（mcp.py）
    ├── 从 ToolRegistry 获取目标 MCP Server 配置
    ├── 解析 JSON-RPC 方法名（tools/call 时触发限流+统计）
    ├── 限流检查（rate_limit.py）→ 超限返回 429
    ├── httpx 异步转发请求到后端 MCP Server
    ├── 流式透传响应（StreamingResponse）
    └── 异步记录调用统计（invocation_stats.py）
```

## 依赖说明

| 包 | 用途 |
|----|------|
| `fastapi` | Web 框架，路由与中间件 |
| `uvicorn` | ASGI 服务器 |
| `motor` | MongoDB 异步驱动 |
| `pymongo` / `bson` | MongoDB 同步工具 + ObjectId |
| `pydantic` | 数据校验与序列化 |
| `pydantic-settings` | 环境变量配置管理 |
| `httpx` | 异步 HTTP 客户端，用于反向代理 |
| `fastmcp` | MCP 协议客户端库（测试用） |
