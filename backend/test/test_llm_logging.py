"""LLM request/response/usage logging regressions."""

import os
import sys
import unittest
from types import SimpleNamespace

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from nexus.core.logical import Operator
from nexus.core.models import ExecContext
from nexus.core.physical import CapabilityFragment, LogicalOutputBinding, PhysicalExecutionPlan
from nexus.engine.coordinator import Coordinator
from nexus.llm.azure_openai import AzureOpenAIProvider
from nexus.resolvers.agent import AgentResolver


class _Usage:
    def model_dump(self, mode="json"):
        return {
            "prompt_tokens": 1200,
            "completion_tokens": 85,
            "total_tokens": 1285,
            "prompt_tokens_details": {
                "cached_tokens": 1024,
                "cache_write_tokens": 0,
                "audio_tokens": 0,
            },
            "completion_tokens_details": {
                "reasoning_tokens": 40,
                "accepted_prediction_tokens": 0,
                "rejected_prediction_tokens": 0,
                "audio_tokens": 0,
            },
        }


class _Completions:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return self.response


class _Registry:
    def __init__(self, resolver):
        self._resolver = resolver

    def resolver(self, name):
        return self._resolver if name == self._resolver.name else None


class _TextLLM:
    name = "test-llm"
    resolver_type = "test"

    def complete(self, messages, schema=None):
        return "## 报告\n\n正文"


class LlmLoggingTests(unittest.TestCase):
    def test_azure_provider_captures_cached_and_reasoning_tokens(self):
        response = SimpleNamespace(
            id="chatcmpl-1",
            model="gpt-test-2026-07-22",
            usage=_Usage(),
            choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content='{"answer": 1}'),
            )],
            _request_id="request-1",
        )
        completions = _Completions(response)
        provider = AzureOpenAIProvider.__new__(AzureOpenAIProvider)
        provider.name = "planner"
        provider.config = {}
        provider._deployment = "deployment-1"
        provider._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

        completion = provider.complete_with_metadata(
            [{"role": "user", "content": "question"}], schema={"type": "object"}
        )

        self.assertEqual(completion.output, {"answer": 1})
        self.assertEqual(completion.log["input"]["messages"][0]["content"], "question")
        self.assertEqual(completion.log["output"]["content"], '{"answer": 1}')
        self.assertEqual(completion.log["output"]["parsed"], {"answer": 1})
        self.assertEqual(completion.log["usage"]["input_tokens"], 1200)
        self.assertEqual(completion.log["usage"]["cached_input_tokens"], 1024)
        self.assertEqual(completion.log["usage"]["uncached_input_tokens"], 176)
        self.assertEqual(completion.log["usage"]["output_tokens"], 85)
        self.assertEqual(completion.log["usage"]["reasoning_tokens"], 40)
        self.assertEqual(completion.log["usage"]["total_tokens"], 1285)
        self.assertEqual(completion.log["request_id"], "request-1")
        self.assertEqual(completion.log["finish_reason"], "stop")

    def test_agent_llm_call_is_written_to_node_and_coordinator_logs(self):
        resolver = AgentResolver.__new__(AgentResolver)
        resolver.name = "agent"
        resolver.config = {}
        resolver._llm = _TextLLM()
        plan = PhysicalExecutionPlan(nodes=[CapabilityFragment(
            id="p_n1", name="生成报告", operator=Operator.ASK, resolver="agent",
            call={"node_id": "p_n1", "prompt": "生成报告"},
            realizes=[LogicalOutputBinding(logical_node="n1", physical_result="result")],
        )])
        ctx = ExecContext("q")

        Coordinator(_Registry(resolver)).execute(plan, ctx)

        node_calls = ctx.physical_results["p_n1"].logs["llm_calls"]
        self.assertEqual(len(node_calls), 1)
        self.assertEqual(node_calls[0]["purpose"], "ask_generation")
        self.assertEqual(node_calls[0]["input"]["messages"][1]["content"], "生成报告")
        self.assertEqual(node_calls[0]["output"]["content"], "## 报告\n\n正文")
        self.assertIsNone(node_calls[0]["usage"])
        self.assertEqual(ctx.stage_logs["llm_calls"], node_calls)


if __name__ == "__main__":
    unittest.main()
