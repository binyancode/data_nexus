"""Render logical SQG results using explicit result contracts and lineage."""

from __future__ import annotations

import math
import re
from decimal import Decimal

from nexus.core.logical import ResultKind
from nexus.core.models import Answer, ExecContext, LineageItem
from nexus.core.physical import PhysicalExecutionPlan


def _normal(value):
    return float(value) if isinstance(value, Decimal) else value


def _display(value) -> str:
    value = _normal(value)
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if not math.isfinite(value):
            return str(value)
        return f"{value:,.6f}".rstrip("0").rstrip(".")
    return str(value)


def _cell(value) -> str:
    return _display(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


def _table(headers: list[str], rows: list[list]) -> str:
    if not headers:
        return "> 无数据。"
    head = "| " + " | ".join(_cell(value) for value in headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return "\n".join([head, divider, *body])


def _excerpt(content, limit=240):
    text = re.sub(r"<[^>]+>", " ", str(content or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


class Generator:
    def generate(self, sqg, plan: PhysicalExecutionPlan, ctx: ExecContext) -> Answer:
        if sqg.context.get("error") and not sqg.nodes:
            return Answer(run_id=ctx.run_id, question=sqg.question,
                          text=sqg.context["error"], status="error")
        sections: list[str] = []
        lineage: list[LineageItem] = []
        data_nodes = []
        status = "ok"
        depended_on = {dependency for node in sqg.nodes for dependency in node.depends_on}
        output_ids = set(sqg.outputs) or {node.id for node in sqg.nodes if node.id not in depended_on}
        for node in sqg.nodes:
            result = ctx.results.get(node.id)
            if result is None:
                continue
            is_output = node.id in output_ids
            if result.error:
                status = "error"
                if is_output:
                    sections.append(f"> **{_cell(node.name)}执行失败**：{_cell(result.error)}")
                continue
            kind = node.result_kind()
            rows = [{key: _normal(value) for key, value in row.items()} for row in (result.rows or [])]
            if kind == "search":
                shown = [[index, row.get("title") or "(无标题)", _excerpt(row.get("content")),
                          f"[查看原文](<{row.get('url')}>)" if row.get("url") else "—"]
                         for index, row in enumerate(rows, 1)]
                if is_output:
                    sections.append(f"## {_cell(node.name)}\n\n{_table(['#', '标题', '摘要', '来源'], shown)}")
                for row in rows:
                    lineage.append(LineageItem(
                        node_id=node.id, label=str(row.get("title") or node.name), value=row.get("url"),
                        resolver=result.resolver, source=str(row.get("url") or result.source),
                        detail=str(row.get("content") or ""),
                    ))
            elif kind == "document":
                row = rows[0] if rows else {}
                title = str(row.get("title") or node.name)
                url = str(row.get("url") or result.source or "")
                content = str(row.get("content") or result.output or "")
                link = f"[查看原文](<{url}>)" if url else ""
                if is_output:
                    sections.append(f"## {_cell(title)}\n\n{link}\n\n{content[:2000]}")
                lineage.append(LineageItem(node_id=node.id, label=title, value=url,
                                           resolver=result.resolver, source=url, detail=content))
            elif kind == "text":
                value = self._single_value(result)
                if is_output:
                    sections.append(f"## {_cell(node.name)}\n\n{_display(value)}")
                lineage.append(self._lineage(node, result, value))
            elif kind == "action":
                value = self._single_value(result)
                if is_output:
                    sections.append(f"## {_cell(node.name)}\n\n> {_cell(value)}")
                lineage.append(self._lineage(node, result, value))
            else:
                contract = node.spec.result
                field_names = [field.name for field in contract.fields]
                if not field_names and rows:
                    field_names = list(rows[0])
                table_rows = [[row.get(name) for name in field_names] for row in rows]
                if contract.kind == ResultKind.SCALAR and rows:
                    lineage_value = rows[0].get(field_names[-1])
                    if is_output:
                        sections.append(f"## 查询结果\n\n{_table(['指标', '值'], [[node.name, lineage_value]])}")
                else:
                    lineage_value = _table(field_names, table_rows) if rows else "—"
                    if is_output:
                        sections.append(f"## {_cell(node.name)}\n\n{lineage_value}")
                lineage.append(self._lineage(node, result, lineage_value))
            data_nodes.append({"node_id": node.id, "name": node.name, "rows": rows})
        return Answer(
            run_id=ctx.run_id, question=sqg.question,
            text="\n\n".join(sections) if sections else "> 没有可用结果。",
            data={"nodes": data_nodes}, lineage=lineage, status=status,
        )

    @staticmethod
    def _single_value(result):
        if result.rows:
            row = result.rows[0]
            return row.get("value", next(iter(row.values()), None))
        return result.output

    @staticmethod
    def _lineage(node, result, value):
        return LineageItem(
            node_id=node.id, label=node.name, value=value,
            resolver=result.resolver, source=result.source, detail=result.detail,
        )
