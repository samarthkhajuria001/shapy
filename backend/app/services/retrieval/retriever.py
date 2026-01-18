"""Main retrieval service orchestrating the full retrieval pipeline."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_settings
from app.core.exceptions import RetrievalError
from app.services.indexing.infrastructure import IndexingInfrastructure
from app.services.indexing.storage import StorageLayer

from .query_expander import QueryExpander
from .hybrid_searcher import HybridSearcher, MatchedChild
from .parent_ranker import ParentRanker, RankedParent
from .xref_resolver import XRefResolver, EnhancedParent
from .context_assembler import ContextAssembler, AssembledContext

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Complete result from the retrieval pipeline."""

    context: AssembledContext
    query_variations: list[str]
    matched_children_count: int
    ranked_parents: list[RankedParent] = field(default_factory=list)
    enhanced_parents: list[EnhancedParent] = field(default_factory=list)


class RetrieverService:
    """
    Orchestrate the full document retrieval pipeline.

    Pipeline stages:
    1. QueryExpander: Generate query variations for broader coverage
    2. HybridSearcher: Vector + BM25 search with RRF fusion
    3. ParentRanker: Aggregate children into ranked parents
    4. XRefResolver: Resolve cross-references for context expansion
    5. ContextAssembler: Format final context for LLM consumption

    Usage:
        retriever = RetrieverService(infrastructure)
        await retriever.initialize()
        result = await retriever.retrieve("Can I build a 4m extension?")
        context_for_llm = result.context.text
    """

    def __init__(self, infrastructure: IndexingInfrastructure):
        self.infra = infrastructure
        self._initialized = False

        self._query_expander: Optional[QueryExpander] = None
        self._hybrid_searcher: Optional[HybridSearcher] = None
        self._parent_ranker: Optional[ParentRanker] = None
        self._xref_resolver: Optional[XRefResolver] = None
        self._context_assembler: Optional[ContextAssembler] = None
        self._storage: Optional[StorageLayer] = None

    async def initialize(self, collection_name: Optional[str] = None) -> None:
        """
        Initialize all pipeline components.

        Args:
            collection_name: ChromaDB collection to search (default from settings)
        """
        if self._initialized:
            return

        settings = get_settings()

        self._storage = StorageLayer(self.infra)
        await self._storage.initialize(collection_name)

        self._query_expander = QueryExpander(self.infra.openai_client)

        self._hybrid_searcher = HybridSearcher(self.infra)
        self._hybrid_searcher.initialize(collection_name)

        self._parent_ranker = ParentRanker()

        self._xref_resolver = XRefResolver(self._storage)

        self._context_assembler = ContextAssembler()

        self._initialized = True
        logger.info("RetrieverService initialized")

    def _check_initialized(self) -> None:
        """Ensure service is initialized before use."""
        if not self._initialized:
            raise RetrievalError(
                "RetrieverService not initialized. Call initialize() first."
            )

    async def retrieve(
        self,
        query: str,
        top_k_per_query: Optional[int] = None,
        top_n_parents: Optional[int] = None,
        max_context_tokens: Optional[int] = None,
        expand_query: Optional[bool] = None,
        resolve_xrefs: Optional[bool] = None,
    ) -> RetrievalResult:
        """
        Execute the full retrieval pipeline for a query.

        Args:
            query: User's natural language query
            top_k_per_query: Override children per query per search method
            top_n_parents: Override number of parents to return
            max_context_tokens: Override context token budget
            expand_query: Override query expansion setting
            resolve_xrefs: Override xref resolution setting

        Returns:
            RetrievalResult with assembled context and metadata

        Raises:
            RetrievalError: If service not initialized or critical failure
        """
        self._check_initialized()

        settings = get_settings()
        do_expand = expand_query if expand_query is not None else settings.enable_query_expansion
        do_xrefs = resolve_xrefs if resolve_xrefs is not None else settings.enable_xref_expansion

        if not query or not query.strip():
            logger.debug("Empty query provided")
            return self._empty_result()

        query = query.strip()

        logger.info(f"Retrieval started for query: {query[:100]}...")

        if do_expand:
            try:
                query_variations = await self._query_expander.expand(query)
                logger.debug(f"Generated {len(query_variations)} query variations")
            except Exception as e:
                logger.warning(f"Query expansion failed, using original: {e}")
                query_variations = [query]
        else:
            query_variations = [query]

        try:
            matched_children = self._hybrid_searcher.search(
                queries=query_variations,
                top_k_per_query=top_k_per_query,
            )
            logger.debug(f"Hybrid search returned {len(matched_children)} children")
        except Exception as e:
            logger.error(f"Hybrid search failed: {e}")
            raise RetrievalError(f"Search failed: {e}")

        if not matched_children:
            logger.info("No search results found")
            return RetrievalResult(
                context=AssembledContext(
                    text="",
                    token_count=0,
                    primary_parent_count=0,
                    xref_parent_count=0,
                ),
                query_variations=query_variations,
                matched_children_count=0,
            )

        ranked_parents = self._parent_ranker.rank(
            matched_children=matched_children,
            top_n=top_n_parents,
        )
        logger.debug(f"Ranked {len(ranked_parents)} parents")

        if not ranked_parents:
            logger.info("No parents found after ranking")
            return RetrievalResult(
                context=AssembledContext(
                    text="",
                    token_count=0,
                    primary_parent_count=0,
                    xref_parent_count=0,
                ),
                query_variations=query_variations,
                matched_children_count=len(matched_children),
            )

        if do_xrefs:
            try:
                enhanced_parents = await self._xref_resolver.resolve(ranked_parents)
                logger.debug(f"Resolved xrefs: {len(enhanced_parents)} enhanced parents")
            except Exception as e:
                logger.warning(f"XRef resolution failed, continuing without: {e}")
                enhanced_parents = await self._xref_resolver._convert_without_xrefs(
                    ranked_parents
                )
        else:
            enhanced_parents = await self._xref_resolver._convert_without_xrefs(
                ranked_parents
            )

        context = self._context_assembler.assemble(
            enhanced_parents=enhanced_parents,
            max_tokens=max_context_tokens,
        )

        logger.info(
            f"Retrieval complete: {context.primary_parent_count} primary, "
            f"{context.xref_parent_count} xref, {context.token_count} tokens"
        )

        return RetrievalResult(
            context=context,
            query_variations=query_variations,
            matched_children_count=len(matched_children),
            ranked_parents=ranked_parents,
            enhanced_parents=enhanced_parents,
        )

    async def retrieve_context_only(
        self,
        query: str,
        max_tokens: Optional[int] = None,
    ) -> str:
        """
        Convenience method to get just the context text.

        Args:
            query: User's natural language query
            max_tokens: Context token budget

        Returns:
            Formatted context string ready for LLM
        """
        result = await self.retrieve(
            query=query,
            max_context_tokens=max_tokens,
        )
        return result.context.text

    async def search_children(
        self,
        query: str,
        top_k: Optional[int] = None,
    ) -> list[MatchedChild]:
        """
        Search for matching children without parent aggregation.

        Useful for debugging or when you need child-level results.

        Args:
            query: User's natural language query
            top_k: Number of children to return

        Returns:
            List of MatchedChild from hybrid search
        """
        self._check_initialized()

        settings = get_settings()

        if settings.enable_query_expansion:
            try:
                queries = await self._query_expander.expand(query)
            except Exception:
                queries = [query]
        else:
            queries = [query]

        return self._hybrid_searcher.search(
            queries=queries,
            top_k_per_query=top_k,
        )

    def _empty_result(self) -> RetrievalResult:
        """Create an empty result for edge cases."""
        return RetrievalResult(
            context=AssembledContext(
                text="",
                token_count=0,
                primary_parent_count=0,
                xref_parent_count=0,
            ),
            query_variations=[],
            matched_children_count=0,
        )


_retriever_service: Optional[RetrieverService] = None


async def get_retriever_service(
    infrastructure: Optional[IndexingInfrastructure] = None,
) -> RetrieverService:
    """
    Get or create the singleton RetrieverService.

    Args:
        infrastructure: Optional infrastructure instance. If not provided,
                       will use the singleton infrastructure.

    Returns:
        Initialized RetrieverService instance
    """
    global _retriever_service

    if _retriever_service is None:
        if infrastructure is None:
            from app.services.indexing.infrastructure import get_indexing_infrastructure
            infrastructure = await get_indexing_infrastructure()

        _retriever_service = RetrieverService(infrastructure)
        await _retriever_service.initialize()

    return _retriever_service


async def close_retriever_service() -> None:
    """Close the singleton RetrieverService."""
    global _retriever_service
    _retriever_service = None
