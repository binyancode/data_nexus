import os
import sys
import unittest
from unittest.mock import Mock, patch

_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from nexus.core.expressions import (
    AggregateExpr, BinaryExpr, ColumnExpr, ComparisonPredicate, LiteralExpr,
)
from nexus.core.logical import Operator
from nexus.core.models import ExecContext
from nexus.core.physical import (
    CapabilityFragment,
    ComputeFragment,
    ComputeInput,
    PhysicalExecutionPlan,
    QueryIR,
    QueryOutput,
    QuerySource,
)
from nexus.engine.binder import BindingError
from nexus.engine.compute import DuckDbCompute, SqlServerCompute, validate_runtime_user
from nexus.engine.compute_registry import ComputeEngineDefinition, ComputeEngineRegistry
from nexus.engine.coordinator import Coordinator
from nexus.engine.optimizer import Optimizer
from nexus.resolvers.query_renderer import QueryRenderer
from nexus.resolvers.duckdb_query_renderer import DuckDbQueryRenderer
from nexus.resolvers.sql_server_query_renderer import SqlServerQueryRenderer


class _ResolverRegistry:
    @staticmethod
    def resolver(name):
        return None


class _ComputeRegistryThatMustNotRun:
    @staticmethod
    def create(name, run_id):
        raise AssertionError("CALCULATE-only plan must not create a database compute engine")


class _FakeComputeDb:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.query_count = 0
        self.non_queries: list[tuple[str, object]] = []

    def execute_query(self, sql, params=None):
        self.query_count += 1
        candidates = [dict(row) for row in self.rows if row.get("is_active", True)]
        if "TOP (1)" in sql:
            if params:
                candidates = [row for row in candidates if row["engine_name"] == params[0]]
            else:
                candidates = [row for row in candidates if row.get("is_default")]
            if "provision_state = 'ready'" in sql:
                candidates = [row for row in candidates if row.get("provision_state") == "ready"]
            return candidates[:1]
        return sorted(candidates, key=lambda row: (not row.get("is_default", False), row["engine_name"]))

    def execute_non_query(self, sql, params=None):
        self.non_queries.append((sql, params))
        return 1


class _RegistryWithDb(ComputeEngineRegistry):
    def __init__(self, db):
        super().__init__()
        self.db = db

    @property
    def _db(self):
        return self.db


def _engine_row(name: str, engine_type: str = "duckdb", *, is_default: bool = False,
                state: str = "ready") -> dict:
    return {
        "engine_name": name,
        "engine_type": engine_type,
        "config": "{}",
        "credential_name": "sql-credential" if engine_type == "sql_server" else None,
        "runtime_user": "runtime_user" if engine_type == "sql_server" else None,
        "is_default": is_default,
        "is_active": True,
        "provision_state": state,
        "provision_error": None,
        "creation_time": None,
        "update_time": None,
    }


