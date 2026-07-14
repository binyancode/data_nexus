"""生成器：把结果写成答案 + 出处（每个数字可追溯来源）。"""

from __future__ import annotations

import math
import re
from decimal import Decimal

from nexus.core.models import SQG, QueryPlan, Answer, LineageItem, ExecContext


def _norm(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def _display(v) -> str:
    """面向人的稳定数值格式，避免 42993961.88999998 之类浮点噪声。"""
    v = _norm(v)
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        if not math.isfinite(v):
            return str(v)
        return f"{v:,.6f}".rstrip("0").rstrip(".")
    return str(v)


def _md_cell(v) -> str:
    """转义 GFM 表格单元格；保留换行语义。"""
    return _display(v).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def _md_table(headers: list[str], rows: list[list]) -> str:
    head = "| " + " | ".join(_md_cell(x) for x in headers) + " |"
    split = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_md_cell(x) for x in row) + " |" for row in rows]
    return "\n".join([head, split, *body])


def _md_link(url: str, label: str = "查看原文") -> str:
    if not url:
        return "—"
    return f"[{label}](<{url.replace('>', '%3E')}>)"


def _excerpt(content, limit: int = 240) -> str:
    text = re.sub(r"<[^>]+>", " ", str(content or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


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
                parts.append(f"> **{_md_cell(node.name)}执行失败**：{_md_cell(res.error)}")
                continue

            kind = node.result_kind()

            if kind == "search":
                items = list(res.rows or [])
                rows = [[i, r.get("title") or "(无标题)", _excerpt(r.get("content")),
                         _md_link(str(r.get("url") or ""))]
                        for i, r in enumerate(items, start=1)]
                parts.append(
                    f"## {_md_cell(node.name)}\n\n{_md_table(['#', '标题', '摘要', '来源'], rows)}"
                    if rows else f"## {_md_cell(node.name)}\n\n> 未找到结果。"
                )
                data_nodes.append({"node_id": node.id, "name": node.name, "items": items})
                for r in items:
                    url = str(r.get("url") or "")
                    lineage.append(LineageItem(
                        node_id=node.id, label=str(r.get("title") or node.name), value=url,
                        resolver=res.resolver, source=url or res.source,
                        detail=str(r.get("content") or "")))
                continue

            if kind == "document":
                row = (res.rows or [{}])[0]
                title = str(row.get("title") or node.name)
                url = str(row.get("url") or res.source or "")
                content = str(row.get("content") or res.output or "")
                preview = content[:2000] + ("…" if len(content) > 2000 else "")
                parts.append(f"## {_md_cell(title)}\n\n{_md_link(url)}\n\n{preview}")
                data_nodes.append({"node_id": node.id, "name": node.name,
                                   "document": row, "content": content})
                lineage.append(LineageItem(
                    node_id=node.id, label=title, value=url,
                    resolver=res.resolver, source=url, detail=content))
                continue

            # 分组/排名：多行 label + value
            if kind == "ranking":
                ranked = [(r.get("label"), _norm(r.get("value"))) for r in (res.rows or [])]
                listed = "、".join(f"{lbl}({_display(val)})" for lbl, val in ranked)
                rows = [[i, label, value] for i, (label, value) in enumerate(ranked, start=1)]
                parts.append(f"## {_md_cell(node.name)}\n\n{_md_table(['排名', '项目', '值'], rows)}")
                data_nodes.append({"node_id": node.id, "name": node.name,
                                   "items": [{"label": l, "value": v} for l, v in ranked]})
                lineage.append(LineageItem(
                    node_id=node.id, label=node.name, value=listed,
                    resolver=res.resolver, source=res.source, detail=res.detail))
                continue

            # 维度去重列举：多行、只有 value（如「列出所有产品」）——逐个列出
            if kind == "list":
                vals = [_norm(r.get("value", next(iter(r.values()), None))) for r in (res.rows or [])]
                listed = "、".join(_display(v) for v in vals)
                rows = [[i, value] for i, value in enumerate(vals, start=1)]
                parts.append(f"## {_md_cell(node.name)}（{len(vals)} 项）\n\n{_md_table(['#', '值'], rows)}")
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

            if kind == "text":
                parts.append(f"## {_md_cell(node.name)}\n\n{_display(value)}")
            elif kind == "action":
                parts.append(f"## {_md_cell(node.name)}\n\n> {_md_cell(value)}")
            else:
                parts.append(f"## 查询结果\n\n{_md_table(['指标', '值'], [[node.name, value]])}")
            data_nodes.append({"node_id": node.id, "name": node.name, "value": value})
            lineage.append(LineageItem(
                node_id=node.id,
                label=node.name,
                value=(_display(value) if value is not None else None),
                resolver=res.resolver,
                source=res.source,
                detail=res.detail,
            ))

        text = "\n\n".join(parts) if parts else "> 没有可用结果。"
        return Answer(
            run_id=ctx.run_id,
            question=sqg.question,
            text=text,
            data={"nodes": data_nodes},
            lineage=lineage,
            status=status,
        )
