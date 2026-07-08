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
from nexus.ontology.merged import MergedOntology
from nexus.ontology.repository import OntologyRepository
from nexus.ontology.store import OntologyStore
from nexus.ontology.validator import ontology_resolver_names, validate_ontology
from utils.logger import get_logger

_logger = get_logger("nexus")

# 自动路由时最多选中的本体数（防下游提示词膨胀）
_MAX_ONTOLOGIES = 4


@dataclass
class Scope:
    """初始化器产物：本次运行的作用域上下文（编译器/优化器据此工作）。"""
    ontology_ids: list          # 选中的本体 id（≥1）
    names: list                 # 对应名称
    ontology: OntologyStore     # 作用域本体（多本体时为 MergedOntology，单个时即该本体）
    allowed: set                # 允许使用的 resolver 名集合（并集）
    available_ops: set          # 这些 resolver 支持的算子并集


class Initializer:
    def __init__(self, repo: OntologyRepository, registry):
        self.repo = repo
        self.registry = registry

    def run(self, ctx: ExecContext) -> Scope:
        """选定本体（可多个）+ 校验 + 装配合并作用域，返回 Scope。
        出错抛异常（→ 失败的初始化器段，可查错因）。

        选择/路由信息写入 ctx.stage_logs：
        - selection: {mode: explicit|auto, ontology_ids, names, [candidates]}
        - prompt:    LLM 路由提示词 {system, user}（仅 auto 且多候选时）
        运行上下文（本体集合）写入 nexus.run.context = {"ontology_ids": [...]}。
        """
        ontos = self._select(ctx)                 # list[Ontology]，非空
        # 逐个校验：无效的丢弃并继续，全无效才报错
        valid, problems = [], []
        for o in ontos:
            probs = validate_ontology(o, self.registry)
            (problems.append(f"{o.name}：" + "；".join(probs)) if probs else valid.append(o))
        if not valid:
            raise ValueError("；".join(problems) or "找不到可用的本体。")

        ctx.ontology_ids = [o.ontology_id for o in valid]
        ctx.recorder.set_run_context(
            ctx.run_id, json.dumps({"ontology_ids": ctx.ontology_ids}, ensure_ascii=False))

        # 装配合并作用域：每本体命名空间化 → 合并；allowed / available_ops 取并集
        subs = [JsonOntology(o.graph, ns=o.ontology_id) for o in valid]
        ontology = subs[0] if len(subs) == 1 else MergedOntology(subs)
        allowed: set = set()
        available_ops: set = set()
        for o in valid:
            names = ontology_resolver_names(o.graph)
            allowed |= names
            for n in names:
                r = self.registry.resolver(n)
                if r:
                    available_ops |= set(getattr(r, "operators", set()))
        return Scope([o.ontology_id for o in valid], [o.name for o in valid],
                     ontology, allowed, available_ops)

    # 选定本体：显式指定优先（单个），否则 LLM 在可见本体里路由（可多个）。写 selection/prompt。
    def _select(self, ctx: ExecContext) -> list:
        req = ctx.requested_ontology_id
        if req:                                   # 用户显式选了 → 直接用，跳过 LLM
            onto = self.repo.get(req)
            if not onto or not self.repo.can_read(onto, ctx.as_user):
                raise ValueError(f"指定的本体不可用或无权访问：{req}")
            ctx.stage_logs["selection"] = {"mode": "explicit",
                                           "ontology_ids": [onto.ontology_id], "names": [onto.name]}
            return [onto]
        visible = self.repo.list_for_user(ctx.as_user)   # 没选 → LLM 路由（一组）
        picked_ids, prompt, cand_ids = self._route(ctx.question, visible,
                                                   self.registry.llm(ctx.llm_name))
        if prompt:
            ctx.stage_logs["prompt"] = prompt
        ontos = []
        for pid in picked_ids:
            o = self.repo.get(pid)
            if o and self.repo.can_read(o, ctx.as_user):
                ontos.append(o)
        if not ontos:
            raise ValueError("找不到可用（或有权访问）的本体。")
        ctx.stage_logs["selection"] = {"mode": "auto",
                                       "ontology_ids": [o.ontology_id for o in ontos],
                                       "names": [o.name for o in ontos], "candidates": cand_ids}
        return ontos

    # 从候选本体里选出所有相关的（LLM 按 name + description 判断，可多选）。
    # 返回 (picked_ids: list, prompt|None, candidate_ids)；无 LLM / 单候选时不调模型。
    def _route(self, question: str, ontologies: list, llm):
        candidates = list(ontologies)
        cand_ids = [o.ontology_id for o in candidates]
        if not candidates:
            return [], None, []
        if len(candidates) == 1 or llm is None:
            return [candidates[0].ontology_id], None, cand_ids

        catalog = "\n".join(
            f"  - id={o.ontology_id}｜名称={o.name}｜说明={(o.description or '')[:300]}"
            for o in candidates
        )
        system = (
            "你是本体路由器。根据用户问题，从下面的本体清单里选出**所有**相关的本体来回答"
            "（问题跨多个领域时可多选；只选真正相关的、无关的不选），按相关度从高到低排序，"
            "只输出 JSON：{\"ontology_ids\":[\"<id>\",...]}。\n# 本体清单\n" + catalog
        )
        prompt = {"system": system, "user": question}
        try:
            out = llm.complete(
                [{"role": "system", "content": system}, {"role": "user", "content": question}],
                schema={"type": "object"},
            )
            data = out if isinstance(out, dict) else json.loads(out)
            picked = [i for i in (data.get("ontology_ids") or []) if i in cand_ids]
            if picked:
                return picked[:_MAX_ONTOLOGIES], prompt, cand_ids
        except Exception as exc:
            _logger.warning(f"ontology route failed: {exc}")
        return [candidates[0].ontology_id], prompt, cand_ids   # 兜底：最近更新的一个
