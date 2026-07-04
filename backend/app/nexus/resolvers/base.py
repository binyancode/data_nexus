"""Resolver 统一接口：数据源 / 智能体 / 动作都长成同一个接口。

三方法一句话：capabilities() 报能力、plan() 评估+编译、resolve() 干活。
另有 describe()/sample() 供自动建本体（见设计文档第 4 节）。
"""
from abc import ABC, abstractmethod

from nexus.core.capabilities import Capabilities
from nexus.core.context import (
    ExecContext,
    PlannedCall,
    ResolveResult,
    SourceSchema,
)
from nexus.core.models import Binding
from nexus.core.sqg import SQGNode


class Resolver(ABC):
    """所有源的统一执行接口。子类需声明 id 并实现三大方法。"""

    id: str

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """报能力清单：能答哪些概念、成本、时效、信任分、是否支持用户级权限。"""
        ...

    @abstractmethod
    def plan(self, node: SQGNode, binding: Binding) -> PlannedCall:
        """评估（成本/时延/信任）+ 用 Binding 把节点编译成具体调用。"""
        ...

    @abstractmethod
    async def resolve(self, call: PlannedCall, ctx: ExecContext) -> ResolveResult:
        """干活：真正执行，返回数据 / 答案+证据 / 回执。"""
        ...

    # ── 自动建本体（可选实现）──
    def describe(self) -> SourceSchema:
        """结构探测：表/字段/外键。"""
        raise NotImplementedError

    def sample(self, obj: str, n: int = 20) -> list[dict]:
        """抽样（脱敏）。"""
        raise NotImplementedError
