from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    query: str
    found: bool
    stal_code: str | None = None
    matched_alias: str | None = None


class SearchByStalResult(BaseModel):
    query: str
    found: bool
    stal_code: str | None = None
    aliases: list[str] = Field(default_factory=list)
