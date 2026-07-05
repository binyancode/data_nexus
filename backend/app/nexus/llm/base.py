"""LLM Provider 抽象。多个 LLM 可注册，各自的密钥走 credential/KV。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMProvider(ABC):
    resolver_type: str = "llm"

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}

    @abstractmethod
    def complete(self, messages: list[dict], schema: Optional[dict] = None, **kwargs) -> Any:
        """给定对话消息，返回文本（或按 schema 的结构化结果）。"""
        ...
