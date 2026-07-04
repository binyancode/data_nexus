"""API 层请求/响应模型（与 nexus 领域模型解耦）。"""
from typing import Any, Optional

from models.base import BaseSchema


class AskRequest(BaseSchema):
    """一次自然语言提问。"""
    q: str
    as_user: Optional[str] = None


class AskResponse(BaseSchema):
    """最终答案 + 血缘。"""
    answer: str
    lineage: list[Any] = []


class ConceptUpsertRequest(BaseSchema):
    """新增/更新一个概念（字段见 nexus.core.models.Concept）。"""
    concept: dict[str, Any]
