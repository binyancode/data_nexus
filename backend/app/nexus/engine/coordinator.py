"""协调器：解释物理 DAG 并按依赖执行。

职责：
  1. 分波：优先用优化器算好的 node.wave；缺失则按 depends_on 拓扑分波兜底。
  2. 波内并行：同波节点互不依赖，用线程池并发（parallelism 控并发度）。
  3. 回填：执行下游前，用已完成节点的结果替换 call 里的 {nX} 占位符。
  4. 失败隔离：单节点异常只标该节点 failed，依赖它的下游标 skipped，不炸整轮。
  5. 边跑边记：每节点 running → done/failed 立刻写 run_node，供前端轮询上色。
"""

from __future__ import annotations

import json
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from nexus.core.models import QueryPlan, PlanNode, NodeResult, ExecContext, Operator, QuerySpec, topo_waves
from nexus.registry import ResolverRegistry

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _result_value(res: NodeResult):
    """节点的代表值：首行的 value 列（或首个值）；无行则取 output。仅用于「短预览」。"""
    if res is None:
        return None
    if res.rows:
        first = res.rows[0]
        return first.get("value", next(iter(first.values()), None))
    return res.output


_MAX_BACKFILL_ROWS = 200
_MAX_BACKFILL_CHARS = 100000


def _cell(v) -> str:
    return "" if v is None else str(v)


def _render_result(res: NodeResult) -> str:
    """把一个节点结果**完整**渲染成给下游 prompt 用的文本（供 {nX} 回填）：
    - 无行 → output 文本；
    - 单行单列 → 标量值；
    - 多行 → 逐行序列化（label: value / value / k=v），别只给第一行。
    行数过多时截断，避免撑爆提示词。"""
    if res is None:
        return ""
    rows = res.rows or []
    if not rows:
        return "" if res.output is None else str(res.output)
    if len(rows) == 1 and len(rows[0]) == 1:
        return _cell(next(iter(rows[0].values())))

    def fmt_row(r: dict) -> str:
        if "label" in r and "value" in r:
            return f"{r.get('label')}: {_cell(r.get('value'))}"
        if set(r.keys()) == {"value"}:
            return _cell(r.get("value"))
        return ", ".join(f"{k}={_cell(v)}" for k, v in r.items())

    shown = rows[:_MAX_BACKFILL_ROWS]
    body = "；".join(fmt_row(r) for r in shown)
    if len(rows) > len(shown):
        body += f"；…（共 {len(rows)} 行，仅列出前 {len(shown)} 行）"
    if len(body) > _MAX_BACKFILL_CHARS:
        body = body[:_MAX_BACKFILL_CHARS] + "…（内容过长，已截断）"
    return body


