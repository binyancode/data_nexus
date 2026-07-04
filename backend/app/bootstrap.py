"""bootstrap.py —— 共享的服务注册。

把 Nexus 引擎注册进全局 IoC 容器，并注册示例 Resolver。
main.py 启动时调用。
"""
from core.services import services
from nexus.client import NexusClient
from nexus.resolvers import SqlResolver


def register_services():
    """注册服务类型及默认配置映射。"""
    services.register(NexusClient)
    # services[NexusClient] 取实例时，自动把 config["nexus"] 传给构造函数
    services.register_default_config(NexusClient, "nexus")


def register_resolvers():
    """向 Nexus 注册各源 Resolver（能力层）。

    示例：注册一个数仓 SQL 源。P0 阶段 plan()/resolve() 待实现，
    但 capabilities() 已可用，能被 /api/v1/resolvers 列出。
    """
    nexus: NexusClient = services[NexusClient]
    nexus.register_resolver(SqlResolver("dwh.sql", {}))
