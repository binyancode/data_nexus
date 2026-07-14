"""凭据模块（从 AIBI 移植并裁剪）。

- credential（ABC）+ 子类（SQL / Azure OpenAI / Web IQ / 本地文件）
- credential_provider（ABC）+ azure_keyvault_credential_provider（Azure Key Vault 实现）

设计：DB 表 `nexus.app_credential` 只存映射（credential_name -> credential_type + secret_name），
密文（JSON）存 Azure Key Vault。Provider 用 DefaultAzureCredential 访问 KV
（本地走 az 登录，云上走托管身份，无需任何密钥）。
"""

from __future__ import annotations

import json
import re
import traceback
import uuid
from abc import ABC, abstractmethod

from services.sql_db import sql_db
from core.services import services
from utils.logger import get_logger

_logger = get_logger("credential")


# ---------------------------------------------------------------------------
# Credential 基础类
# ---------------------------------------------------------------------------
class credential(ABC):
    """凭据抽象基类（不可直接实例化）。"""

    _type_map: dict[str, type] = {}
    display_name: str = ""
    description: str = ""
    schema: list[dict] = []

    def __init__(self, name: str, credential_type: str, data: dict):
        self.name = name
        self.credential_type = credential_type
        self._data: dict = data or {}

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    @property
    def data(self) -> dict:
        return dict(self._data)

    @abstractmethod
    def to_config(self) -> dict:
        """转换为对应服务初始化所需的配置字典。"""
        ...

    def __repr__(self) -> str:
        return f"<credential name={self.name!r} type={self.credential_type!r}>"

    @staticmethod
    def create(name: str, credential_type: str, data: dict) -> "credential":
        cls = credential._type_map.get(credential_type)
        if cls is None:
            raise ValueError(
                f"Unknown credential type: {credential_type!r}. "
                f"Registered types: {list(credential._type_map.keys())}"
            )
        return cls(name=name, credential_type=credential_type, data=data)

    @classmethod
    def register_type(cls, type_name: str, sub_cls: type) -> None:
        if not (isinstance(sub_cls, type) and issubclass(sub_cls, credential)):
            raise TypeError(f"register_type expects a credential subclass, got {sub_cls!r}")
        cls._type_map[type_name] = sub_cls

    @classmethod
    def get_types(cls) -> dict[str, dict]:
        return {
            type_name: {
                "display_name": type_cls.display_name,
                "description": type_cls.description,
                "schema": type_cls.schema,
            }
            for type_name, type_cls in cls._type_map.items()
        }


class sql_credential(credential):
    """SQL Server / Azure SQL 数据库凭据。必填: server, database, username, password。"""

    display_name: str = "SQL Server"
    description: str = "SQL Server / Azure SQL 数据库连接凭据。"
    schema: list[dict] = [
        {"name": "server", "type": "string", "required": True, "sensitive": False, "description": "数据库服务器地址"},
        {"name": "port", "type": "number", "required": False, "sensitive": False, "description": "端口号，默认 1433"},
        {"name": "database", "type": "string", "required": True, "sensitive": False, "description": "数据库名称"},
        {"name": "username", "type": "string", "required": True, "sensitive": False, "description": "用户名"},
        {"name": "password", "type": "password", "required": True, "sensitive": True, "description": "密码"},
        {"name": "driver", "type": "string", "required": False, "sensitive": False, "description": "ODBC Driver 名称"},
        {"name": "encrypt", "type": "string", "required": False, "sensitive": False, "description": "是否加密，默认 yes"},
        {"name": "trust_server_certificate", "type": "string", "required": False, "sensitive": False, "description": "是否信任服务器证书，默认 no"},
        {"name": "timeout", "type": "number", "required": False, "sensitive": False, "description": "连接超时秒数，默认 30"},
    ]

    def __init__(self, name: str, credential_type: str, data: dict):
        super().__init__(name, credential_type, data)
        missing = [k for k in ("server", "database", "username", "password") if not self._data.get(k)]
        if missing:
            raise ValueError(f"sql_credential {name!r} missing required fields: {missing}")

    def to_config(self) -> dict:
        conf = {
            "auth_method": "password",
            "server": self._data["server"],
            "database": self._data["database"],
            "username": self._data["username"],
            "password": self._data["password"],
        }
        for key in ("port", "driver", "encrypt", "trust_server_certificate", "timeout"):
            if self._data.get(key):
                conf[key] = self._data[key]
        return conf


class azure_openai_credential(credential):
    """Azure OpenAI 凭据。必填: endpoint, key。"""

    display_name: str = "Azure OpenAI"
    description: str = "Azure OpenAI 服务凭据，用于调用 GPT / Embedding 模型。"
    schema: list[dict] = [
        {"name": "endpoint", "type": "string", "required": True, "sensitive": False, "description": "Azure OpenAI 端点 URL"},
        {"name": "key", "type": "password", "required": True, "sensitive": True, "description": "API 密钥"},
        {"name": "deployment", "type": "string", "required": False, "sensitive": False, "description": "部署名 / 模型名"},
        {"name": "api_version", "type": "string", "required": False, "sensitive": False, "description": "API 版本"},
    ]

    def __init__(self, name: str, credential_type: str, data: dict):
        super().__init__(name, credential_type, data)
        missing = [k for k in ("endpoint", "key") if not self._data.get(k)]
        if missing:
            raise ValueError(f"azure_openai_credential {name!r} missing required fields: {missing}")

    def to_config(self) -> dict:
        conf = {"endpoint": self._data["endpoint"], "key": self._data["key"]}
        for key in ("deployment", "api_version"):
            if self._data.get(key):
                conf[key] = self._data[key]
        return conf


