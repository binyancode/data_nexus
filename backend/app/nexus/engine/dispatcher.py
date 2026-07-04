"""调度器 Dispatcher：选源竞标 + 编译成真实调用 + 权限透传。

对 SQG 每个节点：① 让能覆盖的 Resolver 竞标，按信任/成本/时效选中；
② 调 resolver.plan(node, binding) 生成 call；③ 若中标 Resolver user_scoped，
给该 plan 项打 user_scoped，执行时透传 as_user。
"""
from nexus.core.sqg import SQG, SQGNode
from nexus.core.context import Plan
from nexus.ontology.store import OntologyStore
from nexus.registry import ResolverRegistry
from nexus.resolvers.base import Resolver


class Dispatcher:
    # 竞标打分权重（成本-信任-时效加权，见设计文档 5.4）
    W_TRUST, W_COST, W_LAT, W_COVER = 1.0, 0.5, 0.3, 0.4

    def __init__(self, ontology: OntologyStore, registry: ResolverRegistry):
        self.ontology = ontology
        self.registry = registry

    def score(self, resolver: Resolver, node: SQGNode) -> float:
        caps = resolver.capabilities()
        norm_lat = min(caps.latency_ms / 2000.0, 1.0)
        cover = 1.0 if (node.concept and node.concept in caps.concepts) else 0.0
        return (
            self.W_TRUST * caps.trust
            - self.W_COST * caps.cost
            - self.W_LAT * norm_lat
            + self.W_COVER * cover
        )

    def dispatch(self, sqg: SQG) -> Plan:
        # TODO(P0): 逐节点竞标选源 → plan() 编译成调用 → 组装 Plan（含 as_user 透传）
        raise NotImplementedError("Dispatcher.dispatch 尚未实现（P0）")
