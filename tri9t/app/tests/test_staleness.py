"""Tests for staleness detection, retrieval, and new API endpoints.

All MongoDB interactions are mocked. No real database required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tri9t.app.db.base import Base
from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node
from tri9t.app.models.selection import Selection
from tri9t.app.services import staleness_service
from tri9t.app.services.staleness_service import (
    StalenessResult,
    StalenessStatus,
    check_staleness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_node(
    id: str = "n1",
    heading: str = "Intro",
    level: int = 1,
    body_text: str = "Body text.",
    section_number: str | None = "1",
    page_number: int = 1,
    content_hash: str = "abc123",
    version_id: str = "v1",
    document_id: str = "doc1",
) -> Node:
    return Node(
        id=id,
        document_id=document_id,
        version_id=version_id,
        heading=heading,
        level=level,
        body_text=body_text,
        section_number=section_number,
        page_number=page_number,
        content_hash=content_hash,
    )


def _make_version(
    id: str = "v1",
    document_id: str = "doc1",
    version_number: int = 1,
    is_latest: bool = True,
) -> DocumentVersion:
    return DocumentVersion(
        id=id,
        document_id=document_id,
        version_number=version_number,
        is_latest=is_latest,
    )


def _make_selection(
    id: str = "s1",
    name: str = "Test Selection",
    document_version_id: str = "v1",
    node_ids: list[str] | None = None,
) -> Selection:
    return Selection(
        id=id,
        selection_name=name,
        document_version_id=document_version_id,
        snapshot_hash="abc",
        node_ids=node_ids or ["n1", "n2"],
    )


def _mock_generation_doc(
    generation_id: str = "gen1",
    selection_id: str = "s1",
    version_id: str = "v1",
    node_hashes: list[str] | None = None,
) -> dict:
    return {
        "_id": generation_id,
        "selection_id": selection_id,
        "version_id": version_id,
        "node_hashes": node_hashes or ["hash_a", "hash_b"],
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "test_cases": [],
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ===================================================================
# StalenessStatus
# ===================================================================


class TestStalenessStatus:
    def test_status_values(self):
        assert StalenessStatus.CURRENT.value == "CURRENT"
        assert StalenessStatus.STALE.value == "STALE"
        assert StalenessStatus.PARTIALLY_STALE.value == "PARTIALLY_STALE"
        assert StalenessStatus.UNKNOWN.value == "UNKNOWN"

    def test_status_is_string_enum(self):
        assert isinstance(StalenessStatus.CURRENT, str)


# ===================================================================
# StalenessResult
# ===================================================================


class TestStalenessResult:
    def test_to_dict(self):
        r = StalenessResult(
            status=StalenessStatus.CURRENT,
            reason="All good",
            impact_level="LOW",
            recommendation="No action",
            total_nodes=5,
            changed_count=0,
        )
        d = r.to_dict()
        assert d["status"] == "CURRENT"
        assert d["reason"] == "All good"
        assert d["total_nodes"] == 5
        assert d["changed_count"] == 0

    def test_default_values(self):
        r = StalenessResult(
            status=StalenessStatus.UNKNOWN,
            reason="Not found",
        )
        assert r.changed_nodes == []
        assert r.changed_sections == []
        assert r.impact_level is None


# ===================================================================
# check_staleness
# ===================================================================


class TestCheckStaleness:
    def test_generation_not_found(self, db):
        with patch(
            "tri9t.app.services.staleness_service._get_generation_doc",
            return_value=None,
        ):
            result = check_staleness(db, "nonexistent")
            assert result.status == StalenessStatus.UNKNOWN
            assert "not found" in result.reason.lower()

    def test_selection_not_found(self, db):
        gen_doc = _mock_generation_doc(selection_id="bad_sel")
        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=None,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.UNKNOWN
            assert "selection not found" in result.reason.lower()

    def test_empty_node_ids(self, db):
        gen_doc = _mock_generation_doc()
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": []}
        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=sel,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.UNKNOWN
            assert "no nodes" in result.reason.lower()

    def test_document_not_found(self, db):
        gen_doc = _mock_generation_doc()
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": ["n1"]}
        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=sel,
            ),
            patch(
                "tri9t.app.services.staleness_service._find_document_id_for_version",
                return_value=None,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.UNKNOWN
            assert "cannot resolve" in result.reason.lower()

    def test_current_generation(self, db):
        """All hashes match → CURRENT."""
        node1 = _make_node("n1", content_hash="hash_a")
        node2 = _make_node("n2", content_hash="hash_b")
        db.add_all([node1, node2])
        db.commit()

        ver = _make_version("v1", "doc1", 1, True)
        db.add(ver)
        db.commit()

        gen_doc = _mock_generation_doc(
            node_hashes=["hash_a", "hash_b"]
        )
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": ["n1", "n2"]}

        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=sel,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.CURRENT
            assert result.changed_count == 0

    def test_stale_generation(self, db):
        """All hashes differ → STALE."""
        node1 = _make_node("n1", content_hash="new_a")
        node2 = _make_node("n2", content_hash="new_b")
        db.add_all([node1, node2])
        db.commit()

        ver = _make_version("v1", "doc1", 1, True)
        db.add(ver)
        db.commit()

        gen_doc = _mock_generation_doc(
            node_hashes=["old_a", "old_b"]
        )
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": ["n1", "n2"]}

        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=sel,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.STALE
            assert result.changed_count == 2

    def test_partial_staleness(self, db):
        """One hash matches, one differs → PARTIALLY_STALE."""
        node1 = _make_node("n1", content_hash="hash_a")
        node2 = _make_node("n2", content_hash="changed_b")
        db.add_all([node1, node2])
        db.commit()

        ver = _make_version("v1", "doc1", 1, True)
        db.add(ver)
        db.commit()

        gen_doc = _mock_generation_doc(
            node_hashes=["hash_a", "hash_b"]
        )
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": ["n1", "n2"]}

        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=sel,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.PARTIALLY_STALE
            assert result.changed_count == 1

    def test_newer_version_exists(self, db):
        """Hashes match but newer version exists → PARTIALLY_STALE."""
        node1 = _make_node("n1", content_hash="hash_a")
        db.add(node1)
        db.commit()

        ver_old = _make_version("v1", "doc1", 1, False)
        ver_new = _make_version("v2", "doc1", 2, True)
        db.add_all([ver_old, ver_new])
        db.commit()

        gen_doc = _mock_generation_doc(
            version_id="v1",
            node_hashes=["hash_a"],
        )
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": ["n1"]}

        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=sel,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.PARTIALLY_STALE
            assert result.latest_version_number == 2

    def test_removed_node(self, db):
        """Node no longer exists → counted as changed."""
        node1 = _make_node("n1", content_hash="hash_a")
        db.add(node1)
        db.commit()

        ver = _make_version("v1", "doc1", 1, True)
        db.add(ver)
        db.commit()

        gen_doc = _mock_generation_doc(
            node_hashes=["hash_a", "hash_b"]
        )
        sel = {"id": "s1", "document_version_id": "v1", "node_ids": ["n1", "n2"]}

        with (
            patch(
                "tri9t.app.services.staleness_service._get_generation_doc",
                return_value=gen_doc,
            ),
            patch(
                "tri9t.app.services.staleness_service.get_selection",
                return_value=sel,
            ),
        ):
            result = check_staleness(db, "gen1")
            assert result.status == StalenessStatus.PARTIALLY_STALE
            assert result.changed_count == 1
            assert result.changed_nodes[0]["change_type"] == "removed"


# ===================================================================
# Retrieval Service
# ===================================================================


class TestRetrievalService:
    def test_get_generation_with_staleness_not_found(self, db):
        from tri9t.app.services.retrieval_service import (
            get_generation_with_staleness,
        )

        with patch(
            "tri9t.app.services.retrieval_service.get_generations_collection",
        ) as mock_col:
            mock_col.return_value.find_one.return_value = None
            result = get_generation_with_staleness(db, "nonexistent")
            assert result is None

    def test_get_generation_with_staleness_found(self, db):
        from tri9t.app.services.retrieval_service import (
            get_generation_with_staleness,
        )

        gen_doc = _mock_generation_doc()

        fake_staleness = StalenessResult(
            status=StalenessStatus.CURRENT,
            reason="All nodes match",
            total_nodes=2,
            changed_count=0,
        )

        with (
            patch(
                "tri9t.app.services.retrieval_service.get_generations_collection",
            ) as mock_col,
            patch(
                "tri9t.app.services.retrieval_service.check_staleness",
                return_value=fake_staleness,
            ),
        ):
            mock_col.return_value.find_one.return_value = gen_doc
            result = get_generation_with_staleness(db, "gen1")
            assert result is not None
            assert "staleness" in result
            assert result["staleness"]["status"] == "CURRENT"

    def test_get_generations_for_selection(self, db):
        from tri9t.app.services.retrieval_service import (
            get_generations_for_selection,
        )

        with patch(
            "tri9t.app.services.retrieval_service.get_generations_collection",
        ) as mock_col:
            mock_col.return_value.count_documents.return_value = 2
            mock_col.return_value.find.return_value.sort.return_value.skip.return_value.limit.return_value = [
                {"_id": "g1"},
                {"_id": "g2"},
            ]
            result = get_generations_for_selection("s1")
            assert result["total"] == 2
            assert len(result["generations"]) == 2


# ===================================================================
# API Endpoints (mocked)
# ===================================================================


class TestNewEndpoints:
    def test_retrieve_generation_with_staleness(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app
        from tri9t.app.db.database import get_db

        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        test_db = TestSession()

        def override_db():
            yield test_db

        app.dependency_overrides[get_db] = override_db

        fake_doc = {
            "selection_id": "s1",
            "test_cases": [],
            "provider": "groq",
            "staleness": {
                "status": "CURRENT",
                "reason": "All nodes match",
            },
        }
        with patch(
            "tri9t.app.routers.generation.get_generation_with_staleness",
            return_value=fake_doc,
        ):
            client = TestClient(app)
            resp = client.get("/generation/g1")
            assert resp.status_code == 200
            assert "staleness" in resp.json()
            assert resp.json()["staleness"]["status"] == "CURRENT"

        app.dependency_overrides.clear()

    def test_node_generations_endpoint(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app

        fake_result = {"generations": [{"_id": "g1"}], "total": 1}
        with patch(
            "tri9t.app.routers.generation.get_generations_for_node",
            return_value=fake_result,
        ):
            client = TestClient(app)
            resp = client.get("/node/n1/generations")
            assert resp.status_code == 200
            assert resp.json()["total"] == 1

    def test_selection_generations_endpoint(self):
        from fastapi.testclient import TestClient
        from tri9t.app.main import app

        fake_result = {"generations": [{"_id": "g1"}, {"_id": "g2"}], "total": 2}
        with patch(
            "tri9t.app.routers.generation.get_generations_for_selection",
            return_value=fake_result,
        ):
            client = TestClient(app)
            resp = client.get("/selection/s1/generations")
            assert resp.status_code == 200
            assert resp.json()["total"] == 2


# ===================================================================
# Impact and Reason Builders
# ===================================================================


class TestHelperFunctions:
    def test_build_reason_no_changes(self):
        from tri9t.app.services.staleness_service import _build_reason
        reason = _build_reason([], 0, 5)
        assert "match" in reason.lower() or "all" in reason.lower()

    def test_build_reason_with_changes(self):
        from tri9t.app.services.staleness_service import _build_reason
        reason = _build_reason(["Section 1: Intro", "Section 2: Body"], 2, 5)
        assert "2/5" in reason
        assert "Section 1" in reason

    def test_build_reason_many_changes(self):
        from tri9t.app.services.staleness_service import _build_reason
        sections = [f"Section {i}" for i in range(10)]
        reason = _build_reason(sections, 10, 10)
        assert "5 more" in reason

    def test_build_recommendation_current(self):
        from tri9t.app.services.staleness_service import _build_recommendation
        rec = _build_recommendation(StalenessStatus.CURRENT, None)
        assert "no action" in rec.lower() or "current" in rec.lower()

    def test_build_recommendation_stale(self):
        from tri9t.app.services.staleness_service import _build_recommendation
        rec = _build_recommendation(StalenessStatus.STALE, "HIGH")
        assert "regenerate" in rec.lower()

    def test_build_recommendation_partial_critical(self):
        from tri9t.app.services.staleness_service import _build_recommendation
        rec = _build_recommendation(StalenessStatus.PARTIALLY_STALE, "CRITICAL")
        assert "regenerate" in rec.lower()

    def test_build_recommendation_unknown(self):
        from tri9t.app.services.staleness_service import _build_recommendation
        rec = _build_recommendation(StalenessStatus.UNKNOWN, None)
        assert "review" in rec.lower() or "manual" in rec.lower()

    def test_determine_impact_empty(self):
        from tri9t.app.services.staleness_service import _determine_impact
        result = _determine_impact([])
        assert result == "LOW"

    def test_determine_impact_with_changes(self):
        from tri9t.app.services.staleness_service import _determine_impact
        changes = [
            {"heading": "Safety Procedure", "change_type": "modified",
             "old_hash": "a", "new_hash": "b"},
        ]
        result = _determine_impact(changes)
        assert result in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
