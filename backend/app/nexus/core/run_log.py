"""运行记录：Nexus 五段引擎执行过程的记录接口（依赖倒置）。

- RunRecorder：记录接口。nexus 引擎只依赖此接口，不碰 DB。
- NullRunRecorder：空实现，未注册记录器时的默认（不落库）。
- register_run_recorder / get_run_recorder：app 层把 DB 实现注册进来。

生命周期（增量落库，供前端轮询看进度）：
    start_run → [start_stage → (start_node → finish_node)* → finish_stage]×5 → finish_run
三层对应三张表：run / run_stage / run_node（见设计文档 §24）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class RunRecorder(ABC):
    """运行记录接口。实现类把每次运行的 run/stage/node 事件落到目的地（DB 等）。"""

    # ── run（整体）──
    @abstractmethod
    def start_run(self, run_id: str, question: str, as_user: Optional[str],
                  context: Optional[str] = None) -> None: ...

    @abstractmethod
    def finish_run(self, run_id: str, state: str, answer: Optional[str], cost_ms: int) -> None: ...

    @abstractmethod
    def set_run_context(self, run_id: str, context: Optional[str]) -> None: ...

    # ── stage（四个引擎）──
    @abstractmethod
    def start_stage(self, run_id: str, stage: str, input: Optional[str]) -> None: ...

    @abstractmethod
    def finish_stage(self, run_id: str, stage: str, state: str,
                     output: Optional[str], error: Optional[str], cost_ms: int,
                     logs: Optional[str] = None) -> None: ...

    # ── node（协调器 DAG 节点）──
    @abstractmethod
    def start_node(self, run_id: str, node_id: str, resolver: str, call: Optional[str]) -> None: ...

    @abstractmethod
    def finish_node(self, run_id: str, node_id: str, state: str, call: Optional[str],
                    output: Optional[str], value: Optional[str], source: str, trust: float,
                    error: Optional[str], cost_ms: int, logs: Optional[str] = None) -> None: ...


class NullRunRecorder(RunRecorder):
    """空记录器：不落库（默认 / 测试用）。"""

    def start_run(self, run_id, question, as_user, context=None): pass
    def finish_run(self, run_id, state, answer, cost_ms): pass
    def set_run_context(self, run_id, context): pass
    def start_stage(self, run_id, stage, input): pass
    def finish_stage(self, run_id, stage, state, output, error, cost_ms, logs=None): pass
    def start_node(self, run_id, node_id, resolver, call): pass
    def finish_node(self, run_id, node_id, state, call, output, value, source, trust, error, cost_ms, logs=None): pass


_NULL = NullRunRecorder()
_recorder: RunRecorder = _NULL


def register_run_recorder(recorder: RunRecorder) -> None:
    """app 层注册 DB 记录器（依赖倒置：DB 依赖留在 app，nexus 只认接口）。"""
    global _recorder
    if not isinstance(recorder, RunRecorder):
        raise TypeError(f"recorder 必须实现 RunRecorder：{type(recorder)!r}")
    _recorder = recorder


def get_run_recorder() -> RunRecorder:
    """取当前记录器；未注册则返回空实现。"""
    return _recorder
