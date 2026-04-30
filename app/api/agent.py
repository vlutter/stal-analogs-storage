import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.agent import AgentCommandResponse, IngestFileResponse, RefineIngestItemsRequest
from app.schemas.mapping import BulkUpsertRequest
from app.services.agent_command_service import AgentCommandService
from app.services.agent_service import AgentService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["Agent"])

ALLOWED_EXTENSIONS = {".xlsx", ".xls", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}

_service = AgentService()
_command_service = AgentCommandService()


@router.post("/ingest-file", response_model=IngestFileResponse)
async def ingest_file(file: UploadFile):
    """Загрузить файл для извлечения соответствий артикулов через ИИ."""
    filename = file.filename or "unknown"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
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


@router.post("/deep-extraction", response_model=BulkUpsertRequest)
async def deep_extraction(file: UploadFile):
    """Загрузить файл для глубокого извлечения внешних наборов артикулов."""
    filename = file.filename or "unknown"
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
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


@router.post("/refine-ingest-items", response_model=IngestFileResponse)
async def refine_ingest_items(body: RefineIngestItemsRequest):
    """Применить текстовую правку к предпросмотру ingest без сохранения."""
    try:
        return _service.refine_ingest_items(body)
    except ValueError as e:
        logger.warning("Validation error while refining ingest preview: %s", e)
        raise HTTPException(400, detail=str(e))
    except Exception:
        logger.exception("Failed to refine ingest preview for '%s'", body.filename)
        raise HTTPException(500, detail="Internal error while refining ingest preview")


@router.post("/command", response_model=AgentCommandResponse)
async def run_command(
    message: str = Form(default=""),
    file: UploadFile | None = File(default=None),
):
    """Выполнить команду пользователя в свободной форме через agent tool calling."""
    filename = file.filename if file else None
    file_bytes: bytes | None = None

    if file is not None:
        filename = file.filename or "unknown"
        ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""

        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                400,
                detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(400, detail="Uploaded file is empty")

    try:
        return _command_service.run(message=message, file_bytes=file_bytes, filename=filename)
    except ValueError as e:
        logger.warning("Validation error while running agent command: %s", e)
        raise HTTPException(400, detail=str(e))
    except Exception:
        logger.exception("Failed to run agent command")
        raise HTTPException(500, detail="Internal error while running agent command")
