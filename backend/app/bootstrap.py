"""bootstrap.py —— 共享的服务注册。

把系统 DB、凭据提供器、Nexus 引擎注册进全局 IoC 容器。
main.py 启动时调用。
"""
from services.sql_db import sql_db
from services.credential import azure_keyvault_credential_provider
from core.services import services
from core.api_handler import api_handler
from core.api_log import ApiLogRecord, ApiLogSink
from nexus.core.run_log import RunRecorder, register_run_recorder
from utils.logger import get_logger
from nexus.client import NexusClient

_log = get_logger("api")
_run_log = get_logger("nexus")


class ApiLogRecorder(ApiLogSink):
    """API 日志汇：同时记录到 nexus.api_log 和系统 logger（按 state 分级）。

    DB 依赖留在 app 层，core 不引用 services。
    """

    def emit(self, record: ApiLogRecord) -> None:
        # 1) 系统 logger（按状态分级；错误时把完整堆栈换行打出，便于定位报错行）
        line = (f"[{record.function}] {record.method} {record.path} "
                f"state={record.state} user={record.user} {record.cost_ms}ms")
        if record.state in ("failed", "error"):
            _log.error(line + (f"\n{record.message}" if record.message else ""))
        elif record.state in ("denied", "unauthorized"):
            _log.warning(line + (f" {record.message}" if record.message else ""))
        else:
            _log.info(line)

        # 2) 数据库
        services[sql_db].execute_non_query(
            """INSERT INTO nexus.api_log
                   (function_name, [method], [path], user_name, payload, response, state, cost_ms, message, source, request_time, response_time)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.function, record.method, record.path, record.user, record.payload,
                record.response, record.state, record.cost_ms, record.message, record.source,
                record.request_time, record.response_time,
            ),
        )


# stage → seq（四个引擎的固定顺序）
_STAGE_SEQ = {"initializer": 1, "compiler": 2, "optimizer": 3, "coordinator": 4, "generator": 5}


class DbRunRecorder(RunRecorder):
    """运行记录器：把 run / run_stage / run_node 增量落库，供前端轮询看执行进度。

    - start_* 写入一行（state=running），finish_* 更新该行（state + 结果 + 耗时）。
    - DB 依赖留在 app 层，core / nexus 引擎只认 RunRecorder 接口。
    - 记录失败绝不影响主流程：任何异常吞掉并记 warning。
    """

    @property
    def _db(self) -> sql_db:
        return services[sql_db]

    def _exec(self, sql: str, params: tuple) -> None:
        try:
            self._db.execute_non_query(sql, params)
        except Exception as exc:  # 记录失败不能拖垮问答
            _run_log.warning(f"run recorder failed: {exc}")

    # ── run ──
    def start_run(self, run_id, question, as_user, ontology_id=None):
        self._exec(
            """INSERT INTO nexus.run (run_id, question, as_user, ontology_id, [state], cost_ms, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'running', 0, SYSUTCDATETIME(), SYSUTCDATETIME())""",
            (run_id, question, as_user, ontology_id),
        )

    def finish_run(self, run_id, state, answer, cost_ms):
        self._exec(
            """UPDATE nexus.run
                  SET [state] = ?, answer = ?, cost_ms = ?, updated_at = SYSUTCDATETIME()
                WHERE run_id = ?""",
            (state, answer, cost_ms, run_id),
        )

    def set_run_ontology(self, run_id, ontology_id):
        self._exec(
            "UPDATE nexus.run SET ontology_id = ?, updated_at = SYSUTCDATETIME() WHERE run_id = ?",
            (ontology_id, run_id),
        )

    # ── stage ──
    def start_stage(self, run_id, stage, input):
        self._exec(
            """INSERT INTO nexus.run_stage (run_id, stage, seq, [state], [input], started_at)
               VALUES (?, ?, ?, 'running', ?, SYSUTCDATETIME())""",
            (run_id, stage, _STAGE_SEQ.get(stage, 0), input),
        )

    def finish_stage(self, run_id, stage, state, output, error, cost_ms, logs=None):
        self._exec(
            """UPDATE nexus.run_stage
                  SET [state] = ?, [output] = ?, error = ?, cost_ms = ?, logs = ?, ended_at = SYSUTCDATETIME()
                WHERE run_id = ? AND stage = ?""",
            (state, output, error, cost_ms, logs, run_id, stage),
        )

    # ── node ──
    def start_node(self, run_id, node_id, resolver, call):
        self._exec(
            """INSERT INTO nexus.run_node (run_id, node_id, [state], resolver, [call], started_at)
               VALUES (?, ?, 'running', ?, ?, SYSUTCDATETIME())""",
            (run_id, node_id, resolver, call),
        )

    def finish_node(self, run_id, node_id, state, call, output, value, source, trust, error, cost_ms, logs=None):
        self._exec(
            """UPDATE nexus.run_node
                  SET [state] = ?, [call] = ?, [output] = ?, [value] = ?, [source] = ?,
                      trust = ?, error = ?, cost_ms = ?, logs = ?, ended_at = SYSUTCDATETIME()
                WHERE run_id = ? AND node_id = ?""",
            (state, call, output, value, source, trust, error, cost_ms, logs, run_id, node_id),
        )


def register_services():
    """注册服务类型及默认配置映射。"""
    services.register(sql_db)
    services.register(azure_keyvault_credential_provider)
    services.register(NexusClient)

    # services[Type] 取实例时，自动把对应 config 段传给构造函数
    services.register_default_config(sql_db, "sql_db")
    services.register_default_config(azure_keyvault_credential_provider, "credential_provider")
    services.register_default_config(NexusClient, "nexus")

    # 注册实现 ApiLogSink 接口的日志汇（依赖倒置：DB 依赖在 app 层，core 不引用 services）
    api_handler.register_log_sink(ApiLogRecorder())

    # 注册运行记录器（同上：把 run/run_stage/run_node 落库，core/nexus 只认接口）
    register_run_recorder(DbRunRecorder())


def register_resolvers():
    """Resolver / LLM 由 NexusClient 启动时从 `nexus.resolvers` / `nexus.llms`
    注册表加载（密文经 credential/KV），此处无需手动注册。"""
    pass


