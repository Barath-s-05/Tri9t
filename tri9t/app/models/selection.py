"""Selection SQLAlchemy model."""

import uuid

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tri9t.app.db.base import Base, TimestampMixin


class Selection(Base, TimestampMixin):
    """Represents a user's version-pinned node selection.

    A selection is a named, immutable snapshot of specific nodes within
    a single document version.  It never updates automatically once
    created.
    """

    __tablename__ = "selections"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    selection_name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    node_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
