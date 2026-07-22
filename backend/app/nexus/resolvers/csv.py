"""CsvResolver：把一个本地文件夹里的 CSV 当数据源，用 DuckDB 执行取数。

持有独立 DuckDB 连接，通过共享 typed QueryIR renderer 生成 DuckDB SQL，并探测列结构。
config 来自 local_file_credential.to_config()：
  { base_dir: 本地文件夹, filename: 可选 }

filename 决定实体粒度（describe 据此枚举候选表）：
  - 空          → 整个文件夹一个实体，key = `*.csv`（运行时 union 合并）
  - 具体文件名  → 该单文件一个实体
  - 通配符      → 匹配到的每个文件各一个实体

绑定：entity 的物理落点(expr) = 文件名或 glob（如 `orders.csv` / `*.csv`）；
运行时 _table_source 把它包成 `read_csv_auto('<base_dir>/<expr>')`。
"""

from __future__ import annotations

import glob as _glob
import os
from typing import Any, Optional

from nexus.core.models import NodeResult, ExecContext
from nexus.core.physical import QueryIR
from nexus.resolvers.base import Resolver
from nexus.resolvers.query_renderer import QueryRenderer


# DuckDB 类型 → 粗粒度语义类型（concept 是语义层，不绑死某引擎的类型表）
_COARSE_TYPE = {
    "tinyint": "number", "smallint": "number", "integer": "number", "int": "number",
    "bigint": "number", "hugeint": "number", "utinyint": "number", "usmallint": "number",
    "uinteger": "number", "ubigint": "number", "decimal": "number", "numeric": "number",
    "real": "number", "float": "number", "double": "number",
    "varchar": "text", "char": "text", "text": "text", "string": "text", "uuid": "text",
    "date": "date", "timestamp": "date", "timestamp_s": "date", "timestamp_ms": "date",
    "timestamp_ns": "date", "datetime": "date", "time": "date",
    "boolean": "bool", "bool": "bool",
}

_GLOB_CHARS = set("*?[")

def _coarse_type(raw: str) -> str:
    base = (raw or "").strip().lower().split("(")[0].strip()   # DECIMAL(18,2) → decimal
    return _COARSE_TYPE.get(base, "unknown")


class CsvResolver(Resolver):
    resolver_type = "csv"
    provides_concepts = True
    operators = {"SELECT", "AGGREGATE"}

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        self._base = os.path.realpath(self.config.get("base_dir", "") or "")
        self._filename = (self.config.get("filename") or "").strip()
        self._conn = None   # 惰性建 DuckDB 连接（无 duckdb 环境也能装配 registry）

    @property
    def _source(self) -> str:
        return f"{self.name}:{os.path.basename(self._base) or self._base}"

    def _dd(self):
        if self._conn is None:
            import duckdb
            self._conn = duckdb.connect(database=":memory:")
        return self._conn

    # ── 路径安全：locator（文件名/glob）解析到 base_dir 下，防穿越 ──
    def _safe_path(self, locator: str) -> str:
        p = os.path.realpath(os.path.join(self._base, locator))
        if p != self._base and not p.startswith(self._base + os.sep):
            raise ValueError(f"CSV path escapes base_dir: {locator!r}")
        return p

    def _table_source(self, locator: str) -> str:
        """文件名/glob → DuckDB 的 read_csv_auto(...) 表源。"""
        path = self._safe_path(locator).replace("\\", "/").replace("'", "''")
        if any(ch in locator for ch in _GLOB_CHARS):
            return f"read_csv_auto('{path}', union_by_name=true)"
        return f"read_csv_auto('{path}')"

    def compile(self, query: QueryIR) -> dict:
        rendered = QueryRenderer(table_source=self._table_source).render(query)
        return {"sql": rendered.sql, "params": rendered.params}

    def capabilities(self) -> dict:
        base = super().capabilities()
        base["relational"] = {
            "filter": ["EQ", "NE", "GT", "GTE", "LT", "LTE", "IN", "BETWEEN", "LIKE"],
            "join": ["INNER", "LEFT"],
            "aggregates": ["SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX", "MEDIAN", "PERCENTILE", "VARIANCE", "STDDEV"],
            "time_grains": ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"],
            "conditional_aggregate": True, "top_n": True,
        }
        return base

    def fetch(self, call: dict, ctx: Optional[ExecContext] = None) -> NodeResult:
        node_id = call.get("node_id", "")
        sql = call.get("sql", "")
        params = list(call.get("params") or [])
        try:
            # 每次取数用独立连接：协调器会同波并行执行多个节点，
            # 单个 DuckDB 连接不支持多线程并发 execute（会串结果）。
            import duckdb
            con = duckdb.connect(database=":memory:")
            try:
                cur = con.execute(sql, params)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            finally:
                con.close()
            return NodeResult(
                node_id=node_id, resolver=self.name, output=rows,
                columns=cols, rows=rows, source=self._source, detail=sql,
            )
        except Exception as exc:
            return NodeResult(node_id=node_id, resolver=self.name, error=str(exc),
                              source=self._source, detail=sql)

    # ── 建本体：枚举候选表（据 filename 语义）+ 探测列 ──
    def _list_tables(self) -> list[str]:
        """返回候选表 key 列表（文件名或 glob），供 describe / 前端选择。"""
        fn = self._filename
        if not fn:
            return ["*.csv"]                       # 文件夹整体一个实体
        if any(ch in fn for ch in _GLOB_CHARS):
            matches = sorted(_glob.glob(os.path.join(self._base, fn)))
            return [os.path.basename(m) for m in matches]   # 逐文件
        return [fn]                                # 单文件

    def describe(self) -> dict:
        """探测：返回 {表key: [{column, type, dtype}]}。dtype 为粗粒度语义类型。"""
        conn = self._dd()
        out: dict[str, list] = {}
        for key in self._list_tables():
            try:
                rows = conn.execute(f"DESCRIBE SELECT * FROM {self._table_source(key)}").fetchall()
            except Exception:
                continue
            out[key] = [
                {"column": r[0], "type": r[1], "dtype": _coarse_type(r[1])}
                for r in rows
            ]
        return out

    def primary_keys(self) -> dict:
        """CSV 无主键约束（用户可在本体里把某列设为维度/主键）。"""
        return {}

    def foreign_keys(self) -> list:
        """CSV 无外键（关系由用户在画布上手动连）。"""
        return []

    def sample(self, target: str = None, n: int = 5) -> list[dict[str, Any]]:
        key = target or (self._list_tables() or [None])[0]
        if not key:
            return []
        try:
            cur = self._dd().execute(f"SELECT * FROM {self._table_source(key)} LIMIT {int(n)}")
            cols = [d[0] for d in cur.description] if cur.description else []
            return [dict(zip(cols, r)) for r in cur.fetchall()]
        except Exception:
            return []
