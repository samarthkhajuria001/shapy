"""Rank parents by aggregating child match scores."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from app.config import get_settings
from .hybrid_searcher import MatchedChild

logger = logging.getLogger(__name__)


@dataclass
class RankedParent:
    """A parent ranked by aggregated child scores."""

    id: str
    score: float
    match_count: int
    best_similarity: float
    children: list[MatchedChild] = field(default_factory=list)
    xrefs: list[str] = field(default_factory=list)


class ParentRanker:
    """
    Aggregate child matches into parent rankings.

    Scoring formula:
    - match_count_normalized: Number of children matched / max matches across all parents
    - best_similarity: Highest RRF score among matched children
    - Final score: (match_count_normalized × 0.4) + (best_similarity × 0.6)

    This balances breadth (many children matched) with depth (strong individual matches).
    """

    MATCH_COUNT_WEIGHT = 0.4
    SIMILARITY_WEIGHT = 0.6

    def rank(
        self,
        matched_children: list[MatchedChild],
        top_n: Optional[int] = None,
    ) -> list[RankedParent]:
        """
        Rank parents by aggregating their children's match scores.

        Args:
            matched_children: List of MatchedChild from HybridSearcher
            top_n: Number of top parents to return (default from settings)

        Returns:
            List of RankedParent sorted by score descending
        """
        settings = get_settings()
        top_n = top_n or settings.retrieval_top_n_parents

        if not matched_children:
            return []

        parent_groups: dict[str, list[MatchedChild]] = {}

        for child in matched_children:
            if not child.parent_id:
                continue

            if child.parent_id not in parent_groups:
                parent_groups[child.parent_id] = []
            parent_groups[child.parent_id].append(child)

        if not parent_groups:
            logger.debug("No children with parent_id found")
            return []

        max_match_count = max(len(children) for children in parent_groups.values())

        ranked = []
        for parent_id, children in parent_groups.items():
            match_count = len(children)
            best_similarity = max(c.rrf_score for c in children)

            match_count_normalized = match_count / max_match_count if max_match_count > 0 else 0

            score = (
                (match_count_normalized * self.MATCH_COUNT_WEIGHT)
                + (best_similarity * self.SIMILARITY_WEIGHT)
            )

            all_xrefs = set()
            for child in children:
                all_xrefs.update(child.xrefs)

            ranked.append(RankedParent(
                id=parent_id,
                score=score,
                match_count=match_count,
                best_similarity=best_similarity,
                children=children,
                xrefs=list(all_xrefs),
            ))

        ranked.sort(key=lambda x: -x.score)

        result = ranked[:top_n]

        logger.debug(
            f"Ranked {len(parent_groups)} parents, returning top {len(result)}"
        )

        return result
