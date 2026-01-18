"""Store children and parents in ChromaDB, BM25, and Redis."""

import json
import logging
from dataclasses import asdict
from typing import Optional

from app.core.exceptions import IndexingError
from .infrastructure import IndexingInfrastructure
from .llm_enricher import EnrichedChild
from .parent_grouper import Parent, ContentIndex

logger = logging.getLogger(__name__)

PARENT_KEY_PREFIX = "parent:"
REF_KEY_PREFIX = "ref:"


class StorageLayer:
    """
    Manage storage of children and parents across ChromaDB, BM25, and Redis.

    Children are stored in:
    - ChromaDB: enriched_text embedded for vector search
    - BM25 index: original text tokenized for keyword search

    Parents are stored in:
    - Redis: full JSON for context retrieval

    Reference index in:
    - Redis: section -> child_id mapping

    Note: store_children() rebuilds the BM25 index from scratch. For multi-source
    ingestion, call rebuild_bm25_index() after all sources are stored.
    """

    def __init__(self, infrastructure: IndexingInfrastructure):
        self.infra = infrastructure
        self._collection = None
        self._collection_name = None

    async def initialize(self, collection_name: Optional[str] = None) -> None:
        """Initialize storage with specified collection."""
        from app.config import get_settings
        settings = get_settings()

        self._collection_name = collection_name or settings.chroma_collection
        self._collection = self.infra.get_or_create_collection(self._collection_name)
        logger.info(f"Storage initialized with collection: {self._collection_name}")

    @property
    def collection(self):
        if self._collection is None:
            raise IndexingError("Storage not initialized. Call initialize() first.")
        return self._collection

    async def store_children(
        self,
        children: list[EnrichedChild],
        rebuild_bm25: bool = True,
    ) -> int:
        """
        Store children in ChromaDB and optionally rebuild BM25 index.

        Args:
            children: List of EnrichedChild from parent grouper
            rebuild_bm25: If True, rebuild BM25 from all stored children.
                          Set False when batch-ingesting multiple sources,
                          then call rebuild_bm25_index() once at the end.

        Returns:
            Number of children stored
        """
        if not children:
            return 0

        ids = []
        documents = []
        metadatas = []

        for child in children:
            ids.append(child.id)
            documents.append(child.enriched_text)

            metadata = {
                "parent_id": child.parent_id or "",
                "page": child.page,
                "section": child.section or "",
                "xrefs": json.dumps(child.xrefs),
                "tags": json.dumps(child.tags),
                "uses_definitions": json.dumps(child.uses_definitions),
                "diagram_context": child.diagram_context,
                "table_context": child.table_context,
                "has_diagram": len(child.diagrams) > 0,
                "has_table": len(child.tables) > 0,
                "original_text": child.text,
            }
            metadatas.append(metadata)

        try:
            self.collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )
            logger.info(f"Stored {len(ids)} children in ChromaDB")

        except Exception as e:
            logger.error(f"Failed to store children in ChromaDB: {e}")
            raise IndexingError(f"ChromaDB storage failed: {e}")

        if rebuild_bm25:
            await self.rebuild_bm25_index()

        return len(children)

    async def rebuild_bm25_index(self) -> int:
        """
        Rebuild BM25 index from all children in ChromaDB.

        This scans the entire collection and rebuilds the index.
        Call this after multi-source ingestion or to repair the index.

        Returns:
            Number of documents indexed
        """
        try:
            all_docs = self.collection.get(include=["metadatas"])

            if not all_docs["ids"]:
                await self.infra.clear_bm25_index()
                logger.info("BM25 index cleared (no documents)")
                return 0

            bm25_corpus = []
            bm25_ids = []

            for i, child_id in enumerate(all_docs["ids"]):
                metadata = all_docs["metadatas"][i] if all_docs["metadatas"] else {}
                text = metadata.get("original_text", "")

                tokens = text.lower().split()
                bm25_corpus.append(tokens)
                bm25_ids.append(child_id)

            await self.infra.save_bm25_index(bm25_corpus, bm25_ids)
            logger.info(f"Rebuilt BM25 index with {len(bm25_ids)} documents")
            return len(bm25_ids)

        except Exception as e:
            logger.error(f"Failed to rebuild BM25 index: {e}")
            raise IndexingError(f"BM25 index rebuild failed: {e}")

    async def store_parents(self, parents: list[Parent]) -> int:
        """
        Store parents in Redis.

        Args:
            parents: List of Parent from parent grouper

        Returns:
            Number of parents stored
        """
        if not parents:
            return 0

        redis = self.infra.redis_client
        pipe = redis.pipeline()

        for parent in parents:
            key = f"{PARENT_KEY_PREFIX}{parent.id}"

            content_index_dict = asdict(parent.content_index)

            value = {
                "id": parent.id,
                "text": parent.text,
                "token_count": parent.token_count,
                "children_ids": parent.children_ids,
                "page_start": parent.page_start,
                "page_end": parent.page_end,
                "source": parent.source,
                "content_index": content_index_dict,
            }

            pipe.set(key, json.dumps(value))

        try:
            await pipe.execute()
            logger.info(f"Stored {len(parents)} parents in Redis")
            return len(parents)
        except Exception as e:
            logger.error(f"Failed to store parents in Redis: {e}")
            raise IndexingError(f"Redis parent storage failed: {e}")

    async def build_reference_index(self, children: list[EnrichedChild]) -> int:
        """
        Build section reference index in Redis.

        Maps section IDs to child IDs for cross-reference resolution.

        Args:
            children: List of EnrichedChild

        Returns:
            Number of references indexed
        """
        redis = self.infra.redis_client
        pipe = redis.pipeline()
        count = 0

        for child in children:
            if child.section:
                key = f"{REF_KEY_PREFIX}{child.section.lower()}"
                pipe.set(key, child.id)
                count += 1

        if count > 0:
            try:
                await pipe.execute()
                logger.info(f"Built reference index with {count} entries")
            except Exception as e:
                logger.error(f"Failed to build reference index: {e}")
                raise IndexingError(f"Reference index build failed: {e}")

        return count

    async def get_parent(self, parent_id: str) -> Optional[dict]:
        """Retrieve a parent by ID from Redis."""
        redis = self.infra.redis_client
        key = f"{PARENT_KEY_PREFIX}{parent_id}"

        try:
            data = await redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Failed to get parent {parent_id}: {e}")
            return None

    async def resolve_reference(self, section: str) -> Optional[str]:
        """Resolve a section reference to a child ID."""
        redis = self.infra.redis_client
        key = f"{REF_KEY_PREFIX}{section.lower()}"

        try:
            child_id = await redis.get(key)
            if child_id:
                return child_id.decode() if isinstance(child_id, bytes) else child_id
            return None
        except Exception as e:
            logger.warning(f"Failed to resolve reference {section}: {e}")
            return None

    async def get_child_metadata(self, child_id: str) -> Optional[dict]:
        """Get metadata for a child from ChromaDB."""
        try:
            result = self.collection.get(ids=[child_id], include=["metadatas"])
            if result["metadatas"]:
                return result["metadatas"][0]
            return None
        except Exception as e:
            logger.warning(f"Failed to get child metadata {child_id}: {e}")
            return None

    async def clear_all(self) -> None:
        """Clear all stored data. Use with caution."""
        try:
            if self._collection_name:
                self.infra.delete_collection(self._collection_name)
                self._collection = self.infra.get_or_create_collection(
                    self._collection_name
                )

            await self.infra.clear_bm25_index()

            redis = self.infra.redis_client
            cursor = 0
            while True:
                cursor, keys = await redis.scan(
                    cursor,
                    match=f"{PARENT_KEY_PREFIX}*",
                    count=100,
                )
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break

            cursor = 0
            while True:
                cursor, keys = await redis.scan(
                    cursor,
                    match=f"{REF_KEY_PREFIX}*",
                    count=100,
                )
                if keys:
                    await redis.delete(*keys)
                if cursor == 0:
                    break

            logger.info("Cleared all storage")

        except Exception as e:
            logger.error(f"Failed to clear storage: {e}")
            raise IndexingError(f"Storage clear failed: {e}")
