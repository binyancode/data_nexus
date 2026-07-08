"""一次性迁移：nexus.run 的 ontology_id 列 → context（JSON，承载运行上下文）。

context JSON 形如 {"ontology_ids": ["onto_a", ...]}；本体集合是其中一项，将来可放
检索到的知识、few-shot 等更多内容。老单 id → 1 元素数组，UI 显示不变。

幂等：可重复运行（按 INFORMATION_SCHEMA 判断列是否存在）。

用法（backend/app 下，用项目 venv）：
    ..\\.venv\\Scripts\\python.exe migrate_run_context.py
"""

import os
import sys

_APP_DIR = os.path.abspath(os.path.dirname(__file__))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from bootstrap import register_services
from core.services import services
from services.sql_db import sql_db


def _col_exists(db, table: str, col: str) -> bool:
    rows = db.execute_query(
        "SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA='nexus' AND TABLE_NAME=? AND COLUMN_NAME=?",
        (table, col),
    )
    return bool(rows)


def main():
    register_services()
    db = services[sql_db]

    has_ctx = _col_exists(db, "run", "context")
    has_old = _col_exists(db, "run", "ontology_id")

    if not has_ctx:
        db.execute_non_query("ALTER TABLE nexus.run ADD context NVARCHAR(MAX) NULL")
        print("[OK] added column nexus.run.context")
    else:
        print("[SKIP] nexus.run.context already exists")

    if has_old:
        # 老单 id → {"ontology_ids":["<id>"]}（id 为 onto_hex/名称，无引号，拼接安全）
        n = db.execute_non_query(
            "UPDATE nexus.run "
            "SET context = CASE WHEN ontology_id IS NULL THEN NULL "
            "ELSE N'{\"ontology_ids\":[\"' + ontology_id + N'\"]}' END "
            "WHERE context IS NULL"
        )
        print(f"[OK] backfilled context from ontology_id (rows affected: {n})")
        db.execute_non_query("ALTER TABLE nexus.run DROP COLUMN ontology_id")
        print("[OK] dropped column nexus.run.ontology_id")
    else:
        print("[SKIP] nexus.run.ontology_id already removed")

    print("MIGRATE RUN CONTEXT DONE")


if __name__ == "__main__":
    main()
