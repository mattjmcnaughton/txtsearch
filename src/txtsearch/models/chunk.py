from typing import Any, ClassVar

from pydantic import Field, ValidationInfo, field_validator, model_validator

from txtsearch.models.base import (
    RecordModel,
    ensure_hex_digest,
    ensure_metadata_dict,
    ensure_non_empty_text,
    ensure_uuid_str,
)


class DocumentChunk(RecordModel):
    SCHEMA_VERSION: ClassVar[str] = "document_chunk.v1"

    schema_version: str = Field(default=SCHEMA_VERSION)
    chunk_id: str
    document_id: str
    chunk_index: int = Field(ge=0)
    text: str
    content_hash: str
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    token_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("chunk_id", "document_id", mode="before")
    @classmethod
    def _normalize_ids(cls, value: Any) -> str:
        return ensure_uuid_str(value)

    @field_validator("text")
    @classmethod
    def _ensure_text(cls, value: str, info: ValidationInfo) -> str:
        return ensure_non_empty_text(value, info.field_name or "text")

    @field_validator("content_hash", mode="before")
    @classmethod
    def _validate_hash(cls, value: Any) -> str:
        return ensure_hex_digest(value)

    @field_validator("metadata", mode="before")
    @classmethod
    def _normalize_metadata(cls, value: Any) -> dict[str, Any]:
        return ensure_metadata_dict(value)

    @model_validator(mode="after")
    def _validate_offsets(self) -> "DocumentChunk":
        if self.char_end < self.char_start:
            raise ValueError("char_end must be greater than or equal to char_start")
        if self.line_end < self.line_start:
            raise ValueError("line_end must be greater than or equal to line_start")
        return self


__all__ = ["DocumentChunk"]
