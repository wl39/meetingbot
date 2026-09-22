"""Bounded parser subprocess. Never follows links or evaluates formulas."""

import base64
import csv
import io
import json
import re
import sys
import zipfile
from datetime import date, datetime, time

PARSER_VERSION = "4"


def decode(data, encodings):
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("DECODE_ERROR")


def value(v):
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    return v


def tables(rows, name, merges=None):
    nonempty = [row for row in rows if any(c["value"] is not None and c["value"] != "" for c in row["cells"])]
    if not nonempty:
        return []
    first = nonempty[0]
    headers = [c["value"] for c in first["cells"]]
    if not all(isinstance(x, str) and x.strip() for x in headers) or len(set(headers)) != len(headers):
        raise ValueError("TABLE_HEADER_REVIEW_REQUIRED")
    if merges and any(m[1] <= first["row"] <= m[3] for m in merges):
        raise ValueError("TABLE_HEADER_REVIEW_REQUIRED")
    out = []
    previous = first["row"]
    for row in nonempty[1:]:
        # Gaps suggest multiple tables; don't silently merge them.
        if row["row"] > previous + 1 and not row.get("hidden_gap"):
            raise ValueError("TABLE_BOUNDARY_REVIEW_REQUIRED")
        if [c["value"] for c in row["cells"]] == headers:
            raise ValueError("TABLE_BOUNDARY_REVIEW_REQUIRED")
        previous = row["row"]
        if len(row["cells"]) != len(headers):
            raise ValueError("TABLE_WIDTH_REVIEW_REQUIRED")
        text = " | ".join(
            f"{head}: {cell.get('display', cell['value']) if cell['value'] is not None else '(빈 값)'}"
            + (" [수식·계산 결과 확인 필요]" if cell.get("formula") else "")
            for head, cell in zip(headers, row["cells"])
        )
        out.append(
            {
                "text": text,
                "title_path": [name],
                "location": {
                    "type": "table",
                    "sheet": name,
                    "header_row": first["row"],
                    "start_row": row["row"],
                    "end_row": row["row"],
                    "cell_range": f"{row['cells'][0]['address']}:{row['cells'][-1]['address']}",
                },
                "table": {"headers": headers, "cells": row["cells"], "merged_ranges": merges or []},
            }
        )
    return out


REVIEW_CODES = {
    "TABLE_HEADER_REVIEW_REQUIRED",
    "TABLE_BOUNDARY_REVIEW_REQUIRED",
    "TABLE_WIDTH_REVIEW_REQUIRED",
}


def reviewed_tables(rows, name, merges, settings, warnings):
    try:
        return tables(rows, name, merges)
    except ValueError as error:
        if not settings.get("allow_review") or str(error) not in REVIEW_CODES:
            raise
        warnings.append({"code": str(error), "sheet": name})
    # Keep every visible source row, including the ambiguous header. Never infer
    # column meanings or join unrelated tables when the user accepts a review.
    out = []
    for row in rows:
        cells = row["cells"]
        if not any(c["value"] not in (None, "") or c.get("formula") for c in cells):
            continue
        headers = [re.sub(r"\d+$", "", c["address"]) + "열" for c in cells]
        out.append(
            {
                "text": "[표 구조 확인 필요 · 셀 주소 기준] "
                + " | ".join(
                    f"{c['address']}: {c.get('display', c['value']) if c['value'] is not None else '(빈 값)'}"
                    + (" [수식·계산 결과 확인 필요]" if c.get("formula") else "")
                    for c in cells
                    if c["value"] not in (None, "") or c.get("formula")
                ),
                "title_path": [name],
                "location": {
                    "type": "table",
                    "sheet": name,
                    "start_row": row["row"],
                    "end_row": row["row"],
                    "cell_range": f"{cells[0]['address']}:{cells[-1]['address']}",
                },
                "table": {
                    "headers": headers,
                    "cells": cells,
                    "merged_ranges": merges or [],
                    "review_required": True,
                },
            }
        )
    return out


