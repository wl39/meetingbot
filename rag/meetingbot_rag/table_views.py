"""Bounded spreadsheet pages from immutable parsed snapshots."""

import re

from .sources import RagError


def table_page(parsed, evidence, sheet=None, page=None):
    sheets = parsed.get("sheets", [])
    if not sheets:
        raise RagError("VIEW_BUILD_FAILED", "표 원문을 다시 준비해 주세요.", 409)
    name = sheet or evidence.get("location", {}).get("sheet") or sheets[0]["name"]
    selected = next((s for s in sheets if s["name"] == name), None)
    if selected is None:
        raise RagError("NOT_FOUND", "시트를 찾을 수 없습니다.", 404)
    rows = selected["rows"]
    columns = list(dict.fromkeys(re.sub(r"\d+$", "", c["address"]) for row in rows for c in row["cells"]))
    size = max(1, min(40, 1000 // max(1, len(columns))))
    total_pages = max(1, (len(rows) + size - 1) // size)
    if page is None:
        target = (
            evidence.get("location", {}).get("start_row", 1)
            if name == evidence.get("location", {}).get("sheet")
            else 1
        )
        page = next((i // size for i, row in enumerate(rows) if row["row"] >= target), 0)
    page = min(page, total_pages - 1)
    visible = []
    truncated = False
    for row in rows[page * size : (page + 1) * size]:
        cells = []
        for cell in row["cells"]:
            cell = dict(cell)
            for key in ("value", "display", "formula"):
                if isinstance(cell.get(key), str) and len(cell[key]) > 2000:
                    cell[key] = cell[key][:2000] + "…"
                    truncated = True
            cells.append(cell)
        visible.append({"row": row["row"], "cells": cells})
    return {
        "kind": "spreadsheet_page",
        "sheet": name,
        "sheets": [{"name": s["name"], "rows": len(s["rows"])} for s in sheets],
        "columns": columns,
        "rows": visible,
        "page": page,
        "total_pages": total_pages,
        "previous_page": page - 1 if page else None,
        "next_page": page + 1 if page + 1 < total_pages else None,
        "merged_ranges": selected.get("merged_ranges", []),
        "truncated": truncated,
        "warnings": parsed.get("warnings", []),
    }
