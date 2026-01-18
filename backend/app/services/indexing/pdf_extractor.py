"""Extract text, tables, and diagrams from PDF files."""

import base64
import io
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pdfplumber
from openai import AsyncOpenAI
from PIL import Image

from app.config import get_settings
from app.core.exceptions import PDFExtractionError

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    """Metadata and content of an extracted table."""

    id: str
    page: int
    title: str
    summary: str
    columns: list[str]
    row_count: int
    markdown: str


@dataclass
class ExtractedDiagram:
    """Metadata from Vision LLM analysis of a diagram."""

    id: str
    page: int
    title: str
    description: str
    visual_elements: list[str]
    rule_illustrated: str


@dataclass
class PageContent:
    """Extracted content from a single PDF page."""

    page_num: int
    text: str
    tables: list[ExtractedTable] = field(default_factory=list)
    diagrams: list[ExtractedDiagram] = field(default_factory=list)


DIAGRAM_VISION_PROMPT = """You are analyzing a diagram from a UK planning permission document about Permitted Development Rights.

NEARBY TEXT CONTEXT:
{nearby_text}

Analyze this diagram and extract:

1. TITLE: A brief descriptive title (5-10 words) that captures what this diagram shows
2. DESCRIPTION: What does this diagram illustrate? How should someone interpret or apply it? (2-3 sentences, be specific about measurements or rules shown)
3. VISUAL_ELEMENTS: List 3-5 key visual elements shown (e.g., "rear wall", "4m measurement arrow", "boundary line")
4. RULE_ILLUSTRATED: What specific planning rule or concept does this illustrate? (e.g., "Class A.1(f) rear extension depth limits")

Return ONLY valid JSON in this exact format:
{{"title": "...", "description": "...", "visual_elements": ["...", "..."], "rule_illustrated": "..."}}"""


