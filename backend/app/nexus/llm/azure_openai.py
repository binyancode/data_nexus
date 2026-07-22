"""Azure OpenAI Provider（openai SDK）。config 来自 azure_openai_credential.to_config()。"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
import time
from typing import Any, Optional

from nexus.llm.base import LLMCompletion, LLMProvider


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
        return self.complete_with_metadata(messages, schema=schema, **kwargs).output

    def complete_with_metadata(self, messages: list[dict], schema: Optional[dict] = None,
                               **kwargs) -> LLMCompletion:
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        req: dict[str, Any] = {"model": self._deployment, "messages": messages}
        if schema is not None:
            req["response_format"] = {"type": "json_object"}
        req.update(kwargs)
        resp = self._client.chat.completions.create(**req)
        content = resp.choices[0].message.content
        output: Any = content
        if schema is not None and content:
            try:
                output = json.loads(content)
            except json.JSONDecodeError:
                output = content

        usage_raw = resp.usage.model_dump(mode="json") if resp.usage is not None else None
        prompt_details = (usage_raw or {}).get("prompt_tokens_details") or {}
        completion_details = (usage_raw or {}).get("completion_tokens_details") or {}
        input_tokens = (usage_raw or {}).get("prompt_tokens")
        cached_tokens = prompt_details.get("cached_tokens")
        usage = None
        if usage_raw is not None:
            usage = {
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_tokens,
                "uncached_input_tokens": (
                    max(0, input_tokens - cached_tokens)
                    if input_tokens is not None and cached_tokens is not None else None
                ),
                "cache_write_input_tokens": prompt_details.get("cache_write_tokens"),
                "output_tokens": usage_raw.get("completion_tokens"),
                "reasoning_tokens": completion_details.get("reasoning_tokens"),
                "total_tokens": usage_raw.get("total_tokens"),
                "input_token_details": prompt_details,
                "output_token_details": completion_details,
            }

        choice = resp.choices[0]
        output_log: dict[str, Any] = {"content": content}
        if isinstance(output, (dict, list)):
            output_log["parsed"] = copy.deepcopy(output)
        return LLMCompletion(output=output, log={
            "provider": self.resolver_type,
            "llm_name": self.name,
            "model": getattr(resp, "model", None),
            "deployment": self._deployment,
            "request_id": getattr(resp, "_request_id", None),
            "response_id": getattr(resp, "id", None),
            "finish_reason": getattr(choice, "finish_reason", None),
            "started_at": started_at,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "input": {
                "messages": copy.deepcopy(messages),
                "response_format": req.get("response_format"),
                "request_options": {
                    key: value for key, value in req.items()
                    if key not in {"messages", "model", "response_format"}
                },
            },
            "output": output_log,
            "usage": usage,
        })
