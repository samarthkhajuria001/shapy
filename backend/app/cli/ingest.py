"""CLI for ingesting PDF documents into the indexing system."""

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from app.config import get_settings
from app.services.indexing import (
    IndexingInfrastructure,
    PDFExtractor,
    SemanticChunker,
    LLMEnricher,
    ParentGrouper,
    StorageLayer,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class IngestionPipeline:
    """
    Orchestrate the full PDF ingestion pipeline.

    Pipeline stages:
    1. PDFExtractor: Extract text, tables, diagrams from PDF
    2. SemanticChunker: Split into semantic children
    3. LLMEnricher: Add tags, xrefs, section IDs
    4. ParentGrouper: Group into parent context windows
    5. StorageLayer: Store in ChromaDB, Redis, BM25
    """

    def __init__(self, infrastructure: IndexingInfrastructure):
        self.infra = infrastructure
        self.extractor = PDFExtractor(infrastructure.openai_client)
        self.chunker = SemanticChunker()
        self.enricher = LLMEnricher(infrastructure.openai_client)
        self.grouper = ParentGrouper()
        self.storage = StorageLayer(infrastructure)

    async def initialize(self, collection_name: Optional[str] = None) -> None:
        """Initialize storage layer."""
        await self.storage.initialize(collection_name)

    async def ingest_pdf(
        self,
        pdf_path: str,
        rebuild_bm25: bool = True,
    ) -> dict:
        """
        Ingest a single PDF through the full pipeline.

        Args:
            pdf_path: Path to PDF file
            rebuild_bm25: Whether to rebuild BM25 index after storage

        Returns:
            Dict with ingestion statistics
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        source = path.stem
        logger.info(f"Starting ingestion: {path.name}")

        stats = {
            "source": source,
            "pdf_path": str(path),
            "pages": 0,
            "children": 0,
            "parents": 0,
            "references": 0,
        }

        logger.info("Stage 1/5: Extracting PDF content...")
        pages = await self.extractor.extract_pdf(str(path))
        stats["pages"] = len(pages)
        logger.info(f"  Extracted {len(pages)} pages")

        logger.info("Stage 2/5: Chunking into semantic units...")
        raw_children = self.chunker.chunk_pages(pages, source)
        logger.info(f"  Created {len(raw_children)} chunks")

        logger.info("Stage 3/5: Enriching with LLM metadata...")
        enriched_children = await self.enricher.enrich_children(raw_children)
        logger.info(f"  Enriched {len(enriched_children)} children")

        logger.info("Stage 4/5: Grouping into parent windows...")
        children_with_parents, parents = self.grouper.group_children(
            enriched_children, source
        )
        stats["children"] = len(children_with_parents)
        stats["parents"] = len(parents)
        logger.info(f"  Created {len(parents)} parents")

        logger.info("Stage 5/5: Storing in databases...")
        await self.storage.store_children(
            children_with_parents,
            rebuild_bm25=rebuild_bm25,
        )
        await self.storage.store_parents(parents)
        ref_count = await self.storage.build_reference_index(children_with_parents)
        stats["references"] = ref_count
        logger.info(f"  Stored {stats['children']} children, {stats['parents']} parents")
        logger.info(f"  Built {ref_count} reference entries")

        logger.info(f"Ingestion complete: {path.name}")
        return stats

    async def ingest_multiple(
        self,
        pdf_paths: list[str],
    ) -> list[dict]:
        """
        Ingest multiple PDFs, rebuilding BM25 once at the end.

        Args:
            pdf_paths: List of PDF file paths

        Returns:
            List of stats dicts for each PDF
        """
        all_stats = []

        for i, pdf_path in enumerate(pdf_paths):
            is_last = i == len(pdf_paths) - 1
            logger.info(f"\n{'='*60}")
            logger.info(f"Processing PDF {i+1}/{len(pdf_paths)}: {Path(pdf_path).name}")
            logger.info(f"{'='*60}")

            try:
                stats = await self.ingest_pdf(
                    pdf_path,
                    rebuild_bm25=is_last,
                )
                all_stats.append(stats)

            except Exception as e:
                logger.error(f"Failed to ingest {pdf_path}: {e}")
                all_stats.append({
                    "source": Path(pdf_path).stem,
                    "pdf_path": pdf_path,
                    "error": str(e),
                })

        return all_stats


async def run_ingestion(
    pdf_paths: list[str],
    collection: Optional[str] = None,
    clear_existing: bool = False,
) -> None:
    """
    Run the ingestion pipeline.

    Args:
        pdf_paths: List of PDF file paths to ingest
        collection: ChromaDB collection name (optional)
        clear_existing: Whether to clear existing data before ingestion
    """
    infrastructure = IndexingInfrastructure()

    try:
        logger.info("Connecting to infrastructure...")
        await infrastructure.connect()

        health = await infrastructure.health_check()
        logger.info(f"Infrastructure health: {health}")

        pipeline = IngestionPipeline(infrastructure)
        await pipeline.initialize(collection)

        if clear_existing:
            logger.info("Clearing existing data...")
            await pipeline.storage.clear_all()
            logger.info("Existing data cleared")

        all_stats = await pipeline.ingest_multiple(pdf_paths)

        logger.info("\n" + "="*60)
        logger.info("INGESTION SUMMARY")
        logger.info("="*60)

        total_pages = 0
        total_children = 0
        total_parents = 0
        total_refs = 0
        errors = 0

        for stats in all_stats:
            if "error" in stats:
                errors += 1
                logger.error(f"  {stats['source']}: FAILED - {stats['error']}")
            else:
                total_pages += stats["pages"]
                total_children += stats["children"]
                total_parents += stats["parents"]
                total_refs += stats["references"]
                logger.info(
                    f"  {stats['source']}: {stats['pages']} pages, "
                    f"{stats['children']} children, {stats['parents']} parents"
                )

        logger.info("-"*60)
        logger.info(f"Total: {len(pdf_paths)} PDFs, {total_pages} pages")
        logger.info(f"       {total_children} children, {total_parents} parents")
        logger.info(f"       {total_refs} reference entries")
        if errors:
            logger.warning(f"       {errors} failed")

    finally:
        await infrastructure.disconnect()
        logger.info("Infrastructure disconnected")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ingest PDF documents into the Shapy indexing system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m app.cli.ingest document.pdf
  python -m app.cli.ingest doc1.pdf doc2.pdf doc3.pdf
  python -m app.cli.ingest --clear docs/*.pdf
  python -m app.cli.ingest --collection my_docs document.pdf
        """,
    )

    parser.add_argument(
        "pdfs",
        nargs="+",
        help="PDF files to ingest",
    )

    parser.add_argument(
        "--collection",
        "-c",
        help="ChromaDB collection name (default: from settings)",
    )

    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing data before ingestion",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    valid_paths = []
    for pdf_path in args.pdfs:
        path = Path(pdf_path)
        if not path.exists():
            logger.error(f"File not found: {pdf_path}")
            continue
        if path.suffix.lower() != ".pdf":
            logger.warning(f"Skipping non-PDF file: {pdf_path}")
            continue
        valid_paths.append(str(path.resolve()))

    if not valid_paths:
        logger.error("No valid PDF files provided")
        sys.exit(1)

    logger.info(f"Found {len(valid_paths)} PDF files to ingest")

    try:
        asyncio.run(run_ingestion(
            pdf_paths=valid_paths,
            collection=args.collection,
            clear_existing=args.clear,
        ))
    except KeyboardInterrupt:
        logger.info("\nIngestion interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
