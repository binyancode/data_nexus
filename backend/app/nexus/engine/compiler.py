"""编译器 Compiler：自然语言 → SQG（DAG）。

职责：意图识别、概念消歧（把「毛利/华东/上季度」映射到 Concept id）、
拆算子建 DAG 标注 deps、注入 as_user。
实现建议：LLM 受约束生成（给定 Concept 清单 + 算子 schema，输出 JSON）+ schema 校验。
"""
from typing import Any, Optional

from nexus.core.sqg import SQG
from nexus.ontology.store import OntologyStore


class Compiler:
    def __init__(self, ontology: OntologyStore, llm: Any = None):
        self.ontology = ontology
        self.llm = llm

    async def compile(
        self,
        nl: str,
        as_user: Optional[str] = None,
        history: Optional[list] = None,
    ) -> SQG:
        # TODO(P0): 拉取 Concept 清单 → LLM 受约束生成 SQG → 校验
        raise NotImplementedError("Compiler.compile 尚未实现（P0）")
