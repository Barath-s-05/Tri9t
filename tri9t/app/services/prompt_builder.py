"""Prompt construction for QA test case generation.

Assembles system, developer, and user prompts from a versioned
template.  The template lives in ``PROMPT_TEMPLATE`` and is
explicitly *not* buried in business logic, making it easy to
review, version, and override.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template – single source of truth.
# Bump ``version`` whenever the system or developer text changes.
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE: dict[str, str] = {
    "version": "1.0",
    "system": (
        "You are an expert QA engineer specializing in technical "
        "documentation analysis.  Your task is to generate comprehensive "
        "test cases based on the provided document content."
    ),
    "developer": (
        "You must generate test cases in the following JSON format:\n"
        "{\n"
        '  "test_cases": [\n'
        "    {\n"
        '      "title": "Test case title",\n'
        '      "preconditions": "Preconditions for the test",\n'
        '      "steps": ["Step 1", "Step 2"],\n'
        '      "expected_result": "Expected outcome",\n'
        '      "priority": "P1",\n'
        '      "traceability": ["Section 1.2"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Requirements:\n"
        "- Generate between 3 and 5 test cases\n"
        "- Each test case must have all required fields\n"
        "- Focus on boundary conditions, error scenarios, and edge cases\n"
        "- Test cases should be traceable to specific document sections\n"
        "- Return ONLY valid JSON, no additional text or markdown"
    ),
}

# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass
class PromptSet:
    """Fully assembled prompt ready for the LLM."""

    system_prompt: str
    developer_prompt: str
    user_prompt: str
    prompt_version: str
    prompt_hash: str  # SHA-256 of the complete prompt content


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def reconstruct_text(nodes: list) -> str:
    """Recreate a readable text representation from document nodes.

    Nodes are ordered by ``(page_number, section_number)`` to
    approximate the original document flow.
    """
    ordered = sorted(
        nodes,
        key=lambda n: (n.page_number or 0, n.section_number or ""),
    )
    parts: list[str] = []
    for node in ordered:
        heading_prefix = f"{node.section_number} " if node.section_number else ""
        parts.append(f"{heading_prefix}{node.heading}")
        if node.body_text:
            parts.append(node.body_text)
    return "\n\n".join(parts)


def _hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_prompt(nodes: list) -> PromptSet:
    """Build a versioned prompt set from the selected document nodes.

    Args:
        nodes: Iterable of node-like objects with ``heading``,
            ``body_text``, ``level``, ``section_number``, and
            ``page_number`` attributes.

    Returns:
        A ``PromptSet`` containing the three prompt sections, the
        template version, and a SHA-256 hash of the complete prompt.
    """
    text = reconstruct_text(nodes)
    system = PROMPT_TEMPLATE["system"]
    developer = PROMPT_TEMPLATE["developer"]
    user = (
        "Analyze the following document content and generate test "
        "cases:\n\n" + text
    )

    full_content = system + developer + user
    prompt_hash = _hash(full_content)

    prompt = PromptSet(
        system_prompt=system,
        developer_prompt=developer,
        user_prompt=user,
        prompt_version=PROMPT_TEMPLATE["version"],
        prompt_hash=prompt_hash,
    )

    logger.info(
        "Built prompt v%s (hash=%s…, nodes=%d)",
        prompt.prompt_version,
        prompt.prompt_hash[:12],
        len(nodes),
    )
    return prompt
