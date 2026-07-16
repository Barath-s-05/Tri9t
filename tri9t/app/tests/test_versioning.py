"""Unit tests for Stage 3 — versioning, node matching, diff, and impact."""

import pytest

from tri9t.app.services.diff_engine import (
    ChangeType,
    FieldChange,
    NodeDiff,
    compute_diff,
    _summarize_field_change,
)
from tri9t.app.services.impact_analyzer import (
    ImpactLevel,
    classify_impact,
    _text_looks_like_typo,
)
from tri9t.app.services.node_hasher import compute_content_hash
from tri9t.app.services.node_matcher import (
    MATCH_THRESHOLD,
    _heading_similarity,
    _section_number_match,
    _position_match,
    _compute_match_score,
    match_nodes,
)


# ── Node matching: heading similarity ──────────────────────────────


class TestHeadingSimilarity:
    """Tests for heading similarity scoring."""

    def test_identical_headings(self) -> None:
        assert _heading_similarity("Introduction", "Introduction") == 1.0

    def test_case_insensitive(self) -> None:
        score = _heading_similarity("Introduction", "INTRODUCTION")
        assert score == 1.0

    def test_similar_headings(self) -> None:
        score = _heading_similarity("System Overview", "System Overview Section")
        assert 0.5 < score < 1.0

    def test_different_headings(self) -> None:
        score = _heading_similarity("Battery Life", "Emergency Shutdown")
        assert score < 0.3


# ── Node matching: section number ──────────────────────────────────


class TestSectionNumberMatch:
    """Tests for section number matching."""

    def test_exact_match(self) -> None:
        assert _section_number_match("1.2.3", "1.2.3") == 1.0

    def test_no_match(self) -> None:
        assert _section_number_match("1.2", "1.3") == 0.0

    def test_both_none(self) -> None:
        assert _section_number_match(None, None) == 1.0

    def test_one_none(self) -> None:
        assert _section_number_match("1.2", None) == 0.0


# ── Node matching: position ────────────────────────────────────────


class TestPositionMatch:
    """Tests for tree position scoring."""

    def test_same_level(self) -> None:
        assert _position_match(2, 2) == 1.0

    def test_one_off(self) -> None:
        assert _position_match(2, 3) == 0.75

    def test_far_apart(self) -> None:
        assert _position_match(1, 5) == 0.0


# ── Node matching: full match ──────────────────────────────────────


class TestNodeMatching:
    """Tests for the full multi-factor matching pipeline."""

    def test_exact_match_reuses_logical_id(self) -> None:
        """Identical nodes should be matched and reuse the old logical ID."""
        old_lid = "logical-aaa"
        old = [
            {
                "id": "old-1",
                "heading": "1.2 Battery",
                "section_number": "1.2",
                "parent_id": "old-0",
                "level": 2,
                "content_hash": "abc",
                "logical_node_id": old_lid,
            }
        ]
        new = [
            {
                "id": "new-1",
                "heading": "1.2 Battery",
                "section_number": "1.2",
                "parent_id": "new-0",
                "level": 2,
                "content_hash": "abc",
                "_parent_heading": "",
            }
        ]
        results = match_nodes(old, new, old_parent_map={})
        assert len(results) == 1
        assert results[0].logical_node_id == old_lid
        assert results[0].is_new is False

    def test_no_match_creates_new_logical_id(self) -> None:
        """Completely different nodes should get a new logical ID."""
        old = [
            {
                "id": "old-1",
                "heading": "1. Battery",
                "section_number": "1",
                "parent_id": None,
                "level": 1,
                "content_hash": "aaa",
                "logical_node_id": "logical-aaa",
            }
        ]
        new = [
            {
                "id": "new-1",
                "heading": "5. Emergency",
                "section_number": "5",
                "parent_id": None,
                "level": 1,
                "content_hash": "zzz",
                "_parent_heading": "",
            }
        ]
        results = match_nodes(old, new, old_parent_map={})
        assert len(results) == 1
        assert results[0].is_new is True
        assert results[0].logical_node_id != "logical-aaa"

    def test_score_above_threshold_matches(self) -> None:
        """A slightly modified node should still match above threshold."""
        old = [
            {
                "id": "old-1",
                "heading": "Battery Capacity",
                "section_number": "2.1",
                "parent_id": "old-0",
                "level": 2,
                "content_hash": "aaa",
                "logical_node_id": "log-1",
            }
        ]
        new = [
            {
                "id": "new-1",
                "heading": "Battery Capacity",
                "section_number": "2.1",
                "parent_id": "new-0",
                "level": 2,
                "content_hash": "bbb",
                "_parent_heading": "",
            }
        ]
        results = match_nodes(old, new, old_parent_map={})
        assert results[0].is_new is False
        assert results[0].score >= MATCH_THRESHOLD


