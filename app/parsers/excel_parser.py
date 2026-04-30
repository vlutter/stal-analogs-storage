"""Parse Excel (.xlsx/.xls) and CSV files into a compact text representation
suitable for sending to an LLM."""

from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

MAX_ROWS_PER_SHEET = 5000


def parse_tabular_file(file_path: Path | None = None, file_bytes: bytes | None = None, filename: str = "") -> str:
    """Return a compact text representation of all sheets/rows.

    Accepts either a file on disk (file_path) or raw bytes + filename.
    """
    ext = (filename or str(file_path or "")).rsplit(".", 1)[-1].lower()

    if ext == "csv":
        return _parse_csv(file_path=file_path, file_bytes=file_bytes)
    if ext in ("xlsx", "xls"):
        return _parse_excel(file_path=file_path, file_bytes=file_bytes)

    raise ValueError(f"Unsupported tabular format: .{ext}")


def _parse_excel(file_path: Path | None = None, file_bytes: bytes | None = None) -> str:
    source = file_path if file_path else io.BytesIO(file_bytes)
    sheets: dict[str, pd.DataFrame] = pd.read_excel(
        source, sheet_name=None, header=None, dtype=str, na_filter=False,
    )

    parts: list[str] = []
    for sheet_name, df in sheets.items():
        df = df.head(MAX_ROWS_PER_SHEET)
        parts.append(f"=== Sheet: {sheet_name} ===")
        for idx, row_values in enumerate(df.values.tolist(), start=1):
            cells = [str(v).strip() for v in row_values if str(v).strip()]
            if cells:
                parts.append(f"Row {idx}: {' | '.join(cells)}")
    return "\n".join(parts)


def _parse_csv(file_path: Path | None = None, file_bytes: bytes | None = None) -> str:
    if file_path:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = file_bytes.decode("utf-8", errors="replace")

    reader = csv.reader(io.StringIO(text))
    parts: list[str] = ["=== CSV ==="]
    for idx, row_values in enumerate(reader, start=1):
        if idx > MAX_ROWS_PER_SHEET:
            break
        cells = [v.strip() for v in row_values if v.strip()]
        if cells:
            parts.append(f"Row {idx}: {' | '.join(cells)}")
    return "\n".join(parts)
