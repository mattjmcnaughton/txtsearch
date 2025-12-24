from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from txtsearch.models.document import Document
from txtsearch.models.enums import SourceType


def _make_hash() -> str:
    return "0123456789abcdef" * 4


def test_document_has_expected_defaults() -> None:
    document = Document(
        document_id=str(uuid4()),
        uri="file:///tmp/example.txt",
        display_name="example.txt",
        content_hash=_make_hash(),
        size_bytes=1024,
        source_type=SourceType.FILE,
        ingested_at=datetime.now(timezone.utc),
    )

    assert document.schema_version == Document.SCHEMA_VERSION
    assert document.metadata == {}
    assert document.to_record()["schema_version"] == Document.SCHEMA_VERSION


def test_document_requires_timezone_aware_ingested_at() -> None:
    with pytest.raises(ValidationError):
        Document(
            document_id=str(uuid4()),
            uri="file:///tmp/example.txt",
            display_name="example.txt",
            content_hash=_make_hash(),
            size_bytes=1,
            source_type=SourceType.FILE,
            ingested_at=datetime.now(),
        )


def test_document_rejects_invalid_hash() -> None:
    with pytest.raises(ValidationError):
        Document(
            document_id=str(uuid4()),
            uri="file:///tmp/example.txt",
            display_name="example.txt",
            content_hash="xyz",
            size_bytes=1,
            source_type=SourceType.FILE,
            ingested_at=datetime.now(timezone.utc),
        )


def test_document_record_round_trip() -> None:
    document = Document(
        document_id=str(uuid4()),
        uri="file:///tmp/example.txt",
        display_name="example.txt",
        content_hash=_make_hash(),
        size_bytes=1,
        source_type=SourceType.FILE,
        ingested_at=datetime.now(timezone.utc),
        metadata={"language": "en"},
    )

    restored = Document.from_record(document.to_record())
    assert restored == document
