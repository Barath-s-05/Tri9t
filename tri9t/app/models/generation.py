"""GenerationRecord SQLAlchemy model."""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from tri9t.app.db.base import Base, TimestampMixin


class GenerationRecord(Base, TimestampMixin):
    """Tracks an LLM-generated output (test cases, etc.)."""

    __tablename__ = "generation_records"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    selection_id: Mapped[str] = mapped_column(String(36), nullable=False)
    generation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    output_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_stale: Mapped[bool] = mapped_column(nullable=False, default=False)
