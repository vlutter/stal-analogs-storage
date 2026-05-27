import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import agent, mappings, search
from app.deps.auth import verify_api_token
from app.repositories.sheets_repository import SheetsRepositoryError
from app.services.file_storage_service import FileStorageError
from app.utils.logging import setup_logging
from app.utils.settings import settings

setup_logging()
logger = logging.getLogger(__name__)

OPENAPI_TAGS = [
    {
        "name": "Mappings",
        "description": (
            "CRUD и массовые операции над соответствиями «STAL-артикул → аналоги». "
            "Данные хранятся в Google Sheets."
        ),
    },
    {
        "name": "Search",
        "description": (
            "Поиск STAL-артикула по аналогу и получение списка аналогов по STAL-коду. "
            "Не изменяет данные."
        ),
    },
    {
        "name": "Agent",
        "description": (
            "Импорт из файлов и обработка команд на естественном языке через LLM (OpenAI). "
            "Поддерживает извлечение, глубокий поиск и интерактивную правку предпросмотра."
        ),
    },
    {
        "name": "System",
        "description": "Служебные эндпоинты мониторинга. Не требуют авторизации.",
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.api_token:
        raise RuntimeError("API_TOKEN is not configured. Set it in .env before starting the server.")

    try:
        agent.get_file_storage().ensure_bucket()
    except FileStorageError as exc:
        raise RuntimeError(
            f"Cannot initialize S3 bucket '{settings.s3_bucket}' at '{settings.s3_endpoint_url}': {exc}"
        ) from exc

    yield


app = FastAPI(
    title=settings.app_title,
    version=settings.app_version,
    description=(
        "REST API для хранения и поиска соответствий артикулов STAL и их аналогов.\n\n"
        "## Аутентификация\n"
        "Все эндпоинты, кроме `/health`, требуют заголовок:\n"
        "`Authorization: Bearer <API_TOKEN>`\n\n"
        "## Хранилище\n"
        "Записи сохраняются в Google Sheets (spreadsheet задаётся переменными окружения).\n\n"
        "## Swagger\n"
        "Интерактивная документация: `/docs`, альтернативная схема OpenAPI: `/redoc`."
    ),
    debug=settings.debug,
    lifespan=lifespan,
    openapi_tags=OPENAPI_TAGS,
)

app.include_router(mappings.router, dependencies=[Depends(verify_api_token)])
app.include_router(search.router, dependencies=[Depends(verify_api_token)])
app.include_router(agent.router, dependencies=[Depends(verify_api_token)])


@app.exception_handler(SheetsRepositoryError)
async def sheets_repository_error_handler(request: Request, exc: SheetsRepositoryError):
    logger.warning("Google Sheets operation failed for %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Google Sheets is temporarily unavailable. Please retry the request."},
    )


@app.get(
    "/health",
    tags=["System"],
    summary="Проверка доступности сервиса",
    description=(
        "Возвращает статус «ok» и версию приложения. "
        "Не требует Bearer-токена — используется для healthcheck в Docker и балансировщиках."
    ),
    responses={
        200: {"description": "Сервис запущен и отвечает на запросы."},
    },
)
async def healthcheck():
    return {"status": "ok", "version": settings.app_version}
