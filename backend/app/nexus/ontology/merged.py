"""MergedOntology：把多份已命名空间化的 JsonOntology 合并成一个只读本体视图。

多本体查询时，初始化器为每个选中本体建 `JsonOntology(graph, ns=ontology_id)`，
其概念 id 都带 `ontology_id::` 前缀、**全局唯一**；本类做**并集/委派**即可，
不存在 id 冲突。含单个子本体时等价于该子本体（行为不变）。
"""

from __future__ import annotations

from typing import Optional

from nexus.core.models import Concept, Binding
from nexus.ontology.store import OntologyStore


class MergedOntology(OntologyStore):
    def __init__(self, subs: list[OntologyStore]):
        self._subs = list(subs)

    # ── 读接口：并集 / 命中即返回（前缀保证唯一）──
    def list_concepts(self) -> list[Concept]:
        return [c for s in self._subs for c in s.list_concepts()]

    def get_concept(self, concept_id: str) -> Optional[Concept]:
        for s in self._subs:
            c = s.get_concept(concept_id)
            if c is not None:
                return c
        return None

    def find_concept(self, term: str) -> Optional[Concept]:
        for s in self._subs:
            c = s.find_concept(term)
            if c is not None:
                return c
        return None

    def list_bindings(self, concept_id: Optional[str] = None) -> list[Binding]:
        return [b for s in self._subs for b in s.list_bindings(concept_id)]

    def get_bindings(self, concept_id: str) -> list[Binding]:
        for s in self._subs:
            bs = s.get_bindings(concept_id)
            if bs:
                return bs
        return []

    # ── 写接口：合并视图只读 ──
    def upsert_concept(self, concept: Concept) -> None:
        raise NotImplementedError("MergedOntology 只读")

    def upsert_binding(self, binding: Binding) -> None:
        raise NotImplementedError("MergedOntology 只读")
