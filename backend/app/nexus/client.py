"""NexusClient：装配本体 + 注册表 + 四段引擎，暴露 ask() 唯一入口。"""

from __future__ import annotations

import json
from typing import Optional

from services.sql_db import sql_db
from core.services import services
from utils.logger import get_logger

from nexus.core.models import Answer, ExecContext
from nexus.ontology.azure_sql import AzureSqlOntologyStore
from nexus.registry import ResolverRegistry
from nexus.engine.compiler import Compiler
from nexus.engine.optimizer import Optimizer
from nexus.engine.coordinator import Coordinator
from nexus.engine.generator import Generator

_logger = get_logger("nexus")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


class NexusClient:
    def __init__(self, config: dict = None):
        conf = config or {}
        onto_conf = conf.get("ontology", {}) if isinstance(conf, dict) else {}
        self._schema = onto_conf.get("schema", "nexus")

        self.ontology = AzureSqlOntologyStore(onto_conf)
        self.registry = ResolverRegistry(onto_conf).load()
        self.compiler = Compiler(self.ontology, self.registry.llm())
        self.optimizer = Optimizer(self.ontology)
        self.coordinator = Coordinator(self.registry)
        self.generator = Generator()

    def ask(self, question: str, as_user: Optional[str] = None) -> Answer:
        ctx = ExecContext(question, as_user)
        sqg = self.compiler.compile(question, ctx)
        plan = self.optimizer.plan(sqg, ctx)
        self.coordinator.execute(plan, ctx)
        answer = self.generator.generate(sqg, plan, ctx)
        try:
            self._persist(ctx, sqg, plan, answer)
        except Exception as exc:
            _logger.warning(f"persist run failed: {exc}")
        return answer

    def _persist(self, ctx: ExecContext, sqg, plan, answer: Answer) -> None:
        db = services[sql_db]
        db.execute_non_query(
            f"""INSERT INTO {self._schema}.runs
                (run_id, as_user, question, sqg, [plan], result, status, cost_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ctx.run_id, ctx.as_user, ctx.question,
                sqg.model_dump_json(), plan.model_dump_json(),
                answer.model_dump_json(), answer.status, ctx.cost_ms,
            ),
        )
        for node_id, res in ctx.results.items():
            db.execute_non_query(
                f"""INSERT INTO {self._schema}.run_steps
                    (run_id, node_id, resolver, [call], [output], trust, verdict)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ctx.run_id, node_id, res.resolver, res.detail,
                    _dumps(res.rows), res.trust, res.error,
                ),
            )
