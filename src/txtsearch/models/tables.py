"""SQLModel table definitions for database persistence.

This module defines SQLModel table classes that map domain models to SQLite tables.
These are kept separate from the Pydantic domain models in document.py and chunk.py
for the following reasons:

1. **Separation of concerns**: Domain models (Document, DocumentChunk) represent
   business entities with validation rules and behavior. Table models represent
   database schema and persistence concerns. Keeping them separate allows each
   to evolve independently.

2. **Purity of domain models**: The domain models use frozen Pydantic with
   extra="forbid" for immutability and strict validation. SQLModel requires
   mutability for ORM operations (session.add, updates). Mixing these would
   compromise the domain model's guarantees.

3. **Flexibility**: Different storage backends might need different table
   structures. By isolating table definitions, we can add alternative backends
   (e.g., PostgreSQL with different column types) without touching domain models.

4. **Testing**: Domain models can be tested without any database dependencies.
   Table models are tested as part of the MetadataStore service tests.

Field names are aligned with domain models to enable conversion via Pydantic's
.model_dump() and .model_validate(). The source_type field stores the enum
value as a string and requires explicit conversion.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON
from sqlmodel import Field, SQLModel


class DocumentRecord(SQLModel, table=True):
    """SQLModel table for document metadata persistence.

    Maps to the Document domain model. Field names match the domain model
    to simplify conversion via Pydantic serialization.
    """

    __tablename__ = "documents"

    document_id: str = Field(primary_key=True)
    schema_version: str
    uri: str = Field(index=True, unique=True)
    display_name: str
    content_hash: str
    size_bytes: int
    source_type: str
    extra: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    ingested_at: datetime


class ChunkRecord(SQLModel, table=True):
    """SQLModel table for document chunk persistence.

    Maps to the DocumentChunk domain model. Includes a foreign key to the
    parent document for referential integrity.
    """

    __tablename__ = "chunks"

    chunk_id: str = Field(primary_key=True)
    schema_version: str
    document_id: str = Field(index=True, foreign_key="documents.document_id")
    chunk_index: int
    text: str
    content_hash: str
    char_start: int
    char_end: int
    line_start: int
    line_end: int
    token_count: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
