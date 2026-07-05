"""bootstrap.py —— 共享的服务注册。

把系统 DB、凭据提供器、Nexus 引擎注册进全局 IoC 容器。
main.py 启动时调用。
"""
from services.sql_db import sql_db
from services.credential import azure_keyvault_credential_provider
from core.services import services
from core.api_handler import api_handler
from core.api_log import ApiLogRecord, ApiLogSink
from utils.logger import get_logger
from nexus.client import NexusClient

_log = get_logger("api")


class ApiLogRecorder(ApiLogSink):
    """API 日志汇：同时记录到 nexus.api_log 和系统 logger（按 state 分级）。

    DB 依赖留在 app 层，core 不引用 services。
    """

    def emit(self, record: ApiLogRecord) -> None:
        # 1) 系统 logger（按状态分级；错误时把完整堆栈换行打出，便于定位报错行）
        line = (f"[{record.function}] {record.method} {record.path} "
                f"state={record.state} user={record.user} {record.cost_ms}ms")
        if record.state in ("failed", "error"):
            _log.error(line + (f"\n{record.message}" if record.message else ""))
        elif record.state in ("denied", "unauthorized"):
            _log.warning(line + (f" {record.message}" if record.message else ""))
        else:
            _log.info(line)

        # 2) 数据库
        services[sql_db].execute_non_query(
            """INSERT INTO nexus.api_log
                   (function_name, [method], [path], user_name, payload, response, state, cost_ms, message, source, request_time, response_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.function, record.method, record.path, record.user, record.payload,
                record.response, record.state, record.cost_ms, record.message, record.source,
                record.request_time, record.response_time,
            ),
        )


def register_services():
    """注册服务类型及默认配置映射。"""
    services.register(sql_db)
    services.register(azure_keyvault_credential_provider)
    services.register(NexusClient)

    # services[Type] 取实例时，自动把对应 config 段传给构造函数
    services.register_default_config(sql_db, "sql_db")
    services.register_default_config(azure_keyvault_credential_provider, "credential_provider")
    services.register_default_config(NexusClient, "nexus")

    # 注册实现 ApiLogSink 接口的日志汇（依赖倒置：DB 依赖在 app 层，core 不引用 services）
    api_handler.register_log_sink(ApiLogRecorder())


def register_resolvers():
    """Resolver / LLM 由 NexusClient 启动时从 `nexus.resolvers` / `nexus.llms`
    注册表加载（密文经 credential/KV），此处无需手动注册。"""
    pass


