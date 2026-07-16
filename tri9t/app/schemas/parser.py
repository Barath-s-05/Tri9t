"""Pydantic schemas for parsed document data."""

from dataclasses import dataclass, field


@dataclass
class ParsedBlock:
    """A raw text block extracted from a single PDF page."""

    text: str
    page_number: int
    font_size: float
    is_bold: bool
    x0: float
    y0: float


@dataclass
class ParsedNode:
    """A single node in the parsed document tree before storage."""

    heading: str
    level: int
    body_text: str = ""
    parent_id: str | None = None
    id: str = ""
    page_number: int = 0
    section_number: str | None = None
    content_hash: str = ""
    node_type: str = "section"


@dataclass
class ParserReport:
    """Report generated after parsing a document."""

    pages_processed: int = 0
    nodes_created: int = 0
    headings_detected: int = 0
    tables_detected: int = 0
    lists_detected: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    processing_time_ms: float = 0.0

    def to_dict(self) -> dict:
        """Convert report to dictionary for API response."""
        return {
            "pages_processed": self.pages_processed,
            "nodes_created": self.nodes_created,
            "headings_detected": self.headings_detected,
            "tables_detected": self.tables_detected,
            "lists_detected": self.lists_detected,
            "warnings": self.warnings,
            "errors": self.errors,
            "processing_time_ms": self.processing_time_ms,
        }
