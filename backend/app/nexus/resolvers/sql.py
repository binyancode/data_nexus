"""SqlResolver：连一个 SQL Server / Azure SQL 库，执行 SQL 取数。

每个 SqlResolver 持有自己独立的连接（来自各自的凭据），与系统库、其它源互不共用。
"""

from __future__ import annotations

from typing import Any, Optional

from services.sql_db import sql_db
from nexus.core.models import NodeResult, ExecContext
from nexus.resolvers.base import Resolver


class SqlResolver(Resolver):
    resolver_type = "sql"

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        # config 即一份 sql 连接（server/database/username/password/...），来自 sql_credential.to_config()
        self._db = sql_db(self.config)

    @property
    def _source(self) -> str:
        return f"{self.name}:{self.config.get('database', '')}"

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
        """探测：返回 {schema.table: [{column, type}]}。"""
        rows = self._db.execute_query(
            """SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
               FROM INFORMATION_SCHEMA.COLUMNS
               ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"""
        )
        tables: dict[str, list] = {}
        for r in rows:
            key = f"{r['TABLE_SCHEMA']}.{r['TABLE_NAME']}"
            tables.setdefault(key, []).append({"column": r["COLUMN_NAME"], "type": r["DATA_TYPE"]})
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
