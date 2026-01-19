"""Prompt templates for the Reasoner node."""

from typing import Any


REASONER_SYSTEM_PROMPT = """You are Shapy, an expert AI assistant for UK Permitted Development regulations.

Your role is to provide accurate, helpful information about what building work is allowed without full planning permission under the Town and Country Planning (General Permitted Development) (England) Order.

CRITICAL RULES:
1. ONLY cite rules that appear in the CONTEXT section below. Never invent regulations.
2. If a rule is not in the context, say "I don't have information about that specific rule."
3. NEVER use phrases like "typically", "usually", "in most cases" when stating legal rules.
4. When uncertain, say "Based on the context provided..." rather than stating as fact.
5. Do NOT extrapolate or generalize beyond the given rules.

TEMPORAL AWARENESS:
The law measures limits from the ORIGINAL house (as it was first built, or on 1st July 1948).
If you cannot confirm whether the house is original, you MUST caveat your answer.

DESIGNATED LAND AWARENESS:
Properties in Conservation Areas, National Parks, AONBs, or World Heritage Sites have STRICTER rules.
If you don't know the property's designation status, mention this limitation.

CITATION FORMAT:
When citing a rule, always include:
- The Class (e.g., "Class A")
- The specific paragraph if available (e.g., "A.1(f)")
- A brief quote or paraphrase from the actual text

RESPONSE STRUCTURE:
1. Direct Answer: Answer the question clearly
2. Legal Basis: Cite the specific rule(s) from the context
3. Calculations (if applicable): Reference any calculation results provided
4. Caveats: State any assumptions or limitations
5. Next Steps: Suggest what the user should do if appropriate"""


ANTI_HALLUCINATION_SECTION = """
GROUNDING RULES (CRITICAL):
- You can ONLY cite rules from the REGULATIONS section below
- If something is not in the regulations provided, say "I don't have information about that"
- NEVER use "typically", "usually", "generally" for legal statements
- Use exact quotes when possible
- If uncertain, express uncertainty clearly

WHAT NOT TO DO:
- "Extensions are typically limited to 3 metres" (too vague)
- "You probably can't build within 2 metres of the boundary" (uncertain language)
- "The general rule is..." (implies knowledge beyond context)

WHAT TO DO:
- "According to Class A.1(f): 'the enlargement... must not extend beyond the rear wall... by more than 4 metres in the case of a detached dwellinghouse, or 3 metres in any other case'"
- "The context does not include information about X. You should check with your local planning authority."
"""


REASONER_USER_TEMPLATE = """## USER'S QUESTION
{query}

## GLOBAL DEFINITIONS
These definitions from the legislation always apply when interpreting rules:

{definitions}

## RELEVANT REGULATIONS
The following rules were retrieved as relevant to this query:

{rules}

## EXCEPTIONS & SPECIAL CASES
{exceptions}

## DRAWING DATA
{drawing_summary}

## CALCULATION RESULTS
{calculations}

## ASSUMPTIONS MADE
{assumptions}

{anti_hallucination}

## INSTRUCTIONS
Based on the above context, provide a helpful answer to the user's question.
Remember: You can ONLY cite rules from the REGULATIONS section. Do not invent or extrapolate."""


def format_definitions(definitions: dict[str, str]) -> str:
    """Format global definitions for the prompt."""
    if not definitions:
        return "No definitions provided."

    parts = []
    for term, definition in definitions.items():
        parts.append(f"**{term}**: {definition}")

    return "\n\n".join(parts)


def format_rules_for_prompt(rules: list[dict]) -> str:
    """Format retrieved rules for the prompt."""
    if not rules:
        return "No specific rules retrieved for this query."

    parts = []
    for i, rule in enumerate(rules, 1):
        section = rule.get("section", "Unknown Section")
        page_start = rule.get("page_start", 0)
        page_end = rule.get("page_end", 0)
        text = rule.get("text", "")
        score = rule.get("relevance_score", 0.0)

        header = f"### Rule {i}: {section}"
        if page_start or page_end:
            header += f" (Pages {page_start}-{page_end})"

        uses_defs = rule.get("uses_definitions", [])
        def_note = ""
        if uses_defs:
            def_note = f"\n*Uses definitions: {', '.join(uses_defs)}*"

        designated = rule.get("designated_land_specific", False)
        designated_note = ""
        if designated:
            designated_note = "\n*Note: This rule relates to designated/protected land*"

        parts.append(f"{header}\n\n{text}{def_note}{designated_note}")

    return "\n\n---\n\n".join(parts)


