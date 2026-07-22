"""数据库实时计算引擎目录与运行实例工厂。

计算引擎配置不做内存缓存：列表、解析和每次 run 的获取均直接读取
``nexus.compute_engines``。内存中仅保留当前进程的运行租约计数，用于阻止正在
执行的配置被删除；租约不是配置数据。
"""

from __future__ import annotations

import json
import re
import threading
from typing import Any

from pydantic import BaseModel, Field

from core.services import services
from services.credential import azure_keyvault_credential_provider
from services.sql_db import sql_db

from nexus.engine.compute import (
    ComputeEngine,
    DuckDbCompute,
    SqlServerCompute,
    SqlServerComputeProvisioner,
    validate_runtime_user,
)


_ENGINE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,99}$")
_SCHEMA_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_ENGINE_TYPES = {"duckdb", "sql_server"}


class ComputeEngineDefinition(BaseModel):
    engine_name: str
    engine_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    credential_name: str | None = None
    runtime_user: str | None = None
    is_default: bool = False
    is_active: bool = True
    provision_state: str = "ready"
    provision_error: str | None = None
    creation_time: Any = None
    update_time: Any = None

    def public(self) -> dict[str, Any]:
        data = self.model_dump(mode="json")
        data["capabilities"] = compute_capabilities(self.engine_type)
        return data


def compute_capabilities(engine_type: str) -> dict[str, Any]:
    if engine_type == "duckdb":
        return DuckDbCompute.capabilities()
    if engine_type == "sql_server":
        return SqlServerCompute.capabilities()
    return {}


