"""编译器：自然语言 → SQG（逻辑语义查询图，可含多层依赖的 DAG）。

流程：
  1. 把本体结构（实体+其属性、指标+口径表达式、分析能力、动作）序列化成目录喂给 LLM。
  2. LLM 依据本体，受约束生成 SQG 的 nodes（带 operator + depends_on），过滤条件直接给属性 concept id。
  3. 轻校验后组装成 SQGNode。

全部由 LLM 依据本体生成——不在此处做正则/角色映射等硬编码解析。
"""

from __future__ import annotations

import json
from typing import Optional

from nexus.core.models import SQG, SQGNode, Operator, ConceptKind, ExecContext

_ALLOWED_OPS = {"AGGREGATE", "ASK", "ACT", "SELECT", "FILTER", "JOIN"}


class Compiler:
    def __init__(self, ontology, llm=None, available_ops=None):
        self.ontology = ontology
        self.llm = llm
        # 本体可用算子集（来自所挂 resolver 的能力并集）；None = 不限制（兼容/测试）
        self.available_ops = set(available_ops) if available_ops is not None else None

    def _op_available(self, op: str) -> bool:
        return self.available_ops is None or op in self.available_ops

    def compile(self, question: str, ctx: Optional[ExecContext] = None) -> SQG:
        if self.llm is None:
            return SQG(question=question, nodes=[], context={"error": "no llm configured"})
        try:
            return self._compile_llm(question, ctx)
        except Exception as exc:
            return SQG(question=question, nodes=[], context={"error": f"compile failed: {exc}"})

    def _compile_llm(self, question: str, ctx: Optional[ExecContext] = None) -> SQG:
        concepts = self.ontology.list_concepts()
        entities = [c for c in concepts if c.kind == ConceptKind.entity]
        attributes = [c for c in concepts if c.kind == ConceptKind.attribute]
        metrics = [c for c in concepts if c.kind == ConceptKind.metric]
        derivations = [c for c in concepts if c.kind == ConceptKind.derivation]
        actions = [c for c in concepts if c.kind == ConceptKind.action]
        # 临时聚合让 metric 变可选：只要有实体（带度量属性）即可取数；空本体才拒绝
        if not entities and not metrics:
            return SQG(question=question, nodes=[], context={"error": "ontology has no entities or metrics"})

        # 按实体列出维度 / 度量（带粗类型 dtype、度量带可加性 additivity）
        attrs_by_entity: dict[str, list] = {}
        for a in attributes:
            attrs_by_entity.setdefault(a.attrs.get("entity"), []).append(a)

        def attr_desc(a) -> str:
            syn = ("/" + "/".join(a.synonyms)) if a.synonyms else ""
            dt = a.attrs.get("dtype") or "?"
            desc = f"·描述={a.semantics}" if a.semantics else ""
            if a.attrs.get("role") == "measure":
                add = a.attrs.get("additivity") or "additive"
                return f"{a.id}（{a.name}{syn}·{dt}·可加性={add}{desc}）"
            return f"{a.id}（{a.name}{syn}·{dt}{desc}）"

        def ent_block(e) -> str:
            al = attrs_by_entity.get(e.id, [])
            dims = [a for a in al if a.attrs.get("role") != "measure"]
            meas = [a for a in al if a.attrs.get("role") == "measure"]
            dim_s = "、".join(attr_desc(a) for a in dims) or "（无）"
            mea_s = "、".join(attr_desc(a) for a in meas) or "（无）"
            return f"  - {e.id}（{e.name}）\n      维度: {dim_s}\n      度量: {mea_s}"

        entity_lines = "\n".join(ent_block(e) for e in entities) or "  （无）"

        metric_lines = "\n".join(
            f"  - id={m.id}｜名称={m.name}｜同义词={list(m.synonyms)}｜口径表达式={(m.attrs or {}).get('expr', '')}"
            for m in metrics
        )
        deriv_lines = "\n".join(
            f"  - id={d.id}｜名称={d.name}｜说明={d.semantics or ''}" for d in derivations
        ) or "  （无）"
        action_lines = "\n".join(
            f"  - id={a.id}｜名称={a.name}｜说明={a.semantics or ''}" for a in actions
        ) or "  （无）"

        # 按本体可用算子裁剪：挂了 agent 即可 ASK、挂了 action 即可 ACT；
        # 派生/动作概念是"可选的具名模板"，没有也能用自由 prompt 的 ASK。
        has_ask = self._op_available("ASK")
        has_act = self._op_available("ACT")

        op_lines = ["- AGGREGATE：对某个度量取一个数或分组取一组数。既可用预定义指标(metric)，也可临时对某个度量列聚合。"]
        if has_ask:
            op_lines.append("- ASK：把上游若干节点的数值交给分析 Agent，做对比 / 归因 / 解释，产出一段结论文字。")
        if has_act:
            op_lines.append("- ACT：执行一个动作（如建复盘任务），通常依赖某个 ASK 的结论。")

        metrics_hint = "# 可用指标（AGGREGATE 首选：concept 填指标 id，走预定义口径）" if metrics \
            else "# 可用指标：（无，请用「临时聚合」直接对度量列计算）"
        cap_lines = [
            "# 实体的维度与度量（filters 从维度或度量选；group_by 只用维度；临时聚合的 measure 只用度量）",
            entity_lines,
            metrics_hint, metric_lines or "  （无）",
        ]
        if has_ask and derivations:
            cap_lines += ["# 可选的具名分析能力（ASK 的 concept 可从这里选；也可不选，用自由 prompt）", deriv_lines]
        if has_act and actions:
            cap_lines += ["# 可选的具名动作（ACT 的 concept 可从这里选；也可不选）", action_lines]

        ex_nodes = [
            '  {"id":"n1","operator":"AGGREGATE","name":"华东2024Q1毛利","concept":"<指标id>","params":{"filters":[{"concept":"<维度attribute id>","op":"=","value":"华东"},{"concept":"<维度attribute id>","op":"=","value":"2024Q1"}]},"depends_on":[]}',
            '  {"id":"n2","operator":"AGGREGATE","name":"订单数量总和(临时聚合)","concept":null,"params":{"measure":"<度量attribute id>","agg":"SUM","filters":[]},"depends_on":[]}',
            '  {"id":"n3","operator":"AGGREGATE","name":"订单数量前三的产品","concept":null,"params":{"measure":"<度量attribute id>","agg":"SUM","group_by":"<维度attribute id>","order":"desc","limit":3},"depends_on":[]}',
            '  {"id":"n4","operator":"AGGREGATE","name":"总销量超1000的产品","concept":null,"params":{"measure":"<度量attribute id>","agg":"SUM","group_by":"<维度attribute id>","having":{"op":">","value":1000},"order":"desc"},"depends_on":[]}',
            '  {"id":"n5","operator":"AGGREGATE","name":"2024年7月销售额","concept":null,"params":{"measure":"<度量attribute id>","agg":"SUM","filters":[{"concept":"<date类型attribute id>","op":">=","value":"2024-07-01","value_format":"yyyy-MM-dd"},{"concept":"<date类型attribute id>","op":"<","value":"2024-08-01","value_format":"yyyy-MM-dd"}]},"depends_on":[]}',
        ]
        if has_ask:
            ex_nodes.append('  {"id":"n6","operator":"ASK","name":"结果分析","concept":null,"params":{"prompt":"以下是查询结果：{n3}。请用中文分析并给出简明结论。"},"depends_on":["n3"]}')
        if has_act:
            ex_nodes.append('  {"id":"n7","operator":"ACT","name":"建复盘任务","concept":null,"params":{"desc":"复盘：{n6}","assignee":"华东"},"depends_on":["n6"]}')

        rules = [
            "- 每个要对比/分析的数值都拆成**独立的 AGGREGATE 节点**，不要把多个地区或多个指标塞进一个节点。",
            "- AGGREGATE 取数二选一：①有合适的预定义指标 → concept 填指标 id；②没有 → 用「临时聚合」：concept=null，params 给 measure（某个**度量** attribute id）+ agg（SUM/AVG/MIN/MAX/COUNT）。",
            "- 聚合函数受**可加性**约束：additive 可 SUM/AVG/MIN/MAX；semi_additive 跨时间维度别 SUM（用 AVG 或不按时间分组）；non_additive（比率/百分比/单价）**禁 SUM**，用 AVG 或直接取。SUM/AVG 只能用于 number 类型的度量。",
            "- filters：维度和度量都可过滤，元素为 {concept, op, value}；op ∈ = != > >= < <= like in（默认 =）；维度常用等值，度量常用比较（如 amount > 1000）。in 的 value 是数组。",
            "- group_by 只能用**维度** attribute id；排名/TopN 用 group_by + order(desc/asc) + limit。",
            "- 聚合后过滤（HAVING，如「总销量超1000的产品」）：在该 AGGREGATE 节点 params 加 having:{op,value}，作用在聚合值上，配合 group_by。",
            "- 日期(date 类型)属性的期间过滤必须用**区间**表达，不要拿日期列等于一个「年/月/季」字符串（那样没有意义）。某月/季/年 = 该期间起始日(含)到下一期间起始日(不含)，用两个过滤：{op:'>=',value:'2024-07-01'} 和 {op:'<',value:'2024-08-01'}（如2024年7月）。",
            "- 每个 date 类型的过滤都要带 value_format 字段说明 value 的格式（用完整日期 'yyyy-MM-dd'）。文本型维度用等值、不需要 value_format。",
            "- 属性若带「描述」，按描述理解其含义与**取值格式**（如字符串型期间列的格式），过滤 value 按该格式生成，不要臆造。",
        ]
        if has_ask:
            rules.append("- 只要用户意图含「分析/为什么/对比/归因/解读」等，就**必须**加一个 ASK 节点：depends_on 指向相关 AGGREGATE，params.prompt 用 {nX} 回填上游结果并要求给出结论；concept 可选（有具名分析能力就填其 id，否则用 null）。")
        if has_act:
            rules.append("- 用户要求「建任务/派单/执行」时加 ACT 节点：params.desc 用 {nX} 引用上游结论，depends_on 指向它；concept 可选。")
        chain = "取数(AGGREGATE)"
        if has_ask:
            chain += " → 分析(ASK)"
        if has_act:
            chain += " → 行动(ACT)"
        rules.append(f"- concept（指标/维度/度量）必须是上面清单里的 id。只用问题真正需要的节点；形成「{chain}」的依赖链。")
        rules.append("- id 用 n1,n2,... 顺序编号。只输出 JSON，不要多余文字。")

        # 强意图拆解指令：多意图问题必须逐句建节点，别漏 ASK/ACT
        intent_hints = []
        if has_ask:
            intent_hints.append("「分析 / 为什么 / 对比 / 归因 / 解读 / 说明」→ 必须建 ASK 节点")
        if has_act:
            intent_hints.append("「建任务 / 派单 / 复盘 / 执行 / 通知」→ 必须建 ACT 节点")
        intent_block = ""
        if intent_hints:
            intent_block = (
                "# 先拆解意图（最重要）\n"
                "把用户问题拆成若干**独立子意图**，为每个子意图各建一个节点，一个都不能漏。常见映射：\n"
                "  - 「取数 / 多少 / 排名 / 对比数值」→ AGGREGATE 节点\n  - "
                + "\n  - ".join(intent_hints)
                + "\n一个问题往往是「取数 → 分析 → 行动」的组合；只要句子里出现分析或行动的意图，就**一定**要有对应的 ASK / ACT 节点，不要只生成取数节点。\n\n"
            )

        system = (
            "你是 Data Nexus 的查询编译器。把用户问题编译成「语义查询图 SQG」——一个带依赖的有向无环图(DAG)，只输出 JSON。\n\n"
            + intent_block
            + "# 算子（operator）\n" + "\n".join(op_lines) + "\n\n"
            + "\n".join(cap_lines) + "\n\n"
            + "# 输出 JSON 格式\n{\"nodes\": [\n" + ",\n".join(ex_nodes) + "\n]}\n\n"
            + "# 规则（重要）\n" + "\n".join(rules)
        )

        out = self.llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": question}],
            schema={"type": "object"},
        )
        # 记录本次编译的完整提示词（落 run_stage.logs，供排查）
        if ctx is not None:
            ctx.stage_logs["prompt"] = {"system": system, "user": question}
        data = out if isinstance(out, dict) else json.loads(out)
        return self._build_sqg(question, data)

    # ── 把 LLM 的 JSON 组装成 SQG（轻校验，不做业务重写）──
    def _build_sqg(self, question: str, data: dict) -> SQG:
        raw_nodes = data.get("nodes") or []
        ids = {n.get("id") for n in raw_nodes if n.get("id")}
        nodes: list[SQGNode] = []
        for rn in raw_nodes:
            nid = rn.get("id")
            op = (rn.get("operator") or "").upper()
            if not nid or op not in _ALLOWED_OPS:
                continue
            # 本体无对应能力时，丢弃该算子节点（安全网，防 LLM 越权生成）
            if op in ("ASK", "ACT") and not self._op_available(op):
                continue
            params = dict(rn.get("params") or {})
            if op == "AGGREGATE":
                params["filters"] = self._clean_filters(params.get("filters"))
            depends_on = [d for d in (rn.get("depends_on") or []) if d in ids and d != nid]
            nodes.append(SQGNode(
                id=nid,
                operator=Operator[op],
                name=rn.get("name") or nid,
                concept=rn.get("concept"),
                params=params,
                depends_on=depends_on,
            ))
        context = {"intent": data.get("intent") or "auto", "generated_by": "llm"}
        return SQG(question=question, nodes=nodes, context=context)

    def _clean_filters(self, filters) -> list[dict]:
        """只保留指向真实属性 concept 的过滤，保留操作符 op（默认 =）。不做角色映射/跨实体改写。"""
        out: list[dict] = []
        items = filters if isinstance(filters, list) else []
        for f in items:
            if not isinstance(f, dict):
                continue
            cid, value = f.get("concept"), f.get("value")
            op = f.get("op") or "="
            # in 允许 value 为数组；其余空值丢弃
            empty = (value in (None, "")) and not (op == "in" and isinstance(value, list) and value)
            if not cid or empty:
                continue
            c = self.ontology.get_concept(cid)
            if c and c.kind == ConceptKind.attribute:
                item = {"concept": cid, "op": op, "value": value}
                if f.get("value_format"):
                    item["value_format"] = f["value_format"]
                out.append(item)
        return out
