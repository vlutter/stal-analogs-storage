from fastapi import APIRouter, Query

from app.api.openapi_common import AUTH_DESCRIPTION, COMMON_RESPONSES
from app.schemas.search import SearchByStalResult, SearchResult
from app.services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["Search"])

_service = SearchService()


@router.get(
    "",
    response_model=SearchResult,
    summary="Поиск STAL-артикула по аналогу",
    description=(
        "Ищет STAL-артикул по любому альтернативному артикулу или по самому STAL-коду.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "**Поведение:**\n"
        "- Поиск выполняется по всем аналогам всех записей, а также по колонке STAL.\n"
        "- Артикул нормализуется перед сравнением (регистр, пробелы и т.п.).\n"
        "- Если совпадение не найдено, `found: false`, поля `stal_code` и `matched_alias` — `null`."
    ),
    responses={
        200: {"description": "Результат поиска (найдено или нет)."},
        **COMMON_RESPONSES,
    },
)
async def search_by_alias(
    article: str = Query(
        ...,
        min_length=1,
        description="Артикул для поиска: аналог (например, P551039) или STAL-код.",
        examples=["P551039"],
    ),
):
    return _service.search_by_alias(article)


@router.get(
    "/by-stal",
    response_model=SearchByStalResult,
    summary="Получить аналоги по STAL-артикулу",
    description=(
        "Возвращает запись по точному STAL-артикулу: сам код и полный список аналогов.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "В отличие от `GET /search`, здесь запрос всегда интерпретируется как STAL-код, "
        "а не как произвольный аналог."
    ),
    responses={
        200: {"description": "Результат поиска по STAL-артикулу."},
        **COMMON_RESPONSES,
    },
)
async def search_by_stal(
    article: str = Query(
        ...,
        min_length=1,
        description="STAL-артикул, например ST20868.",
        examples=["ST20868"],
    ),
):
    return _service.search_by_stal(article)
