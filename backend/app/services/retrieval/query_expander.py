"""Generate query variations for improved retrieval coverage."""

import json
import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


EXPANSION_PROMPT = """Generate 4 alternative search queries for this UK planning permission question.

ORIGINAL QUERY: "{query}"

CRITICAL RULES:
- PRESERVE all specific measurements (e.g., "4m", "3 metres", "50%") in EVERY variation
- PRESERVE all legal references (e.g., "Class A", "A.1(f)", "Part 1") in EVERY variation
- PRESERVE key constraint words (e.g., "maximum", "limit", "within")
- Only vary the phrasing/vocabulary around these key terms

Generate exactly 4 variations:
1. CASUAL_1: Homeowner phrasing (but keep measurements and legal refs)
2. CASUAL_2: Another informal phrasing (but keep measurements and legal refs)
3. TECHNICAL_1: Planning terminology (e.g., "permitted development", "curtilage")
4. TECHNICAL_2: Legal/regulatory language with section references

Example:
Original: "Can I build a 4m rear extension?"
Good: ["is 4m rear extension allowed", "4 metre back extension rules", "4m rear extension permitted development", "Class A 4m single storey rear extension limit"]
Bad: ["can I extend my house" (lost 4m), "building regulations" (too vague)]

Return ONLY valid JSON:
{{"variations": ["casual query 1", "casual query 2", "technical query 1", "technical query 2"]}}"""


class QueryExpander:
    """
    Generate query variations for hybrid search.

    Produces 5 queries total: original + 4 LLM-generated variations.
    This helps catch both colloquial and technical phrasings.
    """

    MAX_QUERY_LENGTH = 500
    MAX_VARIATION_LENGTH = 200

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        model: Optional[str] = None,
    ):
        settings = get_settings()
        self.client = openai_client
        self.model = model or settings.enrichment_model

    async def expand(self, query: str) -> list[str]:
        """
        Generate 5 query variations (original + 4 LLM-generated).

        Args:
            query: Original user query

        Returns:
            List of 5 query strings for search
        """
        if not query or not query.strip():
            return []

        query = query.strip()
        if len(query) > self.MAX_QUERY_LENGTH:
            query = query[:self.MAX_QUERY_LENGTH]

        try:
            variations = await self._generate_variations(query)
            result = [query] + variations[:4]

            while len(result) < 5:
                result.append(query)

            return result

        except Exception as e:
            logger.warning(f"Query expansion failed: {e}")
            return [query] * 5

    async def _generate_variations(self, query: str) -> list[str]:
        """Generate variations using LLM."""
        prompt = EXPANSION_PROMPT.format(query=query)

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            return []

        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        data = json.loads(content)
        raw_variations = data.get("variations", [])

        variations = []
        for v in raw_variations:
            if isinstance(v, str) and v.strip():
                clean = v.strip()
                if len(clean) > self.MAX_VARIATION_LENGTH:
                    clean = clean[:self.MAX_VARIATION_LENGTH]
                variations.append(clean)

        return variations