class web_iq_credential(credential):
    """Microsoft Web IQ 凭据。API 端点是固定公共端点，凭据只保存 API Key。"""

    display_name: str = "Microsoft Web IQ"
    description: str = "Microsoft Web IQ Web Search / Browse API 凭据。"
    schema: list[dict] = [
        {"name": "api_key", "type": "password", "required": True, "sensitive": True,
         "description": "Web IQ API Key（通过 x-apikey 请求头发送）"},
    ]

    def __init__(self, name: str, credential_type: str, data: dict):
        super().__init__(name, credential_type, data)
        if not self._data.get("api_key"):
            raise ValueError(f"web_iq_credential {name!r} missing required field: api_key")

    def to_config(self) -> dict:
        return {"api_key": self._data["api_key"]}


class local_file_credential(credential):
    """本地文件（夹）凭据。base_dir 必填；filename 可选。

    filename 语义（决定实体粒度）：
      - 空          → 整个文件夹作为一个实体（describe 返回 `*.csv`，运行时合并）
      - 具体文件名  → 该单文件作为一个实体
      - 通配符      → 匹配到的每个文件各作为一个实体
    """

    display_name: str = "本地文件"
    description: str = "本地文件夹作为 CSV 数据源。filename 空=文件夹整体一个实体；具体名=单文件；通配符=逐文件。"
    schema: list[dict] = [
        {"name": "base_dir", "type": "string", "required": True, "sensitive": False, "description": "本地文件夹绝对路径"},
        {"name": "filename", "type": "string", "required": False, "sensitive": False, "description": "文件名（空=文件夹合并；具体名=单文件；通配符如 *.csv=逐文件）"},
    ]

    def __init__(self, name: str, credential_type: str, data: dict):
        super().__init__(name, credential_type, data)
        if not self._data.get("base_dir"):
            raise ValueError(f"local_file_credential {name!r} missing required field: base_dir")

    def to_config(self) -> dict:
        conf = {"base_dir": self._data["base_dir"]}
        if self._data.get("filename"):
            conf["filename"] = self._data["filename"]
        return conf


# 注册内置凭据类型
credential.register_type("sql", sql_credential)
credential.register_type("azure_openai", azure_openai_credential)
credential.register_type("web_iq", web_iq_credential)
credential.register_type("local_file", local_file_credential)


# ---------------------------------------------------------------------------
# Credential Provider
# ---------------------------------------------------------------------------
class credential_provider(ABC):
    """凭据提供器抽象接口。"""

    @abstractmethod
    def load(self, credential_name: str) -> credential | None: ...

    @abstractmethod
    def save(self, credential_name: str, credential_type: str, data: dict, description: str = "") -> credential: ...

    @abstractmethod
    def delete(self, credential_name: str) -> bool: ...


