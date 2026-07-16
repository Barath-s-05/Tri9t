"""Unit tests for PDF parser services."""

from tri9t.app.schemas.parser import ParsedNode
from tri9t.app.services.node_hasher import compute_content_hash
from tri9t.app.services.pdf_parser import (
    _compute_heading_level,
    _detect_section_number,
    _is_list_item,
    identify_nodes,
)
from tri9t.app.services.parser_validator import validate_tree
from tri9t.app.services.tree_builder import build_tree


# ── Hash generation ────────────────────────────────────────────────


class TestContentHash:
    """Tests for SHA-256 content hash generation."""

    def test_hash_deterministic(self) -> None:
        """Same inputs always produce the same hash."""
        h1 = compute_content_hash("Introduction", "Body text here")
        h2 = compute_content_hash("Introduction", "Body text here")
        assert h1 == h2

    def test_hash_differs_on_heading(self) -> None:
        """Different headings produce different hashes."""
        h1 = compute_content_hash("Chapter 1", "Same body")
        h2 = compute_content_hash("Chapter 2", "Same body")
        assert h1 != h2

    def test_hash_differs_on_body(self) -> None:
        """Different body text produces different hashes."""
        h1 = compute_content_hash("Same heading", "Body A")
        h2 = compute_content_hash("Same heading", "Body B")
        assert h1 != h2

    def test_hash_is_hex_string(self) -> None:
        """Hash output is a 64-character hex string."""
        h = compute_content_hash("Heading", "Body")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Section number detection ──────────────────────────────────────


class TestSectionNumberDetection:
    """Tests for section number pattern detection."""

    def test_simple_numbering(self) -> None:
        assert _detect_section_number("1 Introduction") == "1"

    def test_dot_separated_numbering(self) -> None:
        assert _detect_section_number("1.2 Background") == "1.2"

    def test_deep_numbering(self) -> None:
        assert _detect_section_number("2.1.3.1 Details") == "2.1.3.1"

    def test_no_numbering(self) -> None:
        assert _detect_section_number("General Text") is None

    def test_heading_level_from_number(self) -> None:
        assert _compute_heading_level("1") == 1
        assert _compute_heading_level("1.2") == 2
        assert _compute_heading_level("2.1.3") == 3


# ── List item detection ───────────────────────────────────────────


class TestListItemDetection:
    """Tests for list item detection."""

    def test_bullet_item(self) -> None:
        assert _is_list_item("- First item") is True

    def test_numbered_item(self) -> None:
        assert _is_list_item("1. First item") is True

    def test_alpha_item(self) -> None:
        assert _is_list_item("a. Item one") is True

    def test_plain_text(self) -> None:
        assert _is_list_item("This is a paragraph.") is False


# ── Duplicate heading detection ───────────────────────────────────


class TestDuplicateHeadings:
    """Tests for duplicate heading detection in validation."""

    def test_duplicate_headings_warning(self) -> None:
        """Validator should warn about duplicate headings."""
        nodes = [
            ParsedNode(id="1", heading="Introduction", level=1, content_hash="a"),
            ParsedNode(id="2", heading="Body", level=2, parent_id="1", content_hash="b"),
            ParsedNode(id="3", heading="Introduction", level=1, content_hash="c"),
        ]
        warnings = validate_tree(nodes)
        duplicate_warnings = [w for w in warnings if "Duplicate heading" in w]
        assert len(duplicate_warnings) == 1
        assert "Introduction" in duplicate_warnings[0]

    def test_no_duplicates_clean(self) -> None:
        """Unique headings produce no duplicate warnings."""
        nodes = [
            ParsedNode(id="1", heading="Introduction", level=1, content_hash="a"),
            ParsedNode(id="2", heading="Body", level=2, parent_id="1", content_hash="b"),
        ]
        warnings = validate_tree(nodes)
        duplicate_warnings = [w for w in warnings if "Duplicate heading" in w]
        assert len(duplicate_warnings) == 0


# ── Nested hierarchy (tree builder) ───────────────────────────────


