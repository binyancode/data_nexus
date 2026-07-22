"""Nexus 领域模型（pydantic）。

覆盖四层数据：
  - 本体：Concept / Binding
    - 计划：PhysicalExecutionPlan（优化器产物）
  - 结果：NodeResult / LineageItem / Answer
  - 执行上下文：ExecContext
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from nexus.core.run_log import RunRecorder, NullRunRecorder


# ─────────────────────────── 本体 ───────────────────────────
class ConceptKind(str, Enum):
    entity = "entity"
    attribute = "attribute"
    relation = "relation"
    metric = "metric"
    derivation = "derivation"
    action = "action"


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


class Ontology(BaseModel):
    """一份本体：元数据 + 一整块 graph JSON（所有概念）。按行存于 nexus.ontology。"""
    ontology_id: str
    name: str
    description: Optional[str] = None
    owner: str = ""
    visibility: str = "private"           # private | shared | public
    state: str = "draft"                  # draft | published
    graph: dict[str, Any] = Field(default_factory=dict)
    grants: list[str] = Field(default_factory=list)  # shared 时的可见用户
    updated_at: Optional[str] = None


def topo_waves(nodes: list) -> list[list]:
    """按 depends_on 拓扑分波：返回 [[wave1节点...], [wave2...], ...]。
    适用于任何带 .id / .depends_on 的逻辑或物理节点。"""
    ids = {n.id for n in nodes}
    done: set = set()
    remaining = list(nodes)
    waves: list[list] = []
    while remaining:
        ready = [n for n in remaining
                 if all((d in done) or (d not in ids) for d in n.depends_on)]
        if not ready:                      # 成环保护：剩余全放最后一波
            ready = remaining
        waves.append(ready)
        done.update(n.id for n in ready)
        remaining = [n for n in remaining if n.id not in done]
    return waves


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
    logs: dict[str, Any] = Field(default_factory=dict)   # 自定义日志（JSON），如 ASK 生成的完整提示词


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

    def __init__(self, question: str, as_user: Optional[str] = None, cancellation_token: Any = None,
                 run_id: Optional[str] = None):
        self.run_id: str = run_id or uuid.uuid4().hex
        self.question = question
        self.as_user = as_user
        self.ontology_ids: list[str] = []                 # 本次运行选中的本体集合（初始化器填）
        self.requested_ontology_id: Optional[str] = None  # 用户显式指定的本体（None=交初始化器 LLM 路由）
        self.llm_name: Optional[str] = None       # 本次运行选中的规划 LLM（None=用默认）
        self.cancellation_token = cancellation_token
        self.started_at = time.time()
        self.results: dict[str, NodeResult] = {}   # node_id -> NodeResult
        self.physical_results: dict[str, NodeResult] = {}  # PEP fragment id -> physical result
        self.context: dict[str, Any] = {}          # 引擎间交接包（携 plan.context）
        self.stage_logs: dict[str, Any] = {}        # 当前 stage 的自定义日志（JSON），每段前清空
        self.compute: Any = None                    # 跨源内存计算引擎（ComputeEngine），协调器按需创建
        self.recorder: RunRecorder = NullRunRecorder()  # 运行记录器（由 client 注入）

    @property
    def cost_ms(self) -> int:
        return int((time.time() - self.started_at) * 1000)
