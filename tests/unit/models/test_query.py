from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from txtsearch.models.enums import SearchStrategy, SourceType
from txtsearch.models.query import Query, QueryFilters


def test_query_defaults_and_id_generation() -> None:
    query = Query(text="find me", strategy=SearchStrategy.SEMANTIC)

    assert query.schema_version == Query.SCHEMA_VERSION
    UUID(query.query_id)  # raises if not valid
    assert query.top_k == 10
    assert query.filters == QueryFilters()


def test_query_filters_validate_inputs() -> None:
    doc_id = str(uuid4())
    filters = QueryFilters(
        document_ids=[doc_id],
        source_types={SourceType.FILE},
        extra_eq={"language": "en"},
        ingested_after=datetime.now(timezone.utc),
    )
    query = Query(
        text="find me",
        strategy=SearchStrategy.LEXICAL,
        top_k=5,
        filters=filters,
        include_snippets=False,
        include_highlights=True,
    )

    assert query.top_k == 5
    assert query.filters.has_filters()
    assert query.include_snippets is False
    assert query.include_highlights is True


def test_query_filters_reject_invalid_uuid() -> None:
    with pytest.raises(ValidationError):
        QueryFilters(document_ids=["not-a-uuid"])


def test_query_filters_require_timezone_aware_datetime() -> None:
    with pytest.raises(ValidationError):
        QueryFilters(ingested_after=datetime.now())
