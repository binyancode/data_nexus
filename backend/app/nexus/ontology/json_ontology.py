"""JsonOntology：把一份 ontology 的 graph JSON 摊平成 Concept/Binding，
实现引擎读取接口（OntologyStore 的读侧），从而 Compiler/Optimizer/Generator 无需改动。

graph 结构（见前端画板）：
{
  "entities":[{id,name,semantics,synonyms,resolver,table,key,
               attributes:[{id,name,column,role,synonyms,semantics}], layout:{x,y}}],
  "relations":[{id,name,semantics,synonyms,from_entity,from_key,to_entity,to_key}],
  "metrics":[{id,name,semantics,synonyms,expr}],
  "derivations":[{id,name,semantics,synonyms,prompt,inputs,resolver}],
  "actions":[{id,name,semantics,synonyms,action,desc,resolver,endpoint}]
}
"""

from __future__ import annotations

import re
from typing import Optional

from nexus.core.models import Concept, Binding, ConceptKind
from nexus.ontology.store import OntologyStore

# 多本体命名空间：概念 id 前缀 `本体id::`，让 id 全局唯一、本体信息随 id 流动。
NS_SEP = "::"
# 表达式里引用属性概念的裸记号（用于给 metric.expr 内嵌 token 加本体前缀）。
_EXPR_ATTR = re.compile(r"attribute(?:\.[A-Za-z0-9_]+)+")


def _syn(x) -> list:
    return list(x) if isinstance(x, (list, tuple)) else []