class azure_keyvault_credential_provider(credential_provider):
    """Azure Key Vault 凭据提供器。

    元数据存 DB 表（默认 `nexus.app_credential`），密文存 Key Vault。

    config:
        vault_url : str          Key Vault URL
        auth_method : str         "default"(DefaultAzureCredential) | "managed_identity" | "service_principal"
        tenant_id / client_id / client_secret : 视 auth_method 而定
        table : str               凭据映射表名，默认 "nexus.app_credential"
    """

    def __init__(self, config: dict = None):
        conf = config or {}
        self._vault_url = conf.get("vault_url", "")
        self._auth_method = conf.get("auth_method", "default")
        self._client_id = conf.get("client_id")
        self._client_secret = conf.get("client_secret")
        self._tenant_id = conf.get("tenant_id")
        self._table = conf.get("table", "nexus.app_credential")
        self._kv_client = None

    @property
    def _db(self) -> sql_db:
        return services[sql_db]

    def init(self) -> "azure_keyvault_credential_provider":
        self._kv_client = self._create_kv_client()
        return self

    def _create_kv_client(self):
        if not self._vault_url:
            return None
        try:
            from azure.identity import (
                ClientSecretCredential,
                DefaultAzureCredential,
                ManagedIdentityCredential,
            )
            from azure.keyvault.secrets import SecretClient

            if self._auth_method == "service_principal":
                azure_cred = ClientSecretCredential(
                    tenant_id=self._tenant_id,
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                )
            elif self._auth_method == "managed_identity":
                azure_cred = (
                    ManagedIdentityCredential(client_id=self._client_id)
                    if self._client_id else ManagedIdentityCredential()
                )
            else:
                kw = {}
                if self._tenant_id:
                    kw["authority"] = f"https://login.microsoftonline.com/{self._tenant_id}"
                azure_cred = DefaultAzureCredential(**kw)

            return SecretClient(vault_url=self._vault_url, credential=azure_cred)
        except Exception:
            _logger.warning(
                f"Failed to create Key Vault client: vault_url={self._vault_url}\n{traceback.format_exc()}"
            )
            return None

    def _ensure_client(self):
        if self._kv_client is None:
            self.init()
        return self._kv_client

    def _query_credential_meta(self, credential_name: str) -> dict | None:
        try:
            rows = self._db.execute_query(
                f"""SELECT TOP 1 credential_type, secret_name
                    FROM {self._table}
                    WHERE credential_name = ? AND is_active = 1""",
                (credential_name,),
            )
            return rows[0] if rows else None
        except Exception:
            _logger.warning(
                f"Failed to query credential meta: credential_name={credential_name}\n{traceback.format_exc()}"
            )
            return None

    def _load_secret(self, secret_name: str) -> str | None:
        client = self._ensure_client()
        if not client:
            return None
        try:
            return client.get_secret(secret_name).value
        except Exception:
            _logger.warning(
                f"Failed to load secret from Key Vault: secret_name={secret_name}\n{traceback.format_exc()}"
            )
            return None

    def load(self, credential_name: str) -> credential | None:
        meta = self._query_credential_meta(credential_name)
        if not meta:
            _logger.warning(f"Credential not found in DB: credential_name={credential_name}")
            return None
        credential_type = meta.get("credential_type", "")
        secret_name = meta.get("secret_name", "")
        if not secret_name:
            _logger.warning(f"Credential has no secret_name: credential_name={credential_name}")
            return None
        secret_value = self._load_secret(secret_name)
        if not secret_value:
            return None
        try:
            data = json.loads(secret_value)
        except json.JSONDecodeError:
            _logger.warning(f"Credential secret is not valid JSON: credential_name={credential_name}")
            return None
        return credential.create(name=credential_name, credential_type=credential_type, data=data)

    @staticmethod
    def _generate_secret_name(credential_name: str) -> str:
        """生成 KV secret 名：{sanitized}-{uuid8}，避免软删除同名冲突。"""
        sanitized = re.sub(r"[^a-zA-Z0-9-]", "-", credential_name).strip("-")
        return f"{sanitized}-{uuid.uuid4().hex[:8]}"[:127]

    def save(self, credential_name: str, credential_type: str, data: dict, description: str = "") -> credential:
        client = self._ensure_client()
        if not client:
            raise RuntimeError("Key Vault client not initialized")

        # 校验数据
        cred = credential.create(name=credential_name, credential_type=credential_type, data=data)

        old_meta = self._query_credential_meta(credential_name)
        old_secret_name = old_meta.get("secret_name") if old_meta else None

        new_secret_name = self._generate_secret_name(credential_name)
        try:
            client.set_secret(new_secret_name, json.dumps(data, ensure_ascii=False))
        except Exception as exc:
            raise RuntimeError(f"Failed to write secret to Key Vault: secret_name={new_secret_name}") from exc

        try:
            if old_meta:
                self._db.execute_non_query(
                    f"""UPDATE {self._table}
                        SET credential_type = ?, secret_name = ?, description = ?,
                            is_active = 1, update_time = SYSUTCDATETIME()
                        WHERE credential_name = ?""",
                    (credential_type, new_secret_name, description, credential_name),
                )
            else:
                self._db.execute_non_query(
                    f"""INSERT INTO {self._table}
                        (credential_name, credential_type, secret_name, description, is_active, creation_time)
                        VALUES (?, ?, ?, ?, 1, SYSUTCDATETIME())""",
                    (credential_name, credential_type, new_secret_name, description),
                )
        except Exception as exc:
            try:
                client.begin_delete_secret(new_secret_name)
            except Exception:
                pass
            raise RuntimeError(f"Failed to write credential meta to DB: credential_name={credential_name}") from exc

        if old_secret_name and old_secret_name != new_secret_name:
            try:
                client.begin_delete_secret(old_secret_name)
            except Exception:
                _logger.warning(f"Failed to delete old secret: secret_name={old_secret_name}")

        _logger.info(f"Credential saved: {credential_name} (type={credential_type}, secret={new_secret_name})")
        return cred

    def delete(self, credential_name: str) -> bool:
        meta = self._query_credential_meta(credential_name)
        if not meta:
            return False
        secret_name = meta.get("secret_name")
        client = self._ensure_client()
        if client and secret_name:
            try:
                client.begin_delete_secret(secret_name)
            except Exception:
                _logger.warning(f"Failed to delete secret: secret_name={secret_name}")
        try:
            self._db.execute_non_query(
                f"UPDATE {self._table} SET is_active = 0, update_time = SYSUTCDATETIME() WHERE credential_name = ?",
                (credential_name,),
            )
        except Exception:
            _logger.warning(f"Failed to deactivate credential in DB: {credential_name}")
            return False
        return True
