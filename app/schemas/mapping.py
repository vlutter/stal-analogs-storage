from pydantic import BaseModel, ConfigDict, Field


class MappingCreate(BaseModel):
    stal_code: str = Field(..., min_length=1, examples=["ST20868"])
    aliases: list[str] = Field(default_factory=list, examples=[["P551039", "P550690", "6667352"]])
    source_filename: str | None = Field(default=None, examples=["BOBCAT.xlsx"])


class MappingUpdate(BaseModel):
    aliases: list[str] = Field(..., min_length=1, examples=[["P551039", "P550690"]])
    append: bool = Field(
        default=False,
        description="If true, append aliases to existing ones instead of replacing",
    )
    source_filename: str | None = None


class MappingResponse(BaseModel):
    stal_code: str
    aliases: list[str]


class BulkUpsertItem(BaseModel):
    stal_code: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    alias_parent_codes: dict[str, str] = Field(default_factory=dict)


class BulkUpsertRequest(BaseModel):
    source_filename: str | None = None
    items: list[BulkUpsertItem] = Field(default_factory=list)


class DeepExtractionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    external_code_sets: list[list[str]] = Field(
        default_factory=list,
        validation_alias="externalCodeSets",
        serialization_alias="externalCodeSets",
    )


class BulkUpsertResponse(BaseModel):
    created: int
    updated: int
    total: int


class MappingDeleteResponse(BaseModel):
    deleted: bool
    stal_code: str
