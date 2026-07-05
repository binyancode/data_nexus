"""优化器：逻辑 SQG → 物理执行计划（多节点 / 多算子）。

- AGGREGATE：据指标 concept 的绑定拼下推 SQL（选中数据源）。
- ASK：路由到 agent（LLM）resolver，call 带回填用的 prompt。
- ACT：路由到 action resolver，call 带动作 + 描述。
resolver 选择优先看 concept 绑定，缺失则按 registry 里的 resolver 类型兜底。
分波（wave）由 depends_on 拓扑排序算出。
"""

from __future__ import annotations

import re
from typing import Optional

from nexus.core.models import SQG, QueryPlan, PlanNode, Operator, ExecContext, topo_waves
from nexus.ontology.store import OntologyStore

# 表达式里引用属性概念的记号，如 attribute.sales.amount
_ATTR_TOKEN = re.compile(r"attribute(?:\.[A-Za-z0-9_]+)+")


class Optimizer:
    def __init__(self, ontology: OntologyStore, registry=None):
        self.ontology = ontology
        self.registry = registry

    def plan(self, sqg: SQG, ctx: Optional[ExecContext] = None) -> QueryPlan:
        nodes: list[PlanNode] = []
        for node in sqg.nodes:
            pn = self._plan_node(node)
            if pn:
                nodes.append(pn)

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

    # ── 分派 ──
    def _plan_node(self, node) -> Optional[PlanNode]:
        if node.operator == Operator.AGGREGATE:
            return self._plan_aggregate(node)
        if node.operator == Operator.ASK:
            return self._plan_ask(node)
        if node.operator == Operator.ACT:
            return self._plan_act(node)
        return None

    # ── AGGREGATE → 下推 SQL ──
    def _plan_aggregate(self, node) -> Optional[PlanNode]:
        metric = self.ontology.get_concept(node.concept) if node.concept else None
        if not metric:
            return None
        expr = metric.attrs.get("expr")
        if not expr:
            return None

        filters = node.params.get("filters", [])
        # 新式：表达式用属性(attribute.*)表达，实体与 JOIN 由属性自动推导
        resolved = self._resolve_attr_aggregate(expr, filters)
        if resolved is None:
            # 兼容旧式：metric.attrs.entity + 裸列表达式
            resolved = self._resolve_entity_aggregate(metric, expr, filters)
        if resolved is None:
            return None
        sql, params, resolver = resolved
        return PlanNode(
            id=node.id, operator=node.operator, name=node.name, resolver=resolver,
            call={"node_id": node.id, "sql": sql, "params": params},
            depends_on=list(node.depends_on),
        )

    # 属性表达式 → SQL（多实体自动 JOIN）
    def _resolve_attr_aggregate(self, expr: str, filters: list):
        tokens = list(dict.fromkeys(_ATTR_TOKEN.findall(expr)))
        if not tokens:
            return None
        info: dict[str, tuple[str, str]] = {}     # attr_id -> (entity_id, column)
        ent_order: list[str] = []
        for tid in tokens:
            c = self.ontology.get_concept(tid)
            col = self._attr_column(tid)
            ent = c.attrs.get("entity") if c else None
            if not (c and col and ent):
                return None
            info[tid] = (ent, col)
            if ent not in ent_order:
                ent_order.append(ent)

        # 实体 → 表/resolver/别名
        meta: dict[str, dict] = {}
        resolver = None
        for i, ent in enumerate(ent_order):
            table, rsv = self._entity_binding(ent)
            if not table:
                return None
            resolver = resolver or rsv
            meta[ent] = {"table": table, "resolver": rsv, "alias": f"t{i}"}
        single = len(ent_order) == 1

        def col_ref(ent: str, col: str) -> str:
            return col if single else f'{meta[ent]["alias"]}.{col}'

        # 替换表达式里的属性记号（长的优先，避免前缀重叠）
        resolved_expr = expr
        for tid in sorted(tokens, key=len, reverse=True):
            ent, col = info[tid]
            resolved_expr = resolved_expr.replace(tid, col_ref(ent, col))

        # FROM / JOIN
        first = ent_order[0]
        if single:
            from_sql = meta[first]["table"]
        else:
            from_sql = f'{meta[first]["table"]} {meta[first]["alias"]}'
            joined = {first}
            for ent in ent_order[1:]:
                rel = self._find_relation(ent, joined)
                if not rel:
                    return None
                fe, fk, te, tk = rel
                from_sql += (
                    f' JOIN {meta[ent]["table"]} {meta[ent]["alias"]} ON '
                    f'{meta[fe]["alias"]}.{fk} = {meta[te]["alias"]}.{tk}'
                )
                joined.add(ent)

        where, params = self._build_where(filters, meta, single)
        sql = f"SELECT {resolved_expr} AS value FROM {from_sql}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return sql, params, resolver

    # 旧式：单实体 + 裸列表达式
    def _resolve_entity_aggregate(self, metric, expr: str, filters: list):
        table, resolver = self._entity_binding(metric.attrs.get("entity"))
        if not (table and resolver):
            return None
        where, params = [], []
        for f in filters:
            col = self._attr_column(f.get("concept"))
            if col:
                where.append(f"{col} = ?")
                params.append(f.get("value"))
        sql = f"SELECT {expr} AS value FROM {table}"
        if where:
            sql += " WHERE " + " AND ".join(where)
        return sql, params, resolver

    # 过滤条件 → WHERE（只应用属性在本次查询实体内的过滤；多实体时加别名前缀）
    def _build_where(self, filters: list, meta: dict, single: bool):
        where, params = [], []
        for f in filters:
            cid = f.get("concept")
            col = self._attr_column(cid)
            if not col:
                continue
            c = self.ontology.get_concept(cid) if cid else None
            ent = c.attrs.get("entity") if c else None
            # 属性不属于本次查询的实体 → 跳过（避免拼出不存在的列）
            if ent and ent not in meta:
                continue
            if not single and ent in meta:
                col = f'{meta[ent]["alias"]}.{col}'
            where.append(f"{col} = ?")
            params.append(f.get("value"))
        return where, params

    # 找一条把 ent 连到已 join 实体的关系
    def _find_relation(self, ent: str, joined: set):
        for c in self.ontology.list_concepts():
            kind = c.kind.value if hasattr(c.kind, "value") else str(c.kind)
            if kind != "relation":
                continue
            fe = c.attrs.get("from_entity"); te = c.attrs.get("to_entity")
            fk = c.attrs.get("from_key"); tk = c.attrs.get("to_key")
            if not (fe and te and fk and tk):
                continue
            if (fe == ent and te in joined) or (te == ent and fe in joined):
                return fe, fk, te, tk
        return None

    # ── ASK → agent(LLM) ──
    def _plan_ask(self, node) -> Optional[PlanNode]:
        resolver = self._concept_resolver(node.concept) or self._first_of_type("agent")
        if not resolver:
            return None
        prompt = node.params.get("prompt") or node.params.get("ask") or ""
        call = {"node_id": node.id, "prompt": prompt}
        if node.params.get("system"):
            call["system"] = node.params["system"]
        return PlanNode(
            id=node.id, operator=node.operator, name=node.name, resolver=resolver,
            call=call, depends_on=list(node.depends_on),
        )

    # ── ACT → action ──
    def _plan_act(self, node) -> Optional[PlanNode]:
        resolver, expr = self._concept_resolver_expr(node.concept)
        resolver = resolver or self._first_of_type("action")
        if not resolver:
            return None
        call = {
            "node_id": node.id,
            "action": expr or node.params.get("action") or "create_task",
            "desc": node.params.get("desc") or node.params.get("title") or "",
        }
        if node.params.get("assignee"):
            call["assignee"] = node.params["assignee"]
        return PlanNode(
            id=node.id, operator=node.operator, name=node.name, resolver=resolver,
            call=call, depends_on=list(node.depends_on),
        )

    # ── 绑定/注册表查询 ──
    def _entity_binding(self, entity_id: Optional[str]):
        if not entity_id:
            return None, None
        for b in self.ontology.get_bindings(entity_id):
            if b.kind == "table":
                return b.expr, b.resolver
        return None, None

    def _attr_column(self, attr_id: Optional[str]) -> Optional[str]:
        if not attr_id:
            return None
        for b in self.ontology.get_bindings(attr_id):
            if b.kind == "column":
                return b.expr
        return None

    def _concept_resolver(self, concept_id: Optional[str]) -> Optional[str]:
        if not concept_id:
            return None
        for b in self.ontology.get_bindings(concept_id):
            if b.resolver:
                return b.resolver
        return None

    def _concept_resolver_expr(self, concept_id: Optional[str]):
        if not concept_id:
            return None, None
        for b in self.ontology.get_bindings(concept_id):
            if b.resolver:
                return b.resolver, b.expr
        return None, None

    def _first_of_type(self, rtype: str) -> Optional[str]:
        if not self.registry:
            return None
        rs = self.registry.resolvers_of_type(rtype)
        return rs[0].name if rs else None
