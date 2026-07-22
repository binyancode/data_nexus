"""Web IQ credential / resolver / SQG integration tests (no real API key or network)."""

import os
import sys
import unittest

import httpx

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from nexus.core.models import (  # noqa: E402
    Concept, ConceptKind, ExecContext, NodeResult,
)
from nexus.core.physical import CapabilityFragment, PhysicalExecutionPlan  # noqa: E402
from nexus.core.logical import Operator, SQG, SearchNode, BrowseNode, SearchSpec, BrowseSpec, AggregateNode, AggregateSpec, SubjectSpec, AttributeDimension, StatisticMeasure, StatisticSpec, ResultContract, ResultField, ResultKind, RankingSpec, OrderKey, SelectNode, SelectSpec, SelectField, InputRef  # noqa: E402
from nexus.core.expressions import AttributeExpr, AggregateFunction  # noqa: E402
from nexus.engine.coordinator import Coordinator  # noqa: E402
from nexus.engine.compiler import Compiler  # noqa: E402
from nexus.engine.generator import Generator  # noqa: E402
from nexus.engine.optimizer import Optimizer  # noqa: E402
from nexus.resolvers.agent import AgentResolver  # noqa: E402
from nexus.resolvers.web_iq import WebIqResolver  # noqa: E402
from services.credential import credential  # noqa: E402


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json):
        self.calls.append((url, json))
        return self.responses.pop(0)

    def close(self):
        return None


def _response(status, data, headers=None):
    return httpx.Response(status, json=data, headers=headers,
                          request=httpx.Request("POST", "https://api.microsoft.ai/test"))


class _Ontology:
    def __init__(self):
        self.entity = Concept(id="entity.web_scope", kind=ConceptKind.entity, name="Web 能力作用域")

    def list_concepts(self):
        return [self.entity]

    def get_concept(self, cid):
        return self.entity if cid == self.entity.id else None

    def get_bindings(self, _cid):
        return []


class _EmptyOntology:
    def list_concepts(self):
        return []

    def get_concept(self, _cid):
        return None

    def get_bindings(self, _cid):
        return []


class _ResolverInfo:
    name = "web"
    operators = {"SEARCH", "BROWSE"}


class _Registry:
    def all_resolvers(self):
        return [_ResolverInfo()]


class _LLM:
    def __init__(self, output):
        self.output = output
        self.messages = None

    def complete(self, messages, schema=None):
        self.messages = messages
        return self.output


class _AnswerLLM:
    def __init__(self):
        self.messages = None

    def complete(self, messages, schema=None):
        self.messages = messages
        return "## 结论\n\n| 指标 | 值 |\n| --- | --- |\n| A | 1 |"


