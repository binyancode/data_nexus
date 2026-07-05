"""Azure SQL 本体存储实现（走 services[sql_db]）。"""

from __future__ import annotations

import json
from typing import Optional

from services.sql_db import sql_db
from core.services import services
from nexus.core.models import Concept, Binding
from nexus.ontology.store import OntologyStore


class AzureSqlOntologyStore(OntologyStore):
    """概念/绑定存于 Azure SQL 的 `{schema}.concepts` / `{schema}.bindings`。"""

    def __init__(self, config: dict = None):
        conf = config or {}
        self._schema = conf.get("schema", "nexus")

    @property
    def _db(self) -> sql_db:
        return services[sql_db]

    # ── 反序列化 ──
    @staticmethod
    def _row_to_concept(row: dict) -> Concept:
        return Concept(
            id=row["id"],
            kind=row["kind"],
            name=row["name"],
            semantics=row.get("semantics"),
            synonyms=json.loads(row.get("synonyms") or "[]"),
            attrs=json.loads(row.get("attrs") or "{}"),
            policy=json.loads(row.get("policy") or "{}"),
            provenance=json.loads(row.get("provenance") or "{}"),
        )

    @staticmethod
    def _row_to_binding(row: dict) -> Binding:
        return Binding(
            id=row["id"],
            concept_id=row["concept_id"],
            resolver=row["resolver"],
            kind=row["kind"],
            expr=row.get("expr"),
            confidence=float(row.get("confidence", 1.0)),
        )

    # ── 概念 ──
    def list_concepts(self) -> list[Concept]:
        rows = self._db.execute_query(f"SELECT * FROM {self._schema}.concepts")
        return [self._row_to_concept(r) for r in rows]

    def get_concept(self, concept_id: str) -> Optional[Concept]:
        rows = self._db.execute_query(
            f"SELECT * FROM {self._schema}.concepts WHERE id = ?", (concept_id,)
        )
        return self._row_to_concept(rows[0]) if rows else None

    def find_concept(self, term: str) -> Optional[Concept]:
        term_l = (term or "").strip().lower()
        if not term_l:
            return None
        # 先精确匹配名称
        rows = self._db.execute_query(
            f"SELECT * FROM {self._schema}.concepts WHERE LOWER(name) = ?", (term_l,)
        )
        if rows:
            return self._row_to_concept(rows[0])
        # 再扫同义词（P0 数据量小，内存匹配即可）
        for c in self.list_concepts():
            if term_l in [s.strip().lower() for s in c.synonyms]:
                return c
            if term_l in c.name.lower():
                return c
        return None

    def upsert_concept(self, concept: Concept) -> None:
        self._db.execute_non_query(
            f"""DELETE FROM {self._schema}.concepts WHERE id = ?;
                INSERT INTO {self._schema}.concepts
                    (id, kind, name, semantics, synonyms, attrs, policy, provenance)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);""",
            (
                concept.id,
                concept.id, concept.kind.value if hasattr(concept.kind, "value") else str(concept.kind),
                concept.name, concept.semantics,
                json.dumps(concept.synonyms, ensure_ascii=False),
                json.dumps(concept.attrs, ensure_ascii=False),
                json.dumps(concept.policy, ensure_ascii=False),
                json.dumps(concept.provenance, ensure_ascii=False),
            ),
        )

    # ── 绑定 ──
    def list_bindings(self, concept_id: Optional[str] = None) -> list[Binding]:
        if concept_id:
            rows = self._db.execute_query(
                f"SELECT * FROM {self._schema}.bindings WHERE concept_id = ?", (concept_id,)
            )
        else:
            rows = self._db.execute_query(f"SELECT * FROM {self._schema}.bindings")
        return [self._row_to_binding(r) for r in rows]

    def get_bindings(self, concept_id: str) -> list[Binding]:
        return self.list_bindings(concept_id)

    def upsert_binding(self, binding: Binding) -> None:
        self._db.execute_non_query(
            f"""DELETE FROM {self._schema}.bindings WHERE id = ?;
                INSERT INTO {self._schema}.bindings
                    (id, concept_id, resolver, kind, expr, confidence)
                VALUES (?, ?, ?, ?, ?, ?);""",
            (
                binding.id,
                binding.id, binding.concept_id, binding.resolver,
                binding.kind, binding.expr, binding.confidence,
            ),
        )
