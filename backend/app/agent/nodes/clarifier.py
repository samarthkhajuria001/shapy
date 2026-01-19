"""Clarifier node for generating user-friendly clarification questions."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.agent.state import (
    AgentState,
    add_reasoning_step,
)

logger = logging.getLogger(__name__)


CLARIFIER_PROMPT = """You are helping a user understand why we need certain information for their UK planning permission question.

User's original question: {query}

We need to clarify the following to give an accurate answer:

{questions_formatted}

Generate a friendly, conversational message that:
1. Acknowledges their question briefly
2. Explains why each piece of information matters for their specific query
3. Presents the questions clearly (numbered if multiple)
4. Makes it easy for them to respond

Keep it concise but helpful. Use plain language, not legal jargon.
Do not use bullet points for the main response - use numbered questions if multiple.

Format: Just the message text, no JSON or special formatting."""


FALLBACK_TEMPLATE = """To give you an accurate answer about your planning question, I need a bit more information:

{questions_text}

This will help me check the specific rules that apply to your situation."""


def _format_questions_for_prompt(questions: list[dict]) -> str:
    """Format clarification questions for the LLM prompt."""
    parts = []

    for i, q in enumerate(questions, 1):
        question_text = q.get("question", "")
        why_needed = q.get("why_needed", "")
        options = q.get("options", [])

        part = f"Question {i}:\n- Question: {question_text}\n- Why needed: {why_needed}"

        if options:
            option_labels = [opt.get("label", opt.get("value", "")) for opt in options]
            part += f"\n- Options: {', '.join(option_labels)}"

        parts.append(part)

    return "\n\n".join(parts)


def _format_fallback_message(questions: list[dict]) -> str:
    """Generate a fallback message without LLM if needed."""
    question_texts = []

    for i, q in enumerate(questions, 1):
        text = q.get("question", "Unknown question")
        options = q.get("options", [])

        question_part = f"{i}. {text}"

        if options:
            option_labels = [opt.get("label", "") for opt in options]
            question_part += f"\n   Options: {', '.join(option_labels)}"

        question_texts.append(question_part)

    return FALLBACK_TEMPLATE.format(questions_text="\n\n".join(question_texts))


def _parse_llm_response(response_text: str) -> str:
    """Clean up LLM response text."""
    text = response_text.strip()

    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    elif text.startswith("'") and text.endswith("'"):
        text = text[1:-1]

    text = text.replace("\\n", "\n")

    return text.strip()


async def clarifier_node(
    state: AgentState,
    openai_client: AsyncOpenAI | None = None,
) -> dict[str, Any]:
    """
    Generate user-friendly clarification questions.

    Takes the structured clarification questions from the state and formats
    them into a natural, conversational message for the user.

    Args:
        state: Current agent state with clarification_questions
        openai_client: Optional OpenAI client for LLM generation

    Returns:
        State updates with final_answer containing the clarification request
    """
    questions = state.get("clarification_questions", [])
    query = state.get("user_query", "")

    unanswered = [
        q for q in questions
        if not q.get("answered", False)
    ]

    if not unanswered:
        logger.warning("Clarifier called with no unanswered questions")
        return {
            "final_answer": "I have all the information I need. Let me process your question.",
            "awaiting_clarification": False,
            "reasoning_chain": add_reasoning_step(
                state,
                "No questions to ask, proceeding",
            ),
        }

    questions_to_ask = unanswered[:3]

    settings = get_settings()
    clarification_message: str

    if openai_client:
        try:
            questions_formatted = _format_questions_for_prompt(questions_to_ask)

            prompt = CLARIFIER_PROMPT.format(
                query=query,
                questions_formatted=questions_formatted,
            )

            response = await openai_client.chat.completions.create(
                model=settings.agent_clarifier_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=500,
            )

            raw_response = response.choices[0].message.content or ""
            clarification_message = _parse_llm_response(raw_response)

            logger.debug("Generated clarification message via LLM")

        except Exception as e:
            logger.warning(f"Clarifier LLM call failed: {e}")
            clarification_message = _format_fallback_message(questions_to_ask)
    else:
        clarification_message = _format_fallback_message(questions_to_ask)

    for q in questions_to_ask:
        from datetime import datetime, timezone
        q["asked_at"] = datetime.now(timezone.utc).isoformat()

    return {
        "final_answer": clarification_message,
        "awaiting_clarification": True,
        "clarification_questions": questions,
        "reasoning_chain": add_reasoning_step(
            state,
            f"Generated clarification request with {len(questions_to_ask)} questions",
        ),
    }


def parse_clarification_response(
    user_response: str,
    questions: list[dict],
) -> dict[str, Any]:
    """
    Parse a user's response to clarification questions.

    Attempts to match the response to the pending questions and extract values.

    Args:
        user_response: The user's text response
        questions: List of clarification question dicts

    Returns:
        Dict mapping field_name to parsed value
    """
    updates: dict[str, Any] = {}
    response_lower = user_response.lower().strip()

    for question in questions:
        if question.get("answered", False):
            continue

        field_name = question.get("field_name", "")
        options = question.get("options", [])

        if options:
            for opt in options:
                opt_label = opt.get("label", "").lower()
                opt_value = opt.get("value", "")

                if opt_label in response_lower or opt_value.lower() in response_lower:
                    if opt_value in ("true", "false"):
                        updates[field_name] = opt_value == "true"
                    elif opt_value == "unknown":
                        updates[field_name] = None
                    else:
                        updates[field_name] = opt_value

                    question["answered"] = True
                    question["raw_answer"] = user_response
                    question["parsed_value"] = updates[field_name]
                    break
        else:
            numbers = re.findall(r"(\d+(?:\.\d+)?)", response_lower)
            if numbers and field_name in ("prior_extensions_sqm", "year_of_prior_extension"):
                value = float(numbers[0])
                if field_name == "year_of_prior_extension":
                    value = int(value)
                updates[field_name] = value
                question["answered"] = True
                question["raw_answer"] = user_response
                question["parsed_value"] = value

    return updates
