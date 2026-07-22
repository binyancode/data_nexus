"""可切换的跨源临时计算引擎。

- ``DuckDbCompute``：每个 run 独立的 DuckDB ``:memory:``。
- ``SqlServerCompute``：每个 run 独占 SQL Server 连接，切换到固定
    ``WITHOUT LOGIN`` 运行用户，并只使用当前 Session 可见的 ``#temp`` 表。

Optimizer 产出方言中立的 typed ``QueryIR``；引擎负责数据物化、方言渲染、
会话隔离与清理。计算引擎配置和运行实例是两层概念：同一份配置可服务多个
run，但每个 run 都创建独立实例。
"""

from __future__ import annotations

import datetime
import decimal
import re
import threading
import uuid
from abc import ABC, abstractmethod
from typing import Any

from nexus.core.physical import QueryIR
from nexus.resolvers.query_renderer import QueryRenderer
from nexus.resolvers.duckdb_query_renderer import DuckDbQueryRenderer
from nexus.resolvers.sql_server_query_renderer import SqlServerQueryRenderer
from services.sql_db import sql_db


_SQL_USER = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,127}$")
_BLOCKED_USERS = {"dbo", "guest", "sys", "information_schema", "public"}


def validate_runtime_user(value: str) -> str:
    user = (value or "").strip()
    if not _SQL_USER.fullmatch(user):
        raise ValueError("运行用户名必须以字母开头，只能包含字母、数字、下划线，长度 3-128")
    if user.casefold() in _BLOCKED_USERS:
        raise ValueError(f"禁止使用系统数据库用户：{user}")
    return user


def _sql_identifier(value: str) -> str:
    return "[" + str(value).replace("]", "]]") + "]"


def _sql_literal(value: str) -> str:
    return "N'" + str(value).replace("'", "''") + "'"


class ComputeEngine(ABC):
    """一次 run 使用的临时计算引擎实例。"""

    name: str
    engine_type: str
    lock: threading.Lock

    @abstractmethod
    def load(self, table: str, rows: list[dict], columns: list[str] | None = None) -> None:
        """把一批行物化成名为 table 的临时表（已存在则替换）。"""
        ...

    @abstractmethod
    def run(self, query: QueryIR, into: str | None = None) -> list[dict]:
        """编译 QueryIR→SQL 执行，返回行；into 给定则同时把结果物化成该表。"""
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

    engine_type = "duckdb"

    def __init__(self, name: str = "duckdb", config: dict | None = None):
        import duckdb
        self.name = name
        self.config = dict(config or {})
        self.lock = threading.Lock()
        self._renderer: QueryRenderer = DuckDbQueryRenderer(
            table_source=lambda table: f'"{table.replace(chr(34), chr(34) * 2)}"'
        )
        self._con = duckdb.connect(database=":memory:")
        try:
            if self.config.get("memory_limit"):
                self._con.execute("SET memory_limit = ?", [str(self.config["memory_limit"])])
            if self.config.get("threads"):
                self._con.execute("SET threads = ?", [int(self.config["threads"])])
        except Exception:
            self.close()
            raise

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "joins": ["INNER", "LEFT"],
            "aggregates": [
                "SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX",
                "MEDIAN", "PERCENTILE", "VARIANCE", "STDDEV",
            ],
            "time_grains": ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"],
            "conditional_aggregate": True,
            "top_n": True,
            "spill": True,
        }

    def load(self, table: str, rows: list[dict], columns: list[str] | None = None) -> None:
        self._con.execute(f'DROP TABLE IF EXISTS "{table}"')
        cols = list(rows[0].keys()) if rows else list(columns or [])
        if not cols:
            self._con.execute(f'CREATE TABLE "{table}" (_empty INTEGER)')
            return
        defs = ", ".join(f'"{c}" {_duck_type(rows, c)}' for c in cols)
        self._con.execute(f'CREATE TABLE "{table}" ({defs})')
        if not rows:
            return
        ph = ",".join(["?"] * len(cols))
        self._con.executemany(
            f'INSERT INTO "{table}" VALUES ({ph})',
            [[r.get(c) for c in cols] for r in rows],
        )

    def run(self, query: QueryIR, into: str | None = None) -> list[dict]:
        rendered = self._renderer.render(query)
        sql, params = rendered.sql, rendered.params
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


def _sql_server_type(rows: list[dict], column: str) -> str:
    values = [row.get(column) for row in rows if row.get(column) is not None]
    if not values:
        return "nvarchar(max)"
    if all(isinstance(value, bool) for value in values):
        return "bit"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "bigint"
    if all(isinstance(value, (int, float, decimal.Decimal)) and not isinstance(value, bool)
           for value in values):
        if any(isinstance(value, decimal.Decimal) for value in values):
            return "decimal(38, 18)"
        return "float"
    if all(isinstance(value, datetime.datetime) for value in values):
        return "datetime2(7)"
    if all(isinstance(value, datetime.date) for value in values):
        return "date"
    if all(isinstance(value, (bytes, bytearray, memoryview)) for value in values):
        return "varbinary(max)"
    length = max(len(str(value)) for value in values)
    return f"nvarchar({max(1, min(4000, length))})" if length <= 4000 else "nvarchar(max)"


