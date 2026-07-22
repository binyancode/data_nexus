"""DuckDB-native renderer for the dialect-neutral physical ``QueryIR``.

This renderer owns the complete DuckDB SQL shape.  It intentionally does not
inherit SQL generation from another dialect: DuckDB-specific syntax and
optimizations (``FILTER``, ``quantile_*``, ``LIMIT``, explicit NULL ordering)
can evolve without constraining SQL Server.
"""

from __future__ import annotations

from typing import Any

from nexus.core.expressions import (
    AggregateExpr,
    AggregateFunction,
    AndPredicate,
    AttributeExpr,
    BetweenPredicate,
    BinaryExpr,
    CaseExpr,
    ColumnExpr,
    ComparisonPredicate,
    FunctionExpr,
    InPredicate,
    LiteralExpr,
    NotPredicate,
    NullPredicate,
    OrPredicate,
    OutputExpr,
    Predicate,
    TimeBucketExpr,
    TimeRangePredicate,
    TruePredicate,
    UnaryExpr,
    aggregate_functions,
)
from nexus.core.physical import QueryIR
from nexus.resolvers.query_renderer import QueryRenderer, RenderedQuery, TableSource


class DuckDbQueryRenderer(QueryRenderer):
    """Render ``QueryIR`` as DuckDB SQL."""

    dialect = "duckdb"

    def __init__(self, table_source: TableSource | None = None):
        self._table_source = table_source or (lambda value: value)
        self._params: list[Any] = []

    @staticmethod
    def _quote(name: str) -> str:
        return f'"{name.replace(chr(34), chr(34) * 2)}"'

    def _table(self, name: str) -> str:
        return self._table_source(name)

    def _literal(self, value: Any) -> str:
        self._params.append(value)
        return "?"

    def _column(self, source: str, name: str) -> str:
        return f"{self._quote(source)}.{self._quote(name)}"

    @staticmethod
    def _time_bucket(value: str, grain: str) -> str:
        return f"date_trunc('{grain.lower()}', {value})"

    @staticmethod
    def _safe_divide(left: str, right: str, zero_policy: str) -> str:
        if zero_policy == "ZERO":
            return f"COALESCE(({left}) / NULLIF(({right}), 0), 0)"
        if zero_policy == "ERROR":
            return f"({left}) / ({right})"
        return f"({left}) / NULLIF(({right}), 0)"

    def _aggregate(self, aggregate: AggregateExpr) -> str:
        function = aggregate.function
        value = self._expression(aggregate.value) if aggregate.value is not None else "*"

        if function == AggregateFunction.COUNT_DISTINCT:
            sql = f"COUNT(DISTINCT {value})"
        elif function == AggregateFunction.MEDIAN:
            sql = self._percentile(value, 0.5, aggregate.method)
        elif function == AggregateFunction.PERCENTILE:
            sql = self._percentile(value, aggregate.percentile or 0.5, aggregate.method)
        else:
            names = {
                AggregateFunction.VARIANCE: "VAR_SAMP",
                AggregateFunction.STDDEV: "STDDEV_SAMP",
            }
            distinct = "DISTINCT " if aggregate.distinct and value != "*" else ""
            sql = f"{names.get(function, function.value)}({distinct}{value})"

        # DuckDB has native filtered aggregates.  This preserves COUNT(*) and
        # allows the engine to optimize the predicate without a CASE payload.
        if aggregate.filter is not None:
            sql += f" FILTER (WHERE {self._predicate(aggregate.filter)})"
        return sql

    def _percentile(self, value: str, percentile: float, method: str) -> str:
        function = "quantile_cont" if method == "CONTINUOUS" else "quantile_disc"
        return f"{function}({value}, {self._literal(percentile)})"

    def _expression(self, expression) -> str:
        if expression is None:
            return "NULL"
        if isinstance(expression, ColumnExpr):
            return self._column(expression.source, expression.name)
        if isinstance(expression, LiteralExpr):
            return self._literal(expression.value)
        if isinstance(expression, OutputExpr):
            return self._quote(expression.name)
        if isinstance(expression, AttributeExpr):
            raise ValueError(f"unbound attribute in DuckDB physical query: {expression.concept}")
        if isinstance(expression, BinaryExpr):
            left = self._expression(expression.left)
            right = self._expression(expression.right)
            if expression.operator == "SAFE_DIVIDE":
                return self._safe_divide(left, right, expression.zero_division)
            operator = {
                "ADD": "+", "SUBTRACT": "-", "MULTIPLY": "*", "DIVIDE": "/",
            }[expression.operator]
            return f"({left}) {operator} ({right})"
        if isinstance(expression, UnaryExpr):
            return f"-({self._expression(expression.operand)})"
        if isinstance(expression, FunctionExpr):
            arguments = ", ".join(self._expression(value) for value in expression.arguments)
            return f"{expression.name}({arguments})"
        if isinstance(expression, TimeBucketExpr):
            return self._time_bucket(self._expression(expression.value), expression.grain)
        if isinstance(expression, AggregateExpr):
            return self._aggregate(expression)
        if isinstance(expression, CaseExpr):
            branches = " ".join(
                f"WHEN {self._predicate(branch.when)} THEN {self._expression(branch.then)}"
                for branch in expression.branches
            )
            otherwise = (
                f" ELSE {self._expression(expression.otherwise)}"
                if expression.otherwise is not None else ""
            )
            return f"CASE {branches}{otherwise} END"
        raise TypeError(f"unsupported DuckDB expression: {type(expression).__name__}")

    def _predicate(self, predicate: Predicate | None) -> str:
        if predicate is None or isinstance(predicate, TruePredicate):
            return "1=1"
        if isinstance(predicate, ComparisonPredicate):
            operator = {
                "EQ": "=", "NE": "<>", "GT": ">", "GTE": ">=",
                "LT": "<", "LTE": "<=", "LIKE": "LIKE",
            }[predicate.operator]
            return (
                f"{self._expression(predicate.left)} {operator} "
                f"{self._expression(predicate.right)}"
            )
        if isinstance(predicate, InPredicate):
            values = ", ".join(self._expression(value) for value in predicate.values)
            return f"{self._expression(predicate.value)} IN ({values})"
        if isinstance(predicate, BetweenPredicate):
            value = self._expression(predicate.value)
            lower_operator = ">=" if predicate.lower_inclusive else ">"
            upper_operator = "<=" if predicate.upper_inclusive else "<"
            return (
                f"({value} {lower_operator} {self._expression(predicate.lower)} AND "
                f"{value} {upper_operator} {self._expression(predicate.upper)})"
            )
        if isinstance(predicate, NullPredicate):
            return (
                f"{self._expression(predicate.value)} IS "
                f"{'NULL' if predicate.is_null else 'NOT NULL'}"
            )
        if isinstance(predicate, TimeRangePredicate):
            raise ValueError("time_range must be bound to a column before DuckDB rendering")
        if isinstance(predicate, AndPredicate):
            return "(" + " AND ".join(self._predicate(value) for value in predicate.operands) + ")"
        if isinstance(predicate, OrPredicate):
            return "(" + " OR ".join(self._predicate(value) for value in predicate.operands) + ")"
        if isinstance(predicate, NotPredicate):
            return f"NOT ({self._predicate(predicate.operand)})"
        raise TypeError(f"unsupported DuckDB predicate: {type(predicate).__name__}")

    @staticmethod
    def _result_expression(expression):
        if isinstance(expression, OutputExpr):
            return ColumnExpr(source="_result", name=expression.name)
        return expression

    def _result_predicate(self, predicate):
        if isinstance(predicate, ComparisonPredicate):
            return predicate.model_copy(update={
                "left": self._result_expression(predicate.left),
                "right": self._result_expression(predicate.right),
            })
        if isinstance(predicate, InPredicate):
            return predicate.model_copy(update={
                "value": self._result_expression(predicate.value),
                "values": [self._result_expression(value) for value in predicate.values],
            })
        if isinstance(predicate, BetweenPredicate):
            return predicate.model_copy(update={
                "value": self._result_expression(predicate.value),
                "lower": self._result_expression(predicate.lower),
                "upper": self._result_expression(predicate.upper),
            })
        if isinstance(predicate, NullPredicate):
            return predicate.model_copy(update={
                "value": self._result_expression(predicate.value),
            })
        if isinstance(predicate, AndPredicate):
            return predicate.model_copy(update={
                "operands": [self._result_predicate(value) for value in predicate.operands],
            })
        if isinstance(predicate, OrPredicate):
            return predicate.model_copy(update={
                "operands": [self._result_predicate(value) for value in predicate.operands],
            })
        if isinstance(predicate, NotPredicate):
            return predicate.model_copy(update={
                "operand": self._result_predicate(predicate.operand),
            })
        return predicate

    def render(self, query: QueryIR) -> RenderedQuery:
        self._params = []
        source = query.source
        from_sql = f"{self._table(source.object_name)} {self._quote(source.alias)}"
        for join in query.joins:
            target = join.source
            conditions = " AND ".join(
                f"{self._expression(left)} = {self._expression(right)}"
                for left, right in zip(join.left, join.right)
            )
            from_sql += (
                f" {join.join_type} JOIN {self._table(target.object_name)} "
                f"{self._quote(target.alias)} ON {conditions}"
            )

        columns = []
        for output in [*query.dimensions, *query.outputs]:
            value = (
                self._expression(output.aggregate)
                if output.aggregate is not None
                else self._expression(output.expression)
            )
            columns.append(f"{value} AS {self._quote(output.name)}")
        if not columns:
            columns = ["*"]

        distinct = "DISTINCT " if query.distinct else ""
        sql = f"SELECT {distinct}{', '.join(columns)} FROM {from_sql}"
        if query.predicate is not None:
            sql += " WHERE " + self._predicate(query.predicate)
        if query.dimensions and any(
            aggregate_functions(output.aggregate) for output in query.outputs
        ):
            sql += " GROUP BY " + ", ".join(
                self._expression(output.expression) for output in query.dimensions
            )
        if query.result_predicate is not None:
            predicate = self._result_predicate(query.result_predicate)
            sql = (
                f"SELECT * FROM ({sql}) {self._quote('_result')} "
                f"WHERE {self._predicate(predicate)}"
            )
        if query.order_by:
            sql += " ORDER BY " + ", ".join(
                f"{self._quote(key.field)} {key.direction} NULLS {key.nulls}"
                for key in query.order_by
            )
        if query.limit:
            sql += f" LIMIT {int(query.limit)}"
        return RenderedQuery(sql=sql, params=list(self._params))
