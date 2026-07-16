"""Selection SQLAlchemy model."""

import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from tri9t.app.db.base import Base, TimestampMixin


class Selection(Base, TimestampMixin):
    """Represents a user's version-pinned node selection."""

    __tablename__ = "selections"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    document_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    node_id: Mapped[str] = mapped_column(String(36), nullable=False)
    selected_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
