"""OntologyRouter：问题 → 选一份本体（按 name + description 让 LLM 判断）。

无匹配/无 LLM 时回退到最近更新的一份。
"""

from __future__ import annotations

import json
from typing import Optional

from utils.logger import get_logger

_logger = get_logger("nexus")


class OntologyRouter:
    def __init__(self, llm=None):
        self.llm = llm

    def pick(self, question: str, ontologies: list) -> Optional[str]:
        """ontologies: list[Ontology]（含 ontology_id/name/description）。返回 ontology_id。"""
        candidates = [o for o in ontologies]
        if not candidates:
            return None
        if len(candidates) == 1 or self.llm is None:
            return candidates[0].ontology_id

        catalog = "\n".join(
            f"  - id={o.ontology_id}｜名称={o.name}｜说明={(o.description or '')[:300]}"
            for o in candidates
        )
        system = (
            "你是本体路由器。根据用户问题，从下面的本体清单里选唯一最合适的一个来回答，"
            "只输出 JSON：{\"ontology_id\":\"<id>\"}。\n# 本体清单\n" + catalog
        )
        try:
            out = self.llm.complete(
                [{"role": "system", "content": system}, {"role": "user", "content": question}],
                schema={"type": "object"},
            )
            data = out if isinstance(out, dict) else json.loads(out)
            picked = data.get("ontology_id")
            if any(o.ontology_id == picked for o in candidates):
                return picked
        except Exception as exc:
            _logger.warning(f"ontology router failed: {exc}")
        return candidates[0].ontology_id
