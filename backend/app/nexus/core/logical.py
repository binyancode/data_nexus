"""Typed high-level Semantic Query Graph (SQG).

SQG nodes are business tasks, not relational-algebra operators.  Physical
FILTER/JOIN/SORT/LIMIT details are lowered by the Optimizer.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

from nexus.core.expressions import Expression, Predicate, AggregateFunction


class Operator(str, Enum):
    SELECT = "SELECT"
    AGGREGATE = "AGGREGATE"
    CALCULATE = "CALCULATE"
    SEARCH = "SEARCH"
    BROWSE = "BROWSE"
    ASK = "ASK"
    ACT = "ACT"


class ResultKind(str, Enum):
    SCALAR = "SCALAR"
    TABLE = "TABLE"
    RANKING = "RANKING"
    DOCUMENT = "DOCUMENT"
    SEARCH = "SEARCH"
    TEXT = "TEXT"
    ACTION = "ACTION"


class ResultField(BaseModel):
    name: str
    data_type: str = "unknown"
    role: Literal["dimension", "measure", "value"] = "value"
    unit: str | None = None
    nullable: bool = True


class ResultContract(BaseModel):
    kind: ResultKind
    name: str = ""
    fields: list[ResultField] = Field(default_factory=list)
    grain: list[str] = Field(default_factory=list)
    domain: str | None = None
    ordering: list[str] = Field(default_factory=list)
    unit: str | None = None


class SubjectSpec(BaseModel):
    entity: str


class SelectField(BaseModel):
    concept: str
    output: str


class AttributeDimension(BaseModel):
    kind: Literal["attribute"] = "attribute"
    concept: str
    output: str


class TimeDimension(BaseModel):
    kind: Literal["time"] = "time"
    attribute: str
    grain: Literal["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"]
    calendar: str = "GREGORIAN"
    timezone: str = "UTC"
    output: str


DimensionSpec = Annotated[Union[AttributeDimension, TimeDimension], Field(discriminator="kind")]


class StatisticSpec(BaseModel):
    function: AggregateFunction
    percentile: float | None = Field(default=None, ge=0, le=1)
    method: Literal["CONTINUOUS", "DISCRETE"] = "CONTINUOUS"
    accuracy: Literal["EXACT", "APPROXIMATE"] = "EXACT"
    nulls: Literal["IGNORE", "INCLUDE"] = "IGNORE"
    distinct: bool = False

    @model_validator(mode="after")
    def validate_percentile(self):
        if self.function == AggregateFunction.PERCENTILE and self.percentile is None:
            raise ValueError("PERCENTILE requires percentile")
        return self


class MetricMeasure(BaseModel):
    kind: Literal["metric"] = "metric"
    metric: str
    output: str


class StatisticMeasure(BaseModel):
    kind: Literal["statistic"] = "statistic"
    value: Expression | None = None
    statistic: StatisticSpec
    output: str


MeasureSpec = Annotated[Union[MetricMeasure, StatisticMeasure], Field(discriminator="kind")]


class OrderKey(BaseModel):
    field: str
    direction: Literal["ASC", "DESC"] = "ASC"
    nulls: Literal["FIRST", "LAST"] = "LAST"


class RankingSpec(BaseModel):
    by: str
    direction: Literal["ASC", "DESC"] = "DESC"
    take: int = Field(gt=0)
    ties: Literal["EXCLUDE", "INCLUDE"] = "EXCLUDE"
    tie_breakers: list[OrderKey] = Field(default_factory=list)


class DomainPolicy(BaseModel):
    unmatched: Literal["EXCLUDE_UNMATCHED", "KEEP_AS_UNKNOWN", "ERROR_ON_UNMATCHED"] = "EXCLUDE_UNMATCHED"
    unknown_label: str = "未知"


class SelectSpec(BaseModel):
    subject: SubjectSpec
    scope: Predicate | None = None
    fields: list[SelectField]
    distinct: bool = False
    result: ResultContract


class AggregateSpec(BaseModel):
    subject: SubjectSpec
    scope: Predicate | None = None
    dimensions: list[DimensionSpec] = Field(default_factory=list)
    measure: MeasureSpec
    result_filter: Predicate | None = None
    ranking: RankingSpec | None = None
    domain_policy: DomainPolicy = Field(default_factory=DomainPolicy)
    result: ResultContract

    @model_validator(mode="after")
    def complete_result_contract(self):
        if self.ranking is not None and not self.ranking.tie_breakers:
            raise ValueError("ranking requires at least one deterministic tie_breaker")
        dimension_names = [dimension.output for dimension in self.dimensions]
        field_names = {field.name for field in self.result.fields}
        for dimension in self.dimensions:
            if dimension.output not in field_names:
                self.result.fields.append(ResultField(
                    name=dimension.output, data_type="date" if isinstance(dimension, TimeDimension) else "unknown",
                    role="dimension",
                ))
        if self.measure.output not in {field.name for field in self.result.fields}:
            self.result.fields.append(ResultField(
                name=self.measure.output, data_type="number", role="measure", unit=self.result.unit,
            ))
        if not self.result.grain:
            self.result.grain = dimension_names
        return self


class AlignmentSpec(BaseModel):
    keys: list[str] = Field(default_factory=list)
    domain: Literal["INNER", "LEFT", "OUTER"] = "INNER"
    scalar_broadcast: bool = False


class NamedExpression(BaseModel):
    name: str
    expression: Expression


class SelectionSpec(BaseModel):
    kind: Literal["MIN_BY", "MAX_BY", "TOP_N", "BOTTOM_N"]
    field: str
    take: int = Field(default=1, gt=0)
    nulls: Literal["FIRST", "LAST"] = "LAST"
    tie_breakers: list[OrderKey] = Field(default_factory=list)


class CalculateSpec(BaseModel):
    alignment: AlignmentSpec = Field(default_factory=AlignmentSpec)
    outputs: list[NamedExpression]
    selection: SelectionSpec | None = None
    result: ResultContract


class InputRef(BaseModel):
    node: str
    output: str | None = None
    row: int | None = Field(default=None, ge=0)


class SearchSpec(BaseModel):
    query: str
    max_results: int = Field(default=10, gt=0, le=100)
    language: str | None = None
    region: str | None = None
    max_length: int | None = None
    content_format: str | None = None
    location: dict[str, Any] | None = None
    include_adult: bool | None = None


class BrowseSpec(BaseModel):
    url: str
    max_length: int | None = None
    live_crawl: bool | None = None
    render_dynamic_pages: bool | None = None
    include_web_links: bool | None = None
    include_image_links: bool | None = None
    language: str | None = None
    region: str | None = None
    content_format: str | None = None


class AskSpec(BaseModel):
    instruction: str
    format: Literal["MARKDOWN", "TEXT"] = "MARKDOWN"
    system: str | None = None


class ActSpec(BaseModel):
    action: str
    recipient: str | None = None
    assignee: str | None = None
    title: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class TaskNode(BaseModel):
    id: str
    name: str
    depends_on: list[str] = Field(default_factory=list)
    inputs: dict[str, InputRef] = Field(default_factory=dict)

    def result_kind(self) -> str:
        spec = getattr(self, "spec", None)
        result = getattr(spec, "result", None)
        return result.kind.value.lower() if result is not None else "unknown"

    def output_fields(self) -> set[str]:
        result = getattr(getattr(self, "spec", None), "result", None)
        return {field.name for field in result.fields} if result is not None else set()


class SelectNode(TaskNode):
    operator: Literal[Operator.SELECT] = Operator.SELECT
    spec: SelectSpec


class AggregateNode(TaskNode):
    operator: Literal[Operator.AGGREGATE] = Operator.AGGREGATE
    spec: AggregateSpec


class CalculateNode(TaskNode):
    operator: Literal[Operator.CALCULATE] = Operator.CALCULATE
    spec: CalculateSpec


class SearchNode(TaskNode):
    operator: Literal[Operator.SEARCH] = Operator.SEARCH
    spec: SearchSpec

    def result_kind(self) -> str:
        return "search"

    def output_fields(self) -> set[str]:
        return {"title", "url", "content", "crawledAt", "lastUpdatedAt", "language",
            "isAdult", "clickUrl", "instrumentationSuffix", "contentTier"}


class BrowseNode(TaskNode):
    operator: Literal[Operator.BROWSE] = Operator.BROWSE
    spec: BrowseSpec

    def result_kind(self) -> str:
        return "document"

    def output_fields(self) -> set[str]:
        return {"title", "url", "content", "lastUpdatedAt", "crawledAt",
                "isAdult", "webLinks", "imageLinks"}


class AskNode(TaskNode):
    operator: Literal[Operator.ASK] = Operator.ASK
    spec: AskSpec

    def result_kind(self) -> str:
        return "text"

    def output_fields(self) -> set[str]:
        return {"value"}


class ActNode(TaskNode):
    operator: Literal[Operator.ACT] = Operator.ACT
    spec: ActSpec

    def result_kind(self) -> str:
        return "action"

    def output_fields(self) -> set[str]:
        return {"value"}


SQGNode = Annotated[
    Union[SelectNode, AggregateNode, CalculateNode, SearchNode, BrowseNode, AskNode, ActNode],
    Field(discriminator="operator"),
]


class SQG(BaseModel):
    version: int = 3
    question: str
    nodes: list[SQGNode] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)

    def node(self, node_id: str) -> SQGNode | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    @model_validator(mode="after")
    def validate_graph(self):
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise ValueError("SQG node ids must be unique")
        known = set(ids)
        for node in self.nodes:
            if node.id in node.depends_on:
                raise ValueError(f"SQG node {node.id} depends on itself")
            missing = set(node.depends_on) - known
            if missing:
                raise ValueError(f"SQG node {node.id} has missing dependencies: {sorted(missing)}")
            input_nodes = {input_ref.node for input_ref in node.inputs.values()}
            missing_inputs = input_nodes - known
            if missing_inputs:
                raise ValueError(f"SQG node {node.id} has missing input nodes: {sorted(missing_inputs)}")
            unordered_inputs = input_nodes - set(node.depends_on)
            if unordered_inputs:
                raise ValueError(
                    f"SQG node {node.id} inputs must also be declared in depends_on: "
                    f"{sorted(unordered_inputs)}"
                )
        if set(self.outputs) - known:
            raise ValueError("SQG outputs must reference existing nodes")
        consumed = {dependency for node in self.nodes for dependency in node.depends_on}
        terminal = {node.id for node in self.nodes if node.id not in consumed}
        requested = set(self.outputs) | terminal
        self.outputs = [node.id for node in self.nodes if node.id in requested]
        return self
