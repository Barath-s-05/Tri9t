"""Document persistence and retrieval service."""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.orm import Session

from tri9t.app.models.document import Document, DocumentVersion
from tri9t.app.models.node import Node
from tri9t.app.schemas.parser import ParsedNode, ParserReport

logger = logging.getLogger(__name__)


def save_document(
    db: Session,
    filename: str,
    nodes: list[ParsedNode],
    report: ParserReport,
) -> tuple[str, int]:
    """Persist a parsed document and its tree nodes to the database.

    Creates a Document record, a DocumentVersion (v1), and all Node
    records with parent relationships and content hashes.

    Args:
        db: Active SQLAlchemy session.
        filename: Original PDF filename.
        nodes: Fully built list of ParsedNode objects.
        report: Parser report to store metadata on the document.

    Returns:
        Tuple of (document_id, node_count).
    """
    doc_id = str(uuid4())
    version_id = str(uuid4())

    document = Document(
        id=doc_id,
        filename=filename,
        title=nodes[0].heading if nodes else filename,
    )
    db.add(document)

    version = DocumentVersion(
        id=version_id,
        document_id=doc_id,
        version_number=1,
        label="initial",
    )
    db.add(version)

    node_count = 0
    for parsed_node in nodes:
        db_node = Node(
            id=parsed_node.id,
            document_id=doc_id,
            parent_id=parsed_node.parent_id,
            heading=parsed_node.heading,
            level=parsed_node.level,
            body_text=parsed_node.body_text,
            page_number=parsed_node.page_number,
            section_number=parsed_node.section_number,
            content_hash=parsed_node.content_hash,
            node_type=parsed_node.node_type,
        )
        db.add(db_node)
        node_count += 1

    db.commit()
    logger.info("Saved document %s with %d nodes", doc_id, node_count)
    return doc_id, node_count
