from datetime import datetime
from typing import Any, ClassVar

from pydantic import Field, ValidationInfo, field_validator

from txtsearch.models.base import (
    RecordModel,
    ensure_hex_digest,
    ensure_metadata_dict,
    ensure_non_empty_text,
    ensure_timezone_aware,
    ensure_uuid_str,
)

from txtsearch.models.enums import SourceType


class Document(RecordModel):
    SCHEMA_VERSION: ClassVar[str] = "document.v1"

    schema_version: str = Field(default=SCHEMA_VERSION)
    document_id: str
    uri: str
    display_name: str
    content_hash: str
    size_bytes: int = Field(ge=0)
    source_type: SourceType
    metadata: dict[str, Any] = Field(default_factory=dict)
    ingested_at: datetime

    @field_validator("document_id", mode="before")
    @classmethod
    def _normalize_document_id(cls, value: Any) -> str:
        return ensure_uuid_str(value)

    @field_validator("uri", "display_name")
    @classmethod
    def _ensure_non_empty(cls, value: str, info: ValidationInfo) -> str:
        return ensure_non_empty_text(value, info.field_name or "value")

    @field_validator("content_hash", mode="before")
    @classmethod
    def _validate_content_hash(cls, value: Any) -> str:
        return ensure_hex_digest(value)

    @field_validator("metadata", mode="before")
    @classmethod
    def _normalize_metadata(cls, value: Any) -> dict[str, Any]:
        return ensure_metadata_dict(value)

    @field_validator("ingested_at", mode="before")
    @classmethod
    def _validate_ingested_at(cls, value: Any) -> datetime:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime):
            raise TypeError("ingested_at must be a datetime")
        return ensure_timezone_aware(value)


__all__ = ["Document"]
