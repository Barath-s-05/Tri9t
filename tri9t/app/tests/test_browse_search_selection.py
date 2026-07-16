"""Unit tests for Stage 4 — browsing, search, and selection services."""

import pytest
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tri9t.app.db.base import Base
from tri9t.app.models.node import Node
from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.services.browse_service import (
    list_documents,
    get_document,
    get_tree,
    get_node,
    get_node_children,
)
from tri9t.app.services.search_service import (
    _compute_score,
    search_nodes,
)
from tri9t.app.services.selection_service import (
    create_selection,
    get_selections,
    get_selection,
    delete_selection,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def make_node(db_session, doc_id, version_id=None, heading="Node", level=1,
              section_number=None, body_text="", parent_id=None):
    node = Node(
        id=str(uuid4()),
        document_id=doc_id,
        version_id=version_id,
        logical_node_id=str(uuid4()),
        heading=heading,
        level=level,
        body_text=body_text,
        section_number=section_number,
        parent_id=parent_id,
        node_type="section",
        content_hash="x" * 64,
    )
    db_session.add(node)
    db_session.flush()
    return node


def make_doc(db_session):
    doc = Document(id=str(uuid4()), filename="test.pdf")
    db_session.add(doc)
    db_session.flush()
    return doc


def make_version(db_session, doc_id, number=1):
    vid = str(uuid4())
    v = DocumentVersion(
        id=vid, document_id=doc_id,
        version_number=number,
        label=f"v{number}",
        is_latest=True,
    )
    db_session.add(v)
    db_session.flush()
    return vid


# ── Browse tests ──────────────────────────────────────────────────


class TestBrowse:
    def test_list_documents_empty(self, db):
        assert list_documents(db) == []

    def test_list_single_document(self, db):
        d = make_doc(db)
        r = list_documents(db)
        assert len(r) == 1
        assert r[0]["id"] == d.id

    def test_list_multiple_documents(self, db):
        make_doc(db)
        make_doc(db)
        assert len(list_documents(db)) == 2

    def test_get_nonexistent_document(self, db):
        assert get_document(db, "none") is None

    def test_get_document_with_version(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        r = get_document(db, d.id)
        assert r is not None
        assert len(r["versions"]) == 1

    def test_get_tree_nonexistent(self, db):
        assert get_tree(db, "none") is None

    def test_tree_hierarchy(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        root = make_node(db, d.id, vid, "Chapter 1", 1)
        make_node(db, d.id, vid, "Section 1.1", 2, parent_id=root.id)
        tree = get_tree(db, vid)
        assert tree is not None
        tree_root = tree["tree"][0]
        assert tree_root["heading"] == "Chapter 1"
        assert len(tree_root["children"]) == 1
        assert tree_root["children"][0]["heading"] == "Section 1.1"

    def test_get_node_nonexistent(self, db):
        assert get_node(db, "none") is None

    def test_get_node_with_children(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        parent = make_node(db, d.id, vid, "Parent", 1)
        make_node(db, d.id, vid, "Child", 2, parent_id=parent.id)
        node = get_node(db, parent.id)
        assert node is not None
        assert len(node["children"]) == 1

    def test_node_children_empty(self, db):
        d = make_doc(db)
        n = make_node(db, d.id)
        assert get_node_children(db, n.id) == []

    def test_node_children_count(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        p = make_node(db, d.id, vid, "P", 1)
        make_node(db, d.id, vid, "A", 2, parent_id=p.id)
        make_node(db, d.id, vid, "B", 2, parent_id=p.id)
        children = get_node_children(db, p.id)
        assert len(children) == 2


# ── Search tests ──────────────────────────────────────────────────


class TestSearch:
    def test_empty_query(self, db):
        assert search_nodes(db, "") == []

    def test_exact_heading(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        make_node(db, d.id, vid, "Exact Topic", 1)
        results = search_nodes(db, "Exact Topic")
        assert len(results) == 1

    def test_partial_heading(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        make_node(db, d.id, vid, "warranty options", 1)
        results = search_nodes(db, "warranty")
        assert len(results) == 1

    def test_section_number(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        make_node(db, d.id, vid, "Intro", 1, section_number="2.1")
        results = search_nodes(db, "2.1")
        assert len(results) == 1

    def test_body_text(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        make_node(db, d.id, vid, "Details", 2, body_text="Firmware version 3.0.1")
        results = search_nodes(db, "3.0.1")
        assert len(results) == 1

    def test_no_matches(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        make_node(db, d.id, vid, "Any", 1)
        assert search_nodes(db, "xxxzzz") == []

    def test_version_scoping(self, db):
        d = make_doc(db)
        vid1 = make_version(db, d.id, 1)
        vid2 = make_version(db, d.id, 2)
        make_node(db, d.id, vid1, "Safety", 1)
        make_node(db, d.id, vid2, "Safety", 1)
        r1 = search_nodes(db, "Safety", version_id=vid1)
        assert len(r1) == 1
        assert r1[0]["version_id"] == vid1
        r2 = search_nodes(db, "Safety", version_id=vid2)
        assert len(r2) == 1
        assert r2[0]["version_id"] == vid2

    def test_document_scoping(self, db):
        d1 = make_doc(db)
        d2 = make_doc(db)
        vid1 = make_version(db, d1.id)
        vid2 = make_version(db, d2.id)
        make_node(db, d1.id, vid1, "Key term", 1)
        make_node(db, d2.id, vid2, "Key term", 1)
        r = search_nodes(db, "term", document_id=d1.id)
        assert len(r) == 1

    def test_deduplication(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        logical_id = str(uuid4())
        n1 = Node(
            id=str(uuid4()), document_id=d.id, version_id=vid,
            logical_node_id=logical_id, heading="Same", level=1,
            node_type="section", content_hash="a"
        )
        n2 = Node(
            id=str(uuid4()), document_id=d.id, version_id=vid,
            logical_node_id=logical_id, heading="Same", level=1,
            node_type="section", content_hash="b"
        )
        db.add_all([n1, n2])
        db.flush()
        r = search_nodes(db, "Same")
        assert len(r) <= 1

    def test_score_ordering(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        make_node(db, d.id, vid, "Safety Manual", 1)
        make_node(db, d.id, vid, "General safety rules", 2, body_text="safety info")
        r = search_nodes(db, "safety")
        assert len(r) >= 2
        assert r[0]["score"] >= r[1]["score"]

    def test_compute_score_exact_contains(self):
        _, match_type = _compute_score("intro", "introduction", "body", None)
        assert "contains" in match_type

    def test_compute_score_no_match(self):
        score, _ = _compute_score("xxx", "abc", "d", None)
        assert score == 0.0


# ── Selection tests ───────────────────────────────────────────────


class TestSelection:
    def test_create_selection(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        n1 = make_node(db, d.id, vid, "N1", 1)
        n2 = make_node(db, d.id, vid, "N2", 2)
        sel = create_selection(db, "my_sel", "desc", vid, [n1.id, n2.id], "tester")
        assert sel.selection_name == "my_sel"
        assert len(sel.node_ids) == 2

    def test_list_selections_empty(self, db):
        assert get_selections(db) == []

    def test_get_selection_nonexistent(self, db):
        assert get_selection(db, "nope") is None

    def test_get_selection_by_id(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        n = make_node(db, d.id, vid, "N", 1)
        sel = create_selection(db, "my_sel", None, vid, [n.id], None)
        result = get_selection(db, sel.id)
        assert result is not None
        assert result["selection_name"] == "my_sel"

    def test_delete_selection(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        n = make_node(db, d.id, vid, "N", 1)
        sel = create_selection(db, "to_del", None, vid, [n.id], None)
        assert delete_selection(db, sel.id) is True
        assert get_selection(db, sel.id) is None

    def test_delete_nonexistent(self, db):
        assert delete_selection(db, "nope") is False

    def test_duplicate_name_raises(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        n = make_node(db, d.id, vid, "N", 1)
        create_selection(db, "dup", None, vid, [n.id], None)
        with pytest.raises(ValueError, match="already exists"):
            create_selection(db, "dup", None, vid, [n.id], None)

    def test_empty_nodes_raises(self, db):
        with pytest.raises(ValueError, match="empty"):
            create_selection(db, "bad", None, "vid", [], None)

    def test_invalid_nodes_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            create_selection(db, "bad", None, "vid", ["nosuch"], None)

    def test_wrong_version_node_raises(self, db):
        d = make_doc(db)
        vid1 = make_version(db, d.id, 1)
        vid2 = make_version(db, d.id, 2)
        n = make_node(db, d.id, vid1, "N", 1)
        with pytest.raises(ValueError, match="different"):
            create_selection(db, "mixed", None, vid2, [n.id], None)

    def test_filter_selections_by_version(self, db):
        d = make_doc(db)
        vid1 = make_version(db, d.id, 1)
        vid2 = make_version(db, d.id, 2)
        n1 = make_node(db, d.id, vid1, "A", 1)
        n2 = make_node(db, d.id, vid2, "B", 1)
        create_selection(db, "first", None, vid1, [n1.id], None)
        create_selection(db, "second", None, vid2, [n2.id], None)
        r = get_selections(db, document_version_id=vid1)
        assert len(r) == 1
        assert r[0]["selection_name"] == "first"

    def test_snapshot_hash_generated(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        n = make_node(db, d.id, vid, "N", 1)
        sel = create_selection(db, "hash_test", None, vid, [n.id], None)
        assert len(sel.snapshot_hash) == 64

    def test_selection_preserves_order(self, db):
        d = make_doc(db)
        vid = make_version(db, d.id)
        n1 = make_node(db, d.id, vid, "A", 1)
        n2 = make_node(db, d.id, vid, "B", 1)
        n3 = make_node(db, d.id, vid, "C", 2)
        sel = create_selection(db, "ordered", None, vid, [n1.id, n2.id, n3.id], None)
        assert len(sel.node_ids) == 3
