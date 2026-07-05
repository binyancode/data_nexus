"""Azure OpenAI Provider（openai SDK）。config 来自 azure_openai_credential.to_config()。"""

from __future__ import annotations

import json
from typing import Any, Optional

from nexus.llm.base import LLMProvider


class AzureOpenAIProvider(LLMProvider):
    resolver_type = "azure_openai"

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        from openai import AzureOpenAI

        self._deployment = self.config.get("deployment") or self.config.get("model")
        self._client = AzureOpenAI(
            azure_endpoint=self.config["endpoint"],
            api_key=self.config["key"],
            api_version=self.config.get("api_version", "2024-06-01"),
        )

    def complete(self, messages: list[dict], schema: Optional[dict] = None, **kwargs) -> Any:
        req: dict[str, Any] = {"model": self._deployment, "messages": messages}
        if schema is not None:
            req["response_format"] = {"type": "json_object"}
        req.update(kwargs)
        resp = self._client.chat.completions.create(**req)
        content = resp.choices[0].message.content
        if schema is not None and content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return content
        return content
