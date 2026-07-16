"""Node SQLAlchemy model."""

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from tri9t.app.db.base import Base, TimestampMixin


class Node(Base, TimestampMixin):
    """Represents a node in a document's hierarchical tree."""

    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
