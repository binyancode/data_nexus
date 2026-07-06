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

    类级能力声明（用于本体作用域 + 算子能力驱动，避免按类型名硬编码）：
    - provides_concepts: 能否贡献概念（可浏览/导入 entity）。sql=True，agent/action=False。
    - operators: 能执行哪些 SQG 算子（编译器据此提供、优化器据此派发）。
    """

    resolver_type: str = "base"
    provides_concepts: bool = False
    operators: set[str] = set()

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
        return {"name": self.name, "type": self.resolver_type,
                "provides_concepts": self.provides_concepts,
                "operators": sorted(self.operators)}
