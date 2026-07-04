"""协调器 Coordinator：按 DAG 分波并行 + 上游结果回填 + 合并 + 裁决。

算法（设计文档 7.3）：
    for wave in topo_waves(plan):
        calls = [backfill(item, results) for item in wave]   # 用已完成结果回填占位符
        wave_results = await gather(run_call(c, ctx) for c in calls)
        results.update(wave_results)
    merged = merge_by_concept(results)
    verdict = arbitrate(merged)     # 数字冲突按 信任×时效×精度 加权
"""
from typing import Any

from nexus.core.context import ExecContext, Plan
from nexus.registry import ResolverRegistry


class Coordinator:
    def __init__(self, registry: ResolverRegistry):
        self.registry = registry

    async def coordinate(self, plan: Plan, ctx: ExecContext) -> tuple[dict, dict]:
        """返回 (merged_results, verdict)。"""
        # TODO(P0): 拓扑分波 → 并行执行（user_scoped 时 ctx.with_user）→ 回填 → 合并 → 裁决
        raise NotImplementedError("Coordinator.coordinate 尚未实现（P0）")

    @staticmethod
    def topo_waves(plan: Plan) -> list[list[str]]:
        """按 deps 把节点拓扑分波，同波可并行。"""
        raise NotImplementedError("Coordinator.topo_waves 尚未实现（P0）")

    @staticmethod
    def backfill(call: Any, results: dict) -> Any:
        """把上游结果回填进 {nX} 占位符。"""
        raise NotImplementedError("Coordinator.backfill 尚未实现（P0）")
