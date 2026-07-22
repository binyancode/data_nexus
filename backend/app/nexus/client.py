"""NexusClient：装配本体 + 注册表 + 五段引擎，暴露 ask() 唯一入口。"""

from __future__ import annotations

import json
import threading
import time
import traceback
from typing import Callable, Optional

from nexus.core.run_log import get_run_recorder
from utils.logger import get_logger

from nexus.core.models import Answer, ExecContext
from nexus.ontology.repository import OntologyRepository
from nexus.registry import ResolverRegistry
from nexus.engine.initializer import Initializer
from nexus.engine.compiler import Compiler
from nexus.engine.optimizer import Optimizer
from nexus.engine.coordinator import Coordinator
from nexus.engine.generator import Generator
from nexus.engine.compute_registry import ComputeEngineRegistry
from nexus.core.relations import RelationContract

_logger = get_logger("nexus")


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _stage_logs_json(ctx: ExecContext) -> Optional[str]:
    """当前 stage 的自定义日志缓冲 → JSON（空则 None，不落列）。"""
    logs = getattr(ctx, "stage_logs", None)
    return _dumps(logs) if logs else None


class NexusClient:
    def __init__(self, config: dict = None):
        conf = config or {}
        onto_conf = conf.get("ontology", {}) if isinstance(conf, dict) else {}
        self._schema = onto_conf.get("schema", "nexus")

        self.repo = OntologyRepository(self._schema)
        self.registry = ResolverRegistry(onto_conf).load()
        self.compute_registry = ComputeEngineRegistry(self._schema)
        self.initializer = Initializer(self.repo, self.registry)
        self.coordinator = Coordinator(self.registry, self.compute_registry)
        self.generator = Generator()

    def start_ask(self, question: str, as_user: Optional[str] = None,
                  ontology_id: Optional[str] = None, run_id: Optional[str] = None,
                  llm_name: Optional[str] = None,
                  compute_engine_name: Optional[str] = None) -> str:
        """同步建 run 并返回 run_id，随后后台线程执行五段引擎：
        初始化器 → 编译器 → 优化器 → 协调器 → 生成器。

        本体选择（显式指定 or LLM 路由）+ 校验都在「初始化器」段内完成并完整落库；
        选不到/无效本体表现为失败的初始化器段（可查错因），不再做 run 前预检。

        start_run 在返回前完成落库，避免前端拿到 run_id 立即轮询时的「Run not found」时间窗。
        """
        ctx = ExecContext(question, as_user, run_id=run_id)
        ctx.llm_name = llm_name
        ctx.requested_ontology_id = ontology_id
        ctx.requested_compute_engine_name = compute_engine_name
        self._prepare_compute_engine(ctx)
        ctx.recorder = get_run_recorder()
        # 本体此时未知；先持久化请求/选中的计算引擎，初始化器随后合并 ontology_ids。
        try:
            ctx.recorder.start_run(ctx.run_id, question, as_user, _dumps(ctx.context))
            threading.Thread(target=self.ask, args=(ctx,), daemon=True).start()
        except Exception:
            self.compute_registry.release(ctx.compute_engine_name)
            ctx.compute_engine_lease = False
            raise
        return ctx.run_id

    def _prepare_compute_engine(self, ctx: ExecContext) -> None:
        if ctx.compute_engine_lease:
            return
        definition = self.compute_registry.acquire(
            ctx.requested_compute_engine_name or ctx.compute_engine_name
        )
        ctx.compute_engine_name = definition.engine_name
        ctx.compute_engine_type = definition.engine_type
        ctx.compute_engine_lease = True
        ctx.context.update({
            "compute_engine_requested": ctx.requested_compute_engine_name,
            "compute_engine_selected": definition.engine_name,
            "compute_engine_type": definition.engine_type,
        })

    def ask(self, ctx: ExecContext) -> Answer:
        question = ctx.question
        rec = ctx.recorder
        run_state, answer = "done", None
        try:
            self._prepare_compute_engine(ctx)
            scope = self._stage(ctx, "initializer",
                                lambda: self.initializer.run(ctx),
                                _dumps({"question": question,
                                        "requested_ontology_id": ctx.requested_ontology_id}),
                                lambda s: _dumps({"ontology_ids": s.ontology_ids, "names": s.names,
                                                  "selection": ctx.stage_logs.get("selection")}))
            sqg = self._stage(ctx, "compiler",
                              lambda: Compiler(scope.ontology, self.registry.llm(ctx.llm_name),
                                               scope.available_ops,
                                               dict(zip(scope.ontology_ids, scope.names))).compile(question, ctx),
                              _dumps({"question": question, "ontology_ids": ctx.ontology_ids}),
                              lambda r: r.model_dump_json())
            plan = self._stage(ctx, "optimizer",
                               lambda: Optimizer(
                                   scope.ontology, self.registry, scope.allowed,
                                   compute_engine_name=ctx.compute_engine_name or "duckdb",
                                   compute_engine_type=ctx.compute_engine_type or "duckdb",
                                   compute_capabilities=self.compute_registry.capabilities(
                                       ctx.compute_engine_name
                                   ),
                               ).plan(sqg, ctx),
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
            try:
                rec.finish_run(ctx.run_id, run_state,
                               (answer.model_dump_json() if answer else None), ctx.cost_ms)
            finally:
                if ctx.compute_engine_lease:
                    self.compute_registry.release(ctx.compute_engine_name)
                    ctx.compute_engine_lease = False

        if answer is None:
            answer = Answer(run_id=ctx.run_id, question=question,
                            text="执行失败。", status="error")
        return answer

    # ── 单段引擎执行 + 记录（start/finish stage）──
    def _stage(self, ctx: ExecContext, stage: str, fn: Callable,
               input_json: Optional[str], out_ser: Callable) -> object:
        rec = ctx.recorder
        t0 = time.time()
        ctx.stage_logs = {}                       # 每段前清空自定义日志缓冲
        rec.start_stage(ctx.run_id, stage, input_json)
        try:
            result = fn()
        except Exception:
            rec.finish_stage(ctx.run_id, stage, "failed", None,
                             traceback.format_exc(), int((time.time() - t0) * 1000),
                             _stage_logs_json(ctx))
            raise
        rec.finish_stage(ctx.run_id, stage, "done", out_ser(result), None,
                         int((time.time() - t0) * 1000), _stage_logs_json(ctx))
        return result

    # ── 本体管理（供 API 层）──
    def list_ontologies(self, user: Optional[str]) -> list:
        return self.repo.list_for_user(user)

    def get_ontology(self, ontology_id: str, user: Optional[str]):
        onto = self.repo.get(ontology_id)
        if not onto or not self.repo.can_read(onto, user):
            return None
        return onto

    def create_ontology(self, name: str, owner: str, description: str = None):
        return self.repo.create(name, owner, description)

    def _owned(self, ontology_id: str, user: Optional[str]):
        onto = self.repo.get(ontology_id)
        if not onto or not user or onto.owner != user:
            return None
        return onto

    def save_ontology(self, ontology_id: str, user: str, name: str,
                      description: Optional[str], graph: dict) -> bool:
        if not self._owned(ontology_id, user):
            return False
        if graph.get("version") != 3:
            return False
        for relation in graph.get("relations", []) or []:
            RelationContract.model_validate(relation)
            confirmation = relation.get("confirmation") or {}
            if confirmation.get("required") and not confirmation.get("confirmed"):
                return False
        self.repo.save(ontology_id, name, description, graph)
        return True

    def publish_ontology(self, ontology_id: str, user: str,
                         visibility: str, grants: list) -> bool:
        if not self._owned(ontology_id, user):
            return False
        self.repo.publish(ontology_id, visibility, grants or [])
        return True

    def delete_ontology(self, ontology_id: str, user: str) -> bool:
        if not self._owned(ontology_id, user):
            return False
        self.repo.delete(ontology_id)
        return True

    # ── 数据源探测 / 导入 ──
    def list_resolvers(self) -> list:
        return [r.capabilities() for r in self.registry.all_resolvers()]

    def list_llms(self) -> list:
        """规划用 LLM 目录（name + is_default），供提问界面下拉。"""
        return self.registry.list_llms()

    def reload_registry(self) -> dict:
        """从 DB 重新装配 resolver / llm / compute engine。"""
        self.registry.reload()
        return {
            "resolvers": len(self.registry.all_resolvers()),
            "llms": len(self.registry.list_llms()),
            "compute_engines": len(self.compute_registry.list()),
        }

    def resolver_schema(self, name: str) -> Optional[dict]:
        r = self.registry.resolver(name)
        if r is None or not hasattr(r, "describe"):
            return None
        return {"tables": r.describe()}

    def import_preview(self, resolver_name: str, tables: list) -> Optional[dict]:
        from nexus.ontology.importer import build_fragment
        r = self.registry.resolver(resolver_name)
        if r is None or not hasattr(r, "describe"):
            return None
        return build_fragment(resolver_name, r.describe(), r.primary_keys(),
                              r.foreign_keys(), tables)
