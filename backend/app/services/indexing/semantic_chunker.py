"""Split PDF page content into semantic children."""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_settings
from .pdf_extractor import PageContent, ExtractedTable, ExtractedDiagram

logger = logging.getLogger(__name__)


@dataclass
class RawChild:
    """A semantic chunk before LLM enrichment."""

    id: str
    text: str
    page: int
    tables: list[ExtractedTable] = field(default_factory=list)
    diagrams: list[ExtractedDiagram] = field(default_factory=list)


class SemanticChunker:
    """
    Split page content into semantic units.

    Strategy:
    1. Split on paragraph breaks (double newlines)
    2. Split large paragraphs on subsection markers: (a), (b), (i), (ii)
    3. Merge small chunks, split remaining large ones on sentences
    4. Associate tables/diagrams with relevant text chunks
    """

    SUBSECTION_PATTERN = re.compile(
        r"^[\s]*(\([a-z]{1,2}\)|\([ivx]+\)|\([0-9]+\))",
        re.MULTILINE,
    )

    DIAGRAM_KEYWORDS = frozenset([
        "diagram", "figure", "illustration", "shown", "illustrated",
        "see the", "as shown", "refer to",
    ])

    def __init__(
        self,
        target_size: Optional[int] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ):
        settings = get_settings()
        self.target_size = target_size or settings.chunk_target_size
        self.min_size = min_size or settings.chunk_min_size
        self.max_size = max_size or settings.chunk_max_size

    def chunk_pages(
        self,
        pages: list[PageContent],
        source: str,
    ) -> list[RawChild]:
        """
        Chunk all pages into semantic children.

        Args:
            pages: List of PageContent from PDF extractor
            source: Source identifier (e.g., PDF filename without extension)

        Returns:
            List of RawChild objects ready for enrichment
        """
        all_children = []

        for page in pages:
            children = self._chunk_page(page, source)
            all_children.extend(children)

        logger.info(f"Created {len(all_children)} chunks from {len(pages)} pages")
        return all_children

    def _chunk_page(
        self,
        page: PageContent,
        source: str,
    ) -> list[RawChild]:
        """Chunk a single page into semantic children."""
        text = page.text
        page_num = page.page_num

        if not text.strip() and not page.tables:
            return []

        if not text.strip() and page.tables:
            children = []
            for idx, table in enumerate(page.tables):
                combined = f"[TABLE: {table.title}]\n{table.markdown}"
                children.append(RawChild(
                    id=f"{source}_p{page_num}_c{idx}",
                    text=combined,
                    page=page_num,
                    tables=[table],
                    diagrams=[],
                ))
            return children

        paragraphs = self._split_paragraphs(text)

        chunks = []
        for para in paragraphs:
            if len(para) > self.max_size:
                chunks.extend(self._split_on_subsections(para))
            else:
                chunks.append(para)

        balanced = self._merge_and_balance(chunks)

        used_tables = set()
        used_diagrams = set()
        children = []

        for idx, chunk_text in enumerate(balanced):
            related_tables = self._find_related_tables(
                chunk_text, page.tables, used_tables
            )
            related_diagrams = self._find_related_diagrams(
                chunk_text, page.diagrams, used_diagrams
            )

            for t in related_tables:
                used_tables.add(t.id)
            for d in related_diagrams:
                used_diagrams.add(d.id)

            combined = self._combine_content(
                chunk_text, related_tables, related_diagrams
            )

            children.append(RawChild(
                id=f"{source}_p{page_num}_c{idx}",
                text=combined,
                page=page_num,
                tables=related_tables,
                diagrams=related_diagrams,
            ))

        remaining_tables = [
            t for t in page.tables if t.id not in used_tables
        ]
        remaining_diagrams = [
            d for d in page.diagrams if d.id not in used_diagrams
        ]

        if remaining_tables or remaining_diagrams:
            if children:
                last = children[-1]
                last.tables.extend(remaining_tables)
                last.diagrams.extend(remaining_diagrams)
                last.text = self._combine_content(
                    last.text.split("\n\n[TABLE:")[0].split("\n\n[DIAGRAM:")[0],
                    last.tables,
                    last.diagrams,
                )
            else:
                combined = self._combine_content("", remaining_tables, remaining_diagrams)
                children.append(RawChild(
                    id=f"{source}_p{page_num}_c0",
                    text=combined,
                    page=page_num,
                    tables=remaining_tables,
                    diagrams=remaining_diagrams,
                ))

        return children

    def _split_paragraphs(self, text: str) -> list[str]:
        """Split text on double newlines (paragraphs)."""
        paragraphs = re.split(r"\n\s*\n", text)
        return [p.strip() for p in paragraphs if p.strip()]

    def _split_on_subsections(self, text: str) -> list[str]:
        """
        Split on subsection markers like (a), (b), (i), (ii).
        Keeps the marker with its following content.
        """
        matches = list(self.SUBSECTION_PATTERN.finditer(text))

        if not matches:
            return self._split_on_sentences(text)

        chunks = []

        if matches[0].start() > 0:
            prefix = text[:matches[0].start()].strip()
            if prefix:
                chunks.append(prefix)

        for i, match in enumerate(matches):
            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)

        result = []
        for chunk in chunks:
            if len(chunk) > self.max_size:
                result.extend(self._split_on_sentences(chunk))
            else:
                result.append(chunk)

        return result if result else [text]

    def _merge_and_balance(self, chunks: list[str]) -> list[str]:
        """Merge small chunks and ensure balanced sizes."""
        if not chunks:
            return []

        result = []
        buffer = ""

        for chunk in chunks:
            potential = (buffer + "\n\n" + chunk).strip() if buffer else chunk

            if len(potential) <= self.target_size:
                buffer = potential
            else:
                if buffer:
                    result.append(buffer)

                if len(chunk) > self.max_size:
                    result.extend(self._split_on_sentences(chunk))
                    buffer = ""
                else:
                    buffer = chunk

        if buffer:
            if result and len(buffer) < self.min_size:
                last = result[-1]
                if len(last) + len(buffer) + 2 <= self.max_size:
                    result[-1] = last + "\n\n" + buffer
                else:
                    result.append(buffer)
            else:
                result.append(buffer)

        return result

    def _split_on_sentences(self, text: str) -> list[str]:
        """Split on sentence boundaries for oversized chunks."""
        sentences = re.split(r"(?<=[.;:!?])\s+", text)

        if len(sentences) <= 1:
            if len(text) > self.max_size:
                mid = len(text) // 2
                space_pos = text.find(" ", mid)
                if space_pos == -1:
                    space_pos = mid
                return [text[:space_pos].strip(), text[space_pos:].strip()]
            return [text]

        chunks = []
        current = ""

        for sentence in sentences:
            potential = (current + " " + sentence).strip() if current else sentence

            if len(potential) <= self.target_size:
                current = potential
            else:
                if current:
                    chunks.append(current)
                current = sentence

        if current:
            chunks.append(current)

        return chunks if chunks else [text]

    def _find_related_tables(
        self,
        text: str,
        tables: list[ExtractedTable],
        used: set,
    ) -> list[ExtractedTable]:
        """Find tables related to this chunk by content overlap."""
        if not tables:
            return []

        text_lower = text.lower()
        related = []

        for table in tables:
            if table.id in used:
                continue

            for col in table.columns:
                if col and len(col) > 2 and col.lower() in text_lower:
                    related.append(table)
                    break

        return related

    def _find_related_diagrams(
        self,
        text: str,
        diagrams: list[ExtractedDiagram],
        used: set,
    ) -> list[ExtractedDiagram]:
        """Find diagrams related to this chunk."""
        if not diagrams:
            return []

        text_lower = text.lower()

        has_ref = any(kw in text_lower for kw in self.DIAGRAM_KEYWORDS)
        if not has_ref:
            return []

        return [d for d in diagrams if d.id not in used]

    def _combine_content(
        self,
        text: str,
        tables: list[ExtractedTable],
        diagrams: list[ExtractedDiagram],
    ) -> str:
        """Combine text with table markdown and diagram descriptions."""
        parts = [text] if text else []

        for table in tables:
            parts.append(f"[TABLE: {table.title}]\n{table.markdown}")

        for diagram in diagrams:
            desc = diagram.description or "Planning diagram"
            parts.append(f"[DIAGRAM: {diagram.title}]\n{desc}")

        return "\n\n".join(parts)