class ComputeEngineRegistry:
    """直接读写数据库的计算引擎目录；不缓存任何配置定义。"""

    _COLUMNS = """engine_name, engine_type, config, credential_name, runtime_user,
                  is_default, is_active, provision_state, provision_error,
                  creation_time, update_time"""

    def __init__(self, schema: str = "nexus"):
        if not _SCHEMA_NAME.fullmatch(schema or ""):
            raise ValueError(f"非法数据库 schema：{schema}")
        self._schema = schema
        self._table = f"[{schema}].[compute_engines]"
        self._lock = threading.RLock()
        self._active_runs: dict[str, int] = {}

    @property
    def _db(self) -> sql_db:
        return services[sql_db]

    @property
    def _credentials(self) -> azure_keyvault_credential_provider:
        return services[azure_keyvault_credential_provider]

    @staticmethod
    def _validate_engine_name(value: str) -> str:
        name = (value or "").strip()
        if not _ENGINE_NAME.fullmatch(name):
            raise ValueError("计算引擎名称必须以字母开头，只能包含字母、数字、点、短横线、下划线，长度 2-100")
        return name

    @staticmethod
    def _normalize_config(engine_type: str, config: dict | None) -> dict[str, Any]:
        result = dict(config or {})
        if engine_type == "sql_server":
            result["command_timeout"] = max(1, int(result.get("command_timeout", 120) or 120))
            result["batch_size"] = max(1, int(result.get("batch_size", 1000) or 1000))
        return result

    @staticmethod
    def _from_row(row: dict) -> ComputeEngineDefinition:
        raw_config = row.get("config") or "{}"
        try:
            config = json.loads(raw_config) if isinstance(raw_config, str) else dict(raw_config)
        except (TypeError, json.JSONDecodeError):
            config = {}
        return ComputeEngineDefinition(
            engine_name=row["engine_name"],
            engine_type=row["engine_type"],
            config=config,
            credential_name=row.get("credential_name"),
            runtime_user=row.get("runtime_user"),
            is_default=bool(row.get("is_default")),
            is_active=bool(row.get("is_active")),
            provision_state=row.get("provision_state") or "ready",
            provision_error=row.get("provision_error"),
            creation_time=row.get("creation_time"),
            update_time=row.get("update_time"),
        )

    def list(self) -> list[dict[str, Any]]:
        """直接返回数据库当前行；不读取或写入任何配置快照。"""
        rows = self._db.execute_query(
            f"""SELECT {self._COLUMNS}
                  FROM {self._table}
                 WHERE is_active = 1
                 ORDER BY is_default DESC, engine_name"""
        )
        return [self._from_row(row).public() for row in rows]

    def _find_definition(self, name: str | None = None,
                         *, require_ready: bool = True) -> ComputeEngineDefinition | None:
        conditions = ["is_active = 1"]
        params: tuple | None = None
        if name:
            conditions.append("engine_name = ?")
            params = (name,)
        else:
            conditions.append("is_default = 1")
        if require_ready:
            conditions.append("provision_state = 'ready'")
        rows = self._db.execute_query(
            f"""SELECT TOP (1) {self._COLUMNS}
                  FROM {self._table}
                 WHERE {' AND '.join(conditions)}
                 ORDER BY is_default DESC, engine_name""",
            params,
        )
        return self._from_row(rows[0]) if rows else None

    def resolve(self, name: str | None = None) -> ComputeEngineDefinition:
        selected = self._validate_engine_name(name) if name else None
        definition = self._find_definition(selected, require_ready=True)
        if definition is None:
            if selected:
                raise ValueError(f"计算引擎不可用：{selected}")
            raise ValueError("没有可用的默认计算引擎")
        return definition

    def acquire(self, name: str | None = None) -> ComputeEngineDefinition:
        """实时读取配置并为一次 run 增加运行租约。"""
        with self._lock:
            definition = self.resolve(name)
            self._active_runs[definition.engine_name] = \
                self._active_runs.get(definition.engine_name, 0) + 1
            return definition

    def release(self, name: str | None) -> None:
        if not name:
            return
        with self._lock:
            count = self._active_runs.get(name, 0)
            if count <= 1:
                self._active_runs.pop(name, None)
            else:
                self._active_runs[name] = count - 1

    def capabilities(self, name: str | None = None) -> dict[str, Any]:
        return compute_capabilities(self.resolve(name).engine_type)

    def _sql_connection_config(self, credential_name: str) -> dict:
        credential = self._credentials.load(credential_name)
        if credential is None:
            raise ValueError(f"SQL Server 凭据不存在或不可用：{credential_name}")
        if credential.credential_type != "sql":
            raise ValueError(f"计算引擎必须引用 sql 类型凭据：{credential_name}")
        return credential.to_config()

    def create(self, name: str | None, run_id: str) -> ComputeEngine:
        definition = self.resolve(name)
        if definition.engine_type == "duckdb":
            return DuckDbCompute(definition.engine_name, definition.config)
        if definition.engine_type == "sql_server":
            return SqlServerCompute(
                definition.engine_name,
                self._sql_connection_config(definition.credential_name or ""),
                definition.runtime_user or "",
                run_id,
                definition.config,
            )
        raise ValueError(f"不支持的计算引擎类型：{definition.engine_type}")

    def _has_default(self) -> bool:
        rows = self._db.execute_query(
            f"""SELECT COUNT(*) AS c
                  FROM {self._table}
                 WHERE is_default = 1 AND is_active = 1
                   AND provision_state = 'ready'"""
        )
        return bool(rows and int(rows[0]["c"]) > 0)

    def _ensure_default(self) -> None:
        if self._has_default():
            return
        self._db.execute_non_query(
            f"""UPDATE {self._table}
                   SET is_default = 1, update_time = SYSUTCDATETIME()
                 WHERE engine_name = (
                     SELECT TOP (1) engine_name
                       FROM {self._table}
                      WHERE is_active = 1 AND provision_state = 'ready'
                      ORDER BY CASE WHEN engine_type = 'duckdb' THEN 0 ELSE 1 END,
                               creation_time
                 )"""
        )

    def _insert_ready_definition(self, *, name: str, kind: str, settings: dict,
                                 credential: str | None, user: str | None,
                                 is_default: bool) -> None:
        # 元数据写入是一个 SQL Server 本地事务。只有远端运行用户创建和实测均成功后
        # 才调用本方法，因此测试失败不会产生任何 compute_engines 行。
        self._db.execute_non_query(
            f"""SET XACT_ABORT ON;
                BEGIN TRANSACTION;

                DECLARE @make_default bit =
                    CASE WHEN ? = 1 OR NOT EXISTS (
                        SELECT 1 FROM {self._table}
                         WHERE is_default = 1 AND is_active = 1
                           AND provision_state = 'ready'
                    ) THEN 1 ELSE 0 END;

                IF @make_default = 1
                    UPDATE {self._table}
                       SET is_default = 0, update_time = SYSUTCDATETIME()
                     WHERE is_default = 1;

                INSERT INTO {self._table}
                    (engine_name, engine_type, config, credential_name, runtime_user,
                     is_default, is_active, provision_state, provision_error, creation_time)
                VALUES
                    (?, ?, ?, ?, ?, @make_default, 1, 'ready', NULL, SYSUTCDATETIME());

                COMMIT TRANSACTION;""",
            (
                1 if is_default else 0,
                name,
                kind,
                json.dumps(settings, ensure_ascii=False),
                credential,
                user,
            ),
        )

    def create_definition(self, *, engine_name: str, engine_type: str,
                          credential_name: str | None, runtime_user: str | None,
                          config: dict | None, is_default: bool) -> ComputeEngineDefinition:
        name = self._validate_engine_name(engine_name)
        kind = (engine_type or "").strip().lower()
        if kind not in _ENGINE_TYPES:
            raise ValueError(f"不支持的计算引擎类型：{kind}")
        settings = self._normalize_config(kind, config)
        credential = (credential_name or "").strip() or None
        user = (runtime_user or "").strip() or None

        existing = self._db.execute_query(
            f"SELECT COUNT(*) AS c FROM {self._table} WHERE engine_name = ?",
            (name,),
        )
        if existing and int(existing[0]["c"]) > 0:
            raise ValueError(f"计算引擎已存在：{name}")

        provisioner: SqlServerComputeProvisioner | None = None
        user_created = False
        if kind == "duckdb":
            credential, user = None, None
            DuckDbCompute(name, settings).close()
        else:
            if not credential or not user:
                raise ValueError("SQL Server 计算引擎必须选择凭据并填写运行用户名")
            user = validate_runtime_user(user)
            provisioner = SqlServerComputeProvisioner(
                self._sql_connection_config(credential),
                settings["command_timeout"],
            )
            # 失败会抛异常并在 Provisioner 内回滚；此时尚未写任何元数据。
            try:
                provisioner.create_and_test(user)
            except Exception as exc:
                raise RuntimeError(
                    f"SQL Server 计算引擎连接与临时表验证失败（配置未写入）：{exc}"
                ) from exc
            user_created = True

        try:
            self._insert_ready_definition(
                name=name,
                kind=kind,
                settings=settings,
                credential=credential,
                user=user,
                is_default=is_default,
            )
        except Exception as exc:
            if provisioner is not None and user_created and user:
                try:
                    provisioner.drop_user(user)
                except Exception as cleanup_exc:
                    raise RuntimeError(
                        f"计算引擎元数据写入失败：{exc}；运行用户回滚失败：{cleanup_exc}"
                    ) from exc
            raise
        return self.resolve(name)

    def update_definition(self, engine_name: str, *, config: dict | None,
                          is_default: bool) -> ComputeEngineDefinition:
        current = self.resolve(self._validate_engine_name(engine_name))
        settings = self._normalize_config(current.engine_type, config)
        if current.engine_type == "duckdb":
            DuckDbCompute(current.engine_name, settings).close()
        else:
            SqlServerComputeProvisioner(
                self._sql_connection_config(current.credential_name or ""),
                int(settings.get("command_timeout", 120)),
            ).test_existing(current.runtime_user or "")

        self._db.execute_non_query(
            f"""UPDATE {self._table}
                   SET config = ?, provision_error = NULL,
                       update_time = SYSUTCDATETIME()
                 WHERE engine_name = ? AND is_active = 1
                   AND provision_state = 'ready'""",
            (
                json.dumps(settings, ensure_ascii=False),
                current.engine_name,
            ),
        )
        if is_default:
            self.set_default(current.engine_name)
        self._ensure_default()
        return self.resolve(current.engine_name)

    def set_default(self, engine_name: str) -> ComputeEngineDefinition:
        current = self.resolve(self._validate_engine_name(engine_name))
        self._db.execute_non_query(
            f"""SET XACT_ABORT ON;
                BEGIN TRANSACTION;

                UPDATE {self._table}
                   SET is_default = 0, update_time = SYSUTCDATETIME()
                 WHERE is_default = 1;

                UPDATE {self._table}
                   SET is_default = 1, update_time = SYSUTCDATETIME()
                 WHERE engine_name = ? AND is_active = 1
                   AND provision_state = 'ready';

                IF @@ROWCOUNT <> 1
                    THROW 50001, 'Compute engine not available', 1;

                COMMIT TRANSACTION;""",
            (current.engine_name,),
        )
        return self.resolve(current.engine_name)

    def test_definition(self, engine_name: str) -> None:
        definition = self.resolve(self._validate_engine_name(engine_name))
        if definition.engine_type == "duckdb":
            engine = DuckDbCompute(definition.engine_name, definition.config)
            engine.close()
            return
        SqlServerComputeProvisioner(
            self._sql_connection_config(definition.credential_name or ""),
            int(definition.config.get("command_timeout", 120)),
        ).test_existing(definition.runtime_user or "")

    def delete_definition(self, engine_name: str) -> bool:
        selected = self._validate_engine_name(engine_name)
        with self._lock:
            definition = self._find_definition(selected, require_ready=False)
            if definition is None:
                return True  # 幂等删除：数据库已经没有该配置即视为成功。
            if self._active_runs.get(definition.engine_name, 0) > 0:
                raise ValueError("该计算引擎仍有运行中的任务，不能删除")
            active = self._db.execute_query(
                f"""SELECT COUNT(*) AS c
                      FROM [{self._schema}].[run]
                     WHERE [state] = 'running'
                       AND ISJSON(context) = 1
                       AND JSON_VALUE(context, '$.compute_engine_selected') = ?""",
                (definition.engine_name,),
            )
            if active and int(active[0]["c"]) > 0:
                raise ValueError("该计算引擎仍有运行中的任务，不能删除")
            if definition.provision_state == "ready":
                remaining = self._db.execute_query(
                    f"""SELECT COUNT(*) AS c
                          FROM {self._table}
                         WHERE is_active = 1 AND provision_state = 'ready'
                           AND engine_name <> ?""",
                    (definition.engine_name,),
                )
                if not remaining or int(remaining[0]["c"]) == 0:
                    raise ValueError("至少保留一个可用计算引擎")

            # 旧版本可能留下 provision_failed/delete_failed 行。这些配置从未成为
            # 可用引擎，删除时只删元数据，绝不再次连接目标数据库。
            if definition.provision_state != "ready":
                self._db.execute_non_query(
                    f"DELETE FROM {self._table} WHERE engine_name = ?",
                    (definition.engine_name,),
                )
                self._ensure_default()
                return True

            # 成功创建过的 SQL Server 配置必须先删除其固定用户。失败时元数据保持
            # 原样，既不制造 delete_failed 行，也不伪装成已删除。
            if definition.engine_type == "sql_server":
                SqlServerComputeProvisioner(
                    self._sql_connection_config(definition.credential_name or ""),
                    int(definition.config.get("command_timeout", 120)),
                ).drop_user(definition.runtime_user or "")

            self._db.execute_non_query(
                f"DELETE FROM {self._table} WHERE engine_name = ?",
                (definition.engine_name,),
            )
            self._ensure_default()
            return True
