"""Retrieval services for document search and context assembly."""

from .query_expander import QueryExpander
from .hybrid_searcher import HybridSearcher, MatchedChild
from .parent_ranker import ParentRanker, RankedParent
from .xref_resolver import XRefResolver, ResolvedXRef, EnhancedParent
from .context_assembler import ContextAssembler, AssembledContext
from .retriever import (
    RetrieverService,
    RetrievalResult,
    get_retriever_service,
    close_retriever_service,
)

__all__ = [
    "QueryExpander",
    "HybridSearcher",
    "MatchedChild",
    "ParentRanker",
    "RankedParent",
    "XRefResolver",
    "ResolvedXRef",
    "EnhancedParent",
    "ContextAssembler",
    "AssembledContext",
    "RetrieverService",
    "RetrievalResult",
    "get_retriever_service",
    "close_retriever_service",
]
