from datetime import datetime
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from txtsearch.models.base import (
    RecordModel,
    ensure_metadata_dict,
    ensure_non_empty_text,
    ensure_timezone_aware,
    ensure_uuid_str,
)
from txtsearch.models.enums import SearchStrategy, SourceType


class QueryFilters(BaseModel):
    document_ids: list[str] | None = None
    source_types: set[SourceType] | None = None
    metadata_eq: dict[str, Any] | None = None
    ingested_after: datetime | None = None

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @field_validator("document_ids", mode="before")
    @classmethod
    def _normalize_document_ids(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        return [ensure_uuid_str(item) for item in value]

    @field_validator("metadata_eq", mode="before")
    @classmethod
    def _normalize_metadata(cls, value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        return ensure_metadata_dict(value)

    @field_validator("ingested_after", mode="before")
    @classmethod
    def _validate_ingested_after(cls, value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            raise TypeError("ingested_after must be a datetime")
        return ensure_timezone_aware(value)

    def has_filters(self) -> bool:
        return any(
            value not in (None, {}, [], set())
            for value in (
                self.document_ids,
                self.source_types,
                self.metadata_eq,
                self.ingested_after,
            )
        )


class Query(RecordModel):
    SCHEMA_VERSION: ClassVar[str] = "query.v1"

    schema_version: str = Field(default=SCHEMA_VERSION)
    query_id: str = Field(default_factory=lambda: str(uuid4()))
    text: str
    strategy: SearchStrategy
    top_k: int = Field(default=10, gt=0)
    filters: QueryFilters = Field(default_factory=QueryFilters)
    include_snippets: bool = True
    include_highlights: bool = False

    @field_validator("query_id", mode="before")
    @classmethod
    def _normalize_query_id(cls, value: Any) -> str:
        return ensure_uuid_str(value)

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return ensure_non_empty_text(value, "text")

    @field_validator("filters", mode="before")
    @classmethod
    def _coerce_filters(cls, value: Any) -> QueryFilters:
        if isinstance(value, QueryFilters):
            return value
        if value is None:
            return QueryFilters()
        return QueryFilters.model_validate(value)


__all__ = ["Query", "QueryFilters"]
