"""ActionResolver：ACT 算子的执行体 —— 执行一个动作（演示版：建复盘任务，返回工单号）。

真实场景应对接工单/审批系统；此处 mock，仅生成任务号 + 回执，验证「分析 → 行动」闭环。
"""

from __future__ import annotations

import uuid
from typing import Optional

from nexus.core.models import NodeResult, ExecContext
from nexus.resolvers.base import Resolver


class ActionResolver(Resolver):
    resolver_type = "action"

    def fetch(self, call: dict, ctx: Optional[ExecContext] = None) -> NodeResult:
        node_id = call.get("node_id", "")
        action = call.get("action") or "create_task"
        desc = call.get("desc") or call.get("title") or ""
        assignee = call.get("assignee") or ""
        task_id = "TASK-" + uuid.uuid4().hex[:6].upper()
        receipt = f"{task_id} 已创建"
        if assignee:
            receipt += f"（负责人：{assignee}）"
        out = {"action": action, "task_id": task_id, "status": "created",
               "assignee": assignee, "desc": desc}
        return NodeResult(
            node_id=node_id, resolver=self.name, output=out,
            rows=[{"value": receipt}], trust=1.0,
            source=f"{self.name}:{action}", detail=desc[:300],
        )
