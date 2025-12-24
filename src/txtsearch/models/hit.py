from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from txtsearch.models.base import (
    RecordModel,
    ensure_metadata_dict,
    ensure_uuid_str,
)
from txtsearch.models.enums import SearchStrategy


class Highlight(BaseModel):
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    label: str | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @model_validator(mode="after")
    def _validate_ranges(self) -> "Highlight":
        if self.char_end < self.char_start:
            raise ValueError("char_end must be greater than or equal to char_start")
        if self.line_start is not None and self.line_end is not None:
            if self.line_end < self.line_start:
                raise ValueError("line_end must be greater than or equal to line_start")
        return self


class SearchHit(RecordModel):
    SCHEMA_VERSION: ClassVar[str] = "search_hit.v1"

    schema_version: str = Field(default=SCHEMA_VERSION)
    hit_id: str
    query_id: str
    document_id: str
    chunk_id: str | None = None
    rank: int = Field(ge=0)
    score: float | None = Field(default=None)
    strategy: SearchStrategy
    snippet: str | None = None
    highlights: list[Highlight] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("hit_id", "query_id", "document_id", "chunk_id", mode="before")
    @classmethod
    def _normalize_ids(cls, value: Any) -> str | None:
        if value is None:
            return None
        return ensure_uuid_str(value)

    @field_validator("metadata", mode="before")
    @classmethod
    def _normalize_metadata(cls, value: Any) -> dict[str, Any]:
        return ensure_metadata_dict(value)

    @field_validator("highlights", mode="before")
    @classmethod
    def _coerce_highlights(cls, value: Any) -> list[Highlight] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [Highlight.model_validate(item) for item in value]
        raise TypeError("highlights must be a list of Highlight objects")

    @model_validator(mode="after")
    def _validate_score(self) -> "SearchHit":
        if self.score is not None and not (0.0 <= self.score <= 1.0):
            raise ValueError("score must be between 0 and 1")
        return self


__all__ = ["SearchHit", "Highlight"]
