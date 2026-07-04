"""SQG（Semantic Query Graph，语义查询图）：一张 DAG，节点=算子、边=依赖。"""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class Operator(str, Enum):
    SELECT = "SELECT"        # 取属性/文档
    FILTER = "FILTER"        # 维度约束
    AGGREGATE = "AGGREGATE"  # 指标计算
    TRAVERSE = "TRAVERSE"    # 沿关系跳转（天然跨源 join）
    ASK = "ASK"              # 把一段交给 Agent 回答
    ACT = "ACT"              # 执行动作/写回


class SQGNode(BaseModel):
    id: str
    op: Operator
    concept: Optional[str] = None            # 该节点关心的概念（ASK/ACT 可空）
    filter: dict[str, Any] = Field(default_factory=dict)
    groupBy: Optional[str] = None
    range: Optional[str] = None
    query: Optional[str] = None              # SELECT 检索词
    prompt: Optional[str] = None             # ASK 问法，{nX} 为占位符
    action: Optional[str] = None             # ACT 动作
    deps: list[str] = Field(default_factory=list)   # 依赖节点，决定执行波次


class SQG(BaseModel):
    intent: str
    as_user: Optional[str] = None            # 当前用户（权限透传）
    nodes: list[SQGNode] = Field(default_factory=list)
