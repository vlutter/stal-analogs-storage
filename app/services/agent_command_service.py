"""Natural-language command agent backed by OpenAI tool calling."""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from app.schemas.agent import AgentCommandResponse
from app.schemas.mapping import BulkUpsertItem, BulkUpsertRequest, MappingUpdate
from app.services.agent_service import AgentService
from app.services.mapping_service import MappingService
from app.services.search_service import SearchService
from app.utils.settings import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a command router for the STAL analogs storage backend.

Your job is to choose the best tool for a user's Russian or English command.
Never invent article codes. Extract only codes explicitly present in the user's message.
If the request is unclear, out of scope, or missing the article codes needed for an action, do not call any tool.

Rules:
- STAL article codes usually look like ST followed by digits, for example ST20868.
- Aliases are non-STAL article codes related to the same physical product.
- Use add_aliases for commands like "добавь", "добавить аналоги", "append".
- Use remove_aliases only when the user wants to remove specific aliases from a STAL code.
- Use set_aliases only when the user clearly wants to replace the full alias list.
- Use delete_mapping only when the user explicitly asks to delete the whole STAL mapping, not just an alias.
- Use ingest_file when a file is attached and the user asks to import, ingest, extract, parse, or process it.
- Use deep_extraction_file when a file is attached and the user asks for deep search, deep extraction,
  indirect matches, searching through the existing database, or finding analogs through another article.
- If a file is attached, put the user's extraction preferences into the ingest_file instructions argument.
- If deep_extraction_file is selected, put the user's extraction preferences into its instructions argument.
- Use search_by_stal when the user asks to find all articles for an explicitly provided STAL code, for example "Найди ST11013".
- Use search_article when the user asks to find the STAL article by a non-STAL alias code, for example "Найди AT112393".
- Use get_mapping when the user explicitly asks to show the stored mapping or aliases for a known STAL code.
- Do not choose a tool for broad analytical requests, questions about unsupported reports, or commands that do not map to these exact actions.
"""

RESPONSE_PROMPT = """\
You write final replies for a Russian-speaking user of the STAL analogs storage agent.

