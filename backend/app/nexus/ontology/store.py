"""本体存储抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from nexus.core.models import Concept, Binding


class OntologyStore(ABC):
    """本体存储：概念与绑定的读写。"""

    @abstractmethod
    def list_concepts(self) -> list[Concept]: ...

    @abstractmethod
    def get_concept(self, concept_id: str) -> Optional[Concept]: ...

    @abstractmethod
    def find_concept(self, term: str) -> Optional[Concept]:
        """按名称或同义词查找概念（供编译器把自然语言词映射到概念）。"""
        ...

    @abstractmethod
    def upsert_concept(self, concept: Concept) -> None: ...

    @abstractmethod
    def list_bindings(self, concept_id: Optional[str] = None) -> list[Binding]: ...

    @abstractmethod
    def get_bindings(self, concept_id: str) -> list[Binding]: ...

    @abstractmethod
    def upsert_binding(self, binding: Binding) -> None: ...
