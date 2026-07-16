"""PDF text extraction and heading detection."""

from __future__ import annotations

import logging
import re
from typing import Any

import fitz  # PyMuPDF

from tri9t.app.schemas.parser import ParsedBlock, ParsedNode

logger = logging.getLogger(__name__)

# Patterns for section numbering detection
_NUM_PATTERNS = [
    re.compile(r"^(\d+(?:\.\d+)*)\s"),          # "1.2 " or "1.2.3 "
    re.compile(r"^(\d+(?:\.\d+)*)\.?\s*$"),      # "1.2" or "1.2."
    re.compile(r"^(\d+(?:\.\d+)*)\.\s+"),        # "1.2. " with trailing dot
]


def _extract_blocks(page: fitz.Page) -> list[ParsedBlock]:
    """Extract text blocks from a single PDF page with font metadata.

    Args:
        page: A PyMuPDF page object.

    Returns:
        List of ParsedBlock objects with font size and boldness info.
    """
    blocks: list[ParsedBlock] = []
    page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:  # text block
            continue

        lines = block.get("lines", [])
        for line in lines:
            spans = line.get("spans", [])
            if not spans:
                continue

            text_parts = []
            sizes = []
            bold_flags = []

            for span in spans:
                text_parts.append(span.get("text", ""))
                sizes.append(span.get("size", 0.0))
                font_name = span.get("font", "")
                bold_flags.append("Bold" in font_name or "bold" in font_name)

            full_text = "".join(text_parts).strip()
            if not full_text:
                continue

            avg_size = sum(sizes) / len(sizes) if sizes else 0.0
            is_bold = any(bold_flags)

            bbox = block.get("bbox", (0, 0, 0, 0))
            blocks.append(
                ParsedBlock(
                    text=full_text,
                    page_number=page.number + 1,
                    font_size=round(avg_size, 2),
                    is_bold=is_bold,
                    x0=bbox[0],
                    y0=bbox[1],
                )
            )

    return blocks


def _detect_section_number(text: str) -> str | None:
    """Detect and extract section numbering from text.

    Args:
        text: The text to analyze.

    Returns:
        The section number string, or None if no numbering found.
    """
    for pattern in _NUM_PATTERNS:
        match = pattern.match(text)
        if match:
            return match.group(1)
    return None


def _compute_heading_level(section_number: str) -> int:
    """Derive heading level from section numbering.

    Args:
        section_number: A string like "1.2.3".

    Returns:
        The heading level (number of dot-separated parts).
    """
    return len(section_number.split("."))


def _is_list_item(text: str) -> bool:
    """Detect if a text block is a list item.

    Args:
        text: The text to check.

    Returns:
        True if the text appears to be a list item.
    """
    list_patterns = [
        re.compile(r"^[•\-\*\+]\s"),
        re.compile(r"^\d+[\.\)]\s"),
        re.compile(r"^[a-z][\.\)]\s"),
        re.compile(r"^[ivxlc]+[\.\)]\s", re.IGNORECASE),
    ]
    return any(p.match(text) for p in list_patterns)


def _is_table_like(blocks: list[ParsedBlock], idx: int) -> bool:
    """Heuristic: detect table-like alignment of blocks on same line.

    Args:
        blocks: All parsed blocks from the page.
        idx: Index of the current block.

    Returns:
        True if the block appears part of a table.
    """
    if idx >= len(blocks) - 1:
        return False
    current = blocks[idx]
    nxt = blocks[idx + 1]
    same_line = abs(current.y0 - nxt.y0) < 3.0
    different_x = abs(current.x0 - nxt.x0) > 50.0
    return same_line and different_x


def detect_font_size_threshold(blocks: list[ParsedBlock]) -> float:
    """Determine the font size threshold for heading detection.

    Uses frequency analysis: the most common font size is body text.
    Anything significantly larger is a potential heading.

    Args:
        blocks: All parsed text blocks.

    Returns:
        Font size threshold above which text is considered a heading.
    """
    if not blocks:
        return 0.0

    size_counts: dict[float, int] = {}
    for block in blocks:
        rounded = round(block.font_size, 1)
        size_counts[rounded] = size_counts.get(rounded, 0) + 1

    if not size_counts:
        return 0.0

    body_size = max(size_counts, key=size_counts.get)

    heading_candidates = [s for s in size_counts if s > body_size]
    if heading_candidates:
        return min(heading_candidates)
    return body_size + 0.5


def parse_pdf(pdf_bytes: bytes) -> tuple[list[ParsedBlock], int, list[str]]:
    """Extract all text blocks from a PDF document.

    Args:
        pdf_bytes: Raw PDF file bytes.

    Returns:
        Tuple of (blocks, pages_processed, warnings).
    """
    warnings: list[str] = []
    all_blocks: list[ParsedBlock] = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        warnings.append(f"Failed to open PDF: {exc}")
        return [], 0, warnings

    pages_processed = len(doc)

    for page in doc:
        page_blocks = _extract_blocks(page)
        all_blocks.extend(page_blocks)

    doc.close()
    return all_blocks, pages_processed, warnings


def identify_nodes(
    blocks: list[ParsedBlock],
    pages_processed: int,
) -> tuple[list[ParsedNode], list[str]]:
    """Classify parsed blocks into heading nodes with body text.

    Uses font size, boldness, section numbering, and context to
    distinguish headings from body text.

    Args:
        blocks: Raw parsed blocks from the PDF.
        pages_processed: Total number of pages processed.

    Returns:
        Tuple of (parsed_nodes, warnings).
    """
    warnings: list[str] = []

    if not blocks:
        return [], warnings

    threshold = detect_font_size_threshold(blocks)
    nodes: list[ParsedNode] = []
    body_buffer: list[str] = []
    current_heading_node: ParsedNode | None = None

    for idx, block in enumerate(blocks):
        section_num = _detect_section_number(block.text)
        is_heading_by_number = section_num is not None
        is_heading_by_font = block.font_size > threshold + 0.5
        is_heading_by_bold = block.is_bold and block.font_size >= threshold

        is_heading = is_heading_by_number or is_heading_by_font or is_heading_by_bold

        # If numbered text but small font, only treat as heading if bold
        if is_heading_by_number and not block.is_bold and not is_heading_by_font:
            is_heading = False

        if is_heading:
            # Save accumulated body to previous node
            if current_heading_node is not None:
                current_heading_node.body_text = "\n".join(body_buffer).strip()
                body_buffer = []

            level = 1
            if section_num:
                level = _compute_heading_level(section_num)

            current_heading_node = ParsedNode(
                heading=block.text,
                level=level,
                page_number=block.page_number,
                section_number=section_num,
                node_type="section",
            )
            nodes.append(current_heading_node)
        else:
            body_buffer.append(block.text)

            # Detect list items
            if _is_list_item(block.text):
                if current_heading_node is not None:
                    current_heading_node.node_type = "section_with_list"

            # Detect tables
            if _is_table_like(blocks, idx):
                if current_heading_node is not None:
                    current_heading_node.node_type = "section_with_table"

    # Flush remaining body text
    if current_heading_node is not None:
        current_heading_node.body_text = "\n".join(body_buffer).strip()
    elif body_buffer:
        # No headings found — create a single root node from all content
        nodes.append(
            ParsedNode(
                heading="Document Content",
                level=1,
                body_text="\n".join(body_buffer).strip(),
                page_number=1,
                node_type="section",
            )
        )

    return nodes, warnings
