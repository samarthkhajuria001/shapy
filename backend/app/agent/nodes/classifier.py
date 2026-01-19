"""Classifier node for determining query type and intent."""

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.agent.state import (
    AgentState,
    ClarificationQuestion,
    MissingInfoType,
    QueryType,
    add_reasoning_step,
)

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = """Classify this user query for a UK planning permission assistant.

Query: {query}
Has Drawing Uploaded: {has_drawing}

Categories:
1. GENERAL - Conceptual questions about planning permission
   Examples: "What is permitted development?", "Do I need permission for a shed?"

2. LEGAL_SEARCH - Questions about specific rules, limits, or requirements
   Examples: "What's the max height for extensions?", "Can I build in a conservation area?"

3. COMPLIANCE_CHECK - Questions checking if a specific plan complies with rules
   Examples: "Is my 4m extension legal?", "Does my drawing meet the 50% rule?"
   Note: Requires a drawing to be uploaded

4. CALCULATION - Requests for specific measurements or calculations
   Examples: "Calculate the coverage percentage", "What's the distance to boundary?"
   Note: Requires a drawing to be uploaded

Respond with JSON only:
{{
    "query_type": "GENERAL" | "LEGAL_SEARCH" | "COMPLIANCE_CHECK" | "CALCULATION",
    "intent": "Brief description of what the user wants (max 20 words)",
    "requires_drawing": true | false,
    "confidence": "high" | "medium" | "low"
}}"""

GENERAL_PHRASE_PATTERNS = [
    "what is ", "what are ", "what does ", "what do ",
    "explain ", "define ", "meaning of ", "tell me about ",
    "how does ", "why do ", "why is ", "who needs ",
]

COMPLIANCE_KEYWORDS = [
    "comply", "compliant", "compliance",
    "is my", "does my", "will my", "would my",
    "check if", "check my", "check the",
    "meet the", "within the", "exceed",
    "under the limit", "over the limit",
    "allowed to", "can i build", "can i extend",
]

CALCULATION_KEYWORDS = [
    "calculate", "measure", "compute",
    "how much area", "how far", "how tall",
    "distance to", "coverage percentage",
]

LEGAL_SEARCH_KEYWORDS = [
    "what is the max", "what is the limit", "what is the rule",
    "maximum", "minimum", "limit for", "allowed height",
    "permitted depth", "can you build",
]


def _keyword_classify(query: str, has_drawing: bool) -> tuple[QueryType, str]:
    """Fallback keyword-based classification with proper priority."""
    query_lower = query.lower()

    # Priority 1: Check for definitional/explanatory questions FIRST
    # These take precedence even if they contain words like "permitted"
    for pattern in GENERAL_PHRASE_PATTERNS:
        if query_lower.startswith(pattern) or f" {pattern}" in query_lower:
            # But exclude "what is the max/limit" which is a legal search
            if not any(lk in query_lower for lk in ["what is the max", "what is the limit", "what is the rule"]):
                return QueryType.GENERAL, "general question about planning concepts"

    # Priority 2: Explicit calculation requests
    if any(kw in query_lower for kw in CALCULATION_KEYWORDS):
        if has_drawing:
            return QueryType.CALCULATION, "calculate requested measurement"
        return QueryType.LEGAL_SEARCH, "question about measurements (no drawing)"

    # Priority 3: Compliance check patterns (requires drawing context)
    if any(kw in query_lower for kw in COMPLIANCE_KEYWORDS):
        if has_drawing:
            return QueryType.COMPLIANCE_CHECK, "check compliance of drawing"
        return QueryType.LEGAL_SEARCH, "question about compliance rules"

    # Priority 4: Legal search for specific rules/limits
    if any(kw in query_lower for kw in LEGAL_SEARCH_KEYWORDS):
        return QueryType.LEGAL_SEARCH, "question about specific planning rules"

    # Default: legal search for anything planning-related
    return QueryType.LEGAL_SEARCH, "question about planning rules"


def _parse_llm_response(response_text: str) -> dict[str, Any] | None:
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = response_text.strip()

    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    elif text.startswith("{"):
        pass
    else:
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1:
            text = text[brace_start:brace_end + 1]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def classifier_node(
    state: AgentState,
    openai_client: AsyncOpenAI | None = None,
) -> dict[str, Any]:
    """
    Classify the user's query to determine processing path.

    Args:
        state: Current agent state with user_query and drawing_context
        openai_client: Optional OpenAI client (uses default if not provided)

    Returns:
        State updates with query_type, query_intent, and potentially missing_info
    """
    settings = get_settings()

    query = state.get("user_query", "")
    if not query:
        return {
            "query_type": QueryType.GENERAL.value,
            "query_intent": "empty query",
            "errors": state.get("errors", []) + ["Empty query provided"],
        }

    drawing_ctx = state.get("drawing_context")
    has_drawing = bool(drawing_ctx and drawing_ctx.get("has_drawing", False))

    query_type: QueryType
    intent: str
    classification_method = "keyword"

    if openai_client:
        try:
            prompt = CLASSIFIER_PROMPT.format(
                query=query,
                has_drawing=has_drawing,
            )

            response = await openai_client.chat.completions.create(
                model=settings.agent_classifier_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )

            result = _parse_llm_response(response.choices[0].message.content or "")

            if result and "query_type" in result:
                type_str = result["query_type"].upper()
                try:
                    query_type = QueryType(type_str.lower())
                except ValueError:
                    query_type, intent = _keyword_classify(query, has_drawing)
                else:
                    intent = result.get("intent", "")
                    classification_method = "llm"

                logger.debug(f"LLM classified as {query_type.value}: {intent}")
            else:
                query_type, intent = _keyword_classify(query, has_drawing)
                logger.debug(f"LLM parse failed, keyword fallback: {query_type.value}")

        except Exception as e:
            logger.warning(f"Classification LLM call failed: {e}")
            query_type, intent = _keyword_classify(query, has_drawing)
    else:
        query_type, intent = _keyword_classify(query, has_drawing)

    updates: dict[str, Any] = {
        "query_type": query_type.value,
        "query_intent": intent,
        "reasoning_chain": add_reasoning_step(
            state,
            f"Classified as {query_type.value} ({classification_method}): {intent}",
        ),
    }

    requires_drawing = query_type in {
        QueryType.COMPLIANCE_CHECK,
        QueryType.CALCULATION,
    }

    if requires_drawing and not has_drawing:
        missing = list(state.get("missing_info", []))
        if MissingInfoType.DRAWING.value not in missing:
            missing.append(MissingInfoType.DRAWING.value)

        questions = list(state.get("clarification_questions", []))
        if not any(q.get("id") == "missing_drawing" for q in questions):
            questions.append(
                ClarificationQuestion(
                    id="missing_drawing",
                    question=(
                        "I need your site plan to answer this question. "
                        "Could you upload a drawing showing your property layout?"
                    ),
                    why_needed=(
                        "Compliance checks and calculations require geometric "
                        "data from your drawing to determine measurements and limits."
                    ),
                    field_name="has_drawing",
                    priority=1,
                ).model_dump()
            )

        updates["missing_info"] = missing
        updates["clarification_questions"] = questions
        updates["reasoning_chain"] = add_reasoning_step(
            state,
            "Drawing required but not uploaded - flagged for clarification",
        )

    return updates
