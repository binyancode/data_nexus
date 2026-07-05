"""P0 种子脚本：把 DWH 凭据写入 KV、注册 resolver、灌本体（概念+绑定）。

用法（在 backend/app 下）：
    ..\\.venv\\Scripts\\python.exe seed_p0.py
可选：设置环境变量 NEXUS_SEED_OPENAI_KEY 一并灌入默认 LLM 凭据。
"""

import os
import json

from config import config
from core.services import services
from services.sql_db import sql_db
from services.credential import azure_keyvault_credential_provider

# ── 注册服务 ──
services.register(sql_db)
services.register(azure_keyvault_credential_provider)
services.register_default_config(sql_db, "sql_db")
services.register_default_config(azure_keyvault_credential_provider, "credential_provider")

cfg = config()
schema = cfg.get("nexus", {}).get("ontology", {}).get("schema", "nexus")
db = services[sql_db]
cred = services[azure_keyvault_credential_provider]


def seed_dwh_credential():
    base = dict(cfg.get("sql_db"))
    data = {
        "server": base["server"],
        "database": "binyandb-data-nexus-dwh",
        "username": base["username"],
        "password": base["password"],
        "driver": base.get("driver", "{ODBC Driver 18 for SQL Server}"),
        "encrypt": base.get("encrypt", "yes"),
        "trust_server_certificate": base.get("trust_server_certificate", "no"),
    }
    cred.save("dwh-sql", "sql", data, description="数仓 DWH 只读连接")
    print("[KV] saved credential: dwh-sql")


def seed_openai_credential():
    key = os.environ.get("NEXUS_SEED_OPENAI_KEY")
    if not key:
        print("[LLM] NEXUS_SEED_OPENAI_KEY not set -> skip llm credential")
        return False
    data = {
        "endpoint": os.environ.get("NEXUS_SEED_OPENAI_ENDPOINT", "https://byaif-eu2.cognitiveservices.azure.com/"),
        "key": key,
        "deployment": os.environ.get("NEXUS_SEED_OPENAI_DEPLOYMENT", "gpt-5.4"),
        "api_version": os.environ.get("NEXUS_SEED_OPENAI_APIVERSION", "2025-04-01-preview"),
    }
    cred.save("default-llm", "azure_openai", data, description="默认 LLM")
    print("[KV] saved credential: default-llm")
    return True


def seed_registry(with_llm: bool):
    db.execute_non_query(
        f"DELETE FROM {schema}.resolvers WHERE resolver_name = 'dwh';"
        f"INSERT INTO {schema}.resolvers (resolver_name, resolver_type, config, credential_name) "
        f"VALUES ('dwh', 'sql', '{{}}', 'dwh-sql');"
    )
    print("[DB] resolver row: dwh")
    if with_llm:
        db.execute_non_query(
            f"DELETE FROM {schema}.llms WHERE llm_name = 'default';"
            f"INSERT INTO {schema}.llms (llm_name, provider, config, credential_name, is_default) "
            f"VALUES ('default', 'azure_openai', '{{}}', 'default-llm', 1);"
        )
        print("[DB] llm row: default")


if __name__ == "__main__":
    seed_dwh_credential()
    with_llm = seed_openai_credential()
    seed_registry(with_llm)
    print("SEED DONE (本体请跑 seed_dwh_ontology.py)")
