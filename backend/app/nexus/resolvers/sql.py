"""SQL 数据源 Resolver（P0 骨架）。

被动 · 确定：用 SQL 取数，结果确定可复算。
P0 目标是「一个 SQL 源能问答」，后续在此填充真实连接与编译逻辑。
"""
from typing import Any

from nexus.core.capabilities import Capabilities
from nexus.core.context import ExecContext, PlannedCall, ResolveResult
from nexus.core.models import Binding
from nexus.core.sqg import SQGNode
from nexus.resolvers.base import Resolver


class SqlResolver(Resolver):
    def __init__(self, id: str, config: dict[str, Any] | None = None):
        self.id = id
        self.config = config or {}

    def capabilities(self) -> Capabilities:
        # TODO(P0): 由 describe() 探测出的概念覆盖 + 实测时延填充
        return Capabilities(
            resolver=self.id,
            operators=["SELECT", "FILTER", "AGGREGATE", "TRAVERSE"],
            cost=0.2,
            latency_ms=300,
            trust=0.98,
            user_scoped=True,
            freshness="realtime",
        )

    def plan(self, node: SQGNode, binding: Binding) -> PlannedCall:
        # TODO(P0): 用 binding.expr / table / joins / grain 拼出真实 SQL
        raise NotImplementedError("SqlResolver.plan 尚未实现（P0）")

    async def resolve(self, call: PlannedCall, ctx: ExecContext) -> ResolveResult:
        # TODO(P0): 执行 SQL；若 call.user_scoped，则按 ctx.user 做行级安全过滤
        raise NotImplementedError("SqlResolver.resolve 尚未实现（P0）")
