"""种子：把 DWH 探测成一份 JSON 本体（sales_dwh）写入 nexus.ontology。

- 用 importer 从 dwh resolver 探测 dbo.* 五张表 → entities/attributes/relations
- 追加两个指标（用属性表达）
- owner = 管理员；默认 public，方便演示

用法（在 backend/app 下）：
    ..\\.venv\\Scripts\\python.exe seed_dwh_ontology.py
"""

import json

from config import config
from core.services import services
from services.sql_db import sql_db
from services.credential import azure_keyvault_credential_provider
from nexus.registry import ResolverRegistry
from nexus.ontology.importer import build_fragment

services.register(sql_db)
services.register(azure_keyvault_credential_provider)
services.register_default_config(sql_db, "sql_db")
services.register_default_config(azure_keyvault_credential_provider, "credential_provider")

cfg = config()
schema = cfg.get("nexus", {}).get("ontology", {}).get("schema", "nexus")
db = services[sql_db]

OWNER = "admin@mngenvmcap036409.onmicrosoft.com"
ONTOLOGY_ID = "sales_dwh"
NAME = "销售数仓"
DESCRIPTION = (
    "面向销售/订单分析的本体：区域、产品、客户、订单、销售明细。"
    "可回答销售额、毛利、按地区/期间/产品/客户的聚合与对比、差异归因等问题。"
)
TABLES = ["dbo.dim_region", "dbo.dim_product", "dbo.dim_customer", "dbo.fact_order", "dbo.fact_sales"]

METRICS = [
    {"id": "metric.sales_amount", "name": "销售额", "synonyms": ["销售额", "营收", "sales"],
     "semantics": "区域/期间的销售金额", "expr": "SUM(attribute.fact_sales.amount)"},
    {"id": "metric.gross_margin", "name": "毛利", "synonyms": ["毛利额", "gross margin"],
     "semantics": "销售额扣成本后的毛利",
     "expr": "SUM(attribute.fact_sales.amount - attribute.fact_sales.cost)"},
]


def main():
    registry = ResolverRegistry({"schema": schema}).load()
    r = registry.resolver("dwh")
    if r is None:
        raise SystemExit("dwh resolver 未注册，请先跑 seed_p0.py")

    frag = build_fragment("dwh", r.describe(), r.primary_keys(), r.foreign_keys(), TABLES)
    graph = {
        "entities": frag["entities"],
        "relations": frag["relations"],
        "metrics": METRICS,
        "derivations": [],
        "actions": [],
    }

    db.execute_non_query(
        f"""DELETE FROM {schema}.ontology_grant WHERE ontology_id = ?;
            DELETE FROM {schema}.ontology WHERE ontology_id = ?;
            INSERT INTO {schema}.ontology
                (ontology_id, name, description, owner, visibility, state, graph)
            VALUES (?, ?, ?, ?, 'public', 'published', ?);""",
        (ONTOLOGY_ID, ONTOLOGY_ID, ONTOLOGY_ID, NAME, DESCRIPTION, OWNER,
         json.dumps(graph, ensure_ascii=False)),
    )
    print(f"[DB] ontology '{ONTOLOGY_ID}': "
          f"{len(graph['entities'])} entities, {len(graph['relations'])} relations, "
          f"{len(graph['metrics'])} metrics")
    print("SEED DWH ONTOLOGY DONE")


if __name__ == "__main__":
    main()
