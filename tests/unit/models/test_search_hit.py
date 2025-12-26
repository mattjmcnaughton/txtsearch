from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from txtsearch.models.enums import SearchStrategy
from txtsearch.models.hit import Highlight, SearchHit


def _uuid_str() -> str:
    return str(uuid4())


def test_search_hit_valid_payload() -> None:
    highlight = Highlight(char_start=0, char_end=10, line_start=1, line_end=1, label="match")
    hit = SearchHit(
        hit_id=_uuid_str(),
        query_id=_uuid_str(),
        document_id=_uuid_str(),
        chunk_id=_uuid_str(),
        rank=0,
        score=0.55,
        strategy=SearchStrategy.SEMANTIC,
        snippet="example snippet",
        highlights=[highlight],
        extra={"distance": 0.45},
    )

    UUID(hit.hit_id)
    assert hit.schema_version == SearchHit.SCHEMA_VERSION
    assert hit.highlights == [highlight]


def test_search_hit_rejects_score_outside_range() -> None:
    with pytest.raises(ValidationError):
        SearchHit(
            hit_id=_uuid_str(),
            query_id=_uuid_str(),
            document_id=_uuid_str(),
            rank=0,
            score=1.5,
            strategy=SearchStrategy.SEMANTIC,
        )


def test_highlight_requires_monotonic_char_range() -> None:
    with pytest.raises(ValidationError):
        Highlight(char_start=5, char_end=4)


def test_search_hit_round_trip() -> None:
    hit = SearchHit(
        hit_id=_uuid_str(),
        query_id=_uuid_str(),
        document_id=_uuid_str(),
        rank=1,
        score=0.9,
        strategy=SearchStrategy.LEXICAL,
        extra={"score_raw": 42.0},
    )

    restored = SearchHit.from_record(hit.to_record())
    assert restored == hit
