"""Agent state schema for LangGraph workflow.

Defines the complete state structure that flows through the AI agent,
including drawing context, retrieved rules, assumptions, and clarifications.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class QueryType(str, Enum):
    """Classification of user queries."""

    GENERAL = "general"
    LEGAL_SEARCH = "legal_search"
    COMPLIANCE_CHECK = "compliance_check"
    CALCULATION = "calculation"
    CLARIFICATION_RESPONSE = "clarification_response"


class MissingInfoType(str, Enum):
    """Types of information that might be missing for compliance checks."""

    DRAWING = "drawing"
    HOUSE_TYPE = "house_type"
    DESIGNATED_LAND = "designated_land"
    ORIGINAL_HOUSE = "original_house"
    PRIOR_EXTENSIONS = "prior_extensions"
    MEASUREMENTS = "measurements"
    ARTICLE_4 = "article_4"


class HouseType(str, Enum):
    """Types of dwelling for regulation lookup."""

    DETACHED = "detached"
    SEMI_DETACHED = "semi-detached"
    TERRACE = "terrace"
    END_TERRACE = "end-terrace"


class DesignatedLandType(str, Enum):
    """Types of protected/designated land."""

    CONSERVATION_AREA = "conservation_area"
    NATIONAL_PARK = "national_park"
    AONB = "aonb"
    WORLD_HERITAGE = "world_heritage"
    BROADS = "broads"
    NONE = "none"


class ConfidenceLevel(str, Enum):
    """Confidence level for assumptions and answers."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AssumptionSource(str, Enum):
    """Source of an assumption."""

    USER_STATED = "user_stated"
    INFERRED = "inferred"
    DEFAULT = "default"


class DrawingContext(BaseModel):
    """Parsed context from user's JSON drawing.

    Populated from Phase 2 session data with user-provided clarifications.
    """

    session_id: str
    has_drawing: bool = False

    plot_area_sqm: Optional[float] = Field(
        None,
        description="Total plot/curtilage area in square metres",
    )
    building_footprint_sqm: Optional[float] = Field(
        None,
        description="Current building footprint in square metres",
    )
    building_height_m: Optional[float] = Field(
        None,
        description="Building height in metres",
    )
    eaves_height_m: Optional[float] = Field(
        None,
        description="Eaves height in metres",
    )
    ridge_height_m: Optional[float] = Field(
        None,
        description="Ridge height in metres",
    )

    distance_to_boundary_m: Optional[float] = Field(
        None,
        description="Minimum distance to any boundary in metres",
    )
    distance_to_rear_boundary_m: Optional[float] = Field(
        None,
        description="Distance to rear boundary in metres",
    )
    distance_to_highway_m: Optional[float] = Field(
        None,
        description="Distance to highway/road in metres",
    )
    fronts_highway: Optional[bool] = Field(
        None,
        description="Whether building fronts a highway",
    )

    house_type: Optional[HouseType] = Field(
        None,
        description="Type of dwelling (detached, semi, terrace)",
    )
    is_original_house: Optional[bool] = Field(
        None,
        description="Whether this is the original house as built (temporal check)",
    )
    prior_extensions_sqm: Optional[float] = Field(
        None,
        description="Area of previous extensions in square metres",
    )
    year_of_prior_extension: Optional[int] = Field(
        None,
        description="Year of most recent prior extension",
    )
    designated_land_type: Optional[DesignatedLandType] = Field(
        None,
        description="Type of designated/protected land, if any",
    )
    article_4_direction: Optional[bool] = Field(
        None,
        description="Whether Article 4 direction applies",
    )

    layers_present: list[str] = Field(
        default_factory=list,
        description="Layer names present in the drawing",
    )

    class Config:
        use_enum_values = True


class Assumption(BaseModel):
    """An assumption the AI is making due to missing information."""

    id: str = Field(..., description="Unique identifier for this assumption")
    description: str = Field(..., description="Human-readable description")
    field_name: str = Field(
        ...,
        description="DrawingContext field this assumption relates to",
    )
    assumed_value: Any = Field(..., description="The value being assumed")
    confidence: ConfidenceLevel = Field(
        default=ConfidenceLevel.MEDIUM,
        description="Confidence in this assumption",
    )
    source: AssumptionSource = Field(
        default=AssumptionSource.DEFAULT,
        description="How this assumption was derived",
    )
    affects_rules: list[str] = Field(
        default_factory=list,
        description="Rule sections affected by this assumption",
    )
    can_invalidate_answer: bool = Field(
        default=True,
        description="Whether changing this could change the answer",
    )

    class Config:
        use_enum_values = True


class ClarificationOption(BaseModel):
    """An option for a clarification question."""

    label: str
    value: str
    description: Optional[str] = None


