"""优化器：逻辑 SQG → 物理执行计划（多节点 / 多算子）。

- AGGREGATE：据指标 concept 的绑定拼下推 SQL（选中数据源）。
- ASK：路由到 agent（LLM）resolver，call 带回填用的 prompt。
- ACT：路由到 action resolver，call 带动作 + 描述。
resolver 选择优先看 concept 绑定，缺失则按 registry 里的 resolver 类型兜底。
分波（wave）由 depends_on 拓扑排序算出。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from nexus.core.models import (
    SQG, QueryPlan, PlanNode, Operator, ExecContext, topo_waves,
    QuerySpec, QueryJoin, QueryFilter, QueryHaving, QuerySelect,
)
from nexus.ontology.store import OntologyStore
from nexus.engine.relations import join_tree

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

        # 第一层（无依赖）AGGREGATE 参与融合优化；其余节点常规处理。
        first_ids = {n.id for n in sqg.nodes
                     if n.operator == Operator.AGGREGATE and not n.depends_on}
        resolved = []                       # [(sqgnode, spec, resolver)]
        for n in sqg.nodes:
            if n.id not in first_ids:
                continue
            if self._is_cross_source(n):            # 跨源：分解成 fetch + join + 聚合
                nodes += self._plan_cross_source(n, sqg, ctx)
                continue
            ok, reason = self._agg_spec(n)
            if ok:
                resolved.append((n, ok[0], ok[1]))
            else:                           # 无法规划 → 失败节点（不静默丢弃）
                nodes.append(self._failed_agg(n.id, n.name, list(n.depends_on), reason))
        nodes += self._fuse_aggregates(resolved, sqg, ctx)

        for n in sqg.nodes:
            if n.id in first_ids:
                continue                    # 已在融合里处理
            pn = self._plan_node(n, ctx)
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
    def _plan_node(self, node, ctx: Optional[ExecContext] = None) -> Optional[PlanNode]:
        if node.operator == Operator.AGGREGATE:
            return self._plan_aggregate(node, ctx)
        if node.operator == Operator.ASK:
            return self._plan_ask(node)
        if node.operator == Operator.ACT:
            return self._plan_act(node)
        return None

    # ── AGGREGATE → 下推 SQL ──
    def _plan_aggregate(self, node, ctx: Optional[ExecContext] = None) -> Optional[PlanNode]:
        ok, reason = self._agg_spec(node)
        if not ok:
            return self._failed_agg(node.id, node.name, list(node.depends_on), reason)
        spec, resolver = ok
        return self._compile_agg_node(node.id, node.name, spec, resolver,
                                      list(node.depends_on), ctx)

    # 失败节点：无法规划取数时产出一个带错因的节点（协调器会标红，不静默消失）
    def _failed_agg(self, node_id, name, depends_on, reason) -> PlanNode:
        return PlanNode(
            id=node_id, operator=Operator.AGGREGATE, name=name, resolver="",
            call={"node_id": node_id, "error": reason or "无法生成取数计划"},
            depends_on=depends_on,
        )

    # ── 跨源：检测 + 分解（各源单独 fetch → 计算引擎里 join → 原聚合算子在合并结果上跑）──
    def _referenced_entities(self, node) -> list:
        """本聚合直接引用到的实体（measure/group_by/filters 里出现的属性所属实体），保序。"""
        expr = self._aggregate_expr(node)
        if not expr:
            return []
        ids = list(_ATTR_TOKEN.findall(expr))
        if node.params.get("group_by"):
            ids.append(node.params["group_by"])
        for f in node.params.get("filters", []) or []:
            if f.get("concept"):
                ids.append(f["concept"])
        out: list = []
        for tid in ids:
            c = self.ontology.get_concept(tid)
            ent = c.attrs.get("entity") if c else None
            if ent and ent not in out:
                out.append(ent)
        return out

    def _is_cross_source(self, node) -> bool:
        """跨源判定：把被引用实体用关系图连通（含中间表），只要连接链上任一实体
        与其它实体不同源，即按跨源处理。"""
        ents = self._referenced_entities(node)
        if len(ents) <= 1:
            return False
        tree = join_tree(self.ontology, ents)
        if tree is None:
            return False                    # 连不通 → 交给下游产失败节点（不在此拦）
        ordered, _ = tree
        resolvers = {self._entity_binding(e)[1] for e in ordered}
        resolvers.discard(None)
        return len(resolvers) > 1

    @staticmethod
    def _local(entity_id: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", entity_id.split(".")[-1]) or "e"

    def _galias(self, entity_id: str, col: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]", "_", f"{self._local(entity_id)}__{col}")

    def _plan_cross_source(self, node, sqg: SQG, ctx: Optional[ExecContext] = None) -> list:
        """跨源聚合分解：每源一个 FETCH（下推自己的过滤、列名加实体前缀去重）→ 一个
        JOIN 节点在计算引擎里合并 → 原聚合节点(id=node.id)在合并结果上做 group/agg/having/top。"""
        def fail(reason):
            return [self._failed_agg(node.id, node.name, list(node.depends_on), reason)]

        expr = self._aggregate_expr(node)
        if not expr:
            return fail("无法确定聚合口径")
        filters = node.params.get("filters", []) or []
        group_by = node.params.get("group_by")
        order = (node.params.get("order") or "desc").lower()
        order = "ASC" if order == "asc" else "DESC"
        try:
            limit = int(node.params.get("limit")) if node.params.get("limit") is not None else None
        except (TypeError, ValueError):
            limit = None
        having = self._clean_having(node.params.get("having"))

        # 解析 measure 里的属性 token → (entity, col)
        tokens = list(dict.fromkeys(_ATTR_TOKEN.findall(expr)))
        info: dict[str, tuple[str, str]] = {}
        ent_order: list[str] = []
        for tid in tokens:
            c = self.ontology.get_concept(tid)
            col = self._attr_column(tid)
            ent = c.attrs.get("entity") if c else None
            if not (c and col and ent):
                return fail(f"属性未解析/未绑定列：{tid}")
            info[tid] = (ent, col)
            if ent not in ent_order:
                ent_order.append(ent)

        group_ent = group_col = None
        if group_by:
            gc = self.ontology.get_concept(group_by)
            group_col = self._attr_column(group_by)
            group_ent = gc.attrs.get("entity") if gc else None
            if not (gc and group_col and group_ent):
                return fail(f"分组维度未解析/未绑定列：{group_by}")
            if group_ent not in ent_order:
                ent_order.append(group_ent)

        # 过滤按所属实体归类（各自下推）
        filt_by_ent: dict[str, list] = {}
        for f in filters:
            cid = f.get("concept")
            col = self._attr_column(cid)
            c = self.ontology.get_concept(cid) if cid else None
            fent = c.attrs.get("entity") if c else None
            if not (col and fent):
                continue
            if fent not in ent_order:
                ent_order.append(fent)
            op = _FILTER_OPS.get((f.get("op") or "=").lower(), "=")
            filt_by_ent.setdefault(fent, []).append(
                QueryFilter(col=col, op=op, value=f.get("value"), value_format=f.get("value_format")))

        # 用关系图把被引用实体连通（含中间表）：ent_order 扩为整条链，edges 为连接树
        tree = join_tree(self.ontology, ent_order)
        if tree is None:
            return fail("跨源聚合缺少关系(relation)：被引用的实体之间没有任何通路。请在本体连上外键关系。")
        ent_order, edges = tree

        # 实体 → (表, resolver)
        meta: dict[str, dict] = {}
        for ent in ent_order:
            table, rsv = self._entity_binding(ent)
            if not table:
                return fail(f"实体未绑定物理表：{ent}")
            if not self._allowed(rsv):
                return fail(f"数据源不在本体允许集：{rsv}")
            meta[ent] = {"table": table, "resolver": rsv}

        # 每实体需要取的列 = 被引用列 + join 键（中间表通常只取 join 键）
        needed = {e: set() for e in ent_order}
        for _, (e, col) in info.items():
            needed[e].add(col)
        if group_ent:
            needed[group_ent].add(group_col)
        for e, flist in filt_by_ent.items():
            for qf in flist:
                needed[e].add(qf.col)
        for (fe, fk, te, tk) in edges:
            needed[fe].add(fk)
            needed[te].add(tk)

        # FETCH 节点（各源下推过滤，列名加实体前缀去重）；表名=fetch 节点 id
        out_nodes: list = []
        fetch_id: dict[str, str] = {}
        for i, ent in enumerate(ent_order):
            rsv = meta[ent]["resolver"]
            robj = self.registry.resolver(rsv) if self.registry else None
            if robj is None:
                return fail(f"resolver 缺失：{rsv}")
            selects = [QuerySelect(alias=self._galias(ent, col), expr=col)
                       for col in sorted(needed[ent])]
            fspec = QuerySpec(from_table=meta[ent]["table"], selects=selects,
                              filters=filt_by_ent.get(ent, []))
            fid = self._unique_id(f"f_{node.id}_{i}", sqg)
            call = robj.compile(fspec)
            call["node_id"] = fid
            fetch_id[ent] = fid
            self._log_node(ctx, fid, fspec, call)
            out_nodes.append(PlanNode(id=fid, operator=Operator.SELECT,
                                      name=f"取数·{self._local(ent)}", resolver=rsv,
                                      call=call, depends_on=[]))

        # JOIN 节点（计算引擎）：各 fetch 结果物化后连接成一张统一表
        alias_of = {ent_order[0]: "a0"}
        jjoins = []
        for k, (fe, fk, te, tk) in enumerate(edges, start=1):
            new_ent = ent_order[k]
            alias_of[new_ent] = f"a{k}"
            jjoins.append(QueryJoin(
                table=fetch_id[new_ent], alias=alias_of[new_ent],
                on_left=f"{alias_of[fe]}.{self._galias(fe, fk)}",
                on_right=f"{alias_of[te]}.{self._galias(te, tk)}",
            ))
        join_spec = QuerySpec(from_table=fetch_id[ent_order[0]], from_alias="a0", joins=jjoins)
        join_tbl = self._unique_id(f"jt_{node.id}", sqg)
        join_nid = self._unique_id(f"j_{node.id}", sqg)
        join_call = {
            "node_id": join_nid,
            "loads": [{"table": fetch_id[e], "from_node": fetch_id[e]} for e in ent_order],
            "spec": join_spec.model_dump(),
            "into": join_tbl,
        }
        self._log_node(ctx, join_nid, join_spec, {k: v for k, v in join_call.items() if k != "node_id"})
        out_nodes.append(PlanNode(id=join_nid, operator=Operator.JOIN, name="跨源连接",
                                  resolver="(compute)", call=join_call,
                                  depends_on=[fetch_id[e] for e in ent_order]))

        # 最终聚合节点（id=逻辑 node.id，计算引擎）：在合并表上 group/agg/having/top
        resolved_expr = expr
        for tid in sorted(tokens, key=len, reverse=True):
            ent, col = info[tid]
            resolved_expr = resolved_expr.replace(tid, self._galias(ent, col))
        agg_spec = QuerySpec(
            from_table=join_tbl,
            value_expr=resolved_expr,
            label_expr=(self._galias(group_ent, group_col) if group_ent else None),
            order=order,
            limit=(limit if group_ent else None),
            having=(QueryHaving(expr=resolved_expr, op=having["op"], value=having["value"]) if having else None),
        )
        agg_call = {"node_id": node.id, "spec": agg_spec.model_dump()}
        self._log_node(ctx, node.id, agg_spec, {"spec": "compute"})
        out_nodes.append(PlanNode(id=node.id, operator=Operator.AGGREGATE, name=node.name,
                                  resolver="(compute)", call=agg_call, depends_on=[join_nid]))
        return out_nodes

    def _log_node(self, ctx, node_id, spec, call):
        if ctx is not None:
            ctx.stage_logs.setdefault("nodes", {})[node_id] = {
                "query_spec": spec.model_dump(), "call": call,
            }


    # 解析一个 AGGREGATE 节点 → ((QuerySpec, resolver) | None, reason)；不编译（供融合先分组）
    def _agg_spec(self, node):
        expr = self._aggregate_expr(node)
        if not expr:
            return None, "无法确定聚合口径（需要有效的指标或度量属性）"
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
        if isinstance(resolved, str):
            return None, resolved                      # 具体原因（如缺少关系）
        if resolved is None:
            return None, "无法解析取数（检查属性绑定/度量类型）"
        spec, resolver = resolved
        if not self._allowed(resolver):
            return None, f"数据源不在本体允许集：{resolver}"
        return (spec, resolver), None

    # QuerySpec + resolver → PlanNode（编译成 call + 落 logs）
    def _compile_agg_node(self, node_id, name, spec, resolver, depends_on,
                          ctx: Optional[ExecContext] = None) -> Optional[PlanNode]:
        robj = self.registry.resolver(resolver) if self.registry else None
        if robj is None:
            return None
        call = robj.compile(spec)
        call["node_id"] = node_id
        # 记录本节点的 QuerySpec 与 resolver 编译出的调用语句（落 optimizer stage 的 logs）
        if ctx is not None:
            ctx.stage_logs.setdefault("nodes", {})[node_id] = {
                "query_spec": spec.model_dump(),
                "call": {k: v for k, v in call.items() if k != "node_id"},
            }
        return PlanNode(
            id=node_id, operator=Operator.AGGREGATE, name=name, resolver=resolver,
            call=call, depends_on=depends_on,
        )

    # ── 融合调度：同一次扫描（同源/表/JOIN/分组）内，按过滤情形派发 P1 / P2 ──
    def _fuse_aggregates(self, resolved: list, sqg: SQG,
                         ctx: Optional[ExecContext] = None) -> list:
        groups: dict[str, list] = {}
        order: list[str] = []
        for node, spec, resolver in resolved:
            # 安全前提：无 TopN、无 HAVING 才可融合（否则单独一个节点）
            if spec.limit is not None or spec.having is not None:
                key = f"__solo__{node.id}"
            else:
                key = self._scan_key(spec, resolver)      # 不含 filters：同一次扫描
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append((node, spec, resolver))

        out: list = []
        seq = [0]                                        # 合并节点计数（可变，供递归共享）
        for key in order:
            out += self._merge_scan_group(groups[key], sqg, ctx, seq)
        return out

    def _merge_scan_group(self, members: list, sqg: SQG, ctx, seq: list) -> list:
        """一个「同扫描」组：同过滤→P1；不同过滤且全单聚合→P2；否则按过滤再分组退回 P1。"""
        if len(members) == 1:
            node, spec, resolver = members[0]
            pn = self._compile_agg_node(node.id, node.name, spec, resolver,
                                        list(node.depends_on), ctx)
            return [pn] if pn else []

        same_filter = len({self._filters_key(s) for (_, s, _) in members}) == 1
        if same_filter:
            return self._merge_p1(members, sqg, ctx, seq)

        parts = [self._split_single_agg(s.value_expr) for (_, s, _) in members]
        if all(parts):
            return self._merge_p2(members, parts, sqg, ctx, seq)

        # 退化：过滤不同 + 有复合口径（难改写 CASE）→ 按过滤再分组，各子组走 P1
        subs: dict[str, list] = {}
        suborder: list[str] = []
        for item in members:
            k = self._filters_key(item[1])
            if k not in subs:
                subs[k] = []
                suborder.append(k)
            subs[k].append(item)
        out: list = []
        for k in suborder:
            out += self._merge_scan_group(subs[k], sqg, ctx, seq)
        return out

    # P1：同过滤、只测度不同 → 过滤上提 WHERE，多测度 select（任意测度/复合口径都行）
    def _merge_p1(self, members: list, sqg: SQG, ctx, seq: list) -> list:
        _, base_spec, resolver = members[0]
        selects = [QuerySelect(alias=f"v_{n.id}", expr=s.value_expr) for (n, s, _) in members]
        merged_spec = base_spec.model_copy(update={"selects": selects})
        return self._emit_merge(members, merged_spec, resolver, sqg, ctx, seq, "P1")

    # P2：不同过滤、全单聚合 → agg(CASE WHEN 各自过滤 THEN inner END)，一次扫描分流
    def _merge_p2(self, members: list, parts: list, sqg: SQG, ctx, seq: list) -> list:
        _, base_spec, resolver = members[0]
        selects = []
        for (n, s, _), (agg, inner) in zip(members, parts):
            selects.append(QuerySelect(alias=f"v_{n.id}", agg=agg, inner=inner, filters=s.filters))
        # 合并节点 WHERE 清空（过滤都进了各自 CASE）；保留 from/join/label
        merged_spec = base_spec.model_copy(update={"selects": selects, "filters": []})
        return self._emit_merge(members, merged_spec, resolver, sqg, ctx, seq, "P2")

    # 产出：一个合并节点 + 每逻辑 id 一个 PROJECT 拆分节点（P1/P2 共用）
    def _emit_merge(self, members, merged_spec, resolver, sqg, ctx, seq, tag) -> list:
        seq[0] += 1
        merged_id = self._unique_id(f"m{seq[0]}", sqg)
        mname = "合并取数：" + "+".join(n.name for (n, _, _) in members)
        mpn = self._compile_agg_node(merged_id, mname, merged_spec, resolver, [], ctx)
        if mpn is None:                              # 合并失败：退回各自单节点
            out = []
            for (n, s, rsv) in members:
                p = self._compile_agg_node(n.id, n.name, s, rsv, list(n.depends_on), ctx)
                if p:
                    out.append(p)
            return out
        out = [mpn]
        for (n, s, rsv) in members:
            out.append(PlanNode(
                id=n.id, operator=Operator.PROJECT, name=n.name, resolver="(merge)",
                call={"node_id": n.id, "from": merged_id, "column": f"v_{n.id}"},
                depends_on=[merged_id],
            ))
        return out

    def _scan_key(self, spec: QuerySpec, resolver: str) -> str:
        """同一次扫描的键：同源/表/JOIN/分组（不含 filters —— P2 允许过滤不同）。"""
        return json.dumps({
            "r": resolver,
            "from": spec.from_table, "alias": spec.from_alias,
            "joins": [j.model_dump() for j in spec.joins],
            "label": spec.label_expr,
        }, sort_keys=True, ensure_ascii=False, default=str)

    def _filters_key(self, spec: QuerySpec) -> str:
        return json.dumps([f.model_dump() for f in spec.filters],
                          sort_keys=True, ensure_ascii=False, default=str)

    _SINGLE_AGG = re.compile(r"\s*(SUM|AVG|MIN|MAX|COUNT)\s*\((.+)\)\s*$", re.IGNORECASE)

    def _split_single_agg(self, expr: str):
        """把 `AGG(inner)` 拆成 (AGG, inner)；复合口径（SUM(a)-SUM(b) 等）返回 None。"""
        m = self._SINGLE_AGG.fullmatch(expr or "")
        if not m:
            return None
        inner = m.group(2)
        depth = 0                                    # 校验 inner 括号平衡、不提前闭合
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return None
        if depth != 0:
            return None
        return m.group(1).upper(), inner

    def _unique_id(self, base: str, sqg: SQG) -> str:
        existing = {n.id for n in sqg.nodes}
        cand, i = base, 0
        while cand in existing:
            i += 1
            cand = f"{base}_{i}"
        return cand

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
        if not mc:
            return None
        agg = (node.params.get("agg") or "SUM").upper()
        if agg not in _AGG_FUNCS:
            return None
        dtype = mc.attrs.get("dtype")
        if agg in _AGG_NEEDS_NUMBER:
            # SUM/AVG：只对数值度量有意义
            if mc.attrs.get("role") != "measure" or dtype not in (None, "number"):
                return None
            if mc.attrs.get("additivity") == "non_additive" and agg == "SUM":
                return None   # 比率/百分比等不可加：禁 SUM
        # MIN/MAX/COUNT：对任意属性（数值/日期/文本/维度）都合法，不要求 role=measure
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
            return "聚合表达式里没有可解析的属性"
        info: dict[str, tuple[str, str]] = {}     # attr_id -> (entity_id, column)
        ent_order: list[str] = []
        for tid in tokens:
            c = self.ontology.get_concept(tid)
            col = self._attr_column(tid)
            ent = c.attrs.get("entity") if c else None
            if not (c and col and ent):
                return f"属性无法解析或未绑定物理列：{tid}"
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
                return f"分组维度无法解析或未绑定列：{rank['group_by']}"
            if group_ent not in ent_order:
                ent_order.append(group_ent)

        # 过滤属性可能引入新实体（度量/维度过滤，跨实体自动 JOIN）
        for f in (filters or []):
            fc = self.ontology.get_concept(f.get("concept")) if f.get("concept") else None
            fent = fc.attrs.get("entity") if fc else None
            if fent and fent not in ent_order and self._attr_column(f.get("concept")):
                ent_order.append(fent)

        # 用关系图把被引用实体连通（含中间表）：ent_order 扩为整条链，tree_edges 为连接树
        tree = join_tree(self.ontology, ent_order)
        if tree is None:
            return ("跨表聚合缺少关系(relation)：被引用的实体之间没有任何通路。"
                    "请在本体画布上连上对应的外键关系。")
        ent_order, tree_edges = tree

        # 实体 → 表/resolver/别名
        meta: dict[str, dict] = {}
        resolver = None
        for i, ent in enumerate(ent_order):
            table, rsv = self._entity_binding(ent)
            if not table:
                return f"实体未绑定物理表：{ent}"
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

        # FROM / JOIN（结构化，别名/关系已解析；具体 SQL 由 resolver 渲染）
        first = ent_order[0]
        from_table = meta[first]["table"]
        from_alias = None if single else meta[first]["alias"]
        joins: list[QueryJoin] = []
        if not single:
            for k in range(1, len(ent_order)):
                ent = ent_order[k]
                fe, fk, te, tk = tree_edges[k - 1]
                joins.append(QueryJoin(
                    table=meta[ent]["table"], alias=meta[ent]["alias"],
                    on_left=f'{meta[fe]["alias"]}.{fk}',
                    on_right=f'{meta[te]["alias"]}.{tk}',
                ))

        filter_specs = self._build_where(filters, meta, single)

        # 分组 / 排序 / TopN / HAVING
        rank = rank or {}
        group_ok = bool(group_ent and group_col)
        having = None
        if rank.get("having"):
            having = QueryHaving(
                expr=resolved_expr,
                op=rank["having"]["op"], value=rank["having"]["value"],
            )
        spec = QuerySpec(
            value_expr=resolved_expr,
            label_expr=col_ref(group_ent, group_col) if group_ok else None,
            from_table=from_table, from_alias=from_alias,
            joins=joins, filters=filter_specs,
            order=rank.get("order", "DESC"),
            limit=rank.get("limit") if group_ok else None,
            having=having,
        )
        return spec, resolver

    # 过滤条件 → QueryFilter 列表（维度/度量均可过滤；op 白名单；多实体时加别名前缀）
    def _build_where(self, filters: list, meta: dict, single: bool) -> list:
        out: list[QueryFilter] = []
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
                out.append(QueryFilter(col=col, op=op, value=vals))
            else:
                if value in (None, ""):
                    continue
                out.append(QueryFilter(col=col, op=op, value=value,
                                       value_format=f.get("value_format")))
        return out

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
