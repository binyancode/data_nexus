"""SqlResolver：连一个 SQL Server / Azure SQL 库，执行 SQL 取数。

每个 SqlResolver 持有自己独立的连接（来自各自的凭据），与系统库、其它源互不共用。
"""

from __future__ import annotations

from typing import Any, Optional

from services.sql_db import sql_db
from nexus.core.models import NodeResult, ExecContext
from nexus.core.physical import QueryIR
from nexus.resolvers.base import Resolver
from nexus.resolvers.sql_server_query_renderer import SqlServerQueryRenderer


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
    """SQL Server 取数源。

    其它数据库即使大体兼容 SQL，也必须提供自己的 Resolver 和 QueryRenderer
    实现，不能通过覆盖单个 LIMIT 片段假定方言兼容。
    """

    resolver_type = "sql"
    provides_concepts = True
    operators = {"SELECT", "AGGREGATE"}

    placeholder = "?"          # 参数占位符（pyodbc = ?）

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        # config 即一份 sql 连接（server/database/username/password/...），来自 sql_credential.to_config()
        self._db = sql_db(self.config)

    @property
    def _source(self) -> str:
        return f"{self.name}:{self.config.get('database', '')}"

    def compile(self, query: QueryIR) -> dict:
        rendered = SqlServerQueryRenderer().render(query)
        return {"sql": rendered.sql, "params": rendered.params}

    def capabilities(self) -> dict:
        base = super().capabilities()
        base["relational"] = {
            "filter": ["EQ", "NE", "GT", "GTE", "LT", "LTE", "IN", "BETWEEN", "LIKE"],
            "join": ["INNER", "LEFT"],
            "aggregates": ["SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX", "VARIANCE", "STDDEV"],
            "time_grains": ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"],
            "conditional_aggregate": True, "top_n": True,
        }
        return base

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
                """SELECT c.TABLE_SCHEMA, c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.IS_NULLABLE,
                                    CASE WHEN EXISTS (
                                            SELECT 1
                                                FROM sys.indexes i
                                                JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id
                                                JOIN sys.columns sc ON sc.object_id=ic.object_id AND sc.column_id=ic.column_id
                                                JOIN sys.tables st ON st.object_id=i.object_id
                                                JOIN sys.schemas ss ON ss.schema_id=st.schema_id
                                                WHERE i.is_unique=1 AND ss.name=c.TABLE_SCHEMA AND st.name=c.TABLE_NAME
                                                    AND sc.name=c.COLUMN_NAME
                                                         AND (SELECT COUNT(*) FROM sys.index_columns ic2
                                                                     WHERE ic2.object_id=i.object_id AND ic2.index_id=i.index_id
                                                                         AND ic2.key_ordinal > 0) = 1
                                    ) THEN 1 ELSE 0 END AS IS_UNIQUE
                            FROM INFORMATION_SCHEMA.COLUMNS c
                        ORDER BY c.TABLE_SCHEMA, c.TABLE_NAME, c.ORDINAL_POSITION"""
        )
        tables: dict[str, list] = {}
        for r in rows:
            key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}"
            tables.setdefault(key, []).append({
                "column": r["COLUMN_NAME"], "type": r["DATA_TYPE"],
                "dtype": _coarse_type(r["DATA_TYPE"]),
                "nullable": str(r.get("IS_NULLABLE") or "").upper() == "YES",
                "unique": bool(r.get("IS_UNIQUE")),
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
            """SELECT fk.name AS constraint_name,
                      sp.name AS from_sch, tp.name AS from_tbl, cp.name AS from_col,
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
        grouped: dict[tuple, dict] = {}
        for row in rows:
            key = (row["constraint_name"], row["from_sch"], row["from_tbl"], row["to_sch"], row["to_tbl"])
            item = grouped.setdefault(key, {
                "constraint_name": row["constraint_name"],
                "from_table": f"{row['from_sch']}.{row['from_tbl']}", "from_cols": [],
                "to_table": f"{row['to_sch']}.{row['to_tbl']}", "to_cols": [],
            })
            item["from_cols"].append(row["from_col"])
            item["to_cols"].append(row["to_col"])
        return list(grouped.values())

    def sample(self, target: str = None, n: int = 5) -> list[dict[str, Any]]:
        if not target:
            return []
        parts = target.split(".")
        if not 1 <= len(parts) <= 4 or any(not part.strip() for part in parts):
            raise ValueError(f"非法 SQL Server 表名：{target}")
        quoted = ".".join(f"[{part.strip().replace(']', ']]')}]" for part in parts)
        limit = max(1, min(int(n), 100))
        return self._db.execute_query(f"SELECT TOP ({limit}) * FROM {quoted}")
