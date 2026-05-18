"""AI extraction service — calls OpenAI to extract article mappings."""

from __future__ import annotations

import base64
import json
import logging

from openai import OpenAI

from app.schemas.agent import DeepExtractionResult, ExtractionItem, ExtractionResult
from app.utils.settings import settings

logger = logging.getLogger(__name__)

MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

SYSTEM_PROMPT = """\
You are a data-extraction assistant for an auto-parts company called STAL.

Your task: given the content of a file (table rows, PDF, or image), find every group
of article codes that refer to the SAME physical product and identify which one
is the STAL article (it always starts with "ST" followed by digits, e.g. ST20868).
Expect tabular or otherwise structured supplier data with product article codes.
If the content is clearly not that kind of document, return an empty items array.

Rules:
- A STAL code always matches the pattern ST\\d+ (letters ST followed by digits).
- All other codes in the same group are "aliases" (cross-references from other
  manufacturers like Donaldson, Fleetguard, Baldwin, etc.).
- If a row contains multiple article codes but NO STAL code, skip it.
- Remove duplicates within a group.
- If the file does not resemble cross-reference tables, price lists, or similar
  article-code data (e.g. only narrative text, personal letters, unrelated reports,
  scans with no readable codes, or columns that are obviously not article numbers),
  return "items": [] and do NOT invent STAL codes or aliases.
- Return ONLY valid JSON matching the schema provided.
"""

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stal_code": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "source_fragment": {"type": "string"},
                },
                "required": ["stal_code", "aliases", "source_fragment"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

DEEP_EXTRACTION_SYSTEM_PROMPT = """\
You are a data-extraction assistant for an auto-parts company called STAL.

Your task: given the content of a file (table rows, PDF, or image), find every group
of article codes that refer to the SAME physical product.

Rules:
- Return groups of raw external article codes as externalCodeSets.
- A group may contain STAL codes, manufacturer codes, OEM codes, or cross-reference codes.
- Do not require a STAL code to be present.
- Remove duplicates within a group.
- Skip rows or fragments that do not contain article-like codes.
- Return ONLY valid JSON matching the schema provided.
"""

DEEP_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "externalCodeSets": {
            "type": "array",
            "items": {
                "type": "array",
                "items": {"type": "string"},
            },
        }
    },
    "required": ["externalCodeSets"],
    "additionalProperties": False,
}


