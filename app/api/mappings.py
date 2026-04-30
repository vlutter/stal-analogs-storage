import logging

from fastapi import APIRouter, HTTPException

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


@router.post("", response_model=MappingResponse, status_code=201)
async def create_mapping(body: MappingCreate):
    """Создать новую запись соответствия артикулов."""
    try:
        return _service.create(body)
    except ValueError as e:
        logger.warning("Failed to create mapping for '%s': %s", body.stal_code, e)
        raise HTTPException(409, detail=str(e))


@router.get("", response_model=list[MappingResponse])
async def get_all_mappings():
    """Получить все записи соответствий."""
    return _service.get_all()


@router.get("/{stal_code}", response_model=MappingResponse)
async def get_mapping(stal_code: str):
    """Получить запись по STAL-артикулу."""
    result = _service.get(stal_code)
    if result is None:
        raise HTTPException(404, detail=f"Mapping for '{stal_code}' not found")
    return result


@router.patch("/{stal_code}", response_model=MappingResponse)
async def update_mapping(stal_code: str, body: MappingUpdate):
    """Обновить aliases для STAL-артикула."""
    try:
        return _service.update(stal_code, body)
    except ValueError as e:
        logger.warning("Failed to update mapping for '%s': %s", stal_code, e)
        raise HTTPException(404, detail=str(e))


@router.delete("/{stal_code}", response_model=MappingDeleteResponse)
async def delete_mapping(stal_code: str):
    """Удалить запись по STAL-артикулу."""
    deleted = _service.delete(stal_code)
    if not deleted:
        raise HTTPException(404, detail=f"Mapping for '{stal_code}' not found")
    return MappingDeleteResponse(deleted=True, stal_code=stal_code)


@router.post("/bulk-upsert", response_model=BulkUpsertResponse)
async def bulk_upsert(body: BulkUpsertRequest):
    """Массовое создание / обновление записей."""
    try:
        return _service.bulk_upsert(body)
    except ValueError as e:
        logger.warning("Failed to bulk upsert mappings: %s", e)
        raise HTTPException(400, detail=str(e))


@router.post("/deep-extraction", response_model=BulkUpsertRequest)
async def deep_extraction(body: DeepExtractionRequest):
    """Собрать preview массового обновления по внешним наборам артикулов."""
    return _service.deep_extraction(body)
