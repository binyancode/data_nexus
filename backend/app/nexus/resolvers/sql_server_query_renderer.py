"""SQL Server-native renderer for the dialect-neutral physical ``QueryIR``.

The implementation owns the complete T-SQL statement shape.  It does not
subclass the DuckDB renderer, so T-SQL-specific choices (``TOP``, CASE-based
filtered aggregates, date bucketing, integer-safe division and NULL ordering)
can be optimized independently.
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


class SqlServerQueryRenderer(QueryRenderer):
    """Render ``QueryIR`` as SQL Server T-SQL."""

    dialect = "sql_server"

    def __init__(self, table_source: TableSource | None = None):
        self._table_source = table_source or self._default_table_source
        self._params: list[Any] = []

    @staticmethod
    def _quote(name: str) -> str:
        return f"[{name.replace(']', ']]')}]"

    def _default_table_source(self, name: str) -> str:
        # QuerySource object names are identifiers, not arbitrary SQL.  A custom
        # table_source callback is the explicit escape hatch for #temp mappings.
        return ".".join(self._quote(part) for part in name.split("."))

    def _table(self, name: str) -> str:
        return self._table_source(name)

    def _literal(self, value: Any) -> str:
        self._params.append(value)
        return "?"

    def _column(self, source: str, name: str) -> str:
        return f"{self._quote(source)}.{self._quote(name)}"

    @staticmethod
    def _time_bucket(value: str, grain: str) -> str:
        if grain == "DAY":
            return f"CAST({value} AS date)"
        if grain == "WEEK":
            # 1900-01-01 is a Monday.  Normalize modulo so pre-1900 dates also
            # map to a Monday and match DuckDB's semantic week boundary.
            offset = f"DATEDIFF(day, DATEFROMPARTS(1900, 1, 1), CAST({value} AS date))"
            return (
                f"DATEADD(day, -((({offset}) % 7 + 7) % 7), "
                f"CAST({value} AS date))"
            )
        if grain == "MONTH":
            return f"DATEFROMPARTS(YEAR({value}), MONTH({value}), 1)"
        if grain == "QUARTER":
            return (
                f"DATEFROMPARTS(YEAR({value}), "
                f"((DATEPART(quarter, {value}) - 1) * 3) + 1, 1)"
            )
        if grain == "YEAR":
            return f"DATEFROMPARTS(YEAR({value}), 1, 1)"
        raise ValueError(f"unsupported SQL Server time grain: {grain}")

    @staticmethod
    def _safe_divide(left: str, right: str, zero_policy: str) -> str:
        # 1.0 prevents T-SQL integer division when both inputs are integral.
        numerator = f"(1.0 * ({left}))"
        if zero_policy == "ZERO":
            return f"COALESCE({numerator} / NULLIF(({right}), 0), 0)"
        if zero_policy == "ERROR":
            return f"{numerator} / ({right})"
        return f"{numerator} / NULLIF(({right}), 0)"

    def _aggregate(self, aggregate: AggregateExpr) -> str:
        function = aggregate.function
        if function in {AggregateFunction.MEDIAN, AggregateFunction.PERCENTILE}:
            raise ValueError(
                f"{function.value} must be rendered through the SQL Server window path"
            )

        # CASE places the predicate before the value in T-SQL; render in that
        # same order so positional pyodbc parameters remain correctly ordered.
        predicate_sql = (
            self._predicate(aggregate.filter) if aggregate.filter is not None else None
        )
        value = self._expression(aggregate.value) if aggregate.value is not None else "*"
        if predicate_sql is not None:
            value = f"CASE WHEN {predicate_sql} THEN {1 if value == '*' else value} END"

        if function == AggregateFunction.COUNT_DISTINCT:
            if value == "*":
                raise ValueError("SQL Server COUNT_DISTINCT requires a value expression")
            return f"COUNT(DISTINCT {value})"

        names = {
            AggregateFunction.VARIANCE: "VAR",
            AggregateFunction.STDDEV: "STDEV",
        }
        distinct = "DISTINCT " if aggregate.distinct and value != "*" else ""
        return f"{names.get(function, function.value)}({distinct}{value})"

    @staticmethod
    def _uses_ordered_percentile(query: QueryIR) -> bool:
        return any(
            {AggregateFunction.MEDIAN.value, AggregateFunction.PERCENTILE.value}
            & aggregate_functions(output.aggregate)
            for output in query.outputs
        )

    def _window_aggregate(self, aggregate: AggregateExpr,
                          dimensions) -> str:
        function = aggregate.function

        if function in {AggregateFunction.MEDIAN, AggregateFunction.PERCENTILE}:
            percentile = 0.5 if function == AggregateFunction.MEDIAN \
                else (aggregate.percentile if aggregate.percentile is not None else 0.5)
            percentile_sql = self._literal(percentile)
            predicate_sql = (
                self._predicate(aggregate.filter) if aggregate.filter is not None else None
            )
            value = self._expression(aggregate.value)
            if predicate_sql is not None:
                value = f"CASE WHEN {predicate_sql} THEN {value} END"
            ordered_set = "PERCENTILE_CONT" if aggregate.method == "CONTINUOUS" \
                else "PERCENTILE_DISC"
            partition = ", ".join(
                self._expression(output.expression) for output in dimensions
            )
            over = f"PARTITION BY {partition}" if partition else ""
            return (
                f"{ordered_set}({percentile_sql}) WITHIN GROUP (ORDER BY {value}) "
                f"OVER ({over})"
            )

        if function == AggregateFunction.COUNT_DISTINCT or aggregate.distinct:
            raise ValueError(
                "SQL Server cannot combine DISTINCT window aggregates with MEDIAN/PERCENTILE"
            )

        predicate_sql = (
            self._predicate(aggregate.filter) if aggregate.filter is not None else None
        )
        value = self._expression(aggregate.value) if aggregate.value is not None else "*"
        if predicate_sql is not None:
            value = f"CASE WHEN {predicate_sql} THEN {1 if value == '*' else value} END"
        names = {
            AggregateFunction.VARIANCE: "VAR",
            AggregateFunction.STDDEV: "STDEV",
        }
        partition = ", ".join(
            self._expression(output.expression) for output in dimensions
        )
        over = f"PARTITION BY {partition}" if partition else ""
        return f"{names.get(function, function.value)}({value}) OVER ({over})"

    def _window_expression(self, expression, dimensions) -> str:
        if isinstance(expression, AggregateExpr):
            return self._window_aggregate(expression, dimensions)
        if isinstance(expression, BinaryExpr):
            left = self._window_expression(expression.left, dimensions)
            right = self._window_expression(expression.right, dimensions)
            if expression.operator == "SAFE_DIVIDE":
                return self._safe_divide(left, right, expression.zero_division)
            if expression.operator == "DIVIDE":
                return f"(1.0 * ({left})) / ({right})"
            operator = {
                "ADD": "+", "SUBTRACT": "-", "MULTIPLY": "*",
            }[expression.operator]
            return f"({left}) {operator} ({right})"
        if isinstance(expression, UnaryExpr):
            return f"-({self._window_expression(expression.operand, dimensions)})"
        if isinstance(expression, FunctionExpr):
            arguments = ", ".join(
                self._window_expression(value, dimensions)
                for value in expression.arguments
            )
            return f"{expression.name}({arguments})"
        if isinstance(expression, CaseExpr):
            branches = " ".join(
                f"WHEN {self._predicate(branch.when)} THEN "
                f"{self._window_expression(branch.then, dimensions)}"
                for branch in expression.branches
            )
            otherwise = (
                f" ELSE {self._window_expression(expression.otherwise, dimensions)}"
                if expression.otherwise is not None else ""
            )
            return f"CASE {branches}{otherwise} END"
        return self._expression(expression)

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
            raise ValueError(
                f"unbound attribute in SQL Server physical query: {expression.concept}"
            )
        if isinstance(expression, BinaryExpr):
            left = self._expression(expression.left)
            right = self._expression(expression.right)
            if expression.operator == "SAFE_DIVIDE":
                return self._safe_divide(left, right, expression.zero_division)
            if expression.operator == "DIVIDE":
                return f"(1.0 * ({left})) / ({right})"
            operator = {
                "ADD": "+", "SUBTRACT": "-", "MULTIPLY": "*",
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
        raise TypeError(f"unsupported SQL Server expression: {type(expression).__name__}")

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
            raise ValueError("time_range must be bound to a column before SQL Server rendering")
        if isinstance(predicate, AndPredicate):
            return "(" + " AND ".join(self._predicate(value) for value in predicate.operands) + ")"
        if isinstance(predicate, OrPredicate):
            return "(" + " OR ".join(self._predicate(value) for value in predicate.operands) + ")"
        if isinstance(predicate, NotPredicate):
            return f"NOT ({self._predicate(predicate.operand)})"
        raise TypeError(f"unsupported SQL Server predicate: {type(predicate).__name__}")

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

    def _render_base_select(self, query: QueryIR) -> str:
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
        return sql

    def _render_window_select(self, query: QueryIR) -> str:
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

        columns = [
            f"{self._expression(output.expression)} AS {self._quote(output.name)}"
            for output in query.dimensions
        ]
        for output in query.outputs:
            if output.aggregate is None or not aggregate_functions(output.aggregate):
                raise ValueError(
                    "SQL Server MEDIAN/PERCENTILE query requires aggregate outputs"
                )
            columns.append(
                f"{self._window_expression(output.aggregate, query.dimensions)} "
                f"AS {self._quote(output.name)}"
            )

        sql = f"SELECT DISTINCT {', '.join(columns)} FROM {from_sql}"
        if query.predicate is not None:
            sql += " WHERE " + self._predicate(query.predicate)
        if query.result_predicate is not None:
            predicate = self._result_predicate(query.result_predicate)
            sql = (
                f"SELECT * FROM ({sql}) {self._quote('_result')} "
                f"WHERE {self._predicate(predicate)}"
            )
        return sql

    @staticmethod
    def _apply_top(sql: str, limit: int | None) -> str:
        if not limit:
            return sql
        return sql.replace("SELECT ", f"SELECT TOP ({int(limit)}) ", 1)

    def render(self, query: QueryIR) -> RenderedQuery:
        self._params = []
        sql = self._render_window_select(query) \
            if self._uses_ordered_percentile(query) else self._render_base_select(query)
        if not query.order_by:
            return RenderedQuery(
                sql=self._apply_top(sql, query.limit),
                params=list(self._params),
            )

        # T-SQL has no NULLS FIRST/LAST and an output alias cannot be embedded
        # in a CASE expression in the same SELECT.  Order an outer projection;
        # SQL Server can still push TOP and predicates into the derived table.
        alias = "_ordered"
        clauses = []
        for key in query.order_by:
            column = self._column(alias, key.field)
            null_value = 0 if key.nulls == "FIRST" else 1
            nonnull_value = 1 - null_value
            clauses.append(
                f"CASE WHEN {column} IS NULL THEN {null_value} "
                f"ELSE {nonnull_value} END ASC"
            )
            clauses.append(f"{column} {key.direction}")
        top = f"TOP ({int(query.limit)}) " if query.limit else ""
        sql = (
            f"SELECT {top}* FROM ({sql}) {self._quote(alias)} "
            f"ORDER BY {', '.join(clauses)}"
        )
        return RenderedQuery(sql=sql, params=list(self._params))