class PDFExtractor:
    """
    Extract structured content from PDF files.

    Handles text, tables, and diagrams with Vision LLM description.
    """

    UNICODE_REPLACEMENTS = {
        "\u2013": "-",   # en-dash
        "\u2014": "-",   # em-dash
        "\u2015": "-",   # horizontal bar
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2026": "...", # ellipsis
        "\u00a0": " ",   # non-breaking space
        "\u00ad": "",    # soft hyphen
        "\t": " ",       # tab to space
        "\r": "\n",      # carriage return to newline
    }

    DIAGRAM_PATTERNS = [
        r"(?:as\s+shown|see|refer\s+to)\s+(?:the\s+)?(?:diagram|figure|illustration)",
        r"(?:diagram|figure)\s+\d+",
        r"(?:in\s+the|below|above|opposite)\s+(?:diagram|figure)",
        r"(?:the\s+)?(?:diagram|figure)\s+(?:shows|illustrates|demonstrates)",
        r"(?:shown|illustrated)\s+(?:in|by)\s+(?:the\s+)?(?:diagram|figure)",
    ]

    MIN_IMAGE_SIZE = 50
    MAX_IMAGE_DIMENSION = 1024
    IMAGE_QUALITY = 85

    def __init__(self, openai_client: AsyncOpenAI):
        self.openai_client = openai_client
        self._settings = get_settings()

    def normalize_text(self, text: str) -> str:
        """Normalize unicode characters for consistent processing."""
        if not text:
            return ""

        for old, new in self.UNICODE_REPLACEMENTS.items():
            text = text.replace(old, new)

        text = re.sub(r" +", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text.strip()

    async def extract_pdf(self, pdf_path: str) -> list[PageContent]:
        """
        Extract all content from a PDF file.

        Args:
            pdf_path: Path to the PDF file

        Returns:
            List of PageContent objects, one per page

        Raises:
            PDFExtractionError: If PDF cannot be opened or is invalid
        """
        path = Path(pdf_path)
        if not path.exists():
            raise PDFExtractionError(f"PDF file not found: {pdf_path}")

        pages = []

        try:
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
                logger.info(f"Processing PDF with {total_pages} pages: {path.name}")

                for page in pdf.pages:
                    try:
                        page_content = await self._extract_page(page)
                        pages.append(page_content)
                    except Exception as e:
                        logger.warning(
                            f"Failed to extract page {page.page_number}: {e}"
                        )
                        pages.append(PageContent(
                            page_num=page.page_number,
                            text="",
                            tables=[],
                            diagrams=[],
                        ))

        except pdfplumber.pdfminer.pdfparser.PDFSyntaxError as e:
            raise PDFExtractionError(f"Invalid PDF syntax: {e}")
        except Exception as e:
            raise PDFExtractionError(f"Failed to open PDF: {e}")

        logger.info(
            f"Extracted {len(pages)} pages, "
            f"{sum(len(p.tables) for p in pages)} tables, "
            f"{sum(len(p.diagrams) for p in pages)} diagrams"
        )

        return pages

    async def _extract_page(self, page) -> PageContent:
        """Extract content from a single page."""
        page_num = page.page_number

        raw_text = page.extract_text() or ""
        text = self.normalize_text(raw_text)

        tables = self._extract_tables(page)

        diagrams = []
        if self._has_diagram_reference(text):
            diagrams = await self._extract_diagrams(page, text)

        return PageContent(
            page_num=page_num,
            text=text,
            tables=tables,
            diagrams=diagrams,
        )

    def _extract_tables(self, page) -> list[ExtractedTable]:
        """Extract tables and convert to markdown format."""
        tables = []

        try:
            raw_tables = page.extract_tables()
        except Exception as e:
            logger.warning(f"Table extraction failed on page {page.page_number}: {e}")
            return []

        for idx, table_data in enumerate(raw_tables):
            if not table_data or len(table_data) < 2:
                continue

            headers = []
            for h in table_data[0]:
                cell = str(h).strip() if h else ""
                headers.append(cell)

            if not any(headers):
                continue

            rows = table_data[1:]
            valid_rows = []
            for row in rows:
                if row and any(cell for cell in row if cell):
                    valid_rows.append(row)

            if not valid_rows:
                continue

            markdown = self._table_to_markdown(headers, valid_rows)
            title = self._infer_table_title(headers, valid_rows)
            summary = self._generate_table_summary(headers, valid_rows)

            tables.append(ExtractedTable(
                id=f"table_p{page.page_number}_{idx}",
                page=page.page_number,
                title=title,
                summary=summary,
                columns=headers,
                row_count=len(valid_rows),
                markdown=markdown,
            ))

        return tables

    def _table_to_markdown(
        self,
        headers: list[str],
        rows: list[list[Any]],
    ) -> str:
        """Convert table data to markdown format."""
        lines = []

        header_line = "| " + " | ".join(h or "" for h in headers) + " |"
        lines.append(header_line)

        separator = "| " + " | ".join("---" for _ in headers) + " |"
        lines.append(separator)

        for row in rows:
            cells = []
            for i, cell in enumerate(row):
                if i >= len(headers):
                    break
                cell_str = str(cell).strip() if cell else ""
                cell_str = cell_str.replace("|", "\\|")
                cell_str = cell_str.replace("\n", " ")
                cells.append(cell_str)

            while len(cells) < len(headers):
                cells.append("")

            row_line = "| " + " | ".join(cells) + " |"
            lines.append(row_line)

        return "\n".join(lines)

    def _infer_table_title(
        self,
        headers: list[str],
        rows: list[list[Any]],
    ) -> str:
        """Infer a descriptive title from table content."""
        meaningful_headers = [h for h in headers if h and len(h) > 1]

        if meaningful_headers:
            if len(meaningful_headers) <= 3:
                return f"Table: {', '.join(meaningful_headers)}"
            return f"Table: {', '.join(meaningful_headers[:2])} and more"

        return "Data Table"

    def _generate_table_summary(
        self,
        headers: list[str],
        rows: list[list[Any]],
    ) -> str:
        """Generate a brief summary of table content."""
        col_count = len([h for h in headers if h])
        row_count = len(rows)

        meaningful_headers = [h for h in headers if h and len(h) > 1]
        if meaningful_headers:
            header_desc = ", ".join(meaningful_headers[:3])
            return f"{row_count} rows covering: {header_desc}"

        return f"Table with {row_count} rows and {col_count} columns"

    def _has_diagram_reference(self, text: str) -> bool:
        """Check if text contains references to diagrams."""
        if not text:
            return False

        text_lower = text.lower()
        return any(
            re.search(pattern, text_lower)
            for pattern in self.DIAGRAM_PATTERNS
        )

    async def _extract_diagrams(
        self,
        page,
        nearby_text: str,
    ) -> list[ExtractedDiagram]:
        """Extract and describe diagrams using Vision LLM."""
        diagrams = []

        try:
            images = page.images
        except Exception as e:
            logger.warning(f"Image extraction failed on page {page.page_number}: {e}")
            return []

        for idx, img_info in enumerate(images):
            width = img_info.get("width", 0)
            height = img_info.get("height", 0)

            if "x0" in img_info and "x1" in img_info:
                width = img_info["x1"] - img_info["x0"]
            if "top" in img_info and "bottom" in img_info:
                height = img_info["bottom"] - img_info["top"]

            if width < self.MIN_IMAGE_SIZE or height < self.MIN_IMAGE_SIZE:
                continue

            try:
                img_base64 = self._extract_image_base64(page, img_info)
                if not img_base64:
                    continue

                context_snippet = nearby_text[:800] if nearby_text else ""
                description = await self._describe_diagram(
                    img_base64,
                    context_snippet,
                )

                if description:
                    diagrams.append(ExtractedDiagram(
                        id=f"diag_p{page.page_number}_{idx}",
                        page=page.page_number,
                        title=description.get("title", "Diagram"),
                        description=description.get("description", ""),
                        visual_elements=description.get("visual_elements", []),
                        rule_illustrated=description.get("rule_illustrated", ""),
                    ))

            except Exception as e:
                logger.warning(
                    f"Failed to process diagram {idx} on page {page.page_number}: {e}"
                )

        return diagrams

    def _extract_image_base64(self, page, img_info: dict) -> Optional[str]:
        """Extract image from page and convert to base64."""
        try:
            x0 = img_info.get("x0", 0)
            top = img_info.get("top", 0)
            x1 = img_info.get("x1", x0 + 100)
            bottom = img_info.get("bottom", top + 100)

            x0 = max(0, x0 - 5)
            top = max(0, top - 5)
            x1 = min(page.width, x1 + 5)
            bottom = min(page.height, bottom + 5)

            cropped_page = page.within_bbox((x0, top, x1, bottom))
            img = cropped_page.to_image(resolution=150)

            pil_image = img.original

            if pil_image.width > self.MAX_IMAGE_DIMENSION or \
               pil_image.height > self.MAX_IMAGE_DIMENSION:
                pil_image.thumbnail(
                    (self.MAX_IMAGE_DIMENSION, self.MAX_IMAGE_DIMENSION),
                    Image.Resampling.LANCZOS,
                )

            if pil_image.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", pil_image.size, (255, 255, 255))
                if pil_image.mode == "P":
                    pil_image = pil_image.convert("RGBA")
                background.paste(
                    pil_image,
                    mask=pil_image.split()[-1] if pil_image.mode == "RGBA" else None,
                )
                pil_image = background

            buffer = io.BytesIO()
            pil_image.save(buffer, format="PNG", optimize=True)
            buffer.seek(0)

            return base64.b64encode(buffer.getvalue()).decode("utf-8")

        except Exception as e:
            logger.debug(f"Image extraction failed: {e}")
            return None

    async def _describe_diagram(
        self,
        img_base64: str,
        nearby_text: str,
    ) -> Optional[dict]:
        """Use Vision LLM to describe a diagram."""
        try:
            prompt = DIAGRAM_VISION_PROMPT.format(
                nearby_text=nearby_text or "No context available"
            )

            response = await self.openai_client.chat.completions.create(
                model=self._settings.vision_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{img_base64}",
                                "detail": "high",
                            },
                        },
                    ],
                }],
                max_tokens=500,
                temperature=0,
            )

            content = response.choices[0].message.content
            if not content:
                return None

            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            result = json.loads(content)

            if not isinstance(result.get("visual_elements"), list):
                result["visual_elements"] = []

            return result

        except json.JSONDecodeError as e:
            logger.warning(f"Vision LLM returned invalid JSON: {e}")
            return None
        except Exception as e:
            logger.warning(f"Vision LLM call failed: {e}")
            return None
