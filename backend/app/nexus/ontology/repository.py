"""OntologyRepository：nexus.ontology / nexus.ontology_grant 的读写。

- 一行一份本体；graph 为整块 JSON。
- 可见性：private（仅 owner）| shared（owner + 授权名单）| public（所有人）。
- 写操作（save/publish/delete）仅 owner。执行期数据权限不在此层（仍由 resolver 凭据 + RLS 决定）。
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from services.sql_db import sql_db
from core.services import services
from nexus.core.models import Ontology


class OntologyRepository:
    def __init__(self, schema: str = "nexus"):
        self._schema = schema

    @property
    def _db(self) -> sql_db:
        return services[sql_db]

    # ── 组装 ──
    @staticmethod
    def _row_to_ontology(row: dict, with_graph: bool = True, grants: list[str] | None = None) -> Ontology:
        graph = {}
        if with_graph and row.get("graph"):
            try:
                graph = json.loads(row["graph"])
            except Exception:
                graph = {}
        return Ontology(
            ontology_id=row["ontology_id"], name=row["name"], description=row.get("description"),
            owner=row["owner"], visibility=row.get("visibility") or "private",
            state=row.get("state") or "draft", graph=graph, grants=grants or [],
            updated_at=str(row.get("updated_at")) if row.get("updated_at") else None,
        )

    def _grants(self, ontology_id: str) -> list[str]:
        rows = self._db.execute_query(
            f"SELECT user_name FROM {self._schema}.ontology_grant WHERE ontology_id = ?", (ontology_id,)
        )
        return [r["user_name"] for r in rows]

    # ── 读 ──
    def list_for_user(self, user: Optional[str]) -> list[Ontology]:
        """列出对 user 可见的本体（不含 graph，减负）。"""
        rows = self._db.execute_query(
            f"""SELECT ontology_id, name, description, owner, visibility, state, updated_at
                  FROM {self._schema}.ontology o
                 WHERE o.owner = ?
                    OR o.visibility = 'public'
                    OR (o.visibility = 'shared' AND EXISTS (
                          SELECT 1 FROM {self._schema}.ontology_grant g
                           WHERE g.ontology_id = o.ontology_id AND g.user_name = ?))
                 ORDER BY o.updated_at DESC""",
            (user or "", user or ""),
        )
        return [self._row_to_ontology(r, with_graph=False) for r in rows]

    def get(self, ontology_id: str) -> Optional[Ontology]:
        rows = self._db.execute_query(
            f"""SELECT ontology_id, name, description, owner, visibility, state, graph, updated_at
                  FROM {self._schema}.ontology WHERE ontology_id = ?""",
            (ontology_id,),
        )
        if not rows:
            return None
        return self._row_to_ontology(rows[0], with_graph=True, grants=self._grants(ontology_id))

    def can_read(self, onto: Ontology, user: Optional[str]) -> bool:
        if onto.visibility == "public":
            return True
        if user and onto.owner == user:
            return True
        return bool(user) and onto.visibility == "shared" and user in onto.grants

    # ── 写（owner-only 由上层校验后调用）──
    def create(self, name: str, owner: str, description: str = None) -> Ontology:
        oid = "onto_" + uuid.uuid4().hex[:12]
        graph = {"entities": [], "relations": [], "metrics": [], "derivations": [], "actions": []}
        self._db.execute_non_query(
            f"""INSERT INTO {self._schema}.ontology
                    (ontology_id, name, description, owner, visibility, state, graph)
                VALUES (?, ?, ?, ?, 'private', 'draft', ?)""",
            (oid, name, description, owner, json.dumps(graph, ensure_ascii=False)),
        )
        return Ontology(ontology_id=oid, name=name, description=description, owner=owner, graph=graph)

    def save(self, ontology_id: str, name: str, description: Optional[str], graph: dict) -> None:
        self._db.execute_non_query(
            f"""UPDATE {self._schema}.ontology
                   SET name = ?, description = ?, graph = ?, updated_at = SYSUTCDATETIME()
                 WHERE ontology_id = ?""",
            (name, description, json.dumps(graph, ensure_ascii=False), ontology_id),
        )

    def publish(self, ontology_id: str, visibility: str, grants: list[str]) -> None:
        self._db.execute_non_query(
            f"""UPDATE {self._schema}.ontology
                   SET visibility = ?, state = 'published', updated_at = SYSUTCDATETIME()
                 WHERE ontology_id = ?""",
            (visibility, ontology_id),
        )
        self._db.execute_non_query(
            f"DELETE FROM {self._schema}.ontology_grant WHERE ontology_id = ?", (ontology_id,)
        )
        for u in grants or []:
            if visibility == "shared" and u:
                self._db.execute_non_query(
                    f"INSERT INTO {self._schema}.ontology_grant (ontology_id, user_name) VALUES (?, ?)",
                    (ontology_id, u),
                )

    def delete(self, ontology_id: str) -> None:
        self._db.execute_non_query(
            f"DELETE FROM {self._schema}.ontology_grant WHERE ontology_id = ?;"
            f"DELETE FROM {self._schema}.ontology WHERE ontology_id = ?;",
            (ontology_id, ontology_id),
        )
