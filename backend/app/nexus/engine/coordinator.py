"""协调器：按计划执行（P0 单波顺序执行；返回各节点结果）。"""

from __future__ import annotations

from nexus.core.models import QueryPlan, NodeResult, ExecContext
from nexus.registry import ResolverRegistry


class Coordinator:
    def __init__(self, registry: ResolverRegistry):
        self.registry = registry

    def execute(self, plan: QueryPlan, ctx: ExecContext) -> dict[str, NodeResult]:
        for step in plan.steps:
            if ctx.cancellation_token and getattr(ctx.cancellation_token, "is_cancelled", False):
                break
            resolver = self.registry.resolver(step.resolver)
            if not resolver:
                ctx.results[step.node_id] = NodeResult(
                    node_id=step.node_id, error=f"resolver not found: {step.resolver}"
                )
                continue
            ctx.results[step.node_id] = resolver.fetch(step.call, ctx)
        return ctx.results