Write a short, natural Russian answer.
Explain what was done and the result. Do not invent facts beyond the provided tool result.
If the operation did not find anything or did not change anything, say that plainly.
Do not mention internal tool names, JSON, schemas, or implementation details.
"""

AGENT_CAPABILITIES = """\
Я умею:
- добавлять соответствия STAL-артикулов и аналогов;
- полностью заменять список аналогов для STAL-артикула;
- удалять конкретные аналоги у STAL-артикула;
- удалять всю связку STAL-артикула;
- искать все артикулы по STAL-коду;
- искать STAL-артикул по аналогу;
- показывать сохраненную связку по STAL-коду;
- массово добавлять связки из текста;
- извлекать связки из приложенного файла;
- выполнять глубокий поиск по приложенному файлу через уже сохраненную базу совпадений.
"""

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "add_aliases",
        "description": "Create a STAL mapping if needed, or append aliases to an existing STAL article.",
        "parameters": {
            "type": "object",
            "properties": {
                "stal_code": {"type": "string", "description": "STAL article code, for example ST123"},
                "aliases": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alias article codes to append",
                },
            },
            "required": ["stal_code", "aliases"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "set_aliases",
        "description": "Replace the full alias list for an existing STAL article.",
        "parameters": {
            "type": "object",
            "properties": {
                "stal_code": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["stal_code", "aliases"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "remove_aliases",
        "description": "Remove specific aliases from an existing STAL article without deleting the STAL mapping.",
        "parameters": {
            "type": "object",
            "properties": {
                "stal_code": {"type": "string"},
                "aliases": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["stal_code", "aliases"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "delete_mapping",
        "description": "Delete the whole mapping row for a STAL article. Use only for explicit full-delete commands.",
        "parameters": {
            "type": "object",
            "properties": {"stal_code": {"type": "string"}},
            "required": ["stal_code"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_article",
        "description": "Find the STAL article for a non-STAL alias article code. Use /search.",
        "parameters": {
            "type": "object",
            "properties": {"article": {"type": "string"}},
            "required": ["article"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "search_by_stal",
        "description": "Find all articles mapped to an explicitly provided STAL article code. Use /search/by-stal.",
        "parameters": {
            "type": "object",
            "properties": {"stal_code": {"type": "string", "description": "STAL article code, for example ST11013"}},
            "required": ["stal_code"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "get_mapping",
        "description": "Get aliases for a known STAL article code.",
        "parameters": {
            "type": "object",
            "properties": {"stal_code": {"type": "string"}},
            "required": ["stal_code"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "bulk_upsert",
        "description": "Create or update multiple STAL mappings from codes listed in the user's text command.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "stal_code": {"type": "string"},
                            "aliases": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["stal_code", "aliases"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "ingest_file",
        "description": "Extract STAL mappings from an attached file using optional user instructions.",
        "parameters": {
            "type": "object",
            "properties": {
                "instructions": {
                    "type": "string",
                    "description": "User preferences for extracting data from the attached file",
                }
            },
            "required": ["instructions"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "deep_extraction_file",
        "description": (
            "Deep-search an attached file through existing mappings. Use this when the user asks to find "
            "indirect STAL analog matches through any article already present in the database."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "instructions": {
                    "type": "string",
                    "description": "User preferences for deep extraction from the attached file",
                }
            },
            "required": ["instructions"],
            "additionalProperties": False,
        },
    },
]


class AgentCommandService:
    def __init__(
        self,
        agent: AgentService | None = None,
        mapping: MappingService | None = None,
        search: SearchService | None = None,
    ) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model
        self._agent = agent or AgentService()
        self._mapping = mapping or MappingService()
        self._search = search or SearchService()

    def run(
        self,
        message: str,
        file_bytes: bytes | None = None,
        filename: str | None = None,
    ) -> AgentCommandResponse:
        tool_call = self._choose_tool(message, has_file=file_bytes is not None, filename=filename)
        if tool_call is None:
            return AgentCommandResponse(
                message=self._unclear_request_message(),
                result={"status": "unclear_request"},
            )

        tool_name = getattr(tool_call, "name", "")
        tool_arguments = self._parse_tool_arguments(getattr(tool_call, "arguments", "{}"))
        logger.info("Agent selected tool '%s' with arguments: %s", tool_name, tool_arguments)

        result = self._execute_tool(tool_name, tool_arguments, file_bytes=file_bytes, filename=filename)
        return AgentCommandResponse(
            message=self._format_response_message(message, tool_name, tool_arguments, result),
            tool_name=tool_name,
            tool_arguments=tool_arguments,
            result=result,
        )

    def _choose_tool(self, message: str, has_file: bool, filename: str | None):
        context = (
            f"User command: {message}\n"
            f"Attached file: {'yes' if has_file else 'no'}\n"
            f"Filename: {filename or ''}"
        )

        response = self._client.responses.create(
            model=self._model,
            instructions=SYSTEM_PROMPT,
            input=context,
            tools=TOOLS,
            tool_choice="auto",
        )

        for item in response.output:
            if getattr(item, "type", None) == "function_call":
                return item
        return None

    @staticmethod
    def _parse_tool_arguments(raw_arguments: str | dict[str, Any]) -> dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        try:
            parsed = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid tool arguments JSON: {raw_arguments}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("Tool arguments must be a JSON object")
        return parsed

    @staticmethod
    def _unclear_request_message() -> str:
        return (
            "Я не до конца понял, какое действие нужно выполнить.\n\n"
            f"{AGENT_CAPABILITIES}\n"
            "Попробуйте сформулировать запрос еще раз: например, укажите STAL-артикул "
            "и аналоги, которые нужно добавить, удалить или найти."
        )

    def _format_response_message(
        self,
        user_message: str,
        tool_name: str,
        tool_arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> str:
        fallback = self._response_message(tool_name, result)
        formatter_input = (
            f"User request:\n{user_message}\n\n"
            f"Selected action:\n{tool_name}\n\n"
            f"Action arguments:\n{json.dumps(tool_arguments, ensure_ascii=False)}\n\n"
            f"Action result:\n{json.dumps(result, ensure_ascii=False)}\n\n"
            f"Fallback answer:\n{fallback}"
        )

        try:
            response = self._client.responses.create(
                model=self._model,
                instructions=RESPONSE_PROMPT,
                input=formatter_input,
            )
        except Exception:
            logger.exception("Failed to format agent command response with LLM")
            return fallback

        message = (getattr(response, "output_text", "") or "").strip()
        return message or fallback

    @staticmethod
    def _response_message(tool_name: str, result: dict[str, Any]) -> str:
        if tool_name == "search_by_stal":
            if not result.get("found"):
                return f"По STAL-артикулу {result.get('query')} ничего не найдено."
            articles = result.get("articles") or []
            return f"Найдены артикулы: {', '.join(articles)}"

        if tool_name == "search_article":
            if not result.get("found"):
                return f"По артикулу {result.get('query')} ничего не найдено."
            return f"Найден STAL-артикул: {result.get('stal_code')}"

        if tool_name == "get_mapping":
            if not result.get("found"):
                return f"Связка для STAL-артикула {result.get('query')} не найдена."
            aliases = result.get("aliases") or []
            return f"Для {result.get('stal_code')} сохранены аналоги: {', '.join(aliases)}"

        if tool_name == "delete_mapping":
            if result.get("deleted"):
                return f"Связка для {result.get('stal_code')} удалена."
            return f"Связка для {result.get('stal_code')} не найдена."

        if tool_name in {"add_aliases", "set_aliases", "remove_aliases"}:
            aliases = result.get("aliases") or []
            if aliases:
                return f"Готово. Для {result.get('stal_code')} сейчас сохранены аналоги: {', '.join(aliases)}"
            return f"Готово. Для {result.get('stal_code')} сейчас нет сохраненных аналогов."

        if tool_name == "bulk_upsert":
            return (
                f"Массовая загрузка выполнена: создано {result.get('created', 0)}, "
                f"обновлено {result.get('updated', 0)}, всего обработано {result.get('total', 0)}."
            )

        if tool_name == "ingest_file":
            status = result.get("status")
            if status == "no_mappings_found":
                return "В файле не удалось найти связки STAL-артикулов."
            return (
                f"Файл обработан: извлечено {result.get('items_extracted', 0)}, "
                "ожидает подтверждения перед сохранением."
            )

        if tool_name == "deep_extraction_file":
            items = result.get("items") or []
            if not items:
                return "По файлу не удалось найти совпадения через сохраненную базу."
            return (
                f"Глубокий поиск выполнен: найдено {len(items)} STAL-строк к обновлению, "
                "ожидает подтверждения перед сохранением."
            )

        return "Команда выполнена."

    def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        file_bytes: bytes | None,
        filename: str | None,
    ) -> dict[str, Any]:
        if tool_name == "add_aliases":
            result = self._mapping.add_aliases(args["stal_code"], args["aliases"], source_filename="agent-command")
            return result.model_dump()

        if tool_name == "set_aliases":
            result = self._mapping.update(
                args["stal_code"],
                MappingUpdate(aliases=args["aliases"], append=False, source_filename="agent-command"),
            )
            return result.model_dump()

        if tool_name == "remove_aliases":
            result = self._mapping.remove_aliases(
                args["stal_code"],
                args["aliases"],
                source_filename="agent-command",
            )
            return result.model_dump()

        if tool_name == "delete_mapping":
            deleted = self._mapping.delete(args["stal_code"])
            return {"deleted": deleted, "stal_code": args["stal_code"]}

        if tool_name == "search_article":
            result = self._search.search_by_alias(args["article"])
            return result.model_dump()

        if tool_name == "search_by_stal":
            result = self._search.search_by_stal(args["stal_code"])
            payload = result.model_dump()
            if result.found and result.stal_code:
                payload["articles"] = [result.stal_code, *result.aliases]
            return payload

        if tool_name == "get_mapping":
            result = self._search.search_by_stal(args["stal_code"])
            return result.model_dump()

        if tool_name == "bulk_upsert":
            items = [
                BulkUpsertItem(stal_code=item["stal_code"], aliases=item.get("aliases", []))
                for item in args["items"]
            ]
            result = self._mapping.bulk_upsert(
                BulkUpsertRequest(source_filename="agent-command", items=items)
            )
            return result.model_dump()

        if tool_name == "ingest_file":
            if not file_bytes or not filename:
                raise ValueError("ingest_file requires an attached file")
            result = self._agent.ingest_file(
                filename,
                file_bytes,
                instructions=args.get("instructions") or None,
            )
            return result.model_dump()

        if tool_name == "deep_extraction_file":
            if not file_bytes or not filename:
                raise ValueError("deep_extraction_file requires an attached file")
            result = self._agent.deep_extraction_file(
                filename,
                file_bytes,
                instructions=args.get("instructions") or None,
            )
            return result.model_dump()

        raise ValueError(f"Unsupported agent tool: {tool_name}")
