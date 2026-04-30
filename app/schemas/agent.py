from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ExtractionItem(BaseModel):
    stal_code: str
    aliases: list[str] = Field(default_factory=list)
    source_fragment: str | None = None


class ExtractionResult(BaseModel):
    items: list[ExtractionItem] = Field(default_factory=list)


class DeepExtractionResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    external_code_sets: list[list[str]] = Field(
        default_factory=list,
        validation_alias="externalCodeSets",
        serialization_alias="externalCodeSets",
    )


class IngestFileResponse(BaseModel):
    filename: str
    items_extracted: int
    items_saved: int
    status: str = "success"
    llm_items: list[ExtractionItem] = Field(default_factory=list)


class RefineIngestItemsRequest(BaseModel):
    filename: str
    items: list[ExtractionItem] = Field(..., min_length=1)
    correction: str = Field(..., min_length=1)


class AgentCommandResponse(BaseModel):
    message: str
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
