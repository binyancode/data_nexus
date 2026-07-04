"""FastAPI 依赖注入辅助。

约定：通过 services[Type] 从全局 IoC 容器取服务实例；
此模块提供把这些实例暴露成 FastAPI Depends 的薄封装。
"""
from config import config as _config
from core.services import services
from nexus.client import NexusClient


def get_config():
    """返回全局配置单例。"""
    return _config()


def get_nexus() -> NexusClient:
    """返回 Nexus 引擎门面（单例）。"""
    return services[NexusClient]
