"""Assumption analyzer node for detecting temporal and contextual dependencies."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from app.agent.state import (
    AgentState,
    Assumption,
    AssumptionSource,
    ClarificationOption,
    ClarificationQuestion,
    ConfidenceLevel,
    MissingInfoType,
    add_reasoning_step,
)

logger = logging.getLogger(__name__)


@dataclass
class DefinitionSpec:
    """Specification for a definition that requires user context."""

    keywords: list[str]
    field_name: str
    missing_info_type: MissingInfoType
    question: str
    why_needed: str
    options: list[ClarificationOption] | None
    priority: int
    default_value: Any
    default_confidence: ConfidenceLevel
    affects: list[str]
    caveat_if_assumed: str


TEMPORAL_DEFINITIONS: dict[str, DefinitionSpec] = {
    "original_dwellinghouse": DefinitionSpec(
        keywords=[
            "original dwellinghouse",
            "original house",
            "as first built",
            "as it stood on 1st july 1948",
            "1 july 1948",
        ],
        field_name="is_original_house",
        missing_info_type=MissingInfoType.ORIGINAL_HOUSE,
        question=(
            "Is the building shown in your drawing the original house as it was "
            "first built? Or has it been extended or modified since construction?"
        ),
        why_needed=(
            "UK planning law calculates permitted development limits from the "
            "ORIGINAL house size (as built, or as it stood on 1st July 1948). "
            "If your house has been extended before, those extensions count "
            "against your allowance."
        ),
        options=[
            ClarificationOption(
                label="Yes, this is the original house",
                value="true",
                description="The house has not been extended since it was first built",
            ),
            ClarificationOption(
                label="No, it has been extended before",
                value="false",
                description="Extensions or modifications have been made",
            ),
            ClarificationOption(
                label="I'm not sure",
                value="unknown",
                description="I don't know the building's history",
            ),
        ],
        priority=1,
        default_value=True,
        default_confidence=ConfidenceLevel.LOW,
        affects=["50% curtilage coverage", "rear extension depth", "side extension width"],
        caveat_if_assumed=(
            "This assessment assumes the drawing shows the ORIGINAL house as first built. "
            "If there have been previous extensions, your actual permitted development "
            "allowance may be less than calculated."
        ),
    ),
    "prior_extensions": DefinitionSpec(
        keywords=[
            "previous extension",
            "prior extension",
            "existing extension",
            "already extended",
            "total enlargement",
        ],
        field_name="prior_extensions_sqm",
        missing_info_type=MissingInfoType.PRIOR_EXTENSIONS,
        question=(
            "You mentioned the house has been extended before. Approximately how much "
            "floor area (in square metres) was added by previous extensions?"
        ),
        why_needed=(
            "Previous extensions count against your permitted development allowance. "
            "We need to know the total area to calculate your remaining allowance."
        ),
        options=None,
        priority=1,
        default_value=0.0,
        default_confidence=ConfidenceLevel.LOW,
        affects=["50% curtilage coverage", "total enlargement calculation"],
        caveat_if_assumed=(
            "Unable to account for previous extensions. The calculated allowance "
            "assumes no prior extensions have been made."
        ),
    ),
}

CONTEXTUAL_DEFINITIONS: dict[str, DefinitionSpec] = {
    "house_type": DefinitionSpec(
        keywords=[
            "detached dwellinghouse",
            "detached house",
            "semi-detached",
            "terrace",
            "terraced house",
            "end of terrace",
        ],
        field_name="house_type",
        missing_info_type=MissingInfoType.HOUSE_TYPE,
        question="Is your house detached, semi-detached, or terraced?",
        why_needed=(
            "Different permitted development limits apply depending on the type of house. "
            "For example, detached houses can extend further to the rear than semi-detached "
            "or terraced houses."
        ),
        options=[
            ClarificationOption(
                label="Detached",
                value="detached",
                description="Stands alone, not joined to any other building",
            ),
            ClarificationOption(
                label="Semi-detached",
                value="semi-detached",
                description="Joined to one other house on one side",
            ),
            ClarificationOption(
                label="Terraced",
                value="terrace",
                description="Joined to houses on both sides (mid-terrace)",
            ),
            ClarificationOption(
                label="End of terrace",
                value="end-terrace",
                description="End house of a terrace row",
            ),
        ],
        priority=1,
        default_value="detached",
        default_confidence=ConfidenceLevel.LOW,
        affects=["rear extension depth (4m vs 3m)", "loft conversion volume"],
        caveat_if_assumed=(
            "House type not confirmed. This assessment assumes a detached house. "
            "If your house is semi-detached or terraced, stricter limits may apply."
        ),
    ),
    "designated_land": DefinitionSpec(
        keywords=[
            "article 2(3)",
            "conservation area",
            "national park",
            "area of outstanding natural beauty",
            "aonb",
            "world heritage site",
            "the broads",
        ],
        field_name="designated_land_type",
        missing_info_type=MissingInfoType.DESIGNATED_LAND,
        question=(
            "Is your property located in any of the following protected areas: "
            "Conservation Area, National Park, Area of Outstanding Natural Beauty (AONB), "
            "World Heritage Site, or The Broads?"
        ),
        why_needed=(
            "Properties in designated areas have stricter permitted development rules. "
            "Some types of development that are normally permitted are restricted or "
            "prohibited in these areas."
        ),
        options=[
            ClarificationOption(
                label="Yes, it's in a protected area",
                value="designated",
                description="My property is in a Conservation Area, National Park, AONB, or similar",
            ),
            ClarificationOption(
                label="No, standard area",
                value="none",
                description="My property is not in a specially designated area",
            ),
            ClarificationOption(
                label="I'm not sure",
                value="unknown",
                description="I don't know if my area has special designation",
            ),
        ],
        priority=2,
        default_value="none",
        default_confidence=ConfidenceLevel.MEDIUM,
        affects=["cladding restrictions", "side extension prohibition", "roof alterations"],
        caveat_if_assumed=(
            "This assessment assumes standard (non-designated) land. If your property "
            "is in a Conservation Area, National Park, or similar, additional restrictions apply."
        ),
    ),
    "article_4": DefinitionSpec(
        keywords=[
            "article 4",
            "article 4 direction",
            "permitted development removed",
            "pd rights removed",
        ],
        field_name="article_4_direction",
        missing_info_type=MissingInfoType.ARTICLE_4,
        question=(
            "Is your property subject to an Article 4 Direction that removes "
            "permitted development rights?"
        ),
        why_needed=(
            "An Article 4 Direction can remove specific permitted development rights "
            "for properties in a defined area. If one applies, you may need planning "
            "permission for work that would normally be permitted."
        ),
        options=[
            ClarificationOption(
                label="Yes, Article 4 applies",
                value="true",
                description="An Article 4 Direction affects my property",
            ),
            ClarificationOption(
                label="No, Article 4 doesn't apply",
                value="false",
                description="No Article 4 Direction affects my property",
            ),
            ClarificationOption(
                label="I'm not sure",
                value="unknown",
                description="I don't know if Article 4 applies",
            ),
        ],
        priority=3,
        default_value=False,
        default_confidence=ConfidenceLevel.MEDIUM,
        affects=["all permitted development rights"],
        caveat_if_assumed=(
            "This assessment assumes no Article 4 Direction applies. Check with your "
            "local planning authority if you're unsure."
        ),
    ),
}


def _text_contains_definition(text: str, spec: DefinitionSpec) -> bool:
    """Check if text contains any of the definition's keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in spec.keywords)


