"""Database engine and session management."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tri9t.app.core.config import settings
from tri9t.app.db.base import Base

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables defined by SQLAlchemy models."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session.

    Yields:
        An SQLAlchemy Session object.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
