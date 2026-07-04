"""Data Nexus 引擎 SDK —— 框架无关，可被 API 层或其他程序直接 import。

用法：
    from nexus import NexusClient
    nexus = NexusClient(config)
    answer = await nexus.ask("华东上季度毛利为什么下滑？", as_user="zhangsan@beone")
"""
from nexus.client import NexusClient

__all__ = ["NexusClient"]
