"""Resolver 注册表：按 id 管理，并支持按概念/算子做选源竞标的候选检索。"""
from nexus.core.sqg import SQGNode
from nexus.resolvers.base import Resolver


class ResolverRegistry:
    def __init__(self) -> None:
        self._resolvers: dict[str, Resolver] = {}

    def register(self, resolver: Resolver) -> None:
        self._resolvers[resolver.id] = resolver

    def get(self, resolver_id: str) -> Resolver | None:
        return self._resolvers.get(resolver_id)

    def all(self) -> list[Resolver]:
        return list(self._resolvers.values())

    def candidates(self, node: SQGNode) -> list[Resolver]:
        """返回能覆盖该节点概念/算子的候选 Resolver（供调度器竞标）。"""
        result: list[Resolver] = []
        for r in self._resolvers.values():
            caps = r.capabilities()
            if node.op.value in caps.operators and (
                node.concept is None or node.concept in caps.concepts or not caps.concepts
            ):
                result.append(r)
        return result
