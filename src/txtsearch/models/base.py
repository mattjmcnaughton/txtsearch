from datetime import datetime
from typing import Any, ClassVar, Mapping, Type, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

T_Model = TypeVar("T_Model", bound="RecordModel")


class SchemaVersioned(BaseModel):
    """Base class enforcing schema_version defaults and immutability."""

    SCHEMA_VERSION: ClassVar[str]
    schema_version: str

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @model_validator(mode="before")
    @classmethod
    def _apply_default_schema_version(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            if "schema_version" not in data:
                data = dict(data)
                data["schema_version"] = cls.SCHEMA_VERSION
        return data

    @model_validator(mode="after")
    def _validate_schema_version(self) -> "SchemaVersioned":
        if self.schema_version != self.SCHEMA_VERSION:
            raise ValueError(f"expected schema_version '{self.SCHEMA_VERSION}'")
        return self


class RecordModel(SchemaVersioned):
    """Adds serialization helpers for storage adapters."""

    def to_record(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    @classmethod
    def from_record(cls: Type[T_Model], data: Mapping[str, Any] | BaseModel) -> T_Model:
        return cls.model_validate(data)


def ensure_uuid_str(value: Any) -> str:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, str):
        value = value.strip()
        return str(UUID(value))
    raise TypeError("expected UUID or string for identifier field")


def ensure_hex_digest(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("expected string hex digest")
    digest = value.strip().lower()
    if not digest:
        raise ValueError("hex digest cannot be empty")
    if len(digest) % 2 != 0:
        raise ValueError("hex digest length must be even")
    if any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("hex digest must contain only hexadecimal characters")
    return digest


def ensure_timezone_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise ValueError("datetime must be timezone-aware")
    return dt


def ensure_non_empty_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value.strip():
        raise ValueError(f"{field_name} cannot be empty")
    return value


def ensure_metadata_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    raise TypeError("metadata must be a dictionary")
