"""Natural language -> typed, business-task-grained SQG."""

from __future__ import annotations

import copy
import hashlib
import json
from string import Formatter
import time
from typing import Optional

from pydantic import ValidationError

from nexus.core.logical import (
    ActNode, AggregateNode, AskNode, AttributeDimension, BrowseNode, CalculateNode, Operator,
    SQG, SearchNode, SelectNode,
)
from nexus.core.expressions import (
    AggregateExpr, AndPredicate, AttributeExpr, BinaryExpr, CaseExpr, FunctionExpr,
    InPredicate, NodeOutputExpr, NotPredicate, OrPredicate, TimeBucketExpr, UnaryExpr,
)
from nexus.core.models import ConceptKind, ExecContext
from nexus.engine.binder import Binder, BindingError

_MAX_COMPILE_ATTEMPTS = 2
_SQG_CACHE_TTL_S = 3600
_SQG_CACHE: dict[tuple, tuple[float, float, SQG]] = {}

_PREDICATE_SCHEMA_GUIDE = """Predicate 必须严格使用以下字段名，禁止自创 conditions/attribute/left/right 等替代字段：
- AND：{"kind":"and","operands":[<Predicate>, ...]}
- OR：{"kind":"or","operands":[<Predicate>, ...]}
- NOT：{"kind":"not","operand":<Predicate>}
- 比较：{"kind":"comparison","left":<Expression>,"operator":"EQ|NE|GT|GTE|LT|LTE|LIKE","right":<Expression>}
- IN：{"kind":"in","value":<Expression>,"values":[<Expression>, ...]}
    例：{"kind":"in","value":{"kind":"attribute","concept":"<区域属性id>"},"values":[{"kind":"literal","value":"华东","data_type":"text"},{"kind":"literal","value":"华南","data_type":"text"}]}
- BETWEEN：{"kind":"between","value":<Expression>,"lower":<Expression>,"upper":<Expression>,"lower_inclusive":true,"upper_inclusive":true}
- NULL：{"kind":"null","value":<Expression>,"is_null":true}
- 时间区间：{"kind":"time_range","attribute":"<日期属性id>","start":"YYYY-MM-DD","end_exclusive":"YYYY-MM-DD","timezone":"Asia/Shanghai"}
其中 Expression 的属性引用只能是 {"kind":"attribute","concept":"<attribute id>"}，常量只能是 {"kind":"literal","value":...,"data_type":"text|number|date|datetime|bool"}。"""

_CALCULATE_SCHEMA_GUIDE = """CALCULATE 必须严格使用以下结构。depends_on 表示执行依赖，节点级 inputs 把上游 output 接入当前输入别名；禁止在 spec 内再定义 inputs：
{
    "id": "n3",
    "operator": "CALCULATE",
    "name": "计算比值并找出最低月份",
    "depends_on": ["n1", "n2"],
    "inputs": {
        "median": {"node": "n1"},
        "average": {"node": "n2"}
    },
    "spec": {
        "alignment": {
            "keys": ["period"],
            "domain": "INNER",
            "scalar_broadcast": false
        },
        "outputs": [
            {
                "name": "period",
                "expression": {"kind":"node_output","input":"median","field":"period"}
            },
            {
                "name": "ratio",
                "expression": {
                    "kind": "binary",
                    "operator": "SAFE_DIVIDE",
                    "left": {"kind":"node_output","input":"median","field":"median_amount"},
                    "right": {"kind":"node_output","input":"average","field":"avg_amount"},
                    "zero_division": "NULL"
                }
            }
        ],
        "selection": {
            "kind": "MIN_BY",
            "field": "ratio",
            "take": 1,
            "nulls": "LAST",
            "tie_breakers": [{"field":"period","direction":"ASC","nulls":"LAST"}]
        },
        "result": {
            "kind": "TABLE",
            "name": "结果名称",
            "fields": [
                {"name":"period","data_type":"date","role":"dimension"},
                {"name":"ratio","data_type":"number","role":"measure"}
            ],
            "grain": ["period"]
        }
    }
}
alignment.keys 是各输入结果共有的同名 grain 字段字符串数组；若两侧字段不同，先让上游 AGGREGATE 使用相同 output 名。outputs 元素只能有 name 和 expression。selection 必须使用 kind/field/take/nulls/tie_breakers。"""

