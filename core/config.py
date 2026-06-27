"""配置管理模块 - 使用 pydantic-settings 从环境变量读取配置"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """网关全局配置 - 通过环境变量或 .env 文件注入"""

    # MongoDB 连接地址
    mongodb_uri: str = ""

    # MongoDB 数据库名称
    database_name: str = "mcp_gateway"

    # MongoDB 集合名称（存储 MCP Server 注册信息）
    collection_name: str = "tool_registry"

    # 代理请求默认超时时间（秒）
    default_timeout_seconds: int = 30

    # 网关服务监听主机
    host: str = "0.0.0.0"

    # 网关服务监听端口
    port: int = 8000

    # 用户令牌校验 MongoDB 集合名称
    token_collection_name: str = "mcp_tokens"

    model_config = {
        "env_prefix": "MCP_GATEWAY_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    log_level: str = "INFO"
    log_dir: str = "logs"
    log_file_name: str = " log"
    log_when: str = "midnight"
    log_interval: int = 1
    log_backup_count: int = 14


settings = Settings()
