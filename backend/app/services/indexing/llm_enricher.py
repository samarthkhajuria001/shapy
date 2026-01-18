"""Enrich children with tags, cross-references, and definitions using LLM."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from .pdf_extractor import ExtractedTable, ExtractedDiagram
from .semantic_chunker import RawChild

logger = logging.getLogger(__name__)


@dataclass
class EnrichedChild:
    """A child with LLM-generated enrichments."""

    id: str
    text: str
    enriched_text: str
    page: int

    section: Optional[str]
    xrefs: list[str]
    tags: list[str]
    uses_definitions: list[str]
    diagram_context: str
    table_context: str

    tables: list[ExtractedTable] = field(default_factory=list)
    diagrams: list[ExtractedDiagram] = field(default_factory=list)

    parent_id: Optional[str] = None


ENRICHMENT_PROMPT = """You are improving search retrieval for UK planning permission documents (Permitted Development Rights).

Analyze this text and extract metadata for search indexing.

TEXT CHUNK:
{text}

Extract the following (be precise and consistent):

1. TAGS: 6-8 search terms using this STANDARD VOCABULARY:
   Heights: "height limit", "maximum height", "Xm height" (e.g., "4m height")
   Depths: "depth limit", "rear extension depth", "Xm depth"
   Widths: "width limit", "side extension", "half width rule"
   Areas: "area limit", "50% coverage", "curtilage area"
   Boundaries: "boundary distance", "2m boundary rule"
   Include specific measurements like "4 metre limit", "3m extension"
   Include Class references: "Class A", "Class B", "A.1(f)"

2. XREFS: Cross-references to other sections. Look for:
   - "subject to paragraph (g)" in section A.1 -> "A.1.g"
   - "conditions in A.3" -> "A.3"
   - "see Class B" -> "B"
   - "paragraph (ii)" in A.2 -> "A.2.ii"
   Return normalized format: uppercase class, lowercase subsection, dots as separators.

3. SECTION: If this text DEFINES a section, what is it? (e.g., "A.1.f", "B.2.a")
   Return null if this is not a section definition.

4. USES_DEFINITIONS: Only include if the rule DEPENDS on these legal terms:
   - "original dwellinghouse" (if distinguishing original vs extended)
   - "curtilage" (if discussing plot coverage)
   - "principal elevation" (if referencing front/highway-facing)
   - "article 2(3) land" (if special restrictions apply)
   Do NOT include common words.

5. DIAGRAM_CONTEXT: If [DIAGRAM: ...] appears, summarize in ONE sentence what rule it illustrates.
   Return "none" if no diagram.

6. TABLE_CONTEXT: If [TABLE: ...] appears, summarize in ONE sentence what data it provides.
   Return "none" if no table.

Return ONLY valid JSON:
{{"tags": ["tag1", "tag2"], "xrefs": ["A.1.g"], "section": "A.1.f", "uses_definitions": ["original dwellinghouse"], "diagram_context": "...", "table_context": "..."}}