_INPUT_OUTPUT_GUIDE = """节点的 depends_on 与 inputs 是两回事，必须同时保留：
- depends_on：控制依赖，表示当前节点必须等待哪些节点完成；有依赖不代表一定消费其输出。
- inputs：数据依赖，把输入名映射到某个上游节点的 output。每个 input.node 必须同时列在 depends_on 中；depends_on 可以比 inputs 多。
- 上游 output 保持原始类型，可以是完整表、单行、单列、标量、文档或文本，不默认转换成文本。

inputs 引用格式：
{
    "all_rows": {"node": "n1"},
    "first_row": {"node": "n1", "row": 0},
    "product_name": {"node": "n1", "output": "product", "row": 0},
    "all_products": {"node": "n1", "output": "product"}
}
含义依次为：完整结果、单行对象、单个原类型值、整列数组。

如果目标参数本身是文本，可在字符串中用 {input_name} 引用标量输入。例如：
{
    "id": "n2",
    "operator": "SEARCH",
    "name": "搜索销量最高产品的新闻",
    "depends_on": ["n1"],
    "inputs": {
        "product_name": {"node": "n1", "output": "product", "row": 0}
    },
    "spec": {"query": "{product_name} 最新新闻", "max_results": 10}
}
ASK/ACT 可以直接接收完整表或对象，无须把输入先变成文本。"""


