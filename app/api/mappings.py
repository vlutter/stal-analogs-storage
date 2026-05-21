import logging

from fastapi import APIRouter, HTTPException, Path

from app.api.openapi_common import AUTH_DESCRIPTION, COMMON_RESPONSES
from app.schemas.mapping import (
    BulkUpsertRequest,
    BulkUpsertResponse,
    DeepExtractionRequest,
    MappingCreate,
    MappingDeleteResponse,
    MappingResponse,
    MappingUpdate,
)
from app.services.mapping_service import MappingService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mappings", tags=["Mappings"])

_service = MappingService()

_MAPPING_RESPONSES = {
    **COMMON_RESPONSES,
    404: {"description": "Запись с указанным STAL-артикулом не найдена."},
}


@router.post(
    "",
    response_model=MappingResponse,
    status_code=201,
    summary="Создать соответствие",
    description=(
        "Создаёт новую запись «STAL-артикул → список аналогов» в Google Sheets.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "**Поведение:**\n"
        "- STAL-код и аналоги нормализуются перед сохранением.\n"
        "- Дубликаты аналогов в одном запросе отбрасываются.\n"
        "- Если запись с таким STAL-артикулом уже существует, возвращается ошибка 409."
    ),
    responses={
        201: {"description": "Запись успешно создана."},
        409: {"description": "Запись с таким STAL-артикулом уже существует."},
        **COMMON_RESPONSES,
    },
)
async def create_mapping(body: MappingCreate):
    try:
        return _service.create(body)
    except ValueError as e:
        logger.warning("Failed to create mapping for '%s': %s", body.stal_code, e)
        raise HTTPException(409, detail=str(e))


@router.get(
    "",
    response_model=list[MappingResponse],
    summary="Получить все соответствия",
    description=(
        "Возвращает полный список записей из Google Sheets: каждый STAL-артикул "
        "и все связанные с ним аналоги.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "**Примечание:** при большом объёме данных ответ может быть объёмным; "
        "для точечного поиска используйте `GET /mappings/{{stal_code}}` или эндпоинты `/search`."
    ),
    responses={
        200: {"description": "Список всех записей."},
        **COMMON_RESPONSES,
    },
)
async def get_all_mappings():
    return _service.get_all()


@router.get(
    "/{stal_code}",
    response_model=MappingResponse,
    summary="Получить соответствие по STAL-артикулу",
    description=(
        "Возвращает одну запись по STAL-артикулу.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "Артикул в пути нормализуется так же, как при записи в хранилище."
    ),
    responses={
        200: {"description": "Запись найдена."},
        **_MAPPING_RESPONSES,
    },
)
async def get_mapping(
    stal_code: str = Path(..., description="STAL-артикул, например `ST20868`."),
):
    result = _service.get(stal_code)
    if result is None:
        raise HTTPException(404, detail=f"Mapping for '{stal_code}' not found")
    return result


@router.patch(
    "/{stal_code}",
    response_model=MappingResponse,
    summary="Обновить аналоги",
    description=(
        "Обновляет список аналогов для существующего STAL-артикула.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "**Режимы:**\n"
        "- `append: false` (по умолчанию) — полная замена списка аналогов.\n"
        "- `append: true` — добавление новых аналогов к существующим без дубликатов."
    ),
    responses={
        200: {"description": "Запись успешно обновлена."},
        **_MAPPING_RESPONSES,
    },
)
async def update_mapping(
    stal_code: str = Path(..., description="STAL-артикул существующей записи."),
    body: MappingUpdate = ...,
):
    try:
        return _service.update(stal_code, body)
    except ValueError as e:
        logger.warning("Failed to update mapping for '%s': %s", stal_code, e)
        raise HTTPException(404, detail=str(e))


@router.delete(
    "/{stal_code}",
    response_model=MappingDeleteResponse,
    summary="Удалить соответствие",
    description=(
        "Полностью удаляет строку с указанным STAL-артикулом из Google Sheets "
        "вместе со всеми аналогами.\n\n"
        f"{AUTH_DESCRIPTION}"
    ),
    responses={
        200: {"description": "Запись успешно удалена."},
        **_MAPPING_RESPONSES,
    },
)
async def delete_mapping(
    stal_code: str = Path(..., description="STAL-артикул записи для удаления."),
):
    deleted = _service.delete(stal_code)
    if not deleted:
        raise HTTPException(404, detail=f"Mapping for '{stal_code}' not found")
    return MappingDeleteResponse(deleted=True, stal_code=stal_code)


@router.post(
    "/bulk-upsert",
    response_model=BulkUpsertResponse,
    summary="Массовое создание и обновление",
    description=(
        "Создаёт новые записи или дополняет аналоги у существующих STAL-артикулов "
        "одним запросом.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "**Поведение:**\n"
        "- Если STAL-артикула нет — создаётся новая строка.\n"
        "- Если STAL-артикул уже есть — новые аналоги добавляются к существующим "
        "(существующие аналоги не удаляются).\n"
        "- Поле `alias_parent_codes` сохраняет связи из глубокого поиска.\n"
        "- Пустой список `items` возвращает ошибку 400."
    ),
    responses={
        200: {"description": "Массовая операция выполнена; в ответе — счётчики created/updated."},
        400: {"description": "Пустой список items или некорректные данные."},
        **COMMON_RESPONSES,
    },
)
async def bulk_upsert(body: BulkUpsertRequest):
    try:
        return _service.bulk_upsert(body)
    except ValueError as e:
        logger.warning("Failed to bulk upsert mappings: %s", e)
        raise HTTPException(400, detail=str(e))


@router.post(
    "/deep-extraction",
    response_model=BulkUpsertRequest,
    summary="Глубокое сопоставление (preview)",
    description=(
        "Формирует **предпросмотр** массового обновления по внешним наборам артикулов "
        "без записи в Google Sheets.\n\n"
        f"{AUTH_DESCRIPTION}\n\n"
        "**Алгоритм глубокого поиска:**\n"
        "1. Для каждого набора из `externalCodeSets` проверяются все его артикулы "
        "против уже сохранённых STAL-кодов и аналогов.\n"
        "2. Если хотя бы один артикул набора найден в таблице, весь набор добавляется "
        "к STAL-артикулу найденной строки как новые аналоги.\n"
        "3. В ответе — структура `BulkUpsertRequest`, которую можно передать "
        "в `POST /mappings/bulk-upsert` для сохранения."
    ),
    responses={
        200: {"description": "Предпросмотр сформирован (может содержать пустой items, если совпадений нет)."},
        **COMMON_RESPONSES,
    },
)
async def deep_extraction(body: DeepExtractionRequest):
    return _service.deep_extraction(body)
