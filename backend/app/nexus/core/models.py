"""Nexus 领域模型（pydantic）。

覆盖四层数据：
  - 本体：Concept / Binding
  - 查询：SQGNode / SQG（语义查询图）
  - 计划：PlanStep / QueryPlan（优化器产物）
  - 结果：NodeResult / LineageItem / Answer
  - 执行上下文：ExecContext
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─────────────────────────── 本体 ───────────────────────────
class ConceptKind(str, Enum):
    entity = "entity"
    attribute = "attribute"
    relation = "relation"
    metric = "metric"
    derivation = "derivation"


class Concept(BaseModel):
    """业务概念（5 种 kind 共用外壳，kind 专属字段放 attrs）。"""
    id: str
    kind: ConceptKind
    name: str
    semantics: Optional[str] = None
    synonyms: list[str] = Field(default_factory=list)
    attrs: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


class Binding(BaseModel):
    """概念 → 物理落点（entity→表 / attribute→列 / metric→表达式 …）。"""
    id: str
    concept_id: str
    resolver: str
    kind: str  # table | column | prompt | file | endpoint | expr
    expr: Optional[str] = None
    confidence: float = 1.0


# ─────────────────────────── 查询（SQG） ───────────────────────────
class Operator(str, Enum):
    SELECT = "SELECT"      # 取明细
    FILTER = "FILTER"      # 过滤条件
    AGGREGATE = "AGGREGATE"  # 聚合指标
    JOIN = "JOIN"          # 关联
    ASK = "ASK"            # 问一个 Agent
    ACT = "ACT"            # 执行动作


class SQGNode(BaseModel):
    """语义查询图节点。"""
    id: str
    operator: Operator
    name: str = ""                       # 业务名（如「华东毛利」）
    concept: Optional[str] = None        # 主概念 id（如 metric.gross_margin）
    params: dict[str, Any] = Field(default_factory=dict)  # 过滤/分组/聚合等参数
    depends_on: list[str] = Field(default_factory=list)


class SQG(BaseModel):
    """语义查询图：一次提问翻成的统一查询指令。"""
    question: str
    nodes: list[SQGNode] = Field(default_factory=list)

    def node(self, node_id: str) -> Optional[SQGNode]:
        return next((n for n in self.nodes if n.id == node_id), None)


# ─────────────────────────── 计划（优化器产物） ───────────────────────────
class PlanStep(BaseModel):
    """物理执行步骤：某个 SQG 节点选中的 Resolver + 具体调用。"""
    node_id: str
    resolver: str                         # 选中的 resolver 名
    call: dict[str, Any] = Field(default_factory=dict)  # 传给 resolver.fetch 的调用描述（如 {sql: ...}）
    depends_on: list[str] = Field(default_factory=list)


class QueryPlan(BaseModel):
    steps: list[PlanStep] = Field(default_factory=list)


# ─────────────────────────── 结果 / 血缘 ───────────────────────────
class LineageItem(BaseModel):
    """一个数字的出处（来源可追溯）。"""
    node_id: str
    label: str                            # 业务名，如「华东上季度毛利」
    value: Any = None
    resolver: str = ""
    source: str = ""                      # 库/表，如 dwh:dbo.fact_sales
    detail: str = ""                      # 口径/SQL 片段


class NodeResult(BaseModel):
    """单个节点的执行结果。"""
    node_id: str
    resolver: str = ""
    output: Any = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    trust: float = 1.0
    error: Optional[str] = None
    source: str = ""
    detail: str = ""


class Answer(BaseModel):
    """最终答案 + 出处。"""
    run_id: str
    question: str
    text: str = ""
    data: Any = None
    lineage: list[LineageItem] = Field(default_factory=list)
    status: str = "ok"


# ─────────────────────────── 执行上下文 ───────────────────────────
class ExecContext:
    """一次运行的执行上下文（非 pydantic：含取消令牌等运行时对象）。"""

    def __init__(self, question: str, as_user: Optional[str] = None, cancellation_token: Any = None):
        self.run_id: str = uuid.uuid4().hex
        self.question = question
        self.as_user = as_user
        self.cancellation_token = cancellation_token
        self.started_at = time.time()
        self.results: dict[str, NodeResult] = {}   # node_id -> NodeResult

    @property
    def cost_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)