class Compiler:
    def __init__(self, ontology, llm=None, available_ops=None, onto_names=None):
        self.ontology = ontology
        self.llm = llm
        self.available_ops = ({*available_ops, Operator.CALCULATE.value}
                              if available_ops is not None else None)
        self.onto_names = dict(onto_names or {})

    def compile(self, question: str, ctx: Optional[ExecContext] = None) -> SQG:
        if self.llm is None:
            return self._fail(question, "未配置规划 LLM")
        key = self._cache_key(question, ctx)
        cached = self._cache_get(key)
        if cached is not None:
            return self._reuse(cached, ctx)
        try:
            sqg = self._compile_llm(question, ctx)
        except Exception as exc:
            return self._fail(question, f"内部错误：{exc}")
        if sqg.nodes:
            now = time.time()
            _SQG_CACHE[key] = (now, now, copy.deepcopy(sqg))
        return sqg

    def _cache_key(self, question: str, ctx: Optional[ExecContext]) -> tuple:
        ontology_ids = tuple(sorted(getattr(ctx, "ontology_ids", None) or self.onto_names.keys()))
        operators = tuple(sorted(self.available_ops or ()))
        normalized_question = " ".join((question or "").strip().casefold().split())
        return (normalized_question, ontology_ids, operators, self._ontology_fingerprint())

    def _ontology_fingerprint(self) -> str:
        digest = hashlib.sha256()
        for concept in sorted(self.ontology.list_concepts(), key=lambda item: item.id):
            digest.update(json.dumps({
                "id": concept.id, "kind": concept.kind.value, "name": concept.name,
                "semantics": concept.semantics, "synonyms": concept.synonyms,
                "attrs": concept.attrs,
            }, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8"))
        return digest.hexdigest()

    def _cache_get(self, key):
        entry = _SQG_CACHE.get(key)
        if entry is None:
            return None
        compiled_at, last_used, sqg = entry
        now = time.time()
        if now - last_used > _SQG_CACHE_TTL_S:
            _SQG_CACHE.pop(key, None)
            return None
        _SQG_CACHE[key] = (compiled_at, now, sqg)
        return compiled_at, sqg

    @staticmethod
    def _reuse(cached, ctx):
        compiled_at, sqg = cached
        result = copy.deepcopy(sqg)
        age = int(time.time() - compiled_at)
        result.context.update({"sqg_reused": True, "cache_age_s": age})
        if ctx is not None:
            ctx.stage_logs.update({
                "sqg_reused": True,
                "cache": {"reused": True, "age_s": age, "ttl_s": _SQG_CACHE_TTL_S},
            })
        return result

    def _compile_llm(self, question: str, ctx: Optional[ExecContext]) -> SQG:
        system = self._prompt()
        attempts = []
        feedback = None
        if ctx is not None:
            ctx.stage_logs["prompt"] = {"system": system, "user": question}
        for attempt in range(1, _MAX_COMPILE_ATTEMPTS + 1):
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ]
            if feedback:
                messages.append({"role": "user", "content": feedback})
            raw = self.llm.complete(messages, schema=SQG.model_json_schema())
            try:
                data = raw if isinstance(raw, dict) else json.loads(raw)
                if not data.get("nodes") and data.get("compile_errors"):
                    reason = "；".join(str(error.get("detail") or error.get("kind"))
                                      for error in data["compile_errors"])
                    attempts.append({"attempt": attempt, "error": reason,
                                     "raw_output": self._safe_raw(data)})
                    self._log_attempts(ctx, attempts)
                    return self._fail(question, reason, attempts)
                data["question"] = question
                data.setdefault("version", 3)
                data.setdefault("outputs", [data["nodes"][-1]["id"]] if data.get("nodes") else [])
                data.setdefault("context", {"generated_by": "llm"})
                sqg = SQG.model_validate(data)
                self._validate_capabilities(sqg)
                self._validate_business_dependencies(sqg)
                self._validate_runtime_inputs(sqg)
                self._validate_calculate_contracts(sqg)
                Binder(self.ontology).bind(sqg)
                attempts.append({"attempt": attempt, "nodes": len(sqg.nodes),
                                 "raw_output": self._safe_raw(data)})
                sqg.context["attempts"] = attempts
                if attempt > 1:
                    sqg.context["recompiled"] = attempt - 1
                self._log_attempts(ctx, attempts)
                return sqg
            except (ValidationError, BindingError, ValueError, TypeError, KeyError) as exc:
                detail = self._error_text(exc)
                attempts.append({"attempt": attempt, "error": detail,
                                 "raw_output": self._safe_raw(raw)})
                feedback = (
                    "上次 JSON 未通过 typed SQG 校验。错误如下：\n" + detail +
                    "\n请保持业务任务粒度，修正 concept/spec/depends_on/inputs 后重新输出完整 JSON；"
                    "不要生成 FILTER/JOIN/SORT/LIMIT/PROJECT 节点。\n" +
                    _PREDICATE_SCHEMA_GUIDE + "\n" + _CALCULATE_SCHEMA_GUIDE +
                    "\n" + _INPUT_OUTPUT_GUIDE
                )
        self._log_attempts(ctx, attempts)
        return self._fail(question, attempts[-1]["error"], attempts)

    def _validate_capabilities(self, sqg: SQG) -> None:
        if self.available_ops is None:
            return
        unavailable = sorted({node.operator.value for node in sqg.nodes} - self.available_ops)
        if unavailable:
            raise ValueError("本体未挂载这些能力：" + "、".join(unavailable))

    @staticmethod
    def _validate_business_dependencies(sqg: SQG) -> None:
        by_id = {node.id: node for node in sqg.nodes}
        structured_ids = {
            node.id for node in sqg.nodes
            if isinstance(node, (SelectNode, AggregateNode, CalculateNode, SearchNode, BrowseNode))
        }

        def ancestors(node_id: str) -> set[str]:
            found: set[str] = set()
            stack = list(by_id[node_id].depends_on)
            while stack:
                current = stack.pop()
                if current in found:
                    continue
                found.add(current)
                if current in by_id:
                    stack.extend(by_id[current].depends_on)
            return found

        def data_ancestors(node_id: str) -> set[str]:
            found: set[str] = set()
            stack = [input_ref.node for input_ref in by_id[node_id].inputs.values()]
            while stack:
                current = stack.pop()
                if current in found:
                    continue
                found.add(current)
                if current in by_id:
                    stack.extend(input_ref.node for input_ref in by_id[current].inputs.values())
            return found

        if structured_ids:
            for node in sqg.nodes:
                if isinstance(node, AskNode) and not (data_ancestors(node.id) & structured_ids):
                    raise ValueError(
                        f"ASK {node.id} 必须通过 inputs 接收它要解释/整理的数据；"
                        "depends_on 只表示执行依赖，不能代替数据输入"
                    )

        for node in sqg.nodes:
            if not isinstance(node, AggregateNode):
                continue
            grouped_attributes = {
                dimension.concept for dimension in node.spec.dimensions
                if isinstance(dimension, AttributeDimension)
            }
            for predicate in Compiler._predicates(node.spec.scope):
                if (isinstance(predicate, InPredicate)
                        and isinstance(predicate.value, AttributeExpr)
                        and predicate.value.concept in grouped_attributes
                        and len(predicate.values) > 1):
                    raise ValueError(
                        f"AGGREGATE {node.id} 把多个明确成员合成了一个分组任务；"
                        "请按每个明确成员拆成独立、可命名的业务节点（例如华东销售额、华南销售额），"
                        "不要用 region IN (...) + GROUP BY region 合并"
                    )

        for node in sqg.nodes:
            if not isinstance(node, ActNode) or node.spec.action.upper() != "EMAIL.SEND":
                continue
            upstream = ancestors(node.id)
            report_asks = [candidate for candidate in sqg.nodes
                           if isinstance(candidate, AskNode) and candidate.id in upstream]
            if structured_ids and not report_asks:
                raise ValueError(f"EMAIL.SEND {node.id} 必须依赖一个生成报告正文的 ASK 节点")
            consumed_reports = data_ancestors(node.id) & {ask.id for ask in report_asks}
            if report_asks and not consumed_reports:
                raise ValueError(
                    f"EMAIL.SEND {node.id} 必须通过 inputs 接收报告 ASK 的 output；"
                    "depends_on 只保证执行顺序"
                )
            report_inputs = [
                (name, input_ref) for name, input_ref in node.inputs.items()
                if isinstance(by_id.get(input_ref.node), AskNode)
            ]
            invalid_report_inputs = [
                name for name, input_ref in report_inputs
                if input_ref.output != "value" or input_ref.row is None
            ]
            if invalid_report_inputs:
                raise ValueError(
                    f"EMAIL.SEND {node.id} 的报告 inputs 必须选择 ASK 的文本标量 "
                    f"output='value', row=0：{invalid_report_inputs}"
                )

    @staticmethod
    def _predicates(predicate):
        if predicate is None:
            return []
        if isinstance(predicate, (AndPredicate, OrPredicate)):
            return [predicate, *(child for item in predicate.operands
                                 for child in Compiler._predicates(item))]
        if isinstance(predicate, NotPredicate):
            return [predicate, *Compiler._predicates(predicate.operand)]
        return [predicate]

    @staticmethod
    def _validate_runtime_inputs(sqg: SQG) -> None:
        by_id = {node.id: node for node in sqg.nodes}
        for node in sqg.nodes:
            for input_name, input_ref in node.inputs.items():
                upstream = by_id.get(input_ref.node)
                fields = upstream.output_fields() if upstream else set()
                if input_ref.output is not None and input_ref.output not in fields:
                    raise ValueError(
                        f"{node.operator.value} {node.id} 的 input {input_name!r} 引用了不存在的 output "
                        f"{input_ref.node}.{input_ref.output}"
                    )
            placeholders = Compiler._format_placeholders(node.spec.model_dump(mode="json"))
            unknown = placeholders - set(node.inputs)
            if unknown:
                raise ValueError(
                    f"{node.operator.value} {node.id} 的文本参数引用了未知 inputs：{sorted(unknown)}"
                )
            non_scalar = [name for name in placeholders
                          if node.inputs[name].output is None or node.inputs[name].row is None]
            if non_scalar:
                raise ValueError(
                    f"{node.operator.value} {node.id} 的文本格式 inputs 必须选择单个标量 "
                    f"（同时指定 output 和 row）：{non_scalar}"
                )

    @staticmethod
    def _format_placeholders(value):
        if isinstance(value, str):
            try:
                return {field_name for _, field_name, _, _ in Formatter().parse(value) if field_name}
            except ValueError:
                return set()
        if isinstance(value, dict):
            return set().union(*(Compiler._format_placeholders(child) for child in value.values())) \
                if value else set()
        if isinstance(value, list):
            return set().union(*(Compiler._format_placeholders(child) for child in value)) \
                if value else set()
        return set()

    @staticmethod
    def _validate_calculate_contracts(sqg: SQG) -> None:
        by_id = {node.id: node for node in sqg.nodes}
        for node in sqg.nodes:
            if not isinstance(node, CalculateNode):
                continue
            input_nodes = {alias: item.node for alias, item in node.inputs.items()}
            if not input_nodes:
                raise ValueError(f"CALCULATE {node.id} 至少需要一个 input")
            selected_inputs = [alias for alias, item in node.inputs.items()
                               if item.output is not None or item.row is not None]
            if selected_inputs:
                raise ValueError(
                    f"CALCULATE {node.id} 需要完整上游结果，不能在 inputs 中预选 row/output："
                    f"{selected_inputs}"
                )
            contracts = {}
            for alias, upstream_id in input_nodes.items():
                upstream = by_id.get(upstream_id)
                contract = getattr(getattr(upstream, "spec", None), "result", None)
                if contract is None:
                    raise ValueError(f"CALCULATE {node.id} 输入 {alias} 没有结果契约：{upstream_id}")
                contracts[alias] = contract

            for key in node.spec.alignment.keys:
                missing = [alias for alias, contract in contracts.items()
                           if key not in contract.grain]
                if missing:
                    raise ValueError(
                        f"CALCULATE {node.id} alignment key {key!r} 不是这些输入的公共 grain：{missing}"
                    )
            if len(contracts) > 1 and not node.spec.alignment.keys \
                    and not node.spec.alignment.scalar_broadcast \
                    and any(contract.grain for contract in contracts.values()):
                raise ValueError(
                    f"CALCULATE {node.id} 的多行输入必须提供 alignment.keys，"
                    "或明确 scalar_broadcast=true"
                )

            output_names = {output.name for output in node.spec.outputs}
            for output in node.spec.outputs:
                for ref in Compiler._node_output_refs(output.expression):
                    if ref.input not in contracts:
                        raise ValueError(
                            f"CALCULATE {node.id} expression 引用了未知输入别名：{ref.input}"
                        )
                    available_fields = {field.name for field in contracts[ref.input].fields}
                    if ref.field not in available_fields:
                        raise ValueError(
                            f"CALCULATE {node.id} 输入 {ref.input} 不存在字段 {ref.field!r}"
                        )
            result_fields = {field.name for field in node.spec.result.fields}
            if not output_names <= result_fields:
                raise ValueError(
                    f"CALCULATE {node.id} result.fields 缺少 outputs：{sorted(output_names - result_fields)}"
                )
            if node.spec.selection:
                if node.spec.selection.field not in output_names:
                    raise ValueError(
                        f"CALCULATE {node.id} selection.field 必须引用 outputs 字段"
                    )
                invalid_ties = [key.field for key in node.spec.selection.tie_breakers
                                if key.field not in output_names]
                if invalid_ties:
                    raise ValueError(
                        f"CALCULATE {node.id} selection.tie_breakers 引用了未知输出：{invalid_ties}"
                    )

    @staticmethod
    def _node_output_refs(expression):
        if isinstance(expression, NodeOutputExpr):
            return [expression]
        if isinstance(expression, BinaryExpr):
            return [*Compiler._node_output_refs(expression.left),
                    *Compiler._node_output_refs(expression.right)]
        if isinstance(expression, UnaryExpr):
            return Compiler._node_output_refs(expression.operand)
        if isinstance(expression, FunctionExpr):
            return [ref for argument in expression.arguments
                    for ref in Compiler._node_output_refs(argument)]
        if isinstance(expression, TimeBucketExpr):
            return Compiler._node_output_refs(expression.value)
        if isinstance(expression, AggregateExpr):
            return Compiler._node_output_refs(expression.value) if expression.value else []
        if isinstance(expression, CaseExpr):
            refs = [ref for branch in expression.branches
                    for ref in Compiler._node_output_refs(branch.then)]
            if expression.otherwise:
                refs.extend(Compiler._node_output_refs(expression.otherwise))
            return refs
        return []

    @staticmethod
    def _error_text(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return "；".join(
                f"{'.'.join(str(v) for v in error['loc'])}: {error['msg']}"
                for error in exc.errors(include_url=False)
            )
        return str(exc)

    @staticmethod
    def _log_attempts(ctx, attempts) -> None:
        if ctx is not None:
            ctx.stage_logs["attempts"] = attempts

    @staticmethod
    def _safe_raw(raw):
        """Persist bounded raw compiler output for direct run_stage.logs diagnosis."""
        if isinstance(raw, dict):
            return raw
        text = str(raw)
        return text[:100000] + ("…" if len(text) > 100000 else "")

    @staticmethod
    def _fail(question: str, reason: str, attempts=None) -> SQG:
        context = {"error": f"编译失败：{reason}", "error_kind": "compile_error"}
        if attempts:
            context["attempts"] = attempts
        return SQG(question=question, context=context)

    def _prompt(self) -> str:
        concepts = self.ontology.list_concepts()
        entities = [concept for concept in concepts if concept.kind == ConceptKind.entity]
        attributes = [concept for concept in concepts if concept.kind == ConceptKind.attribute]
        metrics = [concept for concept in concepts if concept.kind == ConceptKind.metric]
        relations = [concept for concept in concepts if concept.kind == ConceptKind.relation]
        by_entity: dict[str, list] = {}
        for attribute in attributes:
            by_entity.setdefault((attribute.attrs or {}).get("entity"), []).append(attribute)

        entity_catalog = []
        for entity in entities:
            entity_catalog.append({
                "id": entity.id, "name": entity.name, "semantics": entity.semantics,
                "attributes": [{
                    "id": attribute.id, "name": attribute.name,
                    "role": (attribute.attrs or {}).get("role"),
                    "dtype": (attribute.attrs or {}).get("dtype"),
                    "additivity": (attribute.attrs or {}).get("additivity"),
                    "semantics": attribute.semantics,
                } for attribute in by_entity.get(entity.id, [])],
            })
        metric_catalog = [{
            "id": metric.id, "name": metric.name, "semantics": metric.semantics,
            "expression": (metric.attrs or {}).get("expression"),
            "unit": (metric.attrs or {}).get("unit"),
        } for metric in metrics]
        relation_catalog = [{
            "id": relation.id, "name": relation.name,
            "from": (relation.attrs or {}).get("from"),
            "to": (relation.attrs or {}).get("to"),
            "multiplicity": (relation.attrs or {}).get("multiplicity"),
        } for relation in relations]
        available = sorted(self.available_ops or [operator.value for operator in Operator])

        return f"""你是 Data Nexus typed SQG 编译器。只输出一个 JSON object。

SQG 是面向人的解题 DAG：一个节点是一项可独立命名、可形成中间结论的业务任务。
严禁生成 FILTER、JOIN、ALIGN、SORT、LIMIT、PROJECT 技术节点；过滤/分组/排名写在业务节点 spec 内。
不要为了少查一次而合并独立业务任务；是否融合由 Optimizer 决定。
确定性计算用 CALCULATE，ASK 只解释/组织输入，不得口算数字。ASK 和 ACT 各一个高层节点即可。

可用高层算子：{json.dumps(available, ensure_ascii=False)}
实体与属性：{json.dumps(entity_catalog, ensure_ascii=False)}
指标：{json.dumps(metric_catalog, ensure_ascii=False)}
关系：{json.dumps(relation_catalog, ensure_ascii=False)}

公共节点外壳：
{{"id":"n1","operator":"AGGREGATE","name":"业务任务名","depends_on":[],"inputs":{{}},"spec":{{...}}}}
整图：{{"version":3,"nodes":[...],"outputs":["最后业务节点id"],"context":{{"intent":"..."}}}}

Predicate：
{_PREDICATE_SCHEMA_GUIDE}
月/季/年过滤必须用半开 time_range。

AGGREGATE spec：
{{"subject":{{"entity":"entity id"}},"scope":null或Predicate,"dimensions":[
  {{"kind":"attribute","concept":"dimension attribute id","output":"region"}} 或
  {{"kind":"time","attribute":"date attribute id","grain":"DAY|WEEK|MONTH|QUARTER|YEAR","calendar":"GREGORIAN","timezone":"Asia/Shanghai","output":"period"}}
],"measure":
  {{"kind":"metric","metric":"metric id","output":"value"}} 或
  {{"kind":"statistic","value":{{"kind":"attribute","concept":"attribute id"}},"statistic":{{"function":"SUM|COUNT|COUNT_DISTINCT|AVG|MIN|MAX|MEDIAN|PERCENTILE|VARIANCE|STDDEV","percentile":0.5,"method":"CONTINUOUS","accuracy":"EXACT","nulls":"IGNORE"}},"output":"value"}},
"ranking":null或{{"by":"value","direction":"DESC","take":3,"ties":"EXCLUDE","tie_breakers":[{{"field":"dimension output","direction":"ASC"}}]}},
"domain_policy":{{"unmatched":"EXCLUDE_UNMATCHED|KEEP_AS_UNKNOWN|ERROR_ON_UNMATCHED"}},
"result":{{"kind":"SCALAR|TABLE|RANKING","name":"...","fields":[{{"name":"value","data_type":"number","role":"measure","unit":"CNY"}}],"grain":[]}}}}
一个 AGGREGATE 只有一个主要业务结果。

SELECT spec：subject + scope + fields:[{{concept,output}}] + distinct + result。
CALCULATE spec：
{_CALCULATE_SCHEMA_GUIDE}
CALCULATE 的 node_output expression：{{"kind":"node_output","input":"输入别名","field":"字段名"}}。
ASK spec={{"instruction":"...","format":"MARKDOWN"}}。
ACT spec={{"action":"EMAIL.SEND或其它动作","recipient":"对象名","parameters":{{}}}}。
SEARCH spec={{"query":"静态搜索词或{{input_name}}格式字符串","max_results":10}}；BROWSE spec={{"url":"https://..."}}。
节点输入输出统一契约：
{_INPUT_OUTPUT_GUIDE}

规则：
1. concept id 必须逐字取自目录；跨实体属性必须有 relation path。
2. 用户明确点名多个成员时，每个“成员 × 指标”分别建独立 AGGREGATE 节点。例如“华东和华南的销售额和毛利”必须拆成华东销售额、华东毛利、华南销售额、华南毛利四个节点；禁止用 region IN(华东,华南) + GROUP BY region 合成一个节点。Optimizer 会在 PEP 中决定是否一次查询。
3. TopN 作用域必须按问题明确；全局 Top3 用 ranking；各组 Top3 需业务任务明确表达。
4. 排名必须提供稳定 tie_breaker。
5. 结果 contract 的 fields/grain/unit 要与任务一致。
6. 分析/报告用 depends_on 等待相关数据节点，并用 inputs 接收其 output；行动同样用 inputs 接收报告/结论。depends_on 不自动传数据。
7. 无法回答时输出 {{"nodes":[],"compile_errors":[{{"kind":"missing_concept|no_relation","detail":"友好说明"}}]}}。
8. outputs 表示要在页面答案中展示的节点，不等同于“所有输入最终流向的终点”。一个节点即使被 ASK/ACT 消费，也仍可同时出现在 outputs。运行时会自动补齐终点节点，但 Compiler 必须额外保留用户要求直接查看的中间查询结果。
9. 混合交付必须逐个子意图处理。例如“查询 A、查询 B，把 C 发邮件”：A、B 和 EMAIL.SEND ACT 放入 outputs；只让 C 进入报告 ASK 的 inputs；不得把 A、B 强行塞入邮件，也不得因它们有下游而从 outputs 删除。

报告邮件的依赖结构必须是：
AGGREGATE/SELECT 等数据节点 → 一个生成完整报告的 ASK → 一个 EMAIL.SEND ACT。
ASK 的 depends_on 列出执行依赖，inputs 分别接收需要写入报告的数据 output。
EMAIL.SEND 的 depends_on 等待报告 ASK，inputs 必须以 {{"node":"报告ASK","output":"value","row":0}} 接收报告文本标量。
禁止建立无数据 inputs 的“明确报告口径/复述用户需求”ASK；EMAIL.SEND 不要绕过报告 ASK 直接拼接多个数据节点。
"""
