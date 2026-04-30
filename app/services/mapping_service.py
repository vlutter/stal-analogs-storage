import logging

from app.repositories.sheets_repository import MappingRow, SheetsRepository
from app.schemas.mapping import (
    BulkUpsertItem,
    BulkUpsertRequest,
    BulkUpsertResponse,
    DeepExtractionRequest,
    MappingCreate,
    MappingResponse,
    MappingUpdate,
)
from app.utils.normalization import normalize_article_for_search, normalize_article_for_store

logger = logging.getLogger(__name__)


class MappingService:
    def __init__(self, repo: SheetsRepository | None = None) -> None:
        self._repo = repo or SheetsRepository()

    @staticmethod
    def _normalize_aliases(aliases: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for a in aliases:
            norm = normalize_article_for_store(a)
            if norm and norm not in seen:
                seen.add(norm)
                result.append(norm)
        return result

    @staticmethod
    def _normalize_alias_parent_codes(parent_codes: dict[str, str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for alias, parent_code in parent_codes.items():
            normalized_alias = normalize_article_for_store(alias)
            normalized_parent = normalize_article_for_store(parent_code)
            if normalized_alias and normalized_parent:
                result[normalized_alias] = normalized_parent
        return result

    @staticmethod
    def _row_to_response(row: MappingRow) -> MappingResponse:
        return MappingResponse(stal_code=row.stal_code, aliases=row.aliases)

    # ── CRUD ────────────────────────────────────────────────────

    def create(self, data: MappingCreate) -> MappingResponse:
        stal = normalize_article_for_store(data.stal_code)
        if not stal:
            raise ValueError("stal_code is empty after normalization")

        existing = self._repo.get_row_by_stal(stal)
        if existing:
            raise ValueError(f"Mapping for '{stal}' already exists")

        aliases = self._normalize_aliases(data.aliases)
        row = MappingRow(stal_code=stal, aliases=aliases)
        self._repo.append_row(row, source_filename=data.source_filename)
        return MappingResponse(stal_code=stal, aliases=aliases)

    def get_all(self) -> list[MappingResponse]:
        return [self._row_to_response(row) for row in self._repo.get_all_rows()]

    def get(self, stal_code: str) -> MappingResponse | None:
        stal = normalize_article_for_store(stal_code)
        row = self._repo.get_row_by_stal(stal)
        if row is None:
            return None
        return self._row_to_response(row)

    def update(self, stal_code: str, data: MappingUpdate) -> MappingResponse:
        stal = normalize_article_for_store(stal_code)
        row = self._repo.get_row_by_stal(stal)
        if row is None:
            raise ValueError(f"Mapping for '{stal}' not found")

        new_aliases = self._normalize_aliases(data.aliases)

        if data.append:
            merged = list(row.aliases)
            existing_set = {a for a in merged}
            for a in new_aliases:
                if a not in existing_set:
                    merged.append(a)
                    existing_set.add(a)
            new_aliases = merged

        updated_row = MappingRow(stal_code=stal, aliases=new_aliases)
        self._repo.update_row(row.row_index, updated_row, source_filename=data.source_filename)
        return MappingResponse(stal_code=stal, aliases=new_aliases)

    def add_aliases(self, stal_code: str, aliases: list[str], source_filename: str | None = None) -> MappingResponse:
        stal = normalize_article_for_store(stal_code)
        if not stal:
            raise ValueError("stal_code is empty after normalization")

        row = self._repo.get_row_by_stal(stal)
        new_aliases = self._normalize_aliases(aliases)

        if row is None:
            new_row = MappingRow(stal_code=stal, aliases=new_aliases)
            self._repo.append_row(new_row, source_filename=source_filename)
            return MappingResponse(stal_code=stal, aliases=new_aliases)

        merged = list(row.aliases)
        existing_set = set(merged)
        for alias in new_aliases:
            if alias not in existing_set:
                merged.append(alias)
                existing_set.add(alias)

        updated_row = MappingRow(stal_code=stal, aliases=merged)
        self._repo.update_row(row.row_index, updated_row, source_filename=source_filename)
        return MappingResponse(stal_code=stal, aliases=merged)

    def remove_aliases(self, stal_code: str, aliases: list[str], source_filename: str | None = None) -> MappingResponse:
        stal = normalize_article_for_store(stal_code)
        row = self._repo.get_row_by_stal(stal)
        if row is None:
            raise ValueError(f"Mapping for '{stal}' not found")

        aliases_to_remove = set(self._normalize_aliases(aliases))
        remaining_aliases = [
            alias
            for alias in row.aliases
            if normalize_article_for_store(alias) not in aliases_to_remove
        ]

        updated_row = MappingRow(stal_code=stal, aliases=remaining_aliases)
        self._repo.update_row(row.row_index, updated_row, source_filename=source_filename)
        return MappingResponse(stal_code=stal, aliases=remaining_aliases)

    def delete(self, stal_code: str) -> bool:
        stal = normalize_article_for_store(stal_code)
        row = self._repo.get_row_by_stal(stal)
        if row is None:
            return False
        self._repo.delete_row(row.row_index)
        return True

    # ── bulk ────────────────────────────────────────────────────

    def deep_extraction(self, data: DeepExtractionRequest) -> BulkUpsertRequest:
        rows = self._repo.get_all_rows()
        rows_by_code: dict[str, list[MappingRow]] = {}
        for row in rows:
            codes = [row.stal_code, *row.aliases]
            for code in codes:
                key = normalize_article_for_search(code)
                if not key:
                    continue
                rows_by_code.setdefault(key, []).append(row)

        pending: dict[str, list[str]] = {}
        pending_parent_codes: dict[str, dict[str, str]] = {}
        for code_set in data.external_code_sets:
            normalized_codes = self._normalize_aliases(code_set)
            if not normalized_codes:
                continue

            matched_rows: list[tuple[MappingRow, str]] = []
            seen_stal: set[str] = set()
            for code in normalized_codes:
                key = normalize_article_for_search(code)
                for row in rows_by_code.get(key, []):
                    if row.stal_code in seen_stal:
                        continue
                    matched_rows.append((row, code))
                    seen_stal.add(row.stal_code)

            for row, parent_code in matched_rows:
                stal_key = normalize_article_for_search(row.stal_code)
                parent_key = normalize_article_for_search(parent_code)
                aliases = pending.setdefault(row.stal_code, [])
                parent_codes = pending_parent_codes.setdefault(row.stal_code, {})
                existing_aliases = set(aliases)
                for code in normalized_codes:
                    code_key = normalize_article_for_search(code)
                    if code_key == stal_key:
                        continue
                    if code not in existing_aliases:
                        aliases.append(code)
                        existing_aliases.add(code)
                    if parent_key != stal_key and code_key != parent_key:
                        parent_codes.setdefault(code, parent_code)

        return BulkUpsertRequest(
            items=[
                BulkUpsertItem(
                    stal_code=stal_code,
                    aliases=aliases,
                    alias_parent_codes=pending_parent_codes.get(stal_code, {}),
                )
                for stal_code, aliases in pending.items()
            ]
        )

    def bulk_upsert(self, data: BulkUpsertRequest) -> BulkUpsertResponse:
        if not data.items:
            raise ValueError("No mappings to upsert")

        existing_by_stal = {
            row.stal_code: row
            for row in self._repo.get_all_rows()
        }
        pending_creates: dict[str, tuple[list[str], dict[str, str]]] = {}
        pending_updates: dict[str, tuple[int, list[str], dict[str, str]]] = {}

        for item in data.items:
            stal = normalize_article_for_store(item.stal_code)
            if not stal:
                logger.warning("Skipping item with empty stal_code")
                continue

            new_aliases = self._normalize_aliases(item.aliases)
            item_parent_codes = self._normalize_alias_parent_codes(item.alias_parent_codes)
            existing = existing_by_stal.get(stal)

            if existing is not None:
                if stal not in pending_updates:
                    pending_updates[stal] = (existing.row_index, list(existing.aliases), {})
                row_index, merged, parent_codes = pending_updates[stal]
                existing_set = set(merged)
                for alias in new_aliases:
                    if alias not in existing_set:
                        merged.append(alias)
                        existing_set.add(alias)
                        if alias in item_parent_codes:
                            parent_codes[alias] = item_parent_codes[alias]
                pending_updates[stal] = (row_index, merged, parent_codes)
                continue

            if stal not in pending_creates:
                pending_creates[stal] = ([], {})
            merged_new, parent_codes = pending_creates[stal]
            existing_new_set = set(merged_new)
            for alias in new_aliases:
                if alias not in existing_new_set:
                    merged_new.append(alias)
                    existing_new_set.add(alias)
                    if alias in item_parent_codes:
                        parent_codes[alias] = item_parent_codes[alias]

        create_rows = [
            MappingRow(stal_code=stal, aliases=aliases, alias_parent_codes=parent_codes)
            for stal, (aliases, parent_codes) in pending_creates.items()
        ]
        update_rows = [
            (row_index, MappingRow(stal_code=stal, aliases=aliases, alias_parent_codes=parent_codes))
            for stal, (row_index, aliases, parent_codes) in pending_updates.items()
        ]

        self._repo.append_rows(create_rows, source_filename=data.source_filename)
        self._repo.update_rows(update_rows, source_filename=data.source_filename)

        created = len(create_rows)
        updated = len(update_rows)
        return BulkUpsertResponse(created=created, updated=updated, total=created + updated)
