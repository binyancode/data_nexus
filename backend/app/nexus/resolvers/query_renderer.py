"""Query renderer contract shared by independently implemented SQL dialects."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable

from nexus.core.physical import QueryIR


TableSource = Callable[[str], str]


@dataclass(frozen=True)
class RenderedQuery:
    sql: str
    params: list[Any]


class QueryRenderer(ABC):
    """Render dialect-neutral ``QueryIR`` into one engine's SQL dialect.

    Implementations own their complete SQL generation strategy.  This class is
    deliberately interface-only: no quoting, expression, aggregate, ordering
    or limiting behavior is shared between dialects.
    """

    dialect: str

    @abstractmethod
    def render(self, query: QueryIR) -> RenderedQuery:
        """Render one physical query without mutating the input IR."""
        ...