class ComputeEngineTests(unittest.TestCase):
    def test_sql_server_capabilities_match_supported_statistical_aggregates(self):
        aggregates = set(SqlServerCompute.capabilities()["aggregates"])
        self.assertTrue({"MEDIAN", "PERCENTILE", "VARIANCE", "STDDEV"} <= aggregates)

    def test_dialect_renderers_implement_interface_without_cross_inheritance(self):
        duckdb = DuckDbQueryRenderer()
        sql_server = SqlServerQueryRenderer()
        self.assertIsInstance(duckdb, QueryRenderer)
        self.assertIsInstance(sql_server, QueryRenderer)
        self.assertNotIn(DuckDbQueryRenderer, SqlServerQueryRenderer.__mro__)
        self.assertNotIn(SqlServerQueryRenderer, DuckDbQueryRenderer.__mro__)
        with self.assertRaises(TypeError):
            QueryRenderer()

    def test_runtime_user_validation(self):
        self.assertEqual(validate_runtime_user("dn_compute_01"), "dn_compute_01")
        for invalid in ("dbo", "ab", "1compute", "compute-user", "sys"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_runtime_user(invalid)

    def test_duckdb_preserves_empty_input_schema(self):
        engine = DuckDbCompute()
        try:
            engine.load("input", [], ["region", "amount"])
            query = QueryIR(
                source=QuerySource(entity="input", object_name="input", alias="i", source_instance="compute"),
                outputs=[QueryOutput(name="region", expression=ColumnExpr(source="i", name="region"))],
            )
            self.assertEqual(engine.run(query), [])
        finally:
            engine.close()

    def test_duckdb_executes_native_filtered_aggregate(self):
        engine = DuckDbCompute()
        try:
            engine.load("input", [{"amount": -5}, {"amount": 10}, {"amount": 20}])
            query = QueryIR(
                source=QuerySource(
                    entity="input", object_name="input", alias="i", source_instance="compute",
                ),
                outputs=[QueryOutput(
                    name="total",
                    aggregate=AggregateExpr(
                        function="SUM",
                        value=BinaryExpr(
                            operator="ADD",
                            left=ColumnExpr(source="i", name="amount"),
                            right=LiteralExpr(value=10),
                        ),
                        filter=ComparisonPredicate(
                            left=ColumnExpr(source="i", name="amount"),
                            operator="GT",
                            right=LiteralExpr(value=0),
                        ),
                    ),
                )],
            )
            self.assertEqual(engine.run(query), [{"total": 50}])
        finally:
            engine.close()

    def test_sql_server_renderer_uses_supported_dialect(self):
        query = QueryIR(
            source=QuerySource(entity="input", object_name="input", alias="i", source_instance="compute"),
            outputs=[QueryOutput(
                name="total",
                aggregate=AggregateExpr(function="SUM", value=ColumnExpr(source="i", name="amount")),
            )],
            order_by=[{"field": "total", "direction": "DESC", "nulls": "LAST"}],
            limit=5,
        )
        rendered = SqlServerQueryRenderer(
            table_source=lambda _: "[#runtime_input]"
        ).render(query)
        self.assertIn("SELECT TOP (5)", rendered.sql)
        self.assertIn("FROM [#runtime_input] [i]", rendered.sql)
        self.assertNotIn("NULLS LAST", rendered.sql)
        self.assertNotIn(" LIMIT ", rendered.sql)

    def test_renderers_use_engine_native_filtered_aggregate_and_parameter_order(self):
        value = BinaryExpr(
            operator="ADD",
            left=ColumnExpr(source="i", name="amount"),
            right=LiteralExpr(value=10),
        )
        predicate = ComparisonPredicate(
            left=ColumnExpr(source="i", name="amount"),
            operator="GT",
            right=LiteralExpr(value=0),
        )
        query = QueryIR(
            source=QuerySource(
                entity="input", object_name="input", alias="i", source_instance="compute",
            ),
            outputs=[QueryOutput(
                name="total",
                aggregate=AggregateExpr(function="SUM", value=value, filter=predicate),
            )],
            order_by=[{"field": "total", "direction": "DESC", "nulls": "LAST"}],
            limit=5,
        )

        duckdb = DuckDbQueryRenderer(table_source=lambda _: '"input"').render(query)
        sql_server = SqlServerQueryRenderer(
            table_source=lambda _: "[#input]"
        ).render(query)

        self.assertIn(" FILTER (WHERE ", duckdb.sql)
        self.assertIn(" LIMIT 5", duckdb.sql)
        self.assertNotIn("CASE WHEN", duckdb.sql)
        self.assertEqual(duckdb.params, [10, 0])

        self.assertIn("SUM(CASE WHEN", sql_server.sql)
        self.assertIn("SELECT TOP (5)", sql_server.sql)
        self.assertNotIn(" FILTER (WHERE ", sql_server.sql)
        self.assertEqual(sql_server.params, [0, 10])

    def test_sql_server_renderer_uses_grouped_percentile_window_path(self):
        query = QueryIR(
            source=QuerySource(
                entity="input", object_name="input", alias="i", source_instance="compute",
            ),
            dimensions=[QueryOutput(
                name="region",
                expression=ColumnExpr(source="i", name="region"),
            )],
            outputs=[
                QueryOutput(
                    name="median",
                    aggregate=AggregateExpr(
                        function="MEDIAN", value=ColumnExpr(source="i", name="amount"),
                    ),
                ),
                QueryOutput(
                    name="p75",
                    aggregate=AggregateExpr(
                        function="PERCENTILE", percentile=0.75,
                        value=ColumnExpr(source="i", name="amount"),
                    ),
                ),
                QueryOutput(
                    name="average",
                    aggregate=AggregateExpr(
                        function="AVG", value=ColumnExpr(source="i", name="amount"),
                    ),
                ),
            ],
        )
        rendered = SqlServerQueryRenderer(
            table_source=lambda _: "[#input]"
        ).render(query)
        self.assertIn("SELECT DISTINCT", rendered.sql)
        self.assertIn("PERCENTILE_CONT(?) WITHIN GROUP", rendered.sql)
        self.assertIn("OVER (PARTITION BY [i].[region])", rendered.sql)
        self.assertIn("AVG([i].[amount]) OVER (PARTITION BY [i].[region])", rendered.sql)
        self.assertNotIn(" GROUP BY ", rendered.sql)
        self.assertEqual(rendered.params, [0.5, 0.75])

    def test_optimizer_stamps_engine_and_rejects_unsupported_aggregate(self):
        source = QuerySource(entity="input", object_name="input", alias="i", source_instance="compute")
        fragment = ComputeFragment(
            id="p_compute", name="median", inputs=[ComputeInput(table="input", from_fragment="p_source")],
            query=QueryIR(
                source=source,
                outputs=[QueryOutput(
                    name="value",
                    aggregate=AggregateExpr(function="MEDIAN", value=ColumnExpr(source="i", name="amount")),
                )],
            ),
            depends_on=["p_source"],
        )
        plan = PhysicalExecutionPlan(nodes=[fragment])
        optimizer = object.__new__(Optimizer)
        optimizer.compute_engine_name = "sql-temp"
        optimizer.compute_engine_type = "sql_server"
        optimizer.compute_capabilities = {"aggregates": ["SUM", "COUNT", "AVG", "MIN", "MAX"]}
        with self.assertRaises(BindingError):
            optimizer._bind_compute_engine(plan)

        optimizer.compute_capabilities = SqlServerCompute.capabilities()
        optimizer._bind_compute_engine(plan)
        self.assertEqual(fragment.engine, "sql-temp")
        self.assertEqual(plan.context["compute_engine_type"], "sql_server")

    def test_calculate_only_plan_does_not_open_database_compute(self):
        plan = PhysicalExecutionPlan(nodes=[CapabilityFragment(
            id="p_calc",
            name="constant",
            operator=Operator.CALCULATE,
            resolver="(compute)",
            call={
                "node_id": "p_calc",
                "spec": {
                    "outputs": [{"name": "value", "expression": LiteralExpr(value=1).model_dump(mode="json")}],
                    "result": {
                        "kind": "TABLE", "name": "constant",
                        "fields": [{"name": "value", "data_type": "number", "role": "measure"}],
                    },
                },
                "input_refs": {},
            },
        )])
        ctx = ExecContext("constant")
        Coordinator(_ResolverRegistry(), _ComputeRegistryThatMustNotRun()).execute(plan, ctx)
        self.assertIsNone(ctx.compute)
        self.assertIsNone(ctx.physical_results["p_calc"].error)

    def test_registry_run_lease_is_balanced(self):
        db = _FakeComputeDb([_engine_row("duckdb-main", is_default=True)])
        registry = _RegistryWithDb(db)
        selected = registry.acquire()
        self.assertEqual(selected.engine_name, "duckdb-main")
        self.assertEqual(db.query_count, 1)
        self.assertEqual(registry._active_runs["duckdb-main"], 1)
        registry.release("duckdb-main")
        self.assertNotIn("duckdb-main", registry._active_runs)

    def test_registry_list_always_reads_current_database_rows(self):
        db = _FakeComputeDb([
            _engine_row("duckdb", is_default=True),
            _engine_row("removed-sql", "sql_server", state="delete_failed"),
        ])
        registry = _RegistryWithDb(db)
        self.assertEqual(
            [item["engine_name"] for item in registry.list()],
            ["duckdb", "removed-sql"],
        )

        db.rows = [_engine_row("duckdb", is_default=True)]

        self.assertEqual([item["engine_name"] for item in registry.list()], ["duckdb"])
        self.assertEqual(db.query_count, 2)

    def test_failed_sql_server_test_writes_no_metadata_row(self):
        db = Mock()
        db.execute_query.return_value = [{"c": 0}]
        registry = _RegistryWithDb(db)
        with patch.object(registry, "_sql_connection_config", return_value={}), \
             patch("nexus.engine.compute_registry.SqlServerComputeProvisioner") as provisioner_type:
            provisioner_type.return_value.create_and_test.side_effect = RuntimeError("test failed")
            with self.assertRaisesRegex(
                RuntimeError,
                "SQL Server 计算引擎连接与临时表验证失败.*test failed",
            ):
                registry.create_definition(
                    engine_name="sql-compute",
                    engine_type="sql_server",
                    credential_name="sql-credential",
                    runtime_user="runtime_user",
                    config={},
                    is_default=False,
                )
        db.execute_non_query.assert_not_called()

    def test_legacy_failed_row_delete_never_connects_target_database(self):
        db = Mock()
        db.execute_query.side_effect = [[{"c": 0}], [{"c": 1}]]
        registry = _RegistryWithDb(db)
        failed = ComputeEngineDefinition(
            engine_name="failed-sql",
            engine_type="sql_server",
            credential_name="sql-credential",
            runtime_user="runtime_user",
            provision_state="delete_failed",
        )
        with patch.object(registry, "_find_definition", return_value=failed), \
             patch("nexus.engine.compute_registry.SqlServerComputeProvisioner") as provisioner_type:
            self.assertTrue(registry.delete_definition("failed-sql"))
        provisioner_type.assert_not_called()
        self.assertIn("DELETE FROM", db.execute_non_query.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()