class Coordinator:
    def __init__(self, registry: ResolverRegistry):
        self.registry = registry

    def execute(self, plan: QueryPlan, ctx: ExecContext) -> dict[str, NodeResult]:
        ctx.context = plan.context or {}
        parallelism = int(ctx.context.get("parallelism", 4) or 4)
        # 跨源计算：若计划含 compute 节点，每运行建一个内存计算引擎
        if any(getattr(n, "resolver", "") == "(compute)" for n in plan.nodes):
            from nexus.engine.compute import DuckDbCompute
            import threading
            ctx.compute = DuckDbCompute()
            ctx.compute.lock = threading.Lock()
        try:
            for wave in self._waves(plan.nodes):
                if self._cancelled(ctx):
                    break
                self._run_wave(wave, ctx, parallelism)
        finally:
            if ctx.compute is not None:
                ctx.compute.close()
                ctx.compute = None
        return ctx.results

    # ── 分波 ──
    def _waves(self, nodes: list[PlanNode]) -> list[list[PlanNode]]:
        """优先用 node.wave；若有节点缺 wave 则退回拓扑分波。"""
        if nodes and all(getattr(n, "wave", 0) >= 1 for n in nodes):
            buckets: dict[int, list[PlanNode]] = {}
            for n in nodes:
                buckets.setdefault(n.wave, []).append(n)
            return [buckets[w] for w in sorted(buckets)]
        return topo_waves(nodes)

    def _run_wave(self, nodes: list[PlanNode], ctx: ExecContext, parallelism: int) -> None:
        if len(nodes) == 1:
            self._run_node(nodes[0], ctx)
            return
        with ThreadPoolExecutor(max_workers=min(parallelism, len(nodes))) as ex:
            list(ex.map(lambda n: self._run_node(n, ctx), nodes))

    # ── 单节点执行（回填 + 取数 + 记录）──
    def _run_node(self, node: PlanNode, ctx: ExecContext) -> None:
        t0 = time.time()
        call = self._backfill(node.call, ctx.results)
        ctx.recorder.start_node(ctx.run_id, node.id, node.resolver, _dumps(call))

        # 上游失败则跳过（失败隔离）
        if self._upstream_failed(node, ctx):
            res = NodeResult(node_id=node.id, resolver=node.resolver,
                             error="skipped: upstream failed", source="")
            ctx.results[node.id] = res
            ctx.recorder.finish_node(ctx.run_id, node.id, "skipped", _dumps(call),
                                     None, None, "", res.trust, res.error,
                                     int((time.time() - t0) * 1000))
            return

        resolver = self.registry.resolver(node.resolver)
        if isinstance(call, dict) and call.get("error"):
            # 优化器已判定无法规划（如缺少关系）：直接标失败，不去找 resolver
            res = NodeResult(node_id=node.id, resolver=node.resolver, error=str(call["error"]))
        elif node.resolver == "(compute)":
            res = self._compute(node, call, ctx)          # 跨源：内存计算引擎执行 JOIN / 聚合
        elif node.operator == Operator.PROJECT:
            res = self._project(node, call, ctx)          # 融合拆分：从合并节点取一列，不调 resolver
        elif not resolver:
            res = NodeResult(node_id=node.id, resolver=node.resolver,
                             error=f"resolver not found: {node.resolver}")
        else:
            try:
                res = resolver.fetch(call, ctx)
            except Exception:
                res = NodeResult(node_id=node.id, resolver=node.resolver,
                                 error=traceback.format_exc())

        ctx.results[node.id] = res
        state = "failed" if res.error else "done"
        value = _result_value(res)
        # 自定义日志：取数类节点额外记 resolver 返回的行数
        node_logs = dict(res.logs) if res.logs else {}
        n_rows = len(res.rows) if isinstance(res.rows, list) else 0
        if node.operator not in (Operator.ASK, Operator.ACT) and isinstance(res.rows, list):
            node_logs["row_count"] = n_rows
        # 值预览：多行结果标注总条数，避免只显示第一行让人误以为只有一条
        preview = None if value is None else str(value)[:200]
        if preview is not None and n_rows > 1:
            preview = f"{str(value)[:160]} 等 {n_rows} 项"
        ctx.recorder.finish_node(
            ctx.run_id, node.id, state, _dumps(call),
            _dumps(res.rows), preview,
            res.source, res.trust, res.error, int((time.time() - t0) * 1000),
            (_dumps(node_logs) if node_logs else None),
        )

    # ── 跨源：内存计算引擎执行 JOIN / 聚合（load 上游 fetch 结果 → run QuerySpec）──
    def _compute(self, node: PlanNode, call: dict, ctx: ExecContext) -> NodeResult:
        eng = ctx.compute
        if eng is None:
            return NodeResult(node_id=node.id, resolver="(compute)", error="compute engine 未初始化")
        try:
            with eng.lock:
                for ld in call.get("loads", []) or []:
                    src = ctx.results.get(ld.get("from_node"))
                    eng.load(ld["table"], (src.rows if src and src.rows else []))
                spec = QuerySpec(**call["spec"])
                rows = eng.run(spec, into=call.get("into"))
        except Exception:
            return NodeResult(node_id=node.id, resolver="(compute)",
                              error=traceback.format_exc(), source="compute")
        cols = list(rows[0].keys()) if rows else []
        return NodeResult(node_id=node.id, resolver="(compute)", output=rows,
                          columns=cols, rows=rows, source="compute",
                          detail=call.get("into") or "join/aggregate")

    # ── 融合拆分：从合并节点结果里取一列，产出与单聚合等价的 NodeResult ──
    def _project(self, node: PlanNode, call: dict, ctx: ExecContext) -> NodeResult:
        src = ctx.results.get(call.get("from"))
        col = call.get("column")
        if src is None:
            return NodeResult(node_id=node.id, resolver="(merge)",
                              error=f"merge source not found: {call.get('from')}")
        rows = []
        for r in (src.rows or []):
            row = {}
            if "label" in r:
                row["label"] = r["label"]
            row["value"] = r.get(col)
            rows.append(row)
        cols = ["label", "value"] if (rows and "label" in rows[0]) else ["value"]
        return NodeResult(node_id=node.id, resolver="(merge)", output=rows,
                          columns=cols, rows=rows, source=src.source,
                          detail=f"从合并节点 {call.get('from')} 取列 {col}")

    # ── 回填 {nX} ──
    def _backfill(self, call, results: dict[str, NodeResult]):
        if not isinstance(call, dict):
            return call

        def sub(v):
            if isinstance(v, str):
                return _PLACEHOLDER.sub(
                    lambda m: _render_result(results[m.group(1)])
                    if m.group(1) in results else m.group(0),
                    v,
                )
            if isinstance(v, list):
                return [sub(x) for x in v]
            if isinstance(v, dict):
                return {k: sub(x) for k, x in v.items()}
            return v

        return {k: sub(v) for k, v in call.items()}

    def _upstream_failed(self, node: PlanNode, ctx: ExecContext) -> bool:
        for dep in node.depends_on:
            up = ctx.results.get(dep)
            if up is not None and up.error:
                return True
        return False

    def _cancelled(self, ctx: ExecContext) -> bool:
        tok = ctx.cancellation_token
        return bool(tok and getattr(tok, "is_cancelled", False))
