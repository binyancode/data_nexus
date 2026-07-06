"""SqlResolver：连一个 SQL Server / Azure SQL 库，执行 SQL 取数。

每个 SqlResolver 持有自己独立的连接（来自各自的凭据），与系统库、其它源互不共用。
"""

from __future__ import annotations

from typing import Any, Optional

from services.sql_db import sql_db
from nexus.core.models import NodeResult, ExecContext, QuerySpec
from nexus.resolvers.base import Resolver


# 原生 DB 类型 → 粗粒度语义类型（concept 是语义层，不绑死某库的类型表）
_COARSE_TYPE = {
    "int": "number", "bigint": "number", "smallint": "number", "tinyint": "number",
    "decimal": "number", "numeric": "number", "float": "number", "real": "number",
    "money": "number", "smallmoney": "number", "bit": "bool",
    "char": "text", "varchar": "text", "nchar": "text", "nvarchar": "text",
    "text": "text", "ntext": "text",
    "date": "date", "datetime": "date", "datetime2": "date", "smalldatetime": "date",
    "datetimeoffset": "date", "time": "date",
}


def _coarse_type(raw: str) -> str:
    return _COARSE_TYPE.get((raw or "").strip().lower(), "unknown")


class SqlResolver(Resolver):
    """标准 SQL 取数源（默认 SQL Server / Azure SQL 语法）。

    任何 SQL 兼容库都可直接复用；个别语法有差异的库（如 Databricks 用 LIMIT）
    子类化本类、覆写 `_limit_clause` 一个方法即可，无需另建方言体系。
    """

    resolver_type = "sql"
    provides_concepts = True
    operators = {"SELECT", "FILTER", "AGGREGATE", "JOIN"}

    placeholder = "?"          # 参数占位符（pyodbc = ?）

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        # config 即一份 sql 连接（server/database/username/password/...），来自 sql_credential.to_config()
        self._db = sql_db(self.config)

    @property
    def _source(self) -> str:
        return f"{self.name}:{self.config.get('database', '')}"

    # ── QuerySpec → SQL 渲染（优化器只给方言中立的 spec，语法在这里落地）──
    def _limit_clause(self, spec: QuerySpec) -> tuple[str, str]:
        """TopN 语法：返回 (SELECT 前缀, 末尾后缀)。
        SQL Server 用 `SELECT TOP (n)`；用 LIMIT 的库覆写成 ('', ' LIMIT n')。"""
        if spec.limit and spec.label_expr:
            return f"TOP ({int(spec.limit)}) ", ""
        return "", ""

    def _cond(self, f, params: list) -> str:
        """一条过滤渲染成条件串（用于 WHERE 或 CASE WHEN），把值追加进 params。"""
        if f.op == "IN":
            vals = f.value if isinstance(f.value, list) else [f.value]
            params.extend(vals)
            return f"{f.col} IN ({','.join([self.placeholder] * len(vals))})"
        # 日期过滤：value_format 存在时显式转 date（ISO 值 TRY_CONVERT 可靠推断）
        rhs = f"TRY_CONVERT(date, {self.placeholder})" if f.value_format else self.placeholder
        params.append(f.value)
        return f"{f.col} {f.op} {rhs}"

    def compile(self, spec: QuerySpec) -> dict:
        """QuerySpec → {sql, params}。"""
        # FROM / JOIN
        if spec.from_alias:
            from_sql = f"{spec.from_table} {spec.from_alias}"
            for j in spec.joins:
                from_sql += f" JOIN {j.table} {j.alias} ON {j.on_left} = {j.on_right}"
        else:
            from_sql = spec.from_table

        # 多测度融合：一条查询出多列（无 TopN/HAVING，融合时已排除）
        # 参数顺序：SELECT 列表里的 CASE 参数在前，WHERE 参数在后（与 SQL 从左到右一致）
        if spec.selects:
            sel_params: list = []
            cols = []
            for s in spec.selects:
                if s.filters:               # P2 条件聚合：agg(CASE WHEN 各自过滤 THEN inner END)
                    conds = " AND ".join(self._cond(f, sel_params) for f in s.filters)
                    cols.append(f"{s.agg}(CASE WHEN {conds} THEN {s.inner} END) AS {s.alias}")
                else:                       # P1 多测度：直接聚合表达式
                    cols.append(f"{s.expr} AS {s.alias}")
            where_params: list = []
            where = [self._cond(f, where_params) for f in spec.filters]
            head = (f"{spec.label_expr} AS label, " if spec.label_expr else "") + ", ".join(cols)
            sql = f"SELECT {head} FROM {from_sql}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            if spec.label_expr:
                sql += f" GROUP BY {spec.label_expr}"
            return {"sql": sql, "params": sel_params + where_params}

        # 单测度路径
        params: list = []
        where = [self._cond(f, params) for f in spec.filters]
        top, tail = self._limit_clause(spec)

        if spec.label_expr:
            sql = f"SELECT {top}{spec.label_expr} AS label, {spec.value_expr} AS value FROM {from_sql}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            sql += f" GROUP BY {spec.label_expr}"
            if spec.having:
                sql += f" HAVING {spec.value_expr} {spec.having.op} {self.placeholder}"
                params.append(spec.having.value)
            sql += f" ORDER BY value {spec.order}"
            sql += tail
        else:
            sql = f"SELECT {spec.value_expr} AS value FROM {from_sql}"
            if where:
                sql += " WHERE " + " AND ".join(where)
            if spec.having:
                sql += f" HAVING {spec.value_expr} {spec.having.op} {self.placeholder}"
                params.append(spec.having.value)

        return {"sql": sql, "params": params}

    def fetch(self, call: dict, ctx: Optional[ExecContext] = None) -> NodeResult:
        node_id = call.get("node_id", "")
        sql = call.get("sql", "")
        params = call.get("params")
        params = tuple(params) if params else None
        try:
            rows = self._db.execute_query(sql, params)
            columns = list(rows[0].keys()) if rows else []
            return NodeResult(
                node_id=node_id,
                resolver=self.name,
                output=rows,
                columns=columns,
                rows=rows,
                source=self._source,
                detail=sql,
            )
        except Exception as exc:
            return NodeResult(
                node_id=node_id,
                resolver=self.name,
                error=str(exc),
                source=self._source,
                detail=sql,
            )

    def describe(self) -> dict:
        """探测：返回 {schema.table: [{column, type, dtype}]}。dtype 为粗粒度语义类型。"""
        rows = self._db.execute_query(
            """SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
               FROM INFORMATION_SCHEMA.COLUMNS
               ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"""
        )
        tables: dict[str, list] = {}
        for r in rows:
            key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}"
            tables.setdefault(key, []).append({
                "column": r["COLUMN_NAME"], "type": r["DATA_TYPE"],
                "dtype": _coarse_type(r["DATA_TYPE"]),
            })
        return tables

    def primary_keys(self) -> dict:
        """返回 {schema.table: [pk 列...]}。"""
        rows = self._db.execute_query(
            """SELECT s.name AS sch, t.name AS tbl, c.name AS col
                 FROM sys.indexes i
                 JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                 JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id
                 JOIN sys.tables t ON t.object_id=i.object_id
                 JOIN sys.schemas s ON s.schema_id=t.schema_id
                WHERE i.is_primary_key=1
                ORDER BY ic.key_ordinal"""
        )
        pks: dict[str, list] = {}
        for r in rows:
            pks.setdefault(f"{r['sch']}.{r['tbl']}", []).append(r["col"])
        return pks

    def foreign_keys(self) -> list:
        """返回外键 [{from_table, from_col, to_table, to_col}]（table 为 schema.table）。"""
        rows = self._db.execute_query(
            """SELECT sp.name AS from_sch, tp.name AS from_tbl, cp.name AS from_col,
                      sr.name AS to_sch,  tr.name AS to_tbl,  cr.name AS to_col
                 FROM sys.foreign_keys fk
                 JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id=fk.object_id
                 JOIN sys.tables tp ON tp.object_id=fk.parent_object_id
                 JOIN sys.schemas sp ON sp.schema_id=tp.schema_id
                 JOIN sys.columns cp ON cp.object_id=tp.object_id AND cp.column_id=fkc.parent_column_id
                 JOIN sys.tables tr ON tr.object_id=fk.referenced_object_id
                 JOIN sys.schemas sr ON sr.schema_id=tr.schema_id
                 JOIN sys.columns cr ON cr.object_id=tr.object_id AND cr.column_id=fkc.referenced_column_id"""
        )
        return [
            {"from_table": f"{r['from_sch']}.{r['from_tbl']}", "from_col": r["from_col"],
             "to_table": f"{r['to_sch']}.{r['to_tbl']}", "to_col": r["to_col"]}
            for r in rows
        ]

    def sample(self, target: str = None, n: int = 5) -> list[dict[str, Any]]:
        if not target:
            return []
        return self._db.execute_query(f"SELECT TOP {int(n)} * FROM {target}")
