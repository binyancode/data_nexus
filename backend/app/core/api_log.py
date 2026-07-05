"""API 日志：结构化记录 + 日志汇接口（依赖倒置）。

- ApiLogRecord：一条 API 日志的结构化数据。
- ApiLogSink：日志汇接口，外部实现（写 DB / 发队列 / 上报 APM…）后注册给 api_handler。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class ApiLogRecord:
    """一条 API 调用日志。"""
    function: str
    method: str
    path: str
    state: str                          # success | error | denied | unauthorized | failed
    user: Optional[str] = None
    payload: Optional[str] = None
    response: Optional[str] = None
    message: Optional[str] = None        # 出错时的完整堆栈（用于定位报错行）；成功/未触发异常时为 None
    cost_ms: int = 0
    source: str = "backend"              # backend | bff
    request_time: Optional[datetime] = None
    response_time: Optional[datetime] = None


class ApiLogSink(ABC):
    """API 日志汇接口。实现 emit 把一条日志送到目的地（DB、队列、APM 等）。"""

    @abstractmethod
    def emit(self, record: ApiLogRecord) -> None:
        ...