def _get_context_value(drawing_context: dict | None, field_name: str) -> Any:
    """Get a value from drawing context, returning None if not present."""
    if not drawing_context:
        return None
    return drawing_context.get(field_name)


def _is_value_set(value: Any) -> bool:
    """Check if a context value has been meaningfully set."""
    if value is None:
        return False
    if isinstance(value, str) and value.strip() == "":
        return False
    return True


def _collect_affected_sections(rules: list[dict]) -> list[str]:
    """Collect section identifiers from rules."""
    sections = []
    for rule in rules:
        section = rule.get("section")
        if section:
            sections.append(section)
    return sections


def _question_already_exists(
    questions: list[dict],
    question_id: str,
) -> bool:
    """Check if a clarification question already exists."""
    return any(q.get("id") == question_id for q in questions)


def _assumption_already_exists(
    assumptions: list[dict],
    field_name: str,
) -> bool:
    """Check if an assumption for this field already exists."""
    return any(a.get("field_name") == field_name for a in assumptions)


async def assumption_analyzer_node(state: AgentState) -> dict[str, Any]:
    """
    Analyze retrieved rules for assumptions and missing information.

    This is the CRITICAL node for handling the temporal problem and other
    contextual dependencies. It detects when rules reference definitions
    that require user-provided context (like "original dwellinghouse").

    Processing:
    1. Scan retrieved rules for temporal and contextual definitions
    2. Check if required context is already in drawing_context
    3. Generate clarification questions for missing critical info
    4. Create explicit assumptions when proceeding without info
    5. Add caveats to warn about potential inaccuracies

    Args:
        state: Current agent state with retrieved_rules and drawing_context

    Returns:
        State updates with assumptions, missing_info, clarification_questions, caveats
    """
    retrieved_rules = state.get("retrieved_rules", [])
    drawing_context = state.get("drawing_context")
    query_type = state.get("query_type", "")

    existing_assumptions = list(state.get("assumptions", []))
    existing_missing = list(state.get("missing_info", []))
    existing_questions = list(state.get("clarification_questions", []))
    existing_caveats = list(state.get("caveats", []))

    new_assumptions: list[dict] = []
    new_missing: list[str] = []
    new_questions: list[dict] = []
    new_caveats: list[str] = []

    if not retrieved_rules:
        return {
            "reasoning_chain": add_reasoning_step(
                state,
                "No rules to analyze for assumptions",
            ),
        }

    is_compliance_check = query_type in {"compliance_check", "calculation"}

    detected_definitions: dict[str, tuple[DefinitionSpec, list[str]]] = {}

    for rule in retrieved_rules:
        uses_definitions = rule.get("uses_definitions", [])
        rule_text = rule.get("text", "")
        rule_section = rule.get("section") or "unknown"  # Handle None explicitly

        for def_key, spec in TEMPORAL_DEFINITIONS.items():
            if def_key in detected_definitions:
                detected_definitions[def_key][1].append(rule_section)
                continue

            def_name_variants = [
                "original dwellinghouse",
                "original house",
                "curtilage",
            ]
            found_in_uses = any(
                d.lower() in def_name_variants
                for d in uses_definitions
            )
            found_in_text = _text_contains_definition(rule_text, spec)

            if found_in_uses or found_in_text:
                detected_definitions[def_key] = (spec, [rule_section])

        for def_key, spec in CONTEXTUAL_DEFINITIONS.items():
            if def_key in detected_definitions:
                detected_definitions[def_key][1].append(rule_section)
                continue

            found_in_text = _text_contains_definition(rule_text, spec)

            if found_in_text:
                detected_definitions[def_key] = (spec, [rule_section])

    for def_key, (spec, affected_sections) in detected_definitions.items():
        # Filter out None values from affected_sections
        affected_sections = [s for s in affected_sections if s is not None]

        current_value = _get_context_value(drawing_context, spec.field_name)
        question_id = f"clarify_{def_key}"

        if _is_value_set(current_value):
            if not _assumption_already_exists(existing_assumptions, spec.field_name):
                new_assumptions.append(
                    Assumption(
                        id=f"confirmed_{def_key}",
                        description=f"User confirmed: {spec.field_name} = {current_value}",
                        field_name=spec.field_name,
                        assumed_value=current_value,
                        confidence=ConfidenceLevel.HIGH,
                        source=AssumptionSource.USER_STATED,
                        affects_rules=affected_sections,
                        can_invalidate_answer=False,
                    ).model_dump()
                )
            continue

        if spec.field_name == "prior_extensions_sqm":
            is_original = _get_context_value(drawing_context, "is_original_house")
            if is_original is True:
                continue
            if is_original is None:
                continue

        if spec.missing_info_type.value not in existing_missing:
            new_missing.append(spec.missing_info_type.value)

        should_ask = (
            is_compliance_check and spec.priority <= 2
        ) or spec.priority == 1

        if should_ask and not _question_already_exists(existing_questions, question_id):
            options_dicts = None
            if spec.options:
                options_dicts = [opt.model_dump() for opt in spec.options]

            new_questions.append(
                ClarificationQuestion(
                    id=question_id,
                    question=spec.question,
                    why_needed=spec.why_needed,
                    field_name=spec.field_name,
                    options=spec.options,
                    priority=spec.priority,
                    affects_rules=affected_sections,
                ).model_dump()
            )
        else:
            if not _assumption_already_exists(existing_assumptions, spec.field_name):
                new_assumptions.append(
                    Assumption(
                        id=f"assumed_{def_key}",
                        description=f"Assuming {spec.field_name} = {spec.default_value}",
                        field_name=spec.field_name,
                        assumed_value=spec.default_value,
                        confidence=spec.default_confidence,
                        source=AssumptionSource.DEFAULT,
                        affects_rules=affected_sections,
                        can_invalidate_answer=True,
                    ).model_dump()
                )

            if spec.caveat_if_assumed not in existing_caveats:
                new_caveats.append(spec.caveat_if_assumed)

    temporal_flagged = any(
        k in detected_definitions for k in TEMPORAL_DEFINITIONS
    )
    if temporal_flagged:
        is_original = _get_context_value(drawing_context, "is_original_house")
        if is_original is None:
            critical_caveat = (
                "IMPORTANT: Planning law measures limits from the ORIGINAL house. "
                "We cannot verify if your drawing shows the original building or "
                "an already-extended version."
            )
            if critical_caveat not in existing_caveats and critical_caveat not in new_caveats:
                new_caveats.insert(0, critical_caveat)

    all_assumptions = existing_assumptions + new_assumptions
    all_missing = list(set(existing_missing + new_missing))
    all_questions = existing_questions + new_questions
    all_caveats = existing_caveats + new_caveats

    reasoning_parts = []
    if detected_definitions:
        reasoning_parts.append(f"Detected {len(detected_definitions)} contextual dependencies")
    if new_questions:
        reasoning_parts.append(f"generated {len(new_questions)} clarification questions")
    if new_assumptions:
        reasoning_parts.append(f"made {len(new_assumptions)} assumptions")
    if new_caveats:
        reasoning_parts.append(f"added {len(new_caveats)} caveats")

    reasoning = "; ".join(reasoning_parts) if reasoning_parts else "No contextual issues detected"

    logger.debug(f"Assumption analysis: {reasoning}")

    return {
        "assumptions": all_assumptions,
        "missing_info": all_missing,
        "clarification_questions": all_questions,
        "caveats": all_caveats,
        "reasoning_chain": add_reasoning_step(state, f"Analyzed assumptions: {reasoning}"),
    }


def get_critical_missing_info(state: AgentState) -> list[str]:
    """
    Get list of critical missing information that should block processing.

    Critical info includes:
    - ORIGINAL_HOUSE for compliance checks
    - HOUSE_TYPE when rules depend on it
    - DRAWING for any spatial calculation

    Args:
        state: Current agent state

    Returns:
        List of critical MissingInfoType values
    """
    missing = state.get("missing_info", [])
    query_type = state.get("query_type", "")

    critical = []

    if query_type in {"compliance_check", "calculation"}:
        if MissingInfoType.DRAWING.value in missing:
            critical.append(MissingInfoType.DRAWING.value)
        if MissingInfoType.ORIGINAL_HOUSE.value in missing:
            critical.append(MissingInfoType.ORIGINAL_HOUSE.value)
        if MissingInfoType.HOUSE_TYPE.value in missing:
            critical.append(MissingInfoType.HOUSE_TYPE.value)

    return critical
