from pydantic import BaseModel, ConfigDict, Field


class MappingCreate(BaseModel):
    stal_code: str = Field(
        ...,
        min_length=1,
        description="STAL-артикул (основной код товара, обычно формата ST + цифры).",
        examples=["ST20868"],
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Список альтернативных артикулов (аналогов), связанных с данным STAL-кодом.",
        examples=[["P551039", "P550690", "6667352"]],
    )
    source_filename: str | None = Field(
        default=None,
        description="Имя исходного файла, из которого получены данные (для аудита в Google Sheets).",
        examples=["BOBCAT.xlsx"],
    )


class MappingUpdate(BaseModel):
    aliases: list[str] = Field(
        ...,
        min_length=1,
        description="Новый список аналогов для замены или дополнения (см. поле `append`).",
        examples=[["P551039", "P550690"]],
    )
    append: bool = Field(
        default=False,
        description=(
            "Если `true` — новые аналоги добавляются к существующим без дубликатов. "
            "Если `false` — список аналогов полностью заменяется."
        ),
    )
    source_filename: str | None = Field(
        default=None,
        description="Имя исходного файла для записи в журнал изменений Google Sheets.",
    )


class MappingResponse(BaseModel):
    stal_code: str = Field(..., description="STAL-артикул записи.")
    aliases: list[str] = Field(..., description="Все известные аналоги для данного STAL-артикула.")


class BulkUpsertItem(BaseModel):
    stal_code: str = Field(..., min_length=1, description="STAL-артикул для создания или обновления.")
    aliases: list[str] = Field(
        default_factory=list,
        description="Аналоги, которые нужно добавить к STAL-артикулу (существующие не удаляются).",
    )
    alias_parent_codes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Связь «аналог → родительский артикул» из глубокого поиска. "
            "Ключ — код аналога, значение — артикул из внешнего набора, через который найдено совпадение."
        ),
    )


class BulkUpsertRequest(BaseModel):
    source_filename: str | None = Field(
        default=None,
        description="Имя файла-источника для аудита при массовой записи в Google Sheets.",
    )
    items: list[BulkUpsertItem] = Field(
        default_factory=list,
        description="Список записей для массового создания или обновления.",
    )


class DeepExtractionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    external_code_sets: list[list[str]] = Field(
        default_factory=list,
        validation_alias="externalCodeSets",
        serialization_alias="externalCodeSets",
        description=(
            "Наборы внешних артикулов (строки/группы из файла). "
            "Для каждого набора выполняется сопоставление с уже сохранёнными STAL-кодами и аналогами; "
            "совпавшие наборы добавляются как новые аналоги к найденным STAL-артикулам."
        ),
    )


class BulkUpsertResponse(BaseModel):
    created: int = Field(..., description="Количество новых записей, созданных в Google Sheets.")
    updated: int = Field(..., description="Количество существующих записей, у которых обновлены аналоги.")
    total: int = Field(..., description="Сумма `created` и `updated`.")


class MappingDeleteResponse(BaseModel):
    deleted: bool = Field(..., description="Признак успешного удаления (`true`).")
    stal_code: str = Field(..., description="STAL-артикул удалённой записи.")
