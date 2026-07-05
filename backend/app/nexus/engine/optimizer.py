"""优化器：逻辑 SQG → 物理执行计划（P0：选中数据源、拼 SQL）。"""

from __future__ import annotations

from typing import Optional

from nexus.core.models import SQG, QueryPlan, PlanNode, Operator, ExecContext, topo_waves
from nexus.ontology.store import OntologyStore


class Optimizer:
    def __init__(self, ontology: OntologyStore):
        self.ontology = ontology

    def plan(self, sqg: SQG, ctx: Optional[ExecContext] = None) -> QueryPlan:
        nodes: list[PlanNode] = []
        for node in sqg.nodes:
            if node.operator == Operator.AGGREGATE:
                pn = self._plan_aggregate(node)
                if pn:
                    nodes.append(pn)

        # 按 depends_on 拓扑分波，把 wave 写进每个物理节点
        waves = topo_waves(nodes)
        for w, wave_nodes in enumerate(waves, start=1):
            for pn in wave_nodes:
                pn.wave = w

        context = {
            "as_user": ctx.as_user if ctx else None,
            "max_wave": len(waves),
            "parallelism": 4,
            "placeholder": "brace",
        }
        return QueryPlan(nodes=nodes, context=context)

    def _plan_aggregate(self, node) -> Optional[PlanNode]:
        metric = self.ontology.get_concept(node.concept) if node.concept else None
        if not metric:
            return None
        entity_id = metric.attrs.get("entity")
        table, resolver = self._entity_binding(entity_id)
        expr = metric.attrs.get("expr")
        if not (table and resolver and expr):
            return None

        where, params = [], []
        for f in node.params.get("filters", []):
            col = self._attr_column(f["concept"])
            if col:
                where.append(f"{col} = ?")
                params.append(f["value"])

        sql = f"SELECT {expr} AS value FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return PlanNode(
            id=node.id,
            operator=node.operator,
            name=node.name,
            resolver=resolver,
            call={"node_id": node.id, "sql": sql, "params": params},
            depends_on=list(node.depends_on),
        )

    def _entity_binding(self, entity_id: Optional[str]):
        if not entity_id:
            return None, None
        for b in self.ontology.get_bindings(entity_id):
            if b.kind == "table":
                return b.expr, b.resolver
        return None, None

    def _attr_column(self, attr_id: str) -> Optional[str]:
        for b in self.ontology.get_bindings(attr_id):
            if b.kind == "column":
                return b.expr
        return None