# ── Logical node preservation ──────────────────────────────────────


class TestLogicalNodePreservation:
    """Tests that logical_node_id survives across matched nodes."""

    def test_preserved_on_body_change(self) -> None:
        """Body text change should not create a new logical node."""
        old = [
            {
                "id": "old-1",
                "heading": "1.2 Threshold",
                "section_number": "1.2",
                "parent_id": None,
                "level": 2,
                "content_hash": "hash-old",
                "logical_node_id": "persistent-id",
            }
        ]
        new = [
            {
                "id": "new-1",
                "heading": "1.2 Threshold",
                "section_number": "1.2",
                "parent_id": None,
                "level": 2,
                "content_hash": "hash-new",
                "_parent_heading": "",
            }
        ]
        results = match_nodes(old, new, old_parent_map={})
        assert results[0].logical_node_id == "persistent-id"

    def test_preserved_on_heading_minor_edit(self) -> None:
        """Minor heading edit should still preserve logical node."""
        old = [
            {
                "id": "old-1",
                "heading": "Battery Threshold",
                "section_number": "3.1",
                "parent_id": None,
                "level": 2,
                "content_hash": "h1",
                "logical_node_id": "log-bat",
            }
        ]
        new = [
            {
                "id": "new-1",
                "heading": "Battery Thresholds",
                "section_number": "3.1",
                "parent_id": None,
                "level": 2,
                "content_hash": "h2",
                "_parent_heading": "",
            }
        ]
        results = match_nodes(old, new, old_parent_map={})
        assert results[0].logical_node_id == "log-bat"
        assert results[0].is_new is False


# ── Hash change detection ──────────────────────────────────────────


class TestHashChanges:
    """Tests for content hash change detection in diff engine."""

    def test_same_hash_unchanged(self) -> None:
        """Identical hashes yield UNCHANGED diff."""
        pairs = [{"logical_node_id": "l1", "old_node_id": "o1", "new_node_id": "n1"}]
        old_map = {"o1": {"heading": "H", "content_hash": "abc", "body_text": "", "level": 1}}
        new_map = {"n1": {"heading": "H", "content_hash": "abc", "body_text": "", "level": 1}}
        diffs = compute_diff(pairs, old_map, new_map)
        assert diffs[0].change_type == ChangeType.UNCHANGED

    def test_different_hash_modified(self) -> None:
        """Different hashes yield MODIFIED diff."""
        pairs = [{"logical_node_id": "l1", "old_node_id": "o1", "new_node_id": "n1"}]
        old_map = {
            "o1": {
                "heading": "Title",
                "content_hash": "old-hash",
                "body_text": "Old body",
                "level": 1,
                "section_number": "1",
            }
        }
        new_map = {
            "n1": {
                "heading": "Title",
                "content_hash": "new-hash",
                "body_text": "New body text",
                "level": 1,
                "section_number": "1",
            }
        }
        diffs = compute_diff(pairs, old_map, new_map)
        assert diffs[0].change_type == ChangeType.MODIFIED
        assert diffs[0].old_hash == "old-hash"
        assert diffs[0].new_hash == "new-hash"

    def test_added_node(self) -> None:
        """Node with no old_id is classified as ADDED."""
        pairs = [{"logical_node_id": "l1", "old_node_id": None, "new_node_id": "n1"}]
        new_map = {"n1": {"heading": "New", "content_hash": "h", "body_text": "", "level": 1}}
        diffs = compute_diff(pairs, {}, new_map)
        assert diffs[0].change_type == ChangeType.ADDED


