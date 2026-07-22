"""Serializable Optimizer artifacts between typed SQG and physical execution."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from nexus.core.expressions import AggregateExpr, Expression, Predicate
from nexus.core.logical import OrderKey, ResultField


class BoundEntity(BaseModel):
    concept: str
    object_name: str
    source_instance: str
    key: str | list[str] | None = None


class BoundAttribute(BaseModel):
    concept: str
    entity: str
    column: str
    source_instance: str
    data_type: str = "unknown"
    role: str = "dimension"
    additivity: str | None = None


class RelationMultiplicity(BaseModel):
    min: int | str
    max: int | str


class BoundRelation(BaseModel):
    concept: str
    from_entity: str
    from_attributes: list[str]
    to_entity: str
    to_attributes: list[str]
    from_to: RelationMultiplicity
    to_from: RelationMultiplicity
    integrity_mode: str
    confidence: float = 0.0
    temporal: dict[str, Any] | None = None


class SemanticTaskBinding(BaseModel):
    logical_node: str
    entities: list[BoundEntity] = Field(default_factory=list)
    attributes: list[BoundAttribute] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)
    relations: list[BoundRelation] = Field(default_factory=list)
    source_instances: list[str] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class SemanticBindingArtifact(BaseModel):
    artifact_type: str = "semantic_binding"
    schema_version: int = 3
    tasks: list[SemanticTaskBinding] = Field(default_factory=list)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class BoundOperator(str, Enum):
    SCAN = "SCAN"
    FILTER = "FILTER"
    RELATE = "RELATE"
    PROJECT = "PROJECT"
    DERIVE = "DERIVE"
    AGGREGATE = "AGGREGATE"
    DISTINCT = "DISTINCT"
    WINDOW = "WINDOW"
    TOP_N = "TOP_N"
    CALCULATE = "CALCULATE"
    CAPABILITY = "CAPABILITY"


class BoundLogicalNode(BaseModel):
    id: str
    kind: BoundOperator
    name: str = ""
    inputs: list[str] = Field(default_factory=list)
    origin_sqg_nodes: list[str] = Field(default_factory=list)
    result_fields: list[ResultField] = Field(default_factory=list)
    grain: list[str] = Field(default_factory=list)
    domain: str | None = None
    cardinality: str | None = None
    source_candidates: list[str] = Field(default_factory=list)
    entity: BoundEntity | None = None
    predicate: Predicate | None = None
    relation: BoundRelation | None = None
    expressions: list[tuple[str, Expression]] = Field(default_factory=list)
    dimensions: list[tuple[str, Expression]] = Field(default_factory=list)
    aggregate: Expression | None = None
    order_by: list[OrderKey] = Field(default_factory=list)
    limit: int | None = None
    capability: str | None = None


class BoundLogicalPlan(BaseModel):
    artifact_type: str = "bound_logical_plan"
    schema_version: int = 3
    nodes: list[BoundLogicalNode] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
    diagnostics: list[dict[str, Any]] = Field(default_factory=list)


class RuleDecision(BaseModel):
    rule: str
    outcome: str
    logical_nodes: list[str] = Field(default_factory=list)
    reason: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class PlanCandidate(BaseModel):
    id: str
    strategy: str
    logical_nodes: list[str] = Field(default_factory=list)
    estimated_rows: int | None = None
    estimated_bytes: int | None = None
    estimated_cost: float | None = None
    selected: bool = False
    reason: str = ""


class OptimizationTrace(BaseModel):
    artifact_type: str = "optimization_trace"
    schema_version: int = 3
    rules: list[RuleDecision] = Field(default_factory=list)
    candidates: list[PlanCandidate] = Field(default_factory=list)
    selected_plan: str | None = None
