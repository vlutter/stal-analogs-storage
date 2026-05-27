import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.api.openapi_common import AUTH_DESCRIPTION, COMMON_RESPONSES
from app.schemas.agent import AgentCommandResponse, IngestFileResponse, RefineIngestItemsRequest
from app.schemas.mapping import BulkUpsertRequest
from app.services.agent_command_service import AgentCommandService
from app.services.agent_service import AgentService
from app.services.file_storage_service import FileStorageService
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}
ALLOWED_EXTENSIONS_TEXT = ", ".join(sorted(ALLOWED_EXTENSIONS))

_service = AgentService()
_file_storage = FileStorageService()
_session_service = SessionService(file_storage=_file_storage)
_command_service = AgentCommandService(sessions=_session_service)


def get_file_storage() -> FileStorageService:
    """Access the shared FileStorageService instance (used during app startup)."""
    return _file_storage


@router.post(
    "/ingest-file",
    response_model=IngestFileResponse,
    summary="Извлечь соответствия из файла",
    description=(
        "Загружает файл и извлекает пары «STAL-артикул → аналоги» с помощью парсера "
        "и/или LLM (OpenAI).\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        f"**Поддерживаемые форматы:** {ALLOWED_EXTENSIONS_TEXT}.\n\n"
        "**Поведение:**\n"
        "- Табличные файлы (xlsx, xls, csv) обрабатываются структурным парсером.\n"
        "- PDF и изображения отправляются в LLM для распознавания таблиц с артикулами.\n"
        "- Извлечённые записи сохраняются в Google Sheets.\n"
        "- Поле `llm_items` содержит детальный предпросмотр для последующей правки."
    ),
    responses={
        200: {"description": "Файл обработан; в ответе — статистика и список извлечённых записей."},
        400: {"description": "Неподдерживаемый формат, пустой файл или ошибка валидации."},
        500: {"description": "Внутренняя ошибка при обработке файла или вызове LLM."},
        **COMMON_RESPONSES,
    },
)
async def ingest_file(
    file: UploadFile = File(..., description="Файл с таблицей или списком артикулов."),
):
    filename = file.filename or "unknown"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            detail=f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS_TEXT}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail="Uploaded file is empty")

    try:
        return _service.ingest_file(filename, file_bytes)
    except ValueError as e:
        logger.warning("Validation error while processing file '%s': %s", filename, e)
        raise HTTPException(400, detail=str(e))
    except Exception:
        logger.exception("Failed to process file '%s'", filename)
        raise HTTPException(500, detail="Internal error while processing file")


@router.post(
    "/deep-extraction",
    response_model=BulkUpsertRequest,
    summary="Глубокое извлечение из файла (preview)",
    description=(
        "Загружает файл, извлекает из него **наборы/строки артикулов**, затем выполняет "
        "глубокое сопоставление с уже сохранёнными данными в Google Sheets.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        f"**Поддерживаемые форматы:** {ALLOWED_EXTENSIONS_TEXT}.\n\n"
        "**Отличие от `/agent/ingest-file`:**\n"
        "- Не ищет прямые пары STAL → аналог в файле.\n"
        "- Ищет косвенные связи: если артикул из строки файла уже есть в таблице "
        "(как STAL или аналог), вся строка добавляется к найденному STAL-артикулу.\n"
        "- Результат — предпросмотр `BulkUpsertRequest` без автоматического сохранения."
    ),
    responses={
        200: {"description": "Предпросмотр массового обновления сформирован."},
        400: {"description": "Неподдерживаемый формат, пустой файл или ошибка валидации."},
        500: {"description": "Внутренняя ошибка при обработке файла."},
        **COMMON_RESPONSES,
    },
)
async def deep_extraction(
    file: UploadFile = File(..., description="Файл с наборами/строками артикулов для глубокого поиска."),
):
    filename = file.filename or "unknown"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            detail=f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS_TEXT}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(400, detail="Uploaded file is empty")

    try:
        return _service.deep_extraction_file(filename, file_bytes)
    except ValueError as e:
        logger.warning("Validation error while deep-processing file '%s': %s", filename, e)
        raise HTTPException(400, detail=str(e))
    except Exception:
        logger.exception("Failed to deep-process file '%s'", filename)
        raise HTTPException(500, detail="Internal error while deep-processing file")


