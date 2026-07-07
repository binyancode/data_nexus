"""初始化器（Initializer）：一次运行的第一段引擎。

职责：为后续四段引擎**准备作用域本体**——按问题选定本体（用户显式指定优先，否则
让 LLM 在可见本体里路由），并校验可用。与 compiler / optimizer / coordinator /
generator 对等，是引擎的一段；选择/路由过程完整落 run_stage（供复盘）。

（将来这一段还会承担从知识库检索指标描述、示例等"备料"职责。）
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from nexus.core.models import ExecContext
from nexus.ontology.json_ontology import JsonOntology
from nexus.ontology.repository import OntologyRepository
from nexus.ontology.store import OntologyStore
from nexus.ontology.validator import ontology_resolver_names, validate_ontology
from utils.logger import get_logger

_logger = get_logger("nexus")


@dataclass
class Scope:
    """初始化器产物：本次运行的作用域上下文（编译器/优化器据此工作）。"""
    ontology_id: str
    name: str
    ontology: OntologyStore     # 命名空间化的作用域本体
    allowed: set                # 允许使用的 resolver 名集合
    available_ops: set          # 这些 resolver 支持的算子并集


class Initializer:
    def __init__(self, repo: OntologyRepository, registry):
        self.repo = repo
        self.registry = registry

    def run(self, ctx: ExecContext) -> Scope:
        """选定本体 + 校验 + 装配作用域上下文（供后四段引擎用），返回 Scope。
        出错抛异常（→ 失败的初始化器段，可查错因）。

        选择/路由信息写入 ctx.stage_logs：
        - selection: {mode: explicit|auto, ontology_id, name, [candidates]}
        - prompt:    LLM 路由提示词 {system, user}（仅 auto 且多候选时）
        """
        onto = self._select(ctx)
        problems = validate_ontology(onto, self.registry)
        if problems:
            raise ValueError("；".join(problems))
        ctx.ontology_id = onto.ontology_id
        ctx.recorder.set_run_ontology(ctx.run_id, onto.ontology_id)

        # 装配作用域：命名空间化本体 + 允许的 resolver 名 + 可用算子并集
        scoped = JsonOntology(onto.graph, ns=onto.ontology_id)
        allowed = ontology_resolver_names(onto.graph)
        available_ops: set = set()
        for n in allowed:
            r = self.registry.resolver(n)
            if r:
                available_ops |= set(getattr(r, "operators", set()))
        return Scope(onto.ontology_id, onto.name, scoped, allowed, available_ops)

    # 选定本体：显式指定优先，否则 LLM 在可见本体里路由。写 selection/prompt 到 stage_logs。
    def _select(self, ctx: ExecContext):
        req = ctx.requested_ontology_id
        if req:                                   # 用户显式选了 → 直接用，跳过 LLM
            onto = self.repo.get(req)
            if not onto or not self.repo.can_read(onto, ctx.as_user):
                raise ValueError(f"指定的本体不可用或无权访问：{req}")
            ctx.stage_logs["selection"] = {"mode": "explicit",
                                           "ontology_id": onto.ontology_id, "name": onto.name}
            return onto
        visible = self.repo.list_for_user(ctx.as_user)   # 没选 → LLM 路由
        picked, prompt, cand_ids = self._route(ctx.question, visible,
                                               self.registry.llm(ctx.llm_name))
        if prompt:
            ctx.stage_logs["prompt"] = prompt
        onto = self.repo.get(picked) if picked else None
        if onto is None:
            raise ValueError("找不到可用（或有权访问）的本体。")
        ctx.stage_logs["selection"] = {"mode": "auto", "ontology_id": onto.ontology_id,
                                       "name": onto.name, "candidates": cand_ids}
        return onto

    # 从候选本体里选一个（LLM 按 name + description 判断）。
    # 返回 (picked_id, prompt|None, candidate_ids)；无 LLM / 单候选时不调模型。
    def _route(self, question: str, ontologies: list, llm):
        candidates = list(ontologies)
        cand_ids = [o.ontology_id for o in candidates]
        if not candidates:
            return None, None, []
        if len(candidates) == 1 or llm is None:
            return candidates[0].ontology_id, None, cand_ids

        catalog = "\n".join(
            f"  - id={o.ontology_id}｜名称={o.name}｜说明={(o.description or '')[:300]}"
            for o in candidates
        )
        system = (
            "你是本体路由器。根据用户问题，从下面的本体清单里选唯一最合适的一个来回答，"
            "只输出 JSON：{\"ontology_id\":\"<id>\"}。\n# 本体清单\n" + catalog
        )
        prompt = {"system": system, "user": question}
        try:
            out = llm.complete(
                [{"role": "system", "content": system}, {"role": "user", "content": question}],
                schema={"type": "object"},
            )
            data = out if isinstance(out, dict) else json.loads(out)
            picked = data.get("ontology_id")
            if picked in cand_ids:
                return picked, prompt, cand_ids
        except Exception as exc:
            _logger.warning(f"ontology route failed: {exc}")
        return candidates[0].ontology_id, prompt, cand_ids
