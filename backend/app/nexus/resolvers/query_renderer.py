"""Dialect renderers for typed physical QueryIR.

The optimizer owns semantic binding; renderers own quoting, parameters and
function syntax.  No renderer parses logical concept ids or SQL-like strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from nexus.core.expressions import (
    AggregateExpr, AggregateFunction, AndPredicate, AttributeExpr, BetweenPredicate,
    BinaryExpr, CaseExpr, ColumnExpr, ComparisonPredicate, FunctionExpr, InPredicate,
    LiteralExpr, NotPredicate, NullPredicate, OrPredicate, OutputExpr, Predicate,
    TimeBucketExpr, TimeRangePredicate, TruePredicate, UnaryExpr, aggregate_functions,
)
from nexus.core.physical import QueryIR


@dataclass
class RenderedQuery:
    sql: str
    params: list


class QueryRenderer:
    def __init__(self, table_source: Callable[[str], str] | None = None):
        self._table_source = table_source or (lambda value: value)
        self.params: list = []

    def quote(self, name: str) -> str:
        return f'"{name.replace(chr(34), chr(34) * 2)}"'

    def table(self, name: str) -> str:
        return self._table_source(name)

    def placeholder(self) -> str:
        return "?"

    def literal(self, value) -> str:
        self.params.append(value)
        return self.placeholder()

    def column(self, source: str, name: str) -> str:
        return f"{self.quote(source)}.{self.quote(name)}"

    def time_bucket(self, value: str, grain: str) -> str:
        return f"date_trunc('{grain.lower()}', {value})"

    def safe_divide(self, left: str, right: str, zero_policy: str) -> str:
        if zero_policy == "ZERO":
            return f"COALESCE(({left}) / NULLIF(({right}), 0), 0)"
        if zero_policy == "ERROR":
            return f"({left}) / ({right})"
        return f"({left}) / NULLIF(({right}), 0)"

    def aggregate(self, aggregate: AggregateExpr) -> str:
        function = aggregate.function
        value = self.expression(aggregate.value) if aggregate.value is not None else "*"
        if aggregate.filter is not None:
            value = f"CASE WHEN {self.predicate(aggregate.filter)} THEN {value} END"
        if function == AggregateFunction.COUNT_DISTINCT or aggregate.distinct:
            return f"COUNT(DISTINCT {value})"
        if function == AggregateFunction.MEDIAN:
            return self.percentile(value, 0.5, aggregate.method)
        if function == AggregateFunction.PERCENTILE:
            return self.percentile(value, aggregate.percentile or 0.5, aggregate.method)
        names = {
            AggregateFunction.VARIANCE: "VAR_SAMP",
            AggregateFunction.STDDEV: "STDDEV_SAMP",
        }
        return f"{names.get(function, function.value)}({value})"

    def percentile(self, value: str, percentile: float, method: str) -> str:
        function = "quantile_cont" if method == "CONTINUOUS" else "quantile_disc"
        return f"{function}({value}, {self.literal(percentile)})"

    def expression(self, expr) -> str:
        if expr is None:
            return "NULL"
        if isinstance(expr, ColumnExpr):
            return self.column(expr.source, expr.name)
        if isinstance(expr, LiteralExpr):
            return self.literal(expr.value)
        if isinstance(expr, OutputExpr):
            return self.quote(expr.name)
        if isinstance(expr, AttributeExpr):
            raise ValueError(f"unbound attribute in physical query: {expr.concept}")
        if isinstance(expr, BinaryExpr):
            left, right = self.expression(expr.left), self.expression(expr.right)
            if expr.operator == "SAFE_DIVIDE":
                return self.safe_divide(left, right, expr.zero_division)
            op = {"ADD": "+", "SUBTRACT": "-", "MULTIPLY": "*", "DIVIDE": "/"}[expr.operator]
            return f"({left}) {op} ({right})"
        if isinstance(expr, UnaryExpr):
            return f"-({self.expression(expr.operand)})"
        if isinstance(expr, FunctionExpr):
            args = ", ".join(self.expression(value) for value in expr.arguments)
            return f"{expr.name}({args})"
        if isinstance(expr, TimeBucketExpr):
            return self.time_bucket(self.expression(expr.value), expr.grain)
        if isinstance(expr, AggregateExpr):
            return self.aggregate(expr)
        if isinstance(expr, CaseExpr):
            branches = " ".join(
                f"WHEN {self.predicate(branch.when)} THEN {self.expression(branch.then)}"
                for branch in expr.branches
            )
            otherwise = f" ELSE {self.expression(expr.otherwise)}" if expr.otherwise is not None else ""
            return f"CASE {branches}{otherwise} END"
        raise TypeError(f"unsupported expression: {type(expr).__name__}")

    def predicate(self, predicate: Predicate | None) -> str:
        if predicate is None or isinstance(predicate, TruePredicate):
            return "1=1"
        if isinstance(predicate, ComparisonPredicate):
            operator = {"EQ": "=", "NE": "<>", "GT": ">", "GTE": ">=", "LT": "<", "LTE": "<=", "LIKE": "LIKE"}[predicate.operator]
            return f"{self.expression(predicate.left)} {operator} {self.expression(predicate.right)}"
        if isinstance(predicate, InPredicate):
            values = ", ".join(self.expression(value) for value in predicate.values)
            return f"{self.expression(predicate.value)} IN ({values})"
        if isinstance(predicate, BetweenPredicate):
            value = self.expression(predicate.value)
            lower_op = ">=" if predicate.lower_inclusive else ">"
            upper_op = "<=" if predicate.upper_inclusive else "<"
            return f"({value} {lower_op} {self.expression(predicate.lower)} AND {value} {upper_op} {self.expression(predicate.upper)})"
        if isinstance(predicate, NullPredicate):
            return f"{self.expression(predicate.value)} IS {'NULL' if predicate.is_null else 'NOT NULL'}"
        if isinstance(predicate, TimeRangePredicate):
            raise ValueError("time_range must be bound to a column before rendering")
        if isinstance(predicate, AndPredicate):
            return "(" + " AND ".join(self.predicate(value) for value in predicate.operands) + ")"
        if isinstance(predicate, OrPredicate):
            return "(" + " OR ".join(self.predicate(value) for value in predicate.operands) + ")"
        if isinstance(predicate, NotPredicate):
            return f"NOT ({self.predicate(predicate.operand)})"
        raise TypeError(f"unsupported predicate: {type(predicate).__name__}")

    def render(self, query: QueryIR) -> RenderedQuery:
        self.params = []
        source = query.source
        from_sql = f"{self.table(source.object_name)} {self.quote(source.alias)}"
        for join in query.joins:
            target = join.source
            conditions = " AND ".join(
                f"{self.expression(left)} = {self.expression(right)}"
                for left, right in zip(join.left, join.right)
            )
            from_sql += f" {join.join_type} JOIN {self.table(target.object_name)} {self.quote(target.alias)} ON {conditions}"

        columns = []
        for output in [*query.dimensions, *query.outputs]:
            value = self.expression(output.aggregate) if output.aggregate is not None else self.expression(output.expression)
            columns.append(f"{value} AS {self.quote(output.name)}")
        if not columns:
            columns = ["*"]
        distinct = "DISTINCT " if query.distinct else ""
        sql = f"SELECT {distinct}{', '.join(columns)} FROM {from_sql}"
        if query.predicate is not None:
            sql += " WHERE " + self.predicate(query.predicate)
        if query.dimensions and any(aggregate_functions(output.aggregate) for output in query.outputs):
            sql += " GROUP BY " + ", ".join(self.expression(output.expression) for output in query.dimensions)
        if query.result_predicate is not None:
            result_predicate = self._result_predicate(query.result_predicate)
            sql = f"SELECT * FROM ({sql}) {self.quote('_result')} WHERE {self.predicate(result_predicate)}"
        if query.order_by:
            sql += " ORDER BY " + ", ".join(
                f"{self.quote(key.field)} {key.direction} NULLS {key.nulls}" for key in query.order_by
            )
        sql = self.apply_limit(sql, query.limit)
        return RenderedQuery(sql=sql, params=list(self.params))

    def _result_predicate(self, predicate):
        def expression(value):
            if isinstance(value, OutputExpr):
                return ColumnExpr(source="_result", name=value.name)
            return value
        if isinstance(predicate, ComparisonPredicate):
            return predicate.model_copy(update={"left": expression(predicate.left),
                                                "right": expression(predicate.right)})
        if isinstance(predicate, AndPredicate):
            return predicate.model_copy(update={"operands": [self._result_predicate(v) for v in predicate.operands]})
        if isinstance(predicate, OrPredicate):
            return predicate.model_copy(update={"operands": [self._result_predicate(v) for v in predicate.operands]})
        if isinstance(predicate, NotPredicate):
            return predicate.model_copy(update={"operand": self._result_predicate(predicate.operand)})
        return predicate

    def apply_limit(self, sql: str, limit: int | None) -> str:
        return sql + (f" LIMIT {int(limit)}" if limit else "")


class SqlServerRenderer(QueryRenderer):
    def quote(self, name: str) -> str:
        return f"[{name.replace(']', ']]')}]"

    def time_bucket(self, value: str, grain: str) -> str:
        if grain == "DAY":
            return f"CAST({value} AS date)"
        if grain == "WEEK":
            return f"DATEADD(week, DATEDIFF(week, 0, {value}), 0)"
        if grain == "MONTH":
            return f"DATEFROMPARTS(YEAR({value}), MONTH({value}), 1)"
        if grain == "QUARTER":
            return f"DATEFROMPARTS(YEAR({value}), ((DATEPART(quarter, {value}) - 1) * 3) + 1, 1)"
        return f"DATEFROMPARTS(YEAR({value}), 1, 1)"

    def percentile(self, value: str, percentile: float, method: str) -> str:
        function = "PERCENTILE_CONT" if method == "CONTINUOUS" else "PERCENTILE_DISC"
        return f"{function}({self.literal(percentile)}) WITHIN GROUP (ORDER BY {value})"

    def apply_limit(self, sql: str, limit: int | None) -> str:
        if not limit:
            return sql
        marker = "SELECT "
        return sql.replace(marker, f"SELECT TOP ({int(limit)}) ", 1)

    def render(self, query: QueryIR) -> RenderedQuery:
        rendered = super().render(query)
        rendered.sql = rendered.sql.replace(" NULLS LAST", "").replace(" NULLS FIRST", "")
        return rendered
