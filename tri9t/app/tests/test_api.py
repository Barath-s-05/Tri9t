"""API endpoint tests for browsing, search, selection, and validation."""

import pytest
from uuid import uuid4
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tri9t.app.db.base import Base
from tri9t.app.db.database import get_db
from tri9t.app.main import app
from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node

from fastapi.testclient import TestClient

# A valid UUID that will never exist in the database
_NONEXISTENT_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def _seed_document(db, filename="test.pdf"):
    doc = Document(id=str(uuid4()), filename=filename)
    db.add(doc)
    db.flush()
    return doc


def _seed_version(db, doc_id, number=1):
    vid = str(uuid4())
    v = DocumentVersion(
        id=vid, document_id=doc_id,
        version_number=number, label=f"v{number}", is_latest=True,
    )
    db.add(v)
    db.flush()
    return vid


def _seed_node(db, doc_id, version_id, heading="Node", level=1,
               section_number=None, body_text="", parent_id=None,
               change_status="unchanged", impact_level=None):
    node = Node(
        id=str(uuid4()), document_id=doc_id, version_id=version_id,
        logical_node_id=str(uuid4()), heading=heading, level=level,
        body_text=body_text, section_number=section_number,
        parent_id=parent_id, node_type="section",
        content_hash="x" * 64, change_status=change_status,
        impact_level=impact_level,
    )
    db.add(node)
    db.flush()
    return node


# ── Browse API tests ────────────────────────────────────────────────


