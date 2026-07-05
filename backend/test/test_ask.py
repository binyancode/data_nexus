"""测试 /ask 的脚本（直接调用 NexusClient，无需启动服务）。

用法（在 backend/test 下，用项目 venv 运行）：
    ..\\.venv\\Scripts\\python.exe test_ask.py                     # 交互式，逐行输入问题
    ..\\.venv\\Scripts\\python.exe test_ask.py "华东上季度毛利"     # 单个问题
    ..\\.venv\\Scripts\\python.exe test_ask.py "华东毛利" "华南毛利" # 多个问题
"""

import os
import sys

# 让 backend/app 在导入路径上（本脚本在 backend/test 下）
_APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from bootstrap import register_services
from core.services import services
from nexus.client import NexusClient


def _print_answer(question: str, nexus: NexusClient) -> None:
    ans = nexus.ask(question)
    print(f"\nQ: {question}")
    print(f"A: {ans.text}   [status={ans.status}]")
    for li in ans.lineage:
        print(f"   · {li.label} = {li.value}")
        print(f"     来源: {li.source}")
        print(f"     口径: {li.detail}")
    print(f"   run_id: {ans.run_id}")


def main() -> None:
    register_services()
    nexus = services[NexusClient]

    questions = sys.argv[1:]
    if questions:
        for q in questions:
            _print_answer(q, nexus)
        return

    # 交互式：逐行输入，空行或 q/quit/exit 退出
    print("输入问题回车提问；空行或 q 退出。")
    while True:
        try:
            q = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q or q.lower() in ("q", "quit", "exit"):
            break
        try:
            _print_answer(q, nexus)
        except Exception as exc:
            print(f"[错误] {exc}")


if __name__ == "__main__":
    main()
