"""能力清单：Resolver 自报「能答哪些概念、成本、时效、信任分、是否支持用户级权限」。"""
from typing import Optional

from pydantic import BaseModel, Field


class Capabilities(BaseModel):
    resolver: str
    concepts: list[str] = Field(default_factory=list)   # 覆盖的 Concept id
    operators: list[str] = Field(default_factory=list)  # 支持的 SQG 算子
    cost: float = 0.5           # 相对成本 0~1
    latency_ms: int = 500       # 典型时延
    trust: float = 0.8          # 信任分（裁决权重）
    user_scoped: bool = False   # 是否支持用户级权限（行级安全）
    freshness: Optional[str] = None
