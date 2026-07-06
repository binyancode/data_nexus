"""AgentResolver：ASK 算子的执行体 —— 把（已回填的）提示词交给 LLM，返回一段分析文字。

config 来自 azure_openai_credential.to_config()（endpoint/key/deployment/api_version）。
"""

from __future__ import annotations

from typing import Optional

from nexus.core.models import NodeResult, ExecContext
from nexus.resolvers.base import Resolver

_DEFAULT_SYSTEM = (
    "你是资深业务分析师。基于用户给出的具体数值，用中文做简明的对比与归因分析，"
    "指出关键差异、给出最可能的原因和一句结论。控制在 3-4 句以内，不要罗列无关内容。"
)


class AgentResolver(Resolver):
    resolver_type = "agent"
    provides_concepts = False
    operators = {"ASK"}

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        from nexus.llm.azure_openai import AzureOpenAIProvider
        self._llm = AzureOpenAIProvider(name, self.config)

    def fetch(self, call: dict, ctx: Optional[ExecContext] = None) -> NodeResult:
        node_id = call.get("node_id", "")
        prompt = call.get("prompt") or call.get("ask") or ""
        system = call.get("system") or _DEFAULT_SYSTEM
        try:
            text = self._llm.complete(
                [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
            )
            text = (text or "").strip()
            return NodeResult(
                node_id=node_id, resolver=self.name, output=text,
                rows=[{"value": text}], trust=0.8,
                source=f"{self.name}:llm", detail=prompt[:300],
                logs={"prompt": {"system": system, "user": prompt}},
            )
        except Exception as exc:
            return NodeResult(node_id=node_id, resolver=self.name, error=str(exc),
                              source=f"{self.name}:llm", detail=prompt[:300],
                              logs={"prompt": {"system": system, "user": prompt}})