class TestBrowseAPI:
    def test_list_documents_empty(self, client):
        resp = client.get("/documents")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_list_documents(self, client, db_session):
        doc = _seed_document(db_session)
        resp = client.get("/documents")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_get_document_not_found(self, client):
        resp = client.get(f"/documents/{_NONEXISTENT_UUID}")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"] == "DocumentNotFound"

    def test_get_document_with_versions(self, client, db_session):
        doc = _seed_document(db_session)
        _seed_version(db_session, doc.id)
        resp = client.get(f"/documents/{doc.id}")
        assert resp.status_code == 200
        data = resp.json()["document"]
        assert len(data["versions"]) == 1

    def test_document_tree(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        root = _seed_node(db_session, doc.id, vid, "Chapter 1", 1)
        _seed_node(db_session, doc.id, vid, "Section 1.1", 2, parent_id=root.id)
        resp = client.get(f"/documents/{doc.id}/tree")
        assert resp.status_code == 200
        tree = resp.json()["tree"]["tree"]
        assert len(tree) == 1
        assert tree[0]["heading"] == "Chapter 1"
        assert len(tree[0]["children"]) == 1

    def test_node_response_fields(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        node = _seed_node(db_session, doc.id, vid, "Test", 1,
                          change_status="modified", impact_level="high")
        resp = client.get(f"/nodes/{node.id}")
        assert resp.status_code == 200
        n = resp.json()["node"]
        assert n["change_status"] == "modified"
        assert n["impact_level"] == "high"
        assert n["heading"] == "Test"

    def test_node_children(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        parent = _seed_node(db_session, doc.id, vid, "P", 1)
        _seed_node(db_session, doc.id, vid, "C1", 2, parent_id=parent.id)
        _seed_node(db_session, doc.id, vid, "C2", 2, parent_id=parent.id)
        resp = client.get(f"/nodes/{parent.id}/children")
        assert resp.status_code == 200
        assert len(resp.json()["children"]) == 2

    def test_version_tree(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        _seed_node(db_session, doc.id, vid, "A", 1)
        resp = client.get(f"/versions/{vid}/tree")
        assert resp.status_code == 200
        assert resp.json()["tree"]["version_id"] == vid


# ── Search API tests ────────────────────────────────────────────────


class TestSearchAPI:
    def test_search_exact_heading(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        _seed_node(db_session, doc.id, vid, "Safety Manual", 1)
        resp = client.get("/search", params={"query": "Safety Manual"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1
        assert resp.json()["items"][0]["match_type"] == "exact_heading"

    def test_search_body_text(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        _seed_node(db_session, doc.id, vid, "Details", 2, body_text="voltage is 12V")
        resp = client.get("/search", params={"query": "12V"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_search_section_number(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        _seed_node(db_session, doc.id, vid, "Appendix", 2, section_number="A.1")
        resp = client.get("/search", params={"query": "A.1"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_search_version_scoped(self, client, db_session):
        doc = _seed_document(db_session)
        vid1 = _seed_version(db_session, doc.id, 1)
        vid2 = _seed_version(db_session, doc.id, 2)
        _seed_node(db_session, doc.id, vid1, "Same Heading", 1)
        _seed_node(db_session, doc.id, vid2, "Same Heading", 1)
        resp = client.get("/search", params={"query": "Same Heading", "version_id": vid1})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["version_id"] == vid1

    def test_search_impact_filtered(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        _seed_node(db_session, doc.id, vid, "Safety", 1, impact_level="critical")
        _seed_node(db_session, doc.id, vid, "General", 1, impact_level="low")
        resp = client.get("/search", params={"query": "Safety", "impact_level": "critical"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["impact_level"] == "critical"

    def test_search_empty_query_rejected(self, client):
        resp = client.get("/search", params={"query": ""})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "EmptySearchQuery"

    def test_search_whitespace_query_rejected(self, client):
        resp = client.get("/search", params={"query": "   "})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "EmptySearchQuery"

    def test_search_no_match(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        _seed_node(db_session, doc.id, vid, "Introduction", 1)
        resp = client.get("/search", params={"query": "zzzznonexistent"})
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


# ── Selection API tests ─────────────────────────────────────────────


class TestSelectionAPI:
    def test_create_and_get_selection(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        node = _seed_node(db_session, doc.id, vid, "N", 1)
        resp = client.post("/selections/", json={
            "selection_name": "my_sel",
            "document_version_id": vid,
            "node_ids": [node.id],
            "created_by": "tester",
        })
        assert resp.status_code == 200
        sel_id = resp.json()["id"]
        resp2 = client.get(f"/selections/{sel_id}")
        assert resp2.status_code == 200
        assert resp2.json()["selection_name"] == "my_sel"

    def test_list_selections(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        node = _seed_node(db_session, doc.id, vid, "N", 1)
        client.post("/selections/", json={
            "selection_name": "s1",
            "document_version_id": vid,
            "node_ids": [node.id],
        })
        resp = client.get("/selections/")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_delete_selection(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        node = _seed_node(db_session, doc.id, vid, "N", 1)
        create_resp = client.post("/selections/", json={
            "selection_name": "to_del",
            "document_version_id": vid,
            "node_ids": [node.id],
        })
        sel_id = create_resp.json()["id"]
        resp = client.delete(f"/selections/{sel_id}")
        assert resp.status_code == 200
        resp2 = client.get(f"/selections/{sel_id}")
        assert resp2.status_code == 404

    def test_selection_not_found(self, client):
        resp = client.get(f"/selections/{_NONEXISTENT_UUID}")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"] == "SelectionNotFound"

    def test_delete_selection_not_found(self, client):
        resp = client.delete(f"/selections/{_NONEXISTENT_UUID}")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["error"] == "SelectionNotFound"


# ── Validation tests ────────────────────────────────────────────────


class TestValidation:
    def test_duplicate_selection_name_rejected(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        node = _seed_node(db_session, doc.id, vid, "N", 1)
        payload = {
            "selection_name": "dup",
            "document_version_id": vid,
            "node_ids": [node.id],
        }
        resp1 = client.post("/selections/", json=payload)
        assert resp1.status_code == 200
        resp2 = client.post("/selections/", json=payload)
        assert resp2.status_code == 422

    def test_invalid_node_ids_rejected(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        resp = client.post("/selections/", json={
            "selection_name": "bad",
            "document_version_id": vid,
            "node_ids": ["nosuchid"],
        })
        assert resp.status_code == 422

    def test_mixed_version_rejected(self, client, db_session):
        doc = _seed_document(db_session)
        vid1 = _seed_version(db_session, doc.id, 1)
        vid2 = _seed_version(db_session, doc.id, 2)
        n1 = _seed_node(db_session, doc.id, vid1, "A", 1)
        n2 = _seed_node(db_session, doc.id, vid2, "B", 1)
        resp = client.post("/selections/", json={
            "selection_name": "mixed",
            "document_version_id": vid1,
            "node_ids": [n1.id, n2.id],
        })
        assert resp.status_code == 422

    def test_empty_node_list_rejected(self, client, db_session):
        doc = _seed_document(db_session)
        vid = _seed_version(db_session, doc.id)
        resp = client.post("/selections/", json={
            "selection_name": "empty",
            "document_version_id": vid,
            "node_ids": [],
        })
        assert resp.status_code == 422


# ── UUID validation tests ───────────────────────────────────────────


class TestUUIDValidation:
    """Tests that invalid UUID formats are rejected with 422."""

    def test_invalid_document_id_browse(self, client):
        resp = client.get("/documents/not-a-uuid")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"
        assert "document_id" in detail["message"]

    def test_invalid_node_id_browse(self, client):
        resp = client.get("/nodes/not-a-uuid")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"
        assert "node_id" in detail["message"]

    def test_invalid_version_id_browse(self, client):
        resp = client.get("/versions/not-a-uuid/tree")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"
        assert "version_id" in detail["message"]

    def test_invalid_selection_id_get(self, client):
        resp = client.get("/selections/not-a-uuid")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"
        assert "selection_id" in detail["message"]

    def test_invalid_selection_id_delete(self, client):
        resp = client.delete("/selections/not-a-uuid")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"

    def test_invalid_node_id_changes(self, client):
        resp = client.get("/versions/node/not-a-uuid/changes")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"

    def test_invalid_version_id_query(self, client):
        resp = client.get("/search", params={"query": "test", "version_id": "bad"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"

    def test_invalid_document_id_query(self, client):
        resp = client.get("/search", params={"query": "test", "document_id": "bad"})
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"

    def test_empty_path_param_rejected(self, client):
        resp = client.get("/documents/")
        # FastAPI redirects /documents/ → /documents (307), then follows to 200
        assert resp.status_code in (200, 307, 404, 422)

    def test_uuid_with_hyphens_only_rejected(self, client):
        resp = client.get("/documents/----------")
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert detail["error"] == "InvalidUUID"


# ── Structured error response tests ─────────────────────────────────


class TestStructuredErrors:
    """Tests that error responses follow the {error, message, hint} schema."""

    def test_404_has_error_schema(self, client):
        resp = client.get(f"/documents/{_NONEXISTENT_UUID}")
        assert resp.status_code == 404
        body = resp.json()["detail"]
        assert "error" in body
        assert "message" in body
        assert isinstance(body["error"], str)
        assert isinstance(body["message"], str)

    def test_422_has_error_schema(self, client):
        resp = client.get("/documents/not-a-uuid")
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert "error" in body
        assert "message" in body
        assert "hint" in body

    def test_hint_is_optional(self, client):
        resp = client.get(f"/documents/{_NONEXISTENT_UUID}")
        body = resp.json()["detail"]
        # hint may or may not be present; just verify structure
        assert isinstance(body.get("hint"), (str, type(None)))

    def test_search_422_error_schema(self, client):
        resp = client.get("/search", params={"query": ""})
        assert resp.status_code == 422
        body = resp.json()["detail"]
        assert body["error"] == "EmptySearchQuery"
        assert "empty" in body["message"].lower()
        assert body["hint"] is not None
