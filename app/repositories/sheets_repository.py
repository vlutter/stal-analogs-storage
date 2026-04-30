from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError

from app.utils.settings import settings

logger = logging.getLogger(__name__)

_RETRYABLE_EXCEPTIONS = (ConnectionError, ConnectionAbortedError, ConnectionResetError, TimeoutError, OSError)
_RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.5


class SheetsRepositoryError(RuntimeError):
    """Raised when Google Sheets cannot complete a repository operation."""


def _is_retryable_http_error(exc: HttpError) -> bool:
    return exc.resp.status in _RETRYABLE_HTTP_STATUSES


def _execute_with_retry(request, *, max_retries: int = _MAX_RETRIES):
    """Execute a Google API request with retry on transient connection errors."""
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except HttpError as exc:
            if not _is_retryable_http_error(exc):
                raise
            if attempt == max_retries:
                logger.exception(
                    "Google API request failed after %d attempts",
                    max_retries + 1,
                )
                raise SheetsRepositoryError("Google Sheets is temporarily unavailable") from exc
            delay = _BACKOFF_BASE ** attempt
            logger.warning(
                "Transient Google API HTTP error on attempt %d/%d: %s. Retrying in %.1fs...",
                attempt + 1, max_retries + 1, exc, delay,
            )
            time.sleep(delay)
        except _RETRYABLE_EXCEPTIONS as exc:
            if attempt == max_retries:
                logger.exception(
                    "Google API request failed after %d attempts",
                    max_retries + 1,
                )
                raise SheetsRepositoryError("Google Sheets is temporarily unavailable") from exc
            delay = _BACKOFF_BASE ** attempt
            logger.warning(
                "Transient connection error on attempt %d/%d: %s. Retrying in %.1fs...",
                attempt + 1, max_retries + 1, exc, delay,
            )
            time.sleep(delay)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _col_letter(index: int) -> str:
    """0-based column index → A, B, … Z, AA, AB …"""
    result = ""
    while True:
        result = chr(ord("A") + index % 26) + result
        index = index // 26 - 1
        if index < 0:
            break
    return result


@dataclass
class MappingRow:
    stal_code: str
    aliases: list[str] = field(default_factory=list)
    row_index: int | None = None  # 1-based row number in the sheet
    alias_parent_codes: dict[str, str] = field(default_factory=dict)


