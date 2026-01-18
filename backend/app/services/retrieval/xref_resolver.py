"""Resolve cross-references to expand retrieval context."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_settings
from app.services.indexing.storage import StorageLayer
from .parent_ranker import RankedParent

logger = logging.getLogger(__name__)


@dataclass
class ResolvedXRef:
    """A resolved cross-reference."""

    section: str
    child_id: str
    parent_id: str
    parent_data: dict = field(default_factory=dict)


@dataclass
class EnhancedParent:
    """A ranked parent with resolved cross-references."""

    id: str
    score: float
    match_count: int
    best_similarity: float
    parent_data: dict = field(default_factory=dict)
    resolved_xrefs: list[ResolvedXRef] = field(default_factory=list)
    is_xref_parent: bool = False


class XRefResolver:
    """
    Resolve cross-references found in matched children.

    For each ranked parent:
    1. Collect unique xrefs from matched children
    2. Resolve section references to child IDs
    3. Look up parent IDs from child metadata
    4. Fetch parent data for context expansion

    This allows the Context Assembler to include referenced sections
    alongside the directly matched content.
    """

    MAX_XREFS_PER_PARENT = 5
    MAX_TOTAL_XREF_PARENTS = 3

    def __init__(self, storage: StorageLayer):
        self.storage = storage

    async def resolve(
        self,
        ranked_parents: list[RankedParent],
    ) -> list[EnhancedParent]:
        """
        Resolve cross-references and fetch parent data.

        Args:
            ranked_parents: List of RankedParent from ParentRanker

        Returns:
            List of EnhancedParent with resolved xrefs and parent data
        """
        settings = get_settings()

        if not settings.enable_xref_expansion:
            return await self._convert_without_xrefs(ranked_parents)

        if not ranked_parents:
            return []

        existing_parent_ids = {p.id for p in ranked_parents}
        enhanced: list[EnhancedParent] = []
        xref_parents: list[EnhancedParent] = []

        for ranked in ranked_parents:
            parent_data = await self.storage.get_parent(ranked.id)

            resolved_xrefs = await self._resolve_parent_xrefs(
                ranked.xrefs,
                existing_parent_ids,
            )

            enhanced.append(EnhancedParent(
                id=ranked.id,
                score=ranked.score,
                match_count=ranked.match_count,
                best_similarity=ranked.best_similarity,
                parent_data=parent_data or {},
                resolved_xrefs=resolved_xrefs,
                is_xref_parent=False,
            ))

            for xref in resolved_xrefs:
                if xref.parent_id not in existing_parent_ids:
                    existing_parent_ids.add(xref.parent_id)

                    if len(xref_parents) < self.MAX_TOTAL_XREF_PARENTS:
                        xref_parents.append(EnhancedParent(
                            id=xref.parent_id,
                            score=0.0,
                            match_count=0,
                            best_similarity=0.0,
                            parent_data=xref.parent_data,
                            resolved_xrefs=[],
                            is_xref_parent=True,
                        ))

        result = enhanced + xref_parents

        logger.debug(
            f"Resolved xrefs: {len(enhanced)} primary parents, "
            f"{len(xref_parents)} xref parents"
        )

        return result

    async def _resolve_parent_xrefs(
        self,
        xrefs: list[str],
        exclude_parent_ids: set[str],
    ) -> list[ResolvedXRef]:
        """Resolve xrefs for a single parent."""
        resolved = []

        for section in xrefs[:self.MAX_XREFS_PER_PARENT]:
            xref = await self._resolve_single_xref(section, exclude_parent_ids)
            if xref:
                resolved.append(xref)

        return resolved

    async def _resolve_single_xref(
        self,
        section: str,
        exclude_parent_ids: set[str],
    ) -> Optional[ResolvedXRef]:
        """Resolve a single section reference."""
        child_id = await self.storage.resolve_reference(section)
        if not child_id:
            return None

        child_meta = await self.storage.get_child_metadata(child_id)
        if not child_meta:
            return None

        parent_id = child_meta.get("parent_id")
        if not parent_id:
            return None

        if parent_id in exclude_parent_ids:
            return None

        parent_data = await self.storage.get_parent(parent_id)
        if not parent_data:
            return None

        return ResolvedXRef(
            section=section,
            child_id=child_id,
            parent_id=parent_id,
            parent_data=parent_data,
        )

    async def _convert_without_xrefs(
        self,
        ranked_parents: list[RankedParent],
    ) -> list[EnhancedParent]:
        """Convert ranked parents without xref resolution."""
        enhanced = []

        for ranked in ranked_parents:
            parent_data = await self.storage.get_parent(ranked.id)

            enhanced.append(EnhancedParent(
                id=ranked.id,
                score=ranked.score,
                match_count=ranked.match_count,
                best_similarity=ranked.best_similarity,
                parent_data=parent_data or {},
                resolved_xrefs=[],
                is_xref_parent=False,
            ))

        return enhanced
