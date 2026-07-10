"""生成器：把结果写成答案 + 出处（每个数字可追溯来源）。"""

from __future__ import annotations

from decimal import Decimal

from nexus.core.models import SQG, QueryPlan, Answer, LineageItem, ExecContext


def _norm(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


class Generator:
    def generate(self, sqg: SQG, plan: QueryPlan, ctx: ExecContext) -> Answer:
        parts, lineage, data_nodes = [], [], []
        status = "ok"

        # 编译期硬错误（如编译失败）：compiler 已框好「编译失败：…」，直接作为答案报出。
        cerr = (sqg.context or {}).get("error")
        if cerr and not sqg.nodes:
            return Answer(run_id=ctx.run_id, question=sqg.question,
                          text=cerr, status="error")

        for node in sqg.nodes:
            res = ctx.results.get(node.id)
            if res is None:
                continue
            if res.error:
                status = "error"
                parts.append(f"{node.name}：取数失败（{res.error}）")
                continue

            kind = node.result_kind()

            # 分组/排名：多行 label + value
            if kind == "ranking":
                ranked = [(r.get("label"), _norm(r.get("value"))) for r in (res.rows or [])]
                listed = "、".join(f"{lbl}({val})" for lbl, val in ranked)
                parts.append(f"{node.name}：{listed}")
                data_nodes.append({"node_id": node.id, "name": node.name,
                                   "items": [{"label": l, "value": v} for l, v in ranked]})
                lineage.append(LineageItem(
                    node_id=node.id, label=node.name, value=listed,
                    resolver=res.resolver, source=res.source, detail=res.detail))
                continue

            # 维度去重列举：多行、只有 value（如「列出所有产品」）——逐个列出
            if kind == "list":
                vals = [_norm(r.get("value", next(iter(r.values()), None))) for r in (res.rows or [])]
                listed = "、".join("" if v is None else str(v) for v in vals)
                parts.append(f"{node.name}（{len(vals)}）：{listed}")
                data_nodes.append({"node_id": node.id, "name": node.name,
                                   "items": [{"value": v} for v in vals]})
                lineage.append(LineageItem(
                    node_id=node.id, label=node.name, value=listed,
                    resolver=res.resolver, source=res.source, detail=res.detail))
                continue

            # 单值 / 文本(ASK) / 动作(ACT)
            value = None
            if res.rows:
                first = res.rows[0]
                value = first.get("value", next(iter(first.values()), None))
            value = _norm(value)

            parts.append(f"{node.name} = {value}")
            data_nodes.append({"node_id": node.id, "name": node.name, "value": value})
            lineage.append(LineageItem(
                node_id=node.id,
                label=node.name,
                value=(str(value) if value is not None else None),
                resolver=res.resolver,
                source=res.source,
                detail=res.detail,
            ))

        text = "；".join(parts) if parts else "没有可用结果。"
        return Answer(
            run_id=ctx.run_id,
            question=sqg.question,
            text=text,
            data={"nodes": data_nodes},
            lineage=lineage,
            status=status,
        )
