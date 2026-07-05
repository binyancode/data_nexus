"""编译器：自然语言 → SQG（逻辑语义查询图）。

两条路径：
  1) LLM 编译（有 llm 时优先）：把本体里的指标/维度喂给模型，产出 JSON，再映射成 SQG。
  2) 规则兜底：正则识别「指标 + 地区/期间」。
LLM 失败或产出非法时自动回落到规则。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from nexus.core.models import SQG, SQGNode, Operator, ConceptKind, ExecContext
from nexus.ontology.store import OntologyStore

# 「上季度」演示映射（P0 固定；真实场景由日历/参数决定）
DEFAULT_PERIOD = "2024Q1"
_REGION_RE = re.compile(r"(华东|华南|华北|华西|华中|东北|西南|西北)")
_PERIOD_RE = re.compile(r"(\d{4}Q[1-4])")


class Compiler:
    def __init__(self, ontology: OntologyStore, llm=None):
        self.ontology = ontology
        self.llm = llm

    def compile(self, question: str, ctx: Optional[ExecContext] = None) -> SQG:
        if self.llm is not None:
            try:
                sqg = self._compile_llm(question)
                if sqg and sqg.nodes and sqg.nodes[0].concept:
                    return sqg
            except Exception:
                pass  # 回落规则
        return self._compile_rules(question)

    # ── LLM 路径 ──
    def _compile_llm(self, question: str) -> Optional[SQG]:
        metrics = [c for c in self.ontology.list_concepts() if c.kind == ConceptKind.metric]
        attrs = [c for c in self.ontology.list_concepts() if c.kind == ConceptKind.attribute]
        if not metrics:
            return None

        metric_lines = "\n".join(
            f"- id={m.id} 名称={m.name} 同义词={m.synonyms}" for m in metrics
        )
        role_lines = "\n".join(
            f"- role={a.attrs.get('role')} 名称={a.name} 同义词={a.synonyms}"
            for a in attrs if a.attrs.get("role")
        )
        system = (
            "你是一个查询编译器。根据用户问题，从下列已知指标与维度里选出对应项，只输出 JSON。\n"
            f"已知指标：\n{metric_lines}\n已知维度：\n{role_lines}\n"
            "输出格式：{\"metric\": \"<指标 id>\", \"filters\": {\"<role>\": \"<取值>\"}}。\n"
            "规则：metric 必须是上面某个指标 id；filters 的 key 必须是上面的 role；"
            "只放问题中明确出现的过滤值；地区用中文（如 华东）；期间用 YYYYQn（如 2024Q1）；"
            "若用户说『上季度』，取 2024Q1；无法识别的过滤项不要输出。"
        )
        out = self.llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": question}],
            schema={"type": "object"},
        )
        data = out if isinstance(out, dict) else json.loads(out)

        metric = self.ontology.get_concept(data.get("metric", ""))
        if not metric or metric.kind != ConceptKind.metric:
            return None

        filters = []
        for role, value in (data.get("filters") or {}).items():
            if not value:
                continue
            attr = self._attr_by_role(role)
            if attr:
                filters.append({"concept": attr.id, "value": value})

        node = SQGNode(id="n1", operator=Operator.AGGREGATE, name=metric.name,
                       concept=metric.id, params={"filters": filters})
        return SQG(question=question, nodes=[node])

    # ── 规则兜底 ──
    def _compile_rules(self, question: str) -> SQG:
        q = question or ""
        metric = self._find_metric(q)
        filters = []

        rm = _REGION_RE.search(q)
        if rm:
            attr = self._attr_by_role("region")
            if attr:
                filters.append({"concept": attr.id, "value": rm.group(1)})

        pm = _PERIOD_RE.search(q)
        period_val = pm.group(1) if pm else (DEFAULT_PERIOD if ("上季度" in q or "季度" in q) else None)
        if period_val:
            attr = self._attr_by_role("period")
            if attr:
                filters.append({"concept": attr.id, "value": period_val})

        node = SQGNode(
            id="n1",
            operator=Operator.AGGREGATE,
            name=(metric.name if metric else "指标"),
            concept=(metric.id if metric else None),
            params={"filters": filters},
        )
        return SQG(question=question, nodes=[node])

    def _find_metric(self, q: str):
        ql = q.lower()
        for c in self.ontology.list_concepts():
            if c.kind != ConceptKind.metric:
                continue
            terms = [c.name] + list(c.synonyms)
            if any(t and t.lower() in ql for t in terms):
                return c
        return None

    def _attr_by_role(self, role: str):
        for c in self.ontology.list_concepts():
            if c.kind == ConceptKind.attribute and c.attrs.get("role") == role:
                return c
        return None
