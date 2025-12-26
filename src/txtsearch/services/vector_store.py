"""Vector store service for persisting embeddings to ChromaDB.

ChromaDB's Python client is synchronous, so we use asyncio.to_thread()
to wrap blocking operations and maintain async consistency with other services.
"""

import asyncio

import chromadb
import structlog


class VectorStore:
    """Stores and retrieves vector embeddings via ChromaDB.

    Wraps ChromaDB operations with async interface using asyncio.to_thread().
    Accepts a ChromaDB Client via dependency injection to support both
    persistent (PersistentClient) and ephemeral (EphemeralClient) modes.
    """

    DEFAULT_COLLECTION_NAME = "chunks"

    def __init__(
        self,
        client: chromadb.ClientAPI,
        collection_name: str | None = None,
        logger: structlog.stdlib.BoundLogger | None = None,
    ) -> None:
        self._client = client
        self._collection_name = collection_name or self.DEFAULT_COLLECTION_NAME
        self._logger = logger or structlog.get_logger(__name__)
        self._collection: chromadb.Collection | None = None

    async def initialize(self) -> None:
        """Initialize the collection, creating it if it doesn't exist."""
        self._collection = await asyncio.to_thread(
            self._client.get_or_create_collection,
            name=self._collection_name,
        )
        self._logger.info(
            "vector_store_initialized",
            collection_name=self._collection_name,
        )

    async def add_embeddings(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, str | int | float | bool]] | None = None,
    ) -> None:
        """Add embeddings to the collection.

        Args:
            ids: Unique identifiers for each embedding (typically chunk_id).
            embeddings: Vector embeddings as lists of floats.
            documents: Text content for each embedding (chunk text).
            metadatas: Optional metadata dicts for each embedding.

        Raises:
            ValueError: If input lists have mismatched lengths.
            RuntimeError: If collection not initialized.
        """
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")

        if not ids:
            return

        if not (len(ids) == len(embeddings) == len(documents)):
            raise ValueError(
                f"Mismatched lengths: ids={len(ids)}, embeddings={len(embeddings)}, documents={len(documents)}"
            )
        if metadatas is not None and len(metadatas) != len(ids):
            raise ValueError(f"Mismatched lengths: ids={len(ids)}, metadatas={len(metadatas)}")

        await asyncio.to_thread(
            self._collection.upsert,
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )
        self._logger.debug(
            "embeddings_added",
            collection=self._collection_name,
            count=len(ids),
        )

    async def delete_by_ids(self, ids: list[str]) -> None:
        """Delete embeddings by their IDs.

        Args:
            ids: List of embedding IDs to delete.

        Raises:
            RuntimeError: If collection not initialized.
        """
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")

        if not ids:
            return

        await asyncio.to_thread(self._collection.delete, ids=ids)
        self._logger.debug(
            "embeddings_deleted",
            collection=self._collection_name,
            count=len(ids),
        )

    async def clear_collection(self) -> None:
        """Delete and recreate the collection, removing all embeddings.

        Raises:
            RuntimeError: If collection not initialized.
        """
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")

        await asyncio.to_thread(self._client.delete_collection, self._collection_name)
        self._collection = await asyncio.to_thread(
            self._client.get_or_create_collection,
            name=self._collection_name,
        )
        self._logger.info(
            "collection_cleared",
            collection=self._collection_name,
        )

    async def count(self) -> int:
        """Return the number of embeddings in the collection.

        Returns:
            Number of stored embeddings.

        Raises:
            RuntimeError: If collection not initialized.
        """
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")

        return await asyncio.to_thread(self._collection.count)

    async def get_by_ids(self, ids: list[str]) -> dict[str, list[str] | list[list[float]] | list[dict]]:
        """Retrieve embeddings by their IDs.

        Args:
            ids: List of embedding IDs to retrieve.

        Returns:
            Dict with 'ids', 'embeddings', 'documents', and 'metadatas' keys.

        Raises:
            RuntimeError: If collection not initialized.
        """
        if self._collection is None:
            raise RuntimeError("VectorStore not initialized. Call initialize() first.")

        if not ids:
            return {"ids": [], "embeddings": [], "documents": [], "metadatas": []}

        result = await asyncio.to_thread(
            self._collection.get,
            ids=ids,
            include=["embeddings", "documents", "metadatas"],
        )
        return result
