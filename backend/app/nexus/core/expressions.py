"""Strongly typed, dialect-neutral scalar and predicate expressions."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter


class DataType(str, Enum):
    number = "number"
    text = "text"
    date = "date"
    datetime = "datetime"
    bool = "bool"
    unknown = "unknown"


class AttributeExpr(BaseModel):
    kind: Literal["attribute"] = "attribute"
    concept: str


class ColumnExpr(BaseModel):
    kind: Literal["column"] = "column"
    source: str
    name: str


class LiteralExpr(BaseModel):
    kind: Literal["literal"] = "literal"
    value: Any = None
    data_type: DataType | None = None


class NodeOutputExpr(BaseModel):
    kind: Literal["node_output"] = "node_output"
    input: str
    field: str


class OutputExpr(BaseModel):
    kind: Literal["output"] = "output"
    name: str


class BinaryExpr(BaseModel):
    kind: Literal["binary"] = "binary"
    operator: Literal[
        "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "SAFE_DIVIDE",
    ]
    left: "Expression"
    right: "Expression"
    zero_division: Literal["NULL", "ZERO", "ERROR"] = "NULL"


class UnaryExpr(BaseModel):
    kind: Literal["unary"] = "unary"
    operator: Literal["NEGATE"]
    operand: "Expression"


class FunctionExpr(BaseModel):
    kind: Literal["function"] = "function"
    name: Literal["COALESCE", "ABS", "ROUND", "LOWER", "UPPER"]
    arguments: list["Expression"] = Field(default_factory=list)


class TimeBucketExpr(BaseModel):
    kind: Literal["time_bucket"] = "time_bucket"
    value: "Expression"
    grain: Literal["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"]
    calendar: str = "GREGORIAN"
    timezone: str = "UTC"


class AggregateFunction(str, Enum):
    SUM = "SUM"
    COUNT = "COUNT"
    COUNT_DISTINCT = "COUNT_DISTINCT"
    AVG = "AVG"
    MIN = "MIN"
    MAX = "MAX"
    MEDIAN = "MEDIAN"
    PERCENTILE = "PERCENTILE"
    VARIANCE = "VARIANCE"
    STDDEV = "STDDEV"


class AggregateExpr(BaseModel):
    kind: Literal["aggregate"] = "aggregate"
    function: AggregateFunction
    value: "Expression | None" = None
    distinct: bool = False
    filter: "Predicate | None" = None
    percentile: float | None = Field(default=None, ge=0, le=1)
    method: Literal["CONTINUOUS", "DISCRETE"] = "CONTINUOUS"
    accuracy: Literal["EXACT", "APPROXIMATE"] = "EXACT"
    nulls: Literal["IGNORE", "INCLUDE"] = "IGNORE"


class CaseBranch(BaseModel):
    when: "Predicate"
    then: "Expression"


class CaseExpr(BaseModel):
    kind: Literal["case"] = "case"
    branches: list[CaseBranch]
    otherwise: "Expression | None" = None


Expression = Annotated[
    Union[
        AttributeExpr,
        ColumnExpr,
        LiteralExpr,
        NodeOutputExpr,
        OutputExpr,
        BinaryExpr,
        UnaryExpr,
        FunctionExpr,
        TimeBucketExpr,
        AggregateExpr,
        CaseExpr,
    ],
    Field(discriminator="kind"),
]


class TruePredicate(BaseModel):
    kind: Literal["true"] = "true"


class ComparisonPredicate(BaseModel):
    kind: Literal["comparison"] = "comparison"
    left: Expression
    operator: Literal["EQ", "NE", "GT", "GTE", "LT", "LTE", "LIKE"]
    right: Expression


class InPredicate(BaseModel):
    kind: Literal["in"] = "in"
    value: Expression
    values: list[Expression]


class BetweenPredicate(BaseModel):
    kind: Literal["between"] = "between"
    value: Expression
    lower: Expression
    upper: Expression
    lower_inclusive: bool = True
    upper_inclusive: bool = True


class NullPredicate(BaseModel):
    kind: Literal["null"] = "null"
    value: Expression
    is_null: bool = True


class TimeRangePredicate(BaseModel):
    kind: Literal["time_range"] = "time_range"
    attribute: str
    start: Any | None = None
    end_exclusive: Any | None = None
    timezone: str = "UTC"
    value_format: str | None = None


class AndPredicate(BaseModel):
    kind: Literal["and"] = "and"
    operands: list["Predicate"]


class OrPredicate(BaseModel):
    kind: Literal["or"] = "or"
    operands: list["Predicate"]


class NotPredicate(BaseModel):
    kind: Literal["not"] = "not"
    operand: "Predicate"


Predicate = Annotated[
    Union[
        TruePredicate,
        ComparisonPredicate,
        InPredicate,
        BetweenPredicate,
        NullPredicate,
        TimeRangePredicate,
        AndPredicate,
        OrPredicate,
        NotPredicate,
    ],
    Field(discriminator="kind"),
]


for _model in (
    BinaryExpr, UnaryExpr, FunctionExpr, TimeBucketExpr, CaseBranch, CaseExpr,
    ComparisonPredicate, InPredicate, BetweenPredicate, NullPredicate,
    AndPredicate, OrPredicate, NotPredicate, AggregateExpr,
):
    _model.model_rebuild(_types_namespace={"Expression": Expression, "Predicate": Predicate})

EXPRESSION_ADAPTER = TypeAdapter(Expression)
PREDICATE_ADAPTER = TypeAdapter(Predicate)


def expression_attributes(expr: Expression | None) -> set[str]:
    """Return all logical attribute concept ids referenced by an expression."""
    if expr is None:
        return set()
    if isinstance(expr, AttributeExpr):
        return {expr.concept}
    if isinstance(expr, BinaryExpr):
        return expression_attributes(expr.left) | expression_attributes(expr.right)
    if isinstance(expr, UnaryExpr):
        return expression_attributes(expr.operand)
    if isinstance(expr, FunctionExpr):
        return set().union(*(expression_attributes(a) for a in expr.arguments)) if expr.arguments else set()
    if isinstance(expr, TimeBucketExpr):
        return expression_attributes(expr.value)
    if isinstance(expr, AggregateExpr):
        return expression_attributes(expr.value) | predicate_attributes(expr.filter)
    if isinstance(expr, CaseExpr):
        attrs = expression_attributes(expr.otherwise)
        for branch in expr.branches:
            attrs |= predicate_attributes(branch.when)
            attrs |= expression_attributes(branch.then)
        return attrs
    return set()


def predicate_attributes(predicate: Predicate | None) -> set[str]:
    """Return all logical attribute concept ids referenced by a predicate."""
    if predicate is None or isinstance(predicate, TruePredicate):
        return set()
    if isinstance(predicate, ComparisonPredicate):
        return expression_attributes(predicate.left) | expression_attributes(predicate.right)
    if isinstance(predicate, InPredicate):
        attrs = expression_attributes(predicate.value)
        for value in predicate.values:
            attrs |= expression_attributes(value)
        return attrs
    if isinstance(predicate, BetweenPredicate):
        return (expression_attributes(predicate.value) | expression_attributes(predicate.lower)
                | expression_attributes(predicate.upper))
    if isinstance(predicate, NullPredicate):
        return expression_attributes(predicate.value)
    if isinstance(predicate, TimeRangePredicate):
        return {predicate.attribute}
    if isinstance(predicate, (AndPredicate, OrPredicate)):
        return set().union(*(predicate_attributes(p) for p in predicate.operands)) if predicate.operands else set()
    if isinstance(predicate, NotPredicate):
        return predicate_attributes(predicate.operand)
    return set()


def split_conjuncts(predicate: Predicate | None) -> list[Predicate]:
    if predicate is None or isinstance(predicate, TruePredicate):
        return []
    if isinstance(predicate, AndPredicate):
        out: list[Predicate] = []
        for operand in predicate.operands:
            out.extend(split_conjuncts(operand))
        return out
    return [predicate]


def combine_conjuncts(predicates: list[Predicate]) -> Predicate | None:
    if not predicates:
        return None
    if len(predicates) == 1:
        return predicates[0]
    return AndPredicate(operands=predicates)


def predicate_key(predicate: Predicate) -> str:
    return predicate.model_dump_json(exclude_none=True)


def aggregate_functions(expr: Expression | None) -> set[str]:
    if expr is None:
        return set()
    if isinstance(expr, AggregateExpr):
        return {expr.function.value} | aggregate_functions(expr.value)
    if isinstance(expr, BinaryExpr):
        return aggregate_functions(expr.left) | aggregate_functions(expr.right)
    if isinstance(expr, UnaryExpr):
        return aggregate_functions(expr.operand)
    if isinstance(expr, FunctionExpr):
        return set().union(*(aggregate_functions(value) for value in expr.arguments)) if expr.arguments else set()
    if isinstance(expr, TimeBucketExpr):
        return aggregate_functions(expr.value)
    if isinstance(expr, CaseExpr):
        values = aggregate_functions(expr.otherwise)
        for branch in expr.branches:
            values |= aggregate_functions(branch.then)
        return values
    return set()
