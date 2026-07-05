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
    def __init__(self, ontology, llm=None):
        self.ontology = ontology
        self.llm = llm

    def compile(self, question: str, ctx: Optional[ExecContext] = None) -> SQG:
        if self.llm is None:
            return SQG(question=question, nodes=[], context={"error": "no llm configured"})
        try:
            return self._compile_llm(question)
        except Exception as exc:
            return SQG(question=question, nodes=[], context={"error": f"compile failed: {exc}"})

    def _compile_llm(self, question: str) -> SQG:
        concepts = self.ontology.list_concepts()
        entities = [c for c in concepts if c.kind == ConceptKind.entity]
        attributes = [c for c in concepts if c.kind == ConceptKind.attribute]
        metrics = [c for c in concepts if c.kind == ConceptKind.metric]
        derivations = [c for c in concepts if c.kind == ConceptKind.derivation]
        actions = [c for c in concepts if c.kind == ConceptKind.action]
        if not metrics:
            return SQG(question=question, nodes=[], context={"error": "no metrics in ontology"})

        # 按实体列出其可过滤属性（有 role 的），供 LLM 直接选 concept id
        attrs_by_entity: dict[str, list] = {}
        for a in attributes:
            attrs_by_entity.setdefault(a.attrs.get("entity"), []).append(a)

        def attr_desc(a) -> str:
            syn = ("/" + "/".join(a.synonyms)) if a.synonyms else ""
            return f"{a.id}（{a.name}{syn}）"

        entity_lines = "\n".join(
            f"  - {e.id}（{e.name}）可过滤属性: "
            + ("、".join(attr_desc(a) for a in attrs_by_entity.get(e.id, []) if a.attrs.get("role")) or "（无）")
            for e in entities
        ) or "  （无）"

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

        system = f"""你是 Data Nexus 的查询编译器。把用户问题编译成「语义查询图 SQG」——一个带依赖的有向无环图(DAG)，只输出 JSON。

# 算子（operator）
- AGGREGATE：对某个指标按过滤条件取一个数（如「华东 2024Q1 的毛利」）。一个数一个节点。
- ASK：把上游若干节点的数值交给分析 Agent，做对比 / 归因 / 解释，产出一段结论文字。
- ACT：执行一个动作（如建复盘任务），通常依赖某个 ASK 的结论。

# 实体及其可过滤属性（filters 从这里选 attribute id）
{entity_lines}
# 可用指标（AGGREGATE 的 concept 从这里选；口径表达式里引用的 attribute 属于哪个实体，过滤就用同一实体的属性）
{metric_lines}
# 可用分析能力（ASK 的 concept 从这里选）
{deriv_lines}
# 可用动作（ACT 的 concept 从这里选）
{action_lines}

# 输出 JSON 格式
{{"nodes": [
  {{"id":"n1","operator":"AGGREGATE","name":"华东2024Q1毛利","concept":"<指标id>","params":{{"filters":[{{"concept":"<attribute id>","value":"华东"}},{{"concept":"<attribute id>","value":"2024Q1"}}]}},"depends_on":[]}},
  {{"id":"n2","operator":"AGGREGATE","name":"订单数量前三的产品","concept":"<指标id>","params":{{"filters":[],"group_by":"<维度 attribute id>","order":"desc","limit":3}},"depends_on":[]}},
  {{"id":"n5","operator":"ASK","name":"毛利差异归因","concept":"<derivation id>","params":{{"prompt":"华东毛利={{n1}}，华南毛利={{n2}}，请分析华东更低的原因"}},"depends_on":["n1","n2"]}},
  {{"id":"n6","operator":"ACT","name":"建复盘任务","concept":"<action id>","params":{{"desc":"华东毛利复盘：{{n5}}","assignee":"华东"}},"depends_on":["n5"]}}
]}}

# 规则（重要）
- 每个要对比/分析的数值都拆成**独立的 AGGREGATE 节点**，不要把多个地区或多个指标塞进一个节点。
- filters 里的 concept 必须是**该指标口径表达式所用属性同一实体**下的 attribute id（例如指标口径用 fact_sales 的属性，就只用 fact_sales 的可过滤属性；不要选 dim_region / fact_order 等别的实体的属性）。
- 排名 / TopN / 「前N / 最多 / 最高 / 按X分组」类问题：用**一个 AGGREGATE 节点**，在 params 里加：
  - `group_by`：分组维度的 attribute id（如按产品排名就填产品名属性 id）。该属性可以属于别的实体，系统会自动 JOIN。
  - `order`：`desc`（前N/最多/最高）或 `asc`（后N/最少/最低）。
  - `limit`：取前几名的整数（如「前三」= 3）。不要为排名再拆多个节点。
- 过滤取值：地区用中文（华东/华南/华北/华中），期间用 YYYYQn（如 2024Q1）；「上季度」按 2024Q1。
- ASK 节点的 params.prompt 里用 {{nX}} 引用上游 AGGREGATE 的结果，并在 depends_on 里列出这些上游 id。
- ACT 节点的 params.desc 用 {{nX}} 引用 ASK 的结论，depends_on 指向那个 ASK。
- concept 必须是上面清单里的 id。只用问题真正需要的节点；形成「取数(AGGREGATE) → 分析(ASK) → 行动(ACT)」的依赖链，只有问题要求「为什么/分析/对比」才加 ASK，要求「建任务/派单/执行」才加 ACT。
- id 用 n1,n2,... 顺序编号。只输出 JSON，不要多余文字。"""

        out = self.llm.complete(
            [{"role": "system", "content": system}, {"role": "user", "content": question}],
            schema={"type": "object"},
        )
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
        """只保留 LLM 给出的、指向真实属性 concept 的过滤；不做角色映射/跨实体改写。

        兼容旧格式 {role: value} / {concept,value} 两种，但不做角色→concept 的解析。
        """
        out: list[dict] = []
        items = filters if isinstance(filters, list) else []
        for f in items:
            if not isinstance(f, dict):
                continue
            cid, value = f.get("concept"), f.get("value")
            if not cid or value in (None, ""):
                continue
            c = self.ontology.get_concept(cid)
            if c and c.kind == ConceptKind.attribute:
                out.append({"concept": cid, "value": value})
        return out