@router.post(
    "/refine-ingest-items",
    response_model=IngestFileResponse,
    summary="Скорректировать предпросмотр извлечения",
    description=(
        "Применяет текстовую правку к уже извлечённым записям **без сохранения** в Google Sheets.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "**Типичный сценарий:**\n"
        "1. Вызвать `POST /agent/ingest-file` и получить `llm_items`.\n"
        "2. Отправить их сюда вместе с полем `correction` (инструкция на естественном языке).\n"
        "3. Получить обновлённый предпросмотр; при необходимости повторить шаг 2."
    ),
    responses={
        200: {"description": "Предпросмотр успешно скорректирован."},
        400: {"description": "Пустой список items, пустая correction или ошибка валидации."},
        500: {"description": "Внутренняя ошибка при вызове LLM."},
        **COMMON_RESPONSES,
    },
)
async def refine_ingest_items(body: RefineIngestItemsRequest):
    try:
        return _service.refine_ingest_items(body)
    except ValueError as e:
        logger.warning("Validation error while refining ingest preview: %s", e)
        raise HTTPException(400, detail=str(e))
    except Exception:
        logger.exception("Failed to refine ingest preview for '%s'", body.filename)
        raise HTTPException(500, detail="Internal error while refining ingest preview")


@router.post(
    "/command",
    response_model=AgentCommandResponse,
    summary="Выполнить команду на естественном языке",
    description=(
        "Принимает текстовую команду пользователя (русский или английский) и опционально файл. "
        "LLM-агент выбирает подходящий инструмент и выполняет действие.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        f"**Поддерживаемые форматы файла:** {ALLOWED_EXTENSIONS_TEXT}.\n\n"
        "**Примеры команд:**\n"
        "- «Добавь аналоги P551039 и P550690 к ST20868»\n"
        "- «Найди ST11013» / «Найди AT112393»\n"
        "- «Обработай прикреплённый файл» (с файлом в multipart)\n"
        "- «Сделай глубокий поиск по файлу» (с файлом в multipart)\n\n"
        "**Формат запроса:** `multipart/form-data` с полями `message` (текст) и `file` (опционально)."
    ),
    responses={
        200: {"description": "Команда обработана; в ответе — текст для пользователя и результат инструмента."},
        400: {"description": "Неподдерживаемый формат файла, пустой файл или ошибка валидации."},
        500: {"description": "Внутренняя ошибка агента или LLM."},
        **COMMON_RESPONSES,
    },
)
async def run_command(
    user_id: str = Form(
        ...,
        description="Идентификатор пользователя (telegram user_id) для привязки контекста диалога.",
        examples=["123456789"],
    ),
    message: str = Form(
        default="",
        description="Текст команды пользователя на русском или английском языке.",
        examples=["Добавь аналог P551039 к ST20868"],
    ),
    file: UploadFile | None = File(
        default=None,
        description="Опциональный файл для импорта или глубокого поиска.",
    ),
):
    filename = file.filename if file else None
    file_bytes: bytes | None = None
    content_type: str | None = None

    if file is not None:
        filename = file.filename or "unknown"
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                400,
                detail=f"Unsupported file type '{ext}'. Allowed: {ALLOWED_EXTENSIONS_TEXT}",
            )

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(400, detail="Uploaded file is empty")
        content_type = file.content_type

    try:
        return _command_service.run(
            message=message,
            user_id=user_id,
            file_bytes=file_bytes,
            filename=filename,
            content_type=content_type,
        )
    except ValueError as e:
        logger.warning("Validation error while running agent command: %s", e)
        raise HTTPException(400, detail=str(e))
    except Exception:
        logger.exception("Failed to run agent command")
        raise HTTPException(500, detail="Internal error while running agent command")


@router.post(
    "/session/reset",
    summary="Сбросить контекст диалога",
    description=(
        "Закрывает активную сессию пользователя и начинает новую. "
        "Используется ботом для команды `/new`.\n\n"
        f"{AUTH_DESCRIPTION}"
    ),
    responses={
        200: {"description": "Сессия успешно сброшена."},
        **COMMON_RESPONSES,
    },
)
async def reset_session(
    user_id: str = Form(
        ...,
        description="Идентификатор пользователя (telegram user_id) для сброса контекста.",
        examples=["123456789"],
    ),
):
    try:
        session = _session_service.reset(user_id)
        return {"status": "ok", "session_id": session.id}
    except Exception:
        logger.exception("Failed to reset agent session for user_id=%s", user_id)
        raise HTTPException(500, detail="Internal error while resetting session")
