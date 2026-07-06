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

# 过滤操作符白名单（防注入）；键=LLM 给的 op，值=拼进 SQL 的算子
_FILTER_OPS = {"=": "=", "!=": "<>", "<>": "<>", ">": ">", ">=": ">=",
               "<": "<", "<=": "<=", "like": "LIKE", "in": "IN"}
# 临时聚合允许的函数；以及各函数对 dtype 的要求
_AGG_FUNCS = {"SUM", "AVG", "MIN", "MAX", "COUNT"}
_AGG_NEEDS_NUMBER = {"SUM", "AVG"}


class Optimizer:
    def __init__(self, ontology: OntologyStore, registry=None, allowed: Optional[set] = None):
        self.ontology = ontology
        self.registry = registry
        # 本次运行允许使用的 resolver 名集合（本体作用域）；None = 不限制（兼容/测试）
        self.allowed = set(allowed) if allowed is not None else None

    def _allowed(self, name: Optional[str]) -> bool:
        return bool(name) and (self.allowed is None or name in self.allowed)

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
        expr = self._aggregate_expr(node)
        if not expr:
            return None

        filters = node.params.get("filters", [])
        group_by = node.params.get("group_by")
        order = (node.params.get("order") or "desc").lower()
        order = "ASC" if order == "asc" else "DESC"
        limit = node.params.get("limit")
        try:
            limit = int(limit) if limit is not None else None
        except (TypeError, ValueError):
            limit = None
        having = self._clean_having(node.params.get("having"))
        rank = {"group_by": group_by, "order": order, "limit": limit, "having": having} \
            if (group_by or having) else None

        resolved = self._resolve_attr_aggregate(expr, filters, rank)
        if resolved is None:
            return None
        sql, params, resolver = resolved
        if not self._allowed(resolver):
            return None
        return PlanNode(
            id=node.id, operator=node.operator, name=node.name, resolver=resolver,
            call={"node_id": node.id, "sql": sql, "params": params},
            depends_on=list(node.depends_on),
        )

    # 取聚合表达式：优先 metric 口径；否则用 measure 属性 + agg 函数（临时聚合）
    def _aggregate_expr(self, node) -> Optional[str]:
        metric = self.ontology.get_concept(node.concept) if node.concept else None
        if metric and metric.attrs.get("expr"):
            return metric.attrs["expr"]
        # 临时聚合：{measure: attribute.*, agg: SUM/AVG/MIN/MAX/COUNT}
        measure = node.params.get("measure")
        if not measure:
            return None
        mc = self.ontology.get_concept(measure)
        if not mc or mc.attrs.get("role") != "measure":
            return None
        agg = (node.params.get("agg") or "SUM").upper()
        if agg not in _AGG_FUNCS:
            return None
        dtype = mc.attrs.get("dtype")
        if agg in _AGG_NEEDS_NUMBER and dtype not in (None, "number"):
            return None
        additivity = mc.attrs.get("additivity")
        if additivity == "non_additive" and agg == "SUM":
            return None   # 比率/百分比等不可加：禁 SUM
        return f"{agg}({measure})"

    def _clean_having(self, having):
        """having: {op, value} → 规整；非法/缺失返回 None。"""
        if not isinstance(having, dict):
            return None
        op = _FILTER_OPS.get((having.get("op") or "").lower())
        if op is None or op == "IN" or op == "LIKE":   # HAVING 只支持比较
            op = ">" if op is None else op
        if having.get("value") in (None, ""):
            return None
        return {"op": op, "value": having.get("value")}

    # 属性表达式 → SQL（多实体自动 JOIN）
    def _resolve_attr_aggregate(self, expr: str, filters: list, rank: Optional[dict] = None):
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

        # 分组维度（group_by）：解析其实体/列，必要时并入 JOIN
        group_ent = group_col = None
        if rank and rank.get("group_by"):
            gc = self.ontology.get_concept(rank["group_by"])
            group_col = self._attr_column(rank["group_by"])
            group_ent = gc.attrs.get("entity") if gc else None
            if not (gc and group_col and group_ent):
                return None
            if group_ent not in ent_order:
                ent_order.append(group_ent)

        # 过滤属性可能引入新实体（度量/维度过滤，跨实体自动 JOIN）
        for f in (filters or []):
            fc = self.ontology.get_concept(f.get("concept")) if f.get("concept") else None
            fent = fc.attrs.get("entity") if fc else None
            if fent and fent not in ent_order and self._attr_column(f.get("concept")):
                ent_order.append(fent)

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

        # 分组 / 排序 / TopN / HAVING
        rank = rank or {}
        group_ok = bool(group_ent and group_col)
        if group_ok:
            label_ref = col_ref(group_ent, group_col)
            top = f"TOP ({int(rank['limit'])}) " if rank.get("limit") else ""
            sql = f"SELECT {top}{label_ref} AS label, {resolved_expr} AS value FROM {from_sql}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += f" GROUP BY {label_ref}"
            if rank.get("having"):
                sql += f" HAVING {resolved_expr} {rank['having']['op']} ?"
                params.append(rank['having']['value'])
            sql += f" ORDER BY value {rank.get('order', 'DESC')}"
        else:
            sql = f"SELECT {resolved_expr} AS value FROM {from_sql}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            # 无 group_by 的 HAVING：整体聚合值过滤
            if rank.get("having"):
                sql += f" HAVING {resolved_expr} {rank['having']['op']} ?"
                params.append(rank['having']['value'])
        return sql, params, resolver

    # 过滤条件 → WHERE（维度/度量均可过滤；op 白名单；多实体时加别名前缀）
    def _build_where(self, filters: list, meta: dict, single: bool):
        where, params = [], []
        for f in (filters or []):
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
            op = _FILTER_OPS.get((f.get("op") or "=").lower(), "=")
            value = f.get("value")
            if op == "IN":
                vals = value if isinstance(value, list) else [value]
                vals = [v for v in vals if v not in (None, "")]
                if not vals:
                    continue
                where.append(f"{col} IN ({','.join('?' * len(vals))})")
                params.extend(vals)
            else:
                if value in (None, ""):
                    continue
                where.append(f"{col} {op} ?")
                params.append(value)
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
        resolver = self._concept_resolver(node.concept)
        if not self._allowed(resolver):
            resolver = self._first_with_operator("ASK")
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
        if not self._allowed(resolver):
            resolver = self._first_with_operator("ACT")
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

    def _first_with_operator(self, op: str) -> Optional[str]:
        """在允许集内，找第一个能执行算子 op 的 resolver（按算子能力，不看类型名）。"""
        if not self.registry:
            return None
        for r in self.registry.all_resolvers():
            if not self._allowed(r.name):
                continue
            if op in getattr(r, "operators", set()):
                return r.name
        return None