class ClarificationQuestion(BaseModel):
    """A question to ask the user for clarification."""

    id: str = Field(..., description="Unique identifier for tracking")
    question: str = Field(..., description="The question text")
    why_needed: str = Field(
        ...,
        description="Explanation of why this information is needed",
    )
    field_name: str = Field(
        ...,
        description="DrawingContext field this will populate",
    )
    options: Optional[list[ClarificationOption]] = Field(
        None,
        description="Multiple choice options, if applicable",
    )
    priority: int = Field(
        default=2,
        ge=1,
        le=3,
        description="1=must ask, 2=should ask, 3=nice to have",
    )
    affects_rules: list[str] = Field(
        default_factory=list,
        description="Rule sections that need this information",
    )

    asked_at: Optional[datetime] = None
    answered: bool = False
    raw_answer: Optional[str] = None
    parsed_value: Any = None


class RetrievedRule(BaseModel):
    """A rule retrieved from the Phase 3 knowledge base."""

    parent_id: str = Field(..., description="Parent chunk ID from storage")
    text: str = Field(..., description="Full text of the retrieved section")
    section: Optional[str] = Field(
        None,
        description="Section identifier (e.g., 'A.1.f')",
    )
    page_start: int = Field(default=0, description="Starting page number")
    page_end: int = Field(default=0, description="Ending page number")
    source: str = Field(default="", description="Source document identifier")
    relevance_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Relevance score from retrieval",
    )

    uses_definitions: list[str] = Field(
        default_factory=list,
        description="Legal definitions this rule depends on",
    )
    xrefs: list[str] = Field(
        default_factory=list,
        description="Cross-referenced sections",
    )
    sections_covered: list[str] = Field(
        default_factory=list,
        description="All section IDs covered by this parent",
    )
    has_exceptions: bool = Field(
        default=False,
        description="Whether exceptions exist for this rule",
    )
    designated_land_specific: bool = Field(
        default=False,
        description="Whether this rule is specific to designated land",
    )

    @classmethod
    def from_enhanced_parent(cls, parent_data: dict, score: float = 0.0) -> "RetrievedRule":
        """Create from Phase 3 EnhancedParent data dict."""
        content_index = parent_data.get("content_index", {})

        # Check for cross-references which indicate exceptions or related rules
        xrefs = content_index.get("xrefs", [])
        has_exceptions = bool(xrefs)

        return cls(
            parent_id=parent_data.get("id", ""),
            text=parent_data.get("text", ""),
            section=content_index.get("sections_covered", [None])[0],
            page_start=parent_data.get("page_start", 0),
            page_end=parent_data.get("page_end", 0),
            source=parent_data.get("source", ""),
            relevance_score=score,
            uses_definitions=content_index.get("definitions_used", []),
            xrefs=xrefs,
            sections_covered=content_index.get("sections_covered", []),
            has_exceptions=has_exceptions,
            designated_land_specific="article 2(3)" in parent_data.get("text", "").lower(),
        )


class CalculationResult(BaseModel):
    """Result from Phase 5 geometric calculator."""

    calculation_type: str = Field(
        ...,
        description="Type of calculation (coverage, distance, height, volume)",
    )
    input_values: dict[str, Any] = Field(
        default_factory=dict,
        description="Input values used in calculation",
    )
    result: float = Field(..., description="Calculated result value")
    unit: str = Field(..., description="Unit of measurement")

    limit: Optional[float] = Field(
        None,
        description="Regulatory limit for comparison",
    )
    limit_source: Optional[str] = Field(
        None,
        description="Source of the limit (e.g., 'Class A.1(b)')",
    )
    compliant: Optional[bool] = Field(
        None,
        description="Whether result is within limit",
    )
    margin: Optional[float] = Field(
        None,
        description="Difference from limit (positive = headroom, negative = over)",
    )
    notes: Optional[str] = Field(
        None,
        description="Additional notes about the calculation",
    )


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class ConversationTurn(BaseModel):
    """A single turn in the conversation history."""

    role: Literal["user", "assistant"]
    content: str
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentState(TypedDict, total=False):
    """Complete state for the LangGraph agent workflow.

    This TypedDict flows through all graph nodes and maintains
    the full context needed for multi-turn conversations.

    Note: Using total=False to allow partial state updates.
    LangGraph will merge updates into the existing state.
    """

    session_id: str
    conversation_id: str
    turn_number: int

    user_query: str
    query_type: str
    query_intent: str

    drawing_context: Optional[dict]
    conversation_history: list[dict]

    retrieved_rules: list[dict]
    global_definitions: dict[str, str]
    applicable_exceptions: list[dict]
    context_text: str

    calculation_results: list[dict]
    pending_calculations: list[str]

    assumptions: list[dict]
    missing_info: list[str]
    clarification_questions: list[dict]
    awaiting_clarification: bool

    reasoning_chain: list[str]
    confidence: str

    final_answer: Optional[str]
    caveats: list[str]
    suggested_followups: list[str]

    errors: list[str]
    should_escalate: bool


