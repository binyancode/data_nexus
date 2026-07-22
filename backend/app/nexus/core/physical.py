"""Typed physical query IR and Physical Execution Plan (PEP)."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from nexus.core.expressions import AggregateExpr, Expression, Predicate
from nexus.core.logical import Operator, OrderKey, ResultContract


class QuerySource(BaseModel):
    entity: str
    object_name: str
    alias: str
    source_instance: str


class QueryJoin(BaseModel):
    relation: str
    source: QuerySource
    left: list[Expression]
    right: list[Expression]
    join_type: Literal["INNER", "LEFT"] = "INNER"
    cardinality: str = "unknown"


class QueryOutput(BaseModel):
    name: str
    expression: Expression | None = None
    aggregate: Expression | None = None


class QueryIR(BaseModel):
    source: QuerySource
    joins: list[QueryJoin] = Field(default_factory=list)
    predicate: Predicate | None = None
    dimensions: list[QueryOutput] = Field(default_factory=list)
    outputs: list[QueryOutput] = Field(default_factory=list)
    result_predicate: Predicate | None = None
    distinct: bool = False
    order_by: list[OrderKey] = Field(default_factory=list)
    limit: int | None = None


class LogicalOutputBinding(BaseModel):
    logical_node: str
    logical_field: str | None = None
    physical_field: str | None = None
    physical_result: str | None = None


class PlanEstimate(BaseModel):
    rows: int | None = None
    bytes: int | None = None
    cost: float | None = None


class SourceFragment(BaseModel):
    id: str
    kind: Literal["SOURCE_FRAGMENT"] = "SOURCE_FRAGMENT"
    name: str
    source_instance: str
    query: QueryIR
    call: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    wave: int = 1
    realizes: list[LogicalOutputBinding] = Field(default_factory=list)
    estimates: PlanEstimate | None = None


class ExchangeFragment(BaseModel):
    id: str
    kind: Literal["EXCHANGE"] = "EXCHANGE"
    name: str
    mode: Literal["MATERIALIZE", "BROADCAST", "SEMI_JOIN_KEYS", "STREAM"] = "MATERIALIZE"
    from_fragment: str
    into: str
    depends_on: list[str]
    wave: int = 1
    realizes: list[LogicalOutputBinding] = Field(default_factory=list)
    estimates: PlanEstimate | None = None


class ComputeInput(BaseModel):
    table: str
    from_fragment: str


class ComputeFragment(BaseModel):
    id: str
    kind: Literal["COMPUTE_FRAGMENT"] = "COMPUTE_FRAGMENT"
    name: str
    engine: str = "duckdb"
    inputs: list[ComputeInput]
    query: QueryIR
    into: str | None = None
    depends_on: list[str]
    wave: int = 1
    realizes: list[LogicalOutputBinding] = Field(default_factory=list)
    estimates: PlanEstimate | None = None


class CapabilityFragment(BaseModel):
    id: str
    kind: Literal["CAPABILITY"] = "CAPABILITY"
    name: str
    operator: Operator
    resolver: str
    call: dict[str, Any]
    depends_on: list[str] = Field(default_factory=list)
    wave: int = 1
    realizes: list[LogicalOutputBinding] = Field(default_factory=list)


PlanNode = Annotated[
    Union[SourceFragment, ExchangeFragment, ComputeFragment, CapabilityFragment],
    Field(discriminator="kind"),
]


class PhysicalExecutionPlan(BaseModel):
    artifact_type: str = "physical_execution_plan"
    version: int = 3
    nodes: list[PlanNode] = Field(default_factory=list)
    logical_results: dict[str, ResultContract] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)

    def node(self, node_id: str) -> PlanNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)
