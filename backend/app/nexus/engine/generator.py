"""生成器 Generator：合并结果 + verdict → 最终答案（可流式）+ 血缘。

职责：用合并数据写出自然语言答案（可套模板）；附血缘（每个数字/结论来自哪个
节点/Resolver/信任分/裁决记录）；附动作回执。
"""
from typing import Any, AsyncIterator


class Answer:
    def __init__(self, text: str, lineage: list[Any] | None = None):
        self.text = text
        self.lineage = lineage or []


class Generator:
    def __init__(self, llm: Any = None):
        self.llm = llm

    async def generate(self, merged: dict, verdict: dict) -> Answer:
        # TODO(P0): 用合并数据 + verdict 生成答案文本 + 血缘
        raise NotImplementedError("Generator.generate 尚未实现（P0）")

    async def stream(self, merged: dict, verdict: dict) -> AsyncIterator[str]:
        # TODO: 流式输出（SSE）
        raise NotImplementedError("Generator.stream 尚未实现")
        yield  # pragma: no cover
