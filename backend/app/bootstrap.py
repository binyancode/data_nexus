"""bootstrap.py —— 共享的服务注册。

把系统 DB、凭据提供器、Nexus 引擎注册进全局 IoC 容器。
main.py 启动时调用。
"""
from services.sql_db import sql_db
from services.credential import azure_keyvault_credential_provider
from core.services import services
from nexus.client import NexusClient


def register_services():
    """注册服务类型及默认配置映射。"""
    services.register(sql_db)
    services.register(azure_keyvault_credential_provider)
    services.register(NexusClient)

    # services[Type] 取实例时，自动把对应 config 段传给构造函数
    services.register_default_config(sql_db, "sql_db")
    services.register_default_config(azure_keyvault_credential_provider, "credential_provider")
    services.register_default_config(NexusClient, "nexus")


def register_resolvers():
    """Resolver / LLM 由 NexusClient 启动时从 `nexus.resolvers` / `nexus.llms`
    注册表加载（密文经 credential/KV），此处无需手动注册。"""
    pass