def format_calculations_for_prompt(calculations: list[dict]) -> str:
    """Format calculation results for the prompt."""
    if not calculations:
        return "No calculations performed."

    parts = []
    for calc in calculations:
        calc_type = calc.get("calculation_type", "unknown")
        result = calc.get("result", 0)
        unit = calc.get("unit", "")
        limit = calc.get("limit")
        limit_source = calc.get("limit_source", "")
        compliant = calc.get("compliant")
        margin = calc.get("margin")
        notes = calc.get("notes")

        status = ""
        if compliant is not None:
            status = " COMPLIANT" if compliant else " NON-COMPLIANT"

        line = f"- **{calc_type}**: {result}{unit}"

        if limit is not None:
            line += f" (Limit: {limit}{unit}"
            if limit_source:
                line += f" per {limit_source}"
            line += ")"

        if status:
            line += f" [{status}]"

        if margin is not None:
            if margin >= 0:
                line += f" (Headroom: {margin}{unit})"
            else:
                line += f" (Over by: {abs(margin)}{unit})"

        if notes:
            line += f"\n  Note: {notes}"

        parts.append(line)

    return "\n".join(parts)


def format_drawing_summary(drawing_ctx: dict | None) -> str:
    """Format drawing context summary for the prompt."""
    if not drawing_ctx or not drawing_ctx.get("has_drawing"):
        return "No drawing uploaded."

    parts = []

    if drawing_ctx.get("plot_area_sqm"):
        parts.append(f"- Plot Area: {drawing_ctx['plot_area_sqm']}m2")

    if drawing_ctx.get("building_footprint_sqm"):
        parts.append(f"- Building Footprint: {drawing_ctx['building_footprint_sqm']}m2")

    if drawing_ctx.get("building_height_m"):
        parts.append(f"- Building Height: {drawing_ctx['building_height_m']}m")

    if drawing_ctx.get("eaves_height_m"):
        parts.append(f"- Eaves Height: {drawing_ctx['eaves_height_m']}m")

    if drawing_ctx.get("distance_to_boundary_m") is not None:
        parts.append(f"- Distance to Boundary: {drawing_ctx['distance_to_boundary_m']}m")

    house_type = drawing_ctx.get("house_type")
    if house_type:
        parts.append(f"- House Type: {house_type}")
    else:
        parts.append("- House Type: Not specified")

    is_original = drawing_ctx.get("is_original_house")
    if is_original is True:
        parts.append("- Original House: Confirmed as original")
    elif is_original is False:
        prior = drawing_ctx.get("prior_extensions_sqm")
        if prior:
            parts.append(f"- Original House: No (has {prior}m2 of prior extensions)")
        else:
            parts.append("- Original House: No (has prior extensions)")
    else:
        parts.append("- Original House: Not confirmed")

    designated = drawing_ctx.get("designated_land_type")
    if designated and designated != "none":
        parts.append(f"- Designated Land: {designated}")
    else:
        parts.append("- Designated Land: Not specified")

    layers = drawing_ctx.get("layers_present", [])
    if layers:
        parts.append(f"- Drawing Layers: {', '.join(layers)}")

    return "\n".join(parts) if parts else "Drawing uploaded but no measurements extracted."


def format_assumptions_for_prompt(assumptions: list[dict]) -> str:
    """Format assumptions for the prompt."""
    if not assumptions:
        return "No explicit assumptions made."

    parts = []
    for a in assumptions:
        desc = a.get("description", "")
        confidence = a.get("confidence", "medium")
        source = a.get("source", "default")

        line = f"- {desc}"
        line += f" (Confidence: {confidence}, Source: {source})"

        parts.append(line)

    return "\n".join(parts)


def format_exceptions_for_prompt(exceptions: list[dict]) -> str:
    """Format exception rules for the prompt."""
    if not exceptions:
        return "No specific exceptions identified."

    parts = []
    for exc in exceptions:
        section = exc.get("section", "Exception")
        text = exc.get("text", "")
        parts.append(f"**{section}**: {text}")

    return "\n\n".join(parts)


def build_reasoner_prompt(
    query: str,
    definitions: dict[str, str],
    rules: list[dict],
    exceptions: list[dict],
    drawing_ctx: dict | None,
    calculations: list[dict],
    assumptions: list[dict],
    include_anti_hallucination: bool = True,
) -> str:
    """Build the complete reasoner prompt."""
    return REASONER_USER_TEMPLATE.format(
        query=query,
        definitions=format_definitions(definitions),
        rules=format_rules_for_prompt(rules),
        exceptions=format_exceptions_for_prompt(exceptions),
        drawing_summary=format_drawing_summary(drawing_ctx),
        calculations=format_calculations_for_prompt(calculations),
        assumptions=format_assumptions_for_prompt(assumptions),
        anti_hallucination=ANTI_HALLUCINATION_SECTION if include_anti_hallucination else "",
    )
