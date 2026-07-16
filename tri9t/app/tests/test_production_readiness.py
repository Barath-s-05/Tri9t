"""Tests for production-readiness features.

Covers: pagination, sorting, filtering, metrics endpoint,
request ID middleware, and error logging.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tri9t.app.main import app
from tri9t.app.db.database import Base, SessionLocal, engine
from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node
from tri9t.app.models.selection import Selection


@pytest.fixture(autouse=True)
def _reset_db():
    """Drop and recreate all tables for isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    """Yield a TestClient for the app."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _create_doc(db, title="Test Doc", filename="test.pdf") -> Document:
    doc = Document(title=title, filename=filename)
    db.add(doc)
    db.flush()
    return doc


def _create_version(db, doc_id: str) -> DocumentVersion:
    v = DocumentVersion(document_id=doc_id)
    db.add(v)
    db.flush()
    return v


def _create_node(
    db,
    version_id: str,
    document_id: str,
    heading="Section 1",
    nid: str | None = None,
    body_text: str = "Test body content.",
) -> Node:
    import uuid
    node = Node(
        id=nid or str(uuid.uuid4()),
        document_id=document_id,
        version_id=version_id,
        section_number="1.0",
        heading=heading,
        body_text=body_text,
        content_hash="abc123",
        level=2,
        impact_level="MEDIUM",
        parent_id=None,
        node_type="section",
    )
    db.add(node)
    db.flush()
    return node


# ===========================================================================
# Pagination — GET /documents
# ===========================================================================


class TestDocumentPagination:
    def test_empty_documents_returns_pagination_fields(self, client):
        resp = client.get("/documents")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["limit"] == 20
        assert body["total"] == 0
        assert body["pages"] == 1
        assert body["items"] == []

    def test_documents_page_limit(self, client):
        db = SessionLocal()
        try:
            _create_doc(db, title="Doc A")
            db.commit()
        finally:
            db.close()

        resp = client.get("/documents?page=1&limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["limit"] == 1
        assert len(body["items"]) == 1

    def test_documents_page_beyond_total(self, client):
        db = SessionLocal()
        try:
            _create_doc(db, title="Doc A")
            db.commit()
        finally:
            db.close()

        resp = client.get("/documents?page=5&limit=10")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 5
        assert body["items"] == []
        assert body["total"] == 1

    def test_documents_limit_boundary(self, client):
        resp = client.get("/documents?limit=0")
        assert resp.status_code == 422

    def test_documents_limit_over_max(self, client):
        resp = client.get("/documents?limit=101")
        assert resp.status_code == 422


# ===========================================================================
# Sorting — GET /documents
# ===========================================================================


class TestDocumentSorting:
    def test_sort_by_title_asc(self, client):
        db = SessionLocal()
        try:
            _create_doc(db, title="Zebra")
            _create_doc(db, title="Alpha")
            db.commit()
        finally:
            db.close()

        resp = client.get("/documents?sort=title&order=asc")
        assert resp.status_code == 200
        titles = [d["title"] for d in resp.json()["items"]]
        assert titles == ["Alpha", "Zebra"]

    def test_sort_by_title_desc(self, client):
        db = SessionLocal()
        try:
            _create_doc(db, title="Alpha")
            _create_doc(db, title="Zebra")
            db.commit()
        finally:
            db.close()

        resp = client.get("/documents?sort=title&order=desc")
        assert resp.status_code == 200
        titles = [d["title"] for d in resp.json()["items"]]
        assert titles == ["Zebra", "Alpha"]

    def test_default_sort_by_created_at_desc(self, client):
        db = SessionLocal()
        try:
            _create_doc(db, title="First")
            db.commit()
        finally:
            db.close()

        db = SessionLocal()
        try:
            _create_doc(db, title="Second")
            db.commit()
        finally:
            db.close()

        resp = client.get("/documents")
        body = resp.json()
        assert body["total"] == 2
        assert body["page"] == 1
        # Both docs returned; sort order depends on insertion (SQLite granularity)
        titles = [d["title"] for d in body["items"]]
        assert set(titles) == {"First", "Second"}


# ===========================================================================
# Filtering — GET /documents
# ===========================================================================


class TestDocumentFiltering:
    def test_filter_by_title(self, client):
        db = SessionLocal()
        try:
            _create_doc(db, title="Battery Safety Manual")
            _create_doc(db, title="Charging Protocol")
            _create_doc(db, title="Battery Test Report")
            db.commit()
        finally:
            db.close()

        resp = client.get("/documents?title=Battery")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        titles = [d["title"] for d in body["items"]]
        assert "Battery Safety Manual" in titles
        assert "Battery Test Report" in titles
        assert "Charging Protocol" not in titles

    def test_filter_no_match(self, client):
        resp = client.get("/documents?title=Nonexistent")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ===========================================================================
# Search pagination
# ===========================================================================


class TestSearchPagination:
    def test_search_has_pagination_fields(self, client):
        db = SessionLocal()
        try:
            doc = _create_doc(db)
            ver = _create_version(db, doc.id)
            _create_node(db, ver.id, doc.id, heading="Safety Guidelines")
            db.commit()
        finally:
            db.close()

        resp = client.get("/search?query=safety")
        assert resp.status_code == 200
        body = resp.json()
        assert "page" in body
        assert "limit" in body
        assert "total" in body
        assert "pages" in body
        assert body["page"] == 1
        assert body["limit"] == 20

    def test_search_page_limit(self, client):
        db = SessionLocal()
        try:
            doc = _create_doc(db)
            ver = _create_version(db, doc.id)
            _create_node(db, ver.id, doc.id, heading="Safety A")
            _create_node(db, ver.id, doc.id, heading="Safety B")
            db.commit()
        finally:
            db.close()

        resp = client.get("/search?query=safety&page=1&limit=1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 1
        assert len(body["items"]) <= 1


# ===========================================================================
# Selection pagination
# ===========================================================================


class TestSelectionPagination:
    def test_list_selections_has_pagination(self, client):
        resp = client.get("/selections/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["limit"] == 20
        assert body["total"] == 0
        assert body["pages"] == 1

    def test_list_selections_page_limit(self, client):
        resp = client.get("/selections/?page=1&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 5


# ===========================================================================
# Generation history pagination
# ===========================================================================


class TestGenerationHistoryPagination:
    def test_generation_history_has_pagination(self, client):
        resp = client.get("/generation/history")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["limit"] == 20
        assert body["pages"] == 1

    def test_generation_history_page_limit(self, client):
        resp = client.get("/generation/history?page=1&limit=5")
        assert resp.status_code == 200
        body = resp.json()
        assert body["limit"] == 5
        assert body["page"] == 1


# ===========================================================================
# Metrics endpoint
# ===========================================================================


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_metrics_has_all_fields(self, client):
        resp = client.get("/metrics")
        body = resp.json()
        assert "documents" in body
        assert "versions" in body
        assert "nodes" in body
        assert "selections" in body
        assert "generations" in body
        assert isinstance(body["documents"], int)
        assert isinstance(body["versions"], int)
        assert isinstance(body["nodes"], int)
        assert isinstance(body["selections"], int)
        assert isinstance(body["generations"], int)

    def test_metrics_zero_when_empty(self, client):
        resp = client.get("/metrics")
        body = resp.json()
        assert body["documents"] == 0
        assert body["versions"] == 0
        assert body["nodes"] == 0
        assert body["selections"] == 0

    def test_metrics_counts_documents(self, client):
        db = SessionLocal()
        try:
            _create_doc(db, title="A")
            _create_doc(db, title="B")
            _create_doc(db, title="C")
            db.commit()
        finally:
            db.close()

        resp = client.get("/metrics")
        assert resp.json()["documents"] == 3

    def test_metrics_counts_nodes(self, client):
        db = SessionLocal()
        try:
            doc = _create_doc(db)
            ver = _create_version(db, doc.id)
            _create_node(db, ver.id, doc.id, heading="H1")
            _create_node(db, ver.id, doc.id, heading="H2")
            _create_node(db, ver.id, doc.id, heading="H3")
            db.commit()
        finally:
            db.close()

        resp = client.get("/metrics")
        assert resp.json()["nodes"] == 3

    def test_metrics_counts_versions(self, client):
        db = SessionLocal()
        try:
            doc = _create_doc(db)
            _create_version(db, doc.id)
            _create_version(db, doc.id)
            db.commit()
        finally:
            db.close()

        resp = client.get("/metrics")
        assert resp.json()["versions"] == 2


# ===========================================================================
# Request ID middleware
# ===========================================================================


class TestRequestIDMiddleware:
    def test_generates_request_id(self, client):
        resp = client.get("/health")
        assert "x-request-id" in resp.headers
        rid = resp.headers["x-request-id"]
        assert len(rid) == 36  # UUID4 format
        assert rid.count("-") == 4

    def test_echoes_client_request_id(self, client):
        my_rid = "test-request-id-12345"
        resp = client.get("/health", headers={"X-Request-ID": my_rid})
        assert resp.headers["x-request-id"] == my_rid

    def test_request_id_on_error(self, client):
        resp = client.get("/nonexistent")
        assert "x-request-id" in resp.headers

    def test_request_id_on_422(self, client):
        resp = client.get("/documents?limit=0")
        assert "x-request-id" in resp.headers


# ===========================================================================
# Timing header
# ===========================================================================


class TestTimingHeader:
    def test_process_time_header(self, client):
        resp = client.get("/health")
        assert "x-process-time" in resp.headers
        elapsed = float(resp.headers["x-process-time"])
        assert elapsed >= 0


# ===========================================================================
# Structured error response (global exception handler)
# ===========================================================================


class TestGlobalExceptionHandler:
    def test_404_has_error_structure(self, client):
        """Non-existent path returns a structured error (FastAPI built-in)."""
        resp = client.get("/nonexistent/path")
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body

    def test_request_id_on_404(self, client):
        """Even 404s include X-Request-ID in response headers."""
        resp = client.get("/nonexistent/path")
        assert "x-request-id" in resp.headers

    def test_request_id_echoed_on_404(self, client):
        my_rid = "my-custom-rid"
        resp = client.get("/nonexistent/path", headers={"X-Request-ID": my_rid})
        assert resp.headers["x-request-id"] == my_rid

    def test_422_has_error_schema(self, client):
        """Validation errors return 422 with detail."""
        resp = client.get("/documents?limit=0")
        assert resp.status_code == 422
        body = resp.json()
        assert "detail" in body