If section is not applicable, use: "section": null"""


class LLMEnricher:
    """Enrich children with LLM-generated metadata for improved retrieval."""

    XREF_NORMALIZE_PATTERN = re.compile(r"[^a-zA-Z0-9.]")

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
        max_concurrent: Optional[int] = None,
    ):
        settings = get_settings()
        self.client = openai_client
        self.model = model or settings.enrichment_model
        self.batch_size = batch_size or settings.enrichment_batch_size
        self.max_concurrent = max_concurrent or settings.enrichment_max_concurrent
        self._semaphore = asyncio.Semaphore(self.max_concurrent)

    async def enrich_children(
        self,
        children: list[RawChild],
    ) -> list[EnrichedChild]:
        """
        Enrich all children with LLM-generated metadata.

        Args:
            children: List of RawChild from semantic chunker

        Returns:
            List of EnrichedChild ready for parent grouping
        """
        if not children:
            return []

        logger.info(f"Enriching {len(children)} children with {self.model}")
        results = []

        for batch_start in range(0, len(children), self.batch_size):
            batch_end = min(batch_start + self.batch_size, len(children))
            batch = children[batch_start:batch_end]

            tasks = [self._enrich_one(child) for child in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, result in enumerate(batch_results):
                child = batch[i]
                if isinstance(result, Exception):
                    logger.warning(f"Enrichment failed for {child.id}: {result}")
                    results.append(self._create_fallback(child))
                else:
                    results.append(result)

            logger.debug(f"Enriched batch {batch_start}-{batch_end}")

        success_count = sum(1 for r in results if r.tags)
        logger.info(f"Enrichment complete: {success_count}/{len(results)} successful")

        return results

    async def _enrich_one(self, child: RawChild) -> EnrichedChild:
        """Enrich a single child with LLM."""
        async with self._semaphore:
            text_for_prompt = child.text[:3000]
            prompt = ENRICHMENT_PROMPT.format(text=text_for_prompt)

            for attempt in range(3):
                try:
                    response = await self.client.chat.completions.create(
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0,
                        max_tokens=600,
                        response_format={"type": "json_object"},
                    )

                    content = response.choices[0].message.content
                    if not content:
                        raise ValueError("Empty response from LLM")

                    data = self._parse_response(content)
                    return self._build_enriched_child(child, data)

                except Exception as e:
                    if attempt < 2:
                        wait_time = (attempt + 1) * 2
                        logger.debug(f"Retry {attempt + 1} for {child.id}: {e}")
                        await asyncio.sleep(wait_time)
                    else:
                        raise

    def _parse_response(self, content: str) -> dict:
        """Parse and validate LLM response."""
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        data = json.loads(content)

        if not isinstance(data.get("tags"), list):
            data["tags"] = []
        if not isinstance(data.get("xrefs"), list):
            data["xrefs"] = []
        if not isinstance(data.get("uses_definitions"), list):
            data["uses_definitions"] = []

        data["xrefs"] = self._normalize_xrefs(data["xrefs"])

        if data.get("section"):
            data["section"] = self._normalize_section(data["section"])

        return data

    def _normalize_xrefs(self, xrefs: list) -> list[str]:
        """Normalize cross-reference format."""
        normalized = []
        for ref in xrefs:
            if not isinstance(ref, str):
                continue

            ref = ref.strip()
            if not ref:
                continue

            ref = self.XREF_NORMALIZE_PATTERN.sub("", ref)

            if ref and len(ref) <= 20:
                normalized.append(ref)

        return list(dict.fromkeys(normalized))

    def _normalize_section(self, section: str) -> Optional[str]:
        """Normalize section identifier."""
        if not section or section.lower() == "null":
            return None

        section = section.strip()
        section = self.XREF_NORMALIZE_PATTERN.sub("", section)

        return section if section else None

    def _build_enriched_child(
        self,
        child: RawChild,
        data: dict,
    ) -> EnrichedChild:
        """Build EnrichedChild from RawChild and LLM data."""
        tags = data.get("tags", [])
        tags_str = ", ".join(tags) if tags else ""

        if tags_str:
            enriched_text = f"[TAGS: {tags_str}]\n{child.text}"
        else:
            enriched_text = child.text

        return EnrichedChild(
            id=child.id,
            text=child.text,
            enriched_text=enriched_text,
            page=child.page,
            section=data.get("section"),
            xrefs=data.get("xrefs", []),
            tags=tags,
            uses_definitions=data.get("uses_definitions", []),
            diagram_context=data.get("diagram_context", "none") or "none",
            table_context=data.get("table_context", "none") or "none",
            tables=child.tables,
            diagrams=child.diagrams,
            parent_id=None,
        )

    def _create_fallback(self, child: RawChild) -> EnrichedChild:
        """Create minimal enrichment when LLM fails."""
        return EnrichedChild(
            id=child.id,
            text=child.text,
            enriched_text=child.text,
            page=child.page,
            section=None,
            xrefs=[],
            tags=[],
            uses_definitions=[],
            diagram_context="none",
            table_context="none",
            tables=child.tables,
            diagrams=child.diagrams,
            parent_id=None,
        )