class SheetsRepository:
    """Read/write article mappings in a Google Sheets spreadsheet.

    Layout:
        Column A  — stal_code
        Columns B… — alias codes
    Metadata (source, date) stored as cell notes, not extra columns.
    """

    def __init__(self) -> None:
        self._spreadsheet_id = settings.google_sheets_spreadsheet_id
        self._sheet_name = settings.google_sheets_sheet_name
        self._service: Resource | None = None
        self._sheet_id: int | None = None

    # ── connection ──────────────────────────────────────────────

    def _get_service(self) -> Resource:
        if self._service is None:
            creds = self._load_credentials()
            self._service = build("sheets", "v4", credentials=creds)
        return self._service

    @staticmethod
    def _load_credentials() -> Credentials:
        if settings.google_sheets_credentials_json:
            import json
            info = json.loads(settings.google_sheets_credentials_json)
            return Credentials.from_service_account_info(info, scopes=SCOPES)
        return Credentials.from_service_account_file(
            settings.google_sheets_credentials_file,
            scopes=SCOPES,
        )

    @property
    def _sheets(self):
        return self._get_service().spreadsheets()

    # ── helpers ─────────────────────────────────────────────────

    def _range(self, range_a1: str) -> str:
        return f"{self._sheet_name}!{range_a1}"

    def _make_note_text(self, source_filename: str | None, parent_code: str | None = None) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts = [f"Updated: {now}"]
        if source_filename:
            parts.append(f"Source: {source_filename}")
        if parent_code:
            parts.append(f"Parent: {parent_code}")
        return "\n".join(parts)

    def _get_sheet_id(self) -> int:
        """Return the numeric sheetId for the configured sheet name."""
        if self._sheet_id is not None:
            return self._sheet_id

        meta = _execute_with_retry(self._sheets.get(
            spreadsheetId=self._spreadsheet_id,
            fields="sheets.properties",
        ))
        for s in meta.get("sheets", []):
            props = s.get("properties", {})
            if props.get("title") == self._sheet_name:
                self._sheet_id = props["sheetId"]
                return self._sheet_id
        raise ValueError(f"Sheet '{self._sheet_name}' not found in spreadsheet")

    # ── read ────────────────────────────────────────────────────

    def get_all_rows(self) -> list[MappingRow]:
        result = _execute_with_retry(
            self._sheets.values()
            .get(
                spreadsheetId=self._spreadsheet_id,
                range=self._range("A2:Z"),
            )
        )
        rows: list[MappingRow] = []
        for i, raw in enumerate(result.get("values", []), start=2):
            if not raw or not raw[0]:
                continue
            rows.append(
                MappingRow(
                    stal_code=raw[0],
                    aliases=[v for v in raw[1:] if v],
                    row_index=i,
                )
            )
        return rows

    def get_row_by_stal(self, stal_code: str) -> MappingRow | None:
        for row in self.get_all_rows():
            if row.stal_code == stal_code:
                return row
        return None

    def find_row_index_by_stal(self, stal_code: str) -> int | None:
        row = self.get_row_by_stal(stal_code)
        return row.row_index if row else None

    # ── write ───────────────────────────────────────────────────

    def append_row(
        self,
        mapping: MappingRow,
        source_filename: str | None = None,
    ) -> int:
        """Append a new row and return its 1-based row index."""
        return self.append_rows([mapping], source_filename=source_filename)[0]

    def append_rows(
        self,
        mappings: list[MappingRow],
        source_filename: str | None = None,
    ) -> list[int]:
        """Append multiple rows in a single API call and return row indexes."""
        if not mappings:
            return []

        rows_values = [[m.stal_code, *m.aliases] for m in mappings]
        result = _execute_with_retry(
            self._sheets.values().append(
                spreadsheetId=self._spreadsheet_id,
                range=self._range("A:A"),
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": rows_values},
            )
        )

        updated_range: str = result.get("updates", {}).get("updatedRange", "")
        start_row, end_row = self._parse_row_span_from_range(updated_range)
        row_indices = list(range(start_row, end_row + 1))
        if len(row_indices) != len(mappings):
            row_indices = list(range(start_row, start_row + len(mappings)))

        if source_filename:
            notes_meta = [
                (row_idx, mapping)
                for row_idx, mapping in zip(row_indices, mappings)
            ]
            self._set_notes_for_rows(notes_meta, source_filename)

        for row_idx, mapping in zip(row_indices, mappings):
            logger.info("Appended row %d: %s", row_idx, mapping.stal_code)
        return row_indices

    def update_row(
        self,
        row_index: int,
        mapping: MappingRow,
        source_filename: str | None = None,
    ) -> None:
        """Overwrite an existing row (1-based index)."""
        self.update_rows([(row_index, mapping)], source_filename=source_filename)

    def update_rows(
        self,
        updates: list[tuple[int, MappingRow]],
        source_filename: str | None = None,
    ) -> None:
        """Overwrite multiple existing rows in batched API calls."""
        if not updates:
            return

        data: list[dict] = []
        clear_ranges: list[str] = []
        notes_meta: list[tuple[int, MappingRow]] = []

        for row_index, mapping in updates:
            values = [mapping.stal_code, *mapping.aliases]
            end_col = _col_letter(len(values) - 1)
            cell_range = self._range(f"A{row_index}:{end_col}{row_index}")
            data.append({"range": cell_range, "values": [values]})
            if len(values) <= 26:
                start_col = _col_letter(len(values))
                clear_ranges.append(self._range(f"{start_col}{row_index}:Z{row_index}"))
            notes_meta.append((row_index, mapping))

        _execute_with_retry(self._sheets.values().batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ))

        if clear_ranges:
            _execute_with_retry(self._sheets.values().batchClear(
                spreadsheetId=self._spreadsheet_id,
                body={"ranges": clear_ranges},
            ))

        if source_filename:
            self._set_notes_for_rows(notes_meta, source_filename)

        for row_index, mapping in updates:
            logger.info("Updated row %d: %s", row_index, mapping.stal_code)

    def delete_row(self, row_index: int) -> None:
        """Delete a row by its 1-based index."""
        sheet_id = self._get_sheet_id()
        request_body = {
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": sheet_id,
                            "dimension": "ROWS",
                            "startIndex": row_index - 1,
                            "endIndex": row_index,
                        }
                    }
                }
            ]
        }
        _execute_with_retry(self._sheets.batchUpdate(
            spreadsheetId=self._spreadsheet_id,
            body=request_body,
        ))
        logger.info("Deleted row %d", row_index)

    # ── notes (cell metadata) ──────────────────────────────────

    def _set_notes_for_row(
        self,
        row_index: int,
        num_cells: int,
        source_filename: str | None,
    ) -> None:
        """Set notes on every cell in the row."""
        aliases = [""] * max(num_cells - 1, 0)
        self._set_notes_for_rows([(row_index, MappingRow(stal_code="", aliases=aliases))], source_filename)

    def _set_notes_for_rows(
        self,
        rows: list[tuple[int, MappingRow]],
        source_filename: str | None,
    ) -> None:
        """Set notes on multiple row ranges in one batchUpdate call."""
        if not rows:
            return

        sheet_id = self._get_sheet_id()
        note_text = self._make_note_text(source_filename)

        requests = []
        for row_index, mapping in rows:
            num_cells = 1 + len(mapping.aliases)
            requests.append(
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": row_index - 1,
                            "endRowIndex": row_index,
                            "startColumnIndex": 0,
                            "endColumnIndex": num_cells,
                        },
                        "cell": {"note": note_text},
                        "fields": "note",
                    }
                }
            )
            for alias_index, alias in enumerate(mapping.aliases, start=1):
                parent_code = mapping.alias_parent_codes.get(alias)
                if not parent_code:
                    continue
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": row_index - 1,
                                "endRowIndex": row_index,
                                "startColumnIndex": alias_index,
                                "endColumnIndex": alias_index + 1,
                            },
                            "cell": {"note": self._make_note_text(source_filename, parent_code=parent_code)},
                            "fields": "note",
                        }
                    }
                )

        if requests:
            _execute_with_retry(self._sheets.batchUpdate(
                spreadsheetId=self._spreadsheet_id,
                body={"requests": requests},
            ))

    # ── internal helpers ───────────────────────────────────────

    def _clear_row_tail(self, row_index: int, start_col_index: int) -> None:
        """Clear cells after the last written column to remove stale aliases."""
        start_col = _col_letter(start_col_index)
        clear_range = self._range(f"{start_col}{row_index}:Z{row_index}")
        _execute_with_retry(self._sheets.values().clear(
            spreadsheetId=self._spreadsheet_id,
            range=clear_range,
        ))

    @staticmethod
    def _parse_row_from_range(range_str: str) -> int:
        """Extract row number from a range like 'Лист1!A5:C5'."""
        import re
        match = re.search(r"(\d+)", range_str.split("!")[-1])
        if match:
            return int(match.group(1))
        return 1

    @staticmethod
    def _parse_row_span_from_range(range_str: str) -> tuple[int, int]:
        """Extract start/end row from 'Sheet!A5:C7'."""
        import re

        a1 = range_str.split("!")[-1]
        matches = [int(v) for v in re.findall(r"\d+", a1)]
        if not matches:
            return 1, 1
        if len(matches) == 1:
            return matches[0], matches[0]
        return matches[0], matches[-1]