def spreadsheet_tables(rows, name, merges, settings, warnings):
    """Separate title/notes and blank-delimited tables before detecting headers.

    Ambiguous layouts remain searchable by cell address, with a visible warning.
    Original cells are retained separately for the spreadsheet viewer.
    """
    blocks, block = [], []
    for row in rows:
        occupied = [c for c in row["cells"] if c["value"] not in (None, "") or c.get("formula")]
        if occupied:
            block.append(row)
        elif block:
            blocks.append(block)
            block = []
    if block:
        blocks.append(block)
    segments = []
    context = []
    for block in blocks:
        used = {
            re.sub(r"\d+$", "", c["address"])
            for row in block
            for c in row["cells"]
            if c["value"] not in (None, "") or c.get("formula")
        }
        clean = [
            {**row, "cells": [c for c in row["cells"] if re.sub(r"\d+$", "", c["address"]) in used]}
            for row in block
        ]
        # Report-style sheets put a merged title and update note above the table.
        start = 0
        while (
            start < len(clean)
            and sum(c["value"] not in (None, "") or bool(c.get("formula")) for c in clean[start]["cells"])
            <= 1
        ):
            row = clean[start]
            text = " | ".join(
                str(c.get("display", c["value"])) for c in row["cells"] if c["value"] not in (None, "")
            )
            context.append(text)
            segments.append(
                {
                    "text": text,
                    "title_path": [name],
                    "location": {
                        "type": "table",
                        "sheet": name,
                        "start_row": row["row"],
                        "end_row": row["row"],
                        "cell_range": f"{row['cells'][0]['address']}:{row['cells'][-1]['address']}",
                    },
                    "table": {
                        "headers": [re.sub(r"\d+$", "", c["address"]) + "열" for c in row["cells"]],
                        "cells": row["cells"],
                        "merged_ranges": merges or [],
                    },
                }
            )
            start += 1
        if start == len(clean):
            continue
        data = clean[start:]
        # Ignore completely unused trailing columns, including formatting-only cells.
        used = {
            re.sub(r"\d+$", "", c["address"])
            for row in data
            for c in row["cells"]
            if c["value"] not in (None, "") or c.get("formula")
        }
        data = [
            {**row, "cells": [c for c in row["cells"] if re.sub(r"\d+$", "", c["address"]) in used]}
            for row in data
        ]
        parsed = reviewed_tables(data, name, merges, {**settings, "allow_review": True}, warnings)
        if not parsed:  # A single text-only row is content, not a disposable header.
            parsed = [
                {
                    "text": " | ".join(str(c["value"]) for c in data[0]["cells"]),
                    "title_path": [name],
                    "location": {
                        "type": "table",
                        "sheet": name,
                        "start_row": data[0]["row"],
                        "end_row": data[0]["row"],
                        "cell_range": f"{data[0]['cells'][0]['address']}:{data[0]['cells'][-1]['address']}",
                    },
                    "table": {"headers": [], "cells": data[0]["cells"], "merged_ranges": merges or []},
                }
            ]
        for segment in parsed:
            segment["title_path"] = [name] + context[-2:]
        segments.extend(parsed)
    return segments


