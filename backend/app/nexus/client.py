"""NexusClient：装配本体 + 注册表 + 四段引擎，暴露 ask() 唯一入口。"""

from __future__ import annotations

import json
import time
import traceback
from typing import Callable, Optional

from nexus.core.run_log import get_run_recorder
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
        ctx.recorder = get_run_recorder()
        rec = ctx.recorder
        rec.start_run(ctx.run_id, question, as_user)

        run_state, answer = "done", None
        try:
            sqg = self._stage(ctx, "compiler",
                              lambda: self.compiler.compile(question, ctx),
                              _dumps({"question": question}),
                              lambda r: r.model_dump_json())
            plan = self._stage(ctx, "optimizer",
                               lambda: self.optimizer.plan(sqg, ctx),
                               sqg.model_dump_json(),
                               lambda r: r.model_dump_json())        # ← 前端画 flow 的结构来源
            self._stage(ctx, "coordinator",
                        lambda: self.coordinator.execute(plan, ctx),
                        plan.model_dump_json(),
                        lambda r: _dumps({k: v.model_dump() for k, v in r.items()}))
            answer = self._stage(ctx, "generator",
                                 lambda: self.generator.generate(sqg, plan, ctx),
                                 None,
                                 lambda r: r.model_dump_json())
        except Exception:
            run_state = "failed"
            _logger.warning(f"run {ctx.run_id} failed:\n{traceback.format_exc()}")
        finally:
            rec.finish_run(ctx.run_id, run_state,
                           (answer.model_dump_json() if answer else None), ctx.cost_ms)

        if answer is None:
            answer = Answer(run_id=ctx.run_id, question=question,
                            text="执行失败。", status="error")
        return answer

    # ── 单段引擎执行 + 记录（start/finish stage）──
    def _stage(self, ctx: ExecContext, stage: str, fn: Callable,
               input_json: Optional[str], out_ser: Callable) -> object:
        rec = ctx.recorder
        t0 = time.time()
        rec.start_stage(ctx.run_id, stage, input_json)
        try:
            result = fn()
        except Exception:
            rec.finish_stage(ctx.run_id, stage, "failed", None,
                             traceback.format_exc(), int((time.time() - t0) * 1000))
            raise
        rec.finish_stage(ctx.run_id, stage, "done", out_ser(result), None,
                         int((time.time() - t0) * 1000))
        return result
