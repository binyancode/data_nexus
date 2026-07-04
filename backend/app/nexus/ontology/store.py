"""本体存储：Concept / Binding 的读写。

P0 用 SQLite 模拟（设计文档第 14 节：本体存储选型待定，先 SQL 起步）。
"""
from abc import ABC, abstractmethod
from typing import Optional

from nexus.core.models import Binding, Concept


class OntologyStore(ABC):
    """本体读写接口。编译时查 Concept/Binding。"""

    @abstractmethod
    def list_concepts(self) -> list[Concept]: ...

    @abstractmethod
    def get_concept(self, concept_id: str) -> Optional[Concept]: ...

    @abstractmethod
    def upsert_concept(self, concept: Concept) -> None: ...

    @abstractmethod
    def get_binding(self, binding_id: str) -> Optional[Binding]: ...

    @abstractmethod
    def upsert_binding(self, binding: Binding) -> None: ...


class SqliteOntologyStore(OntologyStore):
    """SQLite 实现（P0 骨架）。"""

    def __init__(self, path: str = "nexus_ontology.db"):
        self.path = path
        # TODO(P0): 建表 nexus_concepts / nexus_bindings；JSON 列存复合字段

    def list_concepts(self) -> list[Concept]:
        # TODO(P0): SELECT * FROM nexus_concepts
        return []

    def get_concept(self, concept_id: str) -> Optional[Concept]:
        raise NotImplementedError("SqliteOntologyStore.get_concept 尚未实现（P0）")

    def upsert_concept(self, concept: Concept) -> None:
        raise NotImplementedError("SqliteOntologyStore.upsert_concept 尚未实现（P0）")

    def get_binding(self, binding_id: str) -> Optional[Binding]:
        raise NotImplementedError("SqliteOntologyStore.get_binding 尚未实现（P0）")

    def upsert_binding(self, binding: Binding) -> None:
        raise NotImplementedError("SqliteOntologyStore.upsert_binding 尚未实现（P0）")
