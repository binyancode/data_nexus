"""LLM Provider 抽象。多个 LLM 可注册，各自的密钥走 credential/KV。"""

from __future__ import annotations

from abc import ABC, abstractmethod
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from typing import Any, Optional


@dataclass
class LLMCompletion:
    output: Any
    log: dict[str, Any]


def _logged_output(output: Any) -> dict[str, Any]:
    if isinstance(output, (dict, list)):
        return {"parsed": copy.deepcopy(output)}
    return {"content": output}


def complete_with_logging(llm, messages: list[dict], schema: Optional[dict] = None,
                          *, logs: list[dict], purpose: str,
                          metadata: Optional[dict] = None, **kwargs) -> Any:
    """Invoke any LLM provider and always append one serializable call record.

    Providers that implement ``complete_with_metadata`` supply native usage details.
    Duck-typed/fake providers remain compatible and receive timing/input/output logs
    with token values left unavailable.
    """
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    try:
        traced = getattr(llm, "complete_with_metadata", None)
        if callable(traced):
            completion = traced(messages, schema=schema, **kwargs)
            call = dict(completion.log)
            output = completion.output
        else:
            output = llm.complete(messages, schema=schema, **kwargs)
            call = {
                "provider": getattr(llm, "resolver_type", type(llm).__name__),
                "llm_name": getattr(llm, "name", None),
                "model": None,
                "deployment": None,
                "request_id": None,
                "response_id": None,
                "finish_reason": None,
                "started_at": started_at,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "input": {
                    "messages": copy.deepcopy(messages),
                    "response_format": {"type": "json_object"} if schema is not None else None,
                },
                "output": _logged_output(output),
                "usage": None,
            }
        call["purpose"] = purpose
        if metadata:
            call["metadata"] = dict(metadata)
        logs.append(call)
        return output
    except Exception as exc:
        logs.append({
            "purpose": purpose,
            "metadata": dict(metadata or {}),
            "provider": getattr(llm, "resolver_type", type(llm).__name__),
            "llm_name": getattr(llm, "name", None),
            "model": None,
            "deployment": None,
            "request_id": None,
            "response_id": None,
            "finish_reason": None,
            "started_at": started_at,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "input": {
                "messages": copy.deepcopy(messages),
                "response_format": {"type": "json_object"} if schema is not None else None,
            },
            "output": None,
            "usage": None,
            "error": str(exc),
        })
        raise


class LLMProvider(ABC):
    resolver_type: str = "llm"

    def __init__(self, name: str, config: dict = None):
        self.name = name
        self.config = config or {}

    @abstractmethod
    def complete(self, messages: list[dict], schema: Optional[dict] = None, **kwargs) -> Any:
        """给定对话消息，返回文本（或按 schema 的结构化结果）。"""
        ...
