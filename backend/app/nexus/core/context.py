"""执行期数据结构：调度产物、执行上下文、解析结果、结构探测。"""
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from pydantic import BaseModel, Field


class PlannedCall(BaseModel):
    """调度器把一个 SQG 节点编译成的「具体调用」。"""
    node: str
    resolver: str
    call: Any                                # SQL 串 / 检索请求 / NL 问法 / HTTP 请求
    trust: float = 0.8
    user_scoped: bool = False                # 需要透传当前用户身份


class Plan(BaseModel):
    """整张执行计划。"""
    as_user: Optional[str] = None
    plan: list[PlannedCall] = Field(default_factory=list)


class ResolveResult(BaseModel):
    """Resolver 执行返回：数据 / 答案+证据 / 回执，三种统一形状。"""
    data: Any = None
    evidence: list[Any] = Field(default_factory=list)
    trust: float = 0.8
    meta: dict[str, Any] = Field(default_factory=dict)


class SourceSchema(BaseModel):
    """describe() 探测出的源结构：表/字段/外键，供自动建本体。"""
    tables: dict[str, list[str]] = Field(default_factory=dict)   # table -> columns
    foreign_keys: list[dict[str, str]] = Field(default_factory=list)


@dataclass
class ExecContext:
    """执行上下文。user_scoped 节点执行时通过 with_user 注入当前用户。"""
    user: Optional[str] = None
    trace_id: Optional[str] = None
    cancellation_token: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    def with_user(self, user: str) -> "ExecContext":
        return replace(self, user=user)
