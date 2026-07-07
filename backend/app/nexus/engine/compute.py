"""跨源计算引擎：把各源取回的行物化成临时表，在其上执行 JOIN / 聚合。

设计成可切换的抽象 `ComputeEngine`：
- 现在：`DuckDbCompute`（DuckDB `:memory:`）——零外部依赖、进程内。
- 将来：`SqlDbCompute`（专用临时 SQL 库）——步骤完全一致，只换实现。

优化器仍只产出方言中立的 `QuerySpec`；具体 SQL 由计算引擎按自己的方言渲染，
表名是「已物化的临时表名」（`_table_source` = 纯表名，不像 CSV 包 read_csv）。

每次运行独立一个实例（挂在 ExecContext 上），避免并发 run 的临时表撞名。
"""

from __future__ import annotations

import datetime
from abc import ABC, abstractmethod

from nexus.core.models import QuerySpec


class ComputeEngine(ABC):
    """内存/临时 SQL 计算引擎抽象。"""

    @abstractmethod
    def load(self, table: str, rows: list[dict]) -> None:
        """把一批行物化成名为 table 的临时表（已存在则替换）。"""
        ...

    @abstractmethod
    def run(self, spec: QuerySpec, into: str | None = None) -> list[dict]:
        """编译 QuerySpec→SQL 执行，返回行；into 给定则同时把结果物化成该表。"""
        ...

    def close(self) -> None:
        ...


def _duck_type(rows: list[dict], col: str) -> str:
    for r in rows:
        v = r.get(col)
        if v is None:
            continue
        if isinstance(v, bool):
            return "BOOLEAN"
        if isinstance(v, int):
            return "BIGINT"
        if isinstance(v, float):
            return "DOUBLE"
        if isinstance(v, datetime.datetime):
            return "TIMESTAMP"
        if isinstance(v, datetime.date):
            return "DATE"
        return "VARCHAR"
    return "VARCHAR"


class DuckDbCompute(ComputeEngine):
    """DuckDB 内存实现。"""

    def __init__(self):
        import duckdb
        self._con = duckdb.connect(database=":memory:")

    def load(self, table: str, rows: list[dict]) -> None:
        self._con.execute(f'DROP TABLE IF EXISTS "{table}"')
        if not rows:
            self._con.execute(f'CREATE TABLE "{table}" (_empty INTEGER)')
            return
        cols = list(rows[0].keys())
        defs = ", ".join(f'"{c}" {_duck_type(rows, c)}' for c in cols)
        self._con.execute(f'CREATE TABLE "{table}" ({defs})')
        ph = ",".join(["?"] * len(cols))
        self._con.executemany(
            f'INSERT INTO "{table}" VALUES ({ph})',
            [[r.get(c) for c in cols] for r in rows],
        )

    def run(self, spec: QuerySpec, into: str | None = None) -> list[dict]:
        sql, params = self._render(spec)
        if into:
            self._con.execute(f'DROP TABLE IF EXISTS "{into}"')
            self._con.execute(f'CREATE TABLE "{into}" AS {sql}', params)
            cur = self._con.execute(f'SELECT * FROM "{into}"')
        else:
            cur = self._con.execute(sql, params)
        cols = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        try:
            self._con.close()
        except Exception:
            pass

    # ── QuerySpec → DuckDB SQL（表名=已物化临时表，不做 read_csv 包裹）──
    def _cond(self, f, params: list) -> str:
        if f.op == "IN":
            vals = f.value if isinstance(f.value, list) else [f.value]
            params.extend(vals)
            return f"{f.col} IN ({','.join(['?'] * len(vals))})"
        params.append(f.value)
        return f"{f.col} {f.op} ?"

    def _render(self, spec: QuerySpec) -> tuple[str, list]:
        if spec.from_alias:
            from_sql = f'"{spec.from_table}" {spec.from_alias}'
            for j in spec.joins:
                from_sql += f' JOIN "{j.table}" {j.alias} ON {j.on_left} = {j.on_right}'
        else:
            from_sql = f'"{spec.from_table}"'

        params: list = []
        where = [self._cond(f, params) for f in spec.filters]
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        if not spec.value_expr and not spec.selects:
            # 纯连接/投影：取全部列（列名已在各 fetch 里加实体前缀去重）
            return f"SELECT * FROM {from_sql}{where_sql}", params

        if spec.selects:
            cols = ", ".join(f"{s.expr} AS {s.alias}" for s in spec.selects)
            head = (f"{spec.label_expr} AS label, " if spec.label_expr else "") + cols
            sql = f"SELECT {head} FROM {from_sql}{where_sql}"
            if spec.label_expr:
                sql += f" GROUP BY {spec.label_expr}"
            return sql, params

        # 聚合
        if spec.label_expr:
            sql = f"SELECT {spec.label_expr} AS label, {spec.value_expr} AS value FROM {from_sql}{where_sql}"
            sql += f" GROUP BY {spec.label_expr}"
            if spec.having:
                sql += f" HAVING {spec.value_expr} {spec.having.op} ?"
                params.append(spec.having.value)
            sql += f" ORDER BY value {spec.order}"
            if spec.limit:
                sql += f" LIMIT {int(spec.limit)}"
        else:
            sql = f"SELECT {spec.value_expr} AS value FROM {from_sql}{where_sql}"
            if spec.having:
                sql += f" HAVING {spec.value_expr} {spec.having.op} ?"
                params.append(spec.having.value)
        return sql, params
