"""Group enriched children into parent context windows."""

import logging
from dataclasses import dataclass, field
from typing import Optional

import tiktoken

from app.config import get_settings
from .llm_enricher import EnrichedChild

logger = logging.getLogger(__name__)


@dataclass
class ContentIndex:
    """Summary of content types within a parent."""

    diagrams: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    sections_covered: list[str] = field(default_factory=list)
    definitions_used: list[str] = field(default_factory=list)


@dataclass
class Parent:
    """A context window containing multiple children."""

    id: str
    text: str
    token_count: int
    children_ids: list[str]
    page_start: int
    page_end: int
    source: str
    content_index: ContentIndex


class ParentGrouper:
    """
    Group children into parents using soft token limits.

    The soft limit means: add child first, then check limit.
    A child is never split - we complete it, then start a new parent if needed.
    """

    ENCODING_NAME = "cl100k_base"
    FALLBACK_CHARS_PER_TOKEN = 4

    def __init__(self, soft_limit_tokens: Optional[int] = None):
        settings = get_settings()
        self.soft_limit = soft_limit_tokens or settings.parent_soft_limit_tokens

        try:
            self._encoder = tiktoken.get_encoding(self.ENCODING_NAME)
        except Exception as e:
            logger.warning(f"Failed to load tiktoken encoder: {e}")
            self._encoder = None

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken or fallback."""
        if not text:
            return 0

        if self._encoder:
            try:
                return len(self._encoder.encode(text))
            except Exception:
                pass

        return len(text) // self.FALLBACK_CHARS_PER_TOKEN

    def group_children(
        self,
        children: list[EnrichedChild],
        source: str,
    ) -> tuple[list[EnrichedChild], list[Parent]]:
        """
        Group children into parents with soft token limits.

        Args:
            children: List of EnrichedChild from LLM enricher
            source: Source identifier for parent IDs

        Returns:
            Tuple of (children with parent_id assigned, list of Parent objects)
        """
        if not children:
            return [], []

        parents = []
        parent_idx = 0
        acc = self._new_accumulator(source, parent_idx)

        for child in children:
            child_tokens = self.count_tokens(child.text)

            if acc["page_start"] is None:
                acc["page_start"] = child.page
            acc["page_end"] = child.page

            parent_id = f"{source}_parent_{parent_idx}"
            child.parent_id = parent_id

            acc["children_ids"].append(child.id)
            acc["texts"].append(child.text)
            acc["token_count"] += child_tokens

            self._update_content_index(acc, child)

            if acc["token_count"] >= self.soft_limit:
                parents.append(self._finalize_parent(acc, source, parent_idx))
                parent_idx += 1
                acc = self._new_accumulator(source, parent_idx)

        if acc["children_ids"]:
            parents.append(self._finalize_parent(acc, source, parent_idx))

        logger.info(
            f"Grouped {len(children)} children into {len(parents)} parents "
            f"(soft limit: {self.soft_limit} tokens)"
        )

        return children, parents

    def _new_accumulator(self, source: str, idx: int) -> dict:
        """Create a new parent accumulator."""
        return {
            "children_ids": [],
            "texts": [],
            "token_count": 0,
            "page_start": None,
            "page_end": None,
            "diagrams": [],
            "tables": [],
            "sections": set(),
            "definitions": set(),
        }

    def _update_content_index(self, acc: dict, child: EnrichedChild) -> None:
        """Update accumulator's content index with child's content."""
        for diagram in child.diagrams:
            acc["diagrams"].append({
                "child_id": child.id,
                "title": diagram.title,
                "section": child.section,
            })

        for table in child.tables:
            acc["tables"].append({
                "child_id": child.id,
                "title": table.title,
                "section": child.section,
            })

        if child.section:
            acc["sections"].add(child.section)

        for defn in child.uses_definitions:
            acc["definitions"].add(defn)

    def _finalize_parent(
        self,
        acc: dict,
        source: str,
        idx: int,
    ) -> Parent:
        """Convert accumulator to Parent object."""
        combined_text = "\n\n".join(acc["texts"])

        content_index = ContentIndex(
            diagrams=acc["diagrams"],
            tables=acc["tables"],
            sections_covered=sorted(acc["sections"]),
            definitions_used=sorted(acc["definitions"]),
        )

        return Parent(
            id=f"{source}_parent_{idx}",
            text=combined_text,
            token_count=acc["token_count"],
            children_ids=acc["children_ids"],
            page_start=acc["page_start"] or 0,
            page_end=acc["page_end"] or 0,
            source=source,
            content_index=content_index,
        )
