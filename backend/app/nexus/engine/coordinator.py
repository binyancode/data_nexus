"""Execute a Fragment PEP and publish physical outputs as logical SQG results."""

from __future__ import annotations

import json
import math
from string import Formatter
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from nexus.core.expressions import (
    BinaryExpr, FunctionExpr, LiteralExpr, NodeOutputExpr, OutputExpr, UnaryExpr,
)
from nexus.core.logical import CalculateSpec, InputRef
from nexus.core.models import ExecContext, NodeResult, topo_waves
from nexus.core.physical import (
    CapabilityFragment, ComputeFragment, ExchangeFragment, PhysicalExecutionPlan,
    SourceFragment,
)
from nexus.registry import ResolverRegistry
from nexus.engine.compute_registry import ComputeEngineRegistry


def _dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


class Coordinator:
    def __init__(self, registry: ResolverRegistry,
                 compute_registry: ComputeEngineRegistry | None = None):
        self.registry = registry
        self.compute_registry = compute_registry

    def execute(self, plan: PhysicalExecutionPlan, ctx: ExecContext) -> dict[str, NodeResult]:
        ctx.context = {**ctx.context, **(plan.context or {})}
        ctx.physical_results = {}
        parallelism = int(ctx.context.get("parallelism", 4) or 4)
        needs_compute = any(isinstance(node, ComputeFragment) for node in plan.nodes)
        if needs_compute:
            if self.compute_registry is not None:
                ctx.compute = self.compute_registry.create(ctx.compute_engine_name, ctx.run_id)
            else:  # 单元测试/嵌入调用的向后兼容默认值
                from nexus.engine.compute import DuckDbCompute
                ctx.compute = DuckDbCompute()
        try:
            for wave in self._waves(plan):
                if self._cancelled(ctx):
                    break
                self._run_wave(wave, ctx, parallelism)
        finally:
            llm_calls = [
                call
                for result in ctx.physical_results.values()
                for call in (result.logs or {}).get("llm_calls", [])
            ]
            if llm_calls:
                ctx.stage_logs["llm_calls"] = llm_calls
            if ctx.compute is not None:
                ctx.compute.close()
                ctx.compute = None
        return ctx.results

    @staticmethod
    def _waves(plan: PhysicalExecutionPlan):
        if plan.nodes and all(node.wave >= 1 for node in plan.nodes):
            buckets = {}
            for node in plan.nodes:
                buckets.setdefault(node.wave, []).append(node)
            return [buckets[index] for index in sorted(buckets)]
        return topo_waves(plan.nodes)

    def _run_wave(self, nodes, ctx, parallelism):
        if len(nodes) == 1:
            self._run_node(nodes[0], ctx)
            return
        with ThreadPoolExecutor(max_workers=min(parallelism, len(nodes))) as executor:
            list(executor.map(lambda node: self._run_node(node, ctx), nodes))

    def _run_node(self, node, ctx: ExecContext):
        started = time.time()
        resolver_name = self._resolver_name(node)
        call = self._call(node)
        ctx.recorder.start_node(ctx.run_id, node.id, resolver_name, _dumps(call))
        if self._upstream_failed(node, ctx):
            result = NodeResult(node_id=node.id, resolver=resolver_name,
                                error="skipped: upstream failed")
            state = "skipped"
        else:
            try:
                result = self._execute_node(node, call, ctx)
            except Exception:
                result = NodeResult(node_id=node.id, resolver=resolver_name,
                                    error=traceback.format_exc())
            state = "failed" if result.error else "done"
        ctx.physical_results[node.id] = result
        self._publish(node, result, ctx)
        logs = dict(result.logs or {})
        logs["row_count"] = len(result.rows or [])
        preview = self._preview(result)
        ctx.recorder.finish_node(
            ctx.run_id, node.id, state, _dumps(call), _dumps(result.rows), preview,
            result.source, result.trust, result.error,
            int((time.time() - started) * 1000), _dumps(logs),
        )

    def _execute_node(self, node, call, ctx):
        if isinstance(node, SourceFragment):
            resolver = self.registry.resolver(node.source_instance)
            if resolver is None:
                return NodeResult(node_id=node.id, error=f"resolver not found: {node.source_instance}")
            return resolver.fetch(call, ctx)
        if isinstance(node, ComputeFragment):
            return self._compute(node, ctx)
        if isinstance(node, ExchangeFragment):
            source = ctx.physical_results.get(node.from_fragment)
            if source is None:
                return NodeResult(node_id=node.id, error=f"exchange source missing: {node.from_fragment}")
            return NodeResult(node_id=node.id, resolver="(exchange)", rows=list(source.rows),
                              columns=list(source.columns), output=source.output,
                              source=source.source, detail=node.mode)
        if isinstance(node, CapabilityFragment):
            if node.resolver == "(compute)":
                return self._calculate(node, ctx)
            enriched = self._capability_call(node, call, ctx)
            call.clear()
            call.update(enriched)
            resolver = self.registry.resolver(node.resolver)
            if resolver is None:
                return NodeResult(node_id=node.id, error=f"resolver not found: {node.resolver}")
            return resolver.fetch(enriched, ctx)
        return NodeResult(node_id=node.id, error=f"unsupported plan node: {type(node).__name__}")

    def _compute(self, node: ComputeFragment, ctx: ExecContext):
        engine = ctx.compute
        if engine is None:
            return NodeResult(node_id=node.id, resolver="(compute)", error="compute engine unavailable")
        with engine.lock:
            for item in node.inputs:
                source = ctx.physical_results.get(item.from_fragment)
                engine.load(item.table, list(source.rows) if source else [],
                            list(source.columns) if source else [])
            rows = engine.run(node.query, into=node.into)
        return NodeResult(node_id=node.id, resolver="(compute)", output=rows,
                          rows=rows, columns=list(rows[0]) if rows else [],
                          source=f"compute:{engine.name}",
                          detail=f"typed QueryIR ({engine.engine_type})")

    def _capability_call(self, node: CapabilityFragment, call: dict, ctx: ExecContext):
        result = dict(call)
        inputs = self._resolve_inputs(result.pop("input_refs", {}), ctx)
        result = self._format_input_strings(result, inputs)
        if inputs:
            result["inputs"] = inputs
            if node.operator.value == "ASK":
                result["prompt"] = (result.get("prompt") or result.get("instruction") or "") + \
                    "\n\n输入数据（只可解释和组织，不得修改或重新计算数值）：\n" + _dumps(inputs)
            elif node.operator.value == "ACT":
                result["desc"] = _dumps(inputs)
        if result.get("recipient") and not result.get("assignee"):
            result["assignee"] = result["recipient"]
        return result

    def _resolve_inputs(self, references: dict, ctx: ExecContext) -> dict:
        return {
            name: self._resolve_input(InputRef.model_validate(raw), ctx)
            for name, raw in references.items()
        }

    @staticmethod
    def _resolve_input(reference: InputRef, ctx: ExecContext):
        source = ctx.results.get(reference.node)
        if source is None:
            raise ValueError(f"input source result 不存在：{reference.node}")
        rows = list(source.rows or [])
        if reference.row is not None:
            if reference.row >= len(rows):
                raise ValueError(f"input row {reference.row} 不存在：{reference.node}")
            selected = rows[reference.row]
            if reference.output is None:
                return selected
            if reference.output not in selected:
                raise ValueError(f"input output 不存在：{reference.node}.{reference.output}")
            return selected[reference.output]
        if reference.output is not None:
            missing = [index for index, row in enumerate(rows) if reference.output not in row]
            if missing:
                raise ValueError(
                    f"input output 不存在：{reference.node}.{reference.output}，rows={missing[:5]}"
                )
            return [row[reference.output] for row in rows]
        return rows if rows else source.output

    def _format_input_strings(self, value, inputs: dict):
        if isinstance(value, str):
            try:
                fields = {field_name for _, field_name, _, _ in Formatter().parse(value)
                          if field_name}
            except ValueError:
                return value
            if not fields:
                return value
            if not (fields & set(inputs)):
                return value
            unknown = fields - set(inputs)
            if unknown:
                raise ValueError(f"文本参数引用了未知 inputs：{sorted(unknown)}")
            values = {}
            for field in fields:
                resolved = inputs[field]
                if isinstance(resolved, (dict, list)) or resolved is None:
                    raise ValueError(f"文本参数 input {field!r} 必须是非空标量")
                values[field] = resolved
            return value.format_map(values)
        if isinstance(value, dict):
            return {key: self._format_input_strings(child, inputs)
                    for key, child in value.items()}
        if isinstance(value, list):
            return [self._format_input_strings(child, inputs) for child in value]
        return value

    def _calculate(self, node: CapabilityFragment, ctx: ExecContext):
        spec = CalculateSpec.model_validate(node.call["spec"])
        datasets = {
            alias: list((ctx.results.get(input_ref.node) or NodeResult(node_id=input_ref.node)).rows)
            for alias, raw in node.call.get("input_refs", {}).items()
            for input_ref in [InputRef.model_validate(raw)]
        }
        rows = self._align(datasets, spec.alignment.keys, spec.alignment.domain,
                           spec.alignment.scalar_broadcast)
        calculated = []
        for row in rows:
            output = dict(row.get("_keys", {}))
            values = dict(row.get("_outputs", {}))
            for named in spec.outputs:
                values[named.name] = self._eval(named.expression, row, values)
                output[named.name] = values[named.name]
            calculated.append(output)
        if spec.selection:
            reverse = spec.selection.kind in ("MAX_BY", "TOP_N")
            calculated.sort(key=lambda value: self._sort_value(value.get(spec.selection.field), reverse), reverse=reverse)
            calculated = calculated[:spec.selection.take]
        return NodeResult(node_id=node.id, resolver="(compute)", output=calculated,
                          rows=calculated, columns=list(calculated[0]) if calculated else [],
                          source="compute:calculate", detail="typed CALCULATE")

    @staticmethod
    def _align(datasets, keys, domain, scalar_broadcast):
        aliases = list(datasets)
        if not aliases:
            return []
        if not keys:
            return [{"_keys": {}, "_inputs": {
                alias: (rows[0] if rows else {}) for alias, rows in datasets.items()
            }, "_outputs": {}}]
        indexes = {
            alias: {tuple(row.get(key) for key in keys): row for row in rows}
            for alias, rows in datasets.items()
        }
        key_sets = [set(index) for index in indexes.values()]
        if domain == "INNER":
            selected = set.intersection(*key_sets) if key_sets else set()
        elif domain == "LEFT":
            selected = key_sets[0]
        else:
            selected = set.union(*key_sets) if key_sets else set()
        aligned = []
        for key_tuple in sorted(selected, key=lambda value: tuple(str(v) for v in value)):
            aligned.append({
                "_keys": dict(zip(keys, key_tuple)),
                "_inputs": {alias: index.get(key_tuple, {}) for alias, index in indexes.items()},
                "_outputs": {},
            })
        return aligned

    def _eval(self, expression, row, outputs):
        if isinstance(expression, LiteralExpr):
            return expression.value
        if isinstance(expression, NodeOutputExpr):
            return row.get("_inputs", {}).get(expression.input, {}).get(expression.field)
        if isinstance(expression, OutputExpr):
            return outputs.get(expression.name)
        if isinstance(expression, UnaryExpr):
            value = self._eval(expression.operand, row, outputs)
            return -value if value is not None else None
        if isinstance(expression, BinaryExpr):
            left = self._eval(expression.left, row, outputs)
            right = self._eval(expression.right, row, outputs)
            if left is None or right is None:
                return None
            if expression.operator == "ADD": return left + right
            if expression.operator == "SUBTRACT": return left - right
            if expression.operator == "MULTIPLY": return left * right
            if expression.operator in ("DIVIDE", "SAFE_DIVIDE"):
                if right == 0:
                    if expression.zero_division == "ZERO": return 0
                    if expression.zero_division == "ERROR": raise ZeroDivisionError()
                    return None
                return left / right
        if isinstance(expression, FunctionExpr):
            values = [self._eval(arg, row, outputs) for arg in expression.arguments]
            if expression.name == "COALESCE": return next((v for v in values if v is not None), None)
            if expression.name == "ABS": return abs(values[0])
            if expression.name == "ROUND": return round(values[0], int(values[1]) if len(values) > 1 else 0)
        raise ValueError(f"unsupported calculate expression: {type(expression).__name__}")

    def _publish(self, node, result: NodeResult, ctx: ExecContext):
        for binding in node.realizes:
            rows = list(result.rows or [])
            if binding.physical_field:
                query = getattr(node, "query", None)
                dimension_names = [value.name for value in query.dimensions] if query is not None else []
                rows = [
                    {**{k: row.get(k) for k in dimension_names},
                     binding.logical_field or "value": row.get(binding.physical_field)}
                    for row in rows
                ]
            logical = NodeResult(
                node_id=binding.logical_node, resolver=result.resolver,
                output=rows if rows else result.output,
                rows=rows, columns=list(rows[0]) if rows else [], trust=result.trust,
                error=result.error, source=result.source, detail=result.detail,
                logs=dict(result.logs or {}),
            )
            ctx.results[binding.logical_node] = logical

    @staticmethod
    def _result_payload(result: NodeResult | None):
        if result is None:
            return None
        if result.rows:
            return result.rows
        return result.output

    @staticmethod
    def _sort_value(value, reverse):
        if value is None:
            return -math.inf if reverse else math.inf
        if isinstance(value, Decimal):
            return float(value)
        return value

    @staticmethod
    def _preview(result: NodeResult):
        if result.rows:
            suffix = f" 等 {len(result.rows)} 项" if len(result.rows) > 1 else ""
            suffix_units = len(suffix.encode("utf-16-le")) // 2
            return Coordinator._truncate_utf16(_dumps(result.rows[0]), 200 - suffix_units) + suffix
        return Coordinator._truncate_utf16(str(result.output), 200) if result.output is not None else None

    @staticmethod
    def _truncate_utf16(value: str, max_units: int) -> str:
        encoded = value.encode("utf-16-le")
        if len(encoded) <= max_units * 2:
            return value
        return encoded[:max_units * 2].decode("utf-16-le", errors="ignore")

    @staticmethod
    def _resolver_name(node):
        if isinstance(node, SourceFragment): return node.source_instance
        if isinstance(node, ComputeFragment): return "(compute)"
        if isinstance(node, ExchangeFragment): return "(exchange)"
        return node.resolver

    @staticmethod
    def _call(node):
        if isinstance(node, SourceFragment): return node.call
        if isinstance(node, ComputeFragment): return {"query": node.query.model_dump(mode="json"), "inputs": [i.model_dump() for i in node.inputs]}
        if isinstance(node, ExchangeFragment): return node.model_dump(mode="json")
        return node.call

    @staticmethod
    def _upstream_failed(node, ctx):
        return any((ctx.physical_results.get(dep) and ctx.physical_results[dep].error)
                   for dep in node.depends_on)

    @staticmethod
    def _cancelled(ctx):
        token = ctx.cancellation_token
        return bool(token and getattr(token, "is_cancelled", False))