# ── Diff summaries ─────────────────────────────────────────────────


class TestDiffSummaries:
    """Tests for human-readable diff summaries."""

    def test_heading_change_summary(self) -> None:
        fc = FieldChange(field_name="heading", old_value="Old Title", new_value="New Title")
        summary = _summarize_field_change(fc)
        assert "Old Title" in summary
        assert "New Title" in summary

    def test_body_change_generates_summary(self) -> None:
        pairs = [{"logical_node_id": "l1", "old_node_id": "o1", "new_node_id": "n1"}]
        old_map = {
            "o1": {
                "heading": "H",
                "content_hash": "h1",
                "body_text": "Battery threshold: 15%",
                "level": 1,
                "section_number": "1",
            }
        }
        new_map = {
            "n1": {
                "heading": "H",
                "content_hash": "h2",
                "body_text": "Battery threshold: 10%",
                "level": 1,
                "section_number": "1",
            }
        }
        diffs = compute_diff(pairs, old_map, new_map)
        assert len(diffs[0].summaries) > 0
        assert any("15%" in s for s in diffs[0].summaries)
        assert any("10%" in s for s in diffs[0].summaries)


# ── Impact analysis ────────────────────────────────────────────────


class TestImpactAnalysis:
    """Tests for change impact classification."""

    def test_safety_keywords_are_critical(self) -> None:
        level = classify_impact(
            heading="Emergency Shutdown",
            body_text="Activates emergency shutdown when temperature exceeds limit",
            changed_fields=[{"field_name": "body_text", "old_value": "The system activates normally", "new_value": "Activates emergency shutdown when temperature exceeds limit"}],
        )
        assert level == ImpactLevel.CRITICAL

    def test_measurement_keywords_are_high(self) -> None:
        level = classify_impact(
            heading="Pressure Threshold",
            body_text="Default threshold set to 200 kPa",
            changed_fields=[{"field_name": "body_text", "old_value": "Default threshold set to 150 kPa", "new_value": "Default threshold set to 200 kPa"}],
        )
        assert level == ImpactLevel.HIGH

    def test_battery_keywords_are_medium(self) -> None:
        level = classify_impact(
            heading="Runtime Estimate",
            body_text="Battery capacity is 4500 mAh",
            changed_fields=[{"field_name": "body_text", "old_value": "Battery capacity is 3000 mAh", "new_value": "Battery capacity is 4500 mAh"}],
        )
        assert level == ImpactLevel.MEDIUM

    def test_typo_change_is_low(self) -> None:
        level = classify_impact(
            heading="Overview",
            body_text="This sectoin describes the system",
            changed_fields=[{"field_name": "body_text", "old_value": "This section describes the system", "new_value": "This sectoin describes the system"}],
        )
        assert level == ImpactLevel.LOW


# ── Typo detection ─────────────────────────────────────────────────


class TestTypoDetection:
    """Tests for the typo-heuristic helper."""

    def test_single_char_change_detected(self) -> None:
        assert _text_looks_like_typo("section", "sectoin") is True

    def test_long_change_not_typo(self) -> None:
        assert _text_looks_like_typo("battery", "emergency shutdown") is False


# ── Score computation ──────────────────────────────────────────────


class TestScoreComputation:
    """Tests for the weighted score computation."""

    def test_perfect_match_scores_high(self) -> None:
        from tri9t.app.services.node_matcher import MatchCandidate

        cand = MatchCandidate(
            node_id="o1",
            logical_node_id="l1",
            heading="Battery",
            section_number="2.1",
            parent_heading="Systems",
            level=2,
            content_hash="h",
        )
        score = _compute_match_score(cand, "Battery", "2.1", "Systems", 2)
        assert score >= 0.95

    def test_different_node_scores_low(self) -> None:
        from tri9t.app.services.node_matcher import MatchCandidate

        cand = MatchCandidate(
            node_id="o1",
            logical_node_id="l1",
            heading="Battery",
            section_number="2.1",
            parent_heading="Systems",
            level=2,
            content_hash="h",
        )
        score = _compute_match_score(cand, "Emergency", "5.3", "Safety", 1)
        assert score < MATCH_THRESHOLD
