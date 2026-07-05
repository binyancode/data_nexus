"""
CancellationToken — 轻量级协作式取消令牌。

类比 C# 的 CancellationTokenSource / CancellationToken，
但合并为单一类，简化使用。

核心特性:
  - 线程安全（基于 threading.Event 实现）
  - 支持阻塞等待取消信号
  - 支持注册取消回调（取消时自动触发）
  - 一次性语义：cancel() 后不可重置
  - 支持 parent 链式继承：父 token 取消时，子 token 自动感知（向下传导，不向上影响）

使用场景:

  1. Pipeline 级别:
     pipeline.run() 创建 token → 注入 context["__cancellation_token"]
     pipeline.cancel() → token.cancel()
     node.process() 从 context 取出 token → 传给 task_pool 或自行检查

  2. 独立使用 task_pool:
     token = cancellation_token()
     run_id = pool.add_task(user, func, timeout, retries, *args, cancellation_token=token)
     # 另一个线程中: token.cancel()
     result = pool.wait_for_completion(run_id, timeout=60, cancellation_token=token)

  3. Task 函数内检查:
     def my_task(data, cancellation_token=None):
         for chunk in chunks:
             if cancellation_token:
                 cancellation_token.raise_if_cancelled()
             process(chunk)
"""

from __future__ import annotations

import threading
from typing import Callable


class CancelledError(Exception):
    """取消操作引发的异常。

    当调用 cancellation_token.raise_if_cancelled() 且 token 已被取消时抛出。
    task_pool 会捕获此异常并将任务状态记录为 "cancelled"。
    """
    pass


class cancellation_token:
    """协作式取消令牌。

    线程安全，基于 threading.Event 实现。

    Methods
    -------
    cancel()
        触发取消信号，唤醒所有等待者，执行所有已注册的回调。
    raise_if_cancelled()
        若已取消则抛出 CancelledError。
    wait(timeout=None) -> bool
        阻塞等待取消信号，返回是否在超时前被取消。
    on_cancelled(callback)
        注册取消回调。若注册时已取消，立即执行。

    Properties
    ----------
    is_cancelled : bool
        是否已被取消。
    """

    def __init__(self, parent: "cancellation_token | None" = None):
        self._event = threading.Event()
        self._callbacks: list[Callable] = []
        self._lock = threading.Lock()
        self._parent: cancellation_token | None = parent

    @property
    def is_cancelled(self) -> bool:
        """是否已被取消（含 parent 链式检查）。

        若自身已取消、或任意祖先 token 已取消，均返回 True。
        取消信号只向下传导，不向上影响。
        """
        if self._event.is_set():
            return True
        if self._parent is not None and self._parent.is_cancelled:
            return True
        return False

    def cancel(self) -> None:
        """触发取消。

        - 设置取消标记（唤醒所有 wait() 中的线程）
        - 依次执行所有已注册的回调（回调异常不会阻断后续回调）
        - 幂等操作，多次调用无副作用
        """
        if self._event.is_set():
            return
        self._event.set()
        with self._lock:
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb()
            except Exception:
                pass  # 回调异常不影响取消流程

    def raise_if_cancelled(self, message: str = "Operation was cancelled.") -> None:
        """若已取消（含 parent 链）则抛出 CancelledError。

        Parameters
        ----------
        message : str
            异常消息。
        """
        if self.is_cancelled:
            raise CancelledError(message)

    def wait(self, timeout: float | None = None) -> bool:
        """阻塞等待取消信号。

        Parameters
        ----------
        timeout : float | None
            等待超时时间（秒），None 表示无限等待。

        Returns
        -------
        bool
            True 表示已被取消，False 表示超时仍未取消。
        """
        return self._event.wait(timeout=timeout)

    def on_cancelled(self, callback: Callable) -> None:
        """注册取消回调。

        如果注册时 token 已被取消，回调会立即执行。

        Parameters
        ----------
        callback : Callable
            无参回调函数。
        """
        with self._lock:
            if self._event.is_set():
                # 已取消，立即执行
                try:
                    callback()
                except Exception:
                    pass
            else:
                self._callbacks.append(callback)

    def __repr__(self) -> str:
        return f"<cancellation_token cancelled={self.is_cancelled} has_parent={self._parent is not None}>"
