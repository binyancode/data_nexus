"""NexusClient —— SDK 唯一入口门面。

把「知识层（本体）+ 能力层（Resolver）+ 运行引擎（四段）」组装起来，
对外只暴露一句 ask()。既可被 FastAPI 层调用，也可被其他程序直接 import。

    from nexus import NexusClient
    nexus = NexusClient(config)
    nexus.register_resolver(SqlResolver("dwh.sql", {...}))
    answer = await nexus.ask("华东上季度毛利为什么下滑？", as_user="zhangsan@beone")
"""
from typing import Any, AsyncIterator, Optional

from nexus.core.context import ExecContext
from nexus.engine.compiler import Compiler
from nexus.engine.coordinator import Coordinator
from nexus.engine.dispatcher import Dispatcher
from nexus.engine.generator import Answer, Generator
from nexus.ontology.store import OntologyStore, SqliteOntologyStore
from nexus.registry import ResolverRegistry
from nexus.resolvers.base import Resolver


class NexusClient:
    def __init__(self, config: Optional[dict[str, Any]] = None):
        config = config or {}
        self.config = config

        # 知识层
        onto_cfg = config.get("ontology", {})
        self.ontology: OntologyStore = SqliteOntologyStore(
            path=onto_cfg.get("path", "nexus_ontology.db")
        )

        # 能力层
        self.registry = ResolverRegistry()

        # 运行引擎四段
        llm = config.get("llm")
        self.compiler = Compiler(self.ontology, llm=llm)
        self.dispatcher = Dispatcher(self.ontology, self.registry)
        self.coordinator = Coordinator(self.registry)
        self.generator = Generator(llm=llm)

    # ── 能力层管理 ──
    def register_resolver(self, resolver: Resolver) -> None:
        self.registry.register(resolver)

    def list_resolvers(self) -> list[dict]:
        return [r.capabilities().model_dump() for r in self.registry.all()]

    # ── 主流水线 ──
    async def ask(
        self,
        q: str,
        as_user: Optional[str] = None,
        history: Optional[list] = None,
    ) -> Answer:
        """提问 → 编译 → 调度 → 协调 → 生成 → 答案。"""
        sqg = await self.compiler.compile(q, as_user=as_user, history=history)
        plan = self.dispatcher.dispatch(sqg)
        ctx = ExecContext(user=as_user)
        merged, verdict = await self.coordinator.coordinate(plan, ctx)
        return await self.generator.generate(merged, verdict)

    async def ask_stream(
        self,
        q: str,
        as_user: Optional[str] = None,
        history: Optional[list] = None,
    ) -> AsyncIterator[str]:
        """流式版 ask（供 SSE）。"""
        sqg = await self.compiler.compile(q, as_user=as_user, history=history)
        plan = self.dispatcher.dispatch(sqg)
        ctx = ExecContext(user=as_user)
        merged, verdict = await self.coordinator.coordinate(plan, ctx)
        async for chunk in self.generator.stream(merged, verdict):
            yield chunk