class TestNestedHierarchy:
    """Tests for hierarchical tree building."""

    def test_flat_sections_become_tree(self) -> None:
        """Level-2 nodes nest under the preceding level-1 node."""
        nodes = [
            ParsedNode(heading="1 Intro", level=1),
            ParsedNode(heading="1.1 Background", level=2),
            ParsedNode(heading="1.2 Scope", level=2),
            ParsedNode(heading="2 Methods", level=1),
            ParsedNode(heading="2.1 Approach", level=2),
        ]
        tree, _ = build_tree(nodes)

        assert len(tree) == 5
        # 1.1 Background parent should be 1 Intro
        bg = next(n for n in tree if n.heading == "1.1 Background")
        intro = next(n for n in tree if n.heading == "1 Intro")
        assert bg.parent_id == intro.id

        # 2.1 Approach parent should be 2 Methods
        approach = next(n for n in tree if n.heading == "2.1 Approach")
        methods = next(n for n in tree if n.heading == "2 Methods")
        assert approach.parent_id == methods.id

    def test_deep_nesting(self) -> None:
        """Deeply nested headings establish correct parent chains."""
        nodes = [
            ParsedNode(heading="1 Chapter", level=1),
            ParsedNode(heading="1.1 Section", level=2),
            ParsedNode(heading="1.1.1 Sub", level=3),
        ]
        tree, _ = build_tree(nodes)

        chapter = next(n for n in tree if n.heading == "1 Chapter")
        section = next(n for n in tree if n.heading == "1.1 Section")
        sub = next(n for n in tree if n.heading == "1.1.1 Sub")

        assert chapter.parent_id is None
        assert section.parent_id == chapter.id
        assert sub.parent_id == section.id

    def test_root_injected_when_missing(self) -> None:
        """An artificial root is injected when no level-1 heading exists."""
        nodes = [
            ParsedNode(heading="1.1 Subsection", level=2),
            ParsedNode(heading="1.2 Another", level=2),
        ]
        tree, warnings = build_tree(nodes)
        assert any("injected artificial root" in w for w in warnings)
        root = next(n for n in tree if n.heading == "Root")
        assert root.level == 1


# ── Out-of-order numbering ────────────────────────────────────────


class TestOutOfOrderNumbering:
    """Tests for detecting out-of-order section numbering."""

    def test_out_of_order_warning(self) -> None:
        """Section 3.4 before 3.3 should trigger a warning."""
        nodes = [
            ParsedNode(heading="3. Overview", level=1, section_number="3"),
            ParsedNode(heading="3.4 Details", level=2, section_number="3.4"),
            ParsedNode(heading="3.3 Background", level=2, section_number="3.3"),
        ]
        warnings = validate_tree(nodes)
        jump_warnings = [w for w in warnings if "jumps from" in w]
        assert len(jump_warnings) > 0

    def test_sequential_numbering_clean(self) -> None:
        """Sequential numbering produces no jump warnings."""
        nodes = [
            ParsedNode(heading="1. Intro", level=1, section_number="1"),
            ParsedNode(heading="1.1 Background", level=2, section_number="1.1"),
            ParsedNode(heading="1.2 Scope", level=2, section_number="1.2"),
            ParsedNode(heading="1.3 Method", level=2, section_number="1.3"),
        ]
        warnings = validate_tree(nodes)
        jump_warnings = [w for w in warnings if "jumps from" in w]
        assert len(jump_warnings) == 0


# ── Skipped heading levels ────────────────────────────────────────


class TestSkippedLevels:
    """Tests for detecting skipped heading levels."""

    def test_skip_level_warning(self) -> None:
        """Jump from L1 parent to L3 child should warn."""
        nodes = [
            ParsedNode(id="1", heading="Chapter", level=1),
            ParsedNode(id="2", heading="Deep Sub", level=3, parent_id="1"),
        ]
        warnings = validate_tree(nodes)
        skip_warnings = [w for w in warnings if "Skipped heading level" in w]
        assert len(skip_warnings) == 1


# ── Mixed numbering styles ────────────────────────────────────────


class TestMixedNumbering:
    """Tests for detecting mixed numbering styles."""

    def test_mixed_alpha_numeric_warning(self) -> None:
        """Numeric and alpha numbering in same doc should warn."""
        nodes = [
            ParsedNode(heading="1. Intro", level=1, section_number="1"),
            ParsedNode(heading="1.2 Detail", level=2, section_number="1.2"),
            ParsedNode(heading="1.A Appendix", level=2, section_number="1.A"),
        ]
        warnings = validate_tree(nodes)
        mixed_warnings = [w for w in warnings if "Mixed numbering" in w]
        assert len(mixed_warnings) == 1


# ── Empty heading / missing body ──────────────────────────────────


class TestContentWarnings:
    """Tests for empty heading and missing body warnings."""

    def test_empty_heading_warning(self) -> None:
        nodes = [
            ParsedNode(id="1", heading="", level=1, content_hash="x"),
        ]
        warnings = validate_tree(nodes)
        assert any("Empty heading" in w for w in warnings)

    def test_missing_body_warning(self) -> None:
        nodes = [
            ParsedNode(id="1", heading="Intro", level=1, body_text="", content_hash="x"),
        ]
        warnings = validate_tree(nodes)
        assert any("Missing body" in w for w in warnings)


# ── Identify nodes from blocks ────────────────────────────────────


class TestIdentifyNodes:
    """Tests for heading identification from parsed blocks."""

    def test_numbered_heading_detected(self) -> None:
        """A numbered text block should be classified as a heading."""
        from tri9t.app.schemas.parser import ParsedBlock

        blocks = [
            ParsedBlock(text="1 Introduction", page_number=1, font_size=16.0, is_bold=True, x0=0, y0=0),
            ParsedBlock(text="Body text here", page_number=1, font_size=12.0, is_bold=False, x0=0, y0=30),
        ]
        nodes, _ = identify_nodes(blocks, pages_processed=1)
        assert len(nodes) == 1
        assert nodes[0].heading == "1 Introduction"
        assert nodes[0].level == 1
        assert "Body text here" in nodes[0].body_text
