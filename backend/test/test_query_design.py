"""Clean-break typed SQG / binder / optimizer / renderer integration tests."""

import os
import pathlib
import sys
import tempfile
import unittest

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from nexus.core.expressions import AggregateFunction, AndPredicate, AttributeExpr, ComparisonPredicate, InPredicate, LiteralExpr, OutputExpr
from nexus.core.logical import (
    AggregateNode, AggregateSpec, MetricMeasure, OrderKey, RankingSpec,
    ResultContract, ResultField, ResultKind, SQG, SubjectSpec,
    AttributeDimension,
)
from nexus.core.models import ExecContext, NodeResult
from nexus.core.physical import CapabilityFragment, LogicalOutputBinding, PhysicalExecutionPlan
from nexus.engine.coordinator import Coordinator
from nexus.engine.compiler import Compiler
from nexus.engine.generator import Generator
from nexus.engine.optimizer import Optimizer
from nexus.ontology.json_ontology import JsonOntology
from nexus.resolvers.csv import CsvResolver


class Registry:
    def __init__(self, *resolvers):
        self.items = {resolver.name: resolver for resolver in resolvers}

    def resolver(self, name):
        return self.items.get(name)

    def all_resolvers(self):
        return list(self.items.values())


class SequenceLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.messages = []
        self.schemas = []

    def complete(self, messages, schema=None):
        self.messages.append(messages)
        self.schemas.append(schema)
        return self.outputs.pop(0)


def attribute(entity, name, role="dimension", dtype="number"):
    return {
        "id": f"attribute.{entity}.{name}", "name": name, "column": name,
        "role": role, "dtype": dtype,
        "additivity": "additive" if role == "measure" else None,
    }


def relation(relation_id, from_entity, from_attribute, to_entity, to_attribute,
             integrity="DECLARED"):
    return {
        "id": relation_id, "name": relation_id,
        "from": {"entity": from_entity, "attribute": from_attribute},
        "to": {"entity": to_entity, "attribute": to_attribute},
        "multiplicity": {
            "from_to": {"min": 1, "max": 1},
            "to_from": {"min": 0, "max": "many"},
        },
        "integrity": {"mode": integrity, "source": "test", "confidence": 1},
    }


def aggregate_node(node_id, metric, scope=None, dimensions=None, ranking=None):
    fields = [ResultField(name=d.output, data_type="text", role="dimension")
              for d in (dimensions or [])]
    fields.append(ResultField(name="value", data_type="number", role="measure"))
    return AggregateNode(
        id=node_id, name=node_id,
        spec=AggregateSpec(
            subject=SubjectSpec(entity="entity.order"), scope=scope,
            dimensions=dimensions or [],
            measure=MetricMeasure(metric=metric, output="value"),
            ranking=ranking,
            result=ResultContract(
                kind=ResultKind.RANKING if dimensions else ResultKind.SCALAR,
                name=node_id, fields=fields,
                grain=[d.output for d in (dimensions or [])],
            ),
        ),
    )


