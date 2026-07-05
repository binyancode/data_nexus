"""Resolver 抽象基类：源 = 智能体 = 动作，统一成一个执行接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from nexus.core.models import NodeResult, ExecContext


class Resolver(ABC):
    """一个 Resolver 就是一个「可查询/可执行的源」。

    - describe(): 探测源结构（建本体时用）
    - sample():   取样例数据（建本体时用）
    - fetch():    按调用描述执行，返回 NodeResult
    """

    resolver_type: str = "base"

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}

    @abstractmethod
    def fetch(self, call: dict, ctx: Optional[ExecContext] = None) -> NodeResult:
        """执行一次调用。call 的结构由各类型自定义（如 SQL: {node_id, sql, params}）。"""
        ...

    def describe(self) -> dict:
        """探测源结构（默认不支持）。"""
        return {}

    def sample(self, target: str = None, n: int = 5) -> list[dict[str, Any]]:
        """取样例数据（默认不支持）。"""
        return []

    def capabilities(self) -> dict:
        return {"name": self.name, "type": self.resolver_type}
