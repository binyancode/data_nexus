"""一次性迁移：把现有本体的属性 role 改成新枚举(dimension/measure)，并补 dtype / additivity。

规则（新规定，不兼容旧编码）：
  - 主键列 → dimension
  - dtype==number → measure（additivity 默认 additive）
  - 其它 → dimension
保留用户已编辑的 name / synonyms / semantics / 以及 metrics / relations / resolvers 等。

用法（backend/app 下，用项目 venv）：
    ..\\.venv\\Scripts\\python.exe migrate_attr_types.py
"""

import json
import os
import sys

_APP_DIR = os.path.abspath(os.path.dirname(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from bootstrap import register_services
from core.services import services
from services.sql_db import sql_db
from nexus.client import NexusClient


def main():
    register_services()
    nexus = services[NexusClient]
    db = services[sql_db]
    schema = "nexus"

    rows = db.execute_query(f"SELECT ontology_id, graph FROM {schema}.ontology")
    for r in rows:
        oid = r["ontology_id"]
        graph = json.loads(r["graph"] or "{}")
        changed = 0
        for e in graph.get("entities", []):
            resolver_name = e.get("resolver")
            table = e.get("table")
            key = e.get("key")
            rsv = nexus.registry.resolver(resolver_name) if resolver_name else None
            desc = rsv.describe() if (rsv and hasattr(rsv, "describe")) else {}
            cols = {c["column"]: c for c in desc.get(table, [])}
            for a in e.get("attributes", []):
                col = a.get("column") or a.get("name")
                dtype = (cols.get(col) or {}).get("dtype") or "unknown"
                is_pk = bool(key) and col == key
                role = "dimension" if (is_pk or dtype != "number") else "measure"
                a["role"] = role
                a["dtype"] = dtype
                a["additivity"] = "additive" if role == "measure" else None
                changed += 1
        db.execute_non_query(
            f"UPDATE {schema}.ontology SET graph = ?, updated_at = SYSUTCDATETIME() WHERE ontology_id = ?",
            (json.dumps(graph, ensure_ascii=False), oid),
        )
        print(f"[OK] {oid}: migrated {changed} attributes")
    print("MIGRATE ATTR TYPES DONE")


if __name__ == "__main__":
    main()