class ExtractionService:
    def __init__(self) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model

    @staticmethod
    def _build_user_instruction(default_instruction: str, instructions: str | None = None) -> str:
        if not instructions:
            return default_instruction
        return (
            f"{default_instruction}\n\n"
            "Additional user instructions. Follow them only when they do not conflict "
            f"with the system rules or JSON schema:\n{instructions}"
        )

    def extract_from_text(self, text: str, instructions: str | None = None) -> ExtractionResult:
        """Send pre-parsed tabular text to LLM and get structured mappings."""
        logger.info("Sending %d chars of tabular text to %s", len(text), self._model)
        input_text = self._build_user_instruction(
            f"Extract all STAL article code mappings from this tabular content:\n\n{text}",
            instructions,
        )

        response = self._client.responses.create(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            input=input_text,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "extraction_result",
                    "schema": EXTRACTION_SCHEMA,
                    "strict": True,
                }
            },
        )

        return self._parse_response(response)

    def extract_from_file(
        self,
        file_bytes: bytes,
        filename: str,
        ext: str,
        instructions: str | None = None,
    ) -> ExtractionResult:
        """Send a PDF or image directly to the model as a file input."""
        mime_type = MIME_BY_EXTENSION.get(ext)
        if not mime_type:
            raise ValueError(f"Unsupported file type for LLM extraction: {ext}")

        logger.info(
            "Sending file '%s' (%s, %d bytes) to %s",
            filename, mime_type, len(file_bytes), self._model,
        )

        b64 = base64.standard_b64encode(file_bytes).decode("ascii")

        first_content_item = (
            {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{b64}",
            }
            if ext in IMAGE_EXTENSIONS
            else {
                "type": "input_file",
                "file_data": f"data:{mime_type};base64,{b64}",
                "filename": filename,
            }
        )

        response = self._client.responses.create(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        first_content_item,
                        {
                            "type": "input_text",
                            "text": self._build_user_instruction(
                                "Extract all STAL article code mappings from this file.",
                                instructions,
                            ),
                        },
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "extraction_result",
                    "schema": EXTRACTION_SCHEMA,
                    "strict": True,
                }
            },
        )

        return self._parse_response(response)

    def extract_code_sets_from_text(self, text: str, instructions: str | None = None) -> DeepExtractionResult:
        """Send pre-parsed tabular text to LLM and get external article code groups."""
        logger.info("Sending %d chars of tabular text for deep extraction to %s", len(text), self._model)
        input_text = self._build_user_instruction(
            f"Extract all product article code groups from this tabular content:\n\n{text}",
            instructions,
        )

        response = self._client.responses.create(
            model=self._model,
            instructions=DEEP_EXTRACTION_SYSTEM_PROMPT,
            input=input_text,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "deep_extraction_result",
                    "schema": DEEP_EXTRACTION_SCHEMA,
                    "strict": True,
                }
            },
        )

        return self._parse_deep_response(response)

    def extract_code_sets_from_file(
        self,
        file_bytes: bytes,
        filename: str,
        ext: str,
        instructions: str | None = None,
    ) -> DeepExtractionResult:
        """Send a PDF or image directly to the model for external code group extraction."""
        mime_type = MIME_BY_EXTENSION.get(ext)
        if not mime_type:
            raise ValueError(f"Unsupported file type for LLM extraction: {ext}")

        logger.info(
            "Sending file '%s' (%s, %d bytes) for deep extraction to %s",
            filename, mime_type, len(file_bytes), self._model,
        )

        b64 = base64.standard_b64encode(file_bytes).decode("ascii")
        first_content_item = (
            {
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{b64}",
            }
            if ext in IMAGE_EXTENSIONS
            else {
                "type": "input_file",
                "file_data": f"data:{mime_type};base64,{b64}",
                "filename": filename,
            }
        )

        response = self._client.responses.create(
            model=self._model,
            instructions=DEEP_EXTRACTION_SYSTEM_PROMPT,
            input=[
                {
                    "role": "user",
                    "content": [
                        first_content_item,
                        {
                            "type": "input_text",
                            "text": self._build_user_instruction(
                                "Extract all product article code groups from this file.",
                                instructions,
                            ),
                        },
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "deep_extraction_result",
                    "schema": DEEP_EXTRACTION_SCHEMA,
                    "strict": True,
                }
            },
        )

        return self._parse_deep_response(response)

    def refine_items(self, items: list[ExtractionItem], correction: str) -> ExtractionResult:
        """Apply a user's free-form correction to already extracted mappings."""
        current_items = [item.model_dump() for item in items]
        input_text = (
            "You are editing a previously extracted STAL mapping preview.\n"
            "Apply the user's correction to the current JSON items and return the full updated list.\n"
            "Preserve valid unchanged items. Remove items only if the user explicitly asks for that.\n\n"
            f"Current items:\n{json.dumps(current_items, ensure_ascii=False)}\n\n"
            f"User correction:\n{correction.strip()}"
        )

        response = self._client.responses.create(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            input=input_text,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "extraction_result",
                    "schema": EXTRACTION_SCHEMA,
                    "strict": True,
                }
            },
        )

        return self._parse_response(response)

    def extract_from_pdf(self, file_bytes: bytes, filename: str) -> ExtractionResult:
        """Backward-compatible alias for PDF-only callers."""
        return self.extract_from_file(file_bytes, filename, ".pdf")

    @staticmethod
    def _parse_response(response) -> ExtractionResult:
        raw_text = response.output_text
        data = json.loads(raw_text)
        items = [
            ExtractionItem(
                stal_code=it["stal_code"],
                aliases=it.get("aliases", []),
                source_fragment=it.get("source_fragment"),
            )
            for it in data.get("items", [])
            if it.get("stal_code")
        ]
        logger.info("Extracted %d mapping groups from LLM response", len(items))
        return ExtractionResult(items=items)

    @staticmethod
    def _parse_deep_response(response) -> DeepExtractionResult:
        raw_text = response.output_text
        data = json.loads(raw_text)
        code_sets = [
            [str(code).strip() for code in code_set if str(code).strip()]
            for code_set in data.get("externalCodeSets", [])
            if isinstance(code_set, list)
        ]
        code_sets = [code_set for code_set in code_sets if code_set]
        logger.info("Extracted %d external code sets from LLM response", len(code_sets))
        return DeepExtractionResult(external_code_sets=code_sets)
