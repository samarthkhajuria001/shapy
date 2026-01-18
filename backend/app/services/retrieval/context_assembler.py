"""Assemble retrieved parents into context for LLM consumption."""

import logging
from dataclasses import dataclass, field
from typing import Optional

import tiktoken

from app.config import get_settings
from .xref_resolver import EnhancedParent

logger = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    """Final context assembled for LLM consumption."""

    text: str
    token_count: int
    primary_parent_count: int
    xref_parent_count: int
    sources: list[str] = field(default_factory=list)
    sections_included: list[str] = field(default_factory=list)


class ContextAssembler:
    """
    Assemble enhanced parents into a formatted context string.

    Output format:
    ```
    === RELEVANT DOCUMENT SECTIONS ===

    [Source: document.pdf | Pages 12-14]
    <parent text>

    [Source: document.pdf | Pages 18-19]
    <parent text>

    --- CROSS-REFERENCED SECTIONS ---

    [Reference: Section A.1.g | Pages 5-6]
    <xref parent text>
    ```

    Manages token budget by truncating lower-priority content.
    Primary parents are included first, then xref parents.
    """

    ENCODING_NAME = "cl100k_base"
    FALLBACK_CHARS_PER_TOKEN = 4
    DEFAULT_MAX_TOKENS = 4000

    PRIMARY_HEADER = "=== RELEVANT DOCUMENT SECTIONS ==="
    XREF_HEADER = "--- CROSS-REFERENCED SECTIONS ---"

    def __init__(self, max_tokens: Optional[int] = None):
        self.max_tokens = max_tokens or self.DEFAULT_MAX_TOKENS

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

    def assemble(
        self,
        enhanced_parents: list[EnhancedParent],
        max_tokens: Optional[int] = None,
    ) -> AssembledContext:
        """
        Assemble enhanced parents into formatted context.

        Args:
            enhanced_parents: List of EnhancedParent from XRefResolver
            max_tokens: Override default token limit

        Returns:
            AssembledContext with formatted text and metadata
        """
        budget = max_tokens or self.max_tokens

        if not enhanced_parents:
            return AssembledContext(
                text="",
                token_count=0,
                primary_parent_count=0,
                xref_parent_count=0,
            )

        primary_parents = [p for p in enhanced_parents if not p.is_xref_parent]
        xref_parents = [p for p in enhanced_parents if p.is_xref_parent]

        sections = []
        sources = set()
        section_ids = set()
        total_tokens = 0

        header_tokens = self.count_tokens(self.PRIMARY_HEADER) + 4
        total_tokens += header_tokens

        primary_count = 0
        for parent in primary_parents:
            section_text = self._format_primary_section(parent)
            section_tokens = self.count_tokens(section_text)

            if total_tokens + section_tokens > budget:
                truncated = self._truncate_to_fit(
                    section_text, budget - total_tokens
                )
                if truncated:
                    sections.append(truncated)
                    total_tokens += self.count_tokens(truncated)
                    primary_count += 1
                    self._collect_metadata(parent, sources, section_ids)
                break

            sections.append(section_text)
            total_tokens += section_tokens
            primary_count += 1
            self._collect_metadata(parent, sources, section_ids)

        xref_count = 0
        if xref_parents and total_tokens < budget:
            xref_header_tokens = self.count_tokens(self.XREF_HEADER) + 4

            if total_tokens + xref_header_tokens < budget:
                sections.append(f"\n{self.XREF_HEADER}\n")
                total_tokens += xref_header_tokens

                for parent in xref_parents:
                    section_text = self._format_xref_section(parent)
                    section_tokens = self.count_tokens(section_text)

                    if total_tokens + section_tokens > budget:
                        truncated = self._truncate_to_fit(
                            section_text, budget - total_tokens
                        )
                        if truncated:
                            sections.append(truncated)
                            total_tokens += self.count_tokens(truncated)
                            xref_count += 1
                            self._collect_metadata(parent, sources, section_ids)
                        break

                    sections.append(section_text)
                    total_tokens += section_tokens
                    xref_count += 1
                    self._collect_metadata(parent, sources, section_ids)

        full_text = f"{self.PRIMARY_HEADER}\n\n" + "\n\n".join(sections)
        final_tokens = self.count_tokens(full_text)

        logger.debug(
            f"Assembled context: {primary_count} primary, {xref_count} xref, "
            f"{final_tokens} tokens"
        )

        return AssembledContext(
            text=full_text,
            token_count=final_tokens,
            primary_parent_count=primary_count,
            xref_parent_count=xref_count,
            sources=sorted(sources),
            sections_included=sorted(section_ids),
        )

    def _format_primary_section(self, parent: EnhancedParent) -> str:
        """Format a primary parent section."""
        data = parent.parent_data
        source = data.get("source", "unknown")
        page_start = data.get("page_start", 0)
        page_end = data.get("page_end", 0)
        text = data.get("text", "")

        if page_start == page_end:
            page_info = f"Page {page_start}"
        else:
            page_info = f"Pages {page_start}-{page_end}"

        header = f"[Source: {source} | {page_info}]"
        return f"{header}\n{text}"

    def _format_xref_section(self, parent: EnhancedParent) -> str:
        """Format a cross-reference parent section."""
        data = parent.parent_data
        source = data.get("source", "unknown")
        page_start = data.get("page_start", 0)
        page_end = data.get("page_end", 0)
        text = data.get("text", "")

        content_index = data.get("content_index", {})
        sections = content_index.get("sections_covered", [])
        section_label = sections[0] if sections else "related section"

        if page_start == page_end:
            page_info = f"Page {page_start}"
        else:
            page_info = f"Pages {page_start}-{page_end}"

        header = f"[Reference: {section_label} | {page_info}]"
        return f"{header}\n{text}"

    def _collect_metadata(
        self,
        parent: EnhancedParent,
        sources: set,
        section_ids: set,
    ) -> None:
        """Collect metadata from parent for summary."""
        data = parent.parent_data
        source = data.get("source")
        if source:
            sources.add(source)

        content_index = data.get("content_index", {})
        for section in content_index.get("sections_covered", []):
            section_ids.add(section)

    def _truncate_to_fit(self, text: str, available_tokens: int) -> str:
        """Truncate text to fit within token budget."""
        if available_tokens <= 20:
            return ""

        current_tokens = self.count_tokens(text)
        if current_tokens <= available_tokens:
            return text

        ratio = available_tokens / current_tokens
        target_chars = int(len(text) * ratio * 0.9)

        truncated = text[:target_chars]

        last_period = truncated.rfind(".")
        last_newline = truncated.rfind("\n")
        break_point = max(last_period, last_newline)

        if break_point > target_chars * 0.5:
            truncated = truncated[:break_point + 1]

        return truncated.strip() + "\n[... truncated ...]"
