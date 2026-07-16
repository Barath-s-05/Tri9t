"""Node SQLAlchemy model."""

import uuid

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tri9t.app.db.base import Base, TimestampMixin


class Node(Base, TimestampMixin):
    """Represents a node in a document's hierarchical tree.

    Each node carries a ``logical_node_id`` that persists across document
    versions, enabling cross-version tracking of the same conceptual section.
    The ``version_id`` links the node to its specific document version.
    """

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    logical_node_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    heading: Mapped[str] = mapped_column(String(512), nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False, default="section")
