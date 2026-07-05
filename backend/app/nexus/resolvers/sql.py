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

    def sample(self, target: str = None, n: int = 5) -> list[dict[str, Any]]:
        if not target:
            return []
        return self._db.execute_query(f"SELECT TOP {int(n)} * FROM {target}")
