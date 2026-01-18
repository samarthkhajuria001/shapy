"""Infrastructure connections for the indexing system."""

import logging
import pickle
from pathlib import Path
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from openai import AsyncOpenAI
from rank_bm25 import BM25Okapi
import redis.asyncio as redis

from app.config import get_settings
from app.core.exceptions import ChromaDBConnectionError, BM25IndexError

logger = logging.getLogger(__name__)

BM25_REDIS_KEY = "indexing:bm25:index"
BM25_VERSION_KEY = "indexing:bm25:version"
CURRENT_BM25_VERSION = "1"


class IndexingInfrastructure:
    """
    Manages connections to ChromaDB, Redis, and OpenAI for the indexing system.

    Provides centralized access to:
    - ChromaDB for vector storage and similarity search
    - Redis for parent document storage and BM25 index persistence
    - OpenAI for embeddings and LLM enrichment
    """

    def __init__(
        self,
        chroma_path: Optional[str] = None,
        redis_url: Optional[str] = None,
        openai_api_key: Optional[str] = None,
    ):
        settings = get_settings()

        self._chroma_path = chroma_path or settings.chroma_path
        self._redis_url = redis_url or settings.redis_url
        self._openai_api_key = openai_api_key or settings.openai_api_key

        self._chroma_client: Optional[chromadb.ClientAPI] = None
        self._redis_client: Optional[redis.Redis] = None
        self._openai_client: Optional[AsyncOpenAI] = None

        self._bm25_index: Optional[BM25Okapi] = None
        self._bm25_child_ids: list[str] = []
        self._bm25_corpus: list[list[str]] = []

        self._connected = False

    @property
    def chroma_client(self) -> chromadb.ClientAPI:
        if self._chroma_client is None:
            raise ChromaDBConnectionError("ChromaDB client not initialized")
        return self._chroma_client

    @property
    def redis_client(self) -> redis.Redis:
        if self._redis_client is None:
            raise RuntimeError("Redis client not initialized")
        return self._redis_client

    @property
    def openai_client(self) -> AsyncOpenAI:
        if self._openai_client is None:
            raise RuntimeError("OpenAI client not initialized")
        return self._openai_client

    @property
    def bm25_index(self) -> Optional[BM25Okapi]:
        return self._bm25_index

    @property
    def bm25_child_ids(self) -> list[str]:
        return self._bm25_child_ids

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        """Establish all connections."""
        if self._connected:
            return

        self._init_chroma()
        await self._init_redis()
        self._init_openai()
        await self._load_bm25_index()

        self._connected = True
        logger.info("Indexing infrastructure connected")

    async def disconnect(self) -> None:
        """Close all connections."""
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None

        self._chroma_client = None
        self._openai_client = None
        self._bm25_index = None
        self._bm25_child_ids = []
        self._bm25_corpus = []

        self._connected = False
        logger.info("Indexing infrastructure disconnected")

    def _init_chroma(self) -> None:
        """Initialize ChromaDB persistent client."""
        try:
            chroma_path = Path(self._chroma_path)
            chroma_path.mkdir(parents=True, exist_ok=True)

            self._chroma_client = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )
            logger.info(f"ChromaDB initialized at {chroma_path}")
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {e}")
            raise ChromaDBConnectionError(f"ChromaDB initialization failed: {e}")

    async def _init_redis(self) -> None:
        """Initialize async Redis client."""
        try:
            self._redis_client = redis.from_url(
                self._redis_url,
                decode_responses=False,
            )
            await self._redis_client.ping()
            logger.info("Redis connected for indexing")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise RuntimeError(f"Redis connection failed: {e}")

    def _init_openai(self) -> None:
        """Initialize OpenAI async client."""
        if not self._openai_api_key:
            logger.warning("OpenAI API key not configured")
            self._openai_client = AsyncOpenAI(api_key="dummy")
            return

        self._openai_client = AsyncOpenAI(api_key=self._openai_api_key)
        logger.info("OpenAI client initialized")

    def get_or_create_collection(
        self,
        name: Optional[str] = None,
    ) -> chromadb.Collection:
        """Get or create a ChromaDB collection."""
        settings = get_settings()
        collection_name = name or settings.chroma_collection

        try:
            collection = self.chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.debug(f"Collection '{collection_name}' ready")
            return collection
        except Exception as e:
            logger.error(f"Failed to get/create collection: {e}")
            raise ChromaDBConnectionError(f"Collection operation failed: {e}")

    def delete_collection(self, name: Optional[str] = None) -> None:
        """Delete a ChromaDB collection."""
        settings = get_settings()
        collection_name = name or settings.chroma_collection

        try:
            self.chroma_client.delete_collection(name=collection_name)
            logger.info(f"Collection '{collection_name}' deleted")
        except Exception as e:
            logger.warning(f"Failed to delete collection '{collection_name}': {e}")

    async def _load_bm25_index(self) -> None:
        """Load BM25 index from Redis if available."""
        try:
            version = await self._redis_client.get(BM25_VERSION_KEY)
            if version and version.decode() != CURRENT_BM25_VERSION:
                logger.info("BM25 index version mismatch, will rebuild on next ingestion")
                return

            data = await self._redis_client.get(BM25_REDIS_KEY)
            if not data:
                logger.info("No existing BM25 index found")
                return

            loaded = pickle.loads(data)
            self._bm25_corpus = loaded.get("corpus", [])
            self._bm25_child_ids = loaded.get("child_ids", [])

            if self._bm25_corpus:
                self._bm25_index = BM25Okapi(self._bm25_corpus)
                logger.info(f"BM25 index loaded with {len(self._bm25_child_ids)} documents")
            else:
                logger.info("BM25 index is empty")

        except Exception as e:
            logger.warning(f"Failed to load BM25 index: {e}")
            self._bm25_index = None
            self._bm25_child_ids = []
            self._bm25_corpus = []

    async def save_bm25_index(
        self,
        corpus: list[list[str]],
        child_ids: list[str],
    ) -> None:
        """
        Build and persist BM25 index to Redis.

        Args:
            corpus: List of tokenized documents (each document is a list of tokens)
            child_ids: Corresponding child IDs for each document
        """
        if len(corpus) != len(child_ids):
            raise BM25IndexError("Corpus and child_ids length mismatch")

        try:
            self._bm25_corpus = corpus
            self._bm25_child_ids = child_ids
            self._bm25_index = BM25Okapi(corpus) if corpus else None

            data = {
                "corpus": corpus,
                "child_ids": child_ids,
            }
            serialized = pickle.dumps(data)

            await self._redis_client.set(BM25_REDIS_KEY, serialized)
            await self._redis_client.set(BM25_VERSION_KEY, CURRENT_BM25_VERSION)

            logger.info(f"BM25 index saved with {len(child_ids)} documents")

        except Exception as e:
            logger.error(f"Failed to save BM25 index: {e}")
            raise BM25IndexError(f"Failed to persist BM25 index: {e}")

    async def clear_bm25_index(self) -> None:
        """Clear the BM25 index from memory and Redis."""
        self._bm25_index = None
        self._bm25_child_ids = []
        self._bm25_corpus = []

        try:
            await self._redis_client.delete(BM25_REDIS_KEY, BM25_VERSION_KEY)
            logger.info("BM25 index cleared")
        except Exception as e:
            logger.warning(f"Failed to clear BM25 index from Redis: {e}")

    async def health_check(self) -> dict:
        """
        Check health of all infrastructure components.

        Returns:
            Dict with status of each component
        """
        health = {
            "chroma": False,
            "redis": False,
            "openai": False,
            "bm25_loaded": False,
        }

        if self._chroma_client:
            try:
                self._chroma_client.heartbeat()
                health["chroma"] = True
            except Exception:
                pass

        if self._redis_client:
            try:
                await self._redis_client.ping()
                health["redis"] = True
            except Exception:
                pass

        if self._openai_client:
            health["openai"] = True

        health["bm25_loaded"] = self._bm25_index is not None
        health["bm25_document_count"] = len(self._bm25_child_ids)

        return health


_infrastructure: Optional[IndexingInfrastructure] = None


async def get_indexing_infrastructure() -> IndexingInfrastructure:
    """Get the singleton indexing infrastructure instance."""
    global _infrastructure
    if _infrastructure is None:
        _infrastructure = IndexingInfrastructure()
        await _infrastructure.connect()
    return _infrastructure


async def close_indexing_infrastructure() -> None:
    """Close the singleton indexing infrastructure."""
    global _infrastructure
    if _infrastructure:
        await _infrastructure.disconnect()
        _infrastructure = None