class WebIqTests(unittest.TestCase):
    def _resolver(self, responses, **config):
        resolver = WebIqResolver("web", {"api_key": "secret", **config})
        resolver._client.close()
        resolver._client = _FakeClient(responses)
        resolver._wait = lambda _seconds, _deadline, _ctx: None
        return resolver

    def test_credential_is_api_key_only_and_sensitive(self):
        meta = credential.get_types()["web_iq"]
        self.assertEqual([x["name"] for x in meta["schema"]], ["api_key"])
        self.assertTrue(meta["schema"][0]["sensitive"])
        item = credential.create("wiq", "web_iq", {"api_key": "k"})
        self.assertEqual(item.to_config(), {"api_key": "k"})

    def test_search_maps_web_results_and_filters_adult(self):
        resolver = self._resolver([_response(200, {
            "traceId": "trace-1",
            "webResults": [
                {"title": "RAG", "url": "https://example.com/rag", "content": "grounding", "isAdult": False},
                {"title": "blocked", "url": "https://example.com/x", "content": "x", "isAdult": True},
            ],
        })])
        result = resolver.fetch({"node_id": "n1", "mode": "search", "query": "RAG"})
        self.assertIsNone(result.error)
        self.assertEqual(len(result.rows), 1)
        self.assertEqual(result.rows[0]["title"], "RAG")
        self.assertIn("https://example.com/rag", result.output)
        self.assertEqual(result.logs["trace_id"], "trace-1")
        self.assertNotIn("api_key", result.logs["request"])
        self.assertEqual(resolver._client.calls[0][1]["contentFormat"], "passage")

    def test_browse_polls_202_then_returns_document(self):
        resolver = self._resolver([
            _response(202, {"retryAfter": "0s"}),
            _response(200, {"traceId": "t2", "url": "https://example.com", "title": "Example",
                            "content": "page body", "crawledAt": "2026-07-14T00:00:00Z"}),
        ])
        result = resolver.fetch({"node_id": "n2", "mode": "browse", "url": "https://example.com"})
        self.assertIsNone(result.error)
        self.assertEqual(result.rows[0]["content"], "page body")
        self.assertEqual(len(resolver._client.calls), 2)
        self.assertTrue(resolver._client.calls[0][1]["renderDynamicPages"])

    def test_auth_error_is_not_retried(self):
        resolver = self._resolver([_response(401, {"message": "invalid API key"})])
        result = resolver.fetch({"node_id": "n1", "mode": "search", "query": "RAG"})
        self.assertIn("HTTP 401", result.error)
        self.assertEqual(len(resolver._client.calls), 1)

    def test_transient_service_error_is_retried(self):
        resolver = self._resolver([
            _response(503, {"message": "temporarily unavailable"}),
            _response(200, {"webResults": []}),
        ])
        result = resolver.fetch({"node_id": "n1", "mode": "search", "query": "RAG"})
        self.assertIsNone(result.error)
        self.assertEqual(len(resolver._client.calls), 2)

    def test_optimizer_routes_web_operators_only_to_web_capability(self):
        sqg = SQG(question="q", nodes=[
            SearchNode(id="n1", name="搜", spec=SearchSpec(query="RAG")),
            BrowseNode(id="n2", name="读", spec=BrowseSpec(url="https://example.com")),
        ])
        plan = Optimizer(_Ontology(), _Registry(), allowed={"web"}).plan(sqg)
        self.assertEqual([n.resolver for n in plan.nodes], ["web", "web"])
        self.assertEqual([n.call["mode"] for n in plan.nodes], ["search", "browse"])

    def test_compiler_accepts_search_when_capability_is_available(self):
        llm = _LLM({"nodes": [{"id": "n1", "operator": "SEARCH", "name": "搜索",
                               "spec": {"query": "latest RAG"}, "depends_on": []}]})
        sqg = Compiler(_Ontology(), llm, available_ops={"SEARCH"}).compile("搜索最新 RAG")
        self.assertEqual(sqg.nodes[0].operator, Operator.SEARCH)
        self.assertIn("SEARCH", llm.messages[0]["content"])

    def test_depends_on_and_inputs_are_independent_contracts(self):
        upstream = SelectNode(
            id="n1", name="销量最高的产品",
            spec=SelectSpec(
                subject=SubjectSpec(entity="entity.sales"),
                fields=[SelectField(concept="attribute.sales.product", output="product")],
                result=ResultContract(
                    kind=ResultKind.TABLE, name="销量最高的产品",
                    fields=[ResultField(name="product", data_type="text", role="dimension")],
                    grain=["product"],
                ),
            ),
        )
        control_only = SearchNode(
            id="n2", name="等待后静态搜索", depends_on=["n1"], inputs={},
            spec=SearchSpec(query="RAG 最新新闻"),
        )
        Compiler._validate_runtime_inputs(SQG(question="q", nodes=[upstream, control_only]))

        valid = SearchNode(
            id="n2", name="搜索新闻", depends_on=["n1"],
            inputs={"product_name": InputRef(node="n1", output="product", row=0)},
            spec=SearchSpec(query="{product_name} 最新新闻"),
        )
        Compiler._validate_runtime_inputs(SQG(question="q", nodes=[upstream, valid]))

        with self.assertRaisesRegex(ValueError, "inputs must also be declared in depends_on"):
            SQG(question="q", nodes=[upstream, valid.model_copy(update={"depends_on": []})])

    def test_runtime_template_renders_actual_upstream_product(self):
        ctx = ExecContext(question="q", run_id="r")
        ctx.results["n1"] = NodeResult(
            node_id="n1", rows=[{"product": "乳酸菌（单件）", "quantity": 329574}],
        )
        node = CapabilityFragment(
            id="p_n2", name="搜索新闻", operator=Operator.SEARCH, resolver="web",
            call={
                "node_id": "p_n2", "mode": "search", "query": "{product_name} 最新新闻",
                "input_refs": {
                    "product_name": {"node": "n1", "output": "product", "row": 0},
                },
            },
        )
        call = Coordinator(_Registry())._capability_call(node, node.call, ctx)
        self.assertEqual(call["query"], "乳酸菌（单件） 最新新闻")
        self.assertEqual(call["inputs"], {"product_name": "乳酸菌（单件）"})

    def test_inputs_preserve_table_row_column_and_scalar_types(self):
        ctx = ExecContext(question="q", run_id="r")
        rows = [
            {"product": "A", "quantity": 12},
            {"product": "B", "quantity": 7},
        ]
        ctx.results["n1"] = NodeResult(node_id="n1", rows=rows)
        inputs = Coordinator(_Registry())._resolve_inputs({
            "table": {"node": "n1"},
            "first_row": {"node": "n1", "row": 0},
            "quantities": {"node": "n1", "output": "quantity"},
            "top_quantity": {"node": "n1", "output": "quantity", "row": 0},
        }, ctx)
        self.assertEqual(inputs["table"], rows)
        self.assertEqual(inputs["first_row"], rows[0])
        self.assertEqual(inputs["quantities"], [12, 7])
        self.assertEqual(inputs["top_quantity"], 12)
        self.assertIsInstance(inputs["top_quantity"], int)

    def test_email_body_receives_ask_text_scalar(self):
        ctx = ExecContext(question="q", run_id="r")
        ctx.results["n4"] = NodeResult(
            node_id="n4", rows=[{"value": "# 产品销量报告\n\n正文"}],
        )
        node = CapabilityFragment(
            id="p_n5", name="发邮件", operator=Operator.ACT, resolver="action",
            call={
                "node_id": "p_n5", "action": "EMAIL.SEND", "recipient": "颜斌",
                "parameters": {"body": "{report}"},
                "input_refs": {
                    "report": {"node": "n4", "output": "value", "row": 0},
                },
            },
        )
        call = Coordinator(_Registry())._capability_call(node, node.call, ctx)
        self.assertEqual(call["parameters"]["body"], "# 产品销量报告\n\n正文")
        self.assertEqual(call["inputs"]["report"], "# 产品销量报告\n\n正文")

    def test_node_preview_never_exceeds_nvarchar_200(self):
        result = NodeResult(
            node_id="p_n2",
            rows=[{"title": "😀" * 150, "content": "x" * 300}, {"title": "second"}],
        )
        preview = Coordinator._preview(result)
        self.assertLessEqual(len(preview.encode("utf-16-le")) // 2, 200)
        self.assertTrue(preview.endswith(" 等 2 项"))

    def test_compiler_accepts_web_iq_only_ontology(self):
        llm = _LLM({"nodes": [{"id": "n1", "operator": "BROWSE", "name": "读取网页",
                               "spec": {"url": "https://example.com"},
                               "depends_on": []}]})
        sqg = Compiler(_EmptyOntology(), llm, available_ops={"BROWSE"}).compile("读取网页")
        self.assertEqual(sqg.nodes[0].operator, Operator.BROWSE)

    def test_generator_preserves_web_urls_and_lineage(self):
        node = SearchNode(id="n1", name="搜索", spec=SearchSpec(query="RAG"))
        sqg = SQG(question="q", nodes=[node])
        ctx = ExecContext(question="q", run_id="r")
        from nexus.core.models import NodeResult
        content = "Web IQ grounding " * 80
        ctx.results["n1"] = NodeResult(
            node_id="n1", resolver="web", source="web:search",
            rows=[{"title": "RAG", "url": "https://example.com", "content": content}],
        )
        answer = Generator().generate(sqg, PhysicalExecutionPlan(), ctx)
        self.assertIn("https://example.com", answer.text)
        self.assertIn("| # | 标题 | 摘要 | 来源 |", answer.text)
        self.assertEqual(answer.lineage[0].source, "https://example.com")
        self.assertEqual(answer.lineage[0].detail, content)

    def test_agent_always_requests_markdown(self):
        resolver = AgentResolver.__new__(AgentResolver)
        resolver.name = "agent"
        resolver.config = {}
        resolver._llm = _AnswerLLM()
        result = resolver.fetch({"node_id": "n1", "prompt": "分析数据", "system": "自定义系统提示"})
        self.assertIsNone(result.error)
        self.assertIn("GitHub Flavored Markdown", resolver._llm.messages[0]["content"])
        self.assertIn("| 指标 | 值 |", result.output)

    def test_ranked_query_is_rendered_as_markdown_table(self):
        node = AggregateNode(
            id="n1", name="每个产品的销售额",
            spec=AggregateSpec(
                subject=SubjectSpec(entity="entity.sales"),
                dimensions=[AttributeDimension(concept="attribute.sales.product", output="product")],
                measure=StatisticMeasure(
                    value=AttributeExpr(concept="attribute.sales.amount"),
                    statistic=StatisticSpec(function=AggregateFunction.SUM), output="sales_amount"),
                ranking=RankingSpec(by="sales_amount", direction="DESC", take=3,
                                    tie_breakers=[OrderKey(field="product")]),
                result=ResultContract(
                    kind=ResultKind.RANKING, name="每个产品的销售额", grain=["product"],
                    fields=[ResultField(name="product", data_type="text", role="dimension"),
                            ResultField(name="sales_amount", data_type="number", role="measure")]),
            ),
        )
        sqg = SQG(question="q", nodes=[node])
        ctx = ExecContext(question="q", run_id="r")
        from nexus.core.models import NodeResult
        ctx.results["n1"] = NodeResult(
            node_id="n1", resolver="sales", source="sales:csv",
            rows=[{"product": "乳酸菌（单件）", "sales_amount": 42993961.88999998}],
        )
        answer = Generator().generate(sqg, PhysicalExecutionPlan(), ctx)
        self.assertIn("| product | sales_amount |", answer.text)
        self.assertIn("42,993,961.89", answer.text)
        self.assertNotIn("88999998", answer.text)


if __name__ == "__main__":
    unittest.main()
