"""Hybrid search combining vector and BM25 with Reciprocal Rank Fusion."""

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_settings
from app.services.indexing.infrastructure import IndexingInfrastructure

logger = logging.getLogger(__name__)


@dataclass
class MatchedChild:
    """A child matched by hybrid search."""

    id: str
    rrf_score: float
    vector_score: float
    bm25_score: float
    parent_id: str
    xrefs: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class HybridSearcher:
    """
    Combine vector and BM25 search using Reciprocal Rank Fusion.

    For each query variation:
    1. Run vector search (ChromaDB) -> top-k children
    2. Run BM25 search -> top-k children
    3. Combine using RRF: score = 1/(k+rank_vector) + 1/(k+rank_bm25)
    4. Deduplicate and return ranked results
    """

    def __init__(self, infrastructure: IndexingInfrastructure):
        self.infra = infrastructure
        self._collection = None
        self._collection_name = None

    def initialize(self, collection_name: Optional[str] = None) -> None:
        """Initialize with ChromaDB collection."""
        settings = get_settings()
        self._collection_name = collection_name or settings.chroma_collection
        self._collection = self.infra.get_or_create_collection(self._collection_name)
        logger.info(f"HybridSearcher initialized with collection: {self._collection_name}")

    @property
    def collection(self):
        if self._collection is None:
            raise RuntimeError("HybridSearcher not initialized. Call initialize() first.")
        return self._collection

    def search(
        self,
        queries: list[str],
        top_k_per_query: Optional[int] = None,
    ) -> list[MatchedChild]:
        """
        Perform hybrid search with multiple query variations.

        Args:
            queries: List of query variations (typically 5)
            top_k_per_query: Results per query per method

        Returns:
            Deduplicated, RRF-ranked list of MatchedChild
        """
        settings = get_settings()
        top_k = top_k_per_query or settings.retrieval_top_k_per_query
        rrf_k = settings.retrieval_rrf_k

        if not queries:
            return []

        vector_results: dict[str, tuple[float, dict]] = {}
        bm25_results: dict[str, float] = {}

        for query in queries:
            if not query.strip():
                continue

            v_hits = self._vector_search(query, top_k)
            for child_id, score, meta in v_hits:
                if child_id not in vector_results or score > vector_results[child_id][0]:
                    vector_results[child_id] = (score, meta)

            if settings.enable_bm25 and self.infra.bm25_index is not None:
                b_hits = self._bm25_search(query, top_k)
                for child_id, score in b_hits:
                    if child_id not in bm25_results or score > bm25_results[child_id]:
                        bm25_results[child_id] = score

        if not vector_results and not bm25_results:
            logger.debug("No search results found")
            return []

        matched = self._compute_rrf(vector_results, bm25_results, rrf_k)

        logger.debug(
            f"Hybrid search: {len(queries)} queries, "
            f"{len(vector_results)} vector hits, "
            f"{len(bm25_results)} BM25 hits, "
            f"{len(matched)} combined results"
        )

        return matched

    def _vector_search(
        self,
        query: str,
        top_k: int,
    ) -> list[tuple[str, float, dict]]:
        """Run vector search on ChromaDB."""
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=top_k,
                include=["distances", "metadatas"],
            )

            hits = []
            if results["ids"] and results["ids"][0]:
                ids = results["ids"][0]
                distances = results["distances"][0] if results["distances"] else []
                metadatas = results["metadatas"][0] if results["metadatas"] else []

                for i, child_id in enumerate(ids):
                    dist = distances[i] if i < len(distances) else 1.0
                    score = 1.0 - dist
                    meta = metadatas[i] if i < len(metadatas) else {}
                    hits.append((child_id, score, meta))

            return hits

        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []

    def _bm25_search(
        self,
        query: str,
        top_k: int,
    ) -> list[tuple[str, float]]:
        """Run BM25 search."""
        try:
            if self.infra.bm25_index is None:
                return []

            tokens = query.lower().split()
            if not tokens:
                return []

            scores = self.infra.bm25_index.get_scores(tokens)
            child_ids = self.infra.bm25_child_ids

            if len(scores) != len(child_ids):
                logger.warning("BM25 score/ID mismatch")
                return []

            indexed = [(child_ids[i], scores[i]) for i in range(len(scores))]
            indexed.sort(key=lambda x: -x[1])

            return [(cid, score) for cid, score in indexed[:top_k] if score > 0]

        except Exception as e:
            logger.warning(f"BM25 search failed: {e}")
            return []

    def _compute_rrf(
        self,
        vector_results: dict[str, tuple[float, dict]],
        bm25_results: dict[str, float],
        rrf_k: int,
    ) -> list[MatchedChild]:
        """Compute Reciprocal Rank Fusion scores."""
        all_ids = set(vector_results.keys()) | set(bm25_results.keys())

        if not all_ids:
            return []

        v_sorted = sorted(
            vector_results.keys(),
            key=lambda x: -vector_results[x][0]
        )
        v_rank = {cid: rank + 1 for rank, cid in enumerate(v_sorted)}

        b_sorted = sorted(
            bm25_results.keys(),
            key=lambda x: -bm25_results[x]
        )
        b_rank = {cid: rank + 1 for rank, cid in enumerate(b_sorted)}

        matched = []
        for child_id in all_ids:
            rrf_score = 0.0
            v_score = 0.0
            b_score = 0.0
            metadata = {}

            if child_id in vector_results:
                v_score, metadata = vector_results[child_id]
                rrf_score += 1.0 / (rrf_k + v_rank[child_id])

            if child_id in bm25_results:
                b_score = bm25_results[child_id]
                rrf_score += 1.0 / (rrf_k + b_rank[child_id])

            parent_id = metadata.get("parent_id", "")
            xrefs_raw = metadata.get("xrefs", "[]")
            try:
                xrefs = json.loads(xrefs_raw) if isinstance(xrefs_raw, str) else []
            except json.JSONDecodeError:
                xrefs = []

            matched.append(MatchedChild(
                id=child_id,
                rrf_score=rrf_score,
                vector_score=v_score,
                bm25_score=b_score,
                parent_id=parent_id,
                xrefs=xrefs,
                metadata=metadata,
            ))

        matched.sort(key=lambda x: -x.rrf_score)

        return matched