class SqlServerCompute(ComputeEngine):
    """SQL Server Session 隔离实现。

    管理凭据只用于建立该 run 的独占连接。连接建立后立即 ``EXECUTE AS``
    配置绑定的固定 ``WITHOUT LOGIN`` 用户，所有输入都写入本 Session 的本地
    ``#temp`` 表；``close`` 时 REVERT 并关闭连接，SQL Server 自动清理临时表。
    """

    engine_type = "sql_server"

    def __init__(self, name: str, connection_config: dict, runtime_user: str,
                 run_id: str, config: dict | None = None):
        self.name = name
        self.config = dict(config or {})
        self.runtime_user = validate_runtime_user(runtime_user)
        self.run_id = run_id
        self.lock = threading.Lock()
        self._command_timeout = int(self.config.get("command_timeout", 120) or 120)
        self._batch_size = max(1, int(self.config.get("batch_size", 1000) or 1000))
        self._db = sql_db(connection_config)
        self._con = self._db.open_dedicated_connection()
        self._con.timeout = self._command_timeout
        self._tables: dict[str, str] = {}
        self._renderer: QueryRenderer = SqlServerQueryRenderer(
            table_source=self._table_source
        )
        self._impersonated = False
        self._prefix = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S") + \
            "_" + re.sub(r"[^A-Za-z0-9]", "", run_id)[:8].lower()
        try:
            self._execute_as_runtime_user()
        except Exception:
            self._safe_close_connection()
            self._db.close()
            raise

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "joins": ["INNER", "LEFT"],
            "aggregates": [
                "SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX",
                "MEDIAN", "PERCENTILE", "VARIANCE", "STDDEV",
            ],
            "time_grains": ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"],
            "conditional_aggregate": True,
            "top_n": True,
            "spill": True,
        }

    def _cursor(self):
        return self._con.cursor()

    def _execute_as_runtime_user(self) -> None:
        with self._cursor() as cursor:
            cursor.execute(f"EXECUTE AS USER = {_sql_literal(self.runtime_user)}")
            current = cursor.execute("SELECT USER_NAME()").fetchone()[0]
            if str(current).casefold() != self.runtime_user.casefold():
                raise RuntimeError(
                    f"SQL Server 运行身份切换失败：expected={self.runtime_user}, actual={current}"
                )
        self._impersonated = True

    def _physical_table(self, logical: str) -> str:
        existing = self._tables.get(logical)
        if existing:
            return existing
        safe = re.sub(r"[^A-Za-z0-9_]", "_", logical).strip("_")[:32] or "input"
        physical = f"#nxce_{safe}_{self._prefix}_{uuid.uuid4().hex[:6]}"[:110]
        self._tables[logical] = physical
        return physical

    def _table_source(self, logical: str) -> str:
        if logical not in self._tables:
            raise ValueError(f"SQL Server Compute input table not loaded: {logical}")
        return _sql_identifier(self._tables[logical])

    def load(self, table: str, rows: list[dict], columns: list[str] | None = None) -> None:
        physical = self._physical_table(table)
        cols = list(rows[0].keys()) if rows else list(columns or [])
        with self._cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {_sql_identifier(physical)}")
            if not cols:
                cursor.execute(f"CREATE TABLE {_sql_identifier(physical)} ([_empty] int NULL)")
                return
            definitions = ", ".join(
                f"{_sql_identifier(column)} {_sql_server_type(rows, column)} NULL"
                for column in cols
            )
            cursor.execute(f"CREATE TABLE {_sql_identifier(physical)} ({definitions})")
            if not rows:
                return
            placeholders = ", ".join("?" for _ in cols)
            statement = (
                f"INSERT INTO {_sql_identifier(physical)} "
                f"({', '.join(_sql_identifier(column) for column in cols)}) "
                f"VALUES ({placeholders})"
            )
            values = [[row.get(column) for column in cols] for row in rows]
            for offset in range(0, len(values), self._batch_size):
                cursor.executemany(statement, values[offset:offset + self._batch_size])

    def run(self, query: QueryIR, into: str | None = None) -> list[dict]:
        rendered = self._renderer.render(query)
        with self._cursor() as cursor:
            cursor.execute(rendered.sql, rendered.params)
            cols = [description[0] for description in cursor.description] if cursor.description else []
            rows = [dict(zip(cols, row)) for row in cursor.fetchall()]
        if into:
            self.load(into, rows, cols)
        return rows

    def _safe_close_connection(self) -> None:
        try:
            self._con.close()
        except Exception:
            pass

    def close(self) -> None:
        try:
            if self._impersonated:
                try:
                    with self._cursor() as cursor:
                        cursor.execute("REVERT")
                        cursor.execute("SELECT USER_NAME()").fetchone()
                except Exception:
                    # 该连接不会回池；关闭物理连接即可销毁身份与所有本地临时表。
                    pass
                finally:
                    self._impersonated = False
        finally:
            self._safe_close_connection()
            self._db.close()


