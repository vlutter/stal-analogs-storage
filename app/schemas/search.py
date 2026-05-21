from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    query: str = Field(..., description="Исходный артикул из запроса (до нормализации).")
    found: bool = Field(..., description="Найдено ли соответствие в хранилище.")
    stal_code: str | None = Field(
        default=None,
        description="STAL-артикул, если совпадение найдено; иначе `null`.",
    )
    matched_alias: str | None = Field(
        default=None,
        description=(
            "Артикул из записи, по которому произошло совпадение "
            "(может совпадать с `stal_code`, если искали сам STAL-код)."
        ),
    )


class SearchByStalResult(BaseModel):
    query: str = Field(..., description="Исходный STAL-артикул из запроса.")
    found: bool = Field(..., description="Существует ли запись с таким STAL-артикулом.")
    stal_code: str | None = Field(
        default=None,
        description="Нормализованный STAL-артикул из хранилища; `null`, если запись не найдена.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Все аналоги для найденного STAL-артикула; пустой список, если запись не найдена.",
    )
