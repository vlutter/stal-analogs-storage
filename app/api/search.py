from fastapi import APIRouter, Query

from app.schemas.search import SearchByStalResult, SearchResult
from app.services.search_service import SearchService

router = APIRouter(prefix="/search", tags=["Search"])

_service = SearchService()


@router.get("", response_model=SearchResult)
async def search_by_alias(
    article: str = Query(..., min_length=1, description="Артикул для поиска"),
):
    """Найти STAL-артикул по любому альтернативному артикулу."""
    return _service.search_by_alias(article)


@router.get("/by-stal", response_model=SearchByStalResult)
async def search_by_stal(
    article: str = Query(..., min_length=1, description="STAL-артикул"),
):
    """Получить запись по STAL-артикулу."""
    return _service.search_by_stal(article)