def parse(data, suffix, settings):
    if suffix in {".md", ".txt"}:
        raw = decode(data, settings["encodings"])
        return {"kind": "text", "text": raw, "warnings": [], "parser_version": PARSER_VERSION}
    from openpyxl.utils import get_column_letter

    if suffix in {".csv", ".tsv"}:
        reader = csv.reader(
            io.StringIO(decode(data, settings["encodings"])),
            delimiter="," if suffix == ".csv" else "\t",
            strict=True,
        )
        rows = []
        count = 0
        for n, values in enumerate(reader, 1):
            count += len(values)
            if (
                n > settings["max_rows"]
                or len(values) > settings["max_columns"]
                or count > settings["max_cells"]
            ):
                raise ValueError("TABLE_SIZE_LIMIT")
            rows.append(
                {
                    "row": n,
                    "cells": [
                        {
                            "address": f"{get_column_letter(c)}{n}",
                            "value": v,
                            "type": "string",
                            "formula": None,
                        }
                        for c, v in enumerate(values, 1)
                    ],
                }
            )
        warnings = ["CSV/TSV 값은 원본 문자열로 보존합니다."]
        segments = reviewed_tables(rows, "표", None, settings, warnings)
        return {
            "kind": "table",
            "segments": segments,
            "sheets": [{"name": "표", "rows": rows, "merged_ranges": []}],
            "warnings": warnings,
            "parser_version": PARSER_VERSION,
        }
    if suffix != ".xlsx":
        raise ValueError("UNSUPPORTED_FORMAT")
    from openpyxl import load_workbook

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if (
            len(z.infolist()) > 1000
            or sum(i.file_size for i in z.infolist()) > settings["xlsx_uncompressed_bytes"]
        ):
            raise ValueError("XLSX_EXPANSION_LIMIT")
        for info in z.infolist():
            if info.filename.lower().endswith("vbaproject.bin"):
                raise ValueError("MACRO_EXCLUDED")
            if info.filename.endswith(".xml") and b"<!DOCTYPE" in z.read(info).upper():
                raise ValueError("XML_DOCTYPE_DENIED")
    wb = load_workbook(io.BytesIO(data), data_only=False, keep_links=False)
    cached = load_workbook(io.BytesIO(data), data_only=True, keep_links=False)
    segments, warnings, sheets, count = [], [], [], 0
    if len(wb.worksheets) > settings["max_sheets"]:
        raise ValueError("SHEET_LIMIT")
    for ws in wb.worksheets:
        if ws.sheet_state != "visible" and not settings["include_hidden"]:
            warnings.append(f"숨김 시트 제외: {ws.title}")
            continue
        if ws.max_row > settings["max_rows"] or ws.max_column > settings["max_columns"]:
            raise ValueError("TABLE_SIZE_LIMIT")
        count += ws.max_row * ws.max_column
        if count > settings["max_cells"]:
            raise ValueError("TABLE_SIZE_LIMIT")
        hidden_columns = set()
        for dim in ws.column_dimensions.values():
            if dim.hidden:
                hidden_columns.update(range(dim.min, dim.max + 1))
        rows, hidden_gap = [], False
        for row in ws.iter_rows():
            if ws.row_dimensions[row[0].row].hidden and not settings["include_hidden"]:
                hidden_gap = True
                continue
            cells = []
            for cell in row:
                if cell.column in hidden_columns and not settings["include_hidden"]:
                    continue
                formula = cell.value if cell.data_type == "f" else None
                raw = cached[ws.title][cell.coordinate].value if formula else cell.value
                v = value(raw)
                display = v
                if isinstance(v, (float, int)) and not isinstance(v, bool):
                    if re.fullmatch(r"0+", cell.number_format):
                        display = str(int(v)).zfill(len(cell.number_format)) if v == int(v) else str(v)
                    elif cell.number_format.endswith("%"):
                        display = f"{v * 100:g}%"
                cells.append(
                    {
                        "address": cell.coordinate,
                        "value": v,
                        "display": display,
                        "type": cell.data_type,
                        "number_format": cell.number_format,
                        "formula": formula,
                        "cached_result": v if formula else None,
                        "formula_status": ("cache_missing" if v is None else "cache_freshness_unknown")
                        if formula
                        else None,
                    }
                )
            if cells:
                rows.append({"row": row[0].row, "cells": cells, "hidden_gap": hidden_gap})
                hidden_gap = False
        merged = [list(m.bounds) for m in ws.merged_cells.ranges]
        sheets.append({"name": ws.title, "rows": rows, "merged_ranges": merged})
        segments.extend(spreadsheet_tables(rows, ws.title, merged, settings, warnings))
    wb.close()
    cached.close()
    return {
        "kind": "table",
        "segments": segments,
        "sheets": sheets,
        "warnings": warnings,
        "parser_version": PARSER_VERSION,
    }


if __name__ == "__main__":
    try:
        payload = json.load(sys.stdin)
        result = parse(base64.b64decode(payload["data"]), payload["suffix"], payload["settings"])
        # Pipes use the Windows locale unless UTF-8 mode is enabled. JSON escapes
        # preserve every Unicode character while keeping this transport ASCII-safe.
        print(json.dumps({"result": result}, ensure_ascii=True, allow_nan=False))
    except Exception as exc:
        code = (
            str(exc) if isinstance(exc, ValueError) and re.fullmatch("[A-Z_]+", str(exc)) else "PARSE_FAILED"
        )
        print(json.dumps({"error_code": code}))
