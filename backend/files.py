"""CSV / Excel parsing into rows + the text used for embedding and BM25."""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import HTTPException

MAX_ROWS = 1000
MAX_COLUMNS = 100
MAX_TEXT = 1000  # chars kept per row for indexing (display data stays complete)


def _cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _read(name: str, content: bytes) -> list[list[Any]]:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext == "csv":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        return list(csv.reader(io.StringIO(text)))
    if ext == "xlsx":
        from openpyxl import load_workbook
        try:
            wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            return [list(r) for r in wb.active.iter_rows(values_only=True)]
        except Exception as exc:
            raise HTTPException(400, "Could not read this Excel file.") from exc
    raise HTTPException(400, "Upload a CSV or XLSX file.")


def parse(name: str, content: bytes) -> dict[str, Any]:
    raw = _read(name, content)
    width = max((len(r) for r in raw), default=0)
    if not raw or not width:
        raise HTTPException(400, "The file is empty.")
    if width > MAX_COLUMNS:
        raise HTTPException(413, f"Too many columns. Upload up to {MAX_COLUMNS}.")

    used: set[str] = set()
    headers = []
    for i in range(width):
        base = (" ".join(_cell(raw[0][i] if i < len(raw[0]) else "").split()) or f"Column {i + 1}")[:120]
        h, n = base, 2
        while h in used:
            h, n = f"{base} {n}", n + 1
        used.add(h)
        headers.append(h)

    body = raw[1:]
    while body and not any(_cell(v) for v in body[-1]):
        body.pop()
    if not body:
        raise HTTPException(400, "The file has a header but no data rows.")
    if len(body) > MAX_ROWS:
        raise HTTPException(413, f"Too many rows. Upload up to {MAX_ROWS}.")

    rows, texts = [], []
    for r in body:
        vals = [_cell(r[i]) if i < len(r) else "" for i in range(width)]
        rows.append({h: (v or None) for h, v in zip(headers, vals)})
        texts.append(" | ".join(f"{h}: {v}" for h, v in zip(headers, vals) if v)[:MAX_TEXT])
    return {"fileName": name, "rowCount": len(rows), "columnCount": width,
            "columns": headers, "rows": rows, "texts": texts}