class QueryDesignTests(unittest.TestCase):
    def test_sqg_outputs_include_all_independent_terminal_answers(self):
        first = aggregate_node("n1", "metric.sales")
        second = aggregate_node("n2", "metric.profit")
        sqg = SQG(question="两个独立问题", nodes=[first, second], outputs=["n2"])
        self.assertEqual(sqg.outputs, ["n1", "n2"])
        ctx = ExecContext("两个独立问题")
        ctx.results["n1"] = NodeResult(node_id="n1", rows=[{"value": 3}])
        ctx.results["n2"] = NodeResult(node_id="n2", rows=[{"value": 2}])
        answer = Generator().generate(sqg, PhysicalExecutionPlan(), ctx)
        self.assertIn("| n1 | 3 |", answer.text)
        self.assertIn("| n2 | 2 |", answer.text)

    def test_fused_median_average_feed_calculate_minimum_ratio(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "sales.csv").write_text(
                "order_date,amount\n"
                "2024-01-05,10\n2024-01-20,20\n"
                "2024-02-01,1\n2024-02-10,9\n2024-02-20,20\n",
                encoding="utf-8",
            )
            resolver = CsvResolver("sales", {"base_dir": directory, "filename": "sales.csv"})
            graph = {
                "version": 3,
                "entities": [{"id": "entity.sales", "name": "sales", "resolver": "sales",
                              "table": "sales.csv", "attributes": [
                                  attribute("sales", "order_date", dtype="date"),
                                  attribute("sales", "amount", "measure")]}],
                "relations": [], "metrics": [],
            }
            def aggregate_spec(function, output):
                return {
                    "subject": {"entity": "entity.sales"},
                    "dimensions": [{"kind": "time", "attribute": "attribute.sales.order_date",
                                    "grain": "MONTH", "timezone": "UTC", "output": "period"}],
                    "measure": {"kind": "statistic",
                                "value": {"kind": "attribute", "concept": "attribute.sales.amount"},
                                "statistic": {"function": function, "nulls": "IGNORE"},
                                "output": output},
                    "result": {"kind": "TABLE", "name": output,
                               "fields": [{"name": "period", "data_type": "date", "role": "dimension"},
                                          {"name": output, "data_type": "number", "role": "measure"}],
                               "grain": ["period"]},
                }
            sqg = SQG.model_validate({
                "question": "monthly ratio",
                "nodes": [
                    {"id": "n1", "operator": "AGGREGATE", "name": "median",
                     "spec": aggregate_spec("MEDIAN", "median_amount"), "depends_on": []},
                    {"id": "n2", "operator": "AGGREGATE", "name": "average",
                     "spec": aggregate_spec("AVG", "avg_amount"), "depends_on": []},
                    {"id": "n3", "operator": "CALCULATE", "name": "minimum ratio",
                     "inputs": {"median": {"node": "n1"}, "average": {"node": "n2"}},
                     "spec": {
                         "alignment": {"keys": ["period"], "domain": "INNER", "scalar_broadcast": False},
                         "outputs": [
                             {"name": "period", "expression": {"kind": "node_output", "input": "median", "field": "period"}},
                             {"name": "ratio", "expression": {"kind": "binary", "operator": "SAFE_DIVIDE",
                                                                "left": {"kind": "node_output", "input": "median", "field": "median_amount"},
                                                                "right": {"kind": "node_output", "input": "average", "field": "avg_amount"}}},
                         ],
                         "selection": {"kind": "MIN_BY", "field": "ratio", "take": 1,
                                       "tie_breakers": [{"field": "period", "direction": "ASC"}]},
                         "result": {"kind": "TABLE", "name": "minimum ratio",
                                    "fields": [{"name": "period", "data_type": "date", "role": "dimension"},
                                               {"name": "ratio", "data_type": "number", "role": "measure"}],
                                    "grain": ["period"]},
                     }, "depends_on": ["n1", "n2"]},
                ], "outputs": ["n3"],
            })
            registry = Registry(resolver)
            ctx = ExecContext("monthly ratio")
            plan = Optimizer(JsonOntology(graph), registry, {"sales"}).plan(sqg, ctx)
            self.assertEqual(len([node for node in plan.nodes if node.kind == "SOURCE_FRAGMENT"]), 1)
            result = Coordinator(registry).execute(plan, ctx)
            self.assertEqual(len(result["n3"].rows), 1)
            self.assertTrue(str(result["n3"].rows[0]["period"]).startswith("2024-02"))
            self.assertAlmostEqual(result["n3"].rows[0]["ratio"], 0.9)
            answer = Generator().generate(sqg, plan, ctx)
            self.assertIn("## minimum ratio", answer.text)
            self.assertNotIn("## median", answer.text)
            self.assertNotIn("## average", answer.text)
            self.assertEqual(len(answer.lineage), 3)
            self.assertEqual(len(answer.data["nodes"]), 3)

    def test_compiler_repairs_calculate_alignment_and_expression_shape(self):
        graph = {
            "version": 3,
            "entities": [{
                "id": "entity.order", "name": "order", "resolver": "sales", "table": "orders.csv",
                "attributes": [attribute("order", "amount", "measure"),
                               attribute("order", "period", dtype="date")],
            }],
            "relations": [], "metrics": [],
        }

        def aggregate(node_id, function, output):
            return {
                "id": node_id, "operator": "AGGREGATE", "name": node_id, "depends_on": [],
                "spec": {
                    "subject": {"entity": "entity.order"},
                    "dimensions": [{"kind": "time", "attribute": "attribute.order.period",
                                    "grain": "MONTH", "calendar": "GREGORIAN",
                                    "timezone": "Asia/Shanghai", "output": "period"}],
                    "measure": {"kind": "statistic",
                                "value": {"kind": "attribute", "concept": "attribute.order.amount"},
                                "statistic": {"function": function, "nulls": "IGNORE"},
                                "output": output},
                    "result": {"kind": "TABLE", "name": node_id,
                               "fields": [{"name": "period", "data_type": "date", "role": "dimension"},
                                          {"name": output, "data_type": "number", "role": "measure"}],
                               "grain": ["period"]},
                },
            }

        def calculate(keys):
            return {
                "id": "n3", "operator": "CALCULATE", "name": "最低比值月份",
                "inputs": {"median": {"node": "n1"}, "average": {"node": "n2"}},
                "spec": {
                    "alignment": {"keys": keys, "domain": "INNER", "scalar_broadcast": False},
                    "outputs": [
                        {"name": "period", "expression": {"kind": "node_output", "input": "median", "field": "period"}},
                        {"name": "ratio", "expression": {"kind": "binary", "operator": "SAFE_DIVIDE",
                                                            "left": {"kind": "node_output", "input": "median", "field": "median_amount"},
                                                            "right": {"kind": "node_output", "input": "average", "field": "avg_amount"},
                                                            "zero_division": "NULL"}},
                    ],
                    "selection": {"kind": "MIN_BY", "field": "ratio", "take": 1, "nulls": "LAST",
                                  "tie_breakers": [{"field": "period", "direction": "ASC", "nulls": "LAST"}]},
                    "result": {"kind": "TABLE", "name": "最低比值月份",
                               "fields": [{"name": "period", "data_type": "date", "role": "dimension"},
                                          {"name": "ratio", "data_type": "number", "role": "measure"}],
                               "grain": ["period"]},
                },
                "depends_on": ["n1", "n2"],
            }

        malformed = {"nodes": [aggregate("n1", "MEDIAN", "median_amount"),
                                 aggregate("n2", "AVG", "avg_amount"),
                                 calculate([{"left_field": "period", "right_field": "period"}])],
                     "outputs": ["n3"]}
        repaired = {"nodes": [aggregate("n1", "MEDIAN", "median_amount"),
                                aggregate("n2", "AVG", "avg_amount"), calculate(["period"])],
                    "outputs": ["n3"]}
        llm = SequenceLLM([malformed, repaired])
        ctx = ExecContext("calculate-alignment-regression")
        sqg = Compiler(JsonOntology(graph), llm,
                       available_ops={"AGGREGATE"}).compile(ctx.question, ctx)
        self.assertEqual(len(sqg.nodes), 3)
        self.assertEqual(sqg.node("n3").spec.alignment.keys, ["period"])
        self.assertEqual(sqg.context["recompiled"], 1)
        self.assertIn('"keys": ["period"]', llm.messages[0][0]["content"])
        self.assertIn("alignment.keys.0", ctx.stage_logs["attempts"][0]["error"])

    def test_compiler_repairs_dependent_search_with_result_binding(self):
        graph = {
            "version": 3,
            "entities": [{
                "id": "entity.order", "name": "order", "resolver": "sales", "table": "orders.csv",
                "attributes": [attribute("order", "product", dtype="text"),
                               attribute("order", "quantity", "measure")],
            }],
            "relations": [], "metrics": [],
        }
        aggregate = {
            "id": "n1", "operator": "AGGREGATE", "name": "销量最高的产品", "depends_on": [],
            "spec": {
                "subject": {"entity": "entity.order"},
                "dimensions": [{"kind": "attribute", "concept": "attribute.order.product",
                                "output": "product"}],
                "measure": {"kind": "statistic",
                            "value": {"kind": "attribute", "concept": "attribute.order.quantity"},
                            "statistic": {"function": "SUM"}, "output": "quantity"},
                "ranking": {"by": "quantity", "direction": "DESC", "take": 1,
                            "tie_breakers": [{"field": "product", "direction": "ASC"}]},
                "result": {"kind": "RANKING", "name": "销量最高的产品",
                           "fields": [{"name": "product", "data_type": "text", "role": "dimension"},
                                      {"name": "quantity", "data_type": "number", "role": "measure"}],
                           "grain": ["product"]},
            },
        }
        malformed = {"nodes": [aggregate, {
            "id": "n2", "operator": "SEARCH", "name": "搜索销量最高产品的新闻",
            "spec": {"query": "{product_name} 最新新闻", "max_results": 10},
            "depends_on": ["n1"],
        }], "outputs": ["n2"]}
        repaired = {"nodes": [aggregate, {
            "id": "n2", "operator": "SEARCH", "name": "搜索销量最高产品的新闻",
            "inputs": {"product_name": {"node": "n1", "output": "product", "row": 0}},
            "spec": {"query": "{product_name} 最新新闻", "max_results": 10},
            "depends_on": ["n1"],
        }], "outputs": ["n2"]}
        llm = SequenceLLM([malformed, repaired])
        ctx = ExecContext("查一下销量最高的产品，然后搜索这个产品的新闻")
        sqg = Compiler(JsonOntology(graph), llm,
                       available_ops={"AGGREGATE", "SEARCH"}).compile(ctx.question, ctx)
        self.assertEqual(sqg.node("n2").inputs["product_name"].output, "product")
        self.assertEqual(sqg.context["recompiled"], 1)
        self.assertIn("未知 inputs", ctx.stage_logs["attempts"][0]["error"])
        self.assertIn('"product_name": {"node": "n1", "output": "product", "row": 0}',
                  llm.messages[0][0]["content"])

    def test_compiler_rejects_collapsing_named_members_into_one_grouped_task(self):
        node = aggregate_node(
            "regional_sales", "metric.sales",
            scope=AndPredicate(operands=[InPredicate(
                value=AttributeExpr(concept="attribute.order.region"),
                values=[LiteralExpr(value="East"), LiteralExpr(value="South")],
            )]),
            dimensions=[AttributeDimension(concept="attribute.order.region", output="region")],
        )
        with self.assertRaisesRegex(ValueError, "按每个明确成员拆成独立"):
            Compiler._validate_business_dependencies(SQG(question="q", nodes=[node]))

    def test_compiler_repairs_report_email_dependency_order(self):
        graph = {
            "version": 3,
            "entities": [{
                "id": "entity.order", "name": "order", "resolver": "sales", "table": "orders.csv",
                "attributes": [attribute("order", "amount", "measure")],
            }],
            "relations": [],
            "metrics": [{"id": "metric.sales", "name": "sales", "expression": {
                "kind": "aggregate", "function": "SUM",
                "value": {"kind": "attribute", "concept": "attribute.order.amount"}}}],
        }
        aggregate = {
            "id": "n1", "operator": "AGGREGATE", "name": "sales", "depends_on": [],
            "spec": {
                "subject": {"entity": "entity.order"}, "dimensions": [],
                "measure": {"kind": "metric", "metric": "metric.sales", "output": "value"},
                "result": {"kind": "SCALAR", "name": "sales",
                           "fields": [{"name": "value", "data_type": "number", "role": "measure"}]},
            },
        }
        invalid = {"nodes": [
            {"id": "n0", "operator": "ASK", "name": "明确报告口径",
             "spec": {"instruction": "复述需求", "format": "MARKDOWN"}, "depends_on": []},
            aggregate,
            {"id": "n3", "operator": "ACT", "name": "发邮件",
             "spec": {"action": "EMAIL.SEND", "recipient": "颜斌"}, "depends_on": ["n0", "n1"]},
        ], "outputs": ["n3"]}
        repaired = {"nodes": [
            aggregate,
            {"id": "n2", "operator": "ASK", "name": "生成报告",
               "inputs": {"sales": {"node": "n1"}},
               "spec": {"instruction": "根据输入生成报告", "format": "MARKDOWN"}, "depends_on": ["n1"]},
            {"id": "n3", "operator": "ACT", "name": "发邮件",
             "inputs": {"report": {"node": "n2", "output": "value", "row": 0}},
               "spec": {"action": "EMAIL.SEND", "recipient": "颜斌"}, "depends_on": ["n2"]},
        ], "outputs": ["n3"]}
        llm = SequenceLLM([invalid, repaired])
        ctx = ExecContext("report-email-dependency-regression")
        sqg = Compiler(JsonOntology(graph), llm,
                       available_ops={"AGGREGATE", "ASK", "ACT"}).compile(ctx.question, ctx)
        self.assertEqual([node.id for node in sqg.nodes], ["n1", "n2", "n3"])
        self.assertEqual(sqg.node("n2").depends_on, ["n1"])
        self.assertEqual(sqg.node("n3").depends_on, ["n2"])
        self.assertIn("必须通过 inputs 接收", ctx.stage_logs["attempts"][0]["error"])

    def test_compiler_repairs_mixed_page_answers_and_email_delivery(self):
        graph = {
            "version": 3,
            "entities": [{
                "id": "entity.order", "name": "order", "resolver": "sales", "table": "orders.csv",
                "attributes": [attribute("order", "product_id"),
                               attribute("order", "region_id"),
                               attribute("order", "quantity", "measure")],
            }],
            "relations": [], "metrics": [],
        }

        def aggregate(node_id, name, dimension, function, value, output, kind):
            dimensions = ([{"kind": "attribute", "concept": f"attribute.order.{dimension}",
                            "output": dimension}] if dimension else [])
            fields = ([{"name": dimension, "data_type": "number", "role": "dimension"}]
                      if dimension else [])
            fields.append({"name": output, "data_type": "number", "role": "measure"})
            return {
                "id": node_id, "operator": "AGGREGATE", "name": name,
                "depends_on": [], "inputs": {},
                "spec": {
                    "subject": {"entity": "entity.order"}, "dimensions": dimensions,
                    "measure": {"kind": "statistic",
                                "value": {"kind": "attribute", "concept": f"attribute.order.{value}"},
                                "statistic": {"function": function}, "output": output},
                    "result": {"kind": kind, "name": name, "fields": fields,
                               "grain": [dimension] if dimension else []},
                },
            }

        n1 = aggregate("n1", "产品总数", None, "COUNT_DISTINCT", "product_id",
                       "product_count", "SCALAR")
        n2 = aggregate("n2", "各区域产品数", "region_id", "COUNT_DISTINCT", "product_id",
                       "product_count", "TABLE")
        n3 = aggregate("n3", "所有产品销量", "product_id", "SUM", "quantity",
                       "sales_quantity", "TABLE")
        malformed = {"nodes": [n1, n2, n3,
            {"id": "n4", "operator": "ASK", "name": "生成邮件报告",
             "depends_on": ["n1", "n2", "n3"],
             "inputs": {"total": {"node": "n1"}, "regional": {"node": "n2"},
                        "sales": {"node": "n3"}},
             "spec": {"instruction": "生成完整报告", "format": "MARKDOWN"}},
            {"id": "n5", "operator": "ACT", "name": "发邮件",
             "depends_on": ["n4"], "inputs": {"report": {"node": "n4"}},
             "spec": {"action": "EMAIL.SEND", "recipient": "颜斌",
                      "parameters": {"body": "{report}"}}},
        ], "outputs": ["n5"]}
        repaired = {"nodes": [n1, n2, n3,
            {"id": "n4", "operator": "ASK", "name": "生成产品销量邮件报告",
             "depends_on": ["n3"], "inputs": {"sales": {"node": "n3"}},
             "spec": {"instruction": "根据所有产品销量生成邮件报告", "format": "MARKDOWN"}},
            {"id": "n5", "operator": "ACT", "name": "发邮件",
             "depends_on": ["n4"],
             "inputs": {"report": {"node": "n4", "output": "value", "row": 0}},
             "spec": {"action": "EMAIL.SEND", "recipient": "颜斌",
                      "parameters": {"body": "{report}"}}},
        ], "outputs": ["n1", "n2", "n5"]}
        llm = SequenceLLM([malformed, repaired])
        ctx = ExecContext("查询产品总数和各区域产品数，把所有产品销量发邮件给颜斌")
        sqg = Compiler(JsonOntology(graph), llm,
                       available_ops={"AGGREGATE", "ASK", "ACT"}).compile(ctx.question, ctx)
        self.assertEqual(sqg.outputs, ["n1", "n2", "n5"])
        self.assertEqual(set(sqg.node("n4").inputs), {"sales"})
        self.assertEqual(sqg.node("n5").inputs["report"].output, "value")
        self.assertEqual(sqg.context["recompiled"], 1)
        self.assertIn("报告 inputs 必须选择 ASK 的文本标量",
                      ctx.stage_logs["attempts"][0]["error"])
        self.assertIn("混合交付", llm.messages[0][0]["content"])

    def test_failed_physical_output_is_published_as_logical_error(self):
        class ErrorResolver:
            name = "action"

            @staticmethod
            def fetch(call, ctx=None):
                return NodeResult(node_id=call["node_id"], resolver="action", error="send failed")

        registry = Registry(ErrorResolver())
        plan = PhysicalExecutionPlan(nodes=[CapabilityFragment(
            id="p_n1", name="发送邮件", operator="ACT", resolver="action",
            call={"node_id": "p_n1", "action": "EMAIL.SEND"},
            realizes=[LogicalOutputBinding(logical_node="n1", physical_result="result")],
        )])
        sqg = SQG.model_validate({
            "question": "发送邮件", "outputs": ["n1"],
            "nodes": [{"id": "n1", "operator": "ACT", "name": "发送邮件",
                       "depends_on": [], "inputs": {},
                       "spec": {"action": "EMAIL.SEND", "recipient": "颜斌"}}],
        })
        ctx = ExecContext("发送邮件")
        Coordinator(registry).execute(plan, ctx)
        self.assertEqual(ctx.results["n1"].error, "send failed")
        answer = Generator().generate(sqg, plan, ctx)
        self.assertEqual(answer.status, "error")
        self.assertIn("发送邮件执行失败", answer.text)

    def test_compiler_repairs_exact_predicate_shape_and_logs_raw_output(self):
        graph = {
            "version": 3,
            "entities": [{
                "id": "entity.order", "name": "order", "resolver": "sales", "table": "orders.csv",
                "attributes": [attribute("order", "amount", "measure"),
                               attribute("order", "region", dtype="text")],
            }],
            "relations": [],
            "metrics": [{"id": "metric.sales", "name": "sales", "expression": {
                "kind": "aggregate", "function": "SUM",
                "value": {"kind": "attribute", "concept": "attribute.order.amount"}}}],
        }
        base_spec = {
            "subject": {"entity": "entity.order"}, "dimensions": [],
            "measure": {"kind": "metric", "metric": "metric.sales", "output": "value"},
            "result": {"kind": "SCALAR", "name": "sales",
                       "fields": [{"name": "value", "data_type": "number", "role": "measure"}]},
        }
        malformed = {"nodes": [{
            "id": "n1", "operator": "AGGREGATE", "name": "sales",
            "spec": {**base_spec, "scope": {"kind": "and", "conditions": [{
                "kind": "in", "attribute": "attribute.order.region", "values": ["East"]}]}},
            "depends_on": [],
        }]}
        repaired = {"nodes": [{
            "id": "n1", "operator": "AGGREGATE", "name": "sales",
            "spec": {**base_spec, "scope": {"kind": "and", "operands": [{
                "kind": "in",
                "value": {"kind": "attribute", "concept": "attribute.order.region"},
                "values": [{"kind": "literal", "value": "East", "data_type": "text"}],
            }]}}, "depends_on": [],
        }], "outputs": ["n1"]}
        llm = SequenceLLM([malformed, repaired])
        ctx = ExecContext("predicate-shape-regression")
        sqg = Compiler(JsonOntology(graph), llm, available_ops={"AGGREGATE"}).compile(ctx.question, ctx)
        self.assertEqual(len(sqg.nodes), 1)
        self.assertEqual(sqg.context["recompiled"], 1)
        self.assertIn('"operands"', llm.messages[0][0]["content"])
        self.assertIn('"value":<Expression>', llm.messages[1][-1]["content"])
        self.assertIn("$defs", llm.schemas[0])
        self.assertEqual(ctx.stage_logs["attempts"][0]["raw_output"], malformed)
        self.assertEqual(ctx.stage_logs["attempts"][1]["raw_output"]["nodes"][0]["id"], "n1")

    def test_unknown_relation_disables_cross_source_preaggregation(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "orders.csv").write_text("amount,region_id\n10,1\n", encoding="utf-8")
            pathlib.Path(directory, "regions.csv").write_text("region_id,area\n1,East\n", encoding="utf-8")
            facts = CsvResolver("facts", {"base_dir": directory})
            dims = CsvResolver("dims", {"base_dir": directory})
            rel = relation("relation.order_region", "entity.order", "attribute.order.region_id",
                           "entity.region", "attribute.region.region_id", integrity="UNKNOWN")
            rel["multiplicity"]["from_to"]["max"] = "unknown"
            graph = {
                "version": 3,
                "entities": [
                    {"id": "entity.order", "name": "order", "resolver": "facts", "table": "orders.csv",
                     "attributes": [attribute("order", "amount", "measure"), attribute("order", "region_id")]},
                    {"id": "entity.region", "name": "region", "resolver": "dims", "table": "regions.csv",
                     "attributes": [attribute("region", "region_id"), attribute("region", "area", dtype="text")]},
                ],
                "relations": [rel],
                "metrics": [{"id": "metric.sales", "name": "sales", "expression": {
                    "kind": "aggregate", "function": "SUM",
                    "value": {"kind": "attribute", "concept": "attribute.order.amount"}}}],
            }
            node = aggregate_node("top", "metric.sales",
                                  dimensions=[AttributeDimension(concept="attribute.region.area", output="region")])
            registry = Registry(facts, dims)
            ctx = ExecContext("q")
            plan = Optimizer(JsonOntology(graph), registry, {"facts", "dims"}).plan(SQG(question="q", nodes=[node]), ctx)
            fact_sql = next(item.call["sql"] for item in plan.nodes
                            if item.kind == "SOURCE_FRAGMENT" and item.source_instance == "facts")
            self.assertNotIn("__partial_value", fact_sql)
            trace = ctx.stage_logs["artifacts"]["optimization_trace"]["rules"]
            self.assertTrue(any(item["rule"] == "cross_source_preaggregation"
                                and item["outcome"] == "rejected" for item in trace))

    def test_result_filter_renders_against_aggregate_output(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "orders.csv").write_text(
                "amount,region\n10,East\n30,East\n20,West\n", encoding="utf-8")
            resolver = CsvResolver("sales", {"base_dir": directory, "filename": "orders.csv"})
            graph = {
                "version": 3,
                "entities": [{"id": "entity.order", "name": "order", "resolver": "sales",
                              "table": "orders.csv", "attributes": [
                                  attribute("order", "amount", "measure"),
                                  attribute("order", "region", dtype="text")]}],
                "relations": [],
                "metrics": [{"id": "metric.sales", "name": "sales", "expression": {
                    "kind": "aggregate", "function": "SUM",
                    "value": {"kind": "attribute", "concept": "attribute.order.amount"}}}],
            }
            node = aggregate_node("filtered", "metric.sales",
                                  dimensions=[AttributeDimension(concept="attribute.order.region", output="region")])
            node.spec.result_filter = ComparisonPredicate(
                left=OutputExpr(name="value"), operator="GT", right=LiteralExpr(value=25))
            registry = Registry(resolver)
            ctx = ExecContext("q")
            plan = Optimizer(JsonOntology(graph), registry, {"sales"}).plan(SQG(question="q", nodes=[node]), ctx)
            result = Coordinator(registry).execute(plan, ctx)
            self.assertEqual(result["filtered"].rows, [{"region": "East", "value": 40}])

    def test_same_scope_metrics_fuse_without_project_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "orders.csv").write_text(
                "amount,cost,region\n10,4,East\n30,10,East\n20,8,West\n", encoding="utf-8")
            resolver = CsvResolver("sales", {"base_dir": directory, "filename": "orders.csv"})
            graph = {
                "version": 3,
                "entities": [{
                    "id": "entity.order", "name": "order", "resolver": "sales", "table": "orders.csv",
                    "attributes": [attribute("order", "amount", "measure"),
                                   attribute("order", "cost", "measure"),
                                   attribute("order", "region", dtype="text")],
                }],
                "relations": [],
                "metrics": [
                    {"id": "metric.sales", "name": "sales", "expression": {
                        "kind": "aggregate", "function": "SUM",
                        "value": {"kind": "attribute", "concept": "attribute.order.amount"}}},
                    {"id": "metric.profit", "name": "profit", "expression": {
                        "kind": "aggregate", "function": "SUM", "value": {
                            "kind": "binary", "operator": "SUBTRACT",
                            "left": {"kind": "attribute", "concept": "attribute.order.amount"},
                            "right": {"kind": "attribute", "concept": "attribute.order.cost"}}}},
                ],
            }
            sqg = SQG(question="q", nodes=[aggregate_node("sales", "metric.sales"),
                                             aggregate_node("profit", "metric.profit")])
            registry = Registry(resolver)
            ctx = ExecContext("q")
            plan = Optimizer(JsonOntology(graph), registry, {"sales"}).plan(sqg, ctx)
            self.assertEqual(len(plan.nodes), 1)
            self.assertEqual(plan.nodes[0].kind, "SOURCE_FRAGMENT")
            self.assertEqual({item.logical_node for item in plan.nodes[0].realizes}, {"sales", "profit"})
            self.assertNotIn("PROJECT", plan.model_dump_json())
            result = Coordinator(registry).execute(plan, ctx)
            self.assertEqual(result["sales"].rows, [{"value": 60}])
            self.assertEqual(result["profit"].rows, [{"value": 38}])
            answer = Generator().generate(sqg, plan, ctx)
            self.assertEqual(answer.lineage[0].value, 60)
            self.assertNotEqual(str(answer.lineage[0].value), "[object Object]")
            self.assertIn("bound_logical_plan", ctx.stage_logs["artifacts"])

    def test_cross_source_preaggregation_and_global_topn(self):
        with tempfile.TemporaryDirectory() as directory:
            pathlib.Path(directory, "orders.csv").write_text(
                "amount,customer_id\n10,1\n30,1\n20,2\n", encoding="utf-8")
            pathlib.Path(directory, "customers.csv").write_text(
                "customer_id,region_id\n1,10\n2,20\n", encoding="utf-8")
            pathlib.Path(directory, "regions.csv").write_text(
                "region_id,area\n10,East\n20,West\n", encoding="utf-8")
            facts = CsvResolver("facts", {"base_dir": directory})
            dimensions = CsvResolver("dimensions", {"base_dir": directory})
            graph = {
                "version": 3,
                "entities": [
                    {"id": "entity.order", "name": "order", "resolver": "facts", "table": "orders.csv",
                     "attributes": [attribute("order", "amount", "measure"), attribute("order", "customer_id")]},
                    {"id": "entity.customer", "name": "customer", "resolver": "dimensions", "table": "customers.csv",
                     "attributes": [attribute("customer", "customer_id"), attribute("customer", "region_id")]},
                    {"id": "entity.region", "name": "region", "resolver": "dimensions", "table": "regions.csv",
                     "attributes": [attribute("region", "region_id"), attribute("region", "area", dtype="text")]},
                ],
                "relations": [
                    relation("relation.order_customer", "entity.order", "attribute.order.customer_id",
                             "entity.customer", "attribute.customer.customer_id"),
                    relation("relation.customer_region", "entity.customer", "attribute.customer.region_id",
                             "entity.region", "attribute.region.region_id"),
                ],
                "metrics": [{"id": "metric.sales", "name": "sales", "expression": {
                    "kind": "aggregate", "function": "SUM",
                    "value": {"kind": "attribute", "concept": "attribute.order.amount"}}}],
            }
            dimension = AttributeDimension(concept="attribute.region.area", output="region")
            rank = RankingSpec(by="value", direction="DESC", take=3,
                               tie_breakers=[OrderKey(field="region")])
            sqg = SQG(question="q", nodes=[aggregate_node("top_regions", "metric.sales",
                                                             dimensions=[dimension], ranking=rank)])
            registry = Registry(facts, dimensions)
            ctx = ExecContext("q")
            plan = Optimizer(JsonOntology(graph), registry, {"facts", "dimensions"}).plan(sqg, ctx)
            self.assertEqual([node.kind for node in plan.nodes],
                             ["SOURCE_FRAGMENT", "SOURCE_FRAGMENT", "EXCHANGE", "EXCHANGE", "COMPUTE_FRAGMENT"])
            self.assertIn("__partial_value", plan.nodes[0].call["sql"])
            self.assertIn("GROUP BY", plan.nodes[0].call["sql"])
            result = Coordinator(registry).execute(plan, ctx)
            self.assertEqual(result["top_regions"].rows,
                             [{"region": "East", "value": 40}, {"region": "West", "value": 20}])
            answer = Generator().generate(sqg, plan, ctx)
            self.assertIn("| region | value |", answer.lineage[0].value)
            self.assertIn("| East | 40 |", answer.lineage[0].value)
            rules = ctx.stage_logs["artifacts"]["optimization_trace"]["rules"]
            self.assertTrue(any(item["rule"] == "cross_source_preaggregation"
                                and item["outcome"] == "applied" for item in rules))


if __name__ == "__main__":
    unittest.main()
