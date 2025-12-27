"""Tests for the service factory module."""

from pathlib import Path


from txtsearch.services.chunker import Chunker
from txtsearch.services.factory import (
    create_indexing_service,
    create_test_indexing_service,
    parse_file_pattern,
)
from txtsearch.services.file_walker import FileWalker
from txtsearch.services.index import IndexingService
from txtsearch.services.metadata_store import MetadataStore
from txtsearch.services.vector_store import VectorStore


class TestCreateIndexingService:
    """Tests for create_indexing_service factory."""

    def test_creates_indexing_service_instance(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"

        service = create_indexing_service(output_dir=output_dir)

        assert isinstance(service, IndexingService)

    def test_creates_output_directory(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "nested" / "index"
        assert not output_dir.exists()

        create_indexing_service(output_dir=output_dir)

        assert output_dir.exists()

    def test_creates_metadata_db_location(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"

        service = create_indexing_service(output_dir=output_dir)

        # The MetadataStore is configured but DB file created on first write
        assert isinstance(service._metadata_store, MetadataStore)

    def test_creates_vector_store_location(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"

        service = create_indexing_service(output_dir=output_dir)

        # ChromaDB creates the directory on client creation
        assert isinstance(service._vector_store, VectorStore)
        assert (output_dir / "semantic").exists()

    def test_respects_include_patterns(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"
        patterns = ["*.py", "*.txt"]

        service = create_indexing_service(
            output_dir=output_dir,
            include_patterns=patterns,
        )

        assert service._file_walker._include_patterns == patterns

    def test_respects_exclude_patterns(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"
        patterns = ["*_test.py", "*.bak"]

        service = create_indexing_service(
            output_dir=output_dir,
            exclude_patterns=patterns,
        )

        assert service._file_walker._exclude_patterns == patterns

    def test_respects_chunk_size(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"

        service = create_indexing_service(
            output_dir=output_dir,
            chunk_size=1024,
        )

        assert service._chunker._chunk_size == 1024

    def test_respects_chunk_overlap(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"

        service = create_indexing_service(
            output_dir=output_dir,
            chunk_overlap=100,
        )

        assert service._chunker._chunk_overlap == 100

    def test_respects_collection_name(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"

        service = create_indexing_service(
            output_dir=output_dir,
            collection_name="custom_collection",
        )

        assert service._vector_store._collection_name == "custom_collection"

    def test_uses_default_collection_name(self, tmp_path: Path) -> None:
        output_dir = tmp_path / "index"

        service = create_indexing_service(output_dir=output_dir)

        assert service._vector_store._collection_name == "chunks"


class TestCreateTestIndexingService:
    """Tests for create_test_indexing_service factory."""

    def test_creates_indexing_service_instance(self) -> None:
        service = create_test_indexing_service()

        assert isinstance(service, IndexingService)

    def test_wires_all_dependencies(self) -> None:
        service = create_test_indexing_service()

        assert isinstance(service._file_walker, FileWalker)
        assert isinstance(service._metadata_store, MetadataStore)
        assert isinstance(service._vector_store, VectorStore)
        assert isinstance(service._chunker, Chunker)

    def test_respects_include_patterns(self) -> None:
        patterns = ["*.py", "*.txt"]

        service = create_test_indexing_service(include_patterns=patterns)

        assert service._file_walker._include_patterns == patterns

    def test_respects_exclude_patterns(self) -> None:
        patterns = ["*_test.py"]

        service = create_test_indexing_service(exclude_patterns=patterns)

        assert service._file_walker._exclude_patterns == patterns

    def test_respects_chunk_size(self) -> None:
        service = create_test_indexing_service(chunk_size=256)

        assert service._chunker._chunk_size == 256

    def test_respects_chunk_overlap(self) -> None:
        service = create_test_indexing_service(chunk_overlap=25)

        assert service._chunker._chunk_overlap == 25

    def test_generates_unique_collection_name_by_default(self) -> None:
        service1 = create_test_indexing_service()
        service2 = create_test_indexing_service()

        assert service1._vector_store._collection_name != service2._vector_store._collection_name

    def test_respects_explicit_collection_name(self) -> None:
        service = create_test_indexing_service(collection_name="my_test_collection")

        assert service._vector_store._collection_name == "my_test_collection"

    async def test_can_index_files(self, tmp_path: Path) -> None:
        # Create a simple file to index
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, world! This is test content for indexing.")

        service = create_test_indexing_service(include_patterns=["*.txt"])
        result = await service.index_directory(tmp_path)

        assert result.files_processed == 1
        assert result.chunks_created >= 1


class TestParseFilePattern:
    """Tests for parse_file_pattern helper."""

    def test_simple_pattern_without_braces(self) -> None:
        result = parse_file_pattern("*.py")

        assert result == ["*.py"]

    def test_expands_brace_pattern(self) -> None:
        result = parse_file_pattern("*.{py,js,ts}")

        assert result == ["*.py", "*.js", "*.ts"]

    def test_expands_single_alternative(self) -> None:
        result = parse_file_pattern("*.{py}")

        assert result == ["*.py"]

    def test_expands_with_prefix_and_suffix(self) -> None:
        result = parse_file_pattern("src/*.{py,txt}.bak")

        assert result == ["src/*.py.bak", "src/*.txt.bak"]

    def test_handles_spaces_in_alternatives(self) -> None:
        result = parse_file_pattern("*.{py, js, ts}")

        assert result == ["*.py", "*.js", "*.ts"]

    def test_empty_braces(self) -> None:
        result = parse_file_pattern("*.{}")

        assert result == ["*."]

    def test_only_opening_brace(self) -> None:
        result = parse_file_pattern("*.{py")

        assert result == ["*.{py"]

    def test_only_closing_brace(self) -> None:
        result = parse_file_pattern("*.py}")

        assert result == ["*.py}"]

    def test_complex_pattern(self) -> None:
        result = parse_file_pattern("**/*.{py,js,ts,md,txt,json,yaml,yml}")

        expected = [
            "**/*.py",
            "**/*.js",
            "**/*.ts",
            "**/*.md",
            "**/*.txt",
            "**/*.json",
            "**/*.yaml",
            "**/*.yml",
        ]
        assert result == expected
