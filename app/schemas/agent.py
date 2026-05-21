from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractionItem(BaseModel):
    stal_code: str = Field(..., description="Извлечённый STAL-артикул.")
    aliases: list[str] = Field(
        default_factory=list,
        description="Аналоги, извлечённые для данного STAL-артикула.",
    )
    source_fragment: str | None = Field(
        default=None,
        description="Фрагмент исходного текста или таблицы, на основании которого сделано извлечение.",
    )


class ExtractionResult(BaseModel):
    items: list[ExtractionItem] = Field(
        default_factory=list,
        description="Список извлечённых пар STAL → аналоги.",
    )


class DeepExtractionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    external_code_sets: list[list[str]] = Field(
        default_factory=list,
        validation_alias="externalCodeSets",
        serialization_alias="externalCodeSets",
        description="Наборы артикулов, извлечённые из файла для последующего глубокого сопоставления.",
    )


class IngestFileResponse(BaseModel):
    filename: str = Field(..., description="Имя загруженного файла.")
    items_extracted: int = Field(..., description="Количество извлечённых записей STAL → аналоги.")
    items_saved: int = Field(
        ...,
        description="Количество записей, сохранённых в Google Sheets (0 для режима предпросмотра).",
    )
    status: str = Field(
        default="success",
        description="Статус обработки: `success`, `no_mappings_found` и др.",
    )
    llm_items: list[ExtractionItem] = Field(
        default_factory=list,
        description="Детальный список извлечённых записей для предпросмотра или правки.",
    )


class RefineIngestItemsRequest(BaseModel):
    filename: str = Field(..., description="Имя файла, к которому относится предпросмотр.")
    items: list[ExtractionItem] = Field(
        ...,
        min_length=1,
        description="Текущий предпросмотр извлечённых записей, который нужно скорректировать.",
    )
    correction: str = Field(
        ...,
        min_length=1,
        description=(
            "Текстовая инструкция для LLM: что исправить в предпросмотре "
            "(например, «убери дубликаты» или «ST20868 должен иметь только P551039»)."
        ),
    )


class AgentCommandResponse(BaseModel):
    message: str = Field(..., description="Ответ агента пользователю на естественном языке (русский).")
    tool_name: str | None = Field(
        default=None,
        description="Имя вызванного инструмента, если команда была распознана; иначе `null`.",
    )
    tool_arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Аргументы, переданные выбранному инструменту.",
    )
    result: dict[str, Any] = Field(
        default_factory=dict,
        description="Структурированный результат выполнения инструмента.",
    )