class JsonOntology(OntologyStore):
    def __init__(self, graph: dict | None = None, ns: str | None = None):
        self._graph = graph or {}
        # 命名空间前缀（本体 id）；None = 不加前缀（单本体/测试，向后兼容）。
        self._ns = re.sub(r"[^A-Za-z0-9_]", "_", ns) if ns else None
        self._concepts: dict[str, Concept] = {}
        self._bindings: dict[str, list[Binding]] = {}   # concept_id -> [Binding]
        self._build()

    # 概念 id 加本体前缀；物理名（列/表/键）不加。
    def _p(self, cid: Optional[str]) -> Optional[str]:
        if not cid or not self._ns:
            return cid
        return f"{self._ns}{NS_SEP}{cid}"

    # 给表达式里内嵌的 attribute token 加本体前缀（metric.expr 等）。
    def _pexpr(self, expr: Optional[str]) -> Optional[str]:
        if not expr or not self._ns:
            return expr
        return _EXPR_ATTR.sub(lambda m: f"{self._ns}{NS_SEP}{m.group(0)}", expr)

    # ── 摊平 graph → Concept/Binding ──
    def _build(self) -> None:
        g = self._graph

        for e in g.get("entities", []):
            eid = e.get("id")
            if not eid:
                continue
            eid = self._p(eid)
            resolver = e.get("resolver") or ""
            self._add(Concept(
                id=eid, kind=ConceptKind.entity, name=e.get("name") or eid,
                semantics=e.get("semantics"), synonyms=_syn(e.get("synonyms")),
                attrs={"key": e.get("key")} if e.get("key") else {},
            ))
            if e.get("table"):
                self._bind(Binding(id=f"b.{eid}.table", concept_id=eid, resolver=resolver,
                                   kind="table", expr=e["table"]))
            for a in e.get("attributes", []):
                aid = a.get("id")
                if not aid or a.get("enabled") is False:
                    continue   # 停用的属性不进概念（编译器/优化器看不到）
                aid = self._p(aid)
                attrs = {"entity": eid}
                if a.get("role"):
                    attrs["role"] = a["role"]
                if a.get("dtype"):
                    attrs["dtype"] = a["dtype"]
                if a.get("additivity"):
                    attrs["additivity"] = a["additivity"]
                self._add(Concept(
                    id=aid, kind=ConceptKind.attribute, name=a.get("name") or aid,
                    semantics=a.get("semantics"), synonyms=_syn(a.get("synonyms")), attrs=attrs,
                ))
                if a.get("column"):
                    self._bind(Binding(id=f"b.{aid}.col", concept_id=aid, resolver=resolver,
                                       kind="column", expr=a["column"]))

        for r in g.get("relations", []):
            rid = r.get("id")
            if not rid:
                continue
            # 前缀：relation id + from/to 实体 id；不前缀 from_key/to_key（物理列）。
            self._add(Concept(
                id=self._p(rid), kind=ConceptKind.relation, name=r.get("name") or rid,
                semantics=r.get("semantics"), synonyms=_syn(r.get("synonyms")),
                attrs={"from_entity": self._p(r.get("from_entity")), "from_key": r.get("from_key"),
                       "to_entity": self._p(r.get("to_entity")), "to_key": r.get("to_key")},
            ))

        for m in g.get("metrics", []):
            mid = m.get("id")
            if not mid:
                continue
            # 前缀：metric id + expr 内嵌的 attribute token。
            self._add(Concept(
                id=self._p(mid), kind=ConceptKind.metric, name=m.get("name") or mid,
                semantics=m.get("semantics"), synonyms=_syn(m.get("synonyms")),
                attrs={"expr": self._pexpr(m.get("expr"))},
            ))

        for d in g.get("derivations", []):
            did = d.get("id")
            if not did:
                continue
            did = self._p(did)
            self._add(Concept(
                id=did, kind=ConceptKind.derivation, name=d.get("name") or did,
                semantics=d.get("semantics"), synonyms=_syn(d.get("synonyms")),
                attrs={"prompt": d.get("prompt"), "inputs": d.get("inputs") or []},
            ))
            if d.get("resolver"):
                self._bind(Binding(id=f"b.{did}.prompt", concept_id=did, resolver=d["resolver"],
                                   kind="prompt", expr=d.get("prompt")))

        for ac in g.get("actions", []):
            acid = ac.get("id")
            if not acid:
                continue
            acid = self._p(acid)
            self._add(Concept(
                id=acid, kind=ConceptKind.action, name=ac.get("name") or acid,
                semantics=ac.get("semantics"), synonyms=_syn(ac.get("synonyms")),
                attrs={"action": ac.get("action"), "desc": ac.get("desc")},
            ))
            if ac.get("resolver") or ac.get("endpoint"):
                self._bind(Binding(id=f"b.{acid}.endpoint", concept_id=acid,
                                   resolver=ac.get("resolver") or "action",
                                   kind="endpoint", expr=ac.get("endpoint") or ac.get("action")))

    def _add(self, c: Concept) -> None:
        self._concepts[c.id] = c

    def _bind(self, b: Binding) -> None:
        self._bindings.setdefault(b.concept_id, []).append(b)

    # ── OntologyStore 读接口 ──
    def list_concepts(self) -> list[Concept]:
        return list(self._concepts.values())

    def get_concept(self, concept_id: str) -> Optional[Concept]:
        return self._concepts.get(concept_id)

    def find_concept(self, term: str) -> Optional[Concept]:
        t = (term or "").strip().lower()
        if not t:
            return None
        for c in self._concepts.values():
            if c.name.lower() == t:
                return c
        for c in self._concepts.values():
            if t in [s.lower() for s in c.synonyms] or t in c.name.lower():
                return c
        return None

    def list_bindings(self, concept_id: Optional[str] = None) -> list[Binding]:
        if concept_id:
            return list(self._bindings.get(concept_id, []))
        out: list[Binding] = []
        for bs in self._bindings.values():
            out.extend(bs)
        return out

    def get_bindings(self, concept_id: str) -> list[Binding]:
        return list(self._bindings.get(concept_id, []))

    # 写接口：JSON 本体只读（编辑走前端画板 + 整份保存）
    def upsert_concept(self, concept: Concept) -> None:
        raise NotImplementedError("JsonOntology 只读；编辑请整份保存 graph")

    def upsert_binding(self, binding: Binding) -> None:
        raise NotImplementedError("JsonOntology 只读；编辑请整份保存 graph")
