"""Unit tests for the IndexingService."""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import chromadb
from chromadb.api.types import EmbeddingFunction, Documents, Embeddings
import pytest

from txtsearch.models.chunk import DocumentChunk
from txtsearch.models.document import Document
from txtsearch.models.enums import SourceType
from txtsearch.services.chunker import Chunker
from txtsearch.services.file_walker import FileWalker
from txtsearch.services.index import IndexingResult, IndexingService, FileError
from txtsearch.services.metadata_store import MetadataStore, create_async_engine_from_path
from txtsearch.services.vector_store import VectorStore


class FakeEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic embedding function for testing."""

    def __init__(self, dim: int = 384) -> None:
        self.dim = dim

    def __call__(self, input: Documents) -> Embeddings:
        embeddings: Embeddings = []
        for doc in input:
            seed = len(doc) * 0.001
            embedding = [seed + (i * 0.0001) for i in range(self.dim)]
            embeddings.append(embedding)
        return embeddings


class FakeFileWalker:
    """Fake FileWalker that yields predefined paths."""

    def __init__(self, files: list[Path] | None = None) -> None:
        self._files = files or []

    async def walk(self, directory: Path) -> AsyncIterator[Path]:
        for file_path in self._files:
            yield file_path


class FakeMetadataStore:
    """In-memory fake MetadataStore for testing."""

    def __init__(self) -> None:
        self.documents: dict[str, Document] = {}
        self.chunks: dict[str, list[DocumentChunk]] = {}
        self.initialized = False

    async def initialize_schema(self) -> None:
        self.initialized = True

    async def save_document(self, document: Document) -> None:
        self.documents[document.document_id] = document

    async def save_chunks(self, chunks: list[DocumentChunk]) -> None:
        if not chunks:
            return
        document_id = chunks[0].document_id
        self.chunks[document_id] = chunks


class FakeVectorStore:
    """In-memory fake VectorStore for testing."""

    def __init__(self) -> None:
        self.documents: dict[str, str] = {}
        self.metadatas: dict[str, dict] = {}
        self.initialized = False

    async def initialize(self) -> None:
        self.initialized = True

    async def add_documents(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict] | None = None,
    ) -> None:
        for i, doc_id in enumerate(ids):
            self.documents[doc_id] = documents[i]
            if metadatas:
                self.metadatas[doc_id] = metadatas[i]


@pytest.fixture
def tmp_files(tmp_path: Path) -> dict[str, Path]:
    """Create temporary test files with known content."""
    files = {}

    file1 = tmp_path / "file1.txt"
    file1.write_text("Hello, this is the content of file one.")
    files["file1"] = file1

    file2 = tmp_path / "file2.txt"
    file2.write_text("File two has different content for testing.")
    files["file2"] = file2

    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")
    files["empty"] = empty_file

    whitespace_file = tmp_path / "whitespace.txt"
    whitespace_file.write_text("   \n\n   ")
    files["whitespace"] = whitespace_file

    large_file = tmp_path / "large.txt"
    large_file.write_text("word " * 200)  # 1000 characters
    files["large"] = large_file

    return files


@pytest.fixture
def fake_file_walker() -> FakeFileWalker:
    """Create a fake file walker with no files."""
    return FakeFileWalker()


@pytest.fixture
def fake_metadata_store() -> FakeMetadataStore:
    """Create a fake metadata store."""
    return FakeMetadataStore()


@pytest.fixture
def fake_vector_store() -> FakeVectorStore:
    """Create a fake vector store."""
    return FakeVectorStore()


@pytest.fixture
def chunker() -> Chunker:
    """Create a real chunker with small chunk size for testing."""
    return Chunker(chunk_size=100, chunk_overlap=10)


@pytest.fixture
def indexing_service(
    fake_file_walker: FakeFileWalker,
    fake_metadata_store: FakeMetadataStore,
    fake_vector_store: FakeVectorStore,
    chunker: Chunker,
) -> IndexingService:
    """Create an IndexingService with fake dependencies."""
    return IndexingService(
        file_walker=fake_file_walker,
        metadata_store=fake_metadata_store,
        vector_store=fake_vector_store,
        chunker=chunker,
    )


class TestIndexingResult:
    """Tests for the IndexingResult model."""

    def test_default_values(self) -> None:
        result = IndexingResult(
            files_processed=0,
            files_skipped=0,
            chunks_created=0,
        )
        assert result.files_processed == 0
        assert result.files_skipped == 0
        assert result.chunks_created == 0
        assert result.errors == []

    def test_with_values(self) -> None:
        result = IndexingResult(
            files_processed=10,
            files_skipped=2,
            chunks_created=50,
            errors=["error1", "error2"],
        )
        assert result.files_processed == 10
        assert result.files_skipped == 2
        assert result.chunks_created == 50
        assert result.errors == ["error1", "error2"]

    def test_immutable(self) -> None:
        result = IndexingResult(
            files_processed=1,
            files_skipped=0,
            chunks_created=5,
        )
        with pytest.raises(Exception):  # Pydantic raises ValidationError for frozen models
            result.files_processed = 2


class TestFileError:
    """Tests for the FileError model."""

    def test_creation(self) -> None:
        error = FileError(path="/path/to/file.txt", error="Permission denied")
        assert error.path == "/path/to/file.txt"
        assert error.error == "Permission denied"


class TestIndexingServiceInitialization:
    """Tests for IndexingService initialization."""

    def test_accepts_all_dependencies(
        self,
        fake_file_walker: FakeFileWalker,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
    ) -> None:
        service = IndexingService(
            file_walker=fake_file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )
        assert service._file_walker is fake_file_walker
        assert service._metadata_store is fake_metadata_store
        assert service._vector_store is fake_vector_store
        assert service._chunker is chunker


class TestIndexingServiceEmptyDirectory:
    """Tests for indexing empty directories."""

    async def test_empty_directory_returns_zero_counts(
        self,
        indexing_service: IndexingService,
        tmp_path: Path,
    ) -> None:
        result = await indexing_service.index_directory(tmp_path)

        assert result.files_processed == 0
        assert result.files_skipped == 0
        assert result.chunks_created == 0
        assert result.errors == []

    async def test_initializes_stores_even_for_empty_directory(
        self,
        indexing_service: IndexingService,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        tmp_path: Path,
    ) -> None:
        await indexing_service.index_directory(tmp_path)

        assert fake_metadata_store.initialized
        assert fake_vector_store.initialized


class TestIndexingServiceHappyPath:
    """Tests for successful indexing scenarios."""

    async def test_indexes_single_file(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["file1"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 1
        assert result.chunks_created >= 1
        assert len(fake_metadata_store.documents) == 1
        assert len(fake_vector_store.documents) >= 1

    async def test_indexes_multiple_files(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["file1"], tmp_files["file2"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 2
        assert len(fake_metadata_store.documents) == 2

    async def test_creates_chunks_for_large_file(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["large"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 1
        assert result.chunks_created > 1

    async def test_stores_chunk_metadata_in_vector_store(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["file1"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        await service.index_directory(tmp_path)

        # Check that metadata was stored
        for chunk_id, metadata in fake_vector_store.metadatas.items():
            assert "document_id" in metadata
            assert "chunk_index" in metadata
            assert "char_start" in metadata
            assert "char_end" in metadata


class TestIndexingServiceSkipsEmptyFiles:
    """Tests for skipping empty or whitespace-only files."""

    async def test_skips_empty_file(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["empty"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 0
        assert result.files_skipped == 1
        assert len(fake_metadata_store.documents) == 0

    async def test_skips_whitespace_only_file(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["whitespace"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 0
        assert result.files_skipped == 1


class TestIndexingServiceErrorHandling:
    """Tests for error handling during indexing."""

    async def test_handles_file_read_error(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_path: Path,
    ) -> None:
        # Create a file path that doesn't exist
        nonexistent_file = tmp_path / "nonexistent.txt"
        file_walker = FakeFileWalker([nonexistent_file])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 0
        assert len(result.errors) == 1
        assert "nonexistent.txt" in result.errors[0]

    async def test_continues_after_file_error(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        nonexistent_file = tmp_path / "nonexistent.txt"
        file_walker = FakeFileWalker(
            [
                nonexistent_file,
                tmp_files["file1"],
            ]
        )
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 1
        assert len(result.errors) == 1

    async def test_handles_unicode_decode_error(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_path: Path,
    ) -> None:
        binary_file = tmp_path / "binary.txt"
        binary_file.write_bytes(b"\x80\x81\x82\x83")
        file_walker = FakeFileWalker([binary_file])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        assert result.files_processed == 0
        assert len(result.errors) == 1


class TestIndexingServiceWithRealDependencies:
    """Integration-style tests with real (in-memory) dependencies."""

    async def test_end_to_end_with_real_stores(
        self,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        # Use real dependencies but with in-memory/ephemeral backends
        file_walker = FileWalker(include_patterns=["*.txt"])
        engine = create_async_engine_from_path(":memory:")
        metadata_store = MetadataStore(engine=engine)
        chroma_client = chromadb.EphemeralClient()
        vector_store = VectorStore(
            client=chroma_client,
            collection_name=f"test_{uuid4().hex[:8]}",
            embedding_function=FakeEmbeddingFunction(),
        )
        chunker = Chunker(chunk_size=100, chunk_overlap=10)

        service = IndexingService(
            file_walker=file_walker,
            metadata_store=metadata_store,
            vector_store=vector_store,
            chunker=chunker,
        )

        result = await service.index_directory(tmp_path)

        # Should process all non-empty text files
        assert result.files_processed >= 2
        assert result.chunks_created >= 2
        assert result.errors == []

        # Verify data was persisted
        vector_count = await vector_store.count()
        assert vector_count == result.chunks_created


class TestIndexingServiceDocumentCreation:
    """Tests for document model creation."""

    async def test_creates_document_with_correct_fields(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["file1"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        await service.index_directory(tmp_path)

        assert len(fake_metadata_store.documents) == 1
        document = list(fake_metadata_store.documents.values())[0]

        assert document.uri == tmp_files["file1"].as_uri()
        assert document.display_name == "file1.txt"
        assert document.source_type == SourceType.FILE
        assert document.size_bytes > 0
        assert len(document.content_hash) == 64  # SHA-256 hex digest
        assert document.ingested_at <= datetime.now(timezone.utc)

    async def test_creates_chunks_with_correct_document_id(
        self,
        fake_metadata_store: FakeMetadataStore,
        fake_vector_store: FakeVectorStore,
        chunker: Chunker,
        tmp_files: dict[str, Path],
        tmp_path: Path,
    ) -> None:
        file_walker = FakeFileWalker([tmp_files["file1"]])
        service = IndexingService(
            file_walker=file_walker,
            metadata_store=fake_metadata_store,
            vector_store=fake_vector_store,
            chunker=chunker,
        )

        await service.index_directory(tmp_path)

        document = list(fake_metadata_store.documents.values())[0]
        chunks = list(fake_metadata_store.chunks.values())[0]

        for chunk in chunks:
            assert chunk.document_id == document.document_id
