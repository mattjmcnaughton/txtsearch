from uuid import uuid4

import pytest
from pydantic import ValidationError

from txtsearch.models.chunk import DocumentChunk


def _make_hash() -> str:
    return "fedcba9876543210" * 4


def _make_document_id() -> str:
    return str(uuid4())


def test_chunk_basic_validation() -> None:
    chunk = DocumentChunk(
        chunk_id=str(uuid4()),
        document_id=_make_document_id(),
        chunk_index=0,
        text="Example text.",
        content_hash=_make_hash(),
        char_start=0,
        char_end=12,
        line_start=1,
        line_end=1,
        token_count=3,
    )

    assert chunk.schema_version == DocumentChunk.SCHEMA_VERSION
    assert chunk.extra == {}
    assert chunk.char_end >= chunk.char_start


def test_chunk_rejects_negative_index() -> None:
    with pytest.raises(ValidationError):
        DocumentChunk(
            chunk_id=str(uuid4()),
            document_id=_make_document_id(),
            chunk_index=-1,
            text="bad chunk",
            content_hash=_make_hash(),
            char_start=0,
            char_end=1,
            line_start=1,
            line_end=1,
        )


def test_chunk_requires_monotonic_offsets() -> None:
    with pytest.raises(ValidationError):
        DocumentChunk(
            chunk_id=str(uuid4()),
            document_id=_make_document_id(),
            chunk_index=0,
            text="bad chunk",
            content_hash=_make_hash(),
            char_start=10,
            char_end=9,
            line_start=2,
            line_end=1,
        )


def test_chunk_rejects_negative_token_count() -> None:
    with pytest.raises(ValidationError):
        DocumentChunk(
            chunk_id=str(uuid4()),
            document_id=_make_document_id(),
            chunk_index=0,
            text="bad chunk",
            content_hash=_make_hash(),
            char_start=0,
            char_end=1,
            line_start=1,
            line_end=1,
            token_count=-5,
        )


def test_chunk_record_round_trip() -> None:
    chunk = DocumentChunk(
        chunk_id=str(uuid4()),
        document_id=_make_document_id(),
        chunk_index=1,
        text="Another chunk.",
        content_hash=_make_hash(),
        char_start=13,
        char_end=27,
        line_start=2,
        line_end=3,
        extra={"section": "intro"},
    )

    restored = DocumentChunk.from_record(chunk.to_record())
    assert restored == chunk