class SqlServerComputeProvisioner:
    """创建、验证和删除一份 SQL Server 计算引擎配置拥有的固定运行用户。"""

    def __init__(self, connection_config: dict, command_timeout: int = 120):
        self._db = sql_db(connection_config)
        self._command_timeout = int(command_timeout)

    def _connection(self):
        connection = self._db.open_dedicated_connection()
        connection.timeout = self._command_timeout
        return connection

    def user_exists(self, runtime_user: str) -> bool:
        user = validate_runtime_user(runtime_user)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                return bool(cursor.execute(
                    "SELECT COUNT(*) FROM sys.database_principals WHERE [name] = ?",
                    user,
                ).fetchone()[0])
        finally:
            connection.close()

    def create_and_test(self, runtime_user: str) -> None:
        user = validate_runtime_user(runtime_user)
        connection = None
        created = False
        impersonated = False
        probe = f"#nxce_probe_{uuid.uuid4().hex[:8]}"
        try:
            connection = self._connection()
            with connection.cursor() as cursor:
                if cursor.execute(
                    "SELECT COUNT(*) FROM sys.database_principals WHERE [name] = ?", user
                ).fetchone()[0]:
                    raise ValueError(f"SQL Server 数据库用户已存在，不能被计算引擎接管：{user}")
                cursor.execute(f"CREATE USER {_sql_identifier(user)} WITHOUT LOGIN")
                created = True
                cursor.execute(f"EXECUTE AS USER = {_sql_literal(user)}")
                impersonated = True
                actual = cursor.execute("SELECT USER_NAME()").fetchone()[0]
                if str(actual).casefold() != user.casefold():
                    raise RuntimeError(f"EXECUTE AS USER 验证失败：{actual}")
                cursor.execute(f"CREATE TABLE {_sql_identifier(probe)} ([value] int NOT NULL)")
                cursor.execute(f"INSERT INTO {_sql_identifier(probe)} ([value]) VALUES (1)")
                value = cursor.execute(
                    f"SELECT [value] FROM {_sql_identifier(probe)}"
                ).fetchone()[0]
                if value != 1:
                    raise RuntimeError("SQL Server Compute 临时表读写验证失败")
                cursor.execute(f"DROP TABLE {_sql_identifier(probe)}")
                cursor.execute("REVERT")
                impersonated = False
        except Exception as exc:
            cleanup_errors = []
            if connection is not None and impersonated:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("REVERT")
                    impersonated = False
                except Exception as cleanup_exc:
                    cleanup_errors.append(f"REVERT 失败：{cleanup_exc}")
            if created:
                # 丢弃承载过 EXECUTE AS 的测试连接，始终用新的管理员连接回滚用户。
                if connection is not None:
                    try:
                        connection.close()
                    finally:
                        connection = None
                cleanup_connection = None
                try:
                    cleanup_connection = self._connection()
                    with cleanup_connection.cursor() as cursor:
                        if cursor.execute(
                            "SELECT COUNT(*) FROM sys.database_principals WHERE [name] = ?",
                            user,
                        ).fetchone()[0]:
                            cursor.execute(f"DROP USER {_sql_identifier(user)}")
                    created = False
                except Exception as cleanup_exc:
                    cleanup_errors.append(f"DROP USER 失败：{cleanup_exc}")
                finally:
                    if cleanup_connection is not None:
                        cleanup_connection.close()
            if cleanup_errors:
                raise RuntimeError(
                    f"SQL Server 计算引擎测试失败：{exc}；" + "；".join(cleanup_errors)
                ) from exc
            raise
        finally:
            if connection is not None:
                connection.close()
            self._db.close()

    def test_existing(self, runtime_user: str) -> None:
        user = validate_runtime_user(runtime_user)
        connection = self._connection()
        impersonated = False
        probe = f"#nxce_probe_{uuid.uuid4().hex[:8]}"
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"EXECUTE AS USER = {_sql_literal(user)}")
                impersonated = True
                cursor.execute(f"CREATE TABLE {_sql_identifier(probe)} ([value] int NOT NULL)")
                cursor.execute(f"INSERT INTO {_sql_identifier(probe)} VALUES (1)")
                cursor.execute(f"SELECT [value] FROM {_sql_identifier(probe)}").fetchone()
                cursor.execute(f"DROP TABLE {_sql_identifier(probe)}")
                cursor.execute("REVERT")
                impersonated = False
        finally:
            if impersonated:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("REVERT")
                except Exception:
                    pass
            connection.close()
            self._db.close()

    def drop_user(self, runtime_user: str) -> None:
        user = validate_runtime_user(runtime_user)
        connection = self._connection()
        try:
            with connection.cursor() as cursor:
                if cursor.execute(
                    "SELECT COUNT(*) FROM sys.database_principals WHERE [name] = ?", user
                ).fetchone()[0]:
                    cursor.execute(f"DROP USER {_sql_identifier(user)}")
        finally:
            connection.close()
            self._db.close()
