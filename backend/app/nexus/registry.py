"""注册表：从 `nexus.resolvers` / `nexus.llms` 读注册行，密文经 credential/KV 装配成实例。"""

from __future__ import annotations

import json
from typing import Optional

from services.sql_db import sql_db
from services.credential import azure_keyvault_credential_provider
from core.services import services
from utils.logger import get_logger

from nexus.resolvers.base import Resolver
from nexus.resolvers.sql import SqlResolver
from nexus.resolvers.agent import AgentResolver
from nexus.resolvers.action import ActionResolver
from nexus.llm.base import LLMProvider
from nexus.llm.azure_openai import AzureOpenAIProvider

_logger = get_logger("registry")

# 类型 → 实现类
_RESOLVER_TYPES: dict[str, type] = {
    "sql": SqlResolver,
    "agent": AgentResolver,
    "action": ActionResolver,
}
_LLM_PROVIDERS: dict[str, type] = {
    "azure_openai": AzureOpenAIProvider,
}


class ResolverRegistry:
    """加载并持有所有 Resolver 与 LLM 实例。"""

    def __init__(self, config: dict = None):
        conf = config or {}
        self._schema = conf.get("schema", "nexus")
        self._resolvers: dict[str, Resolver] = {}
        self._llms: dict[str, LLMProvider] = {}
        self._default_llm: Optional[str] = None

    @property
    def _db(self) -> sql_db:
        return services[sql_db]

    @property
    def _cred(self) -> azure_keyvault_credential_provider:
        return services[azure_keyvault_credential_provider]

    # ── 装配 ──
    def _resolve_config(self, base_config: str, credential_name: Optional[str]) -> dict:
        conf = json.loads(base_config or "{}")
        if credential_name:
            cred = self._cred.load(credential_name)
            if cred:
                conf = {**conf, **cred.to_config()}
            else:
                _logger.warning(f"credential not loaded: {credential_name}")
        return conf

    def load(self) -> "ResolverRegistry":
        """从 DB 注册表加载所有 active 的 resolver 与 llm。"""
        # resolvers
        for r in self._db.execute_query(
            f"SELECT resolver_name, resolver_type, config, credential_name FROM {self._schema}.resolvers WHERE is_active = 1"
        ):
            rtype = r["resolver_type"]
            cls = _RESOLVER_TYPES.get(rtype)
            if not cls:
                _logger.warning(f"unknown resolver_type: {rtype} ({r['resolver_name']})")
                continue
            conf = self._resolve_config(r["config"], r["credential_name"])
            self._resolvers[r["resolver_name"]] = cls(r["resolver_name"], conf)
            _logger.info(f"resolver loaded: {r['resolver_name']} ({rtype})")

        # llms
        for r in self._db.execute_query(
            f"SELECT llm_name, provider, config, credential_name, is_default FROM {self._schema}.llms WHERE is_active = 1"
        ):
            provider = r["provider"]
            cls = _LLM_PROVIDERS.get(provider)
            if not cls:
                _logger.warning(f"unknown llm provider: {provider} ({r['llm_name']})")
                continue
            conf = self._resolve_config(r["config"], r["credential_name"])
            self._llms[r["llm_name"]] = cls(r["llm_name"], conf)
            if r.get("is_default"):
                self._default_llm = r["llm_name"]
            _logger.info(f"llm loaded: {r['llm_name']} ({provider})")

        if self._default_llm is None and self._llms:
            self._default_llm = next(iter(self._llms))
        return self

    def reload(self) -> "ResolverRegistry":
        """清空并从 DB 重新装配（供源/凭据/LLM 管理保存后即时生效，免重启）。"""
        self._resolvers = {}
        self._llms = {}
        self._default_llm = None
        return self.load()

    # ── 手动注册（可选）──
    def register_resolver(self, resolver: Resolver) -> None:
        self._resolvers[resolver.name] = resolver

    def register_llm(self, name: str, llm: LLMProvider, default: bool = False) -> None:
        self._llms[name] = llm
        if default or self._default_llm is None:
            self._default_llm = name

    # ── 访问 ──
    def resolver(self, name: str) -> Optional[Resolver]:
        return self._resolvers.get(name)

    def all_resolvers(self) -> list[Resolver]:
        return list(self._resolvers.values())

    def resolvers_of_type(self, rtype: str) -> list[Resolver]:
        return [r for r in self._resolvers.values() if r.resolver_type == rtype]

    def llm(self, name: Optional[str] = None) -> Optional[LLMProvider]:
        return self._llms.get(name or self._default_llm) if (name or self._default_llm) else None

    def list_llms(self) -> list[dict]:
        """规划用 LLM 目录（供提问界面下拉）：name + is_default，不含任何密文。"""
        return [{"name": n, "is_default": n == self._default_llm} for n in self._llms]

    def capabilities(self) -> list[dict]:
        return [r.capabilities() for r in self._resolvers.values()]