def create_initial_state(
    session_id: str,
    user_query: str,
    conversation_id: Optional[str] = None,
    drawing_context: Optional[DrawingContext] = None,
    conversation_history: Optional[list[ConversationTurn]] = None,
) -> AgentState:
    """Create initial agent state for a new query.

    Args:
        session_id: User's session ID from Phase 2
        user_query: The user's question
        conversation_id: Optional ID for multi-turn tracking
        drawing_context: Optional pre-loaded drawing context
        conversation_history: Optional prior conversation turns

    Returns:
        Initialized AgentState ready for graph execution
    """
    now = datetime.now(timezone.utc)
    conv_id = conversation_id or f"{session_id}_{int(now.timestamp())}"

    history_dicts = []
    if conversation_history:
        history_dicts = [turn.model_dump() for turn in conversation_history]

    context_dict = None
    if drawing_context:
        context_dict = drawing_context.model_dump()

    # Calculate turn number: each turn is a user+assistant pair
    # If history has 4 messages (user, assistant, user, assistant), that's 2 complete turns
    turn_number = (len(history_dicts) // 2) + 1

    return AgentState(
        session_id=session_id,
        conversation_id=conv_id,
        turn_number=turn_number,
        user_query=user_query,
        query_type=QueryType.GENERAL.value,
        query_intent="",
        drawing_context=context_dict,
        conversation_history=history_dicts,
        retrieved_rules=[],
        global_definitions={},
        applicable_exceptions=[],
        context_text="",
        calculation_results=[],
        pending_calculations=[],
        assumptions=[],
        missing_info=[],
        clarification_questions=[],
        awaiting_clarification=False,
        reasoning_chain=[],
        confidence=ConfidenceLevel.HIGH.value,
        final_answer=None,
        caveats=[],
        suggested_followups=[],
        errors=[],
        should_escalate=False,
    )


def add_reasoning_step(state: AgentState, step: str) -> list[str]:
    """Add a reasoning step to the chain.

    Args:
        state: Current agent state
        step: Description of the reasoning step

    Returns:
        Updated reasoning chain list
    """
    chain = list(state.get("reasoning_chain", []))
    chain.append(f"[{len(chain) + 1}] {step}")
    return chain


def get_drawing_context(state: AgentState) -> Optional[DrawingContext]:
    """Extract DrawingContext model from state dict.

    Args:
        state: Current agent state

    Returns:
        DrawingContext model or None if not present
    """
    ctx_dict = state.get("drawing_context")
    if ctx_dict is None:
        return None
    return DrawingContext.model_validate(ctx_dict)


def get_assumptions(state: AgentState) -> list[Assumption]:
    """Extract Assumption models from state dict.

    Args:
        state: Current agent state

    Returns:
        List of Assumption models
    """
    assumption_dicts = state.get("assumptions", [])
    return [Assumption.model_validate(a) for a in assumption_dicts]


def get_clarification_questions(state: AgentState) -> list[ClarificationQuestion]:
    """Extract ClarificationQuestion models from state dict.

    Args:
        state: Current agent state

    Returns:
        List of ClarificationQuestion models
    """
    question_dicts = state.get("clarification_questions", [])
    return [ClarificationQuestion.model_validate(q) for q in question_dicts]


def get_retrieved_rules(state: AgentState) -> list[RetrievedRule]:
    """Extract RetrievedRule models from state dict.

    Args:
        state: Current agent state

    Returns:
        List of RetrievedRule models
    """
    rule_dicts = state.get("retrieved_rules", [])
    return [RetrievedRule.model_validate(r) for r in rule_dicts]


def get_calculation_results(state: AgentState) -> list[CalculationResult]:
    """Extract CalculationResult models from state dict.

    Args:
        state: Current agent state

    Returns:
        List of CalculationResult models
    """
    calc_dicts = state.get("calculation_results", [])
    return [CalculationResult.model_validate(c) for c in calc_dicts]


def has_critical_missing_info(state: AgentState) -> bool:
    """Check if state has critical missing information.

    Critical missing info includes:
    - ORIGINAL_HOUSE (temporal problem)
    - DRAWING (for compliance checks)
    - HOUSE_TYPE (for limit lookups)

    Args:
        state: Current agent state

    Returns:
        True if critical info is missing
    """
    critical_types = {
        MissingInfoType.ORIGINAL_HOUSE.value,
        MissingInfoType.DRAWING.value,
        MissingInfoType.HOUSE_TYPE.value,
    }
    missing = set(state.get("missing_info", []))
    return bool(missing & critical_types)


def is_compliance_query(state: AgentState) -> bool:
    """Check if current query is a compliance check.

    Args:
        state: Current agent state

    Returns:
        True if query type is compliance check or calculation
    """
    query_type = state.get("query_type", "")
    return query_type in {
        QueryType.COMPLIANCE_CHECK.value,
        QueryType.CALCULATION.value,
    }
