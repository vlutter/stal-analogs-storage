"""Agent ingestion service — orchestrates parsing and LLM extraction."""

from __future__ import annotations

import logging

from app.parsers.excel_parser import parse_tabular_file
from app.schemas.agent import IngestFileResponse, RefineIngestItemsRequest
from app.schemas.mapping import BulkUpsertRequest, DeepExtractionRequest
from app.services.extraction_service import ExtractionService
from app.services.mapping_service import MappingService

logger = logging.getLogger(__name__)

TABULAR_EXTENSIONS = {".xlsx", ".xls", ".csv"}
OTHER_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


class AgentService:
    def __init__(
        self,
        extraction: ExtractionService | None = None,
        mapping: MappingService | None = None,
    ) -> None:
        self._extraction = extraction or ExtractionService()
        self._mapping = mapping or MappingService()

    def ingest_file(
        self,
        filename: str,
        file_bytes: bytes,
        instructions: str | None = None,
    ) -> IngestFileResponse:
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

        if ext in TABULAR_EXTENSIONS:
            result = self._ingest_tabular(filename, file_bytes, ext, instructions)
        elif ext in OTHER_EXTENSIONS:
            result = self._ingest_file_for_llm(filename, file_bytes, ext, instructions)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        return result

    def refine_ingest_items(self, data: RefineIngestItemsRequest) -> IngestFileResponse:
        extraction = self._extraction.refine_items(data.items, data.correction)
        return self._preview_response(data.filename, extraction)

    def deep_extraction_file(
        self,
        filename: str,
        file_bytes: bytes,
        instructions: str | None = None,
    ) -> BulkUpsertRequest:
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

        if ext in TABULAR_EXTENSIONS:
            code_sets = self._deep_extract_tabular(filename, file_bytes, instructions)
        elif ext in OTHER_EXTENSIONS:
            code_sets = self._extraction.extract_code_sets_from_file(
                file_bytes,
                filename,
                ext,
                instructions=instructions,
            )
        else:
            raise ValueError(f"Unsupported file type: {ext}")

        preview = self._mapping.deep_extraction(
            DeepExtractionRequest(external_code_sets=code_sets.external_code_sets)
        )
        preview.source_filename = filename
        return preview

    def _ingest_tabular(
        self,
        filename: str,
        file_bytes: bytes,
        ext: str,
        instructions: str | None,
    ) -> IngestFileResponse:
        logger.info("Parsing tabular file '%s'", filename)
        text = parse_tabular_file(file_bytes=file_bytes, filename=filename)
        logger.info("Parsed %d chars, sending to LLM", len(text))

        extraction = self._extraction.extract_from_text(text, instructions=instructions)
        return self._preview_response(filename, extraction)

    def _deep_extract_tabular(self, filename: str, file_bytes: bytes, instructions: str | None):
        logger.info("Parsing tabular file '%s' for deep extraction", filename)
        text = parse_tabular_file(file_bytes=file_bytes, filename=filename)
        logger.info("Parsed %d chars, sending to LLM for deep extraction", len(text))
        return self._extraction.extract_code_sets_from_text(text, instructions=instructions)

    def _ingest_file_for_llm(
        self,
        filename: str,
        file_bytes: bytes,
        ext: str,
        instructions: str | None,
    ) -> IngestFileResponse:
        logger.info("Sending '%s' (%s) directly to LLM (no server-side pre-parsing)", filename, ext)
        extraction = self._extraction.extract_from_file(file_bytes, filename, ext, instructions=instructions)
        return self._preview_response(filename, extraction)

    def _preview_response(self, filename: str, extraction) -> IngestFileResponse:
        items_extracted = len(extraction.items)

        if items_extracted == 0:
            logger.warning("No mappings extracted from '%s'", filename)
            return IngestFileResponse(
                filename=filename,
                items_extracted=0,
                items_saved=0,
                status="no_mappings_found",
                llm_items=[],
            )

        logger.info(
            "File '%s': extracted=%d, waiting for confirmation",
            filename, items_extracted,
        )

        return IngestFileResponse(
            filename=filename,
            items_extracted=items_extracted,
            items_saved=0,
            status="preview_ready",
            llm_items=extraction.items,
        )
