"""知识层领域模型：Concept（概念）与 Binding（绑定）。

Concept 只讲业务「是什么」；Binding 把概念落到物理对象上。
换库/加源只改 Binding，Concept 不动；同一 Concept 可绑多个 Binding = 跨源融合。
"""
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConceptKind(str, Enum):
    entity = "entity"        # 实体：客户、产品
    attribute = "attribute"  # 属性：客户名称、产品单价
    relation = "relation"    # 关系：订单→客户
    metric = "metric"        # 指标（可聚合）：销售额、毛利
    dimension = "dimension"  # 维度（可切分）：地区、时间


class Policy(BaseModel):
    """权限（治理内生，随概念挂载）。"""
    sensitivity: str = "internal"
    row_level: bool = False


class Provenance(BaseModel):
    """血缘。"""
    generated_by: str = "manual"   # auto | manual
    confidence: float = 1.0
    source_ref: Optional[str] = None
    updated_at: Optional[str] = None


class Concept(BaseModel):
    """业务名词。所有本体元素同一形状，靠 kind 区分。"""
    id: str                                    # e.g. "metric.gross_margin"
    kind: ConceptKind
    name: str                                  # 业务显示名，如「毛利」
    semantics: str = ""                        # 业务含义，供 LLM 消歧
    type: Optional[str] = None                 # 数据类型
    synonyms: list[str] = Field(default_factory=list)
    bindings: list[str] = Field(default_factory=list)   # 指向 Binding.id，可多个
    policy: Policy = Field(default_factory=Policy)
    provenance: Provenance = Field(default_factory=Provenance)


class BindingKind(str, Enum):
    sql_expr = "sql_expr"
    column = "column"
    join = "join"
    prompt = "prompt"
    file = "file"
    endpoint = "endpoint"


class Join(BaseModel):
    left: str
    right: str


class Binding(BaseModel):
    """概念 → 物理映射。对接目标因 Resolver 而异（表/模板/路径/端点）。"""
    id: str                                    # e.g. "bind.gross_margin.dwh"
    concept_id: str
    resolver: str                              # 由哪个 Resolver 执行
    kind: BindingKind
    expr: Optional[str] = None                 # 如 "SUM(fact_sales.gross_margin)"
    table: Optional[str] = None
    joins: list[Join] = Field(default_factory=list)
    grain: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    extra: dict[str, Any] = Field(default_factory=dict)
