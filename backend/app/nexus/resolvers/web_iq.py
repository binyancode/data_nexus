"""Microsoft Web IQ Resolver：公开 Web 搜索 + 指定 URL 浏览。

官方 API：
- POST https://api.microsoft.ai/v3/search/web
- POST https://api.microsoft.ai/v3/browse
认证：x-apikey；Search 返回 webResults[]；Browse 的实时抓取可能先返回 202 + retryAfter。
"""

from __future__ import annotations

import re
import time
from typing import Any, Optional

import httpx

from nexus.core.models import ExecContext, NodeResult
from nexus.resolvers.base import Resolver

_SEARCH_URL = "https://api.microsoft.ai/v3/search/web"
_BROWSE_URL = "https://api.microsoft.ai/v3/browse"
_RETRYABLE = {429, 430, 500, 503, 504}
_RETRY_AFTER = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*s?\s*$", re.I)


class WebIqResolver(Resolver):
    resolver_type = "web_iq"
    provides_concepts = False
    operators = {"SEARCH", "BROWSE"}

    def __init__(self, name: str, config: dict = None):
        super().__init__(name, config)
        api_key = (self.config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError(f"Web IQ resolver {name!r} missing api_key")
        self._api_key = api_key
        self._timeout_s = self._number("timeout_s", 60.0, minimum=1, maximum=300)
        self._max_retries = self._integer("max_retries", 3, minimum=0, maximum=10)
        self._browse_max_wait_s = self._number("browse_max_wait_s", 180.0, minimum=1, maximum=900)
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout_s),
            headers={
                "host": "api.microsoft.ai",
                "x-apikey": self._api_key,
                "content-type": "application/json",
            },
        )

    def close(self) -> None:
        self._client.close()

    def fetch(self, call: dict, ctx: Optional[ExecContext] = None) -> NodeResult:
        node_id = call.get("node_id", "")
        mode = (call.get("mode") or "").lower()
        try:
            if mode == "search":
                return self._search(node_id, call, ctx)
            if mode == "browse":
                return self._browse(node_id, call, ctx)
            return NodeResult(node_id=node_id, resolver=self.name,
                              error=f"unsupported Web IQ mode: {mode or '(empty)'}",
                              source=f"{self.name}:web-iq")
        except Exception as exc:
            return NodeResult(
                node_id=node_id,
                resolver=self.name,
                error=str(exc),
                source=f"{self.name}:web-iq-{mode or 'unknown'}",
                detail=(call.get("query") or call.get("url") or "")[:500],
                logs={"mode": mode, "request": self._safe_call(call)},
            )

    def _search(self, node_id: str, call: dict, ctx: Optional[ExecContext]) -> NodeResult:
        query = (call.get("query") or "").strip()
        if not query:
            raise ValueError("Web IQ SEARCH 缺少 query")
        if len(query) > 1000:
            raise ValueError("Web IQ SEARCH query 超过 1000 字符")

        payload: dict[str, Any] = {
            "query": query,
            "maxResults": self._call_int(call, "max_results", "search_max_results", 10, 1, 50),
            "language": self._call_str(call, "language", "language", "en"),
            "region": self._call_str(call, "region", "region", "US"),
            "maxLength": self._call_int(call, "max_length", "search_max_length", 10000, 1, 500000),
            "contentFormat": self._call_str(call, "content_format", "search_content_format", "passage"),
        }
        location = call.get("location") or self.config.get("location")
        if location:
            payload["location"] = str(location)

        data = self._post(_SEARCH_URL, payload, "search", ctx)
        raw = data.get("webResults") or []
        if not isinstance(raw, list):
            raise ValueError("Web IQ SEARCH 响应 webResults 不是数组")
        include_adult = bool(call.get("include_adult", self.config.get("include_adult", False)))
        rows = [self._search_row(x) for x in raw
                if isinstance(x, dict) and (include_adult or not x.get("isAdult"))]
        output = "\n\n".join(
            f"[{i}] {r.get('title') or '(无标题)'}\n{r.get('url') or ''}\n{r.get('content') or ''}"
            for i, r in enumerate(rows, start=1)
        )
        return NodeResult(
            node_id=node_id, resolver=self.name, output=output,
            columns=["title", "url", "content", "crawledAt", "lastUpdatedAt", "language"],
            rows=rows, trust=0.75, source=f"{self.name}:web-iq-search", detail=query,
            logs={"mode": "search", "request": payload, "trace_id": data.get("traceId"),
                  "result_count": len(rows)},
        )

    def _browse(self, node_id: str, call: dict, ctx: Optional[ExecContext]) -> NodeResult:
        url = (call.get("url") or "").strip()
        if not url:
            raise ValueError("Web IQ BROWSE 缺少 url")
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("Web IQ BROWSE url 必须是 http/https URL")

        payload: dict[str, Any] = {
            "url": url,
            "maxLength": self._call_int(call, "max_length", "browse_max_length", 20000, 1, 500000),
            "liveCrawl": self._call_str(call, "live_crawl", "browse_live_crawl", "fallback"),
            "renderDynamicPages": self._call_bool(call, "render_dynamic_pages", "browse_render_dynamic_pages", True),
            "includeWebLinks": self._call_bool(call, "include_web_links", "browse_include_web_links", False),
            "includeImageLinks": self._call_bool(call, "include_image_links", "browse_include_image_links", False),
            "language": self._call_str(call, "language", "language", "en"),
            "region": self._call_str(call, "region", "region", "US"),
            "contentFormat": self._call_str(call, "content_format", "browse_content_format", "markdown"),
        }
        data = self._post(_BROWSE_URL, payload, "browse", ctx)
        row = {k: data.get(k) for k in (
            "title", "url", "content", "lastUpdatedAt", "crawledAt", "isAdult", "webLinks", "imageLinks"
        ) if data.get(k) is not None}
        content = str(data.get("content") or "")
        output = f"{data.get('title') or '(无标题)'}\n{data.get('url') or url}\n{content}"
        return NodeResult(
            node_id=node_id, resolver=self.name, output=output,
            columns=list(row.keys()), rows=[row], trust=0.75,
            source=str(data.get("url") or url), detail=url,
            logs={"mode": "browse", "request": payload, "trace_id": data.get("traceId")},
        )

    def _post(self, url: str, payload: dict, mode: str,
              ctx: Optional[ExecContext]) -> dict:
        deadline = time.monotonic() + (self._browse_max_wait_s if mode == "browse" else self._timeout_s)
        transient = 0
        while True:
            self._check_cancelled(ctx)
            try:
                response = self._client.post(url, json=payload)
            except httpx.RequestError as exc:
                if transient >= self._max_retries:
                    raise RuntimeError(f"Web IQ 网络请求失败：{exc}") from exc
                transient += 1
                self._wait(min(2 ** (transient - 1), 8), deadline, ctx)
                continue

            data = self._json(response)
            if response.status_code == 200:
                if not isinstance(data, dict):
                    raise ValueError("Web IQ 响应不是 JSON 对象")
                return data

            if mode == "browse" and response.status_code == 202:
                delay = self._retry_after(response, data, default=2.0)
                self._wait(delay, deadline, ctx)
                continue

            if response.status_code in _RETRYABLE and transient < self._max_retries:
                transient += 1
                delay = self._retry_after(response, data, default=min(2 ** (transient - 1), 8))
                self._wait(delay, deadline, ctx)
                continue

            message = self._error_text(response, data)
            raise RuntimeError(f"Web IQ {mode.upper()} 失败：HTTP {response.status_code}，{message}")

    @staticmethod
    def _json(response: httpx.Response):
        try:
            return response.json()
        except Exception:
            return None

    @staticmethod
    def _error_text(response: httpx.Response, data) -> str:
        if isinstance(data, dict):
            value = data.get("message") or data.get("error") or data.get("detail")
            if value:
                return str(value)[:1000]
        return (response.text or "无响应内容")[:1000]

    @staticmethod
    def _retry_after(response: httpx.Response, data, default: float) -> float:
        raw = None
        if isinstance(data, dict):
            raw = data.get("retryAfter")
        raw = raw or response.headers.get("retry-after")
        match = _RETRY_AFTER.match(str(raw or ""))
        return max(0.0, float(match.group(1))) if match else float(default)

    def _wait(self, seconds: float, deadline: float, ctx: Optional[ExecContext]) -> None:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or seconds > remaining:
            raise TimeoutError("Web IQ 请求等待超时")
        # 小步等待，便于取消长时间 live crawl。
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self._check_cancelled(ctx)
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    @staticmethod
    def _check_cancelled(ctx: Optional[ExecContext]) -> None:
        token = getattr(ctx, "cancellation_token", None) if ctx else None
        if token and getattr(token, "is_cancelled", False):
            raise RuntimeError("Web IQ 请求已取消")

    @staticmethod
    def _search_row(item: dict) -> dict:
        return {k: item.get(k) for k in (
            "title", "url", "content", "crawledAt", "lastUpdatedAt", "language",
            "isAdult", "clickUrl", "instrumentationSuffix", "contentTier"
        ) if item.get(k) is not None}

    @staticmethod
    def _safe_call(call: dict) -> dict:
        return {k: v for k, v in call.items() if k not in {"api_key", "x-apikey", "authorization"}}

    def _integer(self, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _number(self, key: str, default: float, minimum: float, maximum: float) -> float:
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _call_int(self, call: dict, call_key: str, config_key: str,
                  default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(call.get(call_key, self.config.get(config_key, default)))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _call_str(self, call: dict, call_key: str, config_key: str, default: str) -> str:
        return str(call.get(call_key) or self.config.get(config_key) or default)

    def _call_bool(self, call: dict, call_key: str, config_key: str, default: bool) -> bool:
        value = call.get(call_key, self.config.get(config_key, default))
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
